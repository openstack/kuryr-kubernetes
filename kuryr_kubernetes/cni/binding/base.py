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

import os_vif
import pyroute2
from stevedore import driver as stv_driver

_BINDING_NAMESPACE = 'kuryr_kubernetes.cni.binding'
_IPDB = {}


def _get_binding_driver(vif):
    mgr = stv_driver.DriverManager(namespace=_BINDING_NAMESPACE,
                                   name=type(vif).__name__,
                                   invoke_on_load=True)
    return mgr.driver


def get_ipdb(netns=None):
    try:
        return _IPDB[netns]
    except KeyError:
        if netns:
            ipdb = pyroute2.IPDB(nl=pyroute2.NetNS(netns))
        else:
            ipdb = pyroute2.IPDB()
    _IPDB[netns] = ipdb
    return ipdb


def _enable_ipv6(netns):
    # Docker disables IPv6 for --net=none containers
    # TODO(apuimedo) remove when it is no longer the case
    try:
        self_ns_fd = open('/proc/self/ns/net')
        pyroute2.netns.setns(netns)
        with open('/proc/sys/net/ipv6/conf/all/disable_ipv6',
                  'w') as disable_ipv6:
            disable_ipv6.write('0')
    except Exception:
        raise
    finally:
        pyroute2.netns.setns(self_ns_fd)


def _configure_l3(vif, ifname, netns):
    with get_ipdb(netns).interfaces[ifname] as iface:
        for subnet in vif.network.subnets.objects:
            if subnet.cidr.version == 6:
                _enable_ipv6(netns)
            for fip in subnet.ips.objects:
                iface.add_ip('%s/%s' % (fip.address, subnet.cidr.prefixlen))

    routes = get_ipdb(netns).routes
    for subnet in vif.network.subnets.objects:
        for route in subnet.routes.objects:
            routes.add(gateway=str(route.gateway),
                       dst=str(route.cidr)).commit()
        if subnet.gateway:
            routes.add(gateway=str(subnet.gateway),
                       dst='default').commit()


def connect(vif, instance_info, ifname, netns=None):
    driver = _get_binding_driver(vif)
    os_vif.plug(vif, instance_info)
    driver.connect(vif, ifname, netns)
    _configure_l3(vif, ifname, netns)


def disconnect(vif, instance_info, ifname, netns=None):
    driver = _get_binding_driver(vif)
    driver.disconnect(vif, ifname, netns)
    os_vif.unplug(vif, instance_info)
