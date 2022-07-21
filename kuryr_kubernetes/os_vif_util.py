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

from kuryr.lib._i18n import _
from kuryr.lib.binding.drivers import utils as kl_utils
from kuryr.lib import constants as kl_const
from os_vif.objects import fixed_ip as osv_fixed_ip
from os_vif.objects import network as osv_network
from os_vif.objects import route as osv_route
from os_vif.objects import subnet as osv_subnet
from os_vif.objects import vif as osv_vif
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging
from stevedore import driver as stv_driver
from vif_plug_ovs import constants as osv_const

from kuryr_kubernetes import config
from kuryr_kubernetes import constants as const
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import vif as k_vif
from kuryr_kubernetes import utils


LOG = logging.getLogger(__name__)

# REVISIT(ivc): consider making this module part of kuryr-lib
_VIF_TRANSLATOR_NAMESPACE = "kuryr_kubernetes.vif_translators"
_VIF_MANAGERS = {}


def neutron_to_osvif_network(os_network):
    """Converts Neutron network to os-vif Subnet.

    :param os_network: openstack.network.v2.netwrork.Network object.
    :return: an os-vif Network object
    """

    obj = osv_network.Network(id=os_network.id)

    if os_network.name is not None:
        obj.label = os_network.name

    if os_network.mtu is not None:
        obj.mtu = os_network.mtu

    # Vlan information will be used later in Sriov binding driver
    if os_network.provider_network_type == 'vlan':
        obj.should_provide_vlan = True
        obj.vlan = os_network.provider_segmentation_id

    return obj


def neutron_to_osvif_subnet(os_subnet):
    """Converts Neutron subnet to os-vif Subnet.

    :param os_subnet: openstack.network.v2.subnet.Subnet object
    :return: an os-vif Subnet object
    """

    obj = osv_subnet.Subnet(
        cidr=os_subnet.cidr,
        dns=os_subnet.dns_nameservers,
        routes=_neutron_to_osvif_routes(os_subnet.host_routes))

    if os_subnet.gateway_ip is not None:
        obj.gateway = os_subnet.gateway_ip

    return obj


def _neutron_to_osvif_routes(neutron_routes):
    """Converts Neutron host_routes to os-vif RouteList.

    :param neutron_routes: list of routes as returned by neutron client's
                           'show_subnet' in 'host_routes' attribute
    :return: an os-vif RouteList object
    """

    # NOTE(gryf): Nested attributes for OpenStackSDK objects are simple types,
    # like dicts and lists, that's why neutron_routes is a list of dicts.
    obj_list = [osv_route.Route(cidr=route['destination'],
                                gateway=route['nexthop'])
                for route in neutron_routes]

    return osv_route.RouteList(objects=obj_list)


def _make_vif_subnet(subnets, subnet_id):
    """Makes a copy of an os-vif Subnet from subnets mapping.

    :param subnets: subnet mapping as returned by PodSubnetsDriver.get_subnets
    :param subnet_id: ID of the subnet to extract from 'subnets' mapping
    :return: a copy of an os-vif Subnet object matching 'subnet_id'
    """

    network = subnets[subnet_id]

    if len(network.subnets.objects) != 1:
        raise k_exc.IntegrityError(_(
            "Network object for subnet %(subnet_id)s is invalid, "
            "must contain a single subnet, but %(num_subnets)s found") % {
            'subnet_id': subnet_id,
            'num_subnets': len(network.subnets.objects)})

    subnet = network.subnets.objects[0].obj_clone()
    subnet.ips = osv_fixed_ip.FixedIPList(objects=[])
    return subnet


def _make_vif_subnets(neutron_port, subnets):
    """Gets a list of os-vif Subnet objects for port.

    :param neutron_port: dict containing port information as returned by
                         neutron client's 'show_port' or
                         openstack.network.v2.port.Port object
    :param subnets: subnet mapping as returned by PodSubnetsDriver.get_subnets
    :return: list of os-vif Subnet object
    """

    vif_subnets = {}
    try:
        fixed_ips = neutron_port.get('fixed_ips', [])
        port_id = neutron_port.get('id')
    except TypeError:
        fixed_ips = neutron_port.fixed_ips
        port_id = neutron_port.get.id

    for neutron_fixed_ip in fixed_ips:
        subnet_id = neutron_fixed_ip['subnet_id']
        ip_address = neutron_fixed_ip['ip_address']

        if subnet_id not in subnets:
            continue

        try:
            subnet = vif_subnets[subnet_id]
        except KeyError:
            subnet = _make_vif_subnet(subnets, subnet_id)
            vif_subnets[subnet_id] = subnet

        subnet.ips.objects.append(osv_fixed_ip.FixedIP(address=ip_address))

    if not vif_subnets:
        raise k_exc.IntegrityError(_(
            "No valid subnets found for port %(port_id)s") % {
            'port_id': port_id})

    return list(vif_subnets.values())


