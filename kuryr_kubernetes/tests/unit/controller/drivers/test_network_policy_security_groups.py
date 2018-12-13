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
                    'environment': 'development'}},
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

    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch.object(network_policy_security_groups,
                       '_get_kuryrnetpolicy_crds')
    def test_get_sgs_for_pod_without_label(self, m_get_crds, m_cfg):
        m_get_crds.return_value = self._crds
        sg_list = [str(mock.sentinel.sg_id)]
        m_cfg.neutron_defaults.pod_security_groups = sg_list

        sgs = self._driver.get_security_groups(self._pod_without_label,
                                               self._project_id)

        m_get_crds.assert_called_once_with(namespace=self._namespace)
        self.assertEqual(sg_list, sgs)

    @mock.patch.object(network_policy_security_groups,
                       '_match_expressions')
    @mock.patch.object(network_policy_security_groups,
                       '_match_labels')
    @mock.patch.object(network_policy_security_groups,
                       '_get_kuryrnetpolicy_crds')
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
    @mock.patch.object(network_policy_security_groups,
                       '_match_expressions')
    @mock.patch.object(network_policy_security_groups,
                       '_match_labels')
    @mock.patch.object(network_policy_security_groups,
                       '_get_kuryrnetpolicy_crds')
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

    @mock.patch.object(network_policy_security_groups,
                       '_get_kuryrnetpolicy_crds')
    def test_get_sgs_no_crds(self, m_get_crds):
        m_get_crds.return_value = self._empty_crds
        cfg.CONF.set_override('pod_security_groups', [],
                              group='neutron_defaults')

        self.assertRaises(cfg.RequiredOptError,
                          self._driver.get_security_groups, self._pod,
                          self._project_id)
        m_get_crds.assert_called_with(namespace=self._namespace)

    @mock.patch.object(network_policy_security_groups,
                       '_match_expressions')
    @mock.patch.object(network_policy_security_groups,
                       '_match_labels')
    @mock.patch.object(network_policy_security_groups,
                       '_get_kuryrnetpolicy_crds')
    def test_get_sgs_multiple_crds(self, m_get_crds, m_match_labels,
                                   m_match_expressions):
        m_match_expressions.return_value = True
        m_match_labels.return_value = True
        m_get_crds.return_value = self._multiple_crds

        resp = self._driver.get_security_groups(self._pod, self._project_id)

        m_get_crds.assert_called_once_with(namespace=self._namespace)
        self.assertEqual([str(self._sg_id), str(self._sg_id2)], resp)
