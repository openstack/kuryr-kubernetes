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

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.handlers import machine
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base as test_base


class TestKuryrMachineHandler(test_base.TestCase):
    @mock.patch(
        'kuryr_kubernetes.controller.drivers.base.NodesSubnetsDriver.'
        'get_instance')
    def setUp(self, m_get_instance):
        super(TestKuryrMachineHandler, self).setUp()
        self.driver = mock.Mock()
        m_get_instance.return_value = self.driver
        self.handler = machine.MachineHandler()

    def test_on_present(self):
        self.handler._bump_nps = mock.Mock()
        self.driver.add_node.return_value = False
        self.handler.on_present(mock.sentinel.machine)
        self.driver.add_node.assert_called_once_with(mock.sentinel.machine)
        self.handler._bump_nps.assert_not_called()

    def test_on_present_new(self):
        self.handler._bump_nps = mock.Mock()
        self.driver.add_node.return_value = True
        self.handler.on_present(mock.sentinel.machine)
        self.driver.add_node.assert_called_once_with(mock.sentinel.machine)
        self.handler._bump_nps.assert_called_once()

    def test_on_deleted(self):
        self.handler._bump_nps = mock.Mock()
        self.driver.delete_node.return_value = False
        self.handler.on_deleted(mock.sentinel.machine)
        self.driver.delete_node.assert_called_once_with(mock.sentinel.machine)
        self.handler._bump_nps.assert_not_called()

    def test_on_deleted_gone(self):
        self.handler._bump_nps = mock.Mock()
        self.driver.delete_node.return_value = True
        self.handler.on_deleted(mock.sentinel.machine)
        self.driver.delete_node.assert_called_once_with(mock.sentinel.machine)
        self.handler._bump_nps.assert_called_once()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_bump_nps(self, get_client):
        m_k8s = mock.Mock()
        get_client.return_value = m_k8s
        m_k8s.get.return_value = {
            'items': [
                {'metadata': {'annotations': {
                    'networkPolicyLink': mock.sentinel.link1}}},
                {'metadata': {'annotations': {
                    'networkPolicyLink': mock.sentinel.link2}}},
                {'metadata': {'annotations': {
                    'networkPolicyLink': mock.sentinel.link3}}},
            ]
        }
        m_k8s.annotate.side_effect = (
            None, exceptions.K8sResourceNotFound('NP'), None)
        self.handler._bump_nps()
        m_k8s.get.assert_called_once_with(
            constants.K8S_API_CRD_KURYRNETWORKPOLICIES)
        m_k8s.annotate.assert_has_calls([
            mock.call(mock.sentinel.link1, mock.ANY),
            mock.call(mock.sentinel.link2, mock.ANY),
            mock.call(mock.sentinel.link3, mock.ANY),
        ])
