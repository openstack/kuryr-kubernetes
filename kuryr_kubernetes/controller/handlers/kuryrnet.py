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
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions
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
        subnet_id = kuryrnet_crd['spec'].get('subnetId')
        if kuryrnet_crd['spec'].get('populated'):
            LOG.debug("Subnet %s already populated", subnet_id)
            return

        namespace = kuryrnet_crd['metadata']['annotations'].get(
            'namespaceName')
        namespace_obj = driver_utils.get_namespace(namespace)
        namespace_kuryrnet_annotations = driver_utils.get_annotations(
            namespace_obj, constants.K8S_ANNOTATION_NET_CRD)
        if namespace_kuryrnet_annotations != kuryrnet_crd['metadata']['name']:
            # NOTE(ltomasbo): Ensure pool is not populated if namespace is not
            # yet annotated with kuryrnet information
            return

        # NOTE(ltomasbo): using namespace name instead of object as it is not
        # required
        project_id = self._drv_project.get_project(namespace)
        subnets = self._drv_subnets.get_namespace_subnet(namespace, subnet_id)
        sg_id = kuryrnet_crd['spec'].get('sgId', [])

        nodes = utils.get_nodes_ips()
        # NOTE(ltomasbo): Patching the kuryrnet_crd here instead of after
        # populate_pool method to ensure initial repopulation is not happening
        # twice upon unexpected problems, such as neutron failing to
        # transition the ports to ACTIVE or being too slow replying.
        # In such case, even though the repopulation actions got triggered,
        # the pools will not get the ports loaded (as they are not ACTIVE)
        # and new population actions may be triggered if the controller was
        # restarted before performing the populated=true patching.
        driver_utils.patch_kuryrnet_crd(kuryrnet_crd, populated=True)
        # TODO(ltomasbo): Skip the master node where pods are not usually
        # allocated.
        for node_ip in nodes:
            LOG.debug("Populating subnet pool %s at node %s", subnet_id,
                      node_ip)
            try:
                self._drv_vif_pool.populate_pool(node_ip, project_id, subnets,
                                                 sg_id)
            except exceptions.ResourceNotReady:
                # Ensure the repopulation is retriggered if the system was not
                # yet ready to perform the repopulation actions
                driver_utils.patch_kuryrnet_crd(kuryrnet_crd, populated=False)
                raise
