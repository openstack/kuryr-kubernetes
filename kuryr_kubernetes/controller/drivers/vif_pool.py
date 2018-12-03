# Copyright (c) 2017 Red Hat, Inc.
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
import collections
import eventlet
import six
import time

from kuryr.lib._i18n import _
from kuryr.lib import constants as kl_const
from neutronclient.common import exceptions as n_exc
from oslo_cache import core as cache
from oslo_concurrency import lockutils
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import utils as c_utils
from kuryr_kubernetes.controller.managers import pool
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import os_vif_util as ovu
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)

# Moved out from neutron_default group
vif_pool_driver_opts = [
    oslo_cfg.IntOpt('ports_pool_max',
                    help=_("Set a maximun amount of ports per pool. "
                           "0 to disable"),
                    default=0),
    oslo_cfg.IntOpt('ports_pool_min',
                    help=_("Set a target minimum size of the pool of ports"),
                    default=5),
    oslo_cfg.IntOpt('ports_pool_batch',
                    help=_("Number of ports to be created in a bulk request"),
                    default=10),
    oslo_cfg.IntOpt('ports_pool_update_frequency',
                    help=_("Minimun interval (in seconds) "
                           "between pool updates"),
                    default=20),
    oslo_cfg.DictOpt('pools_vif_drivers',
                     help=_("Dict with the pool driver and pod driver to be "
                            "used. If not set, it will take them from the "
                            "kubernetes driver options for pool and pod "
                            "drivers respectively"),
                     default={}),
]

oslo_cfg.CONF.register_opts(vif_pool_driver_opts, "vif_pool")

node_vif_driver_caching_opts = [
    oslo_cfg.BoolOpt('caching', default=True),
    oslo_cfg.IntOpt('cache_time', default=3600),
]

oslo_cfg.CONF.register_opts(node_vif_driver_caching_opts,
                            "node_driver_caching")

cache.configure(oslo_cfg.CONF)
node_driver_cache_region = cache.create_region()
MEMOIZE = cache.get_memoization_decorator(
    oslo_cfg.CONF, node_driver_cache_region, "node_driver_caching")

cache.configure_cache_region(oslo_cfg.CONF, node_driver_cache_region)

VIF_TYPE_TO_DRIVER_MAPPING = {
    'VIFOpenVSwitch': 'neutron-vif',
    'VIFBridge': 'neutron-vif',
    'VIFVlanNested': 'nested-vlan',
    'VIFMacvlanNested': 'nested-macvlan',
    'VIFSriov': 'sriov'
}


class NoopVIFPool(base.VIFPoolDriver):
    """No pool VIFs for Kubernetes Pods"""

    def set_vif_driver(self, driver):
        self._drv_vif = driver

    def request_vif(self, pod, project_id, subnets, security_groups):
        return self._drv_vif.request_vif(pod, project_id, subnets,
                                         security_groups)

    def release_vif(self, pod, vif, *argv):
        self._drv_vif.release_vif(pod, vif, *argv)

    def activate_vif(self, pod, vif):
        self._drv_vif.activate_vif(pod, vif)

    def update_vif_sgs(self, pod, sgs):
        self._drv_vif.update_vif_sgs(pod, sgs)

    def sync_pools(self):
        pass


