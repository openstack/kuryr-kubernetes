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
    """Provides security groups actions based on K8s Network Policies"""

    def ensure_network_policy(self, policy, project_id):
        neutron = clients.get_neutron_client()
        LOG.debug("Creating network policy %s" % policy['metadata']['name'])
        if self._get_kuryrnetpolicy_crd(policy):
            LOG.debug("Already existing CRD")
            return
        security_group_body = {
            "security_group":
            {
                "name": policy['metadata']['name'],
                "project_id": project_id,
                "description": "Kuryr-Kubernetes NetPolicy SG"
                }
            }
        try:
            sg = neutron.create_security_group(body=security_group_body)
            i_rules, e_rules = self.apply_network_policy_rules(policy, sg)
        except n_exc.NeutronClientException:
            LOG.exception("Error creating security group for network policy. ")
            raise
        try:
            self._add_kuryrnetpolicy_crd(policy, project_id,
                                         sg['security_group']['id'], i_rules,
                                         e_rules)
        except exceptions.K8sClientException:
            LOG.exception("Rolling back security groups")
            neutron.delete_security_group(sg['security_group']['id'])
            raise

    def apply_network_policy_rules(self, policy, sg):
        """Creates and applies security group rules out of network policies.

        Whenever a notification from the handler 'on-present' method is
        received, security group rules are created out of network policies'
        ingress and egress ports blocks.
        """
        LOG.debug('Parsing Network Policy %s' % policy['metadata']['name'])
        ingress_rule_list = policy['spec']['ingress']
        egress_rule_list = policy['spec']['egress']
        ingress_sg_rule_list = []
        egress_sg_rule_list = []
        for ingress_rule in ingress_rule_list:
            LOG.debug('Parsing Ingress Rule %s' % ingress_rule)
            if 'ports' in ingress_rule:
                for port in ingress_rule['ports']:
                    i_rule = self._create_security_group_rule(
                        sg['security_group']['id'], 'ingress', port['port'],
                        protocol=port['protocol'].lower())
                    ingress_sg_rule_list.append(i_rule)
            else:
                LOG.debug('This network policy specifies no ingress ports')
        for egress_rule in egress_rule_list:
            LOG.debug('Parsing Egress Rule %s' % egress_rule)
            if 'ports' in egress_rule:
                for port in egress_rule['ports']:
                    e_rule = self._create_security_group_rule(
                        sg['security_group']['id'], 'egress', port['port'],
                        protocol=port['protocol'].lower())
                    egress_sg_rule_list.append(e_rule)
            else:
                LOG.debug('This network policy specifies no egress ports')
        return ingress_sg_rule_list, egress_sg_rule_list

    def _create_security_group_rule(
            self, security_group_id, direction, port_range_min,
            port_range_max=None, protocol='TCP', ethertype='IPv4',
            description="Kuryr-Kubernetes NetPolicy SG rule"):
        if not port_range_max:
            port_range_max = port_range_min
        security_group_rule_body = {
            "security_group_rule": {
                "ethertype": ethertype,
                "security_group_id": security_group_id,
                "description": description,
                "direction": direction,
                "protocol": protocol,
                "port_range_min": port_range_min,
                "port_range_max": port_range_max
            }
        }
        LOG.debug("Creating sg rule %s" % security_group_rule_body)
        neutron = clients.get_neutron_client()
        try:
            sg_rule = neutron.create_security_group_rule(
                body=security_group_rule_body)
        except n_exc.NeutronClientException:
            LOG.exception("Error creating security group rule for the network "
                          "policy.")
            raise
        return sg_rule

    def release_network_policy(self, policy, project_id):
        neutron = clients.get_neutron_client()
        netpolicy_crd = self._get_kuryrnetpolicy_crd(policy)
        if netpolicy_crd is not None:
            try:
                sg_id = netpolicy_crd['spec']['securityGroupId']
                neutron.delete_security_group(sg_id)
            except n_exc.NotFound:
                LOG.debug("Security Group not found: %s", sg_id)
            except n_exc.NeutronClientException:
                LOG.exception("Error deleting security group %s.", sg_id)
                raise
            self._del_kuryrnetpolicy_crd(
                netpolicy_crd['metadata']['name'],
                netpolicy_crd['metadata']['namespace'])

    def _get_kuryrnetpolicy_crd(self, policy):
        kubernetes = clients.get_kubernetes_client()
        netpolicy_crd_name = "np-" + policy['metadata']['name']
        netpolicy_crd_namespace = policy['metadata']['namespace']
        try:
            netpolicy_crd = kubernetes.get('{}/{}/kuryrnetpolicies/{}'.format(
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
        kubernetes = clients.get_kubernetes_client()
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
            kubernetes.post(kubernetes_post, netpolicy_crd)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating kuryrnetpolicy"
                          " CRD. %s" % exceptions.K8sClientException)
            raise
        return netpolicy_crd

    def _del_kuryrnetpolicy_crd(self, netpolicy_crd_name,
                                netpolicy_crd_namespace):
        kubernetes = clients.get_kubernetes_client()
        try:
            LOG.debug("Deleting KuryrNetPolicy CRD %s" % netpolicy_crd_name)
            kubernetes.delete('{}/{}/kuryrnetpolicies/{}'.format(
                constants.K8S_API_CRD_NAMESPACES,
                netpolicy_crd_namespace,
                netpolicy_crd_name))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception deleting kuryrnetpolicy"
                          " CRD.")
            raise