def _make_vif_network(neutron_port, subnets):
    """Get an os-vif Network object for port.

    :param neutron_port: dict containing port information as returned by
                         neutron client's 'show_port', or
                         openstack.network.v2.port.Port object
    :param subnets: subnet mapping as returned by PodSubnetsDriver.get_subnets
    :return: os-vif Network object
    """

    # NOTE(gryf): Because we didn't convert macvlan driver, neutron_port can
    # be either a dict or an object
    try:
        network_id = neutron_port.get('network_id')
        port_id = neutron_port.get('id')
    except TypeError:
        network_id = neutron_port.network_id
        port_id = neutron_port.id

    try:
        network = next(net.obj_clone() for net in subnets.values()
                       if net.id == network_id)
    except StopIteration:
        raise k_exc.IntegrityError(_(
            "Port %(port_id)s belongs to network %(network_id)s, "
            "but requested networks are: %(requested_networks)s") % {
            'port_id': port_id,
            'network_id': network_id,
            'requested_networks': [net.id for net in subnets.values()]})

    network.subnets = osv_subnet.SubnetList(
        objects=_make_vif_subnets(neutron_port, subnets))

    return network


# TODO(a.perevalov) generalize it with get_veth_pair_names
# but it's reasonable if we're going to add vhostuser support
# into kuryr project
def _get_vhu_vif_name(port_id):
    ifname = osv_const.OVS_VHOSTUSER_PREFIX + port_id
    ifname = ifname[:kl_const.NIC_NAME_LEN]
    return ifname


def _get_vif_name(neutron_port):
    """Gets a VIF device name for port.

    :param neutron_port: dict containing port information as returned by
                         neutron client's 'show_port', or an port object
                         returned by openstack client.
    """

    try:
        port_id = neutron_port['id']
    except TypeError:
        port_id = neutron_port.id

    vif_name, _ = kl_utils.get_veth_pair_names(port_id)
    return vif_name


def _get_ovs_hybrid_bridge_name(os_port):
    """Gets a name of the Linux bridge name for hybrid OpenVSwitch port.

    :param os_port: openstack.network.v2.port.Port object
    """
    return ('qbr' + os_port.id)[:kl_const.NIC_NAME_LEN]


def _is_port_active(neutron_port):
    """Checks if port is active.

    :param neutron_port: dict containing port information as returned by
                         neutron client's 'show_port' or
                         openstack.network.v2.port.Port object
    """
    try:
        return (neutron_port['status'] == kl_const.PORT_STATUS_ACTIVE)
    except TypeError:
        return (neutron_port.status == kl_const.PORT_STATUS_ACTIVE)


def neutron_to_osvif_vif_ovs(vif_plugin, os_port, subnets):
    """Converts Neutron port to VIF object for os-vif 'ovs' plugin.

    :param vif_plugin: name of the os-vif plugin to use (i.e. 'ovs')
    :param os_port: openstack.network.v2.port.Port object
    :param subnets: subnet mapping as returned by PodSubnetsDriver.get_subnets
    :return: os-vif VIF object
    """
    profile = osv_vif.VIFPortProfileOpenVSwitch(interface_id=os_port.id)

    details = os_port.binding_vif_details or {}
    ovs_bridge = details.get('bridge_name',
                             config.CONF.neutron_defaults.ovs_bridge)
    if not ovs_bridge:
        raise oslo_cfg.RequiredOptError('ovs_bridge', 'neutron_defaults')

    network = _make_vif_network(os_port, subnets)
    network.bridge = ovs_bridge
    vhostuser_mode = details.get('vhostuser_mode', False)

    LOG.debug('Detected vhostuser_mode=%s for port %s', vhostuser_mode,
              os_port.id)
    if vhostuser_mode:
        # TODO(a.perevalov) obtain path to mount point from pod's mountVolumes
        vhostuser_mount_point = (config.CONF.vhostuser.mount_point)
        if not vhostuser_mount_point:
            raise oslo_cfg.RequiredOptError('vhostuser_mount_point',
                                            'neutron_defaults')
        vif_name = _get_vhu_vif_name(os_port.id)
        vif = osv_vif.VIFVHostUser(
            id=os_port.id,
            address=os_port.mac_address,
            network=network,
            has_traffic_filtering=details.get('port_filter', False),
            preserve_on_delete=False,
            active=_is_port_active(os_port),
            port_profile=profile,
            plugin='ovs',
            path=os.path.join(vhostuser_mount_point, vif_name),
            mode=vhostuser_mode,
            vif_name=vif_name,
            bridge_name=network.bridge)
    elif details.get('ovs_hybrid_plug'):
        vif = osv_vif.VIFBridge(
            id=os_port.id,
            address=os_port.mac_address,
            network=network,
            has_traffic_filtering=details.get('port_filter', False),
            preserve_on_delete=False,
            active=_is_port_active(os_port),
            port_profile=profile,
            plugin=vif_plugin,
            vif_name=_get_vif_name(os_port),
            bridge_name=_get_ovs_hybrid_bridge_name(os_port))
    else:
        vif = osv_vif.VIFOpenVSwitch(
            id=os_port.id,
            address=os_port.mac_address,
            network=network,
            has_traffic_filtering=details.get('port_filter', False),
            preserve_on_delete=False,
            active=_is_port_active(os_port),
            port_profile=profile,
            plugin=vif_plugin,
            vif_name=_get_vif_name(os_port),
            bridge_name=network.bridge)

    return vif


