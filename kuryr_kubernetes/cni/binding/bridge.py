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
import os
from oslo_config import cfg
from oslo_log import log

from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes.handlers import health
from kuryr_kubernetes import linux_net_utils as net_utils

LOG = log.getLogger(__name__)
CONF = cfg.CONF


class BaseBridgeDriver(health.HealthHandler, b_base.BaseBindingDriver):

    def __init__(self):
        super(BaseBridgeDriver, self).__init__()

    def connect(self, vif, ifname, netns, container_id):
        host_ifname = vif.vif_name

        # NOTE(dulek): Check if we already run connect for this iface and if
        #              there's a leftover host-side vif. If so we need to
        #              remove it, its peer should get deleted automatically by
        #              the kernel.
        with b_base.get_ipdb() as h_ipdb:
            self._remove_ifaces(h_ipdb, (host_ifname,))

        interface_mtu = vif.network.mtu
        mtu_cfg = CONF.neutron_defaults.network_device_mtu
        if mtu_cfg and mtu_cfg < interface_mtu:
            interface_mtu = CONF.neutron_defaults.network_device_mtu

        with b_base.get_ipdb(netns) as c_ipdb:
            with c_ipdb.create(ifname=ifname, peer=host_ifname,
                               kind='veth') as c_iface:
                c_iface.mtu = interface_mtu
                c_iface.address = str(vif.address)
                c_iface.up()

            if netns:
                with c_ipdb.interfaces[host_ifname] as h_iface:
                    h_iface.net_ns_pid = os.getpid()

        with b_base.get_ipdb() as h_ipdb:
            with h_ipdb.interfaces[host_ifname] as h_iface:
                h_iface.mtu = interface_mtu
                h_iface.up()

    def disconnect(self, vif, ifname, netns, container_id):
        pass


class BridgeDriver(BaseBridgeDriver):
    def __init__(self):
        super(BridgeDriver, self).__init__()

    def connect(self, vif, ifname, netns, container_id):
        super(BridgeDriver, self).connect(vif, ifname, netns, container_id)
        host_ifname = vif.vif_name
        bridge_name = vif.bridge_name

        with b_base.get_ipdb() as h_ipdb:
            with h_ipdb.interfaces[bridge_name] as h_br:
                h_br.add_port(host_ifname)

    def disconnect(self, vif, ifname, netns, container_id):
        # NOTE(ivc): veth pair is destroyed automatically along with the
        # container namespace
        pass


class VIFOpenVSwitchDriver(BaseBridgeDriver):

    def __init__(self):
        super(VIFOpenVSwitchDriver, self).__init__()

    def connect(self, vif, ifname, netns, container_id):
        super(VIFOpenVSwitchDriver, self).connect(vif, ifname, netns,
                                                  container_id)
        # FIXME(irenab) use pod_id (neutron port device_id)
        instance_id = 'kuryr'
        net_utils.create_ovs_vif_port(vif.bridge_name, vif.vif_name,
                                      vif.port_profile.interface_id,
                                      vif.address, instance_id)

    def disconnect(self, vif, ifname, netns, container_id):
        super(VIFOpenVSwitchDriver, self).disconnect(vif, ifname, netns,
                                                     container_id)
        net_utils.delete_ovs_vif_port(vif.bridge_name, vif.vif_name)

    def is_alive(self):
        bridge_name = CONF.neutron_defaults.ovs_bridge
        try:
            with b_base.get_ipdb() as h_ipdb:
                h_ipdb.interfaces[bridge_name]
            return True
        except Exception:
            LOG.error("The configured ovs_bridge=%s integration interface "
                      "does not exists. Reporting that driver is not healthy.",
                      bridge_name)
            return False
