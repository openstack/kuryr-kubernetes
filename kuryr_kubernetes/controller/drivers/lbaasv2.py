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
from six.moves import http_client as httplib
import time

import requests

from neutronclient.common import exceptions as n_exc
from openstack import exceptions as o_exc
from openstack.load_balancer.v2 import l7_policy as o_l7p
from openstack.load_balancer.v2 import l7_rule as o_l7r
from openstack.load_balancer.v2 import listener as o_lis
from openstack.load_balancer.v2 import load_balancer as o_lb
from openstack.load_balancer.v2 import member as o_mem
from openstack.load_balancer.v2 import pool as o_pool
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import versionutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import utils as c_utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes import utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

_ACTIVATION_TIMEOUT = CONF.neutron_defaults.lbaas_activation_timeout
_L7_POLICY_ACT_REDIRECT_TO_POOL = 'REDIRECT_TO_POOL'
# NOTE(yboaron):Prior to sending create request to Octavia, LBaaS driver
# verifies that LB is in a stable state by polling LB's provisioning_status
# using backoff timer.
# A similar method is used also for the delete flow.
# Unlike LB creation, rest of octavia operations are completed usually after
# few seconds. Next constants define the intervals values for 'fast' and
# 'slow' (will be used for LB creation)  polling.
_LB_STS_POLL_FAST_INTERVAL = 1
_LB_STS_POLL_SLOW_INTERVAL = 3
_OCTAVIA_TAGGING_VERSION = 2, 5


