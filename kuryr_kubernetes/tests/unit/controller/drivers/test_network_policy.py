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

import mock

from kuryr_kubernetes.controller.drivers import network_policy
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix
from kuryr_kubernetes import utils

from neutronclient.common import exceptions as n_exc


def get_pod_obj():
    return {
        'status': {
            'qosClass': 'BestEffort',
            'hostIP': '192.168.1.2',
        },
        'kind': 'Pod',
        'spec': {
            'schedulerName': 'default-scheduler',
            'containers': [{
                'name': 'busybox',
                'image': 'busybox',
                'resources': {}
            }],
            'nodeName': 'kuryr-devstack'
        },
        'metadata': {
            'name': 'busybox-sleep1',
            'namespace': 'default',
            'resourceVersion': '53808',
            'selfLink': '/api/v1/namespaces/default/pods/busybox-sleep1',
            'uid': '452176db-4a85-11e7-80bd-fa163e29dbbb',
            'annotations': {
                'openstack.org/kuryr-vif': {}
            }
        }}


def get_namespace_obj():
    return {
        "kind": "Namespace",
        "metadata": {
            "annotations": {
                "openstack.org/kuryr-namespace-label":
                    "{\"projetc\": \"myproject\"}",
                "openstack.org/kuryr-net-crd": "ns-myproject"
            },
            "labels": {
                "project": "myproject"
            },
            "name": "myproject"}}


