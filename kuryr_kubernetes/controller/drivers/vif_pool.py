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
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import default_subnet
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import os_vif_util as ovu

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
]

oslo_cfg.CONF.register_opts(vif_pool_driver_opts, "vif_pool")


class NoopVIFPool(base.VIFPoolDriver):
    """No pool VIFs for Kubernetes Pods"""

    def set_vif_driver(self, driver):
        self._drv_vif = driver

    def request_vif(self, pod, project_id, subnets, security_groups):
        return self._drv_vif.request_vif(pod, project_id, subnets,
                                         security_groups)

    def release_vif(self, pod, vif, *argv):
        self._drv_vif.release_vif(pod, vif)

    def activate_vif(self, pod, vif):
        self._drv_vif.activate_vif(pod, vif)


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
    _available_ports_pools = collections.defaultdict(collections.deque)
    _existing_vifs = collections.defaultdict(collections.defaultdict)
    _recyclable_ports = collections.defaultdict(collections.defaultdict)
    _last_update = collections.defaultdict(collections.defaultdict)

    def __init__(self):
        # Note(ltomasbo) Execute the port recycling periodic actions in a
        # background thread
        eventlet.spawn(self._return_ports_to_pool)
        # Note(ltomasbo) Delete or recover previously pre-created ports
        eventlet.spawn(self._recover_precreated_ports)

    def set_vif_driver(self, driver):
        self._drv_vif = driver

    def activate_vif(self, pod, vif):
        self._drv_vif.activate_vif(pod, vif)

    def _get_pool_size(self, pool_key=None):
        return len(self._available_ports_pools.get(pool_key, []))

    def _get_host_addr(self, pod):
        return pod['status']['hostIP']

    def request_vif(self, pod, project_id, subnets, security_groups):
        try:
            host_addr = self._get_host_addr(pod)
        except KeyError:
            LOG.warning("Pod has not been scheduled yet.")
            raise
        pool_key = (host_addr, project_id, tuple(sorted(security_groups)))

        try:
            return self._get_port_from_pool(pool_key, pod, subnets)
        except exceptions.ResourceNotReady as ex:
            LOG.warning("Ports pool does not have available ports!")
            eventlet.spawn(self._populate_pool, pool_key, pod, subnets)
            raise ex

    def _populate_pool(self, pool_key, pod, subnets):
        # REVISIT(ltomasbo): Drop the subnets parameter and get the information
        # from the pool_key, which will be required when multi-network is
        # supported
        now = time.time()
        if (now - oslo_cfg.CONF.vif_pool.ports_pool_update_frequency <
                self._last_update.get(pool_key, 0)):
            LOG.info("Not enough time since the last pool update")
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
        pool_key = (host_addr, project_id, tuple(sorted(security_groups)))

        if not self._existing_vifs.get(vif.id):
            self._existing_vifs[vif.id] = vif
        self._recyclable_ports[vif.id] = pool_key

    def _get_ports_by_attrs(self, **attrs):
        neutron = clients.get_neutron_client()
        ports = neutron.list_ports(**attrs)
        return ports['ports']

    def _get_in_use_ports(self):
        kubernetes = clients.get_kubernetes_client()
        in_use_ports = []
        running_pods = kubernetes.get(constants.K8S_API_BASE + '/pods')
        for pod in running_pods['items']:
            annotations = jsonutils.loads(pod['metadata']['annotations'][
                constants.K8S_ANNOTATION_VIF])
            in_use_ports.append(annotations['versioned_object.data']['id'])
        return in_use_ports


