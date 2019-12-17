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

from neutronclient.common import exceptions as n_exc
from openstack import exceptions as o_exc
from oslo_cache import core as cache
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions
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
        self._drv_lbaas = drivers.LBaaSDriver.get_instance()

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

        if (pods_to_update and
                oslo_cfg.CONF.octavia_defaults.enforce_sg_rules and
                not self._is_egress_only_policy(policy)):
            # NOTE(ltomasbo): only need to change services if the pods that
            # they point to are updated
            services = driver_utils.get_services(
                policy['metadata']['namespace'])
            for service in services.get('items'):
                # TODO(ltomasbo): Skip other services that are not affected
                # by the policy
                if (not service['spec'].get('selector') or not
                        self._is_service_affected(service, pods_to_update)):
                    continue
                sgs = self._drv_svc_sg.get_security_groups(service,
                                                           project_id)
                self._drv_lbaas.update_lbaas_sg(service, sgs)

    def on_deleted(self, policy):
        LOG.debug("Deleted network policy: %s", policy)
        project_id = self._drv_project.get_project(policy)
        pods_to_update = self._drv_policy.affected_pods(policy)
        netpolicy_crd = self._drv_policy.get_kuryrnetpolicy_crd(policy)
        if netpolicy_crd:
            crd_sg = netpolicy_crd['spec'].get('securityGroupId')
            for pod in pods_to_update:
                if driver_utils.is_host_network(pod):
                    continue
                pod_sgs = self._drv_pod_sg.get_security_groups(pod,
                                                               project_id)
                if crd_sg in pod_sgs:
                    pod_sgs.remove(crd_sg)
                if not pod_sgs:
                    pod_sgs = (
                        oslo_cfg.CONF.neutron_defaults.pod_security_groups)
                    if not pod_sgs:
                        raise oslo_cfg.RequiredOptError(
                            'pod_security_groups',
                            oslo_cfg.OptGroup('neutron_defaults'))
                try:
                    self._drv_vif_pool.update_vif_sgs(pod, pod_sgs)
                except (n_exc.NotFound, o_exc.NotFoundException):
                    LOG.debug("Fail to update pod sgs."
                              " Retrying policy deletion.")
                    raise exceptions.ResourceNotReady(policy)

            # ensure ports at the pool don't have the NP sg associated
            net_id = self._get_policy_net_id(policy)
            self._drv_vif_pool.remove_sg_from_pools(crd_sg, net_id)

            self._drv_policy.release_network_policy(netpolicy_crd)

            if (oslo_cfg.CONF.octavia_defaults.enforce_sg_rules and
                    not self._is_egress_only_policy(policy)):
                services = driver_utils.get_services(
                    policy['metadata']['namespace'])
                for svc in services.get('items'):
                    if (not svc['spec'].get('selector') or not
                            self._is_service_affected(svc, pods_to_update)):
                        continue
                    sgs = self._drv_svc_sg.get_security_groups(svc,
                                                               project_id)
                    self._drv_lbaas.update_lbaas_sg(svc, sgs)

    def is_ready(self, quota):
        if not utils.has_kuryr_crd(k_const.K8S_API_CRD_KURYRNETPOLICIES):
            return False
        return self._check_quota(quota)

    @MEMOIZE
    def _check_quota(self, quota):
        neutron = clients.get_neutron_client()
        sg_quota = quota['security_group']
        sg_func = neutron.list_security_groups
        if utils.has_limit(sg_quota):
            return utils.is_available('security_groups', sg_quota, sg_func)
        return True

    def _is_service_affected(self, service, affected_pods):
        svc_namespace = service['metadata']['namespace']
        svc_selector = service['spec'].get('selector')
        svc_pods = driver_utils.get_pods({'selector': svc_selector},
                                         svc_namespace).get('items')
        return any(pod in svc_pods for pod in affected_pods)

    def _get_policy_net_id(self, policy):
        policy_ns = policy['metadata']['namespace']
        kuryrnet_name = 'ns-' + str(policy_ns)

        kubernetes = clients.get_kubernetes_client()
        try:
            net_crd = kubernetes.get('{}/{}'.format(
                k_const.K8S_API_CRD_KURYRNETS, kuryrnet_name))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return net_crd['spec']['netId']

    def _is_egress_only_policy(self, policy):
        policy_types = policy['spec'].get('policyTypes', [])
        return (policy_types == ['Egress'] or
                (policy['spec'].get('egress') and
                    not policy['spec'].get('ingress')))
