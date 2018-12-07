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
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes.objects import lbaas as obj_lbaas

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
        lbaas_spec = self._get_lbaas_spec(service)

        if self._should_ignore(service):
            LOG.debug("Skiping Kubernetes service of an unsupported kind or "
                      "without a selector as Kubernetes does not create an "
                      "endpoint object for it.")
            return

        if self._has_lbaas_spec_changes(service, lbaas_spec):
            lbaas_spec = self._generate_lbaas_spec(service)
            self._set_lbaas_spec(service, lbaas_spec)

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
                self._has_port_changes(service, lbaas_spec))

    def _get_service_ports(self, service):
        return [{'name': port.get('name'),
                 'protocol': port.get('protocol', 'TCP'),
                 'port': port['port']}
                for port in service['spec']['ports']]

    def _has_port_changes(self, service, lbaas_spec):
        link = service['metadata']['selfLink']

        fields = obj_lbaas.LBaaSPortSpec.fields
        svc_port_set = {tuple(port[attr] for attr in fields)
                        for port in self._get_service_ports(service)}
        spec_port_set = {tuple(getattr(port, attr) for attr in fields)
                         for port in lbaas_spec.ports}

        if svc_port_set != spec_port_set:
            LOG.debug("LBaaS spec ports %(spec_ports)s != %(svc_ports)s "
                      "for %(link)s" % {'spec_ports': spec_port_set,
                                        'svc_ports': svc_port_set,
                                        'link': link})
        return svc_port_set != spec_port_set

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
                for port in self._get_service_ports(service)]

    def _get_endpoints_link(self, service):
        svc_link = service['metadata']['selfLink']
        link_parts = svc_link.split('/')

        if link_parts[-2] != 'services':
            raise k_exc.IntegrityError(_(
                "Unsupported service link: %(link)s") % {
                'link': svc_link})
        link_parts[-2] = 'endpoints'

        return "/".join(link_parts)

    def _set_lbaas_spec(self, service, lbaas_spec):
        # TODO(ivc): extract annotation interactions
        if lbaas_spec is None:
            LOG.debug("Removing LBaaSServiceSpec annotation: %r", lbaas_spec)
            annotation = None
        else:
            lbaas_spec.obj_reset_changes(recursive=True)
            LOG.debug("Setting LBaaSServiceSpec annotation: %r", lbaas_spec)
            annotation = jsonutils.dumps(lbaas_spec.obj_to_primitive(),
                                         sort_keys=True)
        svc_link = service['metadata']['selfLink']
        ep_link = self._get_endpoints_link(service)
        k8s = clients.get_kubernetes_client()

        try:
            k8s.annotate(ep_link,
                         {k_const.K8S_ANNOTATION_LBAAS_SPEC: annotation})
        except k_exc.K8sClientException:
            # REVISIT(ivc): only raise ResourceNotReady for NotFound
            raise k_exc.ResourceNotReady(ep_link)

        k8s.annotate(svc_link,
                     {k_const.K8S_ANNOTATION_LBAAS_SPEC: annotation},
                     resource_version=service['metadata']['resourceVersion'])

    def _get_lbaas_spec(self, service):
        # TODO(ivc): same as '_set_lbaas_spec'
        try:
            annotations = service['metadata']['annotations']
            annotation = annotations[k_const.K8S_ANNOTATION_LBAAS_SPEC]
        except KeyError:
            return None
        obj_dict = jsonutils.loads(annotation)
        obj = obj_lbaas.LBaaSServiceSpec.obj_from_primitive(obj_dict)
        LOG.debug("Got LBaaSServiceSpec from annotation: %r", obj)
        return obj


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
        lbaas_spec = self._get_lbaas_spec(endpoints)
        if self._should_ignore(endpoints, lbaas_spec):
            return

        lbaas_state = self._get_lbaas_state(endpoints)
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
                self._set_lbaas_state(endpoints, lbaas_state)
            except k_exc.K8sResourceNotFound:
                # Note(yboaron) It's impossible to store neutron resources
                # in K8S object since object was deleted. In that case
                # we should rollback all neutron resources.
                LOG.debug("LoadBalancerHandler failed to store Openstack "
                          "resources in K8S object (not found)")
                self.on_deleted(endpoints, lbaas_state)

    def on_deleted(self, endpoints, lbaas_state=None):
        if lbaas_state is None:
            lbaas_state = self._get_lbaas_state(endpoints)
        if not lbaas_state:
            return
        # NOTE(ivc): deleting pool deletes its members
        if self._drv_lbaas.cascading_capable:
            self._drv_lbaas.release_loadbalancer(
                loadbalancer=lbaas_state.loadbalancer)
            if lbaas_state.service_pub_ip_info:
                self._drv_service_pub_ip.release_pub_ip(
                    lbaas_state.service_pub_ip_info)
        else:
            lbaas_state.members = []
            self._sync_lbaas_members(endpoints, lbaas_state,
                                     obj_lbaas.LBaaSServiceSpec())

    def _should_ignore(self, endpoints, lbaas_spec):
        return not(lbaas_spec and
                   self._has_pods(endpoints) and
                   self._is_lbaas_spec_in_sync(endpoints, lbaas_spec))

    def _is_lbaas_spec_in_sync(self, endpoints, lbaas_spec):
        # REVISIT(ivc): consider other options instead of using 'name'
        ep_ports = list(set(port.get('name')
                            for subset in endpoints.get('subsets', [])
                            for port in subset.get('ports', [])))
        spec_ports = [port.name for port in lbaas_spec.ports]

        return sorted(ep_ports) == sorted(spec_ports)

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

    def _add_new_members(self, endpoints, lbaas_state, lbaas_spec):
        changed = False

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
        current_targets = {(str(m.ip), m.port) for m in lbaas_state.members}

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
                    if (target_ip, target_port) in current_targets:
                        continue
                    port_name = subset_port.get('name')
                    try:
                        pool = pool_by_tgt_name[port_name]
                    except KeyError:
                        LOG.debug("No pool found for port: %r", port_name)
                        continue
                    # TODO(apuimedo): Do not pass subnet_id at all when in
                    # L3 mode once old neutron-lbaasv2 is not supported, as
                    # octavia does not require it
                    if (config.CONF.octavia_defaults.member_mode ==
                            k_const.OCTAVIA_L2_MEMBER_MODE):
                        member_subnet_id = self._get_pod_subnet(target_ref,
                                                                target_ip)
                    else:
                        # We use the service subnet id so that the connectivity
                        # from VIP to pods happens in layer 3 mode, i.e.,
                        # routed.
                        member_subnet_id = lbaas_state.loadbalancer.subnet_id
                    member = self._drv_lbaas.ensure_member(
                        loadbalancer=lbaas_state.loadbalancer,
                        pool=pool,
                        subnet_id=member_subnet_id,
                        ip=target_ip,
                        port=target_port,
                        target_ref_namespace=target_ref['namespace'],
                        target_ref_name=target_ref['name'])
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
        # FIXME(ivc): potentially unsafe [0] index
        return [subnet_id for subnet_id, network in subnets_map.items()
                for subnet in network.subnets.objects
                if ip in subnet.cidr][0]

    def _remove_unused_members(self, endpoints, lbaas_state, lbaas_spec):
        spec_port_names = {p.name for p in lbaas_spec.ports}
        current_targets = {(a['ip'], p['port'])
                           for s in endpoints['subsets']
                           for a in s['addresses']
                           for p in s['ports']
                           if p.get('name') in spec_port_names}
        removed_ids = set()
        for member in lbaas_state.members:
            if (str(member.ip), member.port) in current_targets:
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
        current_port_tuples = {(listener.protocol, listener.port)
                               for listener in lbaas_state.listeners}
        for port_spec in lbaas_spec.ports:
            protocol = port_spec.protocol
            port = port_spec.port
            if (protocol, port) in current_port_tuples:
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

    def _get_lbaas_spec(self, endpoints):
        # TODO(ivc): same as '_get_lbaas_state'
        try:
            annotations = endpoints['metadata']['annotations']
            annotation = annotations[k_const.K8S_ANNOTATION_LBAAS_SPEC]
        except KeyError:
            return None
        obj_dict = jsonutils.loads(annotation)
        obj = obj_lbaas.LBaaSServiceSpec.obj_from_primitive(obj_dict)
        LOG.debug("Got LBaaSServiceSpec from annotation: %r", obj)
        return obj

    def _set_lbaas_state(self, endpoints, lbaas_state):
        # TODO(ivc): extract annotation interactions
        if lbaas_state is None:
            LOG.debug("Removing LBaaSState annotation: %r", lbaas_state)
            annotation = None
        else:
            lbaas_state.obj_reset_changes(recursive=True)
            LOG.debug("Setting LBaaSState annotation: %r", lbaas_state)
            annotation = jsonutils.dumps(lbaas_state.obj_to_primitive(),
                                         sort_keys=True)
        k8s = clients.get_kubernetes_client()
        k8s.annotate(endpoints['metadata']['selfLink'],
                     {k_const.K8S_ANNOTATION_LBAAS_STATE: annotation},
                     resource_version=endpoints['metadata']['resourceVersion'])

    def _get_lbaas_state(self, endpoints):
        # TODO(ivc): same as '_set_lbaas_state'
        try:
            annotations = endpoints['metadata']['annotations']
            annotation = annotations[k_const.K8S_ANNOTATION_LBAAS_STATE]
        except KeyError:
            return None
        obj_dict = jsonutils.loads(annotation)
        obj = obj_lbaas.LBaaSState.obj_from_primitive(obj_dict)
        LOG.debug("Got LBaaSState from annotation: %r", obj)
        return obj