class NeutronVIFPool(BaseVIFPool):
    """Manages VIFs for Bare Metal Kubernetes Pods."""

    def _get_host_addr(self, pod):
        return pod['spec']['nodeName']

    def _get_port_from_pool(self, pool_key, pod, subnets):
        try:
            port_id = self._available_ports_pools[pool_key].pop()
        except IndexError:
            raise exceptions.ResourceNotReady(pod)
        if config.CONF.kubernetes.port_debug:
            neutron = clients.get_neutron_client()
            neutron.update_port(
                port_id,
                {
                    "port": {
                        'name': pod['metadata']['name'],
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
        neutron = clients.get_neutron_client()
        while True:
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
                del self._recyclable_ports[port_id]
            eventlet.sleep(oslo_cfg.CONF.vif_pool.ports_pool_update_frequency)

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
            pool_key = (port['binding:host_id'], port['project_id'],
                        tuple(port['security_groups']))
            subnet_id = port['fixed_ips'][0]['subnet_id']
            subnet = {
                subnet_id: default_subnet._get_subnet(subnet_id)}
            vif_plugin = self._drv_vif._get_vif_plugin(port)
            vif = ovu.neutron_to_osvif_vif(vif_plugin, port, subnet)

            self._existing_vifs[port['id']] = vif
            self._available_ports_pools.setdefault(
                pool_key, []).append(port['id'])

        LOG.info("PORTS POOL: pools updated with pre-created ports")


class NestedVIFPool(BaseVIFPool):
    """Manages VIFs for nested Kubernetes Pods.

    In order to handle the pools of ports for nested Pods, an extra dict is
    used:
    _known_trunk_ids is a dictionary that keeps the trunk port ids associated
    to each pool_key to skip calls to neutron to get the trunk information.
    """
    _known_trunk_ids = collections.defaultdict(str)

    def _get_port_from_pool(self, pool_key, pod, subnets):
        try:
            port_id = self._available_ports_pools[pool_key].pop()
        except IndexError:
            raise exceptions.ResourceNotReady(pod)
        if config.CONF.kubernetes.port_debug:
            neutron = clients.get_neutron_client()
            neutron.update_port(
                port_id,
                {
                    "port": {
                        'name': pod['metadata']['name'],
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
        neutron = clients.get_neutron_client()
        while True:
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
                    trunk_id = self._known_trunk_ids.get(pool_key, None)
                    if not trunk_id:
                        p_port = self._drv_vif._get_parent_port_by_host_ip(
                            neutron, pool_key[0])
                        trunk_id = self._drv_vif._get_trunk_id(p_port)
                        self._known_trunk_ids[pool_key] = trunk_id
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
                del self._recyclable_ports[port_id]
            eventlet.sleep(oslo_cfg.CONF.vif_pool.ports_pool_update_frequency)

    def _get_parent_port_ip(self, port_id):
        neutron = clients.get_neutron_client()
        parent_port = neutron.show_port(port_id).get('port')
        return parent_port['fixed_ips'][0]['ip_address']

    def _recover_precreated_ports(self):
        self._precreated_ports(action='recover')
        LOG.info("PORTS POOL: pools updated with pre-created ports")

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
        if config.CONF.kubernetes.port_debug:
            available_ports = self._get_ports_by_attrs(
                name=constants.KURYR_PORT_NAME, device_owner=[
                    'trunk:subport', kl_const.DEVICE_OWNER])
        else:
            kuryr_subports = self._get_ports_by_attrs(
                device_owner=['trunk:subport', kl_const.DEVICE_OWNER])
            in_use_ports = self._get_in_use_ports()
            available_ports = [subport for subport in kuryr_subports
                               if subport['id'] not in in_use_ports]

        if not available_ports:
            return

        trunk_ports = neutron.list_trunks().get('trunks')
        for trunk in trunk_ports:
            try:
                host_addr = self._get_parent_port_ip(trunk['port_id'])
            except n_exc.PortNotFoundClient:
                LOG.debug('Unable to find parent port for trunk port %s.',
                          trunk['port_id'])
                continue

            if trunk_ips and host_addr not in trunk_ips:
                continue

            for subport in trunk.get('sub_ports'):
                kuryr_subport = None
                for port in available_ports:
                    if port['id'] == subport['port_id']:
                        kuryr_subport = port
                        break

                if kuryr_subport:
                    pool_key = (host_addr, kuryr_subport['project_id'],
                                tuple(kuryr_subport['security_groups']))

                    if action == 'recover':
                        subnet_id = kuryr_subport['fixed_ips'][0]['subnet_id']
                        subnet = {
                            subnet_id: default_subnet._get_subnet(subnet_id)}
                        vif = ovu.neutron_to_osvif_vif_nested_vlan(
                            kuryr_subport, subnet, subport['segmentation_id'])

                        self._existing_vifs[subport['port_id']] = vif
                        self._available_ports_pools.setdefault(
                            pool_key, []).append(subport['port_id'])
                    elif action == 'free':
                        try:
                            self._drv_vif._remove_subport(neutron, trunk['id'],
                                                          subport['port_id'])
                            neutron.delete_port(subport['port_id'])
                            self._drv_vif._release_vlan_id(
                                subport['segmentation_id'])
                            del self._existing_vifs[subport['port_id']]
                            self._available_ports_pools[pool_key].remove(
                                subport['port_id'])
                        except n_exc.PortNotFoundClient:
                            LOG.debug('Unable to release port %s as it no '
                                      'longer exists.', subport['port_id'])
                        except KeyError:
                            LOG.debug('Port %s is not in the ports list.',
                                      subport['port_id'])
                        except n_exc.NeutronClientException:
                            LOG.warning('Error removing the subport %s',
                                        subport['port_id'])
                        except ValueError:
                            LOG.debug('Port %s is not in the available ports '
                                      'pool.', subport['port_id'])

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

        pool_key = (trunk_ip, project_id, tuple(sorted(security_groups)))
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