def neutron_to_osvif_vif_nested_vlan(os_port, subnets, vlan_id):
    """Converts Neutron port to VIF object for VLAN nested containers.

    :param os_port: openstack.network.v2.port.Port object
    :param subnets: subnet mapping as returned by PodSubnetsDriver.get_subnets
    :param vlan_id: VLAN id associated to the VIF object for the pod
    :return: kuryr-k8s native VIF object for VLAN nested
    """
    details = os_port.binding_vif_details or {}

    return k_vif.VIFVlanNested(
        id=os_port.id,
        address=os_port.mac_address,
        network=_make_vif_network(os_port, subnets),
        has_traffic_filtering=details.get('port_filter', False),
        preserve_on_delete=False,
        active=_is_port_active(os_port),
        plugin=const.K8S_OS_VIF_NOOP_PLUGIN,
        vif_name=_get_vif_name(os_port),
        vlan_id=vlan_id)


def neutron_to_osvif_vif_nested_macvlan(neutron_port, subnets):
    """Converts Neutron port to VIF object for MACVLAN nested containers.

    :param neutron_port: dict containing port information as returned by
                         neutron client's 'show_port'
    :param subnets: subnet mapping as returned by PodSubnetsDriver.get_subnets
    :return: kuryr-k8s native VIF object for MACVLAN nested
    """
    details = neutron_port.get('binding:vif_details', {})

    return k_vif.VIFMacvlanNested(
        id=neutron_port['id'],
        address=neutron_port['mac_address'],
        network=_make_vif_network(neutron_port, subnets),
        has_traffic_filtering=details.get('port_filter', False),
        preserve_on_delete=False,
        active=_is_port_active(neutron_port),
        plugin=const.K8S_OS_VIF_NOOP_PLUGIN,
        vif_name=_get_vif_name(neutron_port))


def neutron_to_osvif_vif_dpdk(os_port, subnets, pod):
    """Converts Neutron port to VIF object for nested dpdk containers.

    :param os_port: dict containing port information as returned by
                    neutron client's 'show_port'
    :param subnets: subnet mapping as returned by PodSubnetsDriver.get_subnets
    :param pod: pod object received by k8s and containing profile details
    :return: os-vif VIF object
    """

    details = os_port.get('binding:vif_details', {})
    profile = osv_vif.VIFPortProfileK8sDPDK(
        l3_setup=False,
        selflink=utils.get_res_link(pod))

    return k_vif.VIFDPDKNested(
        id=os_port['id'],
        port_profile=profile,
        address=os_port['mac_address'],
        network=_make_vif_network(os_port, subnets),
        has_traffic_filtering=details.get('port_filter', False),
        preserve_on_delete=False,
        active=_is_port_active(os_port),
        plugin=const.K8S_OS_VIF_NOOP_PLUGIN,
        pci_address="",
        dev_driver="",
        vif_name=_get_vif_name(os_port))


def neutron_to_osvif_vif(vif_translator, os_port, subnets):
    """Converts Neutron port to os-vif VIF object.

    :param vif_translator: name of the traslator for the os-vif plugin to use
    :param os_port: openstack.network.v2.port.Port object
    :param subnets: subnet mapping as returned by PodSubnetsDriver.get_subnets
    :return: os-vif VIF object
    """
    try:
        mgr = _VIF_MANAGERS[vif_translator]
    except KeyError:
        mgr = stv_driver.DriverManager(
            namespace=_VIF_TRANSLATOR_NAMESPACE,
            name=vif_translator, invoke_on_load=False)
        _VIF_MANAGERS[vif_translator] = mgr

    return mgr.driver(vif_translator, os_port, subnets)


def osvif_to_neutron_fixed_ips(subnets):
    fixed_ips = []

    for subnet_id, network in subnets.items():
        ips = []
        if len(network.subnets.objects) > 1:
            raise k_exc.IntegrityError(_(
                "Network object for subnet %(subnet_id)s is invalid, "
                "must contain a single subnet, but %(num_subnets)s found") % {
                'subnet_id': subnet_id,
                'num_subnets': len(network.subnets.objects)})

        for subnet in network.subnets.objects:
            if subnet.obj_attr_is_set('ips'):
                ips.extend([str(ip.address) for ip in subnet.ips.objects])
        if ips:
            fixed_ips.extend([{'subnet_id': subnet_id, 'ip_address': ip}
                              for ip in ips])
        else:
            fixed_ips.append({'subnet_id': subnet_id})

    return fixed_ips
