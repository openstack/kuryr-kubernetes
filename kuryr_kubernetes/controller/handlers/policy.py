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

from oslo_cache import core as cache
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)

np_handler_caching_opts = [
    oslo_cfg.BoolOpt('caching', default=True),
    oslo_cfg.IntOpt('cache_time', default=120),
]

oslo_cfg.CONF.register_opts(np_handler_caching_opts,
                            "np_handler_caching")

cache.configure(oslo_cfg.CONF)
np_handler_cache_region = cache.create_region()
MEMOIZE = cache.get_memoization_decorator(
    oslo_cfg.CONF, np_handler_cache_region, "np_handler_caching")

cache.configure_cache_region(oslo_cfg.CONF, np_handler_cache_region)


class NetworkPolicyHandler(k8s_base.ResourceEventHandler):
    """NetworkPolicyHandler handles k8s Network Policies events"""

    OBJECT_KIND = k_const.K8S_OBJ_POLICY
    OBJECT_WATCH_PATH = k_const.K8S_API_POLICIES

    def __init__(self):
        super(NetworkPolicyHandler, self).__init__()
        self._drv_policy = drivers.NetworkPolicyDriver.get_instance()
        self._drv_project = drivers.NetworkPolicyProjectDriver.get_instance()
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            specific_driver='multi_pool')
        self._drv_vif_pool.set_vif_driver()
        self._drv_pod_sg = drivers.PodSecurityGroupsDriver.get_instance()
        self._drv_svc_sg = drivers.ServiceSecurityGroupsDriver.get_instance()

    def on_present(self, policy):
        LOG.debug("Created or updated: %s", policy)
        project_id = self._drv_project.get_project(policy)
        pods_to_update = []

        modified_pods = self._drv_policy.ensure_network_policy(policy,
                                                               project_id)
        if modified_pods:
            pods_to_update.extend(modified_pods)

        matched_pods = self._drv_policy.affected_pods(policy)
        pods_to_update.extend(matched_pods)

        for pod in pods_to_update:
            if driver_utils.is_host_network(pod):
                continue
            pod_sgs = self._drv_pod_sg.get_security_groups(pod, project_id)
            self._drv_vif_pool.update_vif_sgs(pod, pod_sgs)

    def on_deleted(self, policy):
        LOG.debug("Deleted network policy: %s", policy)
        project_id = self._drv_project.get_project(policy)
        pods_to_update = self._drv_policy.affected_pods(policy)
        netpolicy_crd = self._drv_policy.get_kuryrnetpolicy_crd(policy)
        crd_sg = netpolicy_crd['spec'].get('securityGroupId')
        for pod in pods_to_update:
            if driver_utils.is_host_network(pod):
                continue
            pod_sgs = self._drv_pod_sg.get_security_groups(pod, project_id)
            if crd_sg in pod_sgs:
                pod_sgs.remove(crd_sg)
            if not pod_sgs:
                pod_sgs = oslo_cfg.CONF.neutron_defaults.pod_security_groups
                if not pod_sgs:
                    raise oslo_cfg.RequiredOptError('pod_security_groups',
                                                    oslo_cfg.OptGroup(
                                                        'neutron_defaults'))
            self._drv_vif_pool.update_vif_sgs(pod, pod_sgs)

        self._drv_policy.release_network_policy(netpolicy_crd)

    @MEMOIZE
    def is_ready(self, quota):
        neutron = clients.get_neutron_client()
        sg_quota = quota['security_group']
        sg_func = neutron.list_security_groups
        if utils.has_limit(sg_quota):
            return utils.is_available('security_groups', sg_quota, sg_func)
        return True