class TestNetworkPolicyDriver(test_base.TestCase):

    def setUp(self):
        super(TestNetworkPolicyDriver, self).setUp()
        self._project_id = mock.sentinel.project_id
        self._policy_name = 'np-test'
        self._policy_uid = mock.sentinel.policy_uid
        self._policy_link = mock.sentinel.policy_link
        self._sg_id = mock.sentinel.sg_id
        self._i_rules = [{'security_group_rule': {'id': ''}}]
        self._e_rules = [{'security_group_rule': {'id': ''}}]

        self._policy = {
            'apiVersion': u'networking.k8s.io/v1',
            'kind': u'NetworkPolicy',
            'metadata': {
                'name': self._policy_name,
                'resourceVersion': u'2259309',
                'generation': 1,
                'creationTimestamp': u'2018-09-18T14:09:51Z',
                'namespace': u'default',
                'annotations': {},
                'selfLink': self._policy_link,
                'uid': self._policy_uid
            },
            'spec': {
                'egress': [{'ports':
                            [{'port': 5978, 'protocol': 'TCP'}],
                            'to':
                                [{'namespaceSelector': {
                                    'matchLabels': {
                                        'project': 'myproject'}}}]}],
                'ingress': [{'ports':
                             [{'port': 6379, 'protocol': 'TCP'}],
                            'from':
                                [{'namespaceSelector': {
                                    'matchLabels': {
                                        'project': 'myproject'}}}]}],
                'policyTypes': ['Ingress', 'Egress']
            }
        }

        self._crd = {
            'metadata': {'name': mock.sentinel.name,
                         'namespace': u'default',
                         'selfLink': mock.sentinel.selfLink},
            'spec': {
                'egressSgRules': [
                    {'security_group_rule':
                     {'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                      'direction': 'egress',
                      'ethertype': 'IPv4',
                      'port_range_max': 5978,
                      'port_range_min': 5978,
                      'protocol': 'tcp',
                      'security_group_id': self._sg_id,
                      'id': mock.sentinel.id
                      }}],
                'ingressSgRules': [
                    {'security_group_rule':
                     {'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                      'direction': 'ingress',
                      'ethertype': 'IPv4',
                      'port_range_max': 6379,
                      'port_range_min': 6379,
                      'protocol': 'tcp',
                      'security_group_id': self._sg_id,
                      'id': mock.sentinel.id
                      }}],
                'networkpolicy_spec': self._policy['spec'],
                'securityGroupId': self._sg_id,
                'securityGroupName': mock.sentinel.sg_name}}

        self.neutron = self.useFixture(k_fix.MockNeutronClient()).client
        self.kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        self._driver = network_policy.NetworkPolicyDriver()

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'get_kuryrnetpolicy_crd', return_value=False)
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'create_security_group_rules_from_network_policy')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'update_security_group_rules_from_network_policy')
    def test_ensure_network_policy(self, m_update, m_create, m_get_crd):
        self._driver.ensure_network_policy(self._policy, self._project_id)

        m_get_crd.assert_called_once_with(self._policy)
        m_create.assert_called_once_with(self._policy, self._project_id)
        m_update.assert_not_called()

    @mock.patch.object(network_policy.NetworkPolicyDriver, 'affected_pods')
    @mock.patch.object(network_policy.NetworkPolicyDriver, 'namespaced_pods')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'get_kuryrnetpolicy_crd', return_value=True)
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'create_security_group_rules_from_network_policy')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'update_security_group_rules_from_network_policy')
    def test_ensure_network_policy_with_existing_crd(
            self, m_update, m_create, m_get_crd, m_namespaced, m_affected):
        previous_selector = mock.sentinel.previous_selector
        m_update.return_value = previous_selector
        self._driver.ensure_network_policy(self._policy, self._project_id)

        m_get_crd.assert_called_once_with(self._policy)
        m_create.assert_not_called()
        m_update.assert_called_once_with(self._policy)
        m_affected.assert_called_once_with(self._policy, previous_selector)
        m_namespaced.assert_not_called()

    @mock.patch.object(network_policy.NetworkPolicyDriver, 'affected_pods')
    @mock.patch.object(network_policy.NetworkPolicyDriver, 'namespaced_pods')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'get_kuryrnetpolicy_crd', return_value=True)
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'create_security_group_rules_from_network_policy')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'update_security_group_rules_from_network_policy')
    def test_ensure_network_policy_with_existing_crd_no_selector(
            self, m_update, m_create, m_get_crd, m_namespaced, m_affected):
        m_update.return_value = None
        self._driver.ensure_network_policy(self._policy, self._project_id)

        m_get_crd.assert_called_once_with(self._policy)
        m_create.assert_not_called()
        m_update.assert_called_once_with(self._policy)
        m_affected.assert_not_called()
        m_namespaced.assert_called_once_with(self._policy)

    @mock.patch.object(network_policy.NetworkPolicyDriver, 'affected_pods')
    @mock.patch.object(network_policy.NetworkPolicyDriver, 'namespaced_pods')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'get_kuryrnetpolicy_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'create_security_group_rules_from_network_policy')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'update_security_group_rules_from_network_policy')
    def test_ensure_network_policy_with_existing_crd_empty_selector(
            self, m_update, m_create, m_get_crd, m_namespaced, m_affected):
        previous_selector = {}
        pod_selector = {'matchLabels': {'run': 'demo'}}
        updated_policy = self._policy.copy()
        updated_policy['spec']['podSelector'] = pod_selector
        crd_with_empty_selector = self._crd.copy()
        crd_with_empty_selector['spec']['podSelector'] = previous_selector

        m_get_crd.return_value = crd_with_empty_selector
        m_update.return_value = previous_selector

        self._driver.ensure_network_policy(updated_policy, self._project_id)

        m_get_crd.assert_called_once_with(updated_policy)
        m_create.assert_not_called()
        m_update.assert_called_once_with(updated_policy)
        m_affected.assert_called_with(self._policy, previous_selector)
        m_namespaced.assert_not_called()

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_add_default_np_rules')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'get_kuryrnetpolicy_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_add_kuryrnetpolicy_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'parse_network_policy_rules')
    @mock.patch.object(utils, 'get_subnet_cidr')
    def test_create_security_group_rules_from_network_policy(self, m_utils,
                                                             m_parse,
                                                             m_add_crd,
                                                             m_get_crd,
                                                             m_add_default):
        self._driver.neutron.create_security_group.return_value = {
            'security_group': {'id': mock.sentinel.id,
                               'security_group_rules': []}}
        m_utils.get_subnet_cidr.return_value = {
            'subnet': {'cidr': mock.sentinel.cidr}}
        m_parse.return_value = (self._i_rules, self._e_rules)
        self._driver.neutron.create_security_group_rule.return_value = {
            'security_group_rule': {'id': mock.sentinel.id}}
        self._driver.create_security_group_rules_from_network_policy(
            self._policy, self._project_id)
        m_get_crd.assert_called_once()
        m_add_crd.assert_called_once()
        m_add_default.assert_called_once()

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_add_default_np_rules')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'get_kuryrnetpolicy_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_add_kuryrnetpolicy_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'parse_network_policy_rules')
    @mock.patch.object(utils, 'get_subnet_cidr')
    def test_create_security_group_rules_with_k8s_exc(self, m_utils, m_parse,
                                                      m_add_crd, m_get_crd,
                                                      m_add_default):
        self._driver.neutron.create_security_group.return_value = {
            'security_group': {'id': mock.sentinel.id,
                               'security_group_rules': []}}
        m_utils.get_subnet_cidr.return_value = {
            'subnet': {'cidr': mock.sentinel.cidr}}
        m_parse.return_value = (self._i_rules, self._e_rules)
        m_get_crd.side_effect = exceptions.K8sClientException
        self._driver.neutron.create_security_group_rule.return_value = {
            'security_group_rule': {'id': mock.sentinel.id}}
        self.assertRaises(
            exceptions.K8sClientException,
            self._driver.create_security_group_rules_from_network_policy,
            self._policy, self._project_id)
        m_add_crd.assert_called_once()
        m_add_default.assert_called_once()

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_add_default_np_rules')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'get_kuryrnetpolicy_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_add_kuryrnetpolicy_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'parse_network_policy_rules')
    @mock.patch.object(utils, 'get_subnet_cidr')
    def test_create_security_group_rules_error_add_crd(self, m_utils, m_parse,
                                                       m_add_crd, m_get_crd,
                                                       m_add_default):
        self._driver.neutron.create_security_group.return_value = {
            'security_group': {'id': mock.sentinel.id,
                               'security_group_rules': []}}
        m_utils.get_subnet_cidr.return_value = {
            'subnet': {'cidr': mock.sentinel.cidr}}
        m_parse.return_value = (self._i_rules, self._e_rules)
        m_add_crd.side_effect = exceptions.K8sClientException
        self._driver.neutron.create_security_group_rule.return_value = {
            'security_group_rule': {'id': mock.sentinel.id}}
        self.assertRaises(
            exceptions.K8sClientException,
            self._driver.create_security_group_rules_from_network_policy,
            self._policy, self._project_id)
        m_get_crd.assert_not_called()
        m_add_default.assert_called_once()

    def test_create_security_group_rules_with_n_exc(self):
        self._driver.neutron.create_security_group.side_effect = (
            n_exc.NeutronClientException())
        self.assertRaises(
            n_exc.NeutronClientException,
            self._driver.create_security_group_rules_from_network_policy,
            self._policy, self._project_id)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'get_kuryrnetpolicy_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'parse_network_policy_rules')
    def test_update_security_group_rules(self, m_parse, m_get_crd,
                                         m_create_sgr):
        policy = self._policy.copy()
        policy['spec']['podSelector'] = {'matchLabels': {'test': 'test'}}
        m_get_crd.return_value = self._crd
        m_parse.return_value = (self._i_rules, self._e_rules)
        self._driver.update_security_group_rules_from_network_policy(
            policy)
        m_parse.assert_called_with(policy, self._sg_id)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'get_kuryrnetpolicy_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       'parse_network_policy_rules')
    def test_update_security_group_rules_with_k8s_exc(self, m_parse, m_get_crd,
                                                      m_create_sgr):
        self._driver.kubernetes.patch_crd.side_effect = (
            exceptions.K8sClientException())
        m_get_crd.return_value = self._crd
        m_parse.return_value = (self._i_rules, self._e_rules)
        self.assertRaises(
            exceptions.K8sClientException,
            self._driver.update_security_group_rules_from_network_policy,
            self._policy)
        m_parse.assert_called_with(self._policy, self._sg_id)

    def test_get_namespaces(self):
        namespace_selector = {'namespaceSelector': {
                              'matchLabels': {'project': 'myproject'}}}
        self.kubernetes.get.side_effect = [{'items': [get_namespace_obj()]}]

        resp = self._driver._get_namespaces(namespace_selector)
        self.assertEqual([get_namespace_obj()], resp)
        self.kubernetes.get.assert_called()

    def test_get_namespaces_no_matches(self):
        namespace_selector = {'matchLabels': {'test': 'test'}}
        self.kubernetes.get.return_value = {'items': []}

        resp = self._driver._get_namespaces(namespace_selector)
        self.assertEqual([], resp)
        self.kubernetes.get.assert_called_once()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_resource_details')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_namespaces')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule_body')
    def test_parse_network_policy_rules_with_rules(
            self, m_create, m_get_namespaces,
            m_get_resource_details, m_get_svcs):
        subnet_cidr = '10.10.0.0/24'
        namespace = 'myproject'
        m_get_namespaces.return_value = [get_namespace_obj()]
        m_get_resource_details.return_value = subnet_cidr, namespace
        self._driver.parse_network_policy_rules(self._policy, self._sg_id)
        m_get_namespaces.assert_called()
        m_get_resource_details.assert_called()
        m_create.assert_called()

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_namespaces')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule_body')
    def test_parse_network_policy_rules_with_no_rules(self, m_create,
                                                      m_get_ns):
        policy = self._policy.copy()
        policy['spec']['ingress'] = [{}]
        policy['spec']['egress'] = [{}]
        self._driver.parse_network_policy_rules(policy, self._sg_id)
        m_get_ns.assert_not_called()
        calls = [mock.call(self._sg_id, 'ingress'),
                 mock.call(self._sg_id, 'egress')]
        m_create.assert_has_calls(calls)

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_create_all_pods_sg_rules')
    def test_parse_network_policy_rules_with_no_pod_selector(
            self, m_create_all_pods_sg_rules):
        policy = self._policy.copy()
        policy['spec']['ingress'] = [{'ports':
                                      [{'port': 6379, 'protocol': 'TCP'}]}]
        policy['spec']['egress'] = [{'ports':
                                     [{'port': 6379, 'protocol': 'TCP'}]}]
        self._driver.parse_network_policy_rules(policy, self._sg_id)
        m_create_all_pods_sg_rules.assert_called()

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_create_sg_rule_on_number_port')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_namespaces')
    def test_parse_network_policy_rules_with_ipblock(self,
                                                     m_get_namespaces,
                                                     m_create_sg_rule):
        policy = self._policy.copy()
        policy['spec']['ingress'] = [{'from':
                                      [{'ipBlock':
                                        {'cidr': '172.17.0.0/16',
                                         'except': ['172.17.1.0/24']}}],
                                      'ports': [{'port': 6379,
                                                 'protocol': 'TCP'}]}]
        policy['spec']['egress'] = [{'ports': [{'port': 5978, 'protocol':
                                                'TCP'}],
                                     'to': [{'ipBlock':
                                             {'cidr': '10.0.0.0/24'}}]}]
        self._driver.parse_network_policy_rules(policy, self._sg_id)
        m_create_sg_rule.assert_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_resource_details')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_namespaces')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule_body')
    def test_parse_network_policy_rules_with_no_ports(
            self, m_create, m_get_namespaces, m_get_resource_details,
            m_get_svcs):
        subnet_cidr = '10.10.0.0/24'
        namespace = 'myproject'
        m_get_namespaces.return_value = [get_namespace_obj()]
        m_get_resource_details.return_value = subnet_cidr, namespace
        policy = self._policy.copy()
        selectors = {'namespaceSelector': {
                     'matchLabels': {
                         'project': 'myproject'}}}
        policy['spec']['egress'] = [
            {'to':
                [selectors]}]
        policy['spec']['ingress'] = [
            {'from':
                [selectors]}]
        selectors = {'namespace_selector': selectors['namespaceSelector']}
        self._driver.parse_network_policy_rules(policy, self._sg_id)
        m_get_namespaces.assert_called()
        m_get_resource_details.assert_called()
        calls = [mock.call(self._sg_id, 'ingress', port_range_min=1,
                           port_range_max=65535, cidr=subnet_cidr,
                           namespace=namespace),
                 mock.call(self._sg_id, 'egress', port_range_min=1,
                           port_range_max=65535, cidr=subnet_cidr,
                           namespace=namespace)]
        m_create.assert_has_calls(calls)

    def test_knps_on_namespace(self):
        self.kubernetes.get.return_value = {'items': ['not-empty']}
        namespace = 'test1'

        resp = self._driver.knps_on_namespace(namespace)
        self.assertTrue(resp)

    def test_knps_on_namespace_empty(self):
        self.kubernetes.get.return_value = {'items': []}
        namespace = 'test1'

        resp = self._driver.knps_on_namespace(namespace)
        self.assertFalse(resp)

    @mock.patch.object(network_policy.NetworkPolicyDriver, 'namespaced_pods')
    def test_affected_pods(self, m_namespaced):
        self._driver.affected_pods(self._policy)
        m_namespaced.assert_called_once_with(self._policy)
        self.kubernetes.assert_not_called()

    @mock.patch.object(network_policy.NetworkPolicyDriver, 'namespaced_pods')
    def test_affected_pods_with_podselector(self, m_namespaced):
        self.kubernetes.get.return_value = {'items': []}
        selector = {'matchLabels': {'test': 'test'}}
        self._driver.affected_pods(self._policy, selector)
        m_namespaced.assert_not_called()

    @mock.patch.object(network_policy.NetworkPolicyDriver, 'namespaced_pods')
    def test_affected_pods_with_empty_podselector(self, m_namespaced):
        m_namespaced.return_value = []
        pod_selector = {}
        self._driver.affected_pods(self._policy, pod_selector)
        m_namespaced.assert_called_with(self._policy)

    def test_namespaced_pods(self):
        self.kubernetes.get.return_value = {'items': []}

        resp = self._driver.namespaced_pods(self._policy)
        self.assertEqual([], resp)

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_del_kuryrnetpolicy_crd', return_value=False)
    def test_release_network_policy(self, m_del_crd):
        self._driver.release_network_policy(self._crd)
        self.neutron.delete_security_group.assert_called_once_with(
            self._crd['spec']['securityGroupId'])
        m_del_crd.assert_called_once_with(self._crd['metadata']['name'],
                                          self._crd['metadata']['namespace'])

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_del_kuryrnetpolicy_crd', return_value=False)
    def test_release_network_policy_removed_crd(self, m_del_crd):
        self._driver.release_network_policy(None)
        m_del_crd.assert_not_called()