@six.add_metaclass(abc.ABCMeta)
class BaseVIFPool(base.VIFPoolDriver):
    """Skeletal pool driver.

    In order to handle the pools of ports, a few dicts are used:
    _available_ports_pool is a dictionary with the ready to use Neutron ports
    information. The keys are the 'pool_key' and the values the 'port_id's.
    _existing_vifs is a dictionary containing the port vif objects. The keys
    are the 'port_id' and the values are the vif objects.
    _recyclable_ports is a dictionary with the Neutron ports to be
    recycled. The keys are the 'port_id' and their values are the 'pool_key'.
    _last_update is a dictionary with the timestamp of the last population
    action for each pool. The keys are the pool_keys and the values are the
    timestamps.

    The following driver configuration options exist:
    - ports_pool_max: it specifies how many ports can be kept at each pool.
    If the pool already reached the specified size, the ports to be recycled
    are deleted instead. If set to 0, the limit is disabled and ports are
    always recycled.
    - ports_pool_min: minimum desired number of ready to use ports at populated
    pools. Should be smaller than ports_pool_max (if enabled).
    - ports_pool_batch: target number of ports to be created in bulk requests
    when populating pools.
    - ports_pool_update_frequency: interval in seconds between ports pool
    updates, both for populating pools as well as for recycling ports.
    """

    def __init__(self):
        # Note(ltomasbo) Execute the port recycling periodic actions in a
        # background thread
        eventlet.spawn(self._return_ports_to_pool)

    def set_vif_driver(self, driver):
        self._drv_vif = driver

    def activate_vif(self, pod, vif):
        self._drv_vif.activate_vif(pod, vif)

    def update_vif_sgs(self, pod, sgs):
        self._drv_vif.update_vif_sgs(pod, sgs)

    def _get_pool_size(self, pool_key=None):
        return len(self._available_ports_pools.get(pool_key, []))

    def _get_host_addr(self, pod):
        return pod['status']['hostIP']

    def _get_pool_key(self, host, project_id, security_groups, net_id=None,
                      subnets=None):
        if not net_id and subnets:
            net_obj = list(subnets.values())[0]
            net_id = net_obj.id
        pool_key = (host, project_id, tuple(sorted(security_groups)),
                    net_id)
        return pool_key

    def _get_pool_key_net(self, pool_key):
        return pool_key[3]

    def request_vif(self, pod, project_id, subnets, security_groups):
        try:
            host_addr = self._get_host_addr(pod)
        except KeyError:
            LOG.warning("Pod has not been scheduled yet.")
            raise
        pool_key = self._get_pool_key(host_addr, project_id, security_groups,
                                      None, subnets)

        try:
            return self._get_port_from_pool(pool_key, pod, subnets)
        except exceptions.ResourceNotReady as ex:
            LOG.warning("Ports pool does not have available ports!")
            eventlet.spawn(self._populate_pool, pool_key, pod, subnets)
            raise ex

    def _get_port_from_pool(self, pool_key, pod, subnets):
        raise NotImplementedError()

    def _populate_pool(self, pool_key, pod, subnets):
        # REVISIT(ltomasbo): Drop the subnets parameter and get the information
        # from the pool_key, which will be required when multi-network is
        # supported
        now = time.time()
        try:
            if (now - oslo_cfg.CONF.vif_pool.ports_pool_update_frequency <
                    self._last_update.get(pool_key, 0)):
                LOG.info("Not enough time since the last pool update")
                return
        except AttributeError:
            LOG.info("Kuryr-controller not yet ready to populate pools")
            return
        self._last_update[pool_key] = now

        pool_size = self._get_pool_size(pool_key)
        if pool_size < oslo_cfg.CONF.vif_pool.ports_pool_min:
            num_ports = max(oslo_cfg.CONF.vif_pool.ports_pool_batch,
                            oslo_cfg.CONF.vif_pool.ports_pool_min - pool_size)
            vifs = self._drv_vif.request_vifs(
                pod=pod,
                project_id=pool_key[1],
                subnets=subnets,
                security_groups=list(pool_key[2]),
                num_ports=num_ports)
            for vif in vifs:
                self._existing_vifs[vif.id] = vif
                self._available_ports_pools.setdefault(pool_key,
                                                       []).append(vif.id)

    def release_vif(self, pod, vif, project_id, security_groups):
        host_addr = self._get_host_addr(pod)

        pool_key = self._get_pool_key(host_addr, project_id, security_groups,
                                      vif.network.id, None)

        try:
            if not self._existing_vifs.get(vif.id):
                self._existing_vifs[vif.id] = vif
            self._recyclable_ports[vif.id] = pool_key
        except AttributeError:
            LOG.info("Kuryr-controller is not ready to handle the pools yet.")
            raise exceptions.ResourceNotReady(pod)

    def _return_ports_to_pool(self):
        raise NotImplementedError()

    def _recover_precreated_ports(self):
        raise NotImplementedError()

    def _get_ports_by_attrs(self, **attrs):
        neutron = clients.get_neutron_client()
        ports = neutron.list_ports(**attrs)
        return ports['ports']

    def _get_in_use_ports(self):
        kubernetes = clients.get_kubernetes_client()
        in_use_ports = []
        running_pods = kubernetes.get(constants.K8S_API_BASE + '/pods')
        for pod in running_pods['items']:
            try:
                annotations = jsonutils.loads(pod['metadata']['annotations'][
                    constants.K8S_ANNOTATION_VIF])
                pod_state = utils.extract_pod_annotation(annotations)
            except KeyError:
                LOG.debug("Skipping pod without kuryr VIF annotation: %s",
                          pod)
            else:
                for vif in pod_state.vifs.values():
                    in_use_ports.append(vif.id)
        return in_use_ports

    def list_pools(self):
        return self._available_ports_pools

    def show_pool(self, pool_key):
        return self._available_ports_pools.get(pool_key)

    def delete_network_pools(self, net_id):
        raise NotImplementedError()

    def _create_healthcheck_file(self):
        # Note(ltomasbo): Create a health check file when the pre-created
        # ports are loaded into their corresponding pools. This file is used
        # by the readiness probe when the controller is deployed in
        # containerized mode. This way the controller pod will not be ready
        # until all the pre-created ports have been loaded
        try:
            with open('/tmp/pools_loaded', 'a'):
                LOG.debug("Health check file created for readiness probe")
        except IOError:
            LOG.exception("I/O error creating the health check file.")

    @lockutils.synchronized('return_to_pool_baremetal')
    @lockutils.synchronized('return_to_pool_nested')
    def sync_pools(self):
        self._available_ports_pools = collections.defaultdict(
            collections.deque)
        self._existing_vifs = collections.defaultdict(collections.defaultdict)
        self._recyclable_ports = collections.defaultdict(
            collections.defaultdict)
        self._last_update = collections.defaultdict(collections.defaultdict)
        # NOTE(ltomasbo): Ensure previously created ports are recovered into
        # their respective pools
        self._recover_precreated_ports()


