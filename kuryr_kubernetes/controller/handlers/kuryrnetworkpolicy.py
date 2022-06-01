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

from openstack import exceptions as os_exc
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class KuryrNetworkPolicyHandler(k8s_base.ResourceEventHandler):
    """Controller side of KuryrNetworkPolicy process for Kubernetes pods.

    `KuryrNetworkPolicyHandler` runs on the kuryr-controller and is
    responsible for creating and deleting SG and SG rules for `NetworkPolicy`.
    The `KuryrNetworkPolicy` objects are created by `NetworkPolicyHandler`.
    """
    OBJECT_KIND = constants.K8S_OBJ_KURYRNETWORKPOLICY
    OBJECT_WATCH_PATH = constants.K8S_API_CRD_KURYRNETWORKPOLICIES

    def __init__(self):
        super(KuryrNetworkPolicyHandler, self).__init__()
        self.os_net = clients.get_network_client()
        self.k8s = clients.get_kubernetes_client()
        self._drv_project = drivers.NetworkPolicyProjectDriver.get_instance()
        self._drv_policy = drivers.NetworkPolicyDriver.get_instance()
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            specific_driver='multi_pool')
        self._drv_vif_pool.set_vif_driver()
        self._drv_pod_sg = drivers.PodSecurityGroupsDriver.get_instance()
        self._drv_svc_sg = drivers.ServiceSecurityGroupsDriver.get_instance()
        self._drv_lbaas = drivers.LBaaSDriver.get_instance()

    def _patch_kuryrnetworkpolicy_crd(self, knp, field, data,
                                      action='replace'):
        name = knp['metadata']['name']
        LOG.debug('Patching KuryrNetwork CRD %s', name)
        try:
            status = self.k8s.patch_crd(field, utils.get_res_link(knp),
                                        data, action=action)
        except exceptions.K8sResourceNotFound:
            LOG.debug('KuryrNetworkPolicy CRD not found %s', name)
            return None
        except exceptions.K8sClientException as exc:
            np = utils.get_referenced_object(knp, 'NetworkPolicy')
            self.k8s.add_event(np, 'FailedToPatchKuryrNetworkPolicy',
                               f'Failed to update KuryrNetworkPolicy CRD: '
                               f'{exc}', 'Warning')
            LOG.exception('Error updating KuryrNetworkPolicy CRD %s', name)
            raise

        knp['status'] = status
        return knp

    def _get_networkpolicy(self, link):
        return self.k8s.get(link)

    def _compare_sgs(self, a, b):
        checked_props = ('direction', 'ethertype', 'port_range_max',
                         'port_range_min', 'protocol', 'remote_ip_prefix')

        for k in checked_props:
            if a.get(k) != b.get(k):
                return False
        return True

    def _find_sgs(self, a, rules):
        for r in rules:
            if self._compare_sgs(r, a):
                return True

        return False

    def on_present(self, knp, *args, **kwargs):
        uniq_name = utils.get_res_unique_name(knp)
        LOG.debug('on_present() for NP %s', uniq_name)
        project_id = self._drv_project.get_project(knp)
        if not knp['status'].get('securityGroupId'):
            LOG.debug('Creating SG for NP %s', uniq_name)
            # TODO(dulek): Do this right, why do we have a project driver per
            #              resource?! This one expects policy, not knp, but it
            #              ignores it anyway!
            sg_id = self._drv_policy.create_security_group(knp, project_id)
            knp = self._patch_kuryrnetworkpolicy_crd(
                knp, 'status', {'securityGroupId': sg_id})
            LOG.debug('Created SG %s for NP %s', sg_id, uniq_name)
        else:
            # TODO(dulek): Check if it really exists, recreate if not.
            sg_id = knp['status'].get('securityGroupId')

        # First update SG rules as we want to apply updated ones
        current = knp['status']['securityGroupRules']
        required = knp['spec']['ingressSgRules'] + knp['spec']['egressSgRules']
        required = [r['sgRule'] for r in required]

        # FIXME(dulek): This *might* be prone to race conditions if failure
        #               happens between SG rule is created/deleted and status
        #               is annotated. We don't however need to revert on failed
        #               K8s operations - creation, deletion of SG rules and
        #               attaching or detaching SG from ports are idempotent
        #               so we can repeat them. What worries me is losing track
        #               of an update due to restart. The only way to do it
        #               would be to periodically check if what's in `status`
        #               is the reality in OpenStack API. That should be just
        #               two Neutron API calls + possible resync.
        to_add = []
        to_remove = []
        for r in required:
            if not self._find_sgs(r, current):
                to_add.append(r)

        for i, c in enumerate(current):
            if not self._find_sgs(c, required):
                to_remove.append((i, c['id']))

        LOG.debug('SGs to add for NP %s: %s', uniq_name, to_add)

        for sg_rule in to_add:
            LOG.debug('Adding SG rule %s for NP %s', sg_rule, uniq_name)
            sg_rule['security_group_id'] = sg_id
            sgr_id = driver_utils.create_security_group_rule(sg_rule, knp)
            sg_rule['id'] = sgr_id
            knp = self._patch_kuryrnetworkpolicy_crd(
                knp, 'status', {'securityGroupRules/-': sg_rule}, 'add')

        # We need to remove starting from the last one in order to maintain
        # indexes. Please note this will start to fail miserably if we start
        # to change status from multiple places.
        to_remove.reverse()

        LOG.debug('SGs to remove for NP %s: %s', uniq_name,
                  [x[1] for x in to_remove])

        for i, sg_rule_id in to_remove:
            LOG.debug('Removing SG rule %s as it is no longer part of NP %s',
                      sg_rule_id, uniq_name)
            driver_utils.delete_security_group_rule(sg_rule_id, knp)
            knp = self._patch_kuryrnetworkpolicy_crd(
                knp, 'status/securityGroupRules', i, 'remove')

        pods_to_update = []

        previous_sel = knp['status'].get('podSelector', None)
        current_sel = knp['spec']['podSelector']
        if previous_sel is None:
            # Fresh NetworkPolicy that was never applied.
            pods_to_update.extend(self._drv_policy.namespaced_pods(knp))
        elif previous_sel != current_sel or previous_sel == {}:
            pods_to_update.extend(
                self._drv_policy.affected_pods(knp, previous_sel))

        matched_pods = self._drv_policy.affected_pods(knp)
        pods_to_update.extend(matched_pods)

        for pod in pods_to_update:
            if (utils.is_host_network(pod) or
                    not driver_utils.is_pod_scheduled(pod)):
                continue
            pod_sgs = self._drv_pod_sg.get_security_groups(pod, project_id)
            try:
                self._drv_vif_pool.update_vif_sgs(pod, pod_sgs)
            except os_exc.NotFoundException:
                # Pod got deleted in the meanwhile, should be safe to ignore.
                pass

        # FIXME(dulek): We should not need this one day.
        policy = self._get_networkpolicy(knp['metadata']['annotations']
                                         ['networkPolicyLink'])
        if (pods_to_update and CONF.octavia_defaults.enforce_sg_rules and
                not self._is_egress_only_policy(policy)):
            # NOTE(ltomasbo): only need to change services if the pods that
            # they point to are updated
            services = driver_utils.get_services(knp['metadata']['namespace'])
            for service in services.get('items', []):
                # TODO(ltomasbo): Skip other services that are not affected
                #                 by the policy
                # NOTE(maysams): Network Policy is not enforced on Services
                # without selectors for Amphora Octavia provider.
                # NOTE(dulek): Skip services being deleted.
                if (not service['spec'].get('selector') or
                        service['metadata'].get('deletionTimestamp') or not
                        self._is_service_affected(service, pods_to_update)):
                    continue
                sgs = self._drv_svc_sg.get_security_groups(service, project_id)
                try:
                    self._drv_lbaas.update_lbaas_sg(service, sgs)
                except exceptions.ResourceNotReady:
                    # We can ignore LB that's being created - its SGs will get
                    # handled when members will be getting created.
                    pass

        self._patch_kuryrnetworkpolicy_crd(knp, 'status',
                                           {'podSelector': current_sel})

    def _is_service_affected(self, service, affected_pods):
        svc_namespace = service['metadata']['namespace']
        svc_selector = service['spec'].get('selector')
        svc_pods = driver_utils.get_pods({'selector': svc_selector},
                                         svc_namespace).get('items')
        return any(pod in svc_pods for pod in affected_pods)

    def _is_egress_only_policy(self, policy):
        policy_types = policy['spec'].get('policyTypes', [])
        return (policy_types == ['Egress'] or
                (policy['spec'].get('egress') and
                 not policy['spec'].get('ingress')))

    def _get_policy_net_id(self, knp):
        policy_ns = knp['metadata']['namespace']

        try:
            path = (f'{constants.K8S_API_CRD_NAMESPACES}/{policy_ns}/'
                    f'kuryrnetworks/{policy_ns}')
            net_crd = self.k8s.get(path)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return net_crd['status']['netId']

    def on_finalize(self, knp, *args, **kwargs):
        LOG.debug("Finalizing KuryrNetworkPolicy %s", knp)
        project_id = self._drv_project.get_project(knp)
        pods_to_update = self._drv_policy.affected_pods(knp)
        crd_sg = knp['status'].get('securityGroupId')
        try:
            policy = self._get_networkpolicy(knp['metadata']['annotations']
                                             ['networkPolicyLink'])
        except exceptions.K8sResourceNotFound:
            # NP is already gone, let's just try to clean up.
            policy = None

        if crd_sg:
            for pod in pods_to_update:
                if (utils.is_host_network(pod)
                        or not driver_utils.is_pod_scheduled(pod)):
                    continue
                pod_sgs = self._drv_pod_sg.get_security_groups(pod, project_id)
                if crd_sg in pod_sgs:
                    pod_sgs.remove(crd_sg)
                if not pod_sgs:
                    pod_sgs = CONF.neutron_defaults.pod_security_groups
                    if not pod_sgs:
                        raise cfg.RequiredOptError(
                            'pod_security_groups',
                            cfg.OptGroup('neutron_defaults'))
                try:
                    self._drv_vif_pool.update_vif_sgs(pod, pod_sgs)
                except os_exc.NotFoundException:
                    # Pod got deleted in the meanwhile, safe to ignore.
                    pass

            # ensure ports at the pool don't have the NP sg associated
            try:
                net_id = self._get_policy_net_id(knp)
                self._drv_vif_pool.remove_sg_from_pools(crd_sg, net_id)
            except exceptions.K8sResourceNotFound:
                # Probably the network got removed already, we can ignore it.
                pass

            try:
                self._drv_policy.delete_np_sg(crd_sg)
            except os_exc.SDKException as exc:
                np = utils.get_referenced_object(knp, 'NetworkPolicy')
                if np:
                    self.k8s.add_event(np, 'FailedToRemoveSecurityGroup',
                                       f'Deleting security group for '
                                       f'corresponding Network Policy has '
                                       f'failed: {exc}', 'Warning')
                    raise

            if (CONF.octavia_defaults.enforce_sg_rules and policy and
                    not self._is_egress_only_policy(policy)):
                services = driver_utils.get_services(
                    knp['metadata']['namespace'])
                for svc in services.get('items'):
                    if (not svc['spec'].get('selector') or not
                            self._is_service_affected(svc, pods_to_update)):
                        continue

                    sgs = self._drv_svc_sg.get_security_groups(svc, project_id)

                    if crd_sg in sgs:
                        # Remove our crd_sg out of service groups since we
                        # don't have it anymore
                        sgs.remove(crd_sg)

                    try:
                        self._drv_lbaas.update_lbaas_sg(svc, sgs)
                    except exceptions.ResourceNotReady:
                        # We can ignore LB that's being created - its SGs will
                        # get handled when members will be getting created.
                        pass

        LOG.debug("Removing finalizers from KuryrNetworkPolicy and "
                  "NetworkPolicy.")
        if policy:
            self.k8s.remove_finalizer(policy,
                                      constants.NETWORKPOLICY_FINALIZER)
        self.k8s.remove_finalizer(knp, constants.NETWORKPOLICY_FINALIZER)
