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
import os
import threading

import eventlet
from kuryr.lib._i18n import _
from kuryr.lib import constants as kl_const
from openstack import exceptions as os_exc
from oslo_cache import core as cache
from oslo_concurrency import lockutils
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging
from oslo_log import versionutils

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
                    help=_("Set a maximum amount of ports per pool. "
                           "0 to disable"),
                    default=0),
    oslo_cfg.IntOpt('ports_pool_min',
                    help=_("Set a target minimum size of the pool of ports"),
                    default=5),
    oslo_cfg.IntOpt('ports_pool_batch',
                    help=_("Number of ports to be created in a bulk request"),
                    default=10),
    oslo_cfg.IntOpt('ports_pool_update_frequency',
                    help=_("Minimum interval (in seconds) "
                           "between pool updates"),
                    default=20),
    oslo_cfg.DictOpt('pools_vif_drivers',
                     help=_("Dict with the pool driver and pod driver to be "
                            "used. If not set, it will take them from the "
                            "kubernetes driver options for pool and pod "
                            "drivers respectively"),
                     default={}, deprecated_for_removal=True,
                     deprecated_since="Stein",
                     deprecated_reason=_(
                         "Mapping from pool->vif does not allow different "
                         "vifs to use the same pool driver. "
                         "Use vif_pool_mapping instead.")),
    oslo_cfg.DictOpt('vif_pool_mapping',
                     help=_("Dict with the pod driver and the corresponding "
                            "pool driver to be used. If not set, it will take "
                            "them from the kubernetes driver options for pool "
                            "and pod drivers respectively"),
                     default={}),
]

oslo_cfg.CONF.register_opts(vif_pool_driver_opts, "vif_pool")

node_vif_driver_caching_opts = [
    oslo_cfg.BoolOpt('caching', default=True,
                     help=_('Enable caching of vifs.')),
    oslo_cfg.IntOpt('cache_time', default=3600,
                    help=_('TTL, in seconds, for cached vifs')),
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
    'VIFDPDKNested': 'nested-dpdk',
    'VIFVHostUser': 'neutron-vif',
}

NODE_PORTS_CLEAN_FREQUENCY = 600  # seconds
POPULATE_POOL_TIMEOUT = 420  # seconds
BULK_PORTS_CREATION_REQUESTS = 20


class NoopVIFPool(base.VIFPoolDriver):
    """No pool VIFs for Kubernetes Pods"""

    def set_vif_driver(self, driver):
        self._drv_vif = driver

    def request_vif(self, pod, project_id, subnets, security_groups):
        return self._drv_vif.request_vif(pod, project_id, subnets,
                                         security_groups)

    def release_vif(self, pod, vif, *argv):
        self._drv_vif.release_vif(pod, vif, *argv)

    def activate_vif(self, vif, **kwargs):
        self._drv_vif.activate_vif(vif, **kwargs)

    def update_vif_sgs(self, pod, sgs):
        self._drv_vif.update_vif_sgs(pod, sgs)

    def remove_sg_from_pools(self, sg_id, net_id):
        pass

    def sync_pools(self):
        pass


