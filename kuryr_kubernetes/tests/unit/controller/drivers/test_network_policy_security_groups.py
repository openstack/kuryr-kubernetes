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

from kuryr_kubernetes.controller.drivers import network_policy_security_groups
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix

from oslo_config import cfg


def get_no_match_crd_namespace_obj():
    return {
        "kind": "Namespace",
        "metadata": {
            "annotations": {
                "openstack.org/kuryr-namespace-label": '{"name": "dev"}',
                "openstack.org/kuryr-net-crd": "ns-dev"
            },
            "labels": {"name": "prod"},
            "name": "prod"}}


def get_match_crd_namespace_obj():
    return {
        "kind": "Namespace",
        "metadata": {
            "annotations": {
                "openstack.org/kuryr-namespace-label": '{"name": "dev"}',
                "openstack.org/kuryr-net-crd": "ns-dev"
            },
            "labels": {
                "name": "dev"
            },
            "name": "dev"}}


def get_match_crd_pod_obj():
    return {
        'kind': 'Pod',
        'metadata': {
            'name': mock.sentinel.pod_name,
            'namespace': 'dev',
            'labels': {
                'tier': 'backend'},
            'annotations': {
                'openstack.org/kuryr-pod-label': '{"tier": "backend"}'}},
        'status': {'podIP': mock.sentinel.podIP}}


def get_sg_rule():
    pod_ip = get_match_crd_pod_obj()['status'].get('podIP')
    return {
        "namespace": 'dev',
        "sgRule": {
            "description": "Kuryr-Kubernetes NetPolicy SG rule",
            "direction": "ingress",
            "ethertype": "IPv4",
            "id": 'f15ff50a-e8a4-4872-81bf-a04cbb8cb388',
            "port_range_max": 6379,
            "port_range_min": 6379,
            "protocol": "tcp",
            "remote_ip_prefix": pod_ip,
            "security_group_id": '36923e76-026c-422b-8dfd-7292e7c88228'}}


def get_matched_crd_obj():
    return {
        "kind": "KuryrNetworkPolicy",
        "metadata": {"name": "np-test-network-policy",
                     "namespace": "default"},
        "spec": {
            "egressSgRules": [],
            "ingressSgRules": [get_sg_rule()],
            "networkpolicy_spec": {
                "ingress": [
                    {"from": [
                        {"namespaceSelector": {
                            "matchLabels": {"name": "dev"}}}],
                     "ports": [
                        {"port": 6379,
                         "protocol": "TCP"}]}],
                "podSelector": {"matchLabels": {"app": "demo"}},
                "policyTypes": ["Ingress"]},
            "podSelector": {"matchLabels": {"app": "demo"}},
            "securityGroupId": '36923e76-026c-422b-8dfd-7292e7c88228'}}


def get_crd_obj_no_match():
    return {
        "kind": "KuryrNetworkPolicy",
        "metadata": {"name": "np-test-network-policy",
                     "namespace": "default"},
        "spec": {
            "egressSgRules": [],
            "ingressSgRules": [],
            "networkpolicy_spec": {
                "ingress": [
                    {"from": [
                        {"namespaceSelector": {
                            "matchLabels": {"name": "dev"}}}],
                     "ports": [
                        {"port": 6379,
                         "protocol": "TCP"}]}],
                "podSelector": {"matchLabels": {"app": "demo"}},
                "policyTypes": ["Ingress"]},
            "podSelector": {"matchLabels": {"app": "demo"}},
            "securityGroupId": '36923e76-026c-422b-8dfd-7292e7c88228'}}


def get_crd_obj_with_all_selectors():
    return {
        "kind": "KuryrNetworkPolicy",
        "metadata": {"name": "np-test-network-policy",
                     "namespace": "default"},
        "spec": {
            "egressSgRules": [],
            "ingressSgRules": [],
            "networkpolicy_spec": {
                "ingress": [
                    {"from": [
                        {"namespaceSelector": {
                            "matchLabels": {"name": "dev"}},
                         "podSelector": {
                            "matchLabels": {"tier": "backend"}}}],
                     "ports": [
                        {"port": 6379,
                         "protocol": "TCP"}]}],
                "podSelector": {"matchLabels": {"app": "demo"}},
                "policyTypes": ["Ingress"]},
            "podSelector": {"matchLabels": {"app": "demo"}},
            "securityGroupId": '36923e76-026c-422b-8dfd-7292e7c88228'}}


