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
import six

from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes import config
from kuryr_kubernetes.handlers import health
from kuryr_kubernetes import utils

VLAN_KIND = 'vlan'
MACVLAN_KIND = 'macvlan'
MACVLAN_MODE_BRIDGE = 'bridge'


@six.add_metaclass(abc.ABCMeta)
class NestedDriver(health.HealthHandler, b_base.BaseBindingDriver):

    def __init__(self):
        super(NestedDriver, self).__init__()

    @abc.abstractmethod
    def _get_iface_create_args(self, vif):
        raise NotImplementedError()

    def connect(self, vif, ifname, netns, container_id):
        with b_base.get_ipdb() as h_ipdb:
            # NOTE(vikasc): Ideally 'ifname' should be used here but instead a
            # temporary name is being used while creating the device for
            # container in host network namespace. This is because cni expects
            # only 'eth0' as interface name and if host already has an
            # interface named 'eth0', device creation will fail with 'already
            # exists' error.
            temp_name = vif.vif_name

            # TODO(vikasc): evaluate whether we should have stevedore
            #               driver for getting the link device.
            vm_iface_name = config.CONF.binding.link_iface

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
        # NOTE(vikasc): device will get deleted with container namespace, so
        # nothing to be done here.
        pass


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