class BaseVIFPool(base.VIFPoolDriver, metaclass=abc.ABCMeta):
    """Skeletal pool driver.

    In order to handle the pools of ports, a few dicts are used:
    _available_ports_pool is a dictionary with the ready to use Neutron ports
    information. The keys are the 'pool_key' and the values the 'port_id's.
    _existing_vifs is a dictionary containing the port vif objects. The keys
    are the 'port_id' and the values are the vif objects.
    _recyclable_ports is a dictionary with the Neutron ports to be
    recycled. The keys are the 'port_id' and their values are the 'pool_key'.
    _populate_pool_lock is a dict with the pool_key as key and a lock as value.
    Also, there is a _lock to control access to _populate_pool_lock dict.

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
    updates for recycling ports.
    Also, it has a Semaphore _create_ports_semaphore to restrict the number of
    bulk Ports creation calls running in parallel.
    """

    def __init__(self):
        # Note(ltomasbo) Execute the port recycling periodic actions in a
        # background thread
        self._recovered_pools = False
        eventlet.spawn(self._return_ports_to_pool)
        eventlet.spawn(self._cleanup_removed_nodes)

    def set_vif_driver(self, driver):
        self._drv_vif = driver

    def activate_vif(self, vif, **kwargs):
        self._drv_vif.activate_vif(vif, **kwargs)

    def update_vif_sgs(self, pod, sgs):
        self._drv_vif.update_vif_sgs(pod, sgs)

    def _get_pool_size(self, pool_key):
        pool = self._available_ports_pools.get(pool_key, {})
        pool_members = []
        for port_list in pool.values():
            pool_members.extend(port_list)
        return len(pool_members)

    def _get_host_addr(self, pod):
        return pod['status']['hostIP']

    def _get_pool_key(self, host, project_id, net_id=None, subnets=None):
        if not net_id and subnets:
            net_obj = list(subnets.values())[0]
            net_id = net_obj.id
        pool_key = (host, project_id, net_id)
        return pool_key

    def _get_pool_key_net(self, pool_key):
        return pool_key[2]

    def request_vif(self, pod, project_id, subnets, security_groups):
        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to handle new pods.")
            raise exceptions.ResourceNotReady(pod)
        try:
            host_addr = self._get_host_addr(pod)
        except KeyError:
            return None

        pool_key = self._get_pool_key(host_addr, project_id, None, subnets)

        # NOTE(maysams): It's possible that more recent Pods will retrieve
        # the Ports from the pool that older Pods were waiting for. In case
        # this happens, the event will be retried.
        try:
            return self._get_port_from_pool(pool_key, pod, subnets,
                                            tuple(sorted(security_groups)))
        except exceptions.ResourceNotReady:
            LOG.debug("Ports pool does not have available ports: %s", pool_key)
            if self._populate_pool(pool_key, pod, subnets,
                                   tuple(sorted(security_groups))):
                return self._get_port_from_pool(
                    pool_key, pod, subnets, tuple(sorted(security_groups)))
            raise

    def _set_port_debug(self, port_id, pod):
        """_set_port_debug sets name to the port to simplify debugging"""
        raise NotImplementedError()

    def _get_populate_pool_lock(self, pool_key):
        with self._lock:
            return self._populate_pool_lock[pool_key]

    def _get_port_from_pool(self, pool_key, pod, subnets, security_groups):
        try:
            pool_ports = self._available_ports_pools[pool_key]
        except (KeyError, AttributeError):
            raise exceptions.ResourceNotReady(pod)

        try:
            port_id = pool_ports[security_groups].pop()
        except (KeyError, IndexError):
            # Get another port from the pool and update the SG to the
            # appropriate one. It uses a port from the group that was updated
            # longer ago - these will be at the front of the OrderedDict.
            for sg_group, ports in pool_ports.items():
                try:
                    port_id = pool_ports[sg_group].pop()
                    break
                except (IndexError, KeyError):
                    continue
            else:
                # pool is empty, no port to reuse
                raise exceptions.ResourceNotReady(pod)
            os_net = clients.get_network_client()
            os_net.update_port(port_id, security_groups=list(security_groups))
        if config.CONF.kubernetes.port_debug:
            self._set_port_debug(port_id, pod)
        eventlet.spawn(self._populate_pool, pool_key, pod, subnets,
                       security_groups)
        # Add protection from port_id not in existing_vifs
        try:
            port = self._existing_vifs[port_id]
        except KeyError:
            LOG.debug('Missing port on existing_vifs, this should not happen.'
                      ' Retrying.')
            raise exceptions.ResourceNotReady(pod)
        return port

    def _populate_pool(self, pool_key, pod, subnets, security_groups):
        # REVISIT(ltomasbo): Drop the subnets parameter and get the information
        # from the pool_key, which will be required when multi-network is
        # supported
        kubernetes = clients.get_kubernetes_client()

        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to populate pools.")
            return False
        ports_pool_min = oslo_cfg.CONF.vif_pool.ports_pool_min
        lock = self._get_populate_pool_lock(pool_key)
        # NOTE(maysams): Only allow one request vifs per pool and times out
        # if takes 420 sec.
        if lock.acquire(timeout=POPULATE_POOL_TIMEOUT):
            pool_size = self._get_pool_size(pool_key)
            try:
                if pool_size < ports_pool_min:
                    num_ports = max(oslo_cfg.CONF.vif_pool.ports_pool_batch,
                                    ports_pool_min - pool_size)
                    try:
                        vifs = self._drv_vif.request_vifs(
                            pod=pod,
                            project_id=pool_key[1],
                            subnets=subnets,
                            security_groups=security_groups,
                            num_ports=num_ports,
                            semaphore=self._create_ports_semaphore)
                    except os_exc.SDKException as exc:
                        kubernetes.add_event(
                            pod, 'FailToPopulateVIFPool',
                            f'There was an error during populating VIF pool '
                            f'for pod: {exc.message}', type_='Warning')
                        raise

                    for vif in vifs:
                        self._existing_vifs[vif.id] = vif
                        self._available_ports_pools[pool_key].setdefault(
                                security_groups, []).append(vif.id)
                    if vifs:
                        # Mark it as updated most recently.
                        self._available_ports_pools[pool_key].move_to_end(
                            security_groups)
            finally:
                lock.release()
        else:
            return False
        return True

    def release_vif(self, pod, vif, project_id, host_addr=None):
        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to remove pods.")
            raise exceptions.ResourceNotReady(pod)
        if not host_addr:
            host_addr = self._get_host_addr(pod)

        pool_key = self._get_pool_key(host_addr, project_id, vif.network.id,
                                      None)

        try:
            if not self._existing_vifs.get(vif.id):
                self._existing_vifs[vif.id] = vif
            self._recyclable_ports[vif.id] = pool_key
        except AttributeError:
            LOG.debug("Kuryr-controller is not ready to handle the pools yet.")
            raise exceptions.ResourceNotReady(pod)

    def _return_ports_to_pool(self):
        raise NotImplementedError()

    def _recover_precreated_ports(self):
        raise NotImplementedError()

    def _get_in_use_ports_info(self):
        kubernetes = clients.get_kubernetes_client()
        in_use_ports = []
        networks = {}
        kuryr_ports = kubernetes.get(constants.K8S_API_CRD_KURYRPORTS)
        for kp in kuryr_ports['items']:
            vifs = c_utils.get_vifs(kp)
            for data in vifs.values():
                in_use_ports.append(data.id)
                networks[data.network.id] = data.network
        return in_use_ports, networks

    def list_pools(self):
        return self._available_ports_pools

    def show_pool(self, pool_key):
        return self._available_ports_pools.get(pool_key)

    def delete_network_pools(self, net_id):
        raise NotImplementedError()

    def remove_sg_from_pools(self, sg_id, net_id):
        os_net = clients.get_network_client()
        for pool_key, pool_ports in list(self._available_ports_pools.items()):
            if self._get_pool_key_net(pool_key) != net_id:
                continue
            for sg_key, ports in list(pool_ports.items()):
                if sg_id not in sg_key:
                    continue
                # remove the pool associated to that SG
                try:
                    del self._available_ports_pools[pool_key][sg_key]
                except KeyError:
                    LOG.debug("SG already removed from the pool. Ports "
                              "already re-used, no need to change their "
                              "associated SGs.")
                    continue
                for port_id in ports:
                    # remove all SGs from the port to be reused
                    os_net.update_port(port_id, security_groups=None)
                    # add the port to the default pool
                    self._available_ports_pools[pool_key].setdefault(
                        (), []).append(port_id)
                # NOTE(ltomasbo): as this ports were not created for this
                # pool, ensuring they are used first, marking them as the
                # most outdated
                self._available_ports_pools[pool_key].move_to_end(
                    (), last=False)

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
        # NOTE(ltomasbo): Ensure readiness probe is not set to true until the
        # pools sync is completed in case of controller restart
        try:
            os.remove('/tmp/pools_loaded')
        except OSError:
            pass

        self._available_ports_pools = collections.defaultdict(
            collections.OrderedDict)
        self._existing_vifs = collections.defaultdict()
        self._recyclable_ports = collections.defaultdict()
        self._lock = threading.Lock()
        self._populate_pool_lock = collections.defaultdict(threading.Lock)
        semaphore = eventlet.semaphore.Semaphore(BULK_PORTS_CREATION_REQUESTS)
        self._create_ports_semaphore = semaphore

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
        os_net = clients.get_network_client()
        parent_ports = {}
        subports = {}
        subnets = {}

        attrs = {'status': 'ACTIVE'}
        tags = config.CONF.neutron_defaults.resource_tags
        if tags:
            attrs['tags'] = tags

        all_active_ports = os_net.ports(**attrs)
        in_use_ports, in_use_networks = self._get_in_use_ports_info()

        for port in all_active_ports:
            # Parent port
            # NOTE(dulek): We do not filter by worker_nodes_subnets here
            #              meaning that we might include some unrelated trunks,
            #              but the consequence is only memory usage.
            if port.trunk_details and port.fixed_ips:
                parent_ports[port.trunk_details['trunk_id']] = {
                    'ip': port.fixed_ips[0]['ip_address'],
                    'subports': port.trunk_details['sub_ports']}
            else:
                # Filter to only get subports that are not in use
                if (port.id not in in_use_ports and
                    port.device_owner in ['trunk:subport',
                                          kl_const.DEVICE_OWNER]):
                    subports[port.id] = port
                    # NOTE(ltomasbo): _get_subnet can be costly as it
                    # needs to call neutron to get network and subnet
                    # information. This ensures it is only called once
                    # per subnet in use
                    subnet_id = port.fixed_ips[0]['subnet_id']
                    if not subnets.get(subnet_id):
                        # NOTE(maysams): Avoid calling Neutron by
                        # getting the Network and Subnet info from
                        # Network defined on an existing KuryrPort CR.
                        # This assumes only one Subnet exists per Network.
                        network = in_use_networks.get(port.network_id)
                        if network:
                            subnets[subnet_id] = {subnet_id: network}
                        else:
                            subnets[subnet_id] = {
                                subnet_id: utils.get_subnet(subnet_id)}
        return parent_ports, subports, subnets

    def _cleanup_leftover_ports(self):
        os_net = clients.get_network_client()
        existing_ports = os_net.ports(device_owner=kl_const.DEVICE_OWNER,
                                      status='DOWN')

        tags = config.CONF.neutron_defaults.resource_tags
        if tags:
            nets = os_net.networks(tags=tags)
            nets_ids = [n.id for n in nets]
            for port in existing_ports:
                net_id = port.network_id
                if net_id in nets_ids:
                    if port.binding_host_id:
                        if set(tags).difference(set(port.tags)):
                            # delete the port if it has binding details, it
                            # belongs to the deployment subnet and it does not
                            # have the right tags
                            try:
                                os_net.delete_port(port.id)
                            except os_exc.SDKException:
                                LOG.debug("Problem deleting leftover port %s. "
                                          "Skipping.", port.id)
                    else:
                        # delete port if they have no binding but belong to the
                        # deployment networks, regardless of their tagging
                        try:
                            os_net.delete_port(port.id)
                        except os_exc.SDKException:
                            LOG.debug("Problem deleting leftover port %s. "
                                      "Skipping.", port.id)
                            continue
        else:
            c_utils.delete_ports([p for p in existing_ports
                                  if not p.binding_host_id])

    def _cleanup_removed_nodes(self):
        """Remove ports associated to removed nodes."""
        previous_ports_to_remove = []
        while True:
            # NOTE(ltomasbo): Nodes are not expected to be removed
            # frequently, so there is no need to execute this frequently
            # either
            eventlet.sleep(NODE_PORTS_CLEAN_FREQUENCY)
            try:
                self._trigger_removed_nodes_ports_cleanup(
                    previous_ports_to_remove)
            except Exception:
                LOG.exception('Error while removing the ports associated to '
                              'deleted nodes. It will be retried in %s '
                              'seconds', NODE_PORTS_CLEAN_FREQUENCY)

    def _trigger_removed_nodes_ports_cleanup(self, previous_ports_to_remove):
        """Remove ports associated to removed nodes.

        There are two types of ports pool, one for neutron and one for nested.
        For the nested, the ports lost their device_owner after being detached,
        i.e., after the node they belong to got removed. This means we cannot
        find them unless they have been tagged.

        For the neutron ones, we rely on them having the kuryr device owner
        and not having binding information, thus ensuring they are not
        attached to any node. However, to avoid the case where those ports
        are being created at the same time of the cleanup process, we don't
        delete them unless we have seen them for 2 iterations.
        """
        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to perform nodes"
                      " cleanup.")
            return
        os_net = clients.get_network_client()
        tags = config.CONF.neutron_defaults.resource_tags
        if tags:
            subnetpool_id = config.CONF.namespace_subnet.pod_subnet_pool
            if subnetpool_id:
                subnets = os_net.subnets(tags=tags,
                                         subnetpool_id=subnetpool_id)
                subnets_ids = [s.id for s in subnets]
            else:
                subnets_ids = [config.CONF.neutron_defaults.pod_subnet]

            # NOTE(ltomasbo): Detached subports gets their device_owner unset
            detached_subports = os_net.ports(status='DOWN', tags=tags)
            for subport in detached_subports:
                # FIXME(ltomasbo): Looking for trunk:subport is only needed
                # due to a bug in neutron that does not reset the
                # device_owner after the port is detached from the trunk
                if subport.device_owner not in ['', 'trunk:subport']:
                    continue
                if subport.id not in previous_ports_to_remove:
                    # FIXME(ltomasbo): Until the above problem is there,
                    # we need to add protection for recently created ports
                    # that are still being attached
                    previous_ports_to_remove.append(subport.id)
                    continue
                # check if port belonged to kuryr and it was a subport
                # FIXME(ltomasbo): Assuming single stack
                if len(subport.fixed_ips) != 1:
                    # This should never happen as there is no option to create
                    # ports without IPs in Neutron, yet we hit it. So adding
                    # protection from it
                    continue
                if subport.fixed_ips[0].get('subnet_id') not in subnets_ids:
                    continue
                try:
                    del self._existing_vifs[subport.id]
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', subport.id)
                port_deleted = c_utils.delete_port(subport)
                if port_deleted:
                    previous_ports_to_remove.remove(subport.id)

            # normal ports, or subports not yet attached
            existing_ports = os_net.ports(
                device_owner=kl_const.DEVICE_OWNER,
                status='DOWN',
                tags=tags)
        else:
            # normal ports, or subports not yet attached
            existing_ports = os_net.ports(
                device_owner=kl_const.DEVICE_OWNER,
                status='DOWN')

        for port in existing_ports:
            # NOTE(ltomasbo): It may be that the port got just created and it
            # is still being attached and/or being tagged.
            if port.id not in previous_ports_to_remove:
                previous_ports_to_remove.append(port.id)
                continue

            if not port.binding_host_id:
                try:
                    del self._existing_vifs[port.id]
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', port.id)
                try:
                    os_net.delete_port(port.id)
                except os_exc.SDKException:
                    LOG.debug("Problem deleting leftover port %s. "
                              "Skipping.", port.id)
                else:
                    previous_ports_to_remove.remove(port.id)


