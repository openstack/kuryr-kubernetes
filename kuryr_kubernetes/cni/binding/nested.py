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
import os

from oslo_log import log as logging
import psutil
import pyroute2
from pyroute2 import netlink as pyroute_netlink

from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes import config
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import health
from kuryr_kubernetes import utils

VLAN_KIND = 'vlan'
MACVLAN_KIND = 'macvlan'
MACVLAN_MODE_BRIDGE = 'bridge'
KUBELET_PORT = 10250

LOG = logging.getLogger(__name__)


class NestedDriver(health.HealthHandler, b_base.BaseBindingDriver,
                   metaclass=abc.ABCMeta):

    def __init__(self):
        super(NestedDriver, self).__init__()

    @abc.abstractmethod
    def _get_iface_create_args(self, vif):
        raise NotImplementedError()

    def _detect_iface_name(self, h_ipdb):
        # Let's try config first
        if config.CONF.binding.link_iface in h_ipdb.interfaces:
            LOG.debug(f'Using configured interface '
                      f'{config.CONF.binding.link_iface} as bridge interface.')
            return config.CONF.binding.link_iface

        # Then let's try choosing the one where kubelet listens to
        conns = [x for x in psutil.net_connections()
                 if x.status == psutil.CONN_LISTEN
                 and x.laddr.port == KUBELET_PORT]
        if len(conns) == 1:
            lookup_addr = conns[0].laddr.ip
            for name, iface in h_ipdb.interfaces.items():
                if type(name) is int:  # Skip ones duplicated by id
                    continue

                for addr in iface['ipaddr']:
                    if addr[0] == lookup_addr:
                        LOG.debug(f'Using kubelet bind interface {name} as '
                                  f'bridge interface.')
                        return name

        # Alright, just try the first non-loopback interface
        for name, iface in h_ipdb.interfaces.items():
            if type(name) is int:  # Skip ones duplicated by id
                continue

            if iface['flags'] & pyroute_netlink.rtnl.ifinfmsg.IFF_LOOPBACK:
                continue  # Skip loopback

            LOG.debug(f'Using interface {name} as bridge interface.')
            return name

        raise exceptions.CNIBindingFailure('Cannot find bridge interface for '
                                           'nested driver to use. Please set '
                                           '[binding]link_iface option.')

    def connect(self, vif, ifname, netns, container_id):
        # NOTE(vikasc): Ideally 'ifname' should be used here but instead a
        # temporary name is being used while creating the device for
        # container in host network namespace. This is because cni expects
        # only 'eth0' as interface name and if host already has an
        # interface named 'eth0', device creation will fail with 'already
        # exists' error.
        temp_name = vif.vif_name

        # First let's take a peek into the pod namespace and try to remove any
        # leftover interface in case we got restarted before CNI returned to
        # kubelet.
        with b_base.get_ipdb(netns) as c_ipdb:
            self._remove_ifaces(c_ipdb, (temp_name, ifname), netns)

        # We might also have leftover interface in the host netns, let's try to
        # remove it too. This is outside of the main host's IPDB context
        # manager to make sure removal is commited before starting next
        # transaction.
        with b_base.get_ipdb() as h_ipdb:
            self._remove_ifaces(h_ipdb, (temp_name,))

        with b_base.get_ipdb() as h_ipdb:
            # TODO(vikasc): evaluate whether we should have stevedore
            #               driver for getting the link device.
            vm_iface_name = self._detect_iface_name(h_ipdb)
            mtu = h_ipdb.interfaces[vm_iface_name].mtu
            if mtu < vif.network.mtu:
                # NOTE(dulek): This might happen if Neutron and DHCP agent
                # have different MTU settings. See
                # https://bugs.launchpad.net/kuryr-kubernetes/+bug/1863212
                raise exceptions.CNIBindingFailure(
                    f'MTU of interface {vm_iface_name} ({mtu}) is smaller '
                    f'than MTU of pod network {vif.network.id} '
                    f'({vif.network.mtu}). Please make sure pod network '
                    f'has the same or smaller MTU as node (VM) network.')

            args = self._get_iface_create_args(vif)
            with h_ipdb.create(ifname=temp_name,
                               link=h_ipdb.interfaces[vm_iface_name],
                               **args) as iface:
                iface.net_ns_fd = utils.convert_netns(netns)

        with b_base.get_ipdb(netns) as c_ipdb:
            with c_ipdb.interfaces[temp_name] as iface:
                iface.ifname = ifname
                iface.mtu = vif.network.mtu
                iface.address = str(vif.address)
                iface.up()

    def disconnect(self, vif, ifname, netns, container_id):
        # NOTE(dulek): Interfaces should get deleted with the netns, but it may
        #              happen that kubelet or crio will call new CNI ADD before
        #              the old netns is deleted. This might result in VLAN ID
        #              conflict. In oder to protect from that let's remove the
        #              netns ifaces here anyway.
        with b_base.get_ipdb(netns) as c_ipdb:
            self._remove_ifaces(c_ipdb, (vif.vif_name, ifname), netns)


