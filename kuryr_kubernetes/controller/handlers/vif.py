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

from os_vif import objects
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)
KURYRPORT_URI = constants.K8S_API_CRD_NAMESPACES + '/{ns}/kuryrports/{crd}'


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

        # NOTE(gryf): Set the finalizer as soon, as we have pod created. On
        # subsequent updates of the pod, add_finalizer will ignore this if
        # finalizer exists.
        k8s = clients.get_kubernetes_client()

        try:
            if not k8s.add_finalizer(pod, constants.POD_FINALIZER):
                # NOTE(gryf) It might happen that pod will be deleted even
                # before we got here.
                return
        except k_exc.K8sClientException as ex:
            LOG.exception("Failed to add finalizer to pod object: %s", ex)
            raise

        if self._move_annotations_to_crd(pod):
            return

        kp = driver_utils.get_kuryrport(pod)
        if self._is_pod_completed(pod):
            if kp:
                LOG.debug("Pod has completed execution, removing the vifs")
                self.on_finalize(pod)
            else:
                LOG.debug("Pod has completed execution, no KuryrPort found."
                          " Skipping")
            return

        LOG.debug("Got KuryrPort: %r", kp)
        if not kp:
            try:
                self._add_kuryrport_crd(pod)
            except k_exc.K8sNamespaceTerminating:
                # The underlying namespace is being terminated, we can
                # ignore this and let `on_finalize` handle this now.
                LOG.warning('Namespace %s is being terminated, ignoring Pod '
                            '%s in that namespace.',
                            pod['metadata']['namespace'],
                            pod['metadata']['name'])
                return
            except k_exc.K8sClientException as ex:
                LOG.exception("Kubernetes Client Exception creating "
                              "KuryrPort CRD: %s", ex)
                raise k_exc.ResourceNotReady(pod)

    def on_finalize(self, pod):
        k8s = clients.get_kubernetes_client()

        try:
            kp = k8s.get(KURYRPORT_URI.format(ns=pod["metadata"]["namespace"],
                                              crd=pod["metadata"]["name"]))
        except k_exc.K8sResourceNotFound:
            try:
                k8s.remove_finalizer(pod, constants.POD_FINALIZER)
            except k_exc.K8sClientException as ex:
                LOG.exception('Failed to remove finalizer from pod: %s', ex)
                raise
            return

        if 'deletionTimestamp' in kp['metadata']:
            # NOTE(gryf): Seems like KP was manually removed. By using
            # annotations, force an emition of event to trigger on_finalize
            # method on the KuryrPort.
            try:
                k8s.annotate(kp['metadata']['selfLink'], {'KuryrTrigger': '1'})
            except k_exc.K8sResourceNotFound:
                LOG.error('Cannot annotate existing KuryrPort %s.',
                          kp['metadata']['name'])
                k8s.remove_finalizer(pod, constants.POD_FINALIZER)
            except k_exc.K8sClientException:
                raise k_exc.ResourceNotReady(pod['metadata']['name'])
        else:
            try:
                k8s.delete(KURYRPORT_URI
                           .format(ns=pod["metadata"]["namespace"],
                                   crd=pod["metadata"]["name"]))
            except k_exc.K8sResourceNotFound:
                k8s.remove_finalizer(pod, constants.POD_FINALIZER)

            except k_exc.K8sClientException:
                LOG.exception("Could not remove KuryrPort CRD for pod %s.",
                              pod['metadata']['name'])
                raise k_exc.ResourceNotReady(pod['metadata']['name'])

    def is_ready(self, quota):
        if (utils.has_limit(quota.ports) and
                not utils.is_available('ports', quota.ports)):
            LOG.error('Marking VIFHandler as not ready.')
            return False
        return True

    @staticmethod
    def _is_pod_scheduled(pod):
        """Checks if Pod is in PENDING status and has node assigned."""
        try:
            return (pod['spec']['nodeName'] and
                    pod['status']['phase'] == constants.K8S_POD_STATUS_PENDING)
        except KeyError:
            return False

    @staticmethod
    def _is_pod_completed(pod):
        try:
            return (pod['status']['phase'] in
                    (constants.K8S_POD_STATUS_SUCCEEDED,
                     constants.K8S_POD_STATUS_FAILED))
        except KeyError:
            return False

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

    def _add_kuryrport_crd(self, pod, vifs=None):
        LOG.debug('Adding CRD %s', pod["metadata"]["name"])

        if not vifs:
            vifs = {}

        kuryr_port = {
            'apiVersion': constants.K8S_API_CRD_VERSION,
            'kind': constants.K8S_OBJ_KURYRPORT,
            'metadata': {
                'name': pod['metadata']['name'],
                'finalizers': [constants.KURYRPORT_FINALIZER],
                'labels': {
                    constants.KURYRPORT_LABEL: pod['spec']['nodeName']
                }
            },
            'spec': {
                'podUid': pod['metadata']['uid'],
                'podNodeName': pod['spec']['nodeName']
            },
            'status': {
                'vifs': vifs
            }
        }

        k8s = clients.get_kubernetes_client()
        k8s.post(KURYRPORT_URI.format(ns=pod["metadata"]["namespace"],
                                      crd=''), kuryr_port)

    def _move_annotations_to_crd(self, pod):
        """Support upgrade from annotations to KuryrPort CRD."""
        try:
            state = (pod['metadata']['annotations']
                     [constants.K8S_ANNOTATION_VIF])
        except KeyError:
            return False

        _dict = jsonutils.loads(state)
        state = objects.base.VersionedObject.obj_from_primitive(_dict)

        vifs = {ifname: {'default': state.default_vif == vif,
                         'vif': objects.base.VersionedObject
                         .obj_to_primitive(vif)}
                for ifname, vif in state.vifs.items()}

        try:
            self._add_kuryrport_crd(pod, vifs)
        except k_exc.K8sNamespaceTerminating:
            # The underlying namespace is being terminated, we can
            # ignore this and let `on_finalize` handle this now. Still
            # returning True to make sure `on_present` won't continue.
            return True
        except k_exc.K8sClientException as ex:
            LOG.exception("Kubernetes Client Exception recreating "
                          "KuryrPort CRD from annotation: %s", ex)
            raise k_exc.ResourceNotReady(pod)

        k8s = clients.get_kubernetes_client()
        k8s.remove_annotations(pod['metadata']['selfLink'],
                               constants.K8S_ANNOTATION_VIF)

        return True
