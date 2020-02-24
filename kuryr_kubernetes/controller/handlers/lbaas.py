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


class ServiceHandler(k8s_base.ResourceEventHandler):
    """ServiceHandler handles K8s Service events.

    ServiceHandler handles K8s Service events and updates related Endpoints
    with LBaaSServiceSpec when necessary.
    """

    OBJECT_KIND = k_const.K8S_OBJ_SERVICE
    OBJECT_WATCH_PATH = "%s/%s" % (k_const.K8S_API_BASE, "services")

    def __init__(self):
        super(ServiceHandler, self).__init__()
        self._drv_project = drv_base.ServiceProjectDriver.get_instance()
        self._drv_subnets = drv_base.ServiceSubnetsDriver.get_instance()
        self._drv_sg = drv_base.ServiceSecurityGroupsDriver.get_instance()

    def on_present(self, service):
        if self._should_ignore(service):
            LOG.debug("Skipping Kubernetes service %s of an unsupported kind "
                      "or without a selector as Kubernetes does not create "
                      "an endpoint object for it.",
                      service['metadata']['name'])
            return

        k8s = clients.get_kubernetes_client()
        loadbalancer_crd = k8s.get_loadbalancer_crd(service)
        try:
            self._patch_service_finalizer(service)
        except k_exc.K8sClientException as ex:
            LOG.exception("Failed to set service finalizer: %s", ex)
            raise

        if loadbalancer_crd is None:
            loadbalancer_crd = self.create_crd_spec(service)
        elif self._has_lbaas_spec_changes(service, loadbalancer_crd):
            loadbalancer_crd = self._update_crd_spec(loadbalancer_crd, service)

    def _is_supported_type(self, service):
        spec = service['spec']
        return spec.get('type') in SUPPORTED_SERVICE_TYPES

    def _get_service_ip(self, service):
        if self._is_supported_type(service):
            return service['spec'].get('clusterIP')
        return None

    def _should_ignore(self, service):
        return (not(self._has_clusterip(service)) or
                not(self._is_supported_type(service)))

    def _patch_service_finalizer(self, service):
        k8s = clients.get_kubernetes_client()
        k8s.add_finalizer(service, k_const.SERVICE_FINALIZER)

    def on_finalize(self, service):
        k8s = clients.get_kubernetes_client()

        svc_name = service['metadata']['name']
        svc_namespace = service['metadata']['namespace']

        klb_crd_path = (f"{k_const.K8S_API_CRD_NAMESPACES}/"
                        f"{svc_namespace}/kuryrloadbalancers/{svc_name}")
        k8s.delete(klb_crd_path)

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

    def create_crd_spec(self, service):
        svc_name = service['metadata']['name']
        svc_namespace = service['metadata']['namespace']
        kubernetes = clients.get_kubernetes_client()
        svc_ip = self._get_service_ip(service)
        spec_lb_ip = service['spec'].get('loadBalancerIP')
        ports = service['spec'].get('ports')
        for port in ports:
            if type(port['targetPort']) == int:
                port['targetPort'] = str(port['targetPort'])
        project_id = self._drv_project.get_project(service)
        sg_ids = self._drv_sg.get_security_groups(service, project_id)
        subnet_id = self._get_subnet_id(service, project_id, svc_ip)
        spec_type = service['spec'].get('type')
        loadbalancer_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': svc_name,
                'finalizers': [k_const.KURYRLB_FINALIZER],
                },
            'spec': {
                'ip': svc_ip,
                'ports': ports,
                'project_id': project_id,
                'security_groups_ids': sg_ids,
                'subnet_id': subnet_id,
                'type': spec_type
                },
            'status': {
                }
            }

        if spec_lb_ip is not None:
            loadbalancer_crd['spec']['lb_ip'] = spec_lb_ip

        try:
            kubernetes.post('{}/{}/kuryrloadbalancers'.format(
                k_const.K8S_API_CRD_NAMESPACES, svc_namespace),
                loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(svc_name)
        except k_exc.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating "
                          "kuryrloadbalancer CRD. %s"
                          % k_exc.K8sClientException)
            raise
        return loadbalancer_crd

    def _update_crd_spec(self, loadbalancer_crd, service):
        svc_ip = self._get_service_ip(service)
        ports = service['spec'].get('ports')
        for port in ports:
            if type(port['targetPort']) == int:
                port['targetPort'] = str(port['targetPort'])
        project_id = self._drv_project.get_project(service)
        sg_ids = self._drv_sg.get_security_groups(service, project_id)
        subnet_id = self._get_subnet_id(service, project_id, svc_ip)
        spec_type = service['spec'].get('type')
        kubernetes = clients.get_kubernetes_client()

        patch = {
            'spec': {
                'ip': svc_ip,
                'ports': ports,
                'project_id': project_id,
                'security_groups_ids': sg_ids,
                'subnet_id': subnet_id,
                'type': spec_type
                }
            }

        LOG.debug('Patching KuryrLoadBalancer CRD %s', loadbalancer_crd)
        try:
            kubernetes.patch_crd('spec', loadbalancer_crd['metadata'][
                'selfLink'], patch['spec'])
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrLoadBalancer CRD not found %s', loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(loadbalancer_crd)
        except k_exc.K8sClientException:
            LOG.exception('Error updating kuryrnet CRD %s', loadbalancer_crd)
            raise
        return loadbalancer_crd

    def _has_lbaas_spec_changes(self, service, loadbalancer_crd):
        return (self._has_ip_changes(service, loadbalancer_crd) or
                utils.has_port_changes(service, loadbalancer_crd))

    def _has_ip_changes(self, service, loadbalancer_crd):
        link = service['metadata']['selfLink']
        svc_ip = self._get_service_ip(service)

        if loadbalancer_crd['spec'].get('ip') is None:
            if svc_ip is None:
                return False
            return True

        elif str(loadbalancer_crd['spec'].get('ip')) != svc_ip:
            LOG.debug("LBaaS spec IP %(spec_ip)s != %(svc_ip)s for %(link)s"
                      % {'spec_ip': loadbalancer_crd['spec']['ip'],
                         'svc_ip': svc_ip,
                         'link': link})
            return True

        return False

    def _generate_lbaas_port_specs(self, service):
        return [obj_lbaas.LBaaSPortSpec(**port)
                for port in utils.get_service_ports(service)]


