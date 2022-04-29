# Copyright 2018 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils


LOG = logging.getLogger(__name__)


class NamespaceHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = constants.K8S_OBJ_NAMESPACE
    OBJECT_WATCH_PATH = constants.K8S_API_NAMESPACES

    def __init__(self):
        super(NamespaceHandler, self).__init__()
        self._drv_project = drivers.NamespaceProjectDriver.get_instance()

    def on_present(self, namespace, *args, **kwargs):
        ns_labels = namespace['metadata'].get('labels', {})
        ns_name = namespace['metadata']['name']

        kns_crd = self._get_kns_crd(ns_name)
        if kns_crd:
            LOG.debug("Previous CRD existing at the new namespace.")
            self._update_labels(kns_crd, ns_labels)
            return

        if not self._handle_namespace(ns_name):
            LOG.debug("Namespace %s has no Pods that should be handled. "
                      "Skipping event.", ns_name)
            return

        try:
            self._add_kuryrnetwork_crd(namespace, ns_labels)
        except exceptions.K8sClientException:
            LOG.exception("Kuryrnetwork CRD creation failed.")
            raise exceptions.ResourceNotReady(namespace)

    def _handle_namespace(self, namespace):
        """Evaluate if the Namespace should be handled

        Fetches all the Pods in the Namespace and check
        if there is any Pod in that Namespace on Pods Network.

        :param namespace: Namespace name
        :returns: True if the Namespace resources should be
                  created, False if otherwise.
        """
        kubernetes = clients.get_kubernetes_client()
        pods = kubernetes.get(
                '{}/namespaces/{}/pods'.format(
                    constants.K8S_API_BASE, namespace))
        return any(not utils.is_host_network(pod)
                   for pod in pods.get('items', []))

    def _update_labels(self, kns_crd, ns_labels):
        kns_status = kns_crd.get('status')
        if kns_status:
            kns_crd_labels = kns_crd['status'].get('nsLabels', {})
            if kns_crd_labels == ns_labels:
                # Labels are already up to date, nothing to do
                return

        kubernetes = clients.get_kubernetes_client()
        LOG.debug('Patching KuryrNetwork CRD %s', kns_crd)
        try:
            kubernetes.patch_crd('spec', utils.get_res_link(kns_crd),
                                 {'nsLabels': ns_labels})
        except exceptions.K8sResourceNotFound:
            LOG.debug('KuryrNetwork CRD not found %s', kns_crd)
        except exceptions.K8sClientException:
            LOG.exception('Error updating kuryrnetwork CRD %s', kns_crd)
            raise

    def _get_kns_crd(self, namespace):
        k8s = clients.get_kubernetes_client()
        try:
            kuryrnetwork_crd = k8s.get('{}/{}/kuryrnetworks/{}'.format(
                constants.K8S_API_CRD_NAMESPACES, namespace,
                namespace))
        except exceptions.K8sResourceNotFound:
            return None
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return kuryrnetwork_crd

    def _add_kuryrnetwork_crd(self, namespace, ns_labels):
        ns_name = namespace['metadata']['name']
        project_id = self._drv_project.get_project(namespace)
        kubernetes = clients.get_kubernetes_client()

        kns_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrNetwork',
            'metadata': {
                'name': ns_name,
                'finalizers': [constants.KURYRNETWORK_FINALIZER],
            },
            'spec': {
                'nsName': ns_name,
                'projectId': project_id,
                'nsLabels': ns_labels,
            }
        }
        try:
            kubernetes.post('{}/{}/kuryrnetworks'.format(
                constants.K8S_API_CRD_NAMESPACES, ns_name), kns_crd)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating kuryrnetwork "
                          "CRD.")
            raise

    def is_ready(self, quota):
        if not (utils.has_kuryr_crd(constants.K8S_API_CRD_KURYRNETWORKS) and
                self._check_quota(quota)):
            LOG.error('Marking NamespaceHandler as not ready.')
            return False
        return True

    def _check_quota(self, quota):
        resources = ('subnets', 'networks', 'security_groups')

        for resource in resources:
            resource_quota = quota[resource]
            if utils.has_limit(resource_quota):
                if not utils.is_available(resource, resource_quota):
                    return False
        return True
