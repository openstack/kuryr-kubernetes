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

    def on_present(self, pod):
        if driver_utils.is_host_network(pod) or not self._is_pending_node(pod):
            # REVISIT(ivc): consider an additional configurable check that
            # would allow skipping pods to enable heterogeneous environments
            # where certain pods/namespaces/nodes can be managed by other
            # networking solutions/CNI drivers.
            return
        state = driver_utils.get_pod_state(pod)
        LOG.debug("Got VIFs from annotation: %r", state)

        if not state:
            project_id = self._drv_project.get_project(pod)
            security_groups = self._drv_sg.get_security_groups(pod, project_id)
            subnets = self._drv_subnets.get_subnets(pod, project_id)

            # Request the default interface of pod
            main_vif = self._drv_vif_pool.request_vif(
                pod, project_id, subnets, security_groups)

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
            for ifname, vif in state.vifs.items():
                if not vif.active:
                    self._drv_vif_pool.activate_vif(pod, vif)
                    changed = True
            if changed:
                self._set_pod_state(pod, state)

    def on_deleted(self, pod):
        if driver_utils.is_host_network(pod):
            return
        project_id = self._drv_project.get_project(pod)
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

    @MEMOIZE
    def is_ready(self, quota):
        neutron = clients.get_neutron_client()
        port_quota = quota['port']
        port_func = neutron.list_ports
        if utils.has_limit(port_quota):
            return utils.is_available('ports', port_quota, port_func)
        return True

    @staticmethod
    def _is_pending_node(pod):
        """Checks if Pod is in PENDGING status and has node assigned."""
        try:
            return (pod['spec']['nodeName'] and
                    pod['status']['phase'] == constants.K8S_POD_STATUS_PENDING)
        except KeyError:
            return False

    def _set_pod_state(self, pod, state):
        # TODO(ivc): extract annotation interactions
        if not state:
            LOG.debug("Removing VIFs annotation: %r", state)
            annotation = None
        else:
            state_dict = state.obj_to_primitive()
            annotation = jsonutils.dumps(state_dict, sort_keys=True)
            LOG.debug("Setting VIFs annotation: %r", annotation)

        # NOTE(dulek): We don't care about compatibility with Queens format
        #              here, as eventually all Kuryr services will be upgraded
        #              and cluster will start working normally. Meanwhile
        #              we just ignore issue of old services being unable to
        #              read new annotations.

        k8s = clients.get_kubernetes_client()
        k8s.annotate(pod['metadata']['selfLink'],
                     {constants.K8S_ANNOTATION_VIF: annotation},
                     resource_version=pod['metadata']['resourceVersion'])
