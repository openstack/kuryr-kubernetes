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
        self._labels = mock.sentinel.labels
        self._project_id = mock.sentinel.project_id
        self._sg_id = mock.sentinel.sg_id
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
                'securityGroupId': self._sg_id,
                'securityGroupName': mock.sentinel.sg_name}}

        self._crds = {
            "apiVersion": "v1",
            "items": [self._crd],
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
                    'run': 'demo'}},
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

    @mock.patch.object(network_policy_security_groups,
                       '_get_kuryrnetpolicy_crds')
    def test_get_security_groups(self, m_get_crds):
        m_get_crds.return_value = self._crds
        self._driver.get_security_groups(self._pod, self._project_id)
        calls = [mock.call(self._pod['metadata']['labels'],
                           namespace=self._namespace),
                 mock.call(namespace=self._namespace)]
        m_get_crds.assert_has_calls(calls)

    @mock.patch.object(network_policy_security_groups,
                       '_get_kuryrnetpolicy_crds')
    def test_get_security_groups_without_label(self, m_get_crds):
        pod = self._pod.copy()
        del pod['metadata']['labels']
        labels = {'run': 'demo'}
        self._crds['items'][0]['metadata']['labels'] = labels
        m_get_crds.return_value = self._crds
        self._driver.get_security_groups(pod, self._project_id)
        m_get_crds.assert_called_once_with(namespace=self._namespace)

    @mock.patch.object(network_policy_security_groups,
                       '_get_kuryrnetpolicy_crds')
    def test_get_security_groups_no_crds(self, m_get_crds):
        m_get_crds.return_value = self._empty_crds
        self.assertRaises(cfg.RequiredOptError,
                          self._driver.get_security_groups, self._pod,
                          self._project_id)
        calls = [mock.call(self._pod['metadata']['labels'],
                           namespace=self._namespace),
                 mock.call(namespace=self._namespace)]
        m_get_crds.assert_has_calls(calls)
