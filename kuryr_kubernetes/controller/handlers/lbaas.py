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

import netaddr

from kuryr.lib._i18n import _
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)
CONF = config.CONF

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
        self._drv_lbaas = drv_base.LBaaSDriver.get_instance()
        self.k8s = clients.get_kubernetes_client()

        self._lb_provider = None
        if self._drv_lbaas.providers_supported():
            self._lb_provider = 'amphora'
            config_provider = CONF.kubernetes.endpoints_driver_octavia_provider
            if config_provider != 'default':
                self._lb_provider = config_provider

    def _bump_network_policies(self, svc):
        if driver_utils.is_network_policy_enabled():
            driver_utils.bump_networkpolicies(svc['metadata']['namespace'])

    def on_present(self, service, *args, **kwargs):
        reason = self._should_ignore(service)
        if reason:
            reason %= utils.get_res_unique_name(service)
            LOG.debug(reason)
            self.k8s.add_event(service, 'KuryrServiceSkipped', reason)
            return

        loadbalancer_crd = self.k8s.get_loadbalancer_crd(service)
        try:
            if not self._patch_service_finalizer(service):
                return
        except k_exc.K8sClientException as ex:
            msg = (f'K8s API error when adding finalizer to Service '
                   f'{utils.get_res_unique_name(service)}')
            LOG.exception(msg)
            self.k8s.add_event(service, 'KuryrAddServiceFinalizerError',
                               f'{msg}: {ex}', 'Warning')
            raise

        if loadbalancer_crd is None:
            try:
                # Bump all the NPs in the namespace to force SG rules
                # recalculation.
                self._bump_network_policies(service)
                self.create_crd_spec(service)
            except k_exc.K8sNamespaceTerminating:
                LOG.debug('Namespace %s is being terminated, ignoring '
                          'Service %s in that namespace.',
                          service['metadata']['namespace'],
                          service['metadata']['name'])
                return
        elif self._has_lbaas_spec_changes(service, loadbalancer_crd):
            self._update_crd_spec(loadbalancer_crd, service)

    def _is_supported_type(self, service):
        spec = service['spec']
        return spec.get('type') in SUPPORTED_SERVICE_TYPES

    def _has_spec_annotation(self, service):
        return (k_const.K8S_ANNOTATION_LBAAS_SPEC in
                service['metadata'].get('annotations', {}))

    def _get_service_ip(self, service):
        if self._is_supported_type(service):
            return self._strip_funny_ip(service['spec'].get('clusterIP'))
        return None

    def _should_ignore(self, service):
        if not self._has_clusterip(service):
            return 'Skipping headless Service %s.'
        if not self._is_supported_type(service):
            return 'Skipping service %s of unsupported type.'
        if self._has_spec_annotation(service):
            return ('Skipping annotated service %s, waiting for it to be '
                    'converted to KuryrLoadBalancer object and annotation '
                    'removed.')
        if utils.is_kubernetes_default_resource(service):
            # Avoid to handle default Kubernetes service as requires https.
            return 'Skipping default service %s.'
        return None

    def _patch_service_finalizer(self, service):
        return self.k8s.add_finalizer(service, k_const.SERVICE_FINALIZER)

    def on_finalize(self, service, *args, **kwargs):
        klb_crd_path = utils.get_klb_crd_path(service)
        # Bump all the NPs in the namespace to force SG rules
        # recalculation.
        self._bump_network_policies(service)
        try:
            self.k8s.delete(klb_crd_path)
        except k_exc.K8sResourceNotFound:
            self.k8s.remove_finalizer(service, k_const.SERVICE_FINALIZER)

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
                    'link': utils.get_res_link(service),
                    'ip': ip,
                    'num': len(subnet_ids)})

        return subnet_ids.pop()

    def create_crd_spec(self, service):
        svc_name = service['metadata']['name']
        svc_namespace = service['metadata']['namespace']
        kubernetes = clients.get_kubernetes_client()
        spec = self._build_kuryrloadbalancer_spec(service)

        owner_reference = {
            'apiVersion': service['apiVersion'],
            'kind': service['kind'],
            'name': service['metadata']['name'],
            'uid': service['metadata']['uid'],
        }

        loadbalancer_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': svc_name,
                'finalizers': [k_const.KURYRLB_FINALIZER],
                'ownerReferences': [owner_reference],
            },
            'spec': spec,
            'status': {},
        }

        try:
            kubernetes.post('{}/{}/kuryrloadbalancers'.format(
                k_const.K8S_API_CRD_NAMESPACES, svc_namespace),
                loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(svc_name)
        except k_exc.K8sNamespaceTerminating:
            raise
        except k_exc.K8sClientException as e:
            LOG.exception("Exception when creating KuryrLoadBalancer CRD.")
            self.k8s.add_event(
                service, 'CreateKLBFailed',
                'Error when creating KuryrLoadBalancer object: %s' % e,
                'Warning')
            raise

    def _update_crd_spec(self, loadbalancer_crd, service):
        svc_name = service['metadata']['name']
        kubernetes = clients.get_kubernetes_client()
        spec = self._build_kuryrloadbalancer_spec(service)
        LOG.debug('Patching KuryrLoadBalancer CRD %s', loadbalancer_crd)
        try:
            kubernetes.patch_crd('spec', utils.get_res_link(loadbalancer_crd),
                                 spec)
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrLoadBalancer CRD not found %s', loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(svc_name)
        except k_exc.K8sClientException as e:
            LOG.exception('Error updating KuryrNetwork CRD %s',
                          loadbalancer_crd)
            self.k8s.add_event(
                service, 'UpdateKLBFailed',
                'Error when updating KuryrLoadBalancer object: %s' % e,
                'Warning')
            raise

    def _get_data_timeout_annotation(self, service):
        default_timeout_cli = CONF.octavia_defaults.timeout_client_data
        default_timeout_mem = CONF.octavia_defaults.timeout_member_data
        try:
            annotations = service['metadata']['annotations']
        except KeyError:
            return default_timeout_cli, default_timeout_mem
        try:
            timeout_cli = annotations[k_const.K8S_ANNOTATION_CLIENT_TIMEOUT]
            data_timeout_cli = int(timeout_cli)
        except KeyError:
            data_timeout_cli = default_timeout_cli
        try:
            timeout_mem = annotations[k_const.K8S_ANNOTATION_MEMBER_TIMEOUT]
            data_timeout_mem = int(timeout_mem)
        except KeyError:
            data_timeout_mem = default_timeout_mem
        return data_timeout_cli, data_timeout_mem

    def _build_kuryrloadbalancer_spec(self, service):
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
        spec = {
            'ip': svc_ip,
            'ports': ports,
            'project_id': project_id,
            'security_groups_ids': sg_ids,
            'subnet_id': subnet_id,
            'type': spec_type,
        }

        if self._lb_provider:
            spec['provider'] = self._lb_provider

        if spec_lb_ip is not None:
            spec['lb_ip'] = self._strip_funny_ip(spec_lb_ip)
        timeout_cli, timeout_mem = self._get_data_timeout_annotation(service)
        spec['timeout_client_data'] = timeout_cli
        spec['timeout_member_data'] = timeout_mem
        return spec

    def _has_lbaas_spec_changes(self, service, loadbalancer_crd):
        return (self._has_ip_changes(service, loadbalancer_crd) or
                utils.has_port_changes(service, loadbalancer_crd) or
                self._has_timeout_changes(service, loadbalancer_crd) or
                self._has_provider_changes(loadbalancer_crd))

    def _has_provider_changes(self, loadbalancer_crd):
        return (self._lb_provider and
                loadbalancer_crd['spec'].get('provider') != self._lb_provider)

    def _has_ip_changes(self, service, loadbalancer_crd):
        link = utils.get_res_link(service)
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

    def _has_timeout_changes(self, service, loadbalancer_crd):
        link = utils.get_res_link(service)
        cli_timeout, mem_timeout = self._get_data_timeout_annotation(service)

        for spec_value, current_value in [(loadbalancer_crd['spec'].get(
            'timeout_client_data'), cli_timeout), (loadbalancer_crd[
                'spec'].get('timeout_member_data'), mem_timeout)]:
            if not spec_value and not current_value:
                continue
            elif spec_value != current_value:
                LOG.debug("LBaaS spec listener timeout {} != {} for {}".format(
                    spec_value, current_value, link))
                return True

        return False

    def _strip_funny_ip(self, ip):
        return str(netaddr.IPAddress(ip, flags=netaddr.core.ZEROFILL))


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
        self.k8s = clients.get_kubernetes_client()

    def on_present(self, endpoints, *args, **kwargs):
        ep_name = endpoints['metadata']['name']
        ep_namespace = endpoints['metadata']['namespace']

        loadbalancer_crd = self.k8s.get_loadbalancer_crd(endpoints)

        if (not (self._has_pods(endpoints) or (loadbalancer_crd and
                                               loadbalancer_crd.get('status')))
                or k_const.K8S_ANNOTATION_HEADLESS_SERVICE
                in endpoints['metadata'].get('labels', []) or
                utils.is_kubernetes_default_resource(endpoints)):
            LOG.debug("Ignoring Kubernetes endpoints %s",
                      endpoints['metadata']['name'])
            return

        if loadbalancer_crd is None:
            raise k_exc.KuryrLoadBalancerNotCreated(endpoints)
        else:
            try:
                self._update_crd_spec(loadbalancer_crd, endpoints)
            except k_exc.K8sNamespaceTerminating:
                LOG.debug('Namespace %s is being terminated, ignoring '
                          'Endpoints %s in that namespace.',
                          ep_namespace, ep_name)

    def on_deleted(self, endpoints, *args, **kwargs):
        self._remove_endpoints(endpoints)

    def _has_pods(self, endpoints):
        ep_subsets = endpoints.get('subsets', [])
        if not ep_subsets:
            return False
        return any(True
                   for subset in ep_subsets
                   if subset.get('addresses', []))

    def _convert_subsets_to_endpointslice(self, endpoints_obj):
        endpointslices = []
        endpoints = []
        subsets = endpoints_obj.get('subsets', [])
        for subset in subsets:
            addresses = subset.get('addresses', [])
            ports = subset.get('ports', [])
            for address in addresses:
                ip = address.get('ip')
                targetRef = address.get('targetRef')
                endpoint = {
                    'addresses': [ip],
                    'conditions': {
                        'ready': True
                    },
                }
                if targetRef:
                    endpoint['targetRef'] = targetRef
                endpoints.append(endpoint)
            endpointslices.append({
                'endpoints': endpoints,
                'ports': ports,
            })

        return endpointslices

    def _add_event(self, endpoints, reason, message, type_=None):
        """_add_event adds an event for the corresponding Service."""
        try:
            service = self.k8s.get(utils.get_service_link(endpoints))
        except k_exc.K8sClientException:
            LOG.debug('Error when fetching Service to add an event %s, '
                      'ignoring', utils.get_res_unique_name(endpoints))
            return
        kwargs = {'type_': type_} if type_ else {}
        self.k8s.add_event(service, reason, message, **kwargs)

    def _update_crd_spec(self, loadbalancer_crd, endpoints):
        # TODO(maysams): Remove the conversion once we start handling
        # EndpointSlices.
        epslices = self._convert_subsets_to_endpointslice(endpoints)
        try:
            self.k8s.patch_crd('spec', utils.get_res_link(loadbalancer_crd),
                               {'endpointSlices': epslices})
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrLoadbalancer CRD not found %s', loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(loadbalancer_crd)
        except k_exc.K8sClientException as e:
            LOG.exception('Error updating KuryrLoadbalancer CRD %s',
                          loadbalancer_crd)
            self._add_event(
                endpoints, 'UpdateKLBFailed',
                'Error when updating KuryrLoadBalancer object: %s' % e,
                'Warning')
            raise

        return True

    def _remove_endpoints(self, endpoints):
        lb_name = utils.get_res_unique_name(endpoints)
        try:
            self.k8s.patch_crd('spec', utils.get_klb_crd_path(endpoints),
                               'endpointSlices', action='remove')
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrLoadBalancer CRD not found %s', lb_name)
        except k_exc.K8sUnprocessableEntity:
            # This happens when endpointSlices doesn't exist on the KLB,
            # safe to ignore, the resources is in the state we want already.
            pass
        except k_exc.K8sClientException as e:
            LOG.exception('Error updating KuryrLoadBalancer CRD %s', lb_name)
            self._add_event(
                endpoints, 'UpdateKLBFailed',
                'Error when updating KuryrLoadBalancer object: %s' % e,
                'Warning')
            raise
