# Copyright (c) 2020 Red Hat, Inc.
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

import time

from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)
CONF = config.CONF

OCTAVIA_DEFAULT_PROVIDERS = ['octavia', 'amphora']


class KuryrLoadBalancerHandler(k8s_base.ResourceEventHandler):
    """LoadBalancerStatusHandler handles K8s Endpoints events.

    LBStatusHandler handles K8s Endpoints events and tracks changes in
    LBaaSServiceSpec to update Neutron LBaaS accordingly and to reflect its'
    actual state in LBaaSState.
    """

    OBJECT_KIND = k_const.K8S_OBJ_KURYRLOADBALANCER
    OBJECT_WATCH_PATH = k_const.K8S_API_CRD_KURYRLOADBALANCERS

    def __init__(self):
        super(KuryrLoadBalancerHandler, self).__init__()
        self._drv_lbaas = drv_base.LBaaSDriver.get_instance()
        self._drv_pod_project = drv_base.PodProjectDriver.get_instance()
        self._drv_pod_subnets = drv_base.PodSubnetsDriver.get_instance()
        self._drv_service_pub_ip = drv_base.ServicePubIpDriver.get_instance()
        self._drv_svc_project = drv_base.ServiceProjectDriver.get_instance()
        self._drv_sg = drv_base.ServiceSecurityGroupsDriver.get_instance()
        self._drv_nodes_subnets = drv_base.NodesSubnetsDriver.get_instance()

    def _get_nodes_subnets(self):
        return utils.get_subnets_id_cidrs(
            self._drv_nodes_subnets.get_nodes_subnets())

    def on_present(self, loadbalancer_crd):
        if self._should_ignore(loadbalancer_crd):
            LOG.debug("Ignoring Kubernetes service %s",
                      loadbalancer_crd['metadata']['name'])
            return

        crd_lb = loadbalancer_crd['status'].get('loadbalancer')
        if crd_lb:
            lb_provider = crd_lb.get('provider')
            spec_lb_provider = loadbalancer_crd['spec'].get('provider')
            # amphora to ovn upgrade
            if not lb_provider or lb_provider in OCTAVIA_DEFAULT_PROVIDERS:
                if (spec_lb_provider and
                        spec_lb_provider not in OCTAVIA_DEFAULT_PROVIDERS):
                    self._ensure_release_lbaas(loadbalancer_crd)

            # ovn to amphora downgrade
            elif lb_provider and lb_provider not in OCTAVIA_DEFAULT_PROVIDERS:
                if (not spec_lb_provider or
                        spec_lb_provider in OCTAVIA_DEFAULT_PROVIDERS):
                    self._ensure_release_lbaas(loadbalancer_crd)

        if self._sync_lbaas_members(loadbalancer_crd):
            # Note(yboaron) For LoadBalancer services, we should allocate FIP,
            # associate it to LB VIP and update K8S service status
            lb_ip = loadbalancer_crd['spec'].get('lb_ip')
            pub_info = loadbalancer_crd['status'].get(
                    'service_pub_ip_info')
            if pub_info is None and loadbalancer_crd['spec'].get('type'):
                service_pub_ip_info = (
                    self._drv_service_pub_ip.acquire_service_pub_ip_info(
                        loadbalancer_crd['spec']['type'],
                        lb_ip,
                        loadbalancer_crd['spec']['project_id'],
                        loadbalancer_crd['status']['loadbalancer'][
                            'port_id']))
                if service_pub_ip_info:
                    self._drv_service_pub_ip.associate_pub_ip(
                        service_pub_ip_info, loadbalancer_crd['status'][
                            'loadbalancer']['port_id'])
                    loadbalancer_crd['status'][
                        'service_pub_ip_info'] = service_pub_ip_info
                    self._update_lb_status(loadbalancer_crd)
                    kubernetes = clients.get_kubernetes_client()
                    try:
                        kubernetes.patch_crd('status', utils.get_res_link(
                            loadbalancer_crd), loadbalancer_crd['status'])
                    except k_exc.K8sResourceNotFound:
                        LOG.debug('KuryrLoadbalancer CRD not found %s',
                                  loadbalancer_crd)
                    except k_exc.K8sClientException:
                        LOG.exception('Error updating KuryLoadbalancer CRD %s',
                                      loadbalancer_crd)
                        raise

    def _should_ignore(self, loadbalancer_crd):
        return (not(self._has_endpoints(loadbalancer_crd) or
                    loadbalancer_crd.get('status')) or not
                loadbalancer_crd['spec'].get('ip'))

    def _has_endpoints(self, loadbalancer_crd):
        ep_slices = loadbalancer_crd['spec'].get('endpointSlices', [])
        if not ep_slices:
            return False
        return True

    def on_finalize(self, loadbalancer_crd):
        LOG.debug("Deleting the loadbalancer CRD")

        if loadbalancer_crd['status'] != {}:
            # NOTE(ivc): deleting pool deletes its members
            self._drv_lbaas.release_loadbalancer(
                loadbalancer=loadbalancer_crd['status'].get('loadbalancer'))

            try:
                pub_info = loadbalancer_crd['status']['service_pub_ip_info']
            except KeyError:
                pub_info = None

            if pub_info:
                self._drv_service_pub_ip.release_pub_ip(
                    loadbalancer_crd['status']['service_pub_ip_info'])

        kubernetes = clients.get_kubernetes_client()
        LOG.debug('Removing finalizer from KuryrLoadBalancer CRD %s',
                  loadbalancer_crd)
        try:
            kubernetes.remove_finalizer(loadbalancer_crd,
                                        k_const.KURYRLB_FINALIZER)
        except k_exc.K8sClientException:
            LOG.exception('Error removing kuryrloadbalancer CRD finalizer '
                          'for %s', loadbalancer_crd)
            raise

        namespace = loadbalancer_crd['metadata']['namespace']
        name = loadbalancer_crd['metadata']['name']
        try:
            service = kubernetes.get(f"{k_const.K8S_API_NAMESPACES}"
                                     f"/{namespace}/services/{name}")
        except k_exc.K8sResourceNotFound as ex:
            LOG.warning("Failed to get service: %s", ex)
            return

        LOG.debug('Removing finalizer from service %s',
                  service["metadata"]["name"])
        try:
            kubernetes.remove_finalizer(service, k_const.SERVICE_FINALIZER)
        except k_exc.K8sClientException:
            LOG.exception('Error removing service finalizer '
                          'for %s', service["metadata"]["name"])
            raise

    def _sync_lbaas_members(self, loadbalancer_crd):
        changed = False

        if (self._remove_unused_members(loadbalancer_crd)):
            changed = True

        if self._sync_lbaas_pools(loadbalancer_crd):
            changed = True

        if (self._has_endpoints(loadbalancer_crd) and
                self._add_new_members(loadbalancer_crd)):
            changed = True

        return changed

    def _sync_lbaas_sgs(self, klb_crd):
        lb = klb_crd['status'].get('loadbalancer')
        svc_name = klb_crd['metadata']['name']
        svc_namespace = klb_crd['metadata']['namespace']
        k8s = clients.get_kubernetes_client()
        try:
            service = k8s.get(
                f'{k_const.K8S_API_NAMESPACES}/{svc_namespace}/'
                f'services/{svc_name}')
        except k_exc.K8sResourceNotFound:
            LOG.debug('Service %s not found.', svc_name)
            return
        except k_exc.K8sClientException:
            LOG.exception('Error retrieving Service %s.', svc_name)
            raise

        project_id = self._drv_svc_project.get_project(service)
        lb_sgs = self._drv_sg.get_security_groups(service, project_id)
        lb['security_groups'] = lb_sgs

        try:
            k8s.patch_crd('status/loadbalancer', utils.get_res_link(klb_crd),
                          {'security_groups': lb_sgs})
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrLoadBalancer %s not found', svc_name)
            return None
        except k_exc.K8sUnprocessableEntity:
            LOG.debug('KuryrLoadBalancer entity not processable '
                      'due to missing loadbalancer field.')
            return None
        except k_exc.K8sClientException:
            LOG.exception('Error syncing KuryrLoadBalancer'
                          ' %s', svc_name)
            raise
        return klb_crd

    def _add_new_members(self, loadbalancer_crd):
        changed = False

        if loadbalancer_crd['status'].get('loadbalancer'):
            loadbalancer_crd = self._sync_lbaas_sgs(loadbalancer_crd)
        if not loadbalancer_crd:
            return changed

        lsnr_by_id = {l['id']: l for l in loadbalancer_crd['status'].get(
            'listeners', [])}
        pool_by_lsnr_port = {(lsnr_by_id[p['listener_id']]['protocol'],
                              lsnr_by_id[p['listener_id']]['port']): p
                             for p in loadbalancer_crd['status'].get(
                                 'pools', [])}

        # NOTE(yboaron): Since LBaaSv2 doesn't support UDP load balancing,
        #              the LBaaS driver will return 'None' in case of UDP port
        #              listener creation.
        #              we should consider the case in which
        #              'pool_by_lsnr_port[p.protocol, p.port]' is missing
        pool_by_tgt_name = {}
        for p in loadbalancer_crd['spec'].get('ports', []):
            try:
                pool_by_tgt_name[p['name']] = pool_by_lsnr_port[p['protocol'],
                                                                p['port']]
            except KeyError:
                continue

        current_targets = [(str(m['ip']), m['port'], m['pool_id'])
                           for m in loadbalancer_crd['status'].get(
                               'members', [])]

        for ep_slice in loadbalancer_crd['spec']['endpointSlices']:
            ep_slices_ports = ep_slice.get('ports', [])
            for endpoint in ep_slice.get('endpoints', []):
                try:
                    target_ip = endpoint['addresses'][0]
                    target_ref = endpoint.get('targetRef')
                    target_namespace = None
                    if target_ref:
                        target_namespace = target_ref['namespace']
                    # Avoid to point to a Pod on hostNetwork
                    # that isn't the one to be added as Member.
                    if not target_ref and utils.get_subnet_by_ip(
                            self._get_nodes_subnets(),
                            target_ip):
                        target_pod = {}
                    else:
                        target_pod = utils.get_pod_by_ip(
                            target_ip, target_namespace)
                except KeyError:
                    continue
                if not pool_by_tgt_name:
                    continue
                for ep_slice_port in ep_slices_ports:
                    target_port = ep_slice_port['port']
                    port_name = ep_slice_port.get('name')
                    try:
                        pool = pool_by_tgt_name[port_name]
                    except KeyError:
                        LOG.debug("No pool found for port: %r", port_name)
                        continue

                    if (target_ip, target_port, pool['id']) in current_targets:
                        continue

                    member_subnet_id = self._get_subnet_by_octavia_mode(
                        target_pod, target_ip, loadbalancer_crd)

                    if not member_subnet_id:
                        LOG.warning("Skipping member creation for %s",
                                    target_ip)
                        continue

                    target_name, target_namespace = self._get_target_info(
                        target_ref, loadbalancer_crd)

                    first_member_of_the_pool = True
                    for member in loadbalancer_crd['status'].get(
                            'members', []):
                        if pool['id'] == member['pool_id']:
                            first_member_of_the_pool = False
                            break
                    if first_member_of_the_pool:
                        listener_port = lsnr_by_id[pool['listener_id']][
                            'port']
                    else:
                        listener_port = None
                    loadbalancer = loadbalancer_crd['status']['loadbalancer']
                    member = self._drv_lbaas.ensure_member(
                        loadbalancer=loadbalancer,
                        pool=pool,
                        subnet_id=member_subnet_id,
                        ip=target_ip,
                        port=target_port,
                        target_ref_namespace=target_namespace,
                        target_ref_name=target_name,
                        listener_port=listener_port)
                    if not member:
                        continue
                    members = loadbalancer_crd['status'].get('members', [])
                    if members:
                        loadbalancer_crd['status'].get('members', []).append(
                            member)
                    else:
                        loadbalancer_crd['status']['members'] = []
                        loadbalancer_crd['status'].get('members', []).append(
                            member)
                    kubernetes = clients.get_kubernetes_client()
                    try:
                        kubernetes.patch_crd('status', utils.get_res_link(
                            loadbalancer_crd), loadbalancer_crd['status'])
                    except k_exc.K8sResourceNotFound:
                        LOG.debug('KuryrLoadbalancer CRD not found %s',
                                  loadbalancer_crd)
                    except k_exc.K8sClientException:
                        LOG.exception('Error updating KuryLoadbalancer CRD %s',
                                      loadbalancer_crd)
                        raise
                    changed = True
        return changed

    def _get_target_info(self, target_ref, loadbalancer_crd):
        if target_ref:
            target_namespace = target_ref['namespace']
            target_name = target_ref['name']
        else:
            target_namespace = loadbalancer_crd['metadata']['namespace']
            target_name = loadbalancer_crd['metadata']['name']
        return target_name, target_namespace

    def _get_subnet_by_octavia_mode(self, target_pod, target_ip, lb_crd):
        # TODO(apuimedo): Do not pass subnet_id at all when in
        # L3 mode once old neutron-lbaasv2 is not supported, as
        # octavia does not require it
        subnet_id = None
        if (CONF.octavia_defaults.member_mode ==
                k_const.OCTAVIA_L2_MEMBER_MODE):
            if target_pod:
                subnet_id = self._get_pod_subnet(target_pod, target_ip)
            else:
                subnet = utils.get_subnet_by_ip(
                    self._get_nodes_subnets(), target_ip)
                if subnet:
                    subnet_id = subnet[0]
        else:
            # We use the service subnet id so that the connectivity
            # from VIP to pods happens in layer 3 mode, i.e.,
            # routed.
            subnet_id = lb_crd['status']['loadbalancer']['subnet_id']
        return subnet_id

    def _get_pod_subnet(self, pod, ip):
        project_id = self._drv_pod_project.get_project(pod)
        subnets_map = self._drv_pod_subnets.get_subnets(pod, project_id)
        subnet_ids = [subnet_id for subnet_id, network in subnets_map.items()
                      for subnet in network.subnets.objects
                      if ip in subnet.cidr]
        if subnet_ids:
            return subnet_ids[0]
        else:
            # NOTE(ltomasbo): We are assuming that if IP is not on the
            # pod subnet it's because the member is using hostNetworking. In
            # this case we look for the IP in worker_nodes_subnets.
            subnet = utils.get_subnet_by_ip(self._get_nodes_subnets(), ip)
            if subnet:
                return subnet[0]
            else:
                # This shouldn't ever happen but let's return just the first
                # worker_nodes_subnet id.
                return self._get_nodes_subnets()[0][0]

    def _get_port_in_pool(self, pool, loadbalancer_crd):

        for l in loadbalancer_crd['status']['listeners']:
            if l['id'] != pool['listener_id']:
                continue
            for port in loadbalancer_crd['spec'].get('ports', []):
                if l.get('port') == port.get(
                        'port') and l.get('protocol') == port.get('protocol'):
                    return port
        return None

    def _remove_unused_members(self, loadbalancer_crd):
        lb_crd_name = loadbalancer_crd['metadata']['name']
        spec_ports = {}
        pools = loadbalancer_crd['status'].get('pools', [])
        for pool in pools:
            port = self._get_port_in_pool(pool, loadbalancer_crd)
            if port:
                if not port.get('name'):
                    port['name'] = None
                spec_ports[port['name']] = pool['id']

        ep_slices = loadbalancer_crd['spec'].get('endpointSlices', [])
        current_targets = [utils.get_current_endpoints_target(
                           ep, p, spec_ports, lb_crd_name)
                           for ep_slice in ep_slices
                           for ep in ep_slice['endpoints']
                           for p in ep_slice['ports']
                           if p.get('name') in spec_ports]

        removed_ids = set()
        for member in loadbalancer_crd['status'].get('members', []):
            member_name = member.get('name', '')
            try:
                # NOTE: The member name is compose of:
                # NAMESPACE_NAME/POD_NAME:PROTOCOL_PORT
                pod_name = member_name.split('/')[1].split(':')[0]
            except AttributeError:
                pod_name = ""

            if ((str(member['ip']), pod_name, member['port'], member[
                    'pool_id']) in current_targets):
                continue

            self._drv_lbaas.release_member(loadbalancer_crd['status'][
                'loadbalancer'], member)
            removed_ids.add(member['id'])

        if removed_ids:
            loadbalancer_crd['status']['members'] = [m for m in
                                                     loadbalancer_crd[
                                                         'status'][
                                                             'members']
                                                     if m['id'] not in
                                                     removed_ids]

            kubernetes = clients.get_kubernetes_client()
            try:
                kubernetes.patch_crd('status',
                                     utils.get_res_link(loadbalancer_crd),
                                     loadbalancer_crd['status'])
            except k_exc.K8sResourceNotFound:
                LOG.debug('KuryrLoadbalancer CRD not found %s',
                          loadbalancer_crd)
            except k_exc.K8sClientException:
                LOG.exception('Error updating KuryLoadbalancer CRD %s',
                              loadbalancer_crd)
                raise
        return bool(removed_ids)

    def _sync_lbaas_pools(self, loadbalancer_crd):
        changed = False

        if self._remove_unused_pools(loadbalancer_crd):
            changed = True

        if self._sync_lbaas_listeners(loadbalancer_crd):
            changed = True

        if self._add_new_pools(loadbalancer_crd):
            changed = True

        return changed

    def _add_new_pools(self, loadbalancer_crd):
        changed = False

        current_listeners_ids = {pool['listener_id']
                                 for pool in loadbalancer_crd['status'].get(
                                     'pools', [])}
        for listener in loadbalancer_crd['status'].get('listeners', []):
            if listener['id'] in current_listeners_ids:
                continue
            pool = self._drv_lbaas.ensure_pool(loadbalancer_crd['status'][
                'loadbalancer'], listener)
            if not pool:
                continue
            pools = loadbalancer_crd['status'].get('pools', [])
            if pools:
                loadbalancer_crd['status'].get('pools', []).append(
                    pool)
            else:
                loadbalancer_crd['status']['pools'] = []
                loadbalancer_crd['status'].get('pools', []).append(
                    pool)
            kubernetes = clients.get_kubernetes_client()
            try:
                kubernetes.patch_crd('status',
                                     utils.get_res_link(loadbalancer_crd),
                                     loadbalancer_crd['status'])
            except k_exc.K8sResourceNotFound:
                LOG.debug('KuryrLoadbalancer CRD not found %s',
                          loadbalancer_crd)
            except k_exc.K8sClientException:
                LOG.exception('Error updating KuryrLoadbalancer CRD %s',
                              loadbalancer_crd)
                raise
            changed = True
        return changed

    def _is_pool_in_spec(self, pool, loadbalancer_crd):
        # NOTE(yboaron): in order to check if a specific pool is in lbaas_spec
        # we should:
        #  1. get the listener that pool is attached to
        #  2. check if listener's attributes appear in lbaas_spec.
        for l in loadbalancer_crd['status']['listeners']:
            if l['id'] != pool['listener_id']:
                continue
            for port in loadbalancer_crd['spec'].get('ports', []):
                if l['port'] == port['port'] and l['protocol'] == port[
                        'protocol']:
                    return True
        return False

    def _remove_unused_pools(self, loadbalancer_crd):
        removed_ids = set()

        for pool in loadbalancer_crd['status'].get('pools', []):
            if self._is_pool_in_spec(pool, loadbalancer_crd):
                continue
            self._drv_lbaas.release_pool(loadbalancer_crd['status'][
                'loadbalancer'], pool)
            removed_ids.add(pool['id'])
        if removed_ids:
            loadbalancer_crd['status']['pools'] = [p for p in loadbalancer_crd[
                'status'].get('pools', []) if p['id'] not in removed_ids]
            loadbalancer_crd['status']['members'] = [m for m in
                                                     loadbalancer_crd[
                                                         'status'].get(
                                                         'members', [])
                                                     if m['pool_id'] not in
                                                     removed_ids]

            kubernetes = clients.get_kubernetes_client()
            try:
                kubernetes.patch_crd('status',
                                     utils.get_res_link(loadbalancer_crd),
                                     loadbalancer_crd['status'])
            except k_exc.K8sResourceNotFound:
                LOG.debug('KuryrLoadbalancer CRD not found %s',
                          loadbalancer_crd)
            except k_exc.K8sClientException:
                LOG.exception('Error updating KuryLoadbalancer CRD %s',
                              loadbalancer_crd)
                raise
        return bool(removed_ids)

    def _sync_lbaas_listeners(self, loadbalancer_crd):
        changed = False

        if self._remove_unused_listeners(loadbalancer_crd):
            changed = True

        if self._sync_lbaas_loadbalancer(loadbalancer_crd):
            changed = True

        if self._add_new_listeners(loadbalancer_crd):
            changed = True

        return changed

    def _add_new_listeners(self, loadbalancer_crd):
        changed = False
        lb_crd_spec_ports = loadbalancer_crd['spec'].get('ports')
        if not lb_crd_spec_ports:
            return changed
        lbaas_spec_ports = sorted(lb_crd_spec_ports,
                                  key=lambda x: x['protocol'])
        for port_spec in lbaas_spec_ports:
            protocol = port_spec['protocol']
            port = port_spec['port']
            name = "%s:%s" % (loadbalancer_crd['status']['loadbalancer'][
                'name'], protocol)

            listener = [l for l in loadbalancer_crd['status'].get(
                'listeners', []) if l['port'] == port and l[
                    'protocol'] == protocol]

            if listener:
                continue
            # FIXME (maysams): Due to a bug in Octavia, which does
            # not allows listeners with same port but different
            # protocols to co-exist, we need to skip the creation of
            # listeners that have the same port as an existing one.
            listener = [l for l in loadbalancer_crd['status'].get(
                'listeners', []) if l['port'] == port]

            if listener and not self._drv_lbaas.double_listeners_supported():
                LOG.warning("Skipping listener creation for %s as another one"
                            " already exists with port %s", name, port)
                continue
            if protocol == "SCTP" and not self._drv_lbaas.sctp_supported():
                LOG.warning("Skipping listener creation as provider does"
                            " not support %s protocol", protocol)
                continue
            listener = self._drv_lbaas.ensure_listener(
                loadbalancer=loadbalancer_crd['status'].get('loadbalancer'),
                protocol=protocol,
                port=port,
                service_type=loadbalancer_crd['spec'].get('type'))
            if listener is not None:
                listeners = loadbalancer_crd['status'].get('listeners', [])
                if listeners:
                    listeners.append(listener)
                else:
                    loadbalancer_crd['status']['listeners'] = []
                    loadbalancer_crd['status'].get('listeners', []).append(
                        listener)

                kubernetes = clients.get_kubernetes_client()
                try:
                    kubernetes.patch_crd('status',
                                         utils.get_res_link(loadbalancer_crd),
                                         loadbalancer_crd['status'])
                except k_exc.K8sResourceNotFound:
                    LOG.debug('KuryrLoadbalancer CRD not found %s',
                              loadbalancer_crd)
                except k_exc.K8sClientException:
                    LOG.exception('Error updating KuryrLoadbalancer CRD %s',
                                  loadbalancer_crd)
                    raise
                changed = True
        return changed

    def _remove_unused_listeners(self, loadbalancer_crd):
        current_listeners = {p['listener_id'] for p in loadbalancer_crd[
            'status'].get('pools', [])}
        removed_ids = set()
        for listener in loadbalancer_crd['status'].get('listeners', []):
            if listener['id'] in current_listeners:
                continue
            self._drv_lbaas.release_listener(loadbalancer_crd['status'][
                'loadbalancer'], listener)
            removed_ids.add(listener['id'])
        if removed_ids:
            loadbalancer_crd['status']['listeners'] = [
                l for l in loadbalancer_crd['status'].get('listeners',
                                                          []) if l['id']
                not in removed_ids]

            kubernetes = clients.get_kubernetes_client()
            try:
                kubernetes.patch_crd('status',
                                     utils.get_res_link(loadbalancer_crd),
                                     loadbalancer_crd['status'])
            except k_exc.K8sResourceNotFound:
                LOG.debug('KuryrLoadbalancer CRD not found %s',
                          loadbalancer_crd)
            except k_exc.K8sClientException:
                LOG.exception('Error updating KuryLoadbalancer CRD %s',
                              loadbalancer_crd)
                raise
        return bool(removed_ids)

    def _update_lb_status(self, lb_crd):
        lb_crd_status = lb_crd['status']
        lb_ip_address = lb_crd_status['service_pub_ip_info']['ip_addr']
        name = lb_crd['metadata']['name']
        ns = lb_crd['metadata']['namespace']
        status_data = {"loadBalancer": {
                       "ingress": [{"ip": lb_ip_address.format()}]}}
        k8s = clients.get_kubernetes_client()
        try:
            k8s.patch("status", f"{k_const.K8S_API_NAMESPACES}"
                                f"/{ns}/services/{name}/status",
                                status_data)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(name)
        except k_exc.K8sClientException:
            LOG.exception("Kubernetes Client Exception"
                          "when updating the svc status %s"
                          % name)
            raise

    def _sync_lbaas_loadbalancer(self, loadbalancer_crd):
        changed = False
        lb = loadbalancer_crd['status'].get('loadbalancer')

        if lb and lb['ip'] != loadbalancer_crd['spec'].get('ip'):
            # if loadbalancerIP was associated to lbaas VIP, disassociate it.

            try:
                pub_info = loadbalancer_crd['status']['service_pub_ip_info']
            except KeyError:
                pub_info = None

            if pub_info:
                self._drv_service_pub_ip.disassociate_pub_ip(
                    loadbalancer_crd['status']['service_pub_ip_info'])
                self._drv_service_pub_ip.release_pub_ip(
                    loadbalancer_crd['status']['service_pub_ip_info'])

            self._drv_lbaas.release_loadbalancer(
                loadbalancer=lb)

            lb = {}
            loadbalancer_crd['status'] = {}

        if not lb:
            if loadbalancer_crd['spec'].get('ip'):
                lb_name = self._drv_lbaas.get_service_loadbalancer_name(
                    loadbalancer_crd['metadata']['namespace'],
                    loadbalancer_crd['metadata']['name'])
                lb = self._drv_lbaas.ensure_loadbalancer(
                    name=lb_name,
                    project_id=loadbalancer_crd['spec'].get('project_id'),
                    subnet_id=loadbalancer_crd['spec'].get('subnet_id'),
                    ip=loadbalancer_crd['spec'].get('ip'),
                    security_groups_ids=loadbalancer_crd['spec'].get(
                        'security_groups_ids'),
                    service_type=loadbalancer_crd['spec'].get('type'),
                    provider=loadbalancer_crd['spec'].get('provider'))
                loadbalancer_crd['status']['loadbalancer'] = lb

            kubernetes = clients.get_kubernetes_client()
            try:
                kubernetes.patch_crd('status',
                                     utils.get_res_link(loadbalancer_crd),
                                     loadbalancer_crd['status'])
            except k_exc.K8sResourceNotFound:
                LOG.debug('KuryrLoadbalancer CRD not found %s',
                          loadbalancer_crd)
            except k_exc.K8sClientException:
                LOG.exception('Error updating KuryrLoadbalancer CRD %s',
                              loadbalancer_crd)
                raise
            changed = True

        return changed

    def _ensure_release_lbaas(self, loadbalancer_crd):
        attempts = 0
        deadline = 0
        retry = True
        timeout = config.CONF.kubernetes.watch_retry_timeout
        while retry:
            try:
                if attempts == 1:
                    deadline = time.time() + timeout
                if (attempts > 0 and
                        utils.exponential_sleep(deadline, attempts) == 0):
                    LOG.error("Failed releasing lbaas '%s': deadline exceeded",
                              loadbalancer_crd['status']['loadbalancer'][
                                  'name'])
                    return
                self._drv_lbaas.release_loadbalancer(
                    loadbalancer=loadbalancer_crd['status'].get('loadbalancer')
                )
                retry = False
            except k_exc.ResourceNotReady:
                LOG.debug("Attempt (%s) of loadbalancer release %s failed."
                          " A retry will be triggered.", attempts,
                          loadbalancer_crd['status']['loadbalancer']['name'])
                attempts += 1
                retry = True

            loadbalancer_crd['status'] = {}
            k8s = clients.get_kubernetes_client()
            try:
                k8s.patch_crd('status', utils.get_res_link(loadbalancer_crd),
                              loadbalancer_crd['status'])
            except k_exc.K8sResourceNotFound:
                LOG.debug('KuryrLoadbalancer CRD not found %s',
                          loadbalancer_crd)
            except k_exc.K8sClientException:
                LOG.exception('Error updating KuryrLoadbalancer CRD %s',
                              loadbalancer_crd)
                raise
            # NOTE(ltomasbo): give some extra time to ensure the Load
            # Balancer VIP is also released
            time.sleep(1)
