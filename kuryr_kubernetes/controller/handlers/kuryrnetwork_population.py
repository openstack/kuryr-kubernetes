# Copyright 2020 Red Hat, Inc.
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


class KuryrNetworkPopulationHandler(k8s_base.ResourceEventHandler):
    """Controller side of KuryrNetwork process for Kubernetes pods.

    `KuryrNetworkPopulationHandler` runs on the Kuryr-Kubernetes controller
    and is responsible for populating pools for newly created namespaces.
    """
    OBJECT_KIND = constants.K8S_OBJ_KURYRNETWORK
    OBJECT_WATCH_PATH = constants.K8S_API_CRD_KURYRNETWORKS

    def __init__(self):
        super(KuryrNetworkPopulationHandler, self).__init__()
        self._drv_subnets = drivers.PodSubnetsDriver.get_instance()
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            specific_driver='multi_pool')
        self._drv_vif_pool.set_vif_driver()
        self._drv_nodes_subnets = drivers.NodesSubnetsDriver.get_instance()

    def on_present(self, kuryrnet_crd, *args, **kwargs):
        subnet_id = kuryrnet_crd.get('status', {}).get('subnetId')
        if not subnet_id:
            LOG.debug("No Subnet present for KuryrNetwork %s",
                      kuryrnet_crd['metadata']['name'])
            return

        if kuryrnet_crd['status'].get('populated'):
            LOG.debug("Subnet %s already populated for Namespace %s",
                      subnet_id, kuryrnet_crd['metadata']['name'])
            return

        namespace = kuryrnet_crd['spec'].get('nsName')
        project_id = kuryrnet_crd['spec'].get('projectId')
        # NOTE(ltomasbo): using namespace name instead of object as it is not
        # required
        subnets = self._drv_subnets.get_namespace_subnet(namespace, subnet_id)

        node_subnets = self._drv_nodes_subnets.get_nodes_subnets(
            raise_on_empty=True)
        nodes = utils.get_nodes_ips(node_subnets)
        # NOTE(ltomasbo): Patching the kuryrnet_crd here instead of after
        # populate_pool method to ensure initial repopulation is not happening
        # twice upon unexpected problems, such as neutron failing to
        # transition the ports to ACTIVE or being too slow replying.
        # In such case, even though the repopulation actions got triggered,
        # the pools will not get the ports loaded (as they are not ACTIVE)
        # and new population actions may be triggered if the controller was
        # restarted before performing the populated=true patching.
        self._patch_kuryrnetwork_crd(kuryrnet_crd, populated=True)
        # TODO(ltomasbo): Skip the master node where pods are not usually
        # allocated.
        for node_ip in nodes:
            LOG.debug("Populating subnet pool %s at node %s", subnet_id,
                      node_ip)
            try:
                self._drv_vif_pool.populate_pool(node_ip, project_id, subnets,
                                                 [])
            except exceptions.ResourceNotReady:
                # Ensure the repopulation is retriggered if the system was not
                # yet ready to perform the repopulation actions
                self._patch_kuryrnetwork_crd(kuryrnet_crd, populated=False)
                raise

    def _patch_kuryrnetwork_crd(self, kns_crd, populated=True):
        kubernetes = clients.get_kubernetes_client()
        crd_name = kns_crd['metadata']['name']
        LOG.debug('Patching KuryrNetwork CRD %s' % crd_name)
        try:
            kubernetes.patch_crd('status', utils.get_res_link(kns_crd),
                                 {'populated': populated})
        except exceptions.K8sClientException:
            LOG.exception('Error updating KuryrNetwork CRD %s', crd_name)
            raise
