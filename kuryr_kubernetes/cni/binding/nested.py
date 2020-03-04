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

from oslo_log import log as logging
import pyroute2

from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes import config
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import health
from kuryr_kubernetes import utils

VLAN_KIND = 'vlan'
MACVLAN_KIND = 'macvlan'
MACVLAN_MODE_BRIDGE = 'bridge'

LOG = logging.getLogger(__name__)


class NestedDriver(health.HealthHandler, b_base.BaseBindingDriver,
                   metaclass=abc.ABCMeta):

    def __init__(self):
        super(NestedDriver, self).__init__()

    @abc.abstractmethod
    def _get_iface_create_args(self, vif):
        raise NotImplementedError()

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

        try:
            with b_base.get_ipdb() as h_ipdb:
                # TODO(vikasc): evaluate whether we should have stevedore
                #               driver for getting the link device.
                vm_iface_name = config.CONF.binding.link_iface
                mtu = h_ipdb.interfaces[vm_iface_name].mtu
                if mtu != vif.network.mtu:
                    # NOTE(dulek): This might happen if Neutron and DHCP agent
                    # have different MTU settings. See
                    # https://bugs.launchpad.net/kuryr-kubernetes/+bug/1863212
                    raise exceptions.CNIBindingFailure(
                        f'MTU of interface {vm_iface_name} ({mtu}) does not '
                        f'match MTU of pod network {vif.network.id} '
                        f'({vif.network.mtu}). Please make sure pod network '
                        f'has the same MTU as node (VM) network.')

                args = self._get_iface_create_args(vif)
                with h_ipdb.create(ifname=temp_name,
                                   link=h_ipdb.interfaces[vm_iface_name],
                                   **args) as iface:
                    iface.net_ns_fd = utils.convert_netns(netns)
        except pyroute2.NetlinkError as e:
            if e.code == errno.EEXIST:
                # NOTE(dulek): This is related to bug 1854928. It's super-rare,
                #              so aim of this piece is to gater any info useful
                #              for determining when it happens.
                LOG.exception('Creation of pod interface failed, most likely '
                              'due to duplicated VLAN id. This will probably '
                              'cause kuryr-daemon to crashloop. Trying to '
                              'gather debugging information.')

                with b_base.get_ipdb() as h_ipdb:
                    LOG.error('List of host interfaces: %s', h_ipdb.interfaces)

                with b_base.get_ipdb(netns) as c_ipdb:
                    LOG.error('List of pod namespace interfaces: %s',
                              c_ipdb.interfaces)
            raise

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

    def _get_iface_create_args(self, vif):
        return {'kind': VLAN_KIND, 'vlan_id': vif.vlan_id}


class MacvlanDriver(NestedDriver):

    def __init__(self):
        super(MacvlanDriver, self).__init__()

    def _get_iface_create_args(self, vif):
        return {'kind': MACVLAN_KIND, 'macvlan_mode': MACVLAN_MODE_BRIDGE}
