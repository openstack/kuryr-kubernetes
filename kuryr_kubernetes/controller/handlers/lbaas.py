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

from kuryr.lib._i18n import _
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)

SUPPORTED_SERVICE_TYPES = ('ClusterIP', 'LoadBalancer')


class LBaaSSpecHandler(k8s_base.ResourceEventHandler):
    """LBaaSSpecHandler handles K8s Service events.

    LBaaSSpecHandler handles K8s Service events and updates related Endpoints
    with LBaaSServiceSpec when necessary.
    """

    OBJECT_KIND = k_const.K8S_OBJ_SERVICE
    OBJECT_WATCH_PATH = "%s/%s" % (k_const.K8S_API_BASE, "services")

    def __init__(self):
        super(LBaaSSpecHandler, self).__init__()
        self._drv_project = drv_base.ServiceProjectDriver.get_instance()
        self._drv_subnets = drv_base.ServiceSubnetsDriver.get_instance()
        self._drv_sg = drv_base.ServiceSecurityGroupsDriver.get_instance()

    def on_present(self, service):
        lbaas_spec = utils.get_lbaas_spec(service)

        if self._should_ignore(service):
            LOG.debug("Skipping Kubernetes service %s of an unsupported kind "
                      "or without a selector as Kubernetes does not create "
                      "an endpoint object for it.",
                      service['metadata']['name'])
            return

        if self._has_lbaas_spec_changes(service, lbaas_spec):
            lbaas_spec = self._generate_lbaas_spec(service)
            utils.set_lbaas_spec(service, lbaas_spec)

    def _is_supported_type(self, service):
        spec = service['spec']
        return spec.get('type') in SUPPORTED_SERVICE_TYPES

    def _get_service_ip(self, service):
        if self._is_supported_type(service):
            return service['spec'].get('clusterIP')
        return None

    def _should_ignore(self, service):
        return (not(self._has_selector(service)) or
                not(self._has_clusterip(service)) or
                not(self._is_supported_type(service)))

    def _has_selector(self, service):
        return service['spec'].get('selector')

    def _has_clusterip(self, service):
        # ignore headless service, clusterIP is None
        return service['spec'].get('clusterIP') != 'None'

    def _get_subnet_id(self, service, project_id, ip):
        subnets_mapping = self._drv_subnets.get_subnets(service, project_id)
        subnet_ids = {
            subnet_id
            for subnet_id, network in subnets_mapping.items()
            for subnet in network.subnets.objects
            if ip in subnet.cidr}

        if len(subnet_ids) != 1:
            raise k_exc.IntegrityError(_(
                "Found %(num)s subnets for service %(link)s IP %(ip)s") % {
                'link': service['metadata']['selfLink'],
                'ip': ip,
                'num': len(subnet_ids)})

        return subnet_ids.pop()

    def _generate_lbaas_spec(self, service):
        project_id = self._drv_project.get_project(service)
        ip = self._get_service_ip(service)
        subnet_id = self._get_subnet_id(service, project_id, ip)
        ports = self._generate_lbaas_port_specs(service)
        sg_ids = self._drv_sg.get_security_groups(service, project_id)
        spec_type = service['spec'].get('type')
        spec_lb_ip = service['spec'].get('loadBalancerIP')

        return obj_lbaas.LBaaSServiceSpec(ip=ip,
                                          project_id=project_id,
                                          subnet_id=subnet_id,
                                          ports=ports,
                                          security_groups_ids=sg_ids,
                                          type=spec_type,
                                          lb_ip=spec_lb_ip)

    def _has_lbaas_spec_changes(self, service, lbaas_spec):
        return (self._has_ip_changes(service, lbaas_spec) or
                utils.has_port_changes(service, lbaas_spec))

    def _has_ip_changes(self, service, lbaas_spec):
        link = service['metadata']['selfLink']
        svc_ip = self._get_service_ip(service)

        if not lbaas_spec:
            if svc_ip:
                LOG.debug("LBaaS spec is missing for %(link)s"
                          % {'link': link})
                return True
        elif str(lbaas_spec.ip) != svc_ip:
            LOG.debug("LBaaS spec IP %(spec_ip)s != %(svc_ip)s for %(link)s"
                      % {'spec_ip': lbaas_spec.ip,
                         'svc_ip': svc_ip,
                         'link': link})
            return True

        return False

    def _generate_lbaas_port_specs(self, service):
        return [obj_lbaas.LBaaSPortSpec(**port)
                for port in utils.get_service_ports(service)]