class EndpointsHandler(k8s_base.ResourceEventHandler):
    """EndpointsHandler handles K8s Endpoints events.

    EndpointsHandler handles K8s Endpoints events and tracks changes in
    LBaaSServiceSpec to update Neutron LBaaS accordingly and to reflect its'
    actual state in LBaaSState.
    """

    OBJECT_KIND = k_const.K8S_OBJ_ENDPOINTS
    OBJECT_WATCH_PATH = "%s/%s" % (k_const.K8S_API_BASE, "endpoints")

    def __init__(self):
        super(EndpointsHandler, self).__init__()
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
        k8s = clients.get_kubernetes_client()
        loadbalancer_crd = k8s.get_loadbalancer_crd(endpoints)

        if not self._has_pods(endpoints):
            LOG.debug("Ignoring Kubernetes endpoints %s",
                      endpoints['metadata']['name'])
            return

        if loadbalancer_crd is None:
            loadbalancer_crd = self._create_crd_spec(endpoints)
        else:
            loadbalancer_crd = self._update_crd_spec(loadbalancer_crd,
                                                     endpoints)

    def _has_lbaas_spec_changes(self, endpoints, loadbalancer_crd):
        return (self._has_ip_changes(endpoints, loadbalancer_crd) or
                utils.has_port_changes(endpoints, loadbalancer_crd))

    def _has_ip_changes(self, endpoints, loadbalancer_crd):
        link = endpoints['metadata']['selfLink']
        endpoint_ip = endpoints['subsets']['addresses'].get('ip')
        endpoint_crd_ip = loadbalancer_crd['spec'].get('ip')

        if endpoint_crd_ip != endpoint_ip:
            LOG.debug("LBaaS spec IP %(endpoint_crd_ip)s !="
                      " %(endpoint_ip)s for %(link)s"
                      % {'endpoint_crd_ip': endpoint_crd_ip,
                         'endpoint_ip': endpoint_ip,
                         'link': link})
            return True

        return False

    def _has_pods(self, endpoints):
        ep_subsets = endpoints.get('subsets', [])
        if not ep_subsets:
            return False
        return any(True
                   for subset in ep_subsets
                   for address in subset.get('addresses', [])
                   if address.get('targetRef', {}).get('kind') == 'Pod')

    def _create_crd_spec(self, endpoints):
        endpoints_name = endpoints['metadata']['name']
        namespace = endpoints['metadata']['namespace']
        kubernetes = clients.get_kubernetes_client()

        subsets = endpoints.get('subsets', [])

        loadbalancer_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': endpoints_name,
                'finalizers': [k_const.KURYRLB_FINALIZER]
                },
            'spec': {
                'subsets': subsets
                },
            'status': {
                }
            }

        try:
            kubernetes.post('{}/{}/kuryrloadbalancers'.format(
                k_const.K8S_API_CRD_NAMESPACES, namespace), loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(loadbalancer_crd)
        except k_exc.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating "
                          "kuryrloadbalancer CRD. %s" %
                          k_exc.K8sClientException)
            raise
        return loadbalancer_crd

    def _update_crd_spec(self, loadbalancer_crd, endpoints):
        kubernetes = clients.get_kubernetes_client()
        subsets = endpoints.get('subsets')
        lbaas_update_crd = {
            'subsets': subsets
            }
        try:
            kubernetes.patch_crd('spec', loadbalancer_crd['metadata'][
                'selfLink'], lbaas_update_crd)
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrLoadbalancer CRD not found %s', loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(loadbalancer_crd)
        except k_exc.K8sClientException:
            LOG.exception('Error updating KuryrLoadbalancer CRD %s',
                          loadbalancer_crd)
            raise

        return loadbalancer_crd

    def _get_service_link(self, endpoints):
        ep_link = endpoints['metadata']['selfLink']
        link_parts = ep_link.split('/')

        if link_parts[-2] != 'endpoints':
            raise k_exc.IntegrityError(_(
                "Unsupported endpoints link: %(link)s") % {
                    'link': ep_link})
        link_parts[-2] = 'services'
        return "/".join(link_parts)
