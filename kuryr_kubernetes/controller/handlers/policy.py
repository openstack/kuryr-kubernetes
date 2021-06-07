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
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class NetworkPolicyHandler(k8s_base.ResourceEventHandler):
    """NetworkPolicyHandler handles k8s Network Policies events"""

    OBJECT_KIND = k_const.K8S_OBJ_POLICY
    OBJECT_WATCH_PATH = k_const.K8S_API_POLICIES

    def __init__(self):
        super(NetworkPolicyHandler, self).__init__()
        self._drv_policy = drivers.NetworkPolicyDriver.get_instance()
        self.k8s = clients.get_kubernetes_client()

    def on_present(self, policy, *args, **kwargs):
        LOG.debug("Created or updated: %s", policy)

        self._drv_policy.ensure_network_policy(policy)

        # Put finalizer in if it's not there already.
        self.k8s.add_finalizer(policy, k_const.NETWORKPOLICY_FINALIZER)

    def on_finalize(self, policy, *args, **kwargs):
        LOG.debug("Finalizing policy %s", policy)
        if not self._drv_policy.release_network_policy(policy):
            # KNP was not found, so we need to finalize on our own.
            self.k8s.remove_finalizer(policy, k_const.NETWORKPOLICY_FINALIZER)

    def is_ready(self, quota):
        if not (utils.has_kuryr_crd(k_const.K8S_API_CRD_KURYRNETWORKPOLICIES)
                and self._check_quota(quota)):
            LOG.error("Marking NetworkPolicyHandler as not ready.")
            return False
        return True

    def _check_quota(self, quota):
        if utils.has_limit(quota.security_groups):
            return utils.is_available('security_groups', quota.security_groups)
        return True