class LoadBalancerHandler(k8s_base.ResourceEventHandler):
    """LoadBalancerHandler handles K8s Endpoints events.

    LoadBalancerHandler handles K8s Endpoints events and tracks changes in
    LBaaSServiceSpec to update Neutron LBaaS accordingly and to reflect its'
    actual state in LBaaSState.
    """

    OBJECT_KIND = k_const.K8S_OBJ_ENDPOINTS
    OBJECT_WATCH_PATH = "%s/%s" % (k_const.K8S_API_BASE, "endpoints")

    def __init__(self):
        super(LoadBalancerHandler, self).__init__()
        self._drv_lbaas = drv_base.LBaaSDriver.get_instance()
        self._drv_pod_project = drv_base.PodProjectDriver.get_instance()
        self._drv_pod_subnets = drv_base.PodSubnetsDriver.get_instance()
        self._drv_service_pub_ip = drv_base.ServicePubIpDriver.get_instance()
        # Note(yboaron) LBaaS driver supports 'provider' parameter in
        # Load Balancer creation flow.
        # We need to set the requested load balancer provider
        # according to 'endpoints_driver_octavia_provider' configuration.
        self._lb_provider = None
        if (config.CONF.kubernetes.endpoints_driver_octavia_provider
                != 'default'):
            self._lb_provider = (
                config.CONF.kubernetes.endpoints_driver_octavia_provider)

    def on_present(self, endpoints):
        lbaas_spec = utils.get_lbaas_spec(endpoints)
        if self._should_ignore(endpoints, lbaas_spec):
            LOG.debug("Ignoring Kubernetes endpoints %s",
                      endpoints['metadata']['name'])
            return

        lbaas_state = utils.get_lbaas_state(endpoints)
        if not lbaas_state:
            lbaas_state = obj_lbaas.LBaaSState()

        if self._sync_lbaas_members(endpoints, lbaas_state, lbaas_spec):
            # Note(yboaron) For LoadBalancer services, we should allocate FIP,
            # associate it to LB VIP and update K8S service status
            if lbaas_state.service_pub_ip_info is None:
                service_pub_ip_info = (
                    self._drv_service_pub_ip.acquire_service_pub_ip_info(
                        lbaas_spec.type,
                        lbaas_spec.lb_ip,
                        lbaas_spec.project_id,
                        lbaas_state.loadbalancer.port_id))
                if service_pub_ip_info:
                    self._drv_service_pub_ip.associate_pub_ip(
                        service_pub_ip_info, lbaas_state.loadbalancer.port_id)
                    lbaas_state.service_pub_ip_info = service_pub_ip_info
                    self._update_lb_status(
                        endpoints,
                        lbaas_state.service_pub_ip_info.ip_addr)
            # REVISIT(ivc): since _sync_lbaas_members is responsible for
            # creating all lbaas components (i.e. load balancer, listeners,
            # pools, members), it is currently possible for it to fail (due
            # to invalid Kuryr/K8s/Neutron configuration, e.g. Members' IPs
            # not belonging to configured Neutron subnet or Service IP being
            # in use by gateway or VMs) leaving some Neutron entities without
            # properly updating annotation. Some sort of failsafe mechanism is
            # required to deal with such situations (e.g. cleanup, or skip
            # failing items, or validate configuration) to prevent annotation
            # being out of sync with the actual Neutron state.
            try:
                utils.set_lbaas_state(endpoints, lbaas_state)
            except k_exc.K8sResourceNotFound:
                # Note(yboaron) It's impossible to store neutron resources
                # in K8S object since object was deleted. In that case
                # we should rollback all neutron resources.
                LOG.debug("LoadBalancerHandler failed to store Openstack "
                          "resources in K8S object (not found)")
                self.on_deleted(endpoints, lbaas_state)

    def on_deleted(self, endpoints, lbaas_state=None):
        if lbaas_state is None:
            lbaas_state = utils.get_lbaas_state(endpoints)
        if not lbaas_state:
            return
        # NOTE(ivc): deleting pool deletes its members
        self._drv_lbaas.release_loadbalancer(
            loadbalancer=lbaas_state.loadbalancer)
        if lbaas_state.service_pub_ip_info:
            self._drv_service_pub_ip.release_pub_ip(
                lbaas_state.service_pub_ip_info)

    def _should_ignore(self, endpoints, lbaas_spec):
        # NOTE(ltomasbo): we must wait until service handler has annotated the
        # endpoints to process them. Thus, if annotations are not updated to
        # match the endpoints information, we should skip the event
        return not(lbaas_spec and
                   self._has_pods(endpoints) and
                   self._svc_handler_annotations_updated(endpoints,
                                                         lbaas_spec))

    def _svc_handler_annotations_updated(self, endpoints, lbaas_spec):
        svc_link = self._get_service_link(endpoints)
        k8s = clients.get_kubernetes_client()
        service = k8s.get(svc_link)
        if utils.has_port_changes(service, lbaas_spec):
            # NOTE(ltomasbo): Ensuring lbaas_spec annotated on the endpoints
            # is in sync with the service status, i.e., upon a service
            # modification it will ensure endpoint modifications are not
            # handled until the service handler has performed its annotations
            return False
        return True

    def _has_pods(self, endpoints):
        ep_subsets = endpoints.get('subsets', [])
        if not ep_subsets:
            return False
        return any(True
                   for subset in ep_subsets
                   for address in subset.get('addresses', [])
                   if address.get('targetRef', {}).get('kind') == 'Pod')

    def _sync_lbaas_members(self, endpoints, lbaas_state, lbaas_spec):
        changed = False

        if (self._has_pods(endpoints) and
                self._remove_unused_members(endpoints, lbaas_state,
                                            lbaas_spec)):
            changed = True

        if self._sync_lbaas_pools(endpoints, lbaas_state, lbaas_spec):
            changed = True

        if (self._has_pods(endpoints) and
                self._add_new_members(endpoints, lbaas_state, lbaas_spec)):
            changed = True

        return changed

    def _sync_lbaas_sgs(self, endpoints, lbaas_state, lbaas_spec):
        # NOTE (maysams) Need to retrieve the LBaaS Spec again due to
        # the possibility of it being updated after the LBaaS creation
        # process has started.
        svc_link = self._get_service_link(endpoints)
        k8s = clients.get_kubernetes_client()
        service = k8s.get(svc_link)
        lbaas_spec = utils.get_lbaas_spec(service)

        lb = lbaas_state.loadbalancer
        default_sgs = config.CONF.neutron_defaults.pod_security_groups
        # NOTE(maysams) As the endpoint and svc are annotated with the
        # 'lbaas_spec' in two separate k8s calls, it's possible that
        # the endpoint got annotated and the svc haven't due to controller
        # restarts. For this case, a resourceNotReady exception is raised
        # till the svc gets annotated with a 'lbaas_spec'.
        if lbaas_spec:
            lbaas_spec_sgs = lbaas_spec.security_groups_ids
        else:
            raise k_exc.ResourceNotReady(svc_link)
        if lb.security_groups and lb.security_groups != lbaas_spec_sgs:
            sgs = [lb_sg for lb_sg in lb.security_groups
                   if lb_sg not in default_sgs]
            if lbaas_spec_sgs != default_sgs:
                sgs.extend(lbaas_spec_sgs)
            lb.security_groups = sgs

    def _add_new_members(self, endpoints, lbaas_state, lbaas_spec):
        changed = False

        try:
            self._sync_lbaas_sgs(endpoints, lbaas_state, lbaas_spec)
        except k_exc.K8sResourceNotFound:
            LOG.debug("The svc has been deleted while processing the endpoints"
                      " update. No need to add new members.")

        lsnr_by_id = {l.id: l for l in lbaas_state.listeners}
        pool_by_lsnr_port = {(lsnr_by_id[p.listener_id].protocol,
                              lsnr_by_id[p.listener_id].port): p
                             for p in lbaas_state.pools}

        # NOTE(yboaron): Since LBaaSv2 doesn't support UDP load balancing,
        #              the LBaaS driver will return 'None' in case of UDP port
        #              listener creation.
        #              we should consider the case in which
        #              'pool_by_lsnr_port[p.protocol, p.port]' is missing
        pool_by_tgt_name = {}
        for p in lbaas_spec.ports:
            try:
                pool_by_tgt_name[p.name] = pool_by_lsnr_port[p.protocol,
                                                             p.port]
            except KeyError:
                continue
        current_targets = {(str(m.ip), m.port, m.pool_id)
                           for m in lbaas_state.members}

        for subset in endpoints.get('subsets', []):
            subset_ports = subset.get('ports', [])
            for subset_address in subset.get('addresses', []):
                try:
                    target_ip = subset_address['ip']
                    target_ref = subset_address['targetRef']
                    if target_ref['kind'] != k_const.K8S_OBJ_POD:
                        continue
                except KeyError:
                    continue
                if not pool_by_tgt_name:
                    continue
                for subset_port in subset_ports:
                    target_port = subset_port['port']
                    port_name = subset_port.get('name')
                    try:
                        pool = pool_by_tgt_name[port_name]
                    except KeyError:
                        LOG.debug("No pool found for port: %r", port_name)
                        continue

                    if (target_ip, target_port, pool.id) in current_targets:
                        continue
                    # TODO(apuimedo): Do not pass subnet_id at all when in
                    # L3 mode once old neutron-lbaasv2 is not supported, as
                    # octavia does not require it
                    if (config.CONF.octavia_defaults.member_mode ==
                            k_const.OCTAVIA_L2_MEMBER_MODE):
                        try:
                            member_subnet_id = self._get_pod_subnet(target_ref,
                                                                    target_ip)
                        except k_exc.K8sResourceNotFound:
                            LOG.debug("Member namespace has been deleted. No "
                                      "need to add the members as it is "
                                      "going to be deleted")
                            continue
                    else:
                        # We use the service subnet id so that the connectivity
                        # from VIP to pods happens in layer 3 mode, i.e.,
                        # routed.
                        member_subnet_id = lbaas_state.loadbalancer.subnet_id
                    first_member_of_the_pool = True
                    for member in lbaas_state.members:
                        if pool.id == member.pool_id:
                            first_member_of_the_pool = False
                            break
                    if first_member_of_the_pool:
                        listener_port = lsnr_by_id[pool.listener_id].port
                    else:
                        listener_port = None

                    member = self._drv_lbaas.ensure_member(
                        loadbalancer=lbaas_state.loadbalancer,
                        pool=pool,
                        subnet_id=member_subnet_id,
                        ip=target_ip,
                        port=target_port,
                        target_ref_namespace=target_ref['namespace'],
                        target_ref_name=target_ref['name'],
                        listener_port=listener_port)
                    lbaas_state.members.append(member)
                    changed = True

        return changed

    def _get_pod_subnet(self, target_ref, ip):
        # REVISIT(ivc): consider using true pod object instead
        pod = {'kind': target_ref['kind'],
               'metadata': {'name': target_ref['name'],
                            'namespace': target_ref['namespace']}}
        project_id = self._drv_pod_project.get_project(pod)
        subnets_map = self._drv_pod_subnets.get_subnets(pod, project_id)
        subnet_ids = [subnet_id for subnet_id, network in subnets_map.items()
                      for subnet in network.subnets.objects
                      if ip in subnet.cidr]
        if subnet_ids:
            return subnet_ids[0]
        else:
            # NOTE(ltomasbo): We are assuming that if ip is not on the
            # pod subnet is because the member is using hostnetworking. In
            # this worker_nodes_subnet will be used
            return config.CONF.pod_vif_nested.worker_nodes_subnet

    def _get_port_in_pool(self, pool, lbaas_state, lbaas_spec):
        for l in lbaas_state.listeners:
            if l.id != pool.listener_id:
                continue
            for port in lbaas_spec.ports:
                if l.port == port.port and l.protocol == port.protocol:
                    return port
        return None

    def _remove_unused_members(self, endpoints, lbaas_state, lbaas_spec):
        spec_ports = {}
        for pool in lbaas_state.pools:
            port = self._get_port_in_pool(pool, lbaas_state, lbaas_spec)
            if port:
                spec_ports[port.name] = pool.id

        current_targets = {(a['ip'], a.get('targetRef', {}).get('name', ''),
                            p['port'], spec_ports.get(p.get('name')))
                           for s in endpoints['subsets']
                           for a in s['addresses']
                           for p in s['ports']
                           if p.get('name') in spec_ports}

        removed_ids = set()
        for member in lbaas_state.members:
            try:
                member_name = member.name
                # NOTE: The member name is compose of:
                # NAMESPACE_NAME/POD_NAME:PROTOCOL_PORT
                pod_name = member_name.split('/')[1].split(':')[0]
            except AttributeError:
                pod_name = ""
            if ((str(member.ip), pod_name, member.port, member.pool_id) in
                    current_targets):
                continue
            self._drv_lbaas.release_member(lbaas_state.loadbalancer,
                                           member)
            removed_ids.add(member.id)

        if removed_ids:
            lbaas_state.members = [m for m in lbaas_state.members
                                   if m.id not in removed_ids]
        return bool(removed_ids)

    def _sync_lbaas_pools(self, endpoints, lbaas_state, lbaas_spec):
        changed = False

        if self._remove_unused_pools(lbaas_state, lbaas_spec):
            changed = True

        if self._sync_lbaas_listeners(endpoints, lbaas_state, lbaas_spec):
            changed = True

        if self._add_new_pools(lbaas_state, lbaas_spec):
            changed = True

        return changed

    def _add_new_pools(self, lbaas_state, lbaas_spec):
        changed = False

        current_listeners_ids = {pool.listener_id
                                 for pool in lbaas_state.pools}
        for listener in lbaas_state.listeners:
            if listener.id in current_listeners_ids:
                continue
            pool = self._drv_lbaas.ensure_pool(lbaas_state.loadbalancer,
                                               listener)
            lbaas_state.pools.append(pool)
            changed = True

        return changed

    def _is_pool_in_spec(self, pool, lbaas_state, lbaas_spec):
        # NOTE(yboaron): in order to check if a specific pool is in lbaas_spec
        # we should:
        #  1. get the listener that pool is attached to
        #  2. check if listener's attributes appear in lbaas_spec.
        for l in lbaas_state.listeners:
            if l.id != pool.listener_id:
                continue
            for port in lbaas_spec.ports:
                if l.port == port.port and l.protocol == port.protocol:
                    return True
        return False

    def _remove_unused_pools(self, lbaas_state, lbaas_spec):
        removed_ids = set()
        for pool in lbaas_state.pools:
            if self._is_pool_in_spec(pool, lbaas_state, lbaas_spec):
                continue
            self._drv_lbaas.release_pool(lbaas_state.loadbalancer,
                                         pool)
            removed_ids.add(pool.id)
        if removed_ids:
            lbaas_state.pools = [p for p in lbaas_state.pools
                                 if p.id not in removed_ids]
            lbaas_state.members = [m for m in lbaas_state.members
                                   if m.pool_id not in removed_ids]
        return bool(removed_ids)

    def _sync_lbaas_listeners(self, endpoints, lbaas_state, lbaas_spec):
        changed = False

        if self._remove_unused_listeners(endpoints, lbaas_state, lbaas_spec):
            changed = True

        if self._sync_lbaas_loadbalancer(endpoints, lbaas_state, lbaas_spec):
            changed = True

        if self._add_new_listeners(endpoints, lbaas_spec, lbaas_state):
            changed = True

        return changed

    def _add_new_listeners(self, endpoints, lbaas_spec, lbaas_state):
        changed = False
        lbaas_spec_ports = sorted(lbaas_spec.ports, key=lambda x: x.protocol)
        for port_spec in lbaas_spec_ports:
            protocol = port_spec.protocol
            port = port_spec.port
            # FIXME (maysams): Due to a bug in Octavia, which does
            # not allows listeners with same port but different
            # protocols to co-exist, we need to skip the creation of
            # listeners that have the same port as an existing one.
            name = "%s:%s" % (lbaas_state.loadbalancer.name, protocol)
            listener = self._get_listener_with_same_port(lbaas_state, port)
            if listener:
                if listener.protocol != protocol:
                    LOG.warning("Skipping listener creation for %s "
                                "as another one already exists with port %r",
                                name, port)
                continue
            listener = self._drv_lbaas.ensure_listener(
                loadbalancer=lbaas_state.loadbalancer,
                protocol=protocol,
                port=port,
                service_type=lbaas_spec.type)
            if listener is not None:
                lbaas_state.listeners.append(listener)
                changed = True
        return changed

    def _get_listener_with_same_port(self, lbaas_state, port):
        for listener in lbaas_state.listeners:
            if listener.port == port:
                return listener
        return None

    def _remove_unused_listeners(self, endpoints, lbaas_state, lbaas_spec):
        current_listeners = {p.listener_id for p in lbaas_state.pools}

        removed_ids = set()
        for listener in lbaas_state.listeners:
            if listener.id in current_listeners:
                continue
            self._drv_lbaas.release_listener(lbaas_state.loadbalancer,
                                             listener)
            removed_ids.add(listener.id)
        if removed_ids:
            lbaas_state.listeners = [l for l in lbaas_state.listeners
                                     if l.id not in removed_ids]
        return bool(removed_ids)

    def _update_lb_status(self, endpoints, lb_ip_address):
        status_data = {"loadBalancer": {
            "ingress": [{"ip": lb_ip_address.format()}]}}
        k8s = clients.get_kubernetes_client()
        svc_link = self._get_service_link(endpoints)
        try:
            k8s.patch("status", svc_link, status_data)
        except k_exc.K8sClientException:
            # REVISIT(ivc): only raise ResourceNotReady for NotFound
            raise k_exc.ResourceNotReady(svc_link)

    def _get_service_link(self, endpoints):
        ep_link = endpoints['metadata']['selfLink']
        link_parts = ep_link.split('/')

        if link_parts[-2] != 'endpoints':
            raise k_exc.IntegrityError(_(
                "Unsupported endpoints link: %(link)s") % {
                'link': ep_link})
        link_parts[-2] = 'services'
        return "/".join(link_parts)

    def _sync_lbaas_loadbalancer(self, endpoints, lbaas_state, lbaas_spec):
        changed = False
        lb = lbaas_state.loadbalancer

        if lb and lb.ip != lbaas_spec.ip:
            # if loadbalancerIP was associated to lbaas VIP, disassociate it.
            if lbaas_state.service_pub_ip_info:
                self._drv_service_pub_ip.disassociate_pub_ip(
                    lbaas_state.service_pub_ip_info)

            self._drv_lbaas.release_loadbalancer(
                loadbalancer=lb)
            lb = None
            lbaas_state.pools = []
            lbaas_state.listeners = []
            lbaas_state.members = []
            changed = True

        if not lb:
            if lbaas_spec.ip:
                lb_name = self._drv_lbaas.get_service_loadbalancer_name(
                    endpoints['metadata']['namespace'],
                    endpoints['metadata']['name'])
                lb = self._drv_lbaas.ensure_loadbalancer(
                    name=lb_name,
                    project_id=lbaas_spec.project_id,
                    subnet_id=lbaas_spec.subnet_id,
                    ip=lbaas_spec.ip,
                    security_groups_ids=lbaas_spec.security_groups_ids,
                    service_type=lbaas_spec.type,
                    provider=self._lb_provider)
                changed = True
            elif lbaas_state.service_pub_ip_info:
                self._drv_service_pub_ip.release_pub_ip(
                    lbaas_state.service_pub_ip_info)
                lbaas_state.service_pub_ip_info = None
                changed = True

        lbaas_state.loadbalancer = lb
        return changed
