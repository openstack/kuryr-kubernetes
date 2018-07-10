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

from neutronclient.common import exceptions as n_exc

LOG = logging.getLogger(__name__)


class NamespaceHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = constants.K8S_OBJ_NAMESPACE
    OBJECT_WATCH_PATH = "%s/%s" % (constants.K8S_API_BASE, "namespaces")

    def __init__(self):
        super(NamespaceHandler, self).__init__()
        self._drv_project = drivers.NamespaceProjectDriver.get_instance()
        self._drv_subnets = drivers.PodSubnetsDriver.get_instance()
        self._drv_sg = drivers.PodSecurityGroupsDriver.get_instance()
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            driver_alias='multi_pool')
        self._drv_vif_pool.set_vif_driver()

    def on_present(self, namespace):
        ns_name = namespace['metadata']['name']
        project_id = self._drv_project.get_project(namespace)
        net_crd_id = self._get_net_crd_id(namespace)
        if net_crd_id:
            LOG.debug("CRD existing at the new namespace")
            return

        LOG.debug("Creating network resources for namespace: %s", ns_name)
        net_crd_spec = self._drv_subnets.create_namespace_network(ns_name,
                                                                  project_id)
        try:
            net_crd_sg = self._drv_sg.create_namespace_sg(ns_name, project_id,
                                                          net_crd_spec)
        except n_exc.NeutronClientException:
            LOG.exception("Error creating security group for the namespace. "
                          "Rolling back created network resources.")
            self._drv_subnets.rollback_network_resources(net_crd_spec, ns_name)
            raise
        net_crd_spec.update(net_crd_sg)

        # create CRD resource for the network
        try:
            net_crd = self._add_kuryrnet_crd(ns_name, net_crd_spec)
            self._set_net_crd(namespace, net_crd)
        except exceptions.K8sClientException:
            LOG.exception("Kuryrnet CRD could not be added. Rolling back "
                          "network resources created for the namespace.")
            self._drv_subnets.rollback_network_resources(net_crd_spec, ns_name)
            self._drv_sg.delete_sg(net_crd_sg['sgId'])

    def on_deleted(self, namespace):
        LOG.debug("Deleting namespace: %s", namespace)
        net_crd_id = self._get_net_crd_id(namespace)
        if not net_crd_id:
            LOG.warning("There is no CRD annotated at the namespace %s",
                        namespace)
            return
        net_crd = self._get_net_crd(net_crd_id)

        self._drv_vif_pool.delete_network_pools(net_crd['spec']['netId'])
        self._drv_subnets.delete_namespace_subnet(net_crd)
        self._drv_sg.delete_sg(net_crd['spec']['sgId'])

        self._del_kuryrnet_crd(net_crd_id)

    def _get_net_crd_id(self, namespace):
        try:
            annotations = namespace['metadata']['annotations']
            net_crd_id = annotations[constants.K8S_ANNOTATION_NET_CRD]
        except KeyError:
            return None
        return net_crd_id

    def _get_net_crd(self, net_crd_id):
        k8s = clients.get_kubernetes_client()
        try:
            kuryrnet_crd = k8s.get('%s/kuryrnets/%s' % (constants.K8S_API_CRD,
                                                        net_crd_id))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return kuryrnet_crd

    def _set_net_crd(self, namespace, net_crd):
        LOG.debug("Setting CRD annotations: %s", net_crd)

        k8s = clients.get_kubernetes_client()
        k8s.annotate(namespace['metadata']['selfLink'],
                     {constants.K8S_ANNOTATION_NET_CRD:
                      net_crd['metadata']['name']},
                     resource_version=namespace['metadata']['resourceVersion'])

    def _add_kuryrnet_crd(self, namespace, net_crd_spec):
        kubernetes = clients.get_kubernetes_client()
        net_crd_name = "ns-" + namespace
        spec = {k: v for k, v in net_crd_spec.items()}
        net_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrNet',
            'metadata': {
                'name': net_crd_name,
                'annotations': {
                    'namespaceName': namespace,
                }
            },
            'spec': spec,
        }
        try:
            kubernetes.post('%s/kuryrnets' % constants.K8S_API_CRD, net_crd)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating kuryrnet "
                          "CRD.")
            raise
        return net_crd

    def _del_kuryrnet_crd(self, net_crd_name):
        kubernetes = clients.get_kubernetes_client()
        try:
            kubernetes.delete('%s/kuryrnets/%s' % (constants.K8S_API_CRD,
                                                   net_crd_name))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception deleting kuryrnet "
                          "CRD.")
            raise
