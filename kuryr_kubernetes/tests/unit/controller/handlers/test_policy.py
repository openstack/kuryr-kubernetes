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

from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.handlers import policy
from kuryr_kubernetes.tests import base as test_base


class TestPolicyHandler(test_base.TestCase):

    @mock.patch.object(drivers.NetworkPolicyDriver, 'get_instance')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def setUp(self, m_get_k8s, m_get_np):
        super(TestPolicyHandler, self).setUp()

        self._project_id = mock.sentinel.project_id
        self._policy_name = 'np-test'
        self._policy_uid = mock.sentinel.policy_uid
        self._policy_link = mock.sentinel.policy_link

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
                'egress': [{'ports': [{'port': 5978, 'protocol': 'TCP'}]}],
                'ingress': [{'ports': [{'port': 6379, 'protocol': 'TCP'}]}],
                'policyTypes': ['Ingress', 'Egress']
            }
        }

        self.k8s = mock.Mock()
        m_get_k8s.return_value = self.k8s
        self.m_get_k8s = m_get_k8s

        self.np_driver = mock.Mock()
        m_get_np.return_value = self.np_driver
        self._m_get_np = m_get_np

        self.handler = policy.NetworkPolicyHandler()

    def test_init(self):
        self.m_get_k8s.assert_called_once()
        self._m_get_np.assert_called_once()

        self.assertEqual(self.np_driver, self.handler._drv_policy)
        self.assertEqual(self.k8s, self.handler.k8s)

    def test_on_finalize(self):
        self.handler.on_finalize(self._policy)
        self.np_driver.release_network_policy.assert_called_once_with(
            self._policy)

    def test_on_present(self):
        self.handler.on_present(self._policy)
        self.k8s.add_finalizer.assert_called_once_with(
            self._policy, 'kuryr.openstack.org/networkpolicy-finalizer')
        self.np_driver.ensure_network_policy.assert_called_once_with(
            self._policy)
