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
import uuid

from os_vif.objects import fixed_ip as osv_fixed_ip
from os_vif.objects import network as osv_network
from os_vif.objects import route as osv_route
from os_vif.objects import subnet as osv_subnet
from oslo_config import cfg as o_cfg

from kuryr_kubernetes import constants as const
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import os_vif_util as ovu
from kuryr_kubernetes.tests import base as test_base


# REVISIT(ivc): move to kuryr-lib along with 'os_vif_util'


class TestOSVIFUtils(test_base.TestCase):
    def test_neutron_to_osvif_network(self):
        network_id = str(uuid.uuid4())
        network_name = 'test-net'
        network_mtu = 1500
        neutron_network = {
            'id': network_id,
            'name': network_name,
            'mtu': network_mtu,
        }

        network = ovu.neutron_to_osvif_network(neutron_network)

        self.assertEqual(network_id, network.id)
        self.assertEqual(network_name, network.label)
        self.assertEqual(network_mtu, network.mtu)

    def test_neutron_to_osvif_network_no_name(self):
        network_id = str(uuid.uuid4())
        network_mtu = 1500
        neutron_network = {
            'id': network_id,
            'mtu': network_mtu,
        }

        network = ovu.neutron_to_osvif_network(neutron_network)

        self.assertFalse(network.obj_attr_is_set('label'))

    def test_neutron_to_osvif_network_no_mtu(self):
        network_id = str(uuid.uuid4())
        network_name = 'test-net'
        neutron_network = {
            'id': network_id,
            'name': network_name,
        }

        network = ovu.neutron_to_osvif_network(neutron_network)

        self.assertIsNone(network.mtu)

    @mock.patch('kuryr_kubernetes.os_vif_util._neutron_to_osvif_routes')
    def test_neutron_to_osvif_subnet(self, m_conv_routes):
        gateway = '1.1.1.1'
        cidr = '1.1.1.1/8'
        dns = ['2.2.2.2', '3.3.3.3']
        host_routes = mock.sentinel.host_routes
        route_list = osv_route.RouteList(objects=[
            osv_route.Route(cidr='4.4.4.4/8', gateway='5.5.5.5')])
        m_conv_routes.return_value = route_list
        neutron_subnet = {
            'cidr': cidr,
            'dns_nameservers': dns,
            'host_routes': host_routes,
            'gateway_ip': gateway,
        }

        subnet = ovu.neutron_to_osvif_subnet(neutron_subnet)

        self.assertEqual(cidr, str(subnet.cidr))
        self.assertEqual(route_list, subnet.routes)
        self.assertEqual(set(dns), set([str(addr) for addr in subnet.dns]))
        self.assertEqual(gateway, str(subnet.gateway))
        m_conv_routes.assert_called_once_with(host_routes)

    @mock.patch('kuryr_kubernetes.os_vif_util._neutron_to_osvif_routes')
    def test_neutron_to_osvif_subnet_no_gateway(self, m_conv_routes):
        cidr = '1.1.1.1/8'
        route_list = osv_route.RouteList()
        m_conv_routes.return_value = route_list
        neutron_subnet = {
            'cidr': cidr,
            'dns_nameservers': [],
            'host_routes': [],
        }

        subnet = ovu.neutron_to_osvif_subnet(neutron_subnet)

        self.assertFalse(subnet.obj_attr_is_set('gateway'))

    def test_neutron_to_osvif_routes(self):
        routes_map = {'%s.0.0.0/8' % i: '10.0.0.%s' % i for i in range(3)}
        routes = [{'destination': k, 'nexthop': v}
                  for k, v in routes_map.items()]

        route_list = ovu._neutron_to_osvif_routes(routes)

        self.assertEqual(len(routes), len(route_list.objects))
        for route in route_list.objects:
            self.assertEqual(routes_map[str(route.cidr)], str(route.gateway))

    @mock.patch('kuryr_kubernetes.os_vif_util._VIF_MANAGERS')
    def test_neutron_to_osvif_vif(self, m_mgrs):
        vif_plugin = mock.sentinel.vif_plugin
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets
        m_mgr = mock.Mock()
        m_mgrs.__getitem__.return_value = m_mgr

        ovu.neutron_to_osvif_vif(vif_plugin, port, subnets)

        m_mgrs.__getitem__.assert_called_with(vif_plugin)
        m_mgr.driver.assert_called_with(vif_plugin, port, subnets)

    @mock.patch('stevedore.driver.DriverManager')
    @mock.patch('kuryr_kubernetes.os_vif_util._VIF_MANAGERS')
    def test_neutron_to_osvif_vif_load(self, m_mgrs, m_stv_drm):
        vif_plugin = mock.sentinel.vif_plugin
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets
        m_mgr = mock.Mock()
        m_mgrs.__getitem__.side_effect = KeyError
        m_stv_drm.return_value = m_mgr

        ovu.neutron_to_osvif_vif(vif_plugin, port, subnets)

        m_stv_drm.assert_called_once_with(
            namespace=ovu._VIF_TRANSLATOR_NAMESPACE,
            name=vif_plugin,
            invoke_on_load=False)
        m_mgrs.__setitem__.assert_called_once_with(vif_plugin, m_mgr)
        m_mgr.driver.assert_called_once_with(vif_plugin, port, subnets)

    @mock.patch('kuryr_kubernetes.os_vif_util._get_ovs_hybrid_bridge_name')
    @mock.patch('kuryr_kubernetes.os_vif_util._get_vif_name')
    @mock.patch('kuryr_kubernetes.os_vif_util._is_port_active')
    @mock.patch('kuryr_kubernetes.os_vif_util._make_vif_network')
    @mock.patch('os_vif.objects.vif.VIFBridge')
    @mock.patch('os_vif.objects.vif.VIFPortProfileOpenVSwitch')
    def test_neutron_to_osvif_vif_ovs_hybrid(self,
                                             m_mk_profile,
                                             m_mk_vif,
                                             m_make_vif_network,
                                             m_is_port_active,
                                             m_get_vif_name,
                                             m_get_ovs_hybrid_bridge_name):
        vif_plugin = 'ovs'
        port_id = mock.sentinel.port_id
        mac_address = mock.sentinel.mac_address
        ovs_bridge = mock.sentinel.ovs_bridge
        port_filter = mock.sentinel.port_filter
        subnets = mock.sentinel.subnets
        port_profile = mock.sentinel.port_profile
        network = mock.sentinel.network
        port_active = mock.sentinel.port_active
        vif_name = mock.sentinel.vif_name
        hybrid_bridge = mock.sentinel.hybrid_bridge
        vif = mock.sentinel.vif

        m_mk_profile.return_value = port_profile
        m_make_vif_network.return_value = network
        m_is_port_active.return_value = port_active
        m_get_vif_name.return_value = vif_name
        m_get_ovs_hybrid_bridge_name.return_value = hybrid_bridge
        m_mk_vif.return_value = vif

        port = {'id': port_id,
                'mac_address': mac_address,
                'binding:vif_details': {
                    'ovs_hybrid_plug': True,
                    'bridge_name': ovs_bridge,
                    'port_filter': port_filter},
                }

        self.assertEqual(vif, ovu.neutron_to_osvif_vif_ovs(vif_plugin, port,
                                                           subnets))

        m_mk_profile.assert_called_once_with(interface_id=port_id)
        m_make_vif_network.assert_called_once_with(port, subnets)
        m_is_port_active.assert_called_once_with(port)
        m_get_ovs_hybrid_bridge_name.assert_called_once_with(port)
        m_get_vif_name.assert_called_once_with(port)
        self.assertEqual(ovs_bridge, network.bridge)
        m_mk_vif.assert_called_once_with(
            id=port_id,
            address=mac_address,
            network=network,
            has_traffic_filtering=port_filter,
            preserve_on_delete=False,
            active=port_active,
            port_profile=port_profile,
            plugin=vif_plugin,
            vif_name=vif_name,
            bridge_name=hybrid_bridge)

    @mock.patch('kuryr_kubernetes.os_vif_util._get_vif_name')
    @mock.patch('kuryr_kubernetes.os_vif_util._is_port_active')
    @mock.patch('kuryr_kubernetes.os_vif_util._make_vif_network')
    @mock.patch('os_vif.objects.vif.VIFOpenVSwitch')
    @mock.patch('os_vif.objects.vif.VIFPortProfileOpenVSwitch')
    def test_neutron_to_osvif_vif_ovs_native(self,
                                             m_mk_profile,
                                             m_mk_vif,
                                             m_make_vif_network,
                                             m_is_port_active,
                                             m_get_vif_name):
        vif_plugin = 'ovs'
        port_id = mock.sentinel.port_id
        mac_address = mock.sentinel.mac_address
        ovs_bridge = mock.sentinel.ovs_bridge
        subnets = mock.sentinel.subnets
        port_profile = mock.sentinel.port_profile
        network = mock.sentinel.network
        port_active = mock.sentinel.port_active
        vif_name = mock.sentinel.vif_name
        vif = mock.sentinel.vif

        m_mk_profile.return_value = port_profile
        m_make_vif_network.return_value = network
        m_is_port_active.return_value = port_active
        m_get_vif_name.return_value = vif_name
        m_mk_vif.return_value = vif

        port = {'id': port_id,
                'mac_address': mac_address,
                'binding:vif_details': {
                    'ovs_hybrid_plug': False,
                    'bridge_name': ovs_bridge},
                }

        self.assertEqual(vif, ovu.neutron_to_osvif_vif_ovs(vif_plugin, port,
                                                           subnets))
        m_mk_profile.assert_called_once_with(interface_id=port_id)
        m_make_vif_network.assert_called_once_with(port, subnets)
        m_is_port_active.assert_called_once_with(port)
        m_get_vif_name.assert_called_once_with(port)
        self.assertEqual(ovs_bridge, network.bridge)

    @mock.patch('kuryr_kubernetes.os_vif_util._get_vif_name')
    @mock.patch('kuryr_kubernetes.os_vif_util._is_port_active')
    @mock.patch('kuryr_kubernetes.os_vif_util._make_vif_network')
    @mock.patch('kuryr_kubernetes.objects.vif.VIFVlanNested')
    def test_neutron_to_osvif_nested_vlan(self, m_mk_vif, m_make_vif_network,
                                          m_is_port_active, m_get_vif_name):
        vif_plugin = const.K8S_OS_VIF_NOOP_PLUGIN
        port_id = mock.sentinel.port_id
        mac_address = mock.sentinel.mac_address
        port_filter = mock.sentinel.port_filter
        subnets = mock.sentinel.subnets
        network = mock.sentinel.network
        port_active = mock.sentinel.port_active
        vif_name = mock.sentinel.vif_name
        vif = mock.sentinel.vif
        vlan_id = mock.sentinel.vlan_id

        m_make_vif_network.return_value = network
        m_is_port_active.return_value = port_active
        m_get_vif_name.return_value = vif_name
        m_mk_vif.return_value = vif

        port = {'id': port_id,
                'mac_address': mac_address,
                'binding:vif_details': {
                    'port_filter': port_filter},
                }

        self.assertEqual(vif, ovu.neutron_to_osvif_vif_nested_vlan(port,
                         subnets, vlan_id))

        m_make_vif_network.assert_called_once_with(port, subnets)
        m_is_port_active.assert_called_once_with(port)
        m_get_vif_name.assert_called_once_with(port)
        m_mk_vif.assert_called_once_with(
            id=port_id,
            address=mac_address,
            network=network,
            has_traffic_filtering=port_filter,
            preserve_on_delete=False,
            active=port_active,
            plugin=vif_plugin,
            vif_name=vif_name,
            vlan_id=vlan_id)

    @mock.patch('kuryr_kubernetes.os_vif_util._get_vif_name')
    @mock.patch('kuryr_kubernetes.os_vif_util._is_port_active')
    @mock.patch('kuryr_kubernetes.os_vif_util._make_vif_network')
    @mock.patch('kuryr_kubernetes.objects.vif.VIFMacvlanNested')
    def test_neutron_to_osvif_nested_macvlan(self, m_mk_vif,
                                             m_make_vif_network,
                                             m_is_port_active, m_get_vif_name):
        vif_plugin = const.K8S_OS_VIF_NOOP_PLUGIN
        port_id = mock.sentinel.port_id
        mac_address = mock.sentinel.mac_address
        port_filter = mock.sentinel.port_filter
        subnets = mock.sentinel.subnets
        network = mock.sentinel.network
        port_active = mock.sentinel.port_active
        vif_name = mock.sentinel.vif_name
        vif = mock.sentinel.vif

        m_make_vif_network.return_value = network
        m_is_port_active.return_value = port_active
        m_get_vif_name.return_value = vif_name
        m_mk_vif.return_value = vif

        port = {'id': port_id,
                'mac_address': mac_address,
                'binding:vif_details': {
                    'port_filter': port_filter},
                }

        self.assertEqual(vif, ovu.neutron_to_osvif_vif_nested_macvlan(port,
                                                                      subnets))

        m_make_vif_network.assert_called_once_with(port, subnets)
        m_is_port_active.assert_called_once_with(port)
        m_get_vif_name.assert_called_once_with(port)
        m_mk_vif.assert_called_once_with(
            id=port_id,
            address=mac_address,
            network=network,
            has_traffic_filtering=port_filter,
            preserve_on_delete=False,
            active=port_active,
            plugin=vif_plugin,
            vif_name=vif_name)

    def test_neutron_to_osvif_vif_ovs_no_bridge(self):
        vif_plugin = 'ovs'
        port = {'id': str(uuid.uuid4())}
        subnets = {}

        self.assertRaises(o_cfg.RequiredOptError,
                          ovu.neutron_to_osvif_vif_ovs,
                          vif_plugin, port, subnets)

    def test_get_ovs_hybrid_bridge_name(self):
        port_id = str(uuid.uuid4())
        port = {'id': port_id}

        self.assertEqual("qbr" + port_id[:11],
                         ovu._get_ovs_hybrid_bridge_name(port))

    def test_is_port_active(self):
        port = {'status': 'ACTIVE'}

        self.assertTrue(ovu._is_port_active(port))

    def test_is_port_inactive(self):
        port = {'status': 'DOWN'}

        self.assertFalse(ovu._is_port_active(port))

    @mock.patch('kuryr.lib.binding.drivers.utils.get_veth_pair_names')
    def test_get_vif_name(self, m_get_veth_pair_names):
        port_id = mock.sentinel.port_id
        vif_name = mock.sentinel.vif_name
        port = {'id': port_id}
        m_get_veth_pair_names.return_value = (vif_name, mock.sentinel.any)

        self.assertEqual(vif_name, ovu._get_vif_name(port))
        m_get_veth_pair_names.assert_called_once_with(port_id)

    @mock.patch('kuryr_kubernetes.os_vif_util._make_vif_subnets')
    @mock.patch('os_vif.objects.subnet.SubnetList')
    def test_make_vif_network(self, m_mk_subnet_list, m_make_vif_subnets):
        network_id = mock.sentinel.network_id
        network = mock.Mock()
        orig_network = mock.Mock()
        orig_network.id = network_id
        orig_network.obj_clone.return_value = network
        subnet_id = mock.sentinel.subnet_id
        subnets = {subnet_id: orig_network}
        vif_subnets = mock.sentinel.vif_subnets
        subnet_list = mock.sentinel.subnet_list
        m_make_vif_subnets.return_value = vif_subnets
        m_mk_subnet_list.return_value = subnet_list
        port = {'network_id': network_id}

        self.assertEqual(network, ovu._make_vif_network(port, subnets))
        self.assertEqual(subnet_list, network.subnets)
        m_make_vif_subnets.assert_called_once_with(port, subnets)
        m_mk_subnet_list.assert_called_once_with(objects=vif_subnets)

    def test_make_vif_network_not_found(self):
        network_id = mock.sentinel.network_id
        port = {'network_id': network_id}
        subnets = {}

        self.assertRaises(k_exc.IntegrityError, ovu._make_vif_network,
                          port, subnets)

    @mock.patch('kuryr_kubernetes.os_vif_util._make_vif_subnet')
    @mock.patch('os_vif.objects.fixed_ip.FixedIP')
    def test_make_vif_subnets(self, m_mk_fixed_ip, m_make_vif_subnet):
        subnet_id = mock.sentinel.subnet_id
        ip_address = mock.sentinel.ip_address
        fixed_ip = mock.sentinel.fixed_ip
        subnet = mock.Mock()
        subnets = mock.MagicMock()
        subnets.__contains__.return_value = True
        m_mk_fixed_ip.return_value = fixed_ip
        m_make_vif_subnet.return_value = subnet
        port = {'fixed_ips': [
            {'subnet_id': subnet_id, 'ip_address': ip_address}]}

        self.assertEqual([subnet], ovu._make_vif_subnets(port, subnets))
        m_make_vif_subnet.assert_called_once_with(subnets, subnet_id)
        m_mk_fixed_ip.assert_called_once_with(address=ip_address)
        subnet.ips.objects.append.assert_called_once_with(fixed_ip)

    def test_make_vif_subnets_not_found(self):
        subnet_id = mock.sentinel.subnet_id
        ip_address = mock.sentinel.ip_address
        subnets = mock.MagicMock()
        subnets.__contains__.return_value = False
        port = {'fixed_ips': [
            {'subnet_id': subnet_id, 'ip_address': ip_address}]}

        self.assertRaises(k_exc.IntegrityError, ovu._make_vif_subnets,
                          port, subnets)

    @mock.patch('os_vif.objects.fixed_ip.FixedIPList')
    def test_make_vif_subnet(self, m_mk_fixed_ip_list):
        subnet_id = mock.sentinel.subnet_id
        fixed_ip_list = mock.sentinel.fixed_ip_list
        subnet = mock.Mock()
        orig_subnet = mock.Mock()
        orig_subnet.obj_clone.return_value = subnet
        orig_network = mock.Mock()
        orig_network.subnets.objects = [orig_subnet]
        m_mk_fixed_ip_list.return_value = fixed_ip_list
        subnets = {subnet_id: orig_network}

        self.assertEqual(subnet, ovu._make_vif_subnet(subnets, subnet_id))
        self.assertEqual(fixed_ip_list, subnet.ips)
        m_mk_fixed_ip_list.assert_called_once_with(objects=[])

    def test_make_vif_subnet_invalid(self):
        subnet_id = mock.sentinel.subnet_id
        orig_network = mock.Mock()
        orig_network.subnets.objects = []
        subnets = {subnet_id: orig_network}

        self.assertRaises(k_exc.IntegrityError, ovu._make_vif_subnet,
                          subnets, subnet_id)

    def test_osvif_to_neutron_network_ids(self):
        id_a = mock.sentinel.id_a
        id_b = mock.sentinel.id_b
        net1 = mock.Mock()
        net1.id = id_a
        net2 = mock.Mock()
        net2.id = id_b
        net3 = mock.Mock()
        net3.id = id_a
        subnets = {1: net1, 2: net2, 3: net3}

        ret = ovu.osvif_to_neutron_network_ids(subnets)
        self.assertEqual(2, len(ret))
        self.assertIn(id_a, ret)
        self.assertIn(id_b, ret)

    def test_osvif_to_neutron_fixed_ips(self):
        ip11 = '1.1.1.1'
        ip12 = '2.2.2.2'
        ip3 = '3.3.3.3'
        subnet_id_1 = str(uuid.uuid4())
        subnet_id_2 = str(uuid.uuid4())
        subnet_id_3 = str(uuid.uuid4())

        subnet_1 = osv_subnet.Subnet(ips=osv_fixed_ip.FixedIPList(
            objects=[osv_fixed_ip.FixedIP(address=ip11),
                     osv_fixed_ip.FixedIP(address=ip12)]))
        subnet_2 = osv_subnet.Subnet()
        subnet_3 = osv_subnet.Subnet(ips=osv_fixed_ip.FixedIPList(
            objects=[osv_fixed_ip.FixedIP(address=ip3)]))

        net1 = osv_network.Network(subnets=osv_subnet.SubnetList(
            objects=[subnet_1]))
        net2 = osv_network.Network(subnets=osv_subnet.SubnetList(
            objects=[subnet_2]))
        net3 = osv_network.Network(subnets=osv_subnet.SubnetList(
            objects=[subnet_3]))

        subnets = {subnet_id_1: net1, subnet_id_2: net2, subnet_id_3: net3}

        expected = [{'subnet_id': subnet_id_1, 'ip_address': ip11},
                    {'subnet_id': subnet_id_1, 'ip_address': ip12},
                    {'subnet_id': subnet_id_2},
                    {'subnet_id': subnet_id_3, 'ip_address': ip3}]

        ret = ovu.osvif_to_neutron_fixed_ips(subnets)

        def _sort_key(e):
            return (e.get('subnet_id'), e.get('ip_address'))

        self.assertEqual(sorted(expected, key=_sort_key),
                         sorted(ret, key=_sort_key))

    def test_osvif_to_neutron_fixed_ips_invalid(self):
        subnet_id = str(uuid.uuid4())

        subnet_1 = osv_subnet.Subnet()
        subnet_2 = osv_subnet.Subnet()

        net = osv_network.Network(subnets=osv_subnet.SubnetList(
            objects=[subnet_1, subnet_2]))

        subnets = {subnet_id: net}

        self.assertRaises(k_exc.IntegrityError,
                          ovu.osvif_to_neutron_fixed_ips, subnets)
