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

from kuryr.lib import exceptions as kl_exc
from oslo_config import cfg as oslo_cfg

from kuryr_kubernetes.controller.drivers import nested_vif
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


class TestNestedPodVIFDriver(test_base.TestCase):

    def test_get_parent_port(self):
        cls = nested_vif.NestedPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        node_fixed_ip = mock.sentinel.node_fixed_ip
        pod_status = mock.MagicMock()
        pod_status.__getitem__.return_value = node_fixed_ip

        pod = mock.MagicMock()
        pod.__getitem__.return_value = pod_status
        parent_port = mock.sentinel.parent_port

        m_driver._get_parent_port_by_host_ip.return_value = parent_port

        cls._get_parent_port(m_driver, neutron, pod)
        m_driver._get_parent_port_by_host_ip.assert_called_once()

    def test_get_parent_port_by_host_ip(self):
        cls = nested_vif.NestedPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        node_subnet_id = mock.sentinel.node_subnet_id
        oslo_cfg.CONF.set_override('worker_nodes_subnet',
                                   node_subnet_id,
                                   group='pod_vif_nested')

        node_fixed_ip = mock.sentinel.node_fixed_ip

        port = mock.sentinel.port
        ports = {'ports': [port]}
        neutron.list_ports.return_value = ports

        self.assertEqual(port, cls._get_parent_port_by_host_ip(
            m_driver, neutron, node_fixed_ip))
        fixed_ips = ['subnet_id=%s' % str(node_subnet_id),
                     'ip_address=%s' % str(node_fixed_ip)]
        neutron.list_ports.assert_called_once_with(fixed_ips=fixed_ips)

    def test_get_parent_port_by_host_ip_subnet_id_not_configured(self):
        cls = nested_vif.NestedPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        oslo_cfg.CONF.set_override('worker_nodes_subnet',
                                   '',
                                   group='pod_vif_nested')
        node_fixed_ip = mock.sentinel.node_fixed_ip
        self.assertRaises(oslo_cfg.RequiredOptError,
                          cls._get_parent_port_by_host_ip,
                          m_driver, neutron, node_fixed_ip)

    def test_get_parent_port_by_host_ip_trunk_not_found(self):
        cls = nested_vif.NestedPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        node_subnet_id = mock.sentinel.node_subnet_id

        oslo_cfg.CONF.set_override('worker_nodes_subnet',
                                   node_subnet_id,
                                   group='pod_vif_nested')

        node_fixed_ip = mock.sentinel.node_fixed_ip

        ports = {'ports': []}
        neutron.list_ports.return_value = ports

        self.assertRaises(kl_exc.NoResourceException,
                          cls._get_parent_port_by_host_ip, m_driver, neutron,
                          node_fixed_ip)
        fixed_ips = ['subnet_id=%s' % str(node_subnet_id),
                     'ip_address=%s' % str(node_fixed_ip)]
        neutron.list_ports.assert_called_once_with(fixed_ips=fixed_ips)
