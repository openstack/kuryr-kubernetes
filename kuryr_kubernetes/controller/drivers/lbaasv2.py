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

import requests

from neutronclient.common import exceptions as n_exc
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import timeutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants as const
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import lbaas as obj_lbaas

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

_ACTIVATION_TIMEOUT = CONF.neutron_defaults.lbaas_activation_timeout
_SUPPORTED_LISTENER_PROT = ('HTTP', 'HTTPS', 'TCP')


class LBaaSv2Driver(base.LBaaSDriver):
    """LBaaSv2Driver implements LBaaSDriver for Neutron LBaaSv2 API."""

    @property
    def cascading_capable(self):
        lbaas = clients.get_loadbalancer_client()
        return lbaas.cascading_capable

    def ensure_loadbalancer(self, endpoints, project_id, subnet_id, ip,
                            security_groups_ids, service_type):
        name = "%(namespace)s/%(name)s" % endpoints['metadata']
        request = obj_lbaas.LBaaSLoadBalancer(
            name=name, project_id=project_id, subnet_id=subnet_id, ip=ip,
            security_groups=security_groups_ids)
        response = self._ensure(request, self._create_loadbalancer,
                                self._find_loadbalancer)
        if not response:
            # NOTE(ivc): load balancer was present before 'create', but got
            # deleted externally between 'create' and 'find'
            raise k_exc.ResourceNotReady(request)

        try:
            self.ensure_security_groups(endpoints, response,
                                        security_groups_ids, service_type)
        except n_exc.NeutronClientException:
            # NOTE(dulek): `endpoints` arguments on release_loadbalancer()
            #              is ignored for some reason, so just pass None.
            self.release_loadbalancer(None, response)
            raise

        return response

    def release_loadbalancer(self, endpoints, loadbalancer):
        neutron = clients.get_neutron_client()
        lbaas = clients.get_loadbalancer_client()
        if lbaas.cascading_capable:
            self._release(
                loadbalancer,
                loadbalancer,
                lbaas.delete,
                lbaas.lbaas_loadbalancer_path % loadbalancer.id,
                params={'cascade': True})

        else:
            self._release(loadbalancer, loadbalancer,
                          lbaas.delete_loadbalancer, loadbalancer.id)

            sg_id = self._find_listeners_sg(loadbalancer)
            if sg_id:
                try:
                    neutron.delete_security_group(sg_id)
                except n_exc.NeutronClientException:
                    LOG.exception('Error when deleting loadbalancer security '
                                  'group. Leaving it orphaned.')

    def ensure_security_groups(self, endpoints, loadbalancer,
                               security_groups_ids, service_type):
        # We only handle SGs for legacy LBaaSv2, Octavia handles it dynamically
        # according to listener ports.
        if loadbalancer.provider == const.NEUTRON_LBAAS_HAPROXY_PROVIDER:
            neutron = clients.get_neutron_client()
            sg_id = None
            try:
                # NOTE(dulek): We're creating another security group to
                #              overcome LBaaS v2 limitations and handle SGs
                #              ourselves.
                if service_type == 'LoadBalancer':
                    sg_id = self._find_listeners_sg(loadbalancer)
                    if not sg_id:
                        sg = neutron.create_security_group({
                            'security_group': {
                                'name': loadbalancer.name,
                                'project_id': loadbalancer.project_id,
                            },
                        })
                        sg_id = sg['security_group']['id']
                    loadbalancer.security_groups.append(sg_id)

                neutron.update_port(
                    loadbalancer.port_id,
                    {'port': {
                        'security_groups': loadbalancer.security_groups}})
            except n_exc.NeutronClientException:
                LOG.exception('Failed to set SG for LBaaS v2 VIP port %s.',
                              loadbalancer.port_id)
                if sg_id:
                    neutron.delete_security_group(sg_id)
                raise

    def ensure_security_group_rules(self, endpoints, loadbalancer, listener):
        sg_id = self._find_listeners_sg(loadbalancer)
        if sg_id:
            try:
                neutron = clients.get_neutron_client()
                neutron.create_security_group_rule({
                    'security_group_rule': {
                        'direction': 'ingress',
                        'port_range_min': listener.port,
                        'port_range_max': listener.port,
                        'protocol': listener.protocol,
                        'security_group_id': sg_id,
                        'description': listener.name,
                    },
                })
            except n_exc.NeutronClientException as ex:
                if ex.status_code != requests.codes.conflict:
                    LOG.exception('Failed when creating security group rule '
                                  'for listener %s.', listener.name)

    def ensure_listener(self, endpoints, loadbalancer, protocol, port):
        if protocol not in _SUPPORTED_LISTENER_PROT:
            LOG.info("Protocol: %(prot)s: is not supported by LBaaSV2", {
                'prot': protocol})
            return None
        name = "%(namespace)s/%(name)s" % endpoints['metadata']
        name += ":%s:%s" % (protocol, port)
        listener = obj_lbaas.LBaaSListener(name=name,
                                           project_id=loadbalancer.project_id,
                                           loadbalancer_id=loadbalancer.id,
                                           protocol=protocol,
                                           port=port)
        result = self._ensure_provisioned(loadbalancer, listener,
                                          self._create_listener,
                                          self._find_listener)

        self.ensure_security_group_rules(endpoints, loadbalancer, result)

        return result

    def release_listener(self, endpoints, loadbalancer, listener):
        neutron = clients.get_neutron_client()
        lbaas = clients.get_loadbalancer_client()
        self._release(loadbalancer, listener,
                      lbaas.delete_listener,
                      listener.id)

        sg_id = self._find_listeners_sg(loadbalancer)
        if sg_id:
            rules = neutron.list_security_group_rules(
                security_group_id=sg_id, description=listener.name)
            rules = rules['security_group_rules']
            if len(rules):
                neutron.delete_security_group_rule(rules[0]['id'])
            else:
                LOG.warning('Cannot find SG rule for %s (%s) listener.',
                            listener.id, listener.name)

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
        lbaas = clients.get_loadbalancer_client()
        self._release(loadbalancer, pool,
                      lbaas.delete_lbaas_pool,
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
        lbaas = clients.get_loadbalancer_client()
        self._release(loadbalancer, member,
                      lbaas.delete_lbaas_member,
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
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.create_loadbalancer({'loadbalancer': {
            'name': loadbalancer.name,
            'project_id': loadbalancer.project_id,
            'vip_address': str(loadbalancer.ip),
            'vip_subnet_id': loadbalancer.subnet_id}})
        loadbalancer.id = response['loadbalancer']['id']
        loadbalancer.port_id = self._get_vip_port_id(loadbalancer)
        loadbalancer.provider = response['loadbalancer']['provider']
        return loadbalancer

    def _find_loadbalancer(self, loadbalancer):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.list_loadbalancers(
            name=loadbalancer.name,
            project_id=loadbalancer.project_id,
            vip_address=str(loadbalancer.ip),
            vip_subnet_id=loadbalancer.subnet_id)

        try:
            loadbalancer.id = response['loadbalancers'][0]['id']
            loadbalancer.port_id = self._get_vip_port_id(loadbalancer)
            loadbalancer.provider = response['loadbalancers'][0]['provider']
        except (KeyError, IndexError):
            return None

        return loadbalancer

    def _create_listener(self, listener):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.create_listener({'listener': {
            'name': listener.name,
            'project_id': listener.project_id,
            'loadbalancer_id': listener.loadbalancer_id,
            'protocol': listener.protocol,
            'protocol_port': listener.port}})
        listener.id = response['listener']['id']
        return listener

    def _find_listener(self, listener):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.list_listeners(
            name=listener.name,
            project_id=listener.project_id,
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
        lbaas = clients.get_loadbalancer_client()
        try:
            response = lbaas.create_lbaas_pool({'pool': {
                'name': pool.name,
                'project_id': pool.project_id,
                'listener_id': pool.listener_id,
                'loadbalancer_id': pool.loadbalancer_id,
                'protocol': pool.protocol,
                'lb_algorithm': lb_algorithm}})
            pool.id = response['pool']['id']
            return pool
        except n_exc.StateInvalidClient:
            with excutils.save_and_reraise_exception():
                self._cleanup_bogus_pool(lbaas, pool, lb_algorithm)

    def _cleanup_bogus_pool(self, lbaas, pool, lb_algorithm):
        # REVISIT(ivc): LBaaSv2 creates pool object despite raising an
        # exception. The created pool is not bound to listener, but
        # it is bound to loadbalancer and will cause an error on
        # 'release_loadbalancer'.
        pools = lbaas.list_lbaas_pools(
            name=pool.name, project_id=pool.project_id,
            loadbalancer_id=pool.loadbalancer_id,
            protocol=pool.protocol, lb_algorithm=lb_algorithm)
        bogus_pool_ids = [p['id'] for p in pools.get('pools')
                          if not p['listeners']]
        for pool_id in bogus_pool_ids:
            try:
                LOG.debug("Removing bogus pool %(id)s %(pool)s", {
                    'id': pool_id, 'pool': pool})
                lbaas.delete_lbaas_pool(pool_id)
            except (n_exc.NotFound, n_exc.StateInvalidClient):
                pass

    def _find_pool(self, pool):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.list_lbaas_pools(
            name=pool.name,
            project_id=pool.project_id,
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
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.create_lbaas_member(member.pool_id, {'member': {
            'name': member.name,
            'project_id': member.project_id,
            'subnet_id': member.subnet_id,
            'address': str(member.ip),
            'protocol_port': member.port}})
        member.id = response['member']['id']
        return member

    def _find_member(self, member):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.list_lbaas_members(
            member.pool_id,
            name=member.name,
            project_id=member.project_id,
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
        lbaas = clients.get_loadbalancer_client()

        for remaining in self._provisioning_timer(timeout):
            response = lbaas.show_loadbalancer(loadbalancer.id)
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

    def _find_listeners_sg(self, loadbalancer):
        neutron = clients.get_neutron_client()
        try:
            sgs = neutron.list_security_groups(
                name=loadbalancer.name, project_id=loadbalancer.project_id)
            for sg in sgs['security_groups']:
                sg_id = sg['id']
                if sg_id in loadbalancer.security_groups:
                    return sg_id
        except n_exc.NeutronClientException:
            LOG.exception('Cannot list security groups for loadbalancer %s.',
                          loadbalancer.name)

        return None
