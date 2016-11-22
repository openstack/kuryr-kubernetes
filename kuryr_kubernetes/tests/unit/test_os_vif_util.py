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

from os_vif.objects import route as osv_route
from oslo_utils import uuidutils

from kuryr_kubernetes import os_vif_util as ovu
from kuryr_kubernetes.tests import base as test_base


# REVISIT(ivc): move to kuryr-lib along with 'os_vif_util'


class TestOSVIFUtils(test_base.TestCase):
    def test_neutron_to_osvif_network(self):
        network_id = uuidutils.generate_uuid()
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
        network_id = uuidutils.generate_uuid()
        network_mtu = 1500
        neutron_network = {
            'id': network_id,
            'mtu': network_mtu,
        }

        network = ovu.neutron_to_osvif_network(neutron_network)

        self.assertFalse(network.obj_attr_is_set('label'))

    def test_neutron_to_osvif_network_no_mtu(self):
        network_id = uuidutils.generate_uuid()
        network_name = 'test-net'
        neutron_network = {
            'id': network_id,
            'name': network_name,
        }

        network = ovu.neutron_to_osvif_network(neutron_network)

        self.assertEqual(None, network.mtu)

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