class NeutronVIFPool(BaseVIFPool):
    """Manages VIFs for Bare Metal Kubernetes Pods."""

    def _get_host_addr(self, pod):
        return pod['spec']['nodeName']

    def _get_port_from_pool(self, pool_key, pod, subnets):
        try:
            port_id = self._available_ports_pools[pool_key].pop()
        except (IndexError, AttributeError):
            raise exceptions.ResourceNotReady(pod)
        if config.CONF.kubernetes.port_debug:
            neutron = clients.get_neutron_client()
            neutron.update_port(
                port_id,
                {
                    "port": {
                        'name': c_utils.get_port_name(pod),
                        'device_id': pod['metadata']['uid']
                    }
                })
        # check if the pool needs to be populated
        if (self._get_pool_size(pool_key) <
                oslo_cfg.CONF.vif_pool.ports_pool_min):
            eventlet.spawn(self._populate_pool, pool_key, pod, subnets)
        return self._existing_vifs[port_id]

    def _return_ports_to_pool(self):
        """Recycle ports to be reused by future pods.

        For each port in the recyclable_ports dict it reaplies
        security group if they have been changed and it changes the port
        name to available_port if the port_debug option is enabled.
        Then the port_id is included in the dict with the available_ports.

        If a maximun number of port per pool is set, the port will be
        deleted if the maximun has been already reached.
        """
        while True:
            eventlet.sleep(oslo_cfg.CONF.vif_pool.ports_pool_update_frequency)
            self._trigger_return_to_pool()

    @lockutils.synchronized('return_to_pool_baremetal')
    def _trigger_return_to_pool(self):
        if not hasattr(self, '_recyclable_ports'):
            LOG.info("Kuryr-controller not yet ready to return ports to "
                     "pools.")
            return
        neutron = clients.get_neutron_client()
        sg_current = {}
        if not config.CONF.kubernetes.port_debug:
            kuryr_ports = self._get_ports_by_attrs(
                device_owner=kl_const.DEVICE_OWNER)
            for port in kuryr_ports:
                if port['id'] in self._recyclable_ports.keys():
                    sg_current[port['id']] = port['security_groups']

        for port_id, pool_key in self._recyclable_ports.copy().items():
            if (not oslo_cfg.CONF.vif_pool.ports_pool_max or
                self._get_pool_size(pool_key) <
                    oslo_cfg.CONF.vif_pool.ports_pool_max):
                port_name = (constants.KURYR_PORT_NAME
                             if config.CONF.kubernetes.port_debug
                             else '')
                if (config.CONF.kubernetes.port_debug or
                        list(pool_key[2]) != sg_current.get(port_id)):
                    try:
                        neutron.update_port(
                            port_id,
                            {
                                "port": {
                                    'name': port_name,
                                    'device_id': '',
                                    'security_groups': list(pool_key[2])
                                }
                            })
                    except n_exc.NeutronClientException:
                        LOG.warning("Error preparing port %s to be "
                                    "reused, put back on the cleanable "
                                    "pool.", port_id)
                        continue
                self._available_ports_pools.setdefault(
                    pool_key, []).append(port_id)
            else:
                try:
                    del self._existing_vifs[port_id]
                    neutron.delete_port(port_id)
                except n_exc.PortNotFoundClient:
                    LOG.debug('Unable to release port %s as it no longer '
                              'exists.', port_id)
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', port_id)
            try:
                del self._recyclable_ports[port_id]
            except KeyError:
                LOG.debug('Port already recycled: %s', port_id)

    def _recover_precreated_ports(self):
        if config.CONF.kubernetes.port_debug:
            available_ports = self._get_ports_by_attrs(
                name=constants.KURYR_PORT_NAME, device_owner=[
                    kl_const.DEVICE_OWNER])
        else:
            kuryr_ports = self._get_ports_by_attrs(
                device_owner=kl_const.DEVICE_OWNER)
            in_use_ports = self._get_in_use_ports()
            available_ports = [port for port in kuryr_ports
                               if port['id'] not in in_use_ports]

        for port in available_ports:
            subnet_id = port['fixed_ips'][0]['subnet_id']
            subnet = {
                subnet_id: utils.get_subnet(subnet_id)}
            vif_plugin = self._drv_vif._get_vif_plugin(port)
            vif = ovu.neutron_to_osvif_vif(vif_plugin, port, subnet)
            net_obj = subnet[subnet_id]
            pool_key = self._get_pool_key(port['binding:host_id'],
                                          port['project_id'],
                                          port['security_groups'],
                                          net_obj.id, None)

            self._existing_vifs[port['id']] = vif
            self._available_ports_pools.setdefault(
                pool_key, []).append(port['id'])

        LOG.info("PORTS POOL: pools updated with pre-created ports")
        self._create_healthcheck_file()

    def delete_network_pools(self, net_id):
        if not hasattr(self, '_available_ports_pools'):
            LOG.info("Kuryr-controller not yet ready to delete network "
                     "pools.")
            raise exceptions.ResourceNotReady(net_id)
        neutron = clients.get_neutron_client()

        # NOTE(ltomasbo): Note the pods should already be deleted, but their
        # associated ports may not have been recycled yet, therefore not being
        # on the available_ports_pools dict. The next call forces it to be on
        # that dict before cleaning it up
        self._trigger_return_to_pool()
        for pool_key, ports_id in self._available_ports_pools.items():
            if self._get_pool_key_net(pool_key) != net_id:
                continue
            self._available_ports_pools[pool_key] = []
            for port_id in ports_id:
                try:
                    del self._existing_vifs[port_id]
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', port_id)
                try:
                    neutron.delete_port(port_id)
                except n_exc.PortNotFoundClient:
                    LOG.debug('Unable to release port %s as it no longer '
                              'exists.', port_id)


