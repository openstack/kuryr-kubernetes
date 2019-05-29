# Copyright 2019 Red Hat, Inc.
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

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class KuryrNetHandler(k8s_base.ResourceEventHandler):
    """Controller side of KuryrNet process for Kubernetes pods.

    `KuryrNetHandler` runs on the Kuryr-Kubernetes controller and is
    responsible for populating pools for newly created namespaces.
    """
    OBJECT_KIND = constants.K8S_OBJ_KURYRNET
    OBJECT_WATCH_PATH = constants.K8S_API_CRD_KURYRNETS

    def __init__(self):
        super(KuryrNetHandler, self).__init__()
        self._drv_project = drivers.NamespaceProjectDriver.get_instance()
        self._drv_subnets = drivers.PodSubnetsDriver.get_instance()
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            specific_driver='multi_pool')
        self._drv_vif_pool.set_vif_driver()

    def on_added(self, kuryrnet_crd):
        namespace = kuryrnet_crd['metadata']['annotations'].get(
            'namespaceName')
        # NOTE(ltomasbo): using namespace name instead of object as it is not
        # required
        project_id = self._drv_project.get_project(namespace)
        subnet_id = kuryrnet_crd['spec'].get('subnetId')
        subnets = self._drv_subnets.get_namespace_subnet(namespace, subnet_id)
        sg_id = kuryrnet_crd['spec'].get('sgId', [])

        nodes = utils.get_nodes_ips()
        # TODO(ltomasbo): Skip the master node where pods are not usually
        # allocated.
        for node_ip in nodes:
            LOG.debug("Populating subnet pool %s at node %s", subnet_id,
                      node_ip)
            self._drv_vif_pool.populate_pool(node_ip, project_id, subnets,
                                             sg_id)
