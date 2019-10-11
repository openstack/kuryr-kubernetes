# Copyright (c) 2016 Mirantis, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from neutronclient.common import exceptions as n_exc
from oslo_cache import core as cache
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import objects
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


vif_handler_caching_opts = [
    oslo_cfg.BoolOpt('caching', default=True),
    oslo_cfg.IntOpt('cache_time', default=120),
]

oslo_cfg.CONF.register_opts(vif_handler_caching_opts,
                            "vif_handler_caching")

cache.configure(oslo_cfg.CONF)
vif_handler_cache_region = cache.create_region()
MEMOIZE = cache.get_memoization_decorator(
    oslo_cfg.CONF, vif_handler_cache_region, "vif_handler_caching")

cache.configure_cache_region(oslo_cfg.CONF, vif_handler_cache_region)


class VIFHandler(k8s_base.ResourceEventHandler):
    """Controller side of VIF binding process for Kubernetes pods.

    `VIFHandler` runs on the Kuryr-Kubernetes controller and together with
    the CNI driver (that runs on 'kubelet' nodes) is responsible for providing
    networking to Kubernetes pods. `VIFHandler` relies on a set of drivers
    (which are responsible for managing Neutron resources) to define the VIF
    objects and pass them to the CNI driver in form of the Kubernetes pod
    annotation.
    """

    OBJECT_KIND = constants.K8S_OBJ_POD
    OBJECT_WATCH_PATH = "%s/%s" % (constants.K8S_API_BASE, "pods")

    def __init__(self):
        super(VIFHandler, self).__init__()
        self._drv_project = drivers.PodProjectDriver.get_instance()
        self._drv_subnets = drivers.PodSubnetsDriver.get_instance()
        self._drv_sg = drivers.PodSecurityGroupsDriver.get_instance()
        # REVISIT(ltomasbo): The VIF Handler should not be aware of the pool
        # directly. Due to the lack of a mechanism to load and set the
        # VIFHandler driver, for now it is aware of the pool driver, but this
        # will be reverted as soon as a mechanism is in place.
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            specific_driver='multi_pool')
        self._drv_vif_pool.set_vif_driver()
        self._drv_multi_vif = drivers.MultiVIFDriver.get_enabled_drivers()
        if self._is_network_policy_enabled():
            self._drv_lbaas = drivers.LBaaSDriver.get_instance()
            self._drv_svc_sg = (
                drivers.ServiceSecurityGroupsDriver.get_instance())

    def on_present(self, pod):
        if (driver_utils.is_host_network(pod) or
                not self._is_pod_scheduled(pod)):
            # REVISIT(ivc): consider an additional configurable check that
            # would allow skipping pods to enable heterogeneous environments
            # where certain pods/namespaces/nodes can be managed by other
            # networking solutions/CNI drivers.
            return
        state = driver_utils.get_pod_state(pod)
        LOG.debug("Got VIFs from annotation: %r", state)
        project_id = self._drv_project.get_project(pod)
        security_groups = self._drv_sg.get_security_groups(pod, project_id)
        if not state:
            try:
                subnets = self._drv_subnets.get_subnets(pod, project_id)
            except (n_exc.NotFound, k_exc.K8sResourceNotFound):
                LOG.warning("Subnet does not exists. If namespace driver is "
                            "used, probably the namespace for the pod is "
                            "already deleted. So this pod does not need to "
                            "get a port as it will be deleted too. If the "
                            "default subnet driver is used, then you must "
                            "select an existing subnet to be used by Kuryr.")
                return
            # Request the default interface of pod
            main_vif = self._drv_vif_pool.request_vif(
                pod, project_id, subnets, security_groups)

            if not main_vif:
                pod_name = pod['metadata']['name']
                LOG.warning("Ignoring event due to pod %s not being "
                            "scheduled yet.", pod_name)
                return

            state = objects.vif.PodState(default_vif=main_vif)

            # Request the additional interfaces from multiple dirvers
            additional_vifs = []
            for driver in self._drv_multi_vif:
                additional_vifs.extend(
                    driver.request_additional_vifs(
                        pod, project_id, security_groups))
            if additional_vifs:
                state.additional_vifs = {}
                for i, vif in enumerate(additional_vifs, start=1):
                    k = constants.ADDITIONAL_IFNAME_PREFIX + str(i)
                    state.additional_vifs[k] = vif

            try:
                self._set_pod_state(pod, state)
            except k_exc.K8sClientException as ex:
                LOG.debug("Failed to set annotation: %s", ex)
                # FIXME(ivc): improve granularity of K8sClient exceptions:
                # only resourceVersion conflict should be ignored
                for ifname, vif in state.vifs.items():
                    self._drv_vif_pool.release_vif(pod, vif,
                                                   project_id,
                                                   security_groups)
        else:
            changed = False
            try:
                for ifname, vif in state.vifs.items():
                    if vif.plugin == constants.KURYR_VIF_TYPE_SRIOV:
                        driver_utils.update_port_pci_info(pod, vif)
                    if not vif.active:
                        try:
                            self._drv_vif_pool.activate_vif(pod, vif)
                            changed = True
                        except n_exc.PortNotFoundClient:
                            LOG.debug("Port not found, possibly already "
                                      "deleted. No need to activate it")
            finally:
                if changed:
                    try:
                        self._set_pod_state(pod, state)
                    except k_exc.K8sResourceNotFound as ex:
                        LOG.exception("Failed to set annotation: %s", ex)
                        for ifname, vif in state.vifs.items():
                            self._drv_vif_pool.release_vif(
                                pod, vif, project_id,
                                security_groups)
                    except k_exc.K8sClientException:
                        pod_name = pod['metadata']['name']
                        raise k_exc.ResourceNotReady(pod_name)
                    if self._is_network_policy_enabled():
                        crd_pod_selectors = self._drv_sg.create_sg_rules(pod)
                        if oslo_cfg.CONF.octavia_defaults.enforce_sg_rules:
                            services = driver_utils.get_services()
                            self._update_services(
                                services, crd_pod_selectors, project_id)

    def on_deleted(self, pod):
        if (driver_utils.is_host_network(pod) or
                not pod['spec'].get('nodeName')):
            return

        project_id = self._drv_project.get_project(pod)
        try:
            crd_pod_selectors = self._drv_sg.delete_sg_rules(pod)
        except k_exc.ResourceNotReady:
            # NOTE(ltomasbo): If the pod is being deleted before
            # kuryr-controller annotated any information about the port
            # associated, there is no need for deleting sg rules associated to
            # it. So this exception could be safetly ignored for the current
            # sg drivers. Only the NP driver associates rules to the pods ips,
            # and that waits for annotations to start.
            LOG.debug("Pod was not yet annotated by Kuryr-controller. "
                      "Skipping SG rules deletion associated to the pod %s",
                      pod)
            crd_pod_selectors = []
        try:
            security_groups = self._drv_sg.get_security_groups(pod, project_id)
        except k_exc.ResourceNotReady:
            # NOTE(ltomasbo): If the namespace object gets deleted first the
            # namespace security group driver will raise a ResourceNotReady
            # exception as it cannot access anymore the kuryrnet CRD annotated
            # on the namespace object. In such case we set security groups to
            # empty list so that if pools are enabled they will be properly
            # released.
            security_groups = []

        state = driver_utils.get_pod_state(pod)
        LOG.debug("Got VIFs from annotation: %r", state)
        if state:
            for ifname, vif in state.vifs.items():
                self._drv_vif_pool.release_vif(pod, vif, project_id,
                                               security_groups)
        if (self._is_network_policy_enabled() and crd_pod_selectors and
                oslo_cfg.CONF.octavia_defaults.enforce_sg_rules):
            services = driver_utils.get_services()
            self._update_services(services, crd_pod_selectors, project_id)

    @MEMOIZE
    def is_ready(self, quota):
        neutron = clients.get_neutron_client()
        port_quota = quota['port']
        port_func = neutron.list_ports
        if utils.has_limit(port_quota):
            return utils.is_available('ports', port_quota, port_func)
        return True

    @staticmethod
    def _is_pod_scheduled(pod):
        """Checks if Pod is in PENDING status and has node assigned."""
        try:
            return (pod['spec']['nodeName'] and
                    pod['status']['phase'] == constants.K8S_POD_STATUS_PENDING)
        except KeyError:
            return False

    def _set_pod_state(self, pod, state):
        # TODO(ivc): extract annotation interactions
        if not state:
            LOG.debug("Removing VIFs annotation: %r for pod %s/%s (uid: %s)",
                      state, pod['metadata']['namespace'],
                      pod['metadata']['name'], pod['metadata']['uid'])
            annotation = None
        else:
            state_dict = state.obj_to_primitive()
            annotation = jsonutils.dumps(state_dict, sort_keys=True)
            LOG.debug("Setting VIFs annotation: %r for pod %s/%s (uid: %s)",
                      annotation, pod['metadata']['namespace'],
                      pod['metadata']['name'], pod['metadata']['uid'])

        labels = pod['metadata'].get('labels')
        if not labels:
            LOG.debug("Removing Label annotation: %r", labels)
            labels_annotation = None
        else:
            labels_annotation = jsonutils.dumps(labels, sort_keys=True)
            LOG.debug("Setting Labels annotation: %r", labels_annotation)

        # NOTE(dulek): We don't care about compatibility with Queens format
        #              here, as eventually all Kuryr services will be upgraded
        #              and cluster will start working normally. Meanwhile
        #              we just ignore issue of old services being unable to
        #              read new annotations.

        k8s = clients.get_kubernetes_client()
        k8s.annotate(pod['metadata']['selfLink'],
                     {constants.K8S_ANNOTATION_VIF: annotation,
                      constants.K8S_ANNOTATION_LABEL: labels_annotation},
                     resource_version=pod['metadata']['resourceVersion'])

    def _update_services(self, services, crd_pod_selectors, project_id):
        for service in services.get('items'):
            if not driver_utils.service_matches_affected_pods(
                    service, crd_pod_selectors):
                continue
            sgs = self._drv_svc_sg.get_security_groups(service,
                                                       project_id)
            self._drv_lbaas.update_lbaas_sg(service, sgs)

    def _is_network_policy_enabled(self):
        enabled_handlers = oslo_cfg.CONF.kubernetes.enabled_handlers
        svc_sg_driver = oslo_cfg.CONF.kubernetes.service_security_groups_driver
        return ('policy' in enabled_handlers and svc_sg_driver == 'policy')
