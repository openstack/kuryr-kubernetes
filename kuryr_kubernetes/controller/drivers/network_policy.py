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

from neutronclient.common import exceptions as n_exc

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions

LOG = logging.getLogger(__name__)


class NetworkPolicyDriver(base.NetworkPolicyDriver):
    """Provide security groups actions based on K8s Network Policies"""

    def __init__(self):
        self.neutron = clients.get_neutron_client()
        self.kubernetes = clients.get_kubernetes_client()

    def ensure_network_policy(self, policy, project_id):
        """Create security group rules out of network policies

        Triggered by events from network policies, this method ensures that
        security groups and security group rules are created or updated in
        reaction to kubernetes network policies events.
        """
        LOG.debug("Creating network policy %s", policy['metadata']['name'])

        if self._get_kuryrnetpolicy_crd(policy):
            self.update_security_group_rules_from_network_policy(policy)
        else:
            self.create_security_group_rules_from_network_policy(policy,
                                                                 project_id)

    def update_security_group_rules_from_network_policy(self, policy):
        """Update security group rules

        This method updates security group rules based on CRUD events gotten
        from a configuration or patch to an existing network policy
        """
        crd = self._get_kuryrnetpolicy_crd(policy)
        crd_name = crd['metadata']['name']
        LOG.debug("Already existing CRD %s", crd_name)
        sg_id = crd['spec']['securityGroupId']
        # Fetch existing SG rules from kuryrnetpolicy CRD
        existing_sg_rules = None
        existing_i_rules = crd['spec'].get('ingressSgRules')
        existing_e_rules = crd['spec'].get('egressSgRules')
        if existing_i_rules or existing_e_rules:
            existing_sg_rules = existing_i_rules + existing_e_rules
        # Parse network policy update and get new ruleset
        i_rules, e_rules = self.parse_network_policy_rules(policy, sg_id)
        current_sg_rules = i_rules + e_rules
        # Get existing security group rules ids
        sgr_ids = [x['security_group_rule'].pop('id') for x in
                   existing_sg_rules]
        # SG rules that are meant to be kept get their id back
        sg_rules_to_keep = [existing_sg_rules.index(rule) for rule in
                            existing_sg_rules if rule in current_sg_rules]
        for sg_rule in sg_rules_to_keep:
            sgr_id = sgr_ids[sg_rule]
            existing_sg_rules[sg_rule]['security_group_rule']['id'] = sgr_id
        # Delete SG rules that are no longer in the updated policy
        sg_rules_to_delete = [existing_sg_rules.index(rule) for rule in
                              existing_sg_rules if rule not in
                              current_sg_rules]
        for sg_rule in sg_rules_to_delete:
            try:
                self._delete_security_group_rule(sgr_ids[sg_rule])
            except n_exc.NotFound:
                LOG.debug('Trying to delete non existing sg_rule %s', sg_rule)
        # Create new rules that weren't already on the security group
        sg_rules_to_add = [rule for rule in current_sg_rules if rule not in
                           existing_sg_rules]
        for sg_rule in sg_rules_to_add:
            sgr_id = self._create_security_group_rule(sg_rule)
            if sg_rule['security_group_rule'].get('direction') == 'ingress':
                for i_rule in i_rules:
                    if sg_rule == i_rule:
                        i_rule["security_group_rule"]["id"] = sgr_id
            else:
                for e_rule in e_rules:
                    if sg_rule == e_rule:
                        e_rule["security_group_rule"]["id"] = sgr_id
        # Annotate kuryrnetpolicy CRD with current policy and ruleset
        LOG.debug('Patching KuryrNetPolicy CRD %s', crd_name)
        try:
            self.kubernetes.patch('spec', crd['metadata']['selfLink'],
                                  {'ingressSgRules': i_rules,
                                   'egressSgRules': e_rules,
                                   'networkpolicy_spec': policy['spec']})
        except exceptions.K8sClientException:
            LOG.exception('Error updating kuryrnetpolicy CRD %s', crd_name)
            raise

    def create_security_group_rules_from_network_policy(self, policy,
                                                        project_id):
        """Create initial security group and rules

        This method creates the initial security group for hosting security
        group rules coming out of network policies' parsing.
        """
        sg_name = ("sg-" + policy['metadata']['namespace'] + "-" +
                   policy['metadata']['name'])
        security_group_body = {
            "security_group":
                {
                    "name": sg_name,
                    "project_id": project_id,
                    "description": "Kuryr-Kubernetes NetPolicy SG"
                }
        }
        sg = None
        try:
            # Create initial security group
            sg = self.neutron.create_security_group(body=security_group_body)
            sg_id = sg['security_group']['id']
            i_rules, e_rules = self.parse_network_policy_rules(policy, sg_id)
            for i_rule in i_rules:
                sgr_id = self._create_security_group_rule(i_rule)
                i_rule['security_group_rule']['id'] = sgr_id
            for e_rule in e_rules:
                sgr_id = self._create_security_group_rule(e_rule)
                e_rule['security_group_rule']['id'] = sgr_id
        except n_exc.NeutronClientException:
            LOG.exception("Error creating security group for network policy "
                          " %s", policy['metadata']['name'])
            # If there's any issue creating sg rules, remove them
            if sg:
                self.neutron.delete_security_group(sg['security_group']['id'])
            raise
        try:
            self._add_kuryrnetpolicy_crd(policy, project_id,
                                         sg['security_group']['id'], i_rules,
                                         e_rules)
        except exceptions.K8sClientException:
            LOG.exception("Rolling back security groups")
            # Same with CRD creation
            self.neutron.delete_security_group(sg['security_group']['id'])
            raise
        try:
            crd = self._get_kuryrnetpolicy_crd(policy)
            self.kubernetes.annotate(policy['metadata']['selfLink'],
                                     {"kuryrnetpolicy_selfLink":
                                      crd['metadata']['selfLink']})
        except exceptions.K8sClientException:
            LOG.exception('Error annotating network policy')
            raise

    def parse_network_policy_rules(self, policy, sg_id):
        """Create security group rule bodies out of network policies.

        Whenever a notification from the handler 'on-present' method is
        received, security group rules are created out of network policies'
        ingress and egress ports blocks.
        """
        LOG.debug('Parsing Network Policy %s' % policy['metadata']['name'])
        ingress_rule_list = policy['spec'].get('ingress')
        egress_rule_list = policy['spec'].get('egress')
        ingress_sg_rule_body_list = []
        egress_sg_rule_body_list = []

        if ingress_rule_list:
            if ingress_rule_list[0] == {}:
                LOG.debug('Applying default all open policy from %s',
                          policy['metadata']['selfLink'])
                i_rule = self._create_security_group_rule_body(
                    sg_id, 'ingress', port_range_min=1, port_range_max=65535)
                ingress_sg_rule_body_list.append(i_rule)
            for ingress_rule in ingress_rule_list:
                LOG.debug('Parsing Ingress Rule %s', ingress_rule)
                if 'ports' in ingress_rule:
                    for port in ingress_rule['ports']:
                        i_rule = self._create_security_group_rule_body(
                            sg_id, 'ingress', port['port'],
                            protocol=port['protocol'].lower())
                        ingress_sg_rule_body_list.append(i_rule)
                else:
                    LOG.debug('This network policy specifies no ingress '
                              'ports: %s', policy['metadata']['selfLink'])

        if egress_rule_list:
            if egress_rule_list[0] == {}:
                LOG.debug('Applying default all open policy from %s',
                          policy['metadata']['selfLink'])
                e_rule = self._create_security_group_rule_body(
                    sg_id, 'egress', port_range_min=1, port_range_max=65535)
                egress_sg_rule_body_list.append(e_rule)
            for egress_rule in egress_rule_list:
                LOG.debug('Parsing Egress Rule %s', egress_rule)
                if 'ports' in egress_rule:
                    for port in egress_rule['ports']:
                        e_rule = self._create_security_group_rule_body(
                            sg_id, 'egress', port['port'],
                            protocol=port['protocol'].lower())
                        egress_sg_rule_body_list.append(e_rule)
                else:
                    LOG.debug('This network policy specifies no egress '
                              'ports: %s', policy['metadata']['selfLink'])

        return ingress_sg_rule_body_list, egress_sg_rule_body_list

    def _create_security_group_rule_body(
            self, security_group_id, direction, port_range_min,
            port_range_max=None, protocol='TCP', ethertype='IPv4',
            description="Kuryr-Kubernetes NetPolicy SG rule"):
        if not port_range_max:
            port_range_max = port_range_min
        security_group_rule_body = {
            u'security_group_rule': {
                u'ethertype': ethertype,
                u'security_group_id': security_group_id,
                u'description': description,
                u'direction': direction,
                u'protocol': protocol,
                u'port_range_min': port_range_min,
                u'port_range_max': port_range_max
            }
        }
        LOG.debug("Creating sg rule body %s", security_group_rule_body)
        return security_group_rule_body

    def _create_security_group_rule(self, body):
        sgr = ''
        try:
            sgr = self.neutron.create_security_group_rule(
                body=body)
        except n_exc.Conflict:
            LOG.debug("Failed to create already existing security group "
                      "rule %s", body)
        except n_exc.NeutronClientException:
            LOG.debug("Error creating security group rule")
            raise
        return sgr["security_group_rule"]["id"]

    def _delete_security_group_rule(self, security_group_rule_id):
        try:
            self.neutron.delete_security_group_rule(
                security_group_rule=security_group_rule_id)
        except n_exc.NotFound:
            LOG.debug("Error deleting security group rule as it does not "
                      "exist: %s", security_group_rule_id)
        except n_exc.NeutronClientException:
            LOG.debug("Error deleting security group rule: %s",
                      security_group_rule_id)
            raise

    def release_network_policy(self, policy, project_id):
        netpolicy_crd = self._get_kuryrnetpolicy_crd(policy)
        if netpolicy_crd is not None:
            try:
                sg_id = netpolicy_crd['spec']['securityGroupId']
                self.neutron.delete_security_group(sg_id)
            except n_exc.NotFound:
                LOG.debug("Security Group not found: %s", sg_id)
                raise
            except n_exc.Conflict:
                LOG.debug("Segurity Group already in use: %s", sg_id)
                raise
            except n_exc.NeutronClientException:
                LOG.exception("Error deleting security group %s.", sg_id)
                raise
            self._del_kuryrnetpolicy_crd(
                netpolicy_crd['metadata']['name'],
                netpolicy_crd['metadata']['namespace'])

    def _get_kuryrnetpolicy_crd(self, policy):
        netpolicy_crd_name = "np-" + policy['metadata']['name']
        netpolicy_crd_namespace = policy['metadata']['namespace']
        try:
            netpolicy_crd = self.kubernetes.get(
                '{}/{}/kuryrnetpolicies/{}'.format(
                    constants.K8S_API_CRD_NAMESPACES, netpolicy_crd_namespace,
                    netpolicy_crd_name))
        except exceptions.K8sResourceNotFound:
            return None
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return netpolicy_crd

    def _add_kuryrnetpolicy_crd(self, policy,  project_id, sg_id, i_rules,
                                e_rules):
        networkpolicy_name = policy['metadata']['name']
        netpolicy_crd_name = "np-" + networkpolicy_name
        namespace = policy['metadata']['namespace']

        netpolicy_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': constants.K8S_OBJ_KURYRNETPOLICY,
            'metadata': {
                'name': netpolicy_crd_name,
                'namespace': namespace,
                'annotations': {
                    'networkpolicy_name': networkpolicy_name,
                    'networkpolicy_namespace': namespace,
                    'networkpolicy_uid': policy['metadata']['uid'],
                },
            },
            'spec': {
                'securityGroupName': "sg-" + networkpolicy_name,
                'securityGroupId': sg_id,
                'ingressSgRules': i_rules,
                'egressSgRules': e_rules,
                'networkpolicy_spec': policy['spec']
            },
        }
        try:
            LOG.debug("Creating KuryrNetPolicy CRD %s" % netpolicy_crd)
            kubernetes_post = '{}/{}/kuryrnetpolicies'.format(
                constants.K8S_API_CRD_NAMESPACES,
                namespace)
            self.kubernetes.post(kubernetes_post, netpolicy_crd)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating kuryrnetpolicy"
                          " CRD. %s" % exceptions.K8sClientException)
            raise
        return netpolicy_crd

    def _del_kuryrnetpolicy_crd(self, netpolicy_crd_name,
                                netpolicy_crd_namespace):
        try:
            LOG.debug("Deleting KuryrNetPolicy CRD %s" % netpolicy_crd_name)
            self.kubernetes.delete('{}/{}/kuryrnetpolicies/{}'.format(
                constants.K8S_API_CRD_NAMESPACES,
                netpolicy_crd_namespace,
                netpolicy_crd_name))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception deleting kuryrnetpolicy"
                          " CRD.")
            raise