class TestNetworkPolicySecurityGroupsDriver(test_base.TestCase):

    def setUp(self):
        super(TestNetworkPolicySecurityGroupsDriver, self).setUp()
        self._project_id = mock.sentinel.project_id
        self._sg_id = mock.sentinel.sg_id
        self._sg_id2 = mock.sentinel._sg_id2
        self._namespace = 'default'
        self._crd = {
            'metadata': {'name': mock.sentinel.name},
            'spec': {
                'egressSgRules': [
                    {'sgRule':
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
                    {'sgRule':
                     {'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                      'direction': 'ingress',
                      'ethertype': 'IPv4',
                      'port_range_max': 6379,
                      'port_range_min': 6379,
                      'protocol': 'tcp',
                      'security_group_id': self._sg_id,
                      'id': mock.sentinel.id
                      }}],
                'podSelector': {
                    'matchExpressions': [
                        {
                            'key': 'environment',
                            'operator': 'In',
                            'values': [
                                'production']}],
                    'matchLabels': {
                        'run': 'demo'
                    }}},
            'status': {
                'securityGroupId': self._sg_id,
            },
        }

        self._crd2 = {
            'metadata': {'name': mock.sentinel.name3},
            'spec': {
                'ingressSgRules': [
                    {'sgRule':
                     {'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                      'direction': 'ingress',
                      'ethertype': 'IPv4',
                      'port_range_max': 8080,
                      'port_range_min': 8080,
                      'protocol': 'tcp',
                      'security_group_id': self._sg_id2,
                      'id': mock.sentinel.id
                      }}],
                'podSelector': {}},
            'status': {
                'securityGroupId': self._sg_id2,
                'securityGroupName': mock.sentinel.sg_name}}

        self._crds = [self._crd]

        self._multiple_crds = [self._crd, self._crd2]

        self._pod = {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {
                'name': mock.sentinel.pod_name,
                'namespace': self._namespace,
                'labels': {
                    'run': 'demo',
                    'environment': 'production'}},
            'spec': {
                'containers': [{
                    'image': 'quay.io/kuryr/demo',
                    'imagePullPolicy': 'Always',
                    'name': mock.sentinel.pod_name
                    }]
                }}

        self._pod2 = {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {
                'name': mock.sentinel.pod_name,
                'namespace': self._namespace,
                'labels': {
                    'run': 'demo',
                    'environment': 'development'},
                'annotations': {
                    'openstack.org/kuryr-pod-label': '{'
                    '"run": "demo","environment": "development"}'}},
            'spec': {
                'containers': [{
                    'image': 'quay.io/kuryr/demo',
                    'imagePullPolicy': 'Always',
                    'name': mock.sentinel.pod_name
                    }]
                }}

        self._pod_without_label = {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {
                'name': mock.sentinel.pod_name,
                'namespace': self._namespace},
            'spec': {
                'containers': [{
                    'image': 'quay.io/kuryr/demo',
                    'imagePullPolicy': 'Always',
                    'name': mock.sentinel.pod_name
                    }]
                }}

        self.kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        self._driver = (
            network_policy_security_groups.NetworkPolicySecurityGroupsDriver())

        self._pod_ip = mock.sentinel.pod_ip
        self._pod_dev_namespace = {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {
                'name': mock.sentinel.pod_name,
                'namespace': 'dev',
                'labels': {
                    'tier': 'backend'},
                'annotations': {
                    'openstack.org/kuryr-pod-label': '{"tier": "backend"}'}},
            'spec': {
                'containers': [{
                    'image': 'quay.io/kuryr/demo',
                    'imagePullPolicy': 'Always',
                    'name': mock.sentinel.pod_name
                    }]},
            'status': {'podIP': self._pod_ip}}

        self._crd_sg_id = mock.sentinel.crd_sg_id
        self._sg_rule_body = {
            'sgRule': {
                'direction': 'ingress',
                'protocol': 'tcp',
                'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                'ethertype': 'IPv4',
                'port_range_max': 6379,
                'security_group_id': self._crd_sg_id,
                'port_range_min': 6379,
                'remote_ip_prefix': self._pod_ip}}

        self._new_rule_id = mock.sentinel.id
        self._crd_with_rule = {
            "apiVersion": "openstack.org/v1",
            "kind": "KuryrNetworkPolicy",
            "metadata": {"name": "np-test-network-policy",
                          "namespace": "default"},
            "spec": {
                "egressSgRules": [],
                "ingressSgRules": [{
                    "sgRule": {
                        "description": "Kuryr-Kubernetes NetPolicy SG rule",
                        "direction": "ingress",
                        "ethertype": "IPv4",
                        "id": self._new_rule_id,
                        "port_range_max": 6379,
                        "port_range_min": 6379,
                        "protocol": "tcp",
                        "remote_ip_prefix": self._pod_ip,
                        "security_group_id": self._crd_sg_id}}],
                "networkpolicy_spec": {
                    "ingress": [
                        {"from": [
                            {"namespaceSelector": {
                                "matchLabels": {"name": "dev"}},
                             "podSelector": {
                                "matchLabels": {"tier": "backend"}}}],
                         "ports": [
                            {"port": 6379,
                             "protocol": "TCP"}]}],
                    "podSelector": {"matchLabels": {"app": "demo"}},
                    "policyTypes": ["Ingress"]},
                "podSelector": {"matchLabels": {"app": "demo"}},
                "securityGroupId": self._crd_sg_id}}

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_selector', return_value=True)
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_ip')
    def test__create_sg_rules(self, m_get_pod_ip,
                              m_match_selector):
        sgr_id = mock.sentinel.sgr_id
        crd = get_crd_obj_with_all_selectors()
        pod = get_match_crd_pod_obj()
        m_get_pod_ip.return_value = pod['status'].get('podIP')
        matched = False
        new_sg_rule = self._sg_rule_body

        policy = crd['spec']['networkpolicy_spec']
        rule_list = policy.get('ingress', None)
        pod_ns = pod['metadata']['namespace']

        for rule_block in rule_list:
            for rule in rule_block.get('from', []):
                pod_selector = rule.get('podSelector')
                matched = network_policy_security_groups._create_sg_rules(
                    crd, pod, pod_selector, rule_block, 'ingress', matched)
                new_sg_rule['namespace'] = pod_ns
                new_sg_rule['sgRule']['id'] = sgr_id
                m_match_selector.assert_called_once_with(
                    pod_selector, pod['metadata']['labels'])
                m_get_pod_ip.assert_called_once_with(pod)
                self.assertEqual(matched, True)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_pod_ip')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_selector', return_value=False)
    def test__create_sg_rules_no_match(self, m_match_selector, m_get_pod_ip):
        crd = get_crd_obj_with_all_selectors()
        pod = self._pod2

        policy = crd['spec']['networkpolicy_spec']
        rule_list = policy.get('ingress', None)

        for rule_block in rule_list:
            for rule in rule_block.get('from', []):
                pod_selector = rule.get('podSelector')
                matched = network_policy_security_groups._create_sg_rules(
                    crd, pod, pod_selector, rule_block, 'ingress', False)
                self.assertEqual(matched, False)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.bump_networkpolicy')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetworkpolicy_crds')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_ip')
    def test_delete_sg_rules(self, m_get_pod_ip, m_get_knp_crds, m_bump):
        crd = self._crd_with_rule
        m_get_pod_ip.return_value = self._pod_ip
        m_get_knp_crds.return_value = [crd]
        pod = self._pod_dev_namespace

        self._driver.delete_sg_rules(pod)

        m_get_knp_crds.assert_called_once()
        m_get_pod_ip.assert_called_once_with(pod)
        m_bump.assert_called_once()

    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetworkpolicy_crds')
    def test_get_sgs_for_pod_without_label(self, m_get_crds, m_cfg):
        m_get_crds.return_value = self._crds
        sg_list = [str(mock.sentinel.sg_id)]
        m_cfg.neutron_defaults.pod_security_groups = sg_list

        sgs = self._driver.get_security_groups(self._pod_without_label,
                                               self._project_id)

        m_get_crds.assert_called_once_with(namespace=self._namespace)
        self.assertEqual(sg_list, sgs)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_expressions')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_labels')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetworkpolicy_crds')
    def test_get_sgs_for_pod_with_label(self, m_get_crds, m_match_labels,
                                        m_match_expressions):
        m_get_crds.return_value = self._crds
        m_match_expressions.return_value = True
        m_match_labels.return_value = True
        pod_labels = self._pod['metadata']['labels']
        resp = self._driver.get_security_groups(self._pod, self._project_id)

        m_get_crds.assert_called_once_with(namespace=self._namespace)
        m_match_expressions.assert_called_once_with(
            self._crd['spec']['podSelector']['matchExpressions'], pod_labels)
        m_match_labels.assert_called_once_with(
            self._crd['spec']['podSelector']['matchLabels'], pod_labels)
        self.assertEqual(resp, [self._sg_id])

    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_expressions')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_labels')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetworkpolicy_crds')
    def test_get_sgs_for_pod_with_label_no_match(self, m_get_crds,
                                                 m_match_labels,
                                                 m_match_expressions, m_cfg):
        m_get_crds.return_value = self._crds
        m_match_expressions.return_value = False
        m_match_labels.return_value = True
        sg_list = [mock.sentinel.sg_id]
        m_cfg.neutron_defaults.pod_security_groups = sg_list
        pod_labels = self._pod2['metadata']['labels']

        sgs = self._driver.get_security_groups(self._pod2, self._project_id)

        m_get_crds.assert_called_once_with(namespace=self._namespace)
        m_match_expressions.assert_called_once_with(
            self._crd['spec']['podSelector']['matchExpressions'], pod_labels)
        m_match_labels.assert_called_once_with(
            self._crd['spec']['podSelector']['matchLabels'], pod_labels)
        self.assertEqual(sg_list, sgs)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetworkpolicy_crds')
    def test_get_sgs_no_crds(self, m_get_crds):
        m_get_crds.return_value = []
        cfg.CONF.set_override('pod_security_groups', [],
                              group='neutron_defaults')

        self.assertRaises(cfg.RequiredOptError,
                          self._driver.get_security_groups, self._pod,
                          self._project_id)
        m_get_crds.assert_called_with(namespace=self._namespace)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_expressions')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_labels')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetworkpolicy_crds')
    def test_get_sgs_multiple_crds(self, m_get_crds, m_match_labels,
                                   m_match_expressions):
        m_match_expressions.return_value = True
        m_match_labels.return_value = True
        m_get_crds.return_value = self._multiple_crds

        resp = self._driver.get_security_groups(self._pod, self._project_id)

        m_get_crds.assert_called_once_with(namespace=self._namespace)
        self.assertEqual([self._sg_id, self._sg_id2], resp)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.bump_networkpolicy')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetworkpolicy_crds')
    def test_delete_namespace_sg_rule(self, m_get_knp_crd, m_bump):
        cls = network_policy_security_groups.NetworkPolicySecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)

        m_get_knp_crd.return_value = [get_matched_crd_obj()]

        cls.delete_namespace_sg_rules(m_driver, get_match_crd_namespace_obj())

        m_get_knp_crd.assert_called_once()
        m_bump.assert_called_once()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.bump_networkpolicy')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'delete_security_group_rule')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetworkpolicy_crds')
    def test_delete_namespace_sg_rule_no_match(
            self, m_get_knp_crd, m_delete_sg_rule, m_bump):
        cls = network_policy_security_groups.NetworkPolicySecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)

        m_get_knp_crd.return_value = [get_matched_crd_obj()]

        cls.delete_namespace_sg_rules(m_driver,
                                      get_no_match_crd_namespace_obj())

        m_get_knp_crd.assert_called_once()
        m_delete_sg_rule.assert_not_called()
        m_bump.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pods')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.match_selector')
    def test__parse_rules(self, m_match_selector, m_get_pods):
        crd = get_crd_obj_no_match()
        policy = crd['spec']['networkpolicy_spec']
        i_rule = policy.get('ingress')[0]
        ns_selector = i_rule['from'][0].get('namespaceSelector')
        ns = get_match_crd_namespace_obj()

        m_match_selector.return_value = True

        matched = network_policy_security_groups._parse_rules(
            'ingress', crd, policy, namespace=ns)

        m_match_selector.assert_called_once_with(ns_selector,
                                                 ns['metadata']['labels'])

        self.assertEqual(matched, True)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.match_selector')
    def test__parse_rules_no_match(self, m_match_selector):
        crd = get_crd_obj_no_match()
        policy = crd['spec']['networkpolicy_spec']
        i_rule = policy.get('ingress')[0]
        ns_selector = i_rule['from'][0].get('namespaceSelector')
        ns = get_no_match_crd_namespace_obj()

        m_match_selector.return_value = False

        matched = network_policy_security_groups._parse_rules(
            'ingress', crd, policy, namespace=ns)

        m_match_selector.assert_called_once_with(ns_selector,
                                                 ns['metadata']['labels'])

        self.assertEqual(matched, False)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pods')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_ip')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.match_selector')
    def test__parse_rules_all_selectors(self, m_match_selector, m_get_pod_ip,
                                        m_get_pods):
        crd = get_crd_obj_with_all_selectors()
        policy = crd['spec']['networkpolicy_spec']
        i_rule = policy.get('ingress')[0]
        ns_selector = i_rule['from'][0].get('namespaceSelector')
        pod_selector = i_rule['from'][0].get('podSelector')
        ns = get_match_crd_namespace_obj()
        pod = get_match_crd_pod_obj()

        m_match_selector.return_value = True
        m_get_pod_ip.return_value = pod['status']['podIP']
        m_get_pods.return_value = {"items": [pod]}

        matched = network_policy_security_groups._parse_rules(
            'ingress', crd, policy, namespace=ns)

        m_match_selector.assert_called_once_with(ns_selector,
                                                 ns['metadata']['labels'])
        m_get_pods.assert_called_once_with(pod_selector,
                                           ns['metadata']['name'])
        m_get_pod_ip.assert_called_once_with(pod)

        self.assertEqual(matched, True)

    @mock.patch('kuryr_kubernetes.controller.drivers.'
                'network_policy_security_groups._parse_selectors_on_pod')
    def test__parse_rules_multiple_selectors(self, m_parse_selectors_on_pod):
        no_selector = None
        matched_selector = True
        pod = mock.sentinel.pod
        m_parse_selectors_on_pod.side_effect = [matched_selector]*2

        direction = "ingress"
        pod_selector = mock.sentinel.pod_selector
        namespace_selector = mock.sentinel.namespace_selector
        rule_block = {'from': [{'podSelector': pod_selector},
                      {'namespaceSelector': namespace_selector}]}
        policy = {
            "ingress": [rule_block],
            "policyTypes": ["Ingress"]
        }
        crd = {"spec": {"ingressSgRules": []}}

        matched = network_policy_security_groups._parse_rules(
            direction, crd, policy, pod=pod)

        calls = [mock.call(crd, pod, pod_selector, no_selector, rule_block,
                           direction, not matched_selector),
                 mock.call(crd, pod, no_selector, namespace_selector,
                           rule_block, direction, matched_selector)]
        m_parse_selectors_on_pod.assert_has_calls(calls)

        self.assertEqual(matched, matched_selector)
