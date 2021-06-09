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

import uuid

from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import k8s_base

LOG = logging.getLogger(__name__)


class MachineHandler(k8s_base.ResourceEventHandler):
    """MachineHandler gathers info about OpenShift nodes needed by Kuryr.

    At the moment that's the subnets of all the worker nodes.
    """
    OBJECT_KIND = constants.OPENSHIFT_OBJ_MACHINE
    OBJECT_WATCH_PATH = constants.OPENSHIFT_API_CRD_MACHINES

    def __init__(self):
        super(MachineHandler, self).__init__()
        self.node_subnets_driver = drivers.NodesSubnetsDriver.get_instance()

    def _bump_nps(self):
        """Bump NetworkPolicy objects to have the SG rules recalculated."""
        k8s = clients.get_kubernetes_client()
        # NOTE(dulek): Listing KuryrNetworkPolicies instead of NetworkPolicies,
        #              as we only care about NPs already handled.
        knps = k8s.get(constants.K8S_API_CRD_KURYRNETWORKPOLICIES)
        for knp in knps.get('items', []):
            try:
                k8s.annotate(
                    knp['metadata']['annotations']['networkPolicyLink'],
                    {constants.K8S_ANNOTATION_POLICY: str(uuid.uuid4())})
            except exceptions.K8sResourceNotFound:
                # Had to be deleted in the meanwhile.
                pass

    def on_present(self, machine, *args, **kwargs):
        effect = self.node_subnets_driver.add_node(machine)
        if effect:
            # If the change was meaningful we need to make sure all the NPs
            # are recalculated to get the new SG rules added.
            self._bump_nps()

    def on_deleted(self, machine, *args, **kwargs):
        effect = self.node_subnets_driver.delete_node(machine)
        if effect:
            # If the change was meaningful we need to make sure all the NPs
            # are recalculated to get the old SG rule deleted.
            self._bump_nps()
