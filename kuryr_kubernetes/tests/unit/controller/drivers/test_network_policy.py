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

from unittest import mock

from oslo_config import cfg

from kuryr_kubernetes.controller.drivers import network_policy
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix
from kuryr_kubernetes import utils

CONF = cfg.CONF


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
        self._i_rules = [{'sgRule': {'id': ''}}]
        self._e_rules = [{'sgRule': {'id': ''}}]

        self._policy = {
            'apiVersion': 'networking.k8s.io/v1',
            'kind': 'NetworkPolicy',
            'metadata': {
                'name': self._policy_name,
                'resourceVersion': '2259309',
                'generation': 1,
                'creationTimestamp': '2018-09-18T14:09:51Z',
                'namespace': 'default',
                'annotations': {},
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
                'policyTypes': ['Ingress', 'Egress'],
                'podSelector': {},
            }
        }

        self.crd = {
            'metadata': {'name': 'foobar',
                         'namespace': 'default'},
            'spec': {
                'egressSgRules': [
                    {'sgRule':
                        {'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                         'direction': 'egress',
                         'ethertype': 'IPv4',
                         'port_range_max': 5978,
                         'port_range_min': 5978,
                         'protocol': 'tcp',
                         }}],
                'ingressSgRules': [
                    {'sgRule':
                        {'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                         'direction': 'ingress',
                         'ethertype': 'IPv4',
                         'port_range_max': 6379,
                         'port_range_min': 6379,
                         'protocol': 'tcp',
                         }}],
                'podSelector': {},
                'policyTypes': self._policy['spec']['policyTypes']
            },
            'status': {
                'securityGroupId': self._sg_id,
                'securityGroupRules': [],
                'podSelector': {},
            }
        }

        self.old_crd = {
            'metadata': {'name': 'np-foobar',
                         'namespace': 'default'},
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
                'podSelector': {},
                'networkpolicy_spec': self._policy['spec'],
                'securityGroupId': self._sg_id,
                'securityGroupName': mock.sentinel.sg_name}}

        self.neutron = self.useFixture(k_fix.MockNetworkClient()).client
        self.kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        self._driver = network_policy.NetworkPolicyDriver()

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_default_np_rules')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_knp_crd', return_value=False)
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_create_knp_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_parse_network_policy_rules')
    @mock.patch.object(utils, 'get_subnet_cidr')
    def test_ensure_network_policy(self, m_utils, m_parse, m_add_crd,
                                   m_get_crd, m_get_default):
        m_utils.get_subnet_cidr.return_value = mock.sentinel.cidr
        m_parse.return_value = (self._i_rules, self._e_rules)
        self.kubernetes.get = mock.Mock(return_value={})
        self._driver.ensure_network_policy(self._policy)
        m_get_crd.assert_called_once()
        m_add_crd.assert_called_once()
        m_get_default.assert_called_once()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule_body')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_default_np_rules')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_knp_crd', return_value=False)
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_create_knp_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_parse_network_policy_rules')
    @mock.patch.object(utils, 'get_subnet_cidr')
    def test_ensure_network_policy_services(self, m_utils, m_parse, m_add_crd,
                                            m_get_crd, m_get_default,
                                            m_create_sgr):
        CONF.set_override('enforce_sg_rules', False, group='octavia_defaults')
        self.addCleanup(CONF.set_override, 'enforce_sg_rules', True,
                        group='octavia_defaults')
        m_utils.get_subnet_cidr.return_value = mock.sentinel.cidr
        m_parse.return_value = (self._i_rules, self._e_rules)
        svcs = [
            {'metadata': {'name': 'foo', 'deletionTimestamp': 'foobar'}},
            {'metadata': {'name': 'bar'}, 'spec': {'clusterIP': 'None'}},
            {'metadata': {'name': 'baz'}, 'spec': {'clusterIP': None}},
            {'metadata': {'name': ''}, 'spec': {'clusterIP': '192.168.0.130'}},
        ]
        self.kubernetes.get = mock.Mock(return_value={'items': svcs})
        self._driver.ensure_network_policy(self._policy)
        m_create_sgr.assert_called_once_with('ingress', cidr='192.168.0.130',
                                             description=mock.ANY)
        m_get_crd.assert_called_once()
        m_add_crd.assert_called_once()
        m_get_default.assert_called_once()

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_default_np_rules')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_knp_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_parse_network_policy_rules')
    @mock.patch.object(utils, 'get_subnet_cidr')
    def test_ensure_network_policy_with_k8s_exc(self, m_utils, m_parse,
                                                m_get_crd, m_get_default):
        m_utils.get_subnet_cidr.return_value = mock.sentinel.cidr
        m_parse.return_value = (self._i_rules, self._e_rules)
        m_get_crd.side_effect = exceptions.K8sClientException
        self.kubernetes.get = mock.Mock(return_value={})
        self.assertRaises(exceptions.K8sClientException,
                          self._driver.ensure_network_policy, self._policy)
        m_get_default.assert_called_once()

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_default_np_rules')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_get_knp_crd', return_value=None)
    @mock.patch.object(network_policy.NetworkPolicyDriver, '_create_knp_crd')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_parse_network_policy_rules')
    @mock.patch.object(utils, 'get_subnet_cidr')
    def test_ensure_network_policy_error_add_crd(
            self, m_utils, m_parse, m_add_crd, m_get_crd, m_get_default):
        m_utils.get_subnet_cidr.return_value = mock.sentinel.cidr
        m_parse.return_value = (self._i_rules, self._e_rules)
        m_add_crd.side_effect = exceptions.K8sClientException
        self.kubernetes.get = mock.Mock(return_value={})
        self.assertRaises(exceptions.K8sClientException,
                          self._driver.ensure_network_policy, self._policy)
        m_get_crd.assert_called()
        m_get_default.assert_called_once()

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
        self._driver._parse_network_policy_rules(self._policy)
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
        self._driver._parse_network_policy_rules(policy)
        m_get_ns.assert_not_called()
        calls = [mock.call('ingress', ethertype='IPv4'),
                 mock.call('ingress', ethertype='IPv6'),
                 mock.call('egress', ethertype='IPv4'),
                 mock.call('egress', ethertype='IPv6')]
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
        self._driver._parse_network_policy_rules(policy)
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
        self._driver._parse_network_policy_rules(policy)
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
        policy['spec']['egress'] = [{'to': [selectors]}]
        policy['spec']['ingress'] = [{'from': [selectors]}]
        self._driver._parse_network_policy_rules(policy)
        m_get_namespaces.assert_called()
        m_get_resource_details.assert_called()
        calls = [mock.call('ingress', cidr=subnet_cidr, namespace=namespace),
                 mock.call('egress', cidr=subnet_cidr, namespace=namespace)]
        m_create.assert_has_calls(calls)

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
                       '_del_knp_crd', return_value=False)
    def test_release_network_policy(self, m_del_crd):
        self._driver.release_network_policy(self.crd)
        m_del_crd.assert_called_once_with(self.crd)

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_create_sg_rules_with_container_ports')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_ports')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pods')
    def test__create_sg_rule_body_on_text_port_ingress(self,
                                                       m_get_pods,
                                                       m_get_ports,
                                                       m_create_sgr_cont):
        pod = mock.sentinel.pod
        port = mock.sentinel.port
        container_ports = mock.sentinel.ports
        resources = [mock.sentinel.resource]
        crd_rules = mock.sentinel.crd_rules
        pod_selector = {}
        namespace = mock.sentinel.namespace
        direction = 'ingress'

        m_get_pods.return_value = {'items': [pod]}
        m_get_ports.return_value = container_ports

        self._driver._create_sg_rule_body_on_text_port(direction,
                                                       port,
                                                       resources,
                                                       crd_rules,
                                                       pod_selector,
                                                       namespace)

        m_get_pods.assert_called_with(pod_selector, namespace)
        m_get_ports.assert_called_with(pod, port)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule_body')
    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_create_sg_rules_with_container_ports')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_ports')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pods')
    def test__create_sg_rule_body_on_text_port_ingress_all(self,
                                                           m_get_pods,
                                                           m_get_ports,
                                                           m_create_sgr_cont,
                                                           m_create_sgr):
        pod = mock.sentinel.pod
        port = mock.sentinel.port
        container_ports = mock.sentinel.ports
        resources = [mock.sentinel.resource]
        crd_rules = mock.sentinel.crd_rules
        pod_selector = {}
        namespace = mock.sentinel.namespace
        direction = 'ingress'
        cidrs = ['0.0.0.0/0']

        m_get_pods.return_value = {'items': [pod]}
        m_get_ports.return_value = container_ports

        self._driver._create_sg_rule_body_on_text_port(direction,
                                                       port,
                                                       resources,
                                                       crd_rules,
                                                       pod_selector,
                                                       namespace,
                                                       allowed_cidrs=cidrs)

        m_get_pods.assert_called_with(pod_selector, namespace)
        m_get_ports.assert_called_with(pod, port)
        m_create_sgr.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule_body')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_ports')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pods')
    def test__create_sg_rule_body_on_text_port_ingress_match(self,
                                                             m_get_pods,
                                                             m_get_ports,
                                                             m_create_sgr):

        def _create_sgr_cont(container_ports, allow_all, resource,
                             matched_pods, crd_rules, direction, port,
                             pod_selector=None, policy_namespace=None):
            matched_pods[container_ports[0][1]] = 'foo'

        pod = mock.sentinel.pod
        port = {'protocol': 'TCP', 'port': 22}
        container_ports = [("pod", mock.sentinel.container_port)]
        resources = [mock.sentinel.resource]
        crd_rules = []
        pod_selector = {}
        namespace = mock.sentinel.namespace
        direction = 'ingress'
        cidrs = ['0.0.0.0/0']
        self._driver._create_sg_rules_with_container_ports = _create_sgr_cont

        m_get_pods.return_value = {'items': [pod]}
        m_get_ports.return_value = container_ports

        self._driver._create_sg_rule_body_on_text_port(direction,
                                                       port,
                                                       resources,
                                                       crd_rules,
                                                       pod_selector,
                                                       namespace,
                                                       allowed_cidrs=cidrs)

        m_get_pods.assert_called_with(pod_selector, namespace)
        m_get_ports.assert_called_with(pod, port)

        m_create_sgr.assert_called_once_with(direction, container_ports[0][1],
                                             protocol=port['protocol'],
                                             cidr=cidrs[0],
                                             pods='foo')

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_create_sg_rules_with_container_ports')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_ports')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pods')
    def test__create_sg_rule_body_on_text_port_egress(self,
                                                      m_get_pods,
                                                      m_get_ports,
                                                      m_create_sgr_cont):
        pod = mock.sentinel.pod
        port = mock.sentinel.port
        container_ports = mock.sentinel.ports
        resources = [{'spec': 'foo'}]
        crd_rules = mock.sentinel.crd_rules
        pod_selector = {}
        namespace = mock.sentinel.namespace
        direction = 'egress'

        m_get_pods.return_value = {'items': [pod]}
        m_get_ports.return_value = container_ports

        self._driver._create_sg_rule_body_on_text_port(direction,
                                                       port,
                                                       resources,
                                                       crd_rules,
                                                       pod_selector,
                                                       namespace)

        m_get_ports.assert_called_with(resources[0], port)

    @mock.patch.object(network_policy.NetworkPolicyDriver,
                       '_create_sg_rules_with_container_ports')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_ports')
    def test__create_sg_rule_body_on_text_port_egress_all(self,
                                                          m_get_ports,
                                                          m_create_sgr_cont):
        port = {'protocol': 'TCP', 'port': 22}
        container_ports = mock.sentinel.ports
        resources = [{'spec': 'foo'}]
        crd_rules = []
        pod_selector = {}
        namespace = mock.sentinel.namespace
        direction = 'egress'
        cidrs = ['0.0.0.0/0']

        m_get_ports.return_value = container_ports

        self._driver._create_sg_rule_body_on_text_port(direction,
                                                       port,
                                                       resources,
                                                       crd_rules,
                                                       pod_selector,
                                                       namespace,
                                                       allowed_cidrs=cidrs)

        m_get_ports.assert_called_with(resources[0], port)
        self.assertEqual(len(crd_rules), 0)

    @mock.patch('kuryr_kubernetes.utils.get_subnet_cidr')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule_body')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_ports')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pods')
    def test__create_sg_rule_body_on_text_port_egress_match(self,
                                                            m_get_pods,
                                                            m_get_ports,
                                                            m_create_sgr,
                                                            m_get_subnet_cidr):

        def _create_sgr_cont(container_ports, allow_all, resource,
                             matched_pods, crd_rules, sg_id, direction, port,
                             pod_selector=None, policy_namespace=None):
            matched_pods[container_ports[0][1]] = 'foo'

        pod = mock.sentinel.pod
        port = {'protocol': 'TCP', 'port': 22}
        container_ports = [("pod", mock.sentinel.container_port)]
        resources = [{'spec': 'foo'}]
        crd_rules = []
        pod_selector = {}
        namespace = mock.sentinel.namespace
        direction = 'egress'
        cidrs = ['0.0.0.0/0']
        self._driver._create_sg_rules_with_container_ports = _create_sgr_cont
        m_get_subnet_cidr.return_value = '10.0.0.128/26'
        m_create_sgr.side_effect = [mock.sentinel.sgr1, mock.sentinel.sgr2,
                                    mock.sentinel.sgr3]

        m_get_pods.return_value = {'items': [pod]}
        m_get_ports.return_value = container_ports

        self._driver._create_sg_rule_body_on_text_port(direction,
                                                       port,
                                                       resources,
                                                       crd_rules,
                                                       pod_selector,
                                                       namespace,
                                                       allowed_cidrs=cidrs)

        m_get_ports.assert_called_with(resources[0], port)
        m_create_sgr.assert_called_once_with(direction, container_ports[0][1],
                                             protocol=port['protocol'],
                                             cidr=cidrs[0], pods='foo')

    def test__create_all_pods_sg_rules(self):
        port = {'protocol': 'TCP', 'port': 22}
        direction = 'ingress'
        rules = []

        self._driver._create_all_pods_sg_rules(port, direction, rules, '',
                                               None)
        self.assertEqual(len(rules), 2)

    def test__create_default_sg_rule(self):
        for direction in ('ingress', 'egress'):
            rules = []

            self._driver._create_default_sg_rule(direction, rules)
            self.assertEqual(len(rules), 2)
            self.assertListEqual(rules, [{'sgRule': {
                'ethertype': e,
                'direction': direction,
                'description': 'Kuryr-Kubernetes NetPolicy SG rule'
                }} for e in ('IPv4', 'IPv6')])
