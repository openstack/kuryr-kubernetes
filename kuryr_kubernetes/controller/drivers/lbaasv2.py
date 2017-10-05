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

import random
import time

from neutronclient.common import exceptions as n_exc
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import timeutils

from kuryr_kubernetes import clients
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import lbaas as obj_lbaas

LOG = logging.getLogger(__name__)
_ACTIVATION_TIMEOUT = 300


class LBaaSv2Driver(base.LBaaSDriver):
    """LBaaSv2Driver implements LBaaSDriver for Neutron LBaaSv2 API."""

    def ensure_loadbalancer(self, endpoints, project_id, subnet_id, ip,
                            security_groups_ids):
        name = "%(namespace)s/%(name)s" % endpoints['metadata']
        request = obj_lbaas.LBaaSLoadBalancer(name=name,
                                              project_id=project_id,
                                              subnet_id=subnet_id,
                                              ip=ip)
        response = self._ensure(request,
                                self._create_loadbalancer,
                                self._find_loadbalancer)
        if not response:
            # NOTE(ivc): load balancer was present before 'create', but got
            # deleted externally between 'create' and 'find'
            raise k_exc.ResourceNotReady(request)

        # TODO(ivc): handle security groups

        return response

    def release_loadbalancer(self, endpoints, loadbalancer):
        neutron = clients.get_neutron_client()
        self._release(loadbalancer, loadbalancer,
                      neutron.delete_loadbalancer, loadbalancer.id)

    def ensure_listener(self, endpoints, loadbalancer, protocol, port):
        name = "%(namespace)s/%(name)s" % endpoints['metadata']
        name += ":%s:%s" % (protocol, port)
        listener = obj_lbaas.LBaaSListener(name=name,
                                           project_id=loadbalancer.project_id,
                                           loadbalancer_id=loadbalancer.id,
                                           protocol=protocol,
                                           port=port)
        return self._ensure_provisioned(loadbalancer, listener,
                                        self._create_listener,
                                        self._find_listener)

    def release_listener(self, endpoints, loadbalancer, listener):
        neutron = clients.get_neutron_client()
        self._release(loadbalancer, listener,
                      neutron.delete_listener,
                      listener.id)

    def ensure_pool(self, endpoints, loadbalancer, listener):
        pool = obj_lbaas.LBaaSPool(name=listener.name,
                                   project_id=loadbalancer.project_id,
                                   loadbalancer_id=loadbalancer.id,
                                   listener_id=listener.id,
                                   protocol=listener.protocol)
        return self._ensure_provisioned(loadbalancer, pool,
                                        self._create_pool,
                                        self._find_pool)

    def release_pool(self, endpoints, loadbalancer, pool):
        neutron = clients.get_neutron_client()
        self._release(loadbalancer, pool,
                      neutron.delete_lbaas_pool,
                      pool.id)

    def ensure_member(self, endpoints, loadbalancer, pool,
                      subnet_id, ip, port, target_ref):
        name = "%(namespace)s/%(name)s" % target_ref
        name += ":%s" % port
        member = obj_lbaas.LBaaSMember(name=name,
                                       project_id=pool.project_id,
                                       pool_id=pool.id,
                                       subnet_id=subnet_id,
                                       ip=ip,
                                       port=port)
        return self._ensure_provisioned(loadbalancer, member,
                                        self._create_member,
                                        self._find_member)

    def release_member(self, endpoints, loadbalancer, member):
        neutron = clients.get_neutron_client()
        self._release(loadbalancer, member,
                      neutron.delete_lbaas_member,
                      member.id, member.pool_id)

    def _get_vip_port_id(self, loadbalancer):
        neutron = clients.get_neutron_client()
        try:
            fixed_ips = ['subnet_id=%s' % str(loadbalancer.subnet_id),
                         'ip_address=%s' % str(loadbalancer.ip)]
            ports = neutron.list_ports(fixed_ips=fixed_ips)
        except n_exc.NeutronClientException as ex:
            LOG.error("Port with fixed ips %s not found!", fixed_ips)
            raise ex

        if ports['ports']:
            return ports['ports'][0].get("id")

        return None

    def _create_loadbalancer(self, loadbalancer):
        neutron = clients.get_neutron_client()
        response = neutron.create_loadbalancer({'loadbalancer': {
            'name': loadbalancer.name,
            'project_id': loadbalancer.project_id,
            'tenant_id': loadbalancer.project_id,
            'vip_address': str(loadbalancer.ip),
            'vip_subnet_id': loadbalancer.subnet_id}})
        loadbalancer.id = response['loadbalancer']['id']
        loadbalancer.port_id = self._get_vip_port_id(loadbalancer)
        return loadbalancer

    def _find_loadbalancer(self, loadbalancer):
        neutron = clients.get_neutron_client()
        response = neutron.list_loadbalancers(
            name=loadbalancer.name,
            project_id=loadbalancer.project_id,
            tenant_id=loadbalancer.project_id,
            vip_address=str(loadbalancer.ip),
            vip_subnet_id=loadbalancer.subnet_id)

        try:
            loadbalancer.id = response['loadbalancers'][0]['id']
            loadbalancer.port_id = self._get_vip_port_id(loadbalancer)
        except (KeyError, IndexError):
            return None

        return loadbalancer

    def _create_listener(self, listener):
        neutron = clients.get_neutron_client()
        response = neutron.create_listener({'listener': {
            'name': listener.name,
            'project_id': listener.project_id,
            'tenant_id': listener.project_id,
            'loadbalancer_id': listener.loadbalancer_id,
            'protocol': listener.protocol,
            'protocol_port': listener.port}})
        listener.id = response['listener']['id']
        return listener

    def _find_listener(self, listener):
        neutron = clients.get_neutron_client()
        response = neutron.list_listeners(
            name=listener.name,
            project_id=listener.project_id,
            tenant_id=listener.project_id,
            loadbalancer_id=listener.loadbalancer_id,
            protocol=listener.protocol,
            protocol_port=listener.port)

        try:
            listener.id = response['listeners'][0]['id']
        except (KeyError, IndexError):
            return None

        return listener

    def _create_pool(self, pool):
        # TODO(ivc): make lb_algorithm configurable
        lb_algorithm = 'ROUND_ROBIN'
        neutron = clients.get_neutron_client()
        try:
            response = neutron.create_lbaas_pool({'pool': {
                'name': pool.name,
                'project_id': pool.project_id,
                'tenant_id': pool.project_id,
                'listener_id': pool.listener_id,
                'loadbalancer_id': pool.loadbalancer_id,
                'protocol': pool.protocol,
                'lb_algorithm': lb_algorithm}})
            pool.id = response['pool']['id']
            return pool
        except n_exc.StateInvalidClient:
            with excutils.save_and_reraise_exception():
                self._cleanup_bogus_pool(neutron, pool, lb_algorithm)

    def _cleanup_bogus_pool(self, neutron, pool, lb_algorithm):
        # REVISIT(ivc): LBaaSv2 creates pool object despite raising an
        # exception. The created pool is not bound to listener, but
        # it is bound to loadbalancer and will cause an error on
        # 'release_loadbalancer'.
        pools = neutron.list_lbaas_pools(
            name=pool.name, project_id=pool.project_id,
            loadbalancer_id=pool.loadbalancer_id,
            protocol=pool.protocol, lb_algorithm=lb_algorithm)
        bogus_pool_ids = [p['id'] for p in pools.get('pools')
                          if not p['listeners']]
        for pool_id in bogus_pool_ids:
            try:
                LOG.debug("Removing bogus pool %(id)s %(pool)s", {
                    'id': pool_id, 'pool': pool})
                neutron.delete_lbaas_pool(pool_id)
            except (n_exc.NotFound, n_exc.StateInvalidClient):
                pass

    def _find_pool(self, pool):
        neutron = clients.get_neutron_client()
        response = neutron.list_lbaas_pools(
            name=pool.name,
            project_id=pool.project_id,
            tenant_id=pool.project_id,
            loadbalancer_id=pool.loadbalancer_id,
            protocol=pool.protocol)

        try:
            pools = [p for p in response['pools']
                     if pool.listener_id in {l['id'] for l in p['listeners']}]
            pool.id = pools[0]['id']
        except (KeyError, IndexError):
            return None

        return pool

    def _create_member(self, member):
        neutron = clients.get_neutron_client()
        response = neutron.create_lbaas_member(member.pool_id, {'member': {
            'name': member.name,
            'project_id': member.project_id,
            'tenant_id': member.project_id,
            'subnet_id': member.subnet_id,
            'address': str(member.ip),
            'protocol_port': member.port}})
        member.id = response['member']['id']
        return member

    def _find_member(self, member):
        neutron = clients.get_neutron_client()
        response = neutron.list_lbaas_members(
            member.pool_id,
            name=member.name,
            project_id=member.project_id,
            tenant_id=member.project_id,
            subnet_id=member.subnet_id,
            address=member.ip,
            protocol_port=member.port)

        try:
            member.id = response['members'][0]['id']
        except (KeyError, IndexError):
            return None

        return member

    def _ensure(self, obj, create, find):
        try:
            result = create(obj)
            LOG.debug("Created %(obj)s", {'obj': result})
        except n_exc.Conflict:
            result = find(obj)
            if result:
                LOG.debug("Found %(obj)s", {'obj': result})
        return result

    def _ensure_provisioned(self, loadbalancer, obj, create, find):
        for remaining in self._provisioning_timer(_ACTIVATION_TIMEOUT):
            self._wait_for_provisioning(loadbalancer, remaining)
            try:
                result = self._ensure(obj, create, find)
                if result:
                    return result
            except n_exc.StateInvalidClient:
                continue

        raise k_exc.ResourceNotReady(obj)

    def _release(self, loadbalancer, obj, delete, *args, **kwargs):
        for remaining in self._provisioning_timer(_ACTIVATION_TIMEOUT):
            try:
                try:
                    delete(*args, **kwargs)
                    return
                except (n_exc.Conflict, n_exc.StateInvalidClient):
                    self._wait_for_provisioning(loadbalancer, remaining)
            except n_exc.NotFound:
                return

        raise k_exc.ResourceNotReady(obj)

    def _wait_for_provisioning(self, loadbalancer, timeout):
        neutron = clients.get_neutron_client()

        for remaining in self._provisioning_timer(timeout):
            response = neutron.show_loadbalancer(loadbalancer.id)
            status = response['loadbalancer']['provisioning_status']
            if status == 'ACTIVE':
                LOG.debug("Provisioning complete for %(lb)s", {
                    'lb': loadbalancer})
                return
            else:
                LOG.debug("Provisioning status %(status)s for %(lb)s, "
                          "%(rem).3gs remaining until timeout",
                          {'status': status, 'lb': loadbalancer,
                           'rem': remaining})

        raise k_exc.ResourceNotReady(loadbalancer)

    def _provisioning_timer(self, timeout):
        # REVISIT(ivc): consider integrating with Retry
        interval = 3
        max_interval = 15
        with timeutils.StopWatch(duration=timeout) as timer:
            while not timer.expired():
                yield timer.leftover()
                interval = interval * 2 * random.gauss(0.8, 0.05)
                interval = min(interval, max_interval)
                interval = min(interval, timer.leftover())
                if interval:
                    time.sleep(interval)