class NeutronVIFPool(BaseVIFPool):
    """Manages VIFs for Bare Metal Kubernetes Pods."""

    def _get_host_addr(self, pod):
        return pod['spec']['nodeName']

    def _set_port_debug(self, port_id, pod):
        os_net = clients.get_network_client()
        os_net.update_port(port_id, name=c_utils.get_port_name(pod),
                           device_id=pod['metadata']['uid'])

    def _return_ports_to_pool(self):
        """Recycle ports to be reused by future pods.

        For each port in the recyclable_ports dict it reapplies
        security group if they have been changed and it changes the port
        name to available_port if the port_debug option is enabled.
        Then the port_id is included in the dict with the available_ports.

        If a maximum number of ports per pool is set, the port will be
        deleted if the maximum has been already reached.
        """
        while True:
            eventlet.sleep(oslo_cfg.CONF.vif_pool.ports_pool_update_frequency)
            try:
                self._trigger_return_to_pool()
            except Exception:
                LOG.exception(
                    'Error while returning ports to pool. '
                    'It will be retried in %s seconds',
                    oslo_cfg.CONF.vif_pool.ports_pool_update_frequency)

    @lockutils.synchronized('return_to_pool_baremetal')
    def _trigger_return_to_pool(self):
        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to return ports to "
                      "pools.")
            return
        os_net = clients.get_network_client()
        sg_current = {}
        if not config.CONF.kubernetes.port_debug:
            attrs = {'device_owner': kl_const.DEVICE_OWNER}
            tags = config.CONF.neutron_defaults.resource_tags
            if tags:
                attrs['tags'] = tags

            for port in os_net.ports(**attrs):
                if port.id in self._recyclable_ports:
                    sg_current[port.id] = tuple(sorted(
                        port.security_group_ids))

        for port_id, pool_key in list(self._recyclable_ports.items()):
            if (not oslo_cfg.CONF.vif_pool.ports_pool_max or
                self._get_pool_size(pool_key) <
                    oslo_cfg.CONF.vif_pool.ports_pool_max):
                port_name = (constants.KURYR_PORT_NAME
                             if config.CONF.kubernetes.port_debug
                             else '')
                if config.CONF.kubernetes.port_debug:
                    try:
                        os_net.update_port(port_id, name=port_name,
                                           device_id='')
                    except os_exc.SDKException:
                        LOG.warning("Error changing name for port %s to be "
                                    "reused, put back on the cleanable "
                                    "pool.", port_id)
                        continue
                sg = sg_current.get(port_id)
                self._available_ports_pools[pool_key].setdefault(
                        sg, []).append(port_id)
                # Move it to the end of ports to update the SG.
                self._available_ports_pools[pool_key].move_to_end(sg)
            else:
                try:
                    del self._existing_vifs[port_id]
                    os_net.delete_port(port_id)
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', port_id)
            try:
                del self._recyclable_ports[port_id]
            except KeyError:
                LOG.debug('Port already recycled: %s', port_id)

    def sync_pools(self):
        super(NeutronVIFPool, self).sync_pools()
        # NOTE(ltomasbo): Ensure previously created ports are recovered into
        # their respective pools
        self._cleanup_leftover_ports()
        self._recover_precreated_ports()
        self._recovered_pools = True

    def _recover_precreated_ports(self):
        os_net = clients.get_network_client()
        attrs = {'device_owner': kl_const.DEVICE_OWNER}
        tags = config.CONF.neutron_defaults.resource_tags
        if tags:
            attrs['tags'] = tags

        if config.CONF.kubernetes.port_debug:
            attrs['name'] = constants.KURYR_PORT_NAME
            available_ports = os_net.ports(**attrs)
        else:
            kuryr_ports = os_net.ports(**attrs)
            in_use_ports, _ = self._get_in_use_ports_info()
            available_ports = [port for port in kuryr_ports
                               if port.id not in in_use_ports]

        _, available_subports, _ = self._get_trunks_info()
        for port in available_ports:
            # NOTE(ltomasbo): ensure subports are not considered for
            # recovering in the case of multi pools
            if available_subports.get(port.id):
                continue
            if not port.binding_vif_type or not port.binding_host_id:
                # NOTE(ltomasbo): kuryr-controller is running without the
                # rights to get the needed information to recover the ports.
                # Thus, removing the port instead
                os_net = clients.get_network_client()
                os_net.delete_port(port.id)
                continue
            subnet_id = port.fixed_ips[0]['subnet_id']
            subnet = {
                subnet_id: utils.get_subnet(subnet_id)}
            vif = ovu.neutron_to_osvif_vif(port.binding_vif_type, port, subnet)
            net_obj = subnet[subnet_id]
            pool_key = self._get_pool_key(port.binding_host_id,
                                          port.project_id,
                                          net_obj.id, None)

            self._existing_vifs[port.id] = vif
            self._available_ports_pools[pool_key].setdefault(
                    tuple(sorted(port.security_group_ids)), []).append(port.id)

        LOG.info("PORTS POOL: pools updated with pre-created ports")
        self._create_healthcheck_file()

    def delete_network_pools(self, net_id):
        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to delete network "
                      "pools.")
            raise exceptions.ResourceNotReady(net_id)

        epool = eventlet.GreenPool(constants.LEFTOVER_RM_POOL_SIZE)

        # NOTE(ltomasbo): Note the pods should already be deleted, but their
        # associated ports may not have been recycled yet, therefore not being
        # on the available_ports_pools dict. The next call forces it to be on
        # that dict before cleaning it up
        self._trigger_return_to_pool()
        for pool_key, ports in list(self._available_ports_pools.items()):
            if self._get_pool_key_net(pool_key) != net_id:
                continue
            ports_id = []
            for sg_ports in ports.values():
                ports_id.extend(sg_ports)
            for port_id in ports_id:
                try:
                    del self._existing_vifs[port_id]
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', port_id)
                # NOTE(gryf): openstack client doesn't return information, if
                # the port deos not exists

            # Delete ports concurrently
            for result in epool.imap(c_utils.delete_neutron_port, ports_id):
                if result:
                    LOG.error('During Neutron port deletion an error occured: '
                              '%s', result)
                    raise result

            del self._available_ports_pools[pool_key]
            with self._lock:
                try:
                    del self._populate_pool_lock[pool_key]
                except KeyError:
                    pass


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

    def release_vif(self, pod, vif, project_id):
        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to remove pods.")
            raise exceptions.ResourceNotReady(pod)
        try:
            host_addr = self._get_host_addr(pod)
        except KeyError:
            name = pod['metadata']['name']
            LOG.warning("Pod %s does not have status.hostIP field set when "
                        "getting deleted. This is unusual. Trying to "
                        "determine the IP by calling Neutron.",
                        name)

            parent_id = utils.get_parent_port_id(vif)
            if not parent_id:
                LOG.warning("Port %s not found, ignoring its release request.",
                            vif.id)
                return

            host_addr = utils.get_parent_port_ip(parent_id)
            LOG.debug("Determined hostIP for pod %s is %s", name, host_addr)

        super(NestedVIFPool, self).release_vif(
            pod, vif, project_id, host_addr=host_addr)

    def _set_port_debug(self, port_id, pod):
        os_net = clients.get_network_client()
        os_net.update_port(port_id, name=c_utils.get_port_name(pod))

    def _return_ports_to_pool(self):
        """Recycle ports to be reused by future pods.

        For each port in the recyclable_ports dict it reapplies
        security group if they have been changed and it changes the port
        name to available_port if the port_debug option is enabled.
        Then the port_id is included in the dict with the available_ports.

        If a maximum number of ports per pool is set, the port will be
        deleted if the maximum has been already reached.
        """
        while True:
            eventlet.sleep(oslo_cfg.CONF.vif_pool.ports_pool_update_frequency)
            try:
                self._trigger_return_to_pool()
            except Exception:
                LOG.exception(
                    'Error while returning ports to pool. '
                    'It will be retried in %s seconds',
                    oslo_cfg.CONF.vif_pool.ports_pool_update_frequency)

    @lockutils.synchronized('return_to_pool_nested')
    def _trigger_return_to_pool(self):
        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to return ports to "
                      "pools.")
            return
        os_net = clients.get_network_client()
        sg_current = {}
        if not config.CONF.kubernetes.port_debug:
            attrs = {'device_owner': ['trunk:subport', kl_const.DEVICE_OWNER]}
            tags = config.CONF.neutron_defaults.resource_tags
            if tags:
                attrs['tags'] = tags
            kuryr_subports = os_net.ports(**attrs)
            for subport in kuryr_subports:
                if subport.id in self._recyclable_ports:
                    sg_current[subport.id] = tuple(sorted(
                        subport.security_group_ids))

        for port_id, pool_key in list(self._recyclable_ports.items()):
            if (not oslo_cfg.CONF.vif_pool.ports_pool_max or
                self._get_pool_size(pool_key) <
                    oslo_cfg.CONF.vif_pool.ports_pool_max):
                port_name = (constants.KURYR_PORT_NAME
                             if config.CONF.kubernetes.port_debug
                             else '')
                if config.CONF.kubernetes.port_debug:
                    try:
                        os_net.update_port(port_id, name=port_name)
                    except os_exc.SDKException:
                        LOG.warning("Error changing name for port %s to be "
                                    "reused, put back on the cleanable "
                                    "pool.", port_id)
                        continue
                sg = sg_current.get(port_id)
                self._available_ports_pools[pool_key].setdefault(
                    sg, []).append(port_id)
                # Move it to the end of ports to update the SG.
                self._available_ports_pools[pool_key].move_to_end(sg)
            else:
                trunk_id = self._get_trunk_id(pool_key)
                try:
                    self._drv_vif._remove_subport(trunk_id, port_id)
                    self._drv_vif._release_vlan_id(
                        self._existing_vifs[port_id].vlan_id)
                    del self._existing_vifs[port_id]
                    os_net.delete_port(port_id)
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', port_id)
                except (os_exc.SDKException, os_exc.HttpException):
                    LOG.warning('Error removing the subport %s', port_id)
                    continue
            try:
                del self._recyclable_ports[port_id]
            except KeyError:
                LOG.debug('Port already recycled: %s', port_id)

    def _get_trunk_id(self, pool_key):
        trunk_id = self._known_trunk_ids.get(pool_key, None)
        if not trunk_id:
            p_port = self._drv_vif._get_parent_port_by_host_ip(pool_key[0])
            trunk_id = self._drv_vif._get_trunk_id(p_port)
            self._known_trunk_ids[pool_key] = trunk_id
        return trunk_id

    def sync_pools(self):
        super(NestedVIFPool, self).sync_pools()
        # NOTE(ltomasbo): Ensure previously created ports are recovered into
        # their respective pools
        self._recover_precreated_ports()
        self._recovered_pools = True
        eventlet.spawn(self._cleanup_leftover_ports)

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
        os_net = clients.get_network_client()
        # Note(ltomasbo): ML2/OVS changes the device_owner to trunk:subport
        # when a port is attached to a trunk. However, that is not the case
        # for other ML2 drivers, such as ODL. So we also need to look for
        # compute:kuryr

        parent_ports, available_subports, subnets = self._get_trunks_info()

        if not available_subports:
            return

        # FIXME(ltomasbo): Workaround for ports already detached from trunks
        # whose status is ACTIVE
        trunks_subports = [subport_id['port_id']
                           for p_port in parent_ports.values()
                           for subport_id in p_port['subports']]
        port_ids_to_delete = [p_id for p_id in available_subports
                              if p_id not in trunks_subports]
        for port_id in port_ids_to_delete:
            LOG.debug("Deleting port with wrong status: %s", port_id)
            try:
                os_net.delete_port(port_id)
            except os_exc.SDKException:
                LOG.exception('Error removing the port %s', port_id)

        for trunk_id, parent_port in parent_ports.items():
            host_addr = parent_port.get('ip')
            if trunk_ips and host_addr not in trunk_ips:
                continue

            for subport in parent_port.get('subports'):
                kuryr_subport = available_subports.get(subport['port_id'])
                if not kuryr_subport:
                    continue

                subnet_id = kuryr_subport.fixed_ips[0]['subnet_id']
                subnet = subnets[subnet_id]
                net_obj = subnet[subnet_id]
                pool_key = self._get_pool_key(host_addr,
                                              kuryr_subport.project_id,
                                              net_obj.id, None)

                if action == 'recover':
                    vif = ovu.neutron_to_osvif_vif_nested_vlan(
                        kuryr_subport, subnet, subport['segmentation_id'])

                    self._existing_vifs[kuryr_subport.id] = vif
                    self._available_ports_pools[pool_key].setdefault(
                        tuple(sorted(kuryr_subport.security_group_ids)),
                        []).append(kuryr_subport.id)

                elif action == 'free':
                    try:
                        self._drv_vif._remove_subport(trunk_id,
                                                      kuryr_subport.id)
                        os_net.delete_port(kuryr_subport.id)
                        self._drv_vif._release_vlan_id(
                            subport['segmentation_id'])
                        del self._existing_vifs[kuryr_subport.id]
                        self._available_ports_pools[pool_key][
                            tuple(sorted(kuryr_subport.security_group_ids
                                         ))].remove(kuryr_subport.id)
                    except KeyError:
                        LOG.debug('Port %s is not in the ports list.',
                                  kuryr_subport.id)
                    except (os_exc.SDKException, os_exc.HttpException):
                        LOG.warning('Error removing the subport %s',
                                    kuryr_subport.id)
                    except ValueError:
                        LOG.debug('Port %s is not in the available ports '
                                  'pool.', kuryr_subport.id)

    @lockutils.synchronized('return_to_pool_nested')
    def populate_pool(self, trunk_ip, project_id, subnets, security_groups):
        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to populate pools.")
            raise exceptions.ResourceNotReady(trunk_ip)

        pool_key = self._get_pool_key(trunk_ip, project_id, None, subnets)
        lock = self._get_populate_pool_lock(pool_key)

        if lock.acquire(timeout=POPULATE_POOL_TIMEOUT):
            try:
                pools = self._available_ports_pools.get(pool_key)
                if not pools:
                    # NOTE(ltomasbo): If the amount of nodes is large the
                    # repopulation actions may take too long. Using half of the
                    # batch to prevent the problem
                    num_ports = int(max(oslo_cfg.CONF.vif_pool
                                        .ports_pool_batch/2,
                                        oslo_cfg.CONF.vif_pool.ports_pool_min))
                    self.force_populate_pool(trunk_ip, project_id, subnets,
                                             security_groups, num_ports)
            finally:
                lock.release()
        else:
            LOG.debug("Kuryr-controller timed out waiting for it turn to "
                      "populate pool, retrying.")
            raise exceptions.ResourceNotReady(trunk_ip)

    def force_populate_pool(self, trunk_ip, project_id, subnets,
                            security_groups, num_ports=None):
        """Create a given amount of subports at a given trunk port.

        This function creates a given amount of subports and attaches them to
        the specified trunk, adding them to the related subports pool
        regardless of the amount of subports already available in the pool.
        """
        if not num_ports:
            num_ports = oslo_cfg.CONF.vif_pool.ports_pool_batch
        vifs = self._drv_vif.request_vifs(
            pod=[],
            project_id=project_id,
            subnets=subnets,
            security_groups=security_groups,
            num_ports=num_ports,
            trunk_ip=trunk_ip,
            semaphore=self._create_ports_semaphore)

        pool_key = self._get_pool_key(trunk_ip, project_id, None, subnets)
        for vif in vifs:
            self._existing_vifs[vif.id] = vif
            self._available_ports_pools[pool_key].setdefault(
                tuple(sorted(security_groups)), []).append(vif.id)

    def free_pool(self, trunk_ips=None):
        """Removes subports from the pool and deletes neutron port resource.

        This function empties the pool of available subports and removes the
        neutron port resources of the specified trunk port (or all of them if
        no trunk is specified).
        """
        self._remove_precreated_ports(trunk_ips)

    def delete_network_pools(self, net_id):
        if not self._recovered_pools:
            LOG.debug("Kuryr-controller not yet ready to delete network "
                      "pools.")
            raise exceptions.ResourceNotReady(net_id)

        epool = eventlet.GreenPool(constants.LEFTOVER_RM_POOL_SIZE)
        ports_to_remove = []

        # NOTE(ltomasbo): Note the pods should already be deleted, but their
        # associated ports may not have been recycled yet, therefore not being
        # on the available_ports_pools dict. The next call forces it to be on
        # that dict before cleaning it up
        self._trigger_return_to_pool()
        for pool_key, ports in list(self._available_ports_pools.items()):
            if self._get_pool_key_net(pool_key) != net_id:
                continue
            trunk_id = self._get_trunk_id(pool_key)
            ports_id = [p_id for sg_ports in ports.values()
                        for p_id in sg_ports]
            try:
                self._drv_vif._remove_subports(trunk_id, ports_id)
            except os_exc.NotFoundException:
                # We don't know which subport was already removed, but we'll
                # attempt a manual detach on DELETE error, so just continue.
                pass
            except (os_exc.SDKException, os_exc.HttpException):
                LOG.exception('Error removing subports from trunk: %s',
                              trunk_id)
                raise exceptions.ResourceNotReady(net_id)

            for port_id in ports_id:
                try:
                    self._drv_vif._release_vlan_id(
                        self._existing_vifs[port_id].vlan_id)
                    del self._existing_vifs[port_id]
                except KeyError:
                    LOG.debug('Port %s is not in the ports list.', port_id)
                ports_to_remove.append(port_id)

            del self._available_ports_pools[pool_key]
            with self._lock:
                try:
                    del self._populate_pool_lock[pool_key]
                except KeyError:
                    pass

        # Parallelize Ports deletion. At this point the Ports
        # should have been detatched from Trunk and if not operation
        # will be retried
        for result in epool.imap(c_utils.delete_neutron_port, ports_to_remove):
            if result:
                LOG.error('During Neutron port deletion an error occured: %s',
                          result)
                raise exceptions.ResourceNotReady(net_id)


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
        vif_pool_mapping = self._get_vif_pool_mapping()

        if not vif_pool_mapping:
            pod_vif = oslo_cfg.CONF.kubernetes.pod_vif_driver
            drv_vif = base.PodVIFDriver.get_instance()
            drv_pool = base.VIFPoolDriver.get_instance()
            drv_pool.set_vif_driver(drv_vif)
            self._vif_drvs[pod_vif] = drv_pool
            return
        for pod_driver, pool_driver in vif_pool_mapping.items():
            if not utils.check_suitable_multi_pool_driver_opt(pool_driver,
                                                              pod_driver):
                LOG.error("The pool(%s) and pod(%s) driver selected are not "
                          "compatible.", pool_driver, pod_driver)
                raise exceptions.MultiPodDriverPoolConfigurationNotSupported()
            drv_vif = base.PodVIFDriver.get_instance(
                specific_driver=pod_driver)
            drv_pool = base.VIFPoolDriver.get_instance(
                specific_driver=pool_driver, scope='for:{}'.format(pod_driver))
            drv_pool.set_vif_driver(drv_vif)
            self._vif_drvs[pod_driver] = drv_pool

    def request_vif(self, pod, project_id, subnets, security_groups):
        pod_info = "%s/%s" % (pod['metadata']['namespace'],
                              pod['metadata']['name'])
        try:
            pod_vif_type = self._get_pod_vif_type(pod)
        except KeyError:
            # NOTE(maysams): No nodeName set. Event should be skipped
            LOG.warning("Pod %s has no .spec.nodeName set. This is unexpected "
                        "as it's supposed to be scheduled. Ignoring event.",
                        pod_info)
            return None
        return self._vif_drvs[pod_vif_type].request_vif(
            pod, project_id, subnets, security_groups)

    def release_vif(self, pod, vif, *argv):
        vif_drv_alias = self._get_vif_drv_alias(vif)
        self._vif_drvs[vif_drv_alias].release_vif(pod, vif, *argv)

    def activate_vif(self, vif, **kwargs):
        vif_drv_alias = self._get_vif_drv_alias(vif)
        self._vif_drvs[vif_drv_alias].activate_vif(vif, **kwargs)

    def update_vif_sgs(self, pod, sgs):
        pod_vif_type = self._get_pod_vif_type(pod)
        self._vif_drvs[pod_vif_type].update_vif_sgs(pod, sgs)

    def remove_sg_from_pools(self, sg_id, net_id):
        for vif_drv in self._vif_drvs.values():
            if str(vif_drv) == 'NoopVIFPool':
                continue
            vif_drv.remove_sg_from_pools(sg_id, net_id)

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

    def _get_vif_pool_mapping(self):
        vif_pool_mapping = oslo_cfg.CONF.vif_pool.vif_pool_mapping

        if not vif_pool_mapping:
            pools_vif_drivers = oslo_cfg.CONF.vif_pool.pools_vif_drivers

            if pools_vif_drivers:
                msg = ("Config option vif_pool.pools_vif_drivers is "
                       "deprecated in favour of vif_pool.vif_pool_mapping, "
                       "and will be removed in a future release")
                versionutils.report_deprecated_feature(LOG, msg)

            for pool_driver, pod_driver in pools_vif_drivers.items():
                vif_pool_mapping[pod_driver] = pool_driver

        return vif_pool_mapping

    def populate_pool(self, node_ip, project_id, subnets, sg_id):
        for vif_drv in self._vif_drvs.values():
            if str(vif_drv) == 'NestedVIFPool':
                vif_drv.populate_pool(node_ip, project_id, subnets, sg_id)