class NestedVIFPool(BaseVIFPool):
    """Manages VIFs for nested Kubernetes Pods.

    In order to handle the pools of ports for nested Pods, an extra dict is
    used:
    _known_trunk_ids is a dictionary that keeps the trunk port ids associated
    to each pool_key to skip calls to neutron to get the trunk information.
    """
    _known_trunk_ids = collections.defaultdict(str)

    def __init__(self):
        super(NestedVIFPool, self).__init__()
        # Start the pool manager so that pools can be populated/freed on
        # demand
        if config.CONF.kubernetes.enable_manager:
            self._pool_manager = pool.PoolManager()

    def set_vif_driver(self, driver):
        self._drv_vif = driver

    def _get_port_from_pool(self, pool_key, pod, subnets):
        try:
            port_id = self._available_ports_pools[pool_key].pop()
        except (IndexError, AttributeError):
            raise exceptions.ResourceNotReady(pod)
        if config.CONF.kubernetes.port_debug:
            neutron = clients.get_neutron_client()
            neutron.update_port(
                port_id,
                {
                    "port": {
                        'name': c_utils.get_port_name(pod),
                    }
                })
        # check if the pool needs to be populated
        if (self._get_pool_size(pool_key) <
                oslo_cfg.CONF.vif_pool.ports_pool_min):
            eventlet.spawn(self._populate_pool, pool_key, pod, subnets)
        return self._existing_vifs[port_id]

    def _return_ports_to_pool(self):
        """Recycle ports to be reused by future pods.

        For each port in the recyclable_ports dict it reaplies
        security group if they have been changed and it changes the port
        name to available_port if the port_debug option is enabled.
        Then the port_id is included in the dict with the available_ports.

        If a maximun number of ports per pool is set, the port will be
        deleted if the maximun has been already reached.
        """
        while True:
            eventlet.sleep(oslo_cfg.CONF.vif_pool.ports_pool_update_frequency)
            self._trigger_return_to_pool()

    @lockutils.synchronized('return_to_pool_nested')
    def _trigger_return_to_pool(self):
        if not hasattr(self, '_recyclable_ports'):
            LOG.info("Kuryr-controller not yet ready to return ports to "
                     "pools.")
            return
        neutron = clients.get_neutron_client()
        sg_current = {}
        if not config.CONF.kubernetes.port_debug:
            kuryr_subports = self._get_ports_by_attrs(
                device_owner=['trunk:subport', kl_const.DEVICE_OWNER])
            for subport in kuryr_subports:
                if subport['id'] in self._recyclable_ports.keys():
                    sg_current[subport['id']] = subport['security_groups']

        for port_id, pool_key in self._recyclable_ports.copy().items():
            if (not oslo_cfg.CONF.vif_pool.ports_pool_max or
                self._get_pool_size(pool_key) <
                    oslo_cfg.CONF.vif_pool.ports_pool_max):
                port_name = (constants.KURYR_PORT_NAME
                             if config.CONF.kubernetes.port_debug
                             else '')
                if (config.CONF.kubernetes.port_debug or
                        list(pool_key[2]) != sg_current.get(port_id)):
                    try:
                        neutron.update_port(
                            port_id,
                            {
                                "port": {
                                    'name': port_name,
                                    'security_groups': list(pool_key[2])
                                }
                            })
                    except n_exc.NeutronClientException:
                        LOG.warning("Error preparing port %s to be "
                                    "reused, put back on the cleanable "
                                    "pool.", port_id)
                        continue
                self._available_ports_pools.setdefault(
                    pool_key, []).append(port_id)
            else:
                trunk_id = self._get_trunk_id(neutron, pool_key)
                try:
                    self._drv_vif._remove_subport(neutron, trunk_id,
                                                  port_id)
                    self._drv_vif._release_vlan_id(
                        self._existing_vifs[port_id].vlan_id)
                    del self._existing_vifs[port_id]
                    neutron.delete_port(port_id)
                except n_exc.PortNotFoundClient:
                    LOG.debug('Unable to release port %s as it no longer '
                              'exists.', port_id)
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', port_id)
                except n_exc.NeutronClientException:
                    LOG.warning('Error removing the subport %s', port_id)
                    continue
            try:
                del self._recyclable_ports[port_id]
            except KeyError:
                LOG.debug('Port already recycled: %s', port_id)

    def _get_trunk_id(self, neutron, pool_key):
        trunk_id = self._known_trunk_ids.get(pool_key, None)
        if not trunk_id:
            p_port = self._drv_vif._get_parent_port_by_host_ip(
                neutron, pool_key[0])
            trunk_id = self._drv_vif._get_trunk_id(p_port)
            self._known_trunk_ids[pool_key] = trunk_id
        return trunk_id

    def _get_parent_port_ip(self, port_id):
        neutron = clients.get_neutron_client()
        parent_port = neutron.show_port(port_id).get('port')
        return parent_port['fixed_ips'][0]['ip_address']

    def _get_trunks_info(self):
        """Returns information about trunks and their subports.

        This method searches for parent ports and subports among the active
        neutron ports.
        To find the parent ports it filters the ones that have trunk_details,
        i.e., the ones that are the parent port of a trunk.
        To find the subports to recover, it filters out the ports that are
        already in used by running kubernetes pods. It also filters out the
        ports whose device_owner is not related to subports, i.e., the ports
        that are not attached to trunks, such as active ports allocated to
        running VMs.
        At the same time it collects information about ports subnets to
        minimize the number of interaction with Neutron API.

        It returns three dictionaries with the needed information about the
        parent ports, subports and subnets

        :return: 3 dicts with the trunk details (Key: trunk_id; Value: dict
        containing ip and subports), subport details (Key: port_id; Value:
        port_object), and subnet details (Key: subnet_id; Value: subnet dict)
        """
        # REVISIT(ltomasbo): there is no need to recover the subports
        # belonging to trunk ports whose parent port is DOWN as that means no
        # pods can be scheduled there. We may need to update this if we allow
        # lively extending the kubernetes cluster with VMs that already have
        # precreated subports. For instance by shutting down and up a
        # kubernetes Worker VM with subports already attached, and the
        # controller is restarted in between.
        parent_ports = {}
        subports = {}
        subnets = {}

        all_active_ports = self._get_ports_by_attrs(status='ACTIVE')
        in_use_ports = self._get_in_use_ports()

        for port in all_active_ports:
            trunk_details = port.get('trunk_details')
            # Parent port
            if trunk_details:
                parent_ports[trunk_details['trunk_id']] = {
                    'ip': port['fixed_ips'][0]['ip_address'],
                    'subports': trunk_details['sub_ports']}
            else:
                # Filter to only get subports that are not in use
                if (port['id'] not in in_use_ports and
                    port['device_owner'] in ['trunk:subport',
                                             kl_const.DEVICE_OWNER]):
                    subports[port['id']] = port
                    # NOTE(ltomasbo): _get_subnet can be costly as it
                    # needs to call neutron to get network and subnet
                    # information. This ensures it is only called once
                    # per subnet in use
                    subnet_id = port['fixed_ips'][0]['subnet_id']
                    if not subnets.get(subnet_id):
                        subnets[subnet_id] = {subnet_id:
                                              utils.get_subnet(
                                                  subnet_id)}
        return parent_ports, subports, subnets

    def _recover_precreated_ports(self):
        self._precreated_ports(action='recover')
        LOG.info("PORTS POOL: pools updated with pre-created ports")
        self._create_healthcheck_file()

    def _remove_precreated_ports(self, trunk_ips=None):
        self._precreated_ports(action='free', trunk_ips=trunk_ips)

    def _precreated_ports(self, action, trunk_ips=None):
        """Removes or recovers pre-created subports at given pools

        This function handles the pre-created ports based on the given action:
        - If action is `free` it will remove all the subport from the given
        trunk ports, or from all the trunk ports if no trunk_ips are passed.
        - If action is `recover` it will discover the existing subports in the
        given trunk ports (or in all of them if none are passed) and will add
        them (and the needed information) to the respective pools.
        """
        neutron = clients.get_neutron_client()
        # Note(ltomasbo): ML2/OVS changes the device_owner to trunk:subport
        # when a port is attached to a trunk. However, that is not the case
        # for other ML2 drivers, such as ODL. So we also need to look for
        # compute:kuryr

        parent_ports, available_subports, subnets = self._get_trunks_info()

        if not available_subports:
            return

        for trunk_id, parent_port in parent_ports.items():
            host_addr = parent_port.get('ip')
            if trunk_ips and host_addr not in trunk_ips:
                continue

            for subport in parent_port.get('subports'):
                kuryr_subport = available_subports.get(subport['port_id'])
                if kuryr_subport:
                    subnet_id = kuryr_subport['fixed_ips'][0]['subnet_id']
                    subnet = subnets[subnet_id]
                    net_obj = subnet[subnet_id]
                    pool_key = self._get_pool_key(host_addr,
                                                  kuryr_subport['project_id'],
                                                  kuryr_subport[
                                                      'security_groups'],
                                                  net_obj.id, None)

                    if action == 'recover':
                        vif = ovu.neutron_to_osvif_vif_nested_vlan(
                            kuryr_subport, subnet, subport['segmentation_id'])

                        self._existing_vifs[kuryr_subport['id']] = vif
                        self._available_ports_pools.setdefault(
                            pool_key, []).append(kuryr_subport['id'])

                    elif action == 'free':
                        try:
                            self._drv_vif._remove_subport(neutron, trunk_id,
                                                          kuryr_subport['id'])
                            neutron.delete_port(kuryr_subport['id'])
                            self._drv_vif._release_vlan_id(
                                subport['segmentation_id'])
                            del self._existing_vifs[kuryr_subport['id']]
                            self._available_ports_pools[pool_key].remove(
                                kuryr_subport['id'])
                        except n_exc.PortNotFoundClient:
                            LOG.debug('Unable to release port %s as it no '
                                      'longer exists.', kuryr_subport['id'])
                        except KeyError:
                            LOG.debug('Port %s is not in the ports list.',
                                      kuryr_subport['id'])
                        except n_exc.NeutronClientException:
                            LOG.warning('Error removing the subport %s',
                                        kuryr_subport['id'])
                        except ValueError:
                            LOG.debug('Port %s is not in the available ports '
                                      'pool.', kuryr_subport['id'])

    def force_populate_pool(self, trunk_ip, project_id, subnets,
                            security_groups, num_ports):
        """Create a given amount of subports at a given trunk port.

        This function creates a given amount of subports and attaches them to
        the specified trunk, adding them to the related subports pool
        regardless of the amount of subports already available in the pool.
        """
        vifs = self._drv_vif.request_vifs(
            pod=[],
            project_id=project_id,
            subnets=subnets,
            security_groups=security_groups,
            num_ports=num_ports,
            trunk_ip=trunk_ip)

        pool_key = self._get_pool_key(trunk_ip, project_id, security_groups,
                                      None, subnets)
        for vif in vifs:
            self._existing_vifs[vif.id] = vif
            self._available_ports_pools.setdefault(pool_key,
                                                   []).append(vif.id)

    def free_pool(self, trunk_ips=None):
        """Removes subports from the pool and deletes neutron port resource.

        This function empties the pool of available subports and removes the
        neutron port resources of the specified trunk port (or all of them if
        no trunk is specified).
        """
        self._remove_precreated_ports(trunk_ips)

    def delete_network_pools(self, net_id):
        if not hasattr(self, '_available_ports_pools'):
            LOG.info("Kuryr-controller not yet ready to delete network "
                     "pools.")
            raise exceptions.ResourceNotReady(net_id)
        neutron = clients.get_neutron_client()
        # NOTE(ltomasbo): Note the pods should already be deleted, but their
        # associated ports may not have been recycled yet, therefore not being
        # on the available_ports_pools dict. The next call forces it to be on
        # that dict before cleaning it up
        self._trigger_return_to_pool()
        for pool_key, ports_ids in self._available_ports_pools.items():
            if self._get_pool_key_net(pool_key) != net_id:
                continue
            self._available_ports_pools[pool_key] = []
            trunk_id = self._get_trunk_id(neutron, pool_key)
            try:
                self._drv_vif._remove_subports(neutron, trunk_id, ports_ids)
            except n_exc.NeutronClientException:
                LOG.exception('Error removing subports from trunk: %s',
                              trunk_id)
                continue

            for port_id in ports_ids:
                try:
                    self._drv_vif._release_vlan_id(
                        self._existing_vifs[port_id].vlan_id)
                    del self._existing_vifs[port_id]
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', port_id)
                try:
                    neutron.delete_port(port_id)
                except n_exc.PortNotFoundClient:
                    LOG.debug('Unable to delete subport %s as it no longer '
                              'exists.', port_id)


