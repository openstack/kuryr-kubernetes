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

LOG = logging.getLogger(__name__)


class NamespaceHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = constants.K8S_OBJ_NAMESPACE
    OBJECT_WATCH_PATH = "%s/%s" % (constants.K8S_API_BASE, "namespaces")

    def __init__(self):
        super(NamespaceHandler, self).__init__()
        self._drv_project = drivers.NamespaceProjectDriver.get_instance()
        self._drv_subnets = drivers.PodSubnetsDriver.get_instance()
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            driver_alias='multi_pool')
        self._drv_vif_pool.set_vif_driver()

    def on_present(self, namespace):
        ns_name = namespace['metadata']['name']
        project_id = self._drv_project.get_project(namespace)
        net_crd = self._get_net_crd(namespace)
        if net_crd:
            LOG.debug("CRD existing at the new namespace")
            return

        LOG.debug("Creating network resources for namespace: %s", ns_name)
        net_crd = self._drv_subnets.create_namespace_network(ns_name,
                                                             project_id)
        try:
            self._set_net_crd(namespace, net_crd)
        except exceptions.K8sClientException:
            LOG.exception("Failed to set annotation")
            crd_spec = net_crd['spec']
            self._drv_subnets.rollback_network_resources(
                crd_spec['routerId'], crd_spec['netId'], crd_spec['subnetId'],
                ns_name)

    def on_deleted(self, namespace):
        LOG.debug("Deleting namespace: %s", namespace)
        net_crd = self._get_net_crd(namespace)
        if not net_crd:
            LOG.warning("There is no CRD annotated at the namespace %s",
                        namespace)
            return

        net_id = self._get_net_id_from_net_crd(net_crd)
        self._drv_vif_pool.delete_network_pools(net_id)
        self._drv_subnets.delete_namespace_subnet(net_crd)

    def _get_net_crd(self, namespace):
        try:
            annotations = namespace['metadata']['annotations']
            net_crd = annotations[constants.K8S_ANNOTATION_NET_CRD]
        except KeyError:
            return None
        return net_crd

    def _set_net_crd(self, namespace, net_crd):
        LOG.debug("Setting CRD annotations: %s", net_crd)

        k8s = clients.get_kubernetes_client()
        k8s.annotate(namespace['metadata']['selfLink'],
                     {constants.K8S_ANNOTATION_NET_CRD:
                      net_crd['metadata']['name']},
                     resource_version=namespace['metadata']['resourceVersion'])

    def _get_net_id_from_net_crd(self, net_crd):
        k8s = clients.get_kubernetes_client()
        try:
            kuryrnet_crd = k8s.get('%s/kuryrnets/%s' % (constants.K8S_API_CRD,
                                                        net_crd))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return kuryrnet_crd['spec']['netId']