class LBaaSv2Driver(base.LBaaSDriver):
    """LBaaSv2Driver implements LBaaSDriver for Neutron LBaaSv2 API."""

    def __init__(self):
        super(LBaaSv2Driver, self).__init__()

        self._octavia_tags = False
        # Check if Octavia API supports tagging.
        # TODO(dulek): *Maybe* this can be replaced with
        #         lbaas.get_api_major_version(version=_OCTAVIA_TAGGING_VERSION)
        #         if bug https://storyboard.openstack.org/#!/story/2007040 gets
        #         fixed one day.
        v = self.get_octavia_version()
        if v >= _OCTAVIA_TAGGING_VERSION:
            LOG.info('Octavia supports resource tags.')
            self._octavia_tags = True
        else:
            v_str = '%d.%d' % v
            LOG.warning('[neutron_defaults]resource_tags is set, but Octavia '
                        'API %s does not support resource tagging. Kuryr '
                        'will put requested tags in the description field of '
                        'Octavia resources.', v_str)

    def get_octavia_version(self):
        lbaas = clients.get_loadbalancer_client()
        region_name = getattr(CONF.neutron, 'region_name', None)

        regions = lbaas.get_all_version_data()
        # If region was specified take it, otherwise just take first as default
        endpoints = regions.get(region_name, list(regions.values())[0])
        # Take the first endpoint
        services = list(endpoints.values())[0]
        # Try load-balancer service, if not take the first
        versions = services.get('load-balancer', list(services.values())[0])
        # Lookup the latest version. For safety, we won't look for
        # version['status'] == 'CURRENT' and assume it's the maximum. Also we
        # won't assume this dict is sorted.
        max_ver = 0, 0
        for version in versions:
            v_tuple = versionutils.convert_version_to_tuple(version['version'])
            if v_tuple > max_ver:
                max_ver = v_tuple

        LOG.debug("Detected Octavia version %d.%d", *max_ver)
        return max_ver

    def get_service_loadbalancer_name(self, namespace, svc_name):
        return "%s/%s" % (namespace, svc_name)

    def get_loadbalancer_pool_name(self, loadbalancer, namespace, svc_name):
        return "%s/%s/%s" % (loadbalancer.name, namespace, svc_name)

    def _add_tags(self, resource, req):
        if CONF.neutron_defaults.resource_tags:
            if self._octavia_tags:
                req['tags'] = CONF.neutron_defaults.resource_tags
            else:
                if resource in ('loadbalancer', 'listener', 'pool',
                                'l7policy'):
                    req['description'] = ','.join(
                        CONF.neutron_defaults.resource_tags)

    def ensure_loadbalancer(self, name, project_id, subnet_id, ip,
                            security_groups_ids=None, service_type=None,
                            provider=None):
        request = obj_lbaas.LBaaSLoadBalancer(
            name=name, project_id=project_id, subnet_id=subnet_id, ip=ip,
            security_groups=security_groups_ids, provider=provider)
        response = self._ensure(request, self._create_loadbalancer,
                                self._find_loadbalancer)
        if not response:
            # NOTE(ivc): load balancer was present before 'create', but got
            # deleted externally between 'create' and 'find'
            # NOTE(ltomasbo): or it is in ERROR status, so we deleted and
            # trigger the retry
            raise k_exc.ResourceNotReady(request)

        return response

    def release_loadbalancer(self, loadbalancer):
        neutron = clients.get_neutron_client()
        lbaas = clients.get_loadbalancer_client()
        self._release(
            loadbalancer,
            loadbalancer,
            lbaas.delete_load_balancer,
            loadbalancer.id,
            cascade=True)

        sg_id = self._find_listeners_sg(loadbalancer)
        if sg_id:
            # Note: reusing activation timeout as deletion timeout
            self._wait_for_deletion(loadbalancer, _ACTIVATION_TIMEOUT)
            try:
                neutron.delete_security_group(sg_id)
            except n_exc.NotFound:
                LOG.debug('Security group %s already deleted', sg_id)
            except n_exc.NeutronClientException:
                LOG.exception('Error when deleting loadbalancer security '
                              'group. Leaving it orphaned.')

    def _create_lb_security_group_rule(self, loadbalancer, listener):
        neutron = clients.get_neutron_client()
        sg_id = self._find_listeners_sg(loadbalancer)
        # if an SG for the loadbalancer has not being created, create one
        if not sg_id:
            sg = neutron.create_security_group({
                'security_group': {
                    'name': loadbalancer.name,
                    'project_id': loadbalancer.project_id,
                    },
                })
            sg_id = sg['security_group']['id']
            c_utils.tag_neutron_resources('security-groups', [sg_id])
            loadbalancer.security_groups.append(sg_id)
            vip_port = self._get_vip_port(loadbalancer)
            neutron.update_port(
                vip_port.get('id'),
                {'port': {
                    'security_groups': [sg_id]}})

        try:
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

    def _apply_members_security_groups(self, loadbalancer, port, target_port,
                                       protocol, sg_rule_name, new_sgs=None):
        LOG.debug("Applying members security groups.")
        neutron = clients.get_neutron_client()
        lb_sg = None
        if CONF.octavia_defaults.sg_mode == 'create':
            if new_sgs:
                lb_name = sg_rule_name.split(":")[0]
                lb_sg = self._find_listeners_sg(loadbalancer, lb_name=lb_name)
            else:
                lb_sg = self._find_listeners_sg(loadbalancer)
        else:
            vip_port = self._get_vip_port(loadbalancer)
            if vip_port:
                lb_sg = vip_port.get('security_groups')[0]

        # NOTE (maysams) It might happen that the update of LBaaS SG
        # has been triggered and the LBaaS SG was not created yet.
        # This update is skiped, until the LBaaS members are created.
        if not lb_sg:
            return

        lbaas_sg_rules = neutron.list_security_group_rules(
            security_group_id=lb_sg)
        all_pod_rules = []
        add_default_rules = False

        if new_sgs:
            sgs = new_sgs
        else:
            sgs = loadbalancer.security_groups

        # Check if Network Policy allows listener on the pods
        for sg in sgs:
            if sg != lb_sg:
                if sg in config.CONF.neutron_defaults.pod_security_groups:
                    # If default sg is set, this means there is no NP
                    # associated to the service, thus falling back to the
                    # default listener rules
                    add_default_rules = True
                    break
                rules = neutron.list_security_group_rules(
                    security_group_id=sg)
                for rule in rules['security_group_rules']:
                    # copying ingress rules with same protocol onto the
                    # loadbalancer sg rules
                    # NOTE(ltomasbo): NP sg can only have rules with
                    # or without remote_ip_prefix. Rules with remote_group_id
                    # are not possible, therefore only applying the ones
                    # with or without remote_ip_prefix.
                    if (rule['protocol'] == protocol.lower() and
                            rule['direction'] == 'ingress'):
                        # If listener port not in allowed range, skip
                        min_port = rule.get('port_range_min')
                        max_port = rule.get('port_range_max')
                        if (min_port and target_port not in range(min_port,
                                                                  max_port+1)):
                            continue
                        all_pod_rules.append(rule)
                        try:
                            LOG.debug("Creating LBaaS sg rule for sg: %r",
                                      lb_sg)
                            neutron.create_security_group_rule({
                                'security_group_rule': {
                                    'direction': 'ingress',
                                    'port_range_min': port,
                                    'port_range_max': port,
                                    'protocol': protocol,
                                    'remote_ip_prefix': rule[
                                        'remote_ip_prefix'],
                                    'security_group_id': lb_sg,
                                    'description': sg_rule_name,
                                },
                            })
                        except n_exc.NeutronClientException as ex:
                            if ex.status_code != requests.codes.conflict:
                                LOG.exception('Failed when creating security '
                                              'group rule for listener %s.',
                                              sg_rule_name)

        # Delete LBaaS sg rules that do not match NP
        for rule in lbaas_sg_rules['security_group_rules']:
            if (rule.get('protocol') != protocol.lower() or
                    rule.get('port_range_min') != port or
                    rule.get('direction') != 'ingress'):
                if all_pod_rules and self._is_default_rule(rule):
                    LOG.debug("Removing default LBaaS sg rule for sg: %r",
                              lb_sg)
                    neutron.delete_security_group_rule(rule['id'])
                continue
            self._delete_rule_if_no_match(rule, all_pod_rules)

        if add_default_rules:
            try:
                LOG.debug("Restoring default LBaaS sg rule for sg: %r", lb_sg)
                neutron.create_security_group_rule({
                    'security_group_rule': {
                        'direction': 'ingress',
                        'port_range_min': port,
                        'port_range_max': port,
                        'protocol': protocol,
                        'security_group_id': lb_sg,
                        'description': sg_rule_name,
                    },
                })
            except n_exc.NeutronClientException as ex:
                if ex.status_code != requests.codes.conflict:
                    LOG.exception('Failed when creating security '
                                  'group rule for listener %s.',
                                  sg_rule_name)

    def _delete_rule_if_no_match(self, rule, all_pod_rules):
        for pod_rule in all_pod_rules:
            if pod_rule['remote_ip_prefix'] == rule['remote_ip_prefix']:
                return
        neutron = clients.get_neutron_client()
        LOG.debug("Deleting sg rule: %r", rule['id'])
        neutron.delete_security_group_rule(rule['id'])

    def _is_default_rule(self, rule):
        if (rule.get('direction') == 'ingress' and
                not rule.get('remote_ip_prefix') and
                'network-policy' not in rule.get('description')):
            return True
        return False

    def _remove_default_octavia_rules(self, sg_id, listener):
        neutron = clients.get_neutron_client()
        for remaining in self._provisioning_timer(
                _ACTIVATION_TIMEOUT, _LB_STS_POLL_SLOW_INTERVAL):
            listener_rules = neutron.list_security_group_rules(
                security_group_id=sg_id,
                protocol=listener.protocol,
                port_range_min=listener.port,
                port_range_max=listener.port,
                direction='ingress')
            for rule in listener_rules['security_group_rules']:
                if not (rule.get('remote_group_id') or
                        rule.get('remote_ip_prefix')):
                    # remove default sg rules
                    neutron.delete_security_group_rule(rule['id'])
                    return

    def _extend_lb_security_group_rules(self, loadbalancer, listener):
        neutron = clients.get_neutron_client()

        if CONF.octavia_defaults.sg_mode == 'create':
            sg_id = self._find_listeners_sg(loadbalancer)
            # if an SG for the loadbalancer has not being created, create one
            if not sg_id:
                sg = neutron.create_security_group({
                    'security_group': {
                        'name': loadbalancer.name,
                        'project_id': loadbalancer.project_id,
                        },
                    })
                sg_id = sg['security_group']['id']
                c_utils.tag_neutron_resources('security-groups', [sg_id])
                loadbalancer.security_groups.append(sg_id)
                vip_port = self._get_vip_port(loadbalancer)
                neutron.update_port(
                    vip_port.get('id'),
                    {'port': {
                        'security_groups': loadbalancer.security_groups}})
        else:
            sg_id = self._get_vip_port(loadbalancer).get('security_groups')[0]
            # wait until octavia adds default sg rules
            self._remove_default_octavia_rules(sg_id, listener)

        for sg in loadbalancer.security_groups:
            if sg != sg_id:
                try:
                    neutron.create_security_group_rule({
                        'security_group_rule': {
                            'direction': 'ingress',
                            'port_range_min': listener.port,
                            'port_range_max': listener.port,
                            'protocol': listener.protocol,
                            'security_group_id': sg_id,
                            'remote_group_id': sg,
                            'description': listener.name,
                        },
                    })
                except n_exc.NeutronClientException as ex:
                    if ex.status_code != requests.codes.conflict:
                        LOG.exception('Failed when creating security group '
                                      'rule for listener %s.', listener.name)

        # ensure routes have access to the services
        service_subnet_cidr = utils.get_subnet_cidr(loadbalancer.subnet_id)
        try:
            # add access from service subnet
            neutron.create_security_group_rule({
                'security_group_rule': {
                    'direction': 'ingress',
                    'port_range_min': listener.port,
                    'port_range_max': listener.port,
                    'protocol': listener.protocol,
                    'security_group_id': sg_id,
                    'remote_ip_prefix': service_subnet_cidr,
                    'description': listener.name,
                },
            })

            # add access from worker node VM subnet for non-native route
            # support
            worker_subnet_id = CONF.pod_vif_nested.worker_nodes_subnet
            if worker_subnet_id:
                worker_subnet_cidr = utils.get_subnet_cidr(worker_subnet_id)
                neutron.create_security_group_rule({
                    'security_group_rule': {
                        'direction': 'ingress',
                        'port_range_min': listener.port,
                        'port_range_max': listener.port,
                        'protocol': listener.protocol,
                        'security_group_id': sg_id,
                        'remote_ip_prefix': worker_subnet_cidr,
                        'description': listener.name,
                    },
                })
        except n_exc.NeutronClientException as ex:
            if ex.status_code != requests.codes.conflict:
                LOG.exception('Failed when creating security group rule '
                              'to enable routes for listener %s.',
                              listener.name)

    def _ensure_security_group_rules(self, loadbalancer, listener,
                                     service_type):
        namespace_isolation = (
            'namespace' in CONF.kubernetes.enabled_handlers and
            CONF.kubernetes.service_security_groups_driver == 'namespace')
        create_sg = CONF.octavia_defaults.sg_mode == 'create'

        if create_sg:
            self._create_lb_security_group_rule(loadbalancer, listener)
        if (namespace_isolation and service_type == 'ClusterIP' and
                CONF.octavia_defaults.enforce_sg_rules):
            self._extend_lb_security_group_rules(loadbalancer, listener)

    def ensure_listener(self, loadbalancer, protocol, port,
                        service_type='ClusterIP'):
        name = "%s:%s:%s" % (loadbalancer.name, protocol, port)
        listener = obj_lbaas.LBaaSListener(name=name,
                                           project_id=loadbalancer.project_id,
                                           loadbalancer_id=loadbalancer.id,
                                           protocol=protocol,
                                           port=port)
        try:
            result = self._ensure_provisioned(
                loadbalancer, listener, self._create_listener,
                self._find_listener, _LB_STS_POLL_SLOW_INTERVAL)
        except requests.exceptions.HTTPError:
            LOG.info("Listener creation failed, most probably because "
                     "protocol %(prot)s is not supported", {'prot': protocol})
            return None

        self._ensure_security_group_rules(loadbalancer, result, service_type)

        return result

    def release_listener(self, loadbalancer, listener):
        neutron = clients.get_neutron_client()
        lbaas = clients.get_loadbalancer_client()
        self._release(loadbalancer, listener,
                      lbaas.delete_listener,
                      listener.id)

        if CONF.octavia_defaults.sg_mode == 'create':
            sg_id = self._find_listeners_sg(loadbalancer)
        else:
            sg_id = self._get_vip_port(loadbalancer).get('security_groups')[0]
        if sg_id:
            rules = neutron.list_security_group_rules(
                security_group_id=sg_id, description=listener.name)
            rules = rules['security_group_rules']
            if len(rules):
                neutron.delete_security_group_rule(rules[0]['id'])
            else:
                LOG.warning('Cannot find SG rule for %s (%s) listener.',
                            listener.id, listener.name)

    def ensure_pool(self, loadbalancer, listener):
        pool = obj_lbaas.LBaaSPool(name=listener.name,
                                   project_id=loadbalancer.project_id,
                                   loadbalancer_id=loadbalancer.id,
                                   listener_id=listener.id,
                                   protocol=listener.protocol)
        return self._ensure_provisioned(loadbalancer, pool,
                                        self._create_pool,
                                        self._find_pool)

    def ensure_pool_attached_to_lb(self, loadbalancer, namespace,
                                   svc_name, protocol):
        name = self.get_loadbalancer_pool_name(loadbalancer,
                                               namespace, svc_name)
        pool = obj_lbaas.LBaaSPool(name=name,
                                   project_id=loadbalancer.project_id,
                                   loadbalancer_id=loadbalancer.id,
                                   listener_id=None,
                                   protocol=protocol)
        return self._ensure_provisioned(loadbalancer, pool,
                                        self._create_pool,
                                        self._find_pool_by_name)

    def release_pool(self, loadbalancer, pool):
        lbaas = clients.get_loadbalancer_client()
        self._release(loadbalancer, pool, lbaas.delete_pool, pool.id)

    def ensure_member(self, loadbalancer, pool,
                      subnet_id, ip, port, target_ref_namespace,
                      target_ref_name, listener_port=None):
        name = ("%s/%s" % (target_ref_namespace, target_ref_name))
        name += ":%s" % port
        member = obj_lbaas.LBaaSMember(name=name,
                                       project_id=loadbalancer.project_id,
                                       pool_id=pool.id,
                                       subnet_id=subnet_id,
                                       ip=ip,
                                       port=port)
        result = self._ensure_provisioned(loadbalancer, member,
                                          self._create_member,
                                          self._find_member)

        network_policy = (
            'policy' in CONF.kubernetes.enabled_handlers and
            CONF.kubernetes.service_security_groups_driver == 'policy')
        if (network_policy and CONF.octavia_defaults.enforce_sg_rules and
                listener_port):
            protocol = pool.protocol
            sg_rule_name = pool.name
            self._apply_members_security_groups(loadbalancer, listener_port,
                                                port, protocol, sg_rule_name)
        return result

    def release_member(self, loadbalancer, member):
        lbaas = clients.get_loadbalancer_client()
        self._release(loadbalancer, member, lbaas.delete_member, member.id,
                      member.pool_id)

    def _get_vip_port(self, loadbalancer):
        neutron = clients.get_neutron_client()
        try:
            fixed_ips = ['subnet_id=%s' % str(loadbalancer.subnet_id),
                         'ip_address=%s' % str(loadbalancer.ip)]
            ports = neutron.list_ports(fixed_ips=fixed_ips)
        except n_exc.NeutronClientException:
            LOG.error("Port with fixed ips %s not found!", fixed_ips)
            raise

        if ports['ports']:
            return ports['ports'][0]

        return None

    def _post_lb_resource(self, resource, request, **kwargs):
        # FIXME(dulek): openstacksdk doesn't support Octavia tags until version
        #               0.24.0 (Stein+). At the moment our dependency is
        #               >=0.13.0, because we want Kuryr to support multiple
        #               OpenStack versions also in terms of dependencies (think
        #               building container images from various distros or
        #               running Kuryr on older OS-es). Once 0.24.0 is fairly
        #               stable and available, we can raise the requirement and
        #               use lbaas.create_*() directly. Until then we manually
        #               send POST request.
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.post(resource.base_path % kwargs,
                              json={resource.resource_key: request})
        if not response.ok:
            LOG.error('Error when creating %s: %s', resource.resource_key,
                      response.text)
            response.raise_for_status()
        response_dict = response.json()[resource.resource_key]
        return resource(**response_dict)

    def _create_loadbalancer(self, loadbalancer):
        request = {
            'name': loadbalancer.name,
            'project_id': loadbalancer.project_id,
            'vip_address': str(loadbalancer.ip),
            'vip_subnet_id': loadbalancer.subnet_id,
        }

        if loadbalancer.provider is not None:
            request['provider'] = loadbalancer.provider

        self._add_tags('loadbalancer', request)

        response = self._post_lb_resource(o_lb.LoadBalancer, request)

        loadbalancer.id = response.id
        loadbalancer.port_id = self._get_vip_port(loadbalancer).get("id")
        if (loadbalancer.provider is not None and
                loadbalancer.provider != response.provider):
            LOG.error("Request provider(%s) != Response provider(%s)",
                      loadbalancer.provider, response.provider)
            return None
        loadbalancer.provider = response.provider
        return loadbalancer

    def _find_loadbalancer(self, loadbalancer):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.load_balancers(
            name=loadbalancer.name,
            project_id=loadbalancer.project_id,
            vip_address=str(loadbalancer.ip),
            vip_subnet_id=loadbalancer.subnet_id)

        try:
            os_lb = next(response)  # openstacksdk returns a generator
            loadbalancer.id = os_lb.id
            loadbalancer.port_id = self._get_vip_port(loadbalancer).get("id")
            loadbalancer.provider = os_lb.provider
            if os_lb.provisioning_status == 'ERROR':
                self.release_loadbalancer(loadbalancer)
                return None
        except (KeyError, StopIteration):
            return None

        return loadbalancer

    def _create_listener(self, listener):
        request = {
            'name': listener.name,
            'project_id': listener.project_id,
            'loadbalancer_id': listener.loadbalancer_id,
            'protocol': listener.protocol,
            'protocol_port': listener.port,
        }
        self._add_tags('listener', request)
        response = self._post_lb_resource(o_lis.Listener, request)
        listener.id = response.id
        return listener

    def _find_listener(self, listener):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.listeners(
            name=listener.name,
            project_id=listener.project_id,
            load_balancer_id=listener.loadbalancer_id,
            protocol=listener.protocol,
            protocol_port=listener.port)

        try:
            os_listener = next(response)
            listener.id = os_listener.id
        except (KeyError, StopIteration):
            return None

        return listener

    def _create_pool(self, pool):
        # TODO(ivc): make lb_algorithm configurable
        lb_algorithm = 'ROUND_ROBIN'
        request = {
            'name': pool.name,
            'project_id': pool.project_id,
            'listener_id': pool.listener_id,
            'loadbalancer_id': pool.loadbalancer_id,
            'protocol': pool.protocol,
            'lb_algorithm': lb_algorithm,
        }
        self._add_tags('pool', request)
        response = self._post_lb_resource(o_pool.Pool, request)
        pool.id = response.id
        return pool

    def _find_pool(self, pool, by_listener=True):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.pools(
            name=pool.name,
            project_id=pool.project_id,
            loadbalancer_id=pool.loadbalancer_id,
            protocol=pool.protocol)

        try:
            if by_listener:
                pools = [p for p in response if pool.listener_id
                         in {l['id'] for l in p.listeners}]
            else:
                pools = [p for p in response if pool.name == p.name]

            pool.id = pools[0].id
        except (KeyError, IndexError):
            return None
        return pool

    def _find_pool_by_name(self, pool):
        return self._find_pool(pool, by_listener=False)

    def _create_member(self, member):
        request = {
            'name': member.name,
            'project_id': member.project_id,
            'subnet_id': member.subnet_id,
            'address': str(member.ip),
            'protocol_port': member.port,
        }
        self._add_tags('member', request)
        response = self._post_lb_resource(o_mem.Member, request,
                                          pool_id=member.pool_id)
        member.id = response.id
        return member

    def _find_member(self, member):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.members(
            member.pool_id,
            name=member.name,
            project_id=member.project_id,
            subnet_id=member.subnet_id,
            address=member.ip,
            protocol_port=member.port)

        try:
            member.id = next(response).id
        except (KeyError, StopIteration):
            return None

        return member

    def _ensure(self, obj, create, find):
        okay_codes = (409, 500)
        try:
            result = create(obj)
            LOG.debug("Created %(obj)s", {'obj': result})
            return result
        except o_exc.HttpException as e:
            if e.status_code not in okay_codes:
                raise
        except requests.exceptions.HTTPError as e:
            if e.response.status_code not in okay_codes:
                raise

        result = find(obj)
        if result:
            LOG.debug("Found %(obj)s", {'obj': result})
        return result

    def _ensure_provisioned(self, loadbalancer, obj, create, find,
                            interval=_LB_STS_POLL_FAST_INTERVAL):
        for remaining in self._provisioning_timer(_ACTIVATION_TIMEOUT,
                                                  interval):
            self._wait_for_provisioning(loadbalancer, remaining, interval)
            try:
                result = self._ensure(obj, create, find)
                if result:
                    return result
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == httplib.BAD_REQUEST:
                    raise

        raise k_exc.ResourceNotReady(obj)

    def _release(self, loadbalancer, obj, delete, *args, **kwargs):
        for remaining in self._provisioning_timer(_ACTIVATION_TIMEOUT):
            try:
                try:
                    delete(*args, **kwargs)
                    return
                except (o_exc.ConflictException, o_exc.BadRequestException):
                    self._wait_for_provisioning(loadbalancer, remaining)
            except o_exc.NotFoundException:
                return

        raise k_exc.ResourceNotReady(obj)

    def _wait_for_provisioning(self, loadbalancer, timeout,
                               interval=_LB_STS_POLL_FAST_INTERVAL):
        lbaas = clients.get_loadbalancer_client()

        for remaining in self._provisioning_timer(timeout, interval):
            response = lbaas.get_load_balancer(loadbalancer.id)
            status = response.provisioning_status
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

    def _wait_for_deletion(self, loadbalancer, timeout,
                           interval=_LB_STS_POLL_FAST_INTERVAL):
        lbaas = clients.get_loadbalancer_client()

        for remaining in self._provisioning_timer(timeout, interval):
            try:
                lbaas.get_load_balancer(loadbalancer.id)
            except o_exc.NotFoundException:
                return

    def _provisioning_timer(self, timeout,
                            interval=_LB_STS_POLL_FAST_INTERVAL):
        # REVISIT(ivc): consider integrating with Retry
        max_interval = 15
        with timeutils.StopWatch(duration=timeout) as timer:
            while not timer.expired():
                yield timer.leftover()
                interval = interval * 2 * random.gauss(0.8, 0.05)
                interval = min(interval, max_interval)
                interval = min(interval, timer.leftover())
                if interval:
                    time.sleep(interval)

    def _find_listeners_sg(self, loadbalancer, lb_name=None):
        neutron = clients.get_neutron_client()
        if lb_name:
            sgs = neutron.list_security_groups(
                name=lb_name, project_id=loadbalancer.project_id)
            # NOTE(ltomasbo): lb_name parameter is only passed when sg_mode
            # is 'create' and in that case there is only one sg associated
            # to the loadbalancer
            try:
                sg_id = sgs['security_groups'][0]['id']
            except IndexError:
                sg_id = None
                LOG.debug("Security Group not created yet for LBaaS.")
            return sg_id
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

    def get_lb_by_uuid(self, lb_uuid):
        lbaas = clients.get_loadbalancer_client()
        try:
            response = lbaas.get_load_balancer(lb_uuid)
        except o_exc.NotFoundException:
            LOG.debug("Couldn't find loadbalancer with uuid=%s", lb_uuid)
            return None

        return obj_lbaas.LBaaSLoadBalancer(
            id=response.id,
            port_id=response.vip_port_id,
            name=response.name,
            project_id=response.project_id,
            subnet_id=response.vip_subnet_id,
            ip=response.vip_address,
            security_groups=None,
            provider=response.provider)

    def get_pool_by_name(self, pool_name, project_id):
        lbaas = clients.get_loadbalancer_client()

        # NOTE(yboaron): pool_name should be constructed using
        # get_loadbalancer_pool_name function, which means that pool's name
        # is unique

        pools = lbaas.pools(project_id=project_id)
        for entry in pools:
            if not entry:
                continue
            if entry.name == pool_name:
                listener_id = (entry.listeners[0].id if
                               entry.listeners else None)
                return obj_lbaas.LBaaSPool(
                    name=entry.name, project_id=entry.project_id,
                    loadbalancer_id=entry.loadbalancers[0].id,
                    listener_id=listener_id,
                    protocol=entry.protocol, id=entry.id)
        return None

    def ensure_l7_policy(self, namespace, route_name,
                         loadbalancer, pool,
                         listener_id):
        name = namespace + route_name
        l7_policy = obj_lbaas.LBaaSL7Policy(name=name,
                                            project_id=pool.project_id,
                                            listener_id=listener_id,
                                            redirect_pool_id=pool.id)

        return self._ensure_provisioned(
            loadbalancer, l7_policy, self._create_l7_policy,
            self._find_l7_policy)

    def release_l7_policy(self, loadbalancer, l7_policy):
        lbaas = clients.get_loadbalancer_client()
        self._release(
            loadbalancer, l7_policy, lbaas.delete_l7_policy,
            l7_policy.id)

    def _create_l7_policy(self, l7_policy):
        request = {
            'action': _L7_POLICY_ACT_REDIRECT_TO_POOL,
            'listener_id': l7_policy.listener_id,
            'name': l7_policy.name,
            'project_id': l7_policy.project_id,
            'redirect_pool_id': l7_policy.redirect_pool_id,
        }
        self._add_tags('l7policy', request)
        response = self._post_lb_resource(o_l7p.L7Policy, request)
        l7_policy.id = response['id']
        return l7_policy

    def _find_l7_policy(self, l7_policy):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.l7_policies(
            name=l7_policy.name,
            project_id=l7_policy.project_id,
            redirect_pool_id=l7_policy.redirect_pool_id,
            listener_id=l7_policy.listener_id)
        try:
            l7_policy.id = next(response).id
        except (KeyError, StopIteration):
            return None
        return l7_policy

    def ensure_l7_rule(self, loadbalancer, l7_policy, compare_type,
                       type, value):

        l7_rule = obj_lbaas.LBaaSL7Rule(
            compare_type=compare_type, l7policy_id=l7_policy.id,
            type=type, value=value)
        return self._ensure_provisioned(
            loadbalancer, l7_rule, self._create_l7_rule,
            self._find_l7_rule)

    def _create_l7_rule(self, l7_rule):
        request = {
            'compare_type': l7_rule.compare_type,
            'type': l7_rule.type,
            'value': l7_rule.value
        }
        self._add_tags('rule', request)
        response = self._post_lb_resource(o_l7r.L7Rule, request,
                                          l7policy_id=l7_rule.l7policy_id)
        l7_rule.id = response['id']
        return l7_rule

    def _find_l7_rule(self, l7_rule):
        lbaas = clients.get_loadbalancer_client()
        response = lbaas.l7_rules(
            l7_rule.l7policy_id,
            type=l7_rule.type,
            value=l7_rule.value,
            compare_type=l7_rule.compare_type)
        try:
            l7_rule.id = next(response).id
        except (KeyError, StopIteration):
            return None
        return l7_rule

    def release_l7_rule(self, loadbalancer, l7_rule):
        lbaas = clients.get_loadbalancer_client()
        self._release(
            loadbalancer, l7_rule, lbaas.delete_l7_rule,
            l7_rule.id, l7_rule.l7policy_id)

    def update_l7_rule(self, l7_rule, new_value):
        lbaas = clients.get_loadbalancer_client()
        try:
            lbaas.update_l7_rule(
                l7_rule.id, l7_rule.l7policy_id,
                value=new_value)
        except o_exc.SDKException:
            LOG.exception("Failed to update l7_rule- id=%s ", l7_rule.id)
            raise

    def is_pool_used_by_other_l7policies(self, l7policy, pool):
        lbaas = clients.get_loadbalancer_client()
        l7policy_list = lbaas.l7_policies(project_id=l7policy.project_id)
        for entry in l7policy_list:
            if not entry:
                continue
            if (entry.redirect_pool_id == pool.id and
                    entry.id != l7policy.id):
                return True
        return False

    def update_lbaas_sg(self, service, sgs):
        LOG.debug('Setting SG for LBaaS VIP port')

        svc_namespace = service['metadata']['namespace']
        svc_name = service['metadata']['name']
        svc_ports = service['spec'].get('ports', [])

        lbaas_name = "%s/%s" % (svc_namespace, svc_name)

        endpoints_link = utils.get_endpoints_link(service)
        k8s = clients.get_kubernetes_client()
        endpoint = k8s.get(endpoints_link)

        lbaas = utils.get_lbaas_state(endpoint)
        if not lbaas:
            return

        lbaas_obj = lbaas.loadbalancer
        lbaas_obj.security_groups = sgs

        utils.set_lbaas_state(endpoint, lbaas)

        for port in svc_ports:
            port_protocol = port['protocol']
            lbaas_port = port['port']
            target_port = port['targetPort']
            sg_rule_name = "%s:%s:%s" % (lbaas_name, port_protocol, lbaas_port)

            self._apply_members_security_groups(lbaas_obj, lbaas_port,
                                                target_port, port_protocol,
                                                sg_rule_name, sgs)
