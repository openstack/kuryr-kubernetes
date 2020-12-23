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

from unittest import mock

from kuryr.lib import exceptions as kl_exc
from oslo_config import cfg as oslo_cfg

from kuryr_kubernetes.controller.drivers import nested_vif
from kuryr_kubernetes.controller.drivers import node_subnets
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


class TestNestedPodVIFDriver(test_base.TestCase):

    def test_get_parent_port(self):
        cls = nested_vif.NestedPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        self.useFixture(k_fix.MockNetworkClient()).client

        node_fixed_ip = mock.sentinel.node_fixed_ip
        pod_status = mock.MagicMock()
        pod_status.__getitem__.return_value = node_fixed_ip

        pod = mock.MagicMock()
        pod.__getitem__.return_value = pod_status
        parent_port = mock.sentinel.parent_port

        m_driver._get_parent_port_by_host_ip.return_value = parent_port

        cls._get_parent_port(m_driver, pod)
        m_driver._get_parent_port_by_host_ip.assert_called_once()

    def test_get_parent_port_by_host_ip(self):
        cls = nested_vif.NestedPodVIFDriver
        m_driver = mock.Mock(
            spec=cls, nodes_subnets_driver=node_subnets.ConfigNodesSubnets())
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        node_subnet_id1 = 'node_subnet_id1'
        node_subnet_id2 = 'node_subnet_id2'
        oslo_cfg.CONF.set_override('worker_nodes_subnets',
                                   [node_subnet_id2],
                                   group='pod_vif_nested')

        node_fixed_ip = mock.sentinel.node_fixed_ip

        ports = [
            mock.Mock(fixed_ips=[{'subnet_id': node_subnet_id1}]),
            mock.Mock(fixed_ips=[{'subnet_id': node_subnet_id2}]),
        ]
        os_net.ports.return_value = iter(ports)

        self.assertEqual(ports[1], cls._get_parent_port_by_host_ip(
            m_driver, node_fixed_ip))
        fixed_ips = ['ip_address=%s' % str(node_fixed_ip)]
        os_net.ports.assert_called_once_with(fixed_ips=fixed_ips)

    def test_get_parent_port_by_host_ip_multiple(self):
        cls = nested_vif.NestedPodVIFDriver
        m_driver = mock.Mock(
            spec=cls, nodes_subnets_driver=node_subnets.ConfigNodesSubnets())
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        node_subnet_id1 = 'node_subnet_id1'
        node_subnet_id2 = 'node_subnet_id2'
        node_subnet_id3 = 'node_subnet_id3'
        oslo_cfg.CONF.set_override('worker_nodes_subnets',
                                   [node_subnet_id3, node_subnet_id2],
                                   group='pod_vif_nested')

        node_fixed_ip = mock.sentinel.node_fixed_ip

        ports = [
            mock.Mock(fixed_ips=[{'subnet_id': node_subnet_id1}]),
            mock.Mock(fixed_ips=[{'subnet_id': node_subnet_id2}]),
        ]
        os_net.ports.return_value = (p for p in ports)

        self.assertEqual(ports[1], cls._get_parent_port_by_host_ip(
            m_driver, node_fixed_ip))
        fixed_ips = ['ip_address=%s' % str(node_fixed_ip)]
        os_net.ports.assert_called_with(fixed_ips=fixed_ips)

    def test_get_parent_port_by_host_ip_subnet_id_not_configured(self):
        cls = nested_vif.NestedPodVIFDriver
        m_driver = mock.Mock(
            spec=cls, nodes_subnets_driver=node_subnets.ConfigNodesSubnets())
        self.useFixture(k_fix.MockNetworkClient()).client
        oslo_cfg.CONF.set_override('worker_nodes_subnets',
                                   '',
                                   group='pod_vif_nested')
        node_fixed_ip = mock.sentinel.node_fixed_ip
        self.assertRaises(oslo_cfg.RequiredOptError,
                          cls._get_parent_port_by_host_ip,
                          m_driver, node_fixed_ip)

    def test_get_parent_port_by_host_ip_trunk_not_found(self):
        cls = nested_vif.NestedPodVIFDriver
        m_driver = mock.Mock(
            spec=cls, nodes_subnets_driver=node_subnets.ConfigNodesSubnets())
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        node_subnet_id = 'node_subnet_id'

        oslo_cfg.CONF.set_override('worker_nodes_subnets',
                                   [node_subnet_id],
                                   group='pod_vif_nested')

        node_fixed_ip = mock.sentinel.node_fixed_ip

        ports = (p for p in [])
        os_net.ports.return_value = ports

        self.assertRaises(kl_exc.NoResourceException,
                          cls._get_parent_port_by_host_ip, m_driver,
                          node_fixed_ip)
        fixed_ips = ['ip_address=%s' % str(node_fixed_ip)]
        os_net.ports.assert_called_once_with(fixed_ips=fixed_ips)
