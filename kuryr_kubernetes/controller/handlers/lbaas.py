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
import six

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes.objects import lbaas as obj_lbaas

LOG = logging.getLogger(__name__)


class LBaaSSpecHandler(k8s_base.ResourceEventHandler):
    """LBaaSSpecHandler handles K8s Service events.

    LBaaSSpecHandler handles K8s Service events and updates related Endpoints
    with LBaaSServiceSpec when necessary.
    """

    OBJECT_KIND = k_const.K8S_OBJ_SERVICE

    def __init__(self):
        self._drv_project = drv_base.ServiceProjectDriver.get_instance()
        self._drv_subnets = drv_base.ServiceSubnetsDriver.get_instance()
        self._drv_sg = drv_base.ServiceSecurityGroupsDriver.get_instance()

    def on_present(self, service):
        lbaas_spec = self._get_lbaas_spec(service)

        if self._has_lbaas_spec_changes(service, lbaas_spec):
            lbaas_spec = self._generate_lbaas_spec(service)
            self._set_lbaas_spec(service, lbaas_spec)

    def _get_service_ip(self, service):
        spec = service['spec']
        if spec.get('type') == 'ClusterIP':
            return spec.get('clusterIP')
        return None

    def _get_subnet_id(self, service, project_id, ip):
        subnets_mapping = self._drv_subnets.get_subnets(service, project_id)
        subnet_ids = {
            subnet_id
            for subnet_id, network in six.iteritems(subnets_mapping)
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

        return obj_lbaas.LBaaSServiceSpec(ip=ip,
                                          project_id=project_id,
                                          subnet_id=subnet_id,
                                          ports=ports,
                                          security_groups_ids=sg_ids)

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
