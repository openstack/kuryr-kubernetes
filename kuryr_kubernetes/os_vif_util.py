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

from os_vif.objects import network as osv_network
from os_vif.objects import route as osv_route
from os_vif.objects import subnet as osv_subnet


# REVISIT(ivc): consider making this module part of kuryr-lib


def neutron_to_osvif_network(neutron_network):
    obj = osv_network.Network(id=neutron_network['id'])

    if neutron_network.get('name') is not None:
        obj.label = neutron_network['name']

    if neutron_network.get('mtu') is not None:
        obj.mtu = neutron_network['mtu']

    return obj


def neutron_to_osvif_subnet(neutron_subnet):
    obj = osv_subnet.Subnet(
        cidr=neutron_subnet['cidr'],
        dns=neutron_subnet['dns_nameservers'],
        routes=_neutron_to_osvif_routes(neutron_subnet['host_routes']))

    if neutron_subnet.get('gateway_ip') is not None:
        obj.gateway = neutron_subnet['gateway_ip']

    return obj


def _neutron_to_osvif_routes(neutron_routes):
    obj_list = [osv_route.Route(cidr=route['destination'],
                                gateway=route['nexthop'])
                for route in neutron_routes]

    return osv_route.RouteList(objects=obj_list)
