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

import abc
import errno

import os_vif
from os_vif.objects import vif as osv_objects
from oslo_log import log as logging
import pyroute2
from pyroute2 import netns as pyroute_netns
from stevedore import driver as stv_driver

from kuryr_kubernetes.cni import utils as cni_utils
from kuryr_kubernetes import utils

_BINDING_NAMESPACE = 'kuryr_kubernetes.cni.binding'
LOG = logging.getLogger(__name__)


class BaseBindingDriver(object, metaclass=abc.ABCMeta):
    """Interface to attach ports to pods."""

    def _remove_ifaces(self, ipdb, ifnames, netns='host'):
        """Check if any of `ifnames` exists and remove it.

        :param ipdb: ipdb of the network namespace to check
        :param ifnames: iterable of interface names to remove
        :param netns: network namespace name (used for logging)
        """
        for ifname in ifnames:
            if ifname in ipdb.interfaces:
                LOG.warning('Found hanging interface %(ifname)s inside '
                            '%(netns)s netns. Most likely it is a leftover '
                            'from a kuryr-daemon restart. Trying to delete '
                            'it.', {'ifname': ifname, 'netns': netns})
                with ipdb.interfaces[ifname] as iface:
                    iface.remove()

    @abc.abstractmethod
    def connect(self, vif, ifname, netns, container_id):
        raise NotImplementedError()

    @abc.abstractmethod
    def disconnect(self, vif, ifname, netns, container_id):
        raise NotImplementedError()


def _get_binding_driver(vif):
    mgr = stv_driver.DriverManager(namespace=_BINDING_NAMESPACE,
                                   name=type(vif).__name__,
                                   invoke_on_load=True)
    return mgr.driver


def get_ipdb(netns=None):
    if netns:
        netns = utils.convert_netns(netns)
        ipdb = pyroute2.IPDB(nl=pyroute2.NetNS(netns))
    else:
        ipdb = pyroute2.IPDB()
    return ipdb


def _enable_ipv6(netns):
    # Docker disables IPv6 for --net=none containers
    # TODO(apuimedo) remove when it is no longer the case
    try:
        netns = utils.convert_netns(netns)
        path = utils.convert_netns('/proc/self/ns/net')
        self_ns_fd = open(path)
        pyroute_netns.setns(netns)
        path = utils.convert_netns('/proc/sys/net/ipv6/conf/all/disable_ipv6')
        with open(path, 'w') as disable_ipv6:
            disable_ipv6.write('0')
    except Exception:
        raise
    finally:
        pyroute_netns.setns(self_ns_fd)


def _configure_l3(vif, ifname, netns, is_default_gateway):
    with get_ipdb(netns) as ipdb:
        with ipdb.interfaces[ifname] as iface:
            for subnet in vif.network.subnets.objects:
                if subnet.cidr.version == 6:
                    _enable_ipv6(netns)
                for fip in subnet.ips.objects:
                    iface.add_ip('%s/%s' % (fip.address,
                                            subnet.cidr.prefixlen))

        routes = ipdb.routes
        for subnet in vif.network.subnets.objects:
            for route in subnet.routes.objects:
                routes.add(gateway=str(route.gateway),
                           dst=str(route.cidr)).commit()
            if is_default_gateway and hasattr(subnet, 'gateway'):
                try:
                    routes.add(gateway=str(subnet.gateway),
                               dst='default').commit()
                except pyroute2.NetlinkError as ex:
                    if ex.code != errno.EEXIST:
                        raise
                    LOG.debug("Default route already exists in pod for vif=%s."
                              " Did not overwrite with requested gateway=%s",
                              vif, subnet.gateway)


def _need_configure_l3(vif):
    if isinstance(vif, osv_objects.VIFVHostUser):
        return False
    if not hasattr(vif, 'physnet'):
        # NOTE(danil): non-sriov vif. Figure out if it is nested-dpdk
        if vif.obj_attr_is_set('port_profile') and hasattr(vif.port_profile,
                                                           'l3_setup'):
            return vif.port_profile.l3_setup
        # NOTE(danil): by default kuryr-kubernetes has to setup l3
        return True
    return True


@cni_utils.log_ipdb
def connect(vif, instance_info, ifname, netns=None, report_health=None,
            is_default_gateway=True, container_id=None):
    driver = _get_binding_driver(vif)
    if report_health:
        report_health(driver.is_alive())
    os_vif.plug(vif, instance_info)
    driver.connect(vif, ifname, netns, container_id)
    if _need_configure_l3(vif):
        _configure_l3(vif, ifname, netns, is_default_gateway)


@cni_utils.log_ipdb
def disconnect(vif, instance_info, ifname, netns=None, report_health=None,
               container_id=None, **kwargs):
    driver = _get_binding_driver(vif)
    if report_health:
        report_health(driver.is_alive())
    driver.disconnect(vif, ifname, netns, container_id)
    os_vif.unplug(vif, instance_info)


@cni_utils.log_ipdb
def cleanup(ifname, netns):
    try:
        with get_ipdb(netns) as c_ipdb:
            if ifname in c_ipdb.interfaces:
                with c_ipdb.interfaces[ifname] as iface:
                    iface.remove()
    except Exception:
        # Just ignore cleanup errors, there's not much we can do anyway.
        LOG.warning('Error occured when attempting to clean up netns %s. '
                    'Ignoring.', netns)
