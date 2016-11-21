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

from kuryr.lib._i18n import _LE
from kuryr.lib import constants as kl_const
from neutronclient.common import exceptions as n_exc
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import os_vif_util as ovu


LOG = logging.getLogger(__name__)


class GenericPodVIFDriver(base.PodVIFDriver):
    """Manages normal Neutron ports to provide VIFs for Kubernetes Pods."""

    def request_vif(self, pod, project_id, subnets, security_groups):
        neutron = clients.get_neutron_client()

        rq = self._get_port_request(pod, project_id, subnets, security_groups)
        port = neutron.create_port(rq).get('port')
        vif_plugin = self._get_vif_plugin(port)

        return ovu.neutron_to_osvif_vif(vif_plugin, port, subnets)

    def release_vif(self, pod, vif):
        neutron = clients.get_neutron_client()

        try:
            neutron.delete_port(vif.id)
        except n_exc.PortNotFoundClient:
            LOG.debug('Unable to release port %s as it no longer exists.',
                      vif.id)

    def activate_vif(self, pod, vif):
        if vif.active:
            return

        neutron = clients.get_neutron_client()
        port = neutron.show_port(vif.id).get('port')

        if port['status'] != kl_const.PORT_STATUS_ACTIVE:
            raise k_exc.ResourceNotReady(vif)

        vif.active = True

    def _get_port_request(self, pod, project_id, subnets, security_groups):
        port_req_body = {'project_id': project_id,
                         'name': self._get_port_name(pod),
                         'network_id': self._get_network_id(subnets),
                         'fixed_ips': ovu.osvif_to_neutron_fixed_ips(subnets),
                         'device_owner': kl_const.DEVICE_OWNER,
                         'device_id': self._get_device_id(pod),
                         'admin_state_up': True,
                         'binding:host_id': self._get_host_id(pod)}

        if security_groups:
            port_req_body['security_groups'] = security_groups

        return {'port': port_req_body}

    def _get_vif_plugin(self, port):
        return port.get('binding:vif_type')

    def _get_network_id(self, subnets):
        ids = ovu.osvif_to_neutron_network_ids(subnets)

        if len(ids) != 1:
            raise k_exc.IntegrityError(_LE(
                "Subnet mapping %(subnets)s is not valid: %(num_networks)s "
                "unique networks found") % {
                'subnets': subnets,
                'num_networks': len(ids)})

        return ids[0]

    def _get_port_name(self, pod):
        return pod['metadata']['name']

    def _get_device_id(self, pod):
        return pod['metadata']['uid']

    def _get_host_id(self, pod):
        return pod['spec']['nodeName']
