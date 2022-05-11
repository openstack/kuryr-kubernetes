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
import uuid

from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

CONF = cfg.CONF
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
        super(VIFHandler).__init__()
        self.k8s = clients.get_kubernetes_client()

    def on_present(self, pod, *args, **kwargs):
        if utils.is_host_network(pod):
            return

        pod_name = pod['metadata']['name']
        if utils.is_pod_completed(pod):
            LOG.debug("Pod %s has completed execution, "
                      "removing the vifs", pod_name)
            self.on_finalize(pod)
            return

        if not self._is_pod_scheduled(pod):
            # REVISIT(ivc): consider an additional configurable check that
            # would allow skipping pods to enable heterogeneous environments
            # where certain pods/namespaces/nodes can be managed by other
            # networking solutions/CNI drivers.
            return

        namespace = pod['metadata']['namespace']
        kuryrnetwork_path = '{}/{}/kuryrnetworks/{}'.format(
            constants.K8S_API_CRD_NAMESPACES, namespace,
            namespace)
        kuryrnetwork = driver_utils.get_k8s_resource(kuryrnetwork_path)
        kuryrnetwork_status = kuryrnetwork.get('status', {})
        if (CONF.kubernetes.pod_subnets_driver == 'namespace' and
                (not kuryrnetwork or not kuryrnetwork_status.get('routerId'))):
            namespace_path = '{}/{}'.format(
                constants.K8S_API_NAMESPACES, namespace)
            LOG.debug("Triggering Namespace Handling %s", namespace_path)
            try:
                self.k8s.annotate(namespace_path,
                                  {'KuryrTrigger': str(uuid.uuid4())})
            except k_exc.K8sResourceNotFound:
                LOG.warning('Ignoring Pod handling, no Namespace %s.',
                            namespace)
                return
            raise k_exc.ResourceNotReady(pod)

        # NOTE(gryf): Set the finalizer as soon, as we have pod created. On
        # subsequent updates of the pod, add_finalizer will ignore this if
        # finalizer exist.
        try:
            if not self.k8s.add_finalizer(pod, constants.POD_FINALIZER):
                # NOTE(gryf) It might happen that pod will be deleted even
                # before we got here.
                return
        except k_exc.K8sClientException as ex:
            self.k8s.add_event(pod, 'FailedToAddFinalizerToPod',
                               f'Adding finalizer to pod has failed: {ex}',
                               'Warning')
            LOG.exception("Failed to add finalizer to pod object: %s", ex)
            raise

        kp = driver_utils.get_kuryrport(pod)
        LOG.debug("Got KuryrPort: %r", kp)
        if not kp:
            try:
                self._add_kuryrport_crd(pod)
            except k_exc.K8sNamespaceTerminating:
                # The underlying namespace is being terminated, we can
                # ignore this and let `on_finalize` handle this now.
                LOG.debug('Namespace %s is being terminated, ignoring Pod '
                          '%s in that namespace.',
                          pod['metadata']['namespace'], pod_name)
                return
            except k_exc.K8sClientException as ex:
                self.k8s.add_event(pod, 'FailedToCreateKuryrPortCRD',
                                   f'Creating corresponding KuryrPort CRD has '
                                   f'failed: {ex}', 'Warning')
                LOG.exception("Kubernetes Client Exception creating "
                              "KuryrPort CRD: %s", ex)
                raise k_exc.ResourceNotReady(pod)

    def on_finalize(self, pod, *args, **kwargs):

        try:
            kp = self.k8s.get(KURYRPORT_URI.format(
                ns=pod["metadata"]["namespace"], crd=pod["metadata"]["name"]))
        except k_exc.K8sResourceNotFound:
            try:
                self.k8s.remove_finalizer(pod, constants.POD_FINALIZER)
            except k_exc.K8sClientException as ex:
                self.k8s.add_event(pod, 'FailedRemovingFinalizerFromPod',
                                   f'Removing finalizer from pod has failed: '
                                   f'{ex}', 'Warning')
                LOG.exception('Failed to remove finalizer from pod: %s', ex)
                raise
            return

        if 'deletionTimestamp' in kp['metadata']:
            # NOTE(gryf): Seems like KP was manually removed. By using
            # annotations, force an emition of event to trigger on_finalize
            # method on the KuryrPort.
            try:
                self.k8s.annotate(utils.get_res_link(kp),
                                  {'KuryrTrigger': str(uuid.uuid4())})
            except k_exc.K8sResourceNotFound:
                self.k8s.remove_finalizer(pod, constants.POD_FINALIZER)
            except k_exc.K8sClientException as ex:
                self.k8s.add_event(pod, 'FailedRemovingPodFinalzier',
                                   f'Failed removing finalizer from pod: {ex}',
                                   'Warning')
                raise k_exc.ResourceNotReady(pod['metadata']['name'])
        else:
            try:
                self.k8s.delete(KURYRPORT_URI
                                .format(ns=pod["metadata"]["namespace"],
                                        crd=pod["metadata"]["name"]))
            except k_exc.K8sResourceNotFound:
                self.k8s.remove_finalizer(pod, constants.POD_FINALIZER)

            except k_exc.K8sClientException as ex:
                self.k8s.add_event(pod, 'FailedRemovingKuryrPortCRD',
                                   f'Failed removing corresponding KuryrPort '
                                   f'CRD: {ex}', 'Warning')
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

    def _add_kuryrport_crd(self, pod):
        LOG.debug('Adding CRD %s', pod["metadata"]["name"])

        vifs = {}

        owner_reference = {'apiVersion': pod['apiVersion'],
                           'kind': pod['kind'],
                           'name': pod['metadata']['name'],
                           'uid': pod['metadata']['uid']}

        kuryr_port = {
            'apiVersion': constants.K8S_API_CRD_VERSION,
            'kind': constants.K8S_OBJ_KURYRPORT,
            'metadata': {
                'name': pod['metadata']['name'],
                'finalizers': [constants.KURYRPORT_FINALIZER],
                'labels': {
                    constants.KURYRPORT_LABEL: pod['spec']['nodeName']
                },
                'ownerReferences': [owner_reference]
            },
            'spec': {
                'podUid': pod['metadata']['uid'],
                'podNodeName': pod['spec']['nodeName'],
                'podStatic': utils.is_pod_static(pod)
            },
            'status': {
                'vifs': vifs
            }
        }

        self.k8s.post(KURYRPORT_URI.format(ns=pod["metadata"]["namespace"],
                                           crd=''), kuryr_port)
