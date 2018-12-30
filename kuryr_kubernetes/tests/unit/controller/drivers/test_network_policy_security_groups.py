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

from kuryr_kubernetes.controller.drivers import network_policy_security_groups
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix

from oslo_config import cfg


class TestNetworkPolicySecurityGroupsDriver(test_base.TestCase):

    def setUp(self):
        super(TestNetworkPolicySecurityGroupsDriver, self).setUp()
        self._project_id = mock.sentinel.project_id
        self._sg_id = mock.sentinel.sg_id
        self._sg_id2 = mock.sentinel._sg_id2
        self._namespace = 'default'
        self._crd = {
            'metadata': {'name': mock.sentinel.name,
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
                'podSelector': {
                    'matchExpressions': [
                        {
                            'key': 'environment',
                            'operator': 'In',
                            'values': [
                                'production']}],
                    'matchLabels': {
                        'run': 'demo'
                    }},
                'securityGroupId': self._sg_id,
                'securityGroupName': mock.sentinel.sg_name}}

        self._crd2 = {
            'metadata': {'name': mock.sentinel.name3,
                         'selfLink': mock.sentinel.selfLink},
            'spec': {
                'ingressSgRules': [
                    {'security_group_rule':
                     {'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                      'direction': 'ingress',
                      'ethertype': 'IPv4',
                      'port_range_max': 8080,
                      'port_range_min': 8080,
                      'protocol': 'tcp',
                      'security_group_id': self._sg_id2,
                      'id': mock.sentinel.id
                      }}],
                'podSelector': {},
                'securityGroupId': self._sg_id2,
                'securityGroupName': mock.sentinel.sg_name}}

        self._crds = {
            "apiVersion": "v1",
            "items": [self._crd],
            "kind": "List",
            "metadata": {
                "resourceVersion": "",
                "selfLink": mock.sentinel.selfLink}}

        self._multiple_crds = {
            "apiVersion": "v1",
            "items": [self._crd, self._crd2],
            "kind": "List",
            "metadata": {
                "resourceVersion": "",
                "selfLink": mock.sentinel.selfLink}}

        self._empty_crds = {
            "apiVersion": "v1",
            "items": [],
            "kind": "List",
            "metadata": {
                "resourceVersion": "",
                "selfLink": mock.sentinel.selfLink}}

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
                    'image': 'kuryr/demo',
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
                    'image': 'kuryr/demo',
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
                    'image': 'kuryr/demo',
                    'imagePullPolicy': 'Always',
                    'name': mock.sentinel.pod_name
                    }]
                }}

        self.kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        self._driver = (
            network_policy_security_groups.NetworkPolicySecurityGroupsDriver())

        self._crd_sg_id = mock.sentinel.crd_sg_id
        self._crd_without_rules = {
            "apiVersion": "openstack.org/v1",
            "kind": "KuryrNetPolicy",
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
                "securityGroupId": self._crd_sg_id}}

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
                    'image': 'kuryr/demo',
                    'imagePullPolicy': 'Always',
                    'name': mock.sentinel.pod_name
                    }]},
            'status': {'podIP': self._pod_ip}}

        self._sg_rule_body = {
            u'security_group_rule': {
                u'direction': 'ingress',
                u'protocol': u'tcp',
                u'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                u'ethertype': 'IPv4',
                u'port_range_max': 6379,
                u'security_group_id': self._crd_sg_id,
                u'port_range_min': 6379,
                u'remote_ip_prefix': self._pod_ip}}

        self._new_rule_id = mock.sentinel.id
        self._crd_with_rule = {
            "apiVersion": "openstack.org/v1",
            "kind": "KuryrNetPolicy",
            "metadata": {"name": "np-test-network-policy",
                          "namespace": "default"},
            "spec": {
                "egressSgRules": [],
                "ingressSgRules": [{
                    "security_group_rule": {
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
                'create_security_group_rule')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'create_security_group_rule_body')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_selector', return_value=True)
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_ip')
    def test__create_sg_rules(self, m_get_pod_ip,
                              m_match_selector,
                              m_create_sg_rule_body,
                              m_create_sg_rule):
        m_get_pod_ip.return_value = self._pod_ip
        m_create_sg_rule_body.return_value = self._sg_rule_body
        sgr_id = mock.sentinel.sgr_id
        m_create_sg_rule.return_value = sgr_id
        crd = self._crd_without_rules
        pod = self._pod_dev_namespace
        matched = False
        new_sg_rule = self._sg_rule_body

        policy = crd['spec']['networkpolicy_spec']
        rule_list = policy.get('ingress', None)
        crd_rules = crd['spec'].get('ingressSgRules')
        pod_ns = pod['metadata']['namespace']

        for rule_block in rule_list:
            for rule in rule_block.get('from', []):
                pod_selector = rule.get('podSelector')
                matched = network_policy_security_groups._create_sg_rules(
                    crd, pod, pod_selector, rule_block,
                    crd_rules, 'ingress', matched, pod_ns)
                new_sg_rule['namespace'] = pod_ns
                new_sg_rule['security_group_rule']['id'] = sgr_id
                m_match_selector.assert_called_once_with(
                    pod_selector, pod['metadata']['labels'])
                m_get_pod_ip.assert_called_once_with(pod)
                m_create_sg_rule_body.assert_called_once()
                m_create_sg_rule.assert_called_once()
                self.assertEqual([new_sg_rule], crd_rules)
                self.assertEqual(matched, True)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_selector', return_value=False)
    def test__create_sg_rules_no_match(self, m_match_selector):
        crd = self._crd_without_rules
        pod = self._pod2

        policy = crd['spec']['networkpolicy_spec']
        rule_list = policy.get('ingress', None)
        crd_rules = crd['spec'].get('ingressSgRules')

        for rule_block in rule_list:
            for rule in rule_block.get('from', []):
                pod_selector = rule.get('podSelector')
                matched = network_policy_security_groups._create_sg_rules(
                    crd, pod, pod_selector, rule_block,
                    crd_rules, 'ingress', False, self._namespace)
                self.assertEqual(matched, False)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'patch_kuryr_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetpolicy_crds')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'delete_security_group_rule')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_ip')
    def test_delete_sg_rules(self, m_get_pod_ip, m_delete_sg_rule,
                             m_get_knp_crds, m_patch_kuryr_crd):
        crd = self._crd_with_rule
        i_rule = crd['spec'].get('ingressSgRules')[0]
        sgr_id = i_rule['security_group_rule'].get('id')
        m_get_pod_ip.return_value = self._pod_ip
        m_get_knp_crds.return_value = {
            "apiVersion": "v1",
            "items": [crd],
            "kind": "List",
            "metadata": {
                "resourceVersion": "",
                "selfLink": mock.sentinel.selfLink}}
        i_rules = e_rules = []
        pod = self._pod_dev_namespace

        self._driver.delete_sg_rules(pod)

        m_get_knp_crds.assert_called_once()
        m_get_pod_ip.assert_called_once_with(pod)
        m_delete_sg_rule.assert_called_once_with(sgr_id)
        m_patch_kuryr_crd.assert_called_with(
            crd, i_rules, e_rules, crd['spec'].get('podSelector'))

    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetpolicy_crds')
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
                'get_kuryrnetpolicy_crds')
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
        self.assertEqual(resp, [str(self._sg_id)])

    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_expressions')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_labels')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetpolicy_crds')
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
                'get_kuryrnetpolicy_crds')
    def test_get_sgs_no_crds(self, m_get_crds):
        m_get_crds.return_value = self._empty_crds
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
                'get_kuryrnetpolicy_crds')
    def test_get_sgs_multiple_crds(self, m_get_crds, m_match_labels,
                                   m_match_expressions):
        m_match_expressions.return_value = True
        m_match_labels.return_value = True
        m_get_crds.return_value = self._multiple_crds

        resp = self._driver.get_security_groups(self._pod, self._project_id)

        m_get_crds.assert_called_once_with(namespace=self._namespace)
        self.assertEqual([str(self._sg_id), str(self._sg_id2)], resp)
