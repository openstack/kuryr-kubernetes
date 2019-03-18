# Copyright (c) 2016 Mirantis, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock

from kuryr_kubernetes import clients
from kuryr_kubernetes.tests import base as test_base


class TestK8sClient(test_base.TestCase):

    @mock.patch('openstack.connection.Connection')
    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch('kuryr_kubernetes.k8s_client.K8sClient')
    @mock.patch('kuryr.lib.utils.get_neutron_client')
    def test_setup_clients(self, m_neutron, m_k8s, m_cfg, m_openstack):
        k8s_api_root = 'http://127.0.0.1:1234'

        neutron_mock = mock.Mock()
        openstacksdk_mock = mock.Mock()
        openstacksdk_mock.load_balancer = mock.Mock()
        k8s_dummy = object()

        m_cfg.kubernetes.api_root = k8s_api_root
        m_neutron.return_value = neutron_mock
        m_k8s.return_value = k8s_dummy
        m_openstack.return_value = openstacksdk_mock

        clients.setup_clients()

        m_k8s.assert_called_with(k8s_api_root)
        self.assertIs(k8s_dummy, clients.get_kubernetes_client())
        self.assertIs(neutron_mock, clients.get_neutron_client())
        self.assertIs(openstacksdk_mock, clients.get_openstacksdk())
        self.assertIs(openstacksdk_mock.load_balancer,
                      clients.get_loadbalancer_client())