class VlanDriver(NestedDriver):

    def __init__(self):
        super(VlanDriver, self).__init__()

    def connect(self, vif, ifname, netns, container_id):
        try:
            super().connect(vif, ifname, netns, container_id)
        except pyroute2.NetlinkError as e:
            if e.code == errno.EEXIST:
                args = self._get_iface_create_args(vif)
                LOG.warning(
                    f'Creation of pod interface failed due to VLAN ID '
                    f'(vlan_info={args}) conflict. Probably the CRI had not '
                    f'cleaned up the network namespace of deleted pods. '
                    f'Attempting to find and delete offending interface and '
                    f'retry.')
                self._cleanup_conflicting_vlan(netns, args['vlan_id'])
                super().connect(vif, ifname, netns, container_id)
                return
            raise

    def _get_iface_create_args(self, vif):
        return {'kind': VLAN_KIND, 'vlan_id': vif.vlan_id}

    def _cleanup_conflicting_vlan(self, netns, vlan_id):
        if vlan_id is None:
            # Better to not attempt that, might remove way to much.
            return

        netns_paths = []
        handled_netns = set()
        with b_base.get_ipdb() as h_ipdb:
            vm_iface_name = self._detect_iface_name(h_ipdb)
            vm_iface_index = h_ipdb.interfaces[vm_iface_name].index

        if netns.startswith('/proc'):
            # Paths have /proc/<pid>/ns/net pattern, we need to iterate
            # over /proc.
            netns_dir = utils.convert_netns('/proc')
            for pid in os.listdir(netns_dir):
                if not pid.isdigit():
                    # Ignore all the non-pid stuff in /proc
                    continue
                netns_paths.append(os.path.join(netns_dir, pid, 'ns/net'))
        else:
            # cri-o manages netns, they're in /var/run/netns/* or similar.
            netns_dir = os.path.dirname(netns)
            netns_paths = os.listdir(netns_dir)
            netns_paths = [os.path.join(netns_dir, netns_path)
                           for netns_path in netns_paths]

        for netns_path in netns_paths:
            netns_path = os.fsdecode(netns_path)
            try:
                # NOTE(dulek): inode can be used to clearly distinguish the
                #              netns' as `man namespaces` says:
                #
                # Since Linux 3.8, they appear as symbolic links.  If two
                # processes are in the same namespace, then the device IDs and
                # inode numbers of their /proc/[pid]/ns/xxx symbolic links will
                # be the same; an application can check this using the
                # stat.st_dev and stat.st_ino fields returned by stat(2).
                netns_stat = os.stat(netns_path)
                netns_id = netns_stat.st_dev, netns_stat.st_ino
            except OSError:
                continue
            if netns_id in handled_netns:
                continue
            handled_netns.add(netns_id)

            try:
                with b_base.get_ipdb(netns_path) as c_ipdb:
                    for ifname, iface in c_ipdb.interfaces.items():
                        if (iface.vlan_id == vlan_id
                                and iface.link == vm_iface_index):
                            LOG.warning(
                                f'Found offending interface {ifname} with '
                                f'VLAN ID {vlan_id} in netns {netns_path}. '
                                f'Trying to remove it.')
                            with c_ipdb.interfaces[ifname] as found_iface:
                                found_iface.remove()
                            break
            except OSError:
                continue


class MacvlanDriver(NestedDriver):

    def __init__(self):
        super(MacvlanDriver, self).__init__()

    def _get_iface_create_args(self, vif):
        return {'kind': MACVLAN_KIND, 'macvlan_mode': MACVLAN_MODE_BRIDGE}