class MultiVIFPool(base.VIFPoolDriver):
    """Manages pools with different VIF types.

    It manages hybrid deployments containing both Bare Metal and Nested
    Kubernetes Pods. To do that it creates a pool per node with a different
    pool driver depending on the vif driver that the node is using.

    It assumes a label pod_vif is added to each node to inform about the
    driver set for that node. If no label is added, it assumes the default pod
    vif: the one specified at kuryr.conf
    """

    def set_vif_driver(self):
        self._vif_drvs = {}
        pools_vif_drivers = oslo_cfg.CONF.vif_pool.pools_vif_drivers
        if not pools_vif_drivers:
            pod_vif = oslo_cfg.CONF.kubernetes.pod_vif_driver
            drv_vif = base.PodVIFDriver.get_instance()
            drv_pool = base.VIFPoolDriver.get_instance()
            drv_pool.set_vif_driver(drv_vif)
            self._vif_drvs[pod_vif] = drv_pool
            return
        for pool_driver, pod_driver in pools_vif_drivers.items():
            if not utils.check_suitable_multi_pool_driver_opt(pool_driver,
                                                              pod_driver):
                LOG.error("The pool and pod driver selected are not "
                          "compatible. They will be skipped")
                raise exceptions.MultiPodDriverPoolConfigurationNotSupported()
            drv_vif = base.PodVIFDriver.get_instance(
                specific_driver=pod_driver)
            drv_pool = base.VIFPoolDriver.get_instance(
                specific_driver=pool_driver)
            drv_pool.set_vif_driver(drv_vif)
            self._vif_drvs[pod_driver] = drv_pool

    def request_vif(self, pod, project_id, subnets, security_groups):
        pod_vif_type = self._get_pod_vif_type(pod)
        return self._vif_drvs[pod_vif_type].request_vif(
            pod, project_id, subnets, security_groups)

    def release_vif(self, pod, vif, *argv):
        vif_drv_alias = self._get_vif_drv_alias(vif)
        self._vif_drvs[vif_drv_alias].release_vif(pod, vif, *argv)

    def activate_vif(self, pod, vif):
        vif_drv_alias = self._get_vif_drv_alias(vif)
        self._vif_drvs[vif_drv_alias].activate_vif(pod, vif)

    def update_vif_sgs(self, pod, sgs):
        pod_vif_type = self._get_pod_vif_type(pod)
        self._vif_drvs[pod_vif_type].update_vif_sgs(pod, sgs)

    def delete_network_pools(self, net_id):
        for vif_drv in self._vif_drvs.values():
            if str(vif_drv) == 'NoopVIFPool':
                continue
            vif_drv.delete_network_pools(net_id)

    def sync_pools(self):
        for vif_drv in self._vif_drvs.values():
            vif_drv.sync_pools()

    def _get_pod_vif_type(self, pod):
        node_name = pod['spec']['nodeName']
        return self._get_node_vif_driver(node_name)

    @MEMOIZE
    def _get_node_vif_driver(self, node_name):
        kubernetes = clients.get_kubernetes_client()
        node_info = kubernetes.get(
            constants.K8S_API_BASE + '/nodes/' + node_name)

        labels = node_info['metadata'].get('labels', None)
        if labels:
            pod_vif = labels.get('pod_vif',
                                 oslo_cfg.CONF.kubernetes.pod_vif_driver)
            return pod_vif
        return oslo_cfg.CONF.kubernetes.pod_vif_driver

    def _get_vif_drv_alias(self, vif):
        vif_type_name = type(vif).__name__
        return VIF_TYPE_TO_DRIVER_MAPPING[vif_type_name]
