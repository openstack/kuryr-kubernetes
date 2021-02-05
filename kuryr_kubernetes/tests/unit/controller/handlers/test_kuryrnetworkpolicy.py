# Copyright 2020 Red Hat, Inc.
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
from kuryr_kubernetes.controller.handlers import kuryrnetworkpolicy
from kuryr_kubernetes.tests import base as test_base


class TestPolicyHandler(test_base.TestCase):

    @mock.patch.object(drivers.LBaaSDriver, 'get_instance')
    @mock.patch.object(drivers.NetworkPolicyDriver, 'get_instance')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    @mock.patch('kuryr_kubernetes.clients.get_loadbalancer_client')
    def setUp(self, m_get_os_lb, m_get_os_net, m_get_k8s, m_get_np,
              m_get_lbaas):
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

        self.os_net = mock.Mock()
        m_get_os_net.return_value = self.os_net
        self.m_get_os_net = m_get_os_net

        self.np_driver = mock.Mock()
        m_get_np.return_value = self.np_driver
        self.m_get_np = m_get_np

        self.lbaas_driver = mock.Mock()
        m_get_lbaas.return_value = self.lbaas_driver
        self.m_get_lbaas = m_get_lbaas

        self.k8s.get.return_value = {}
        self.handler = kuryrnetworkpolicy.KuryrNetworkPolicyHandler()

    def _get_knp_obj(self):
        knp_obj = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrNetworkPolicy',
            'metadata': {
                'name': 'np-test-network-policy',
                'namespace': 'test-1',
            },
            'spec': {
                'securityGroupId': 'c1ac16f5-e198-4628-9d84-253c6001be8e',
                'securityGroupName': 'sg-test-network-policy'
            }}
        return knp_obj

    def test_init(self):
        self.m_get_k8s.assert_called_once()
        self.m_get_np.assert_called_once()

        self.assertEqual(self.np_driver, self.handler._drv_policy)
        self.assertEqual(self.k8s, self.handler.k8s)
        self.assertEqual(self.os_net, self.handler.os_net)
        self.assertEqual(self.lbaas_driver, self.handler._drv_lbaas)
