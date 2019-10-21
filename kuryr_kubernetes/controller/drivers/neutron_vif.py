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

from keystoneauth1 import exceptions as key_exc
from kuryr.lib import constants as kl_const
from neutronclient.common import exceptions as n_exc
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import os_vif_util as ovu


LOG = logging.getLogger(__name__)


class NeutronPodVIFDriver(base.PodVIFDriver):
    """Manages normal Neutron ports to provide VIFs for Kubernetes Pods."""

    def request_vif(self, pod, project_id, subnets, security_groups):
        neutron = clients.get_neutron_client()

        rq = self._get_port_request(pod, project_id, subnets, security_groups)
        port = neutron.create_port(rq).get('port')
        utils.tag_neutron_resources('ports', [port['id']])
        vif_plugin = self._get_vif_plugin(port)

        return ovu.neutron_to_osvif_vif(vif_plugin, port, subnets)

    def request_vifs(self, pod, project_id, subnets, security_groups,
                     num_ports):
        neutron = clients.get_neutron_client()

        rq = self._get_port_request(pod, project_id, subnets, security_groups,
                                    unbound=True)

        bulk_port_rq = {'ports': [rq] * num_ports}
        try:
            ports = neutron.create_port(bulk_port_rq).get('ports')
        except n_exc.NeutronClientException:
            LOG.exception("Error creating bulk ports: %s", bulk_port_rq)
            raise
        utils.tag_neutron_resources('ports', [port['id'] for port in ports])

        vif_plugin = self._get_vif_plugin(ports[0])

        # NOTE(ltomasbo): Due to the bug (1696051) on neutron bulk port
        # creation request returning the port objects without binding
        # information, an additional port show is performed to get the binding
        # information
        if vif_plugin == 'unbound':
            port_info = neutron.show_port(ports[0]['id']).get('port')
            vif_plugin = self._get_vif_plugin(port_info)

        vifs = []
        for port in ports:
            vif = ovu.neutron_to_osvif_vif(vif_plugin, port, subnets)
            vifs.append(vif)
        return vifs

    def release_vif(self, pod, vif, project_id=None, security_groups=None):
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
        try:
            port = neutron.show_port(vif.id).get('port')
        except (key_exc.ConnectionError, n_exc.ConnectionFailed):
            LOG.debug("Unable to obtain port information, retrying.")
            raise k_exc.ResourceNotReady(vif)

        if port['status'] != kl_const.PORT_STATUS_ACTIVE:
            raise k_exc.ResourceNotReady(vif)

        vif.active = True

    def update_vif_sgs(self, pod, security_groups):
        neutron = clients.get_neutron_client()
        pod_state = utils.get_pod_state(pod)
        if pod_state:
            # NOTE(ltomasbo): It just updates the default_vif security group
            port_id = pod_state.vifs[constants.DEFAULT_IFNAME].id
            neutron.update_port(port_id,
                                {
                                    "port": {
                                        'security_groups': list(
                                            security_groups)
                                    }
                                })

    def _get_port_request(self, pod, project_id, subnets, security_groups,
                          unbound=False):
        port_req_body = {'project_id': project_id,
                         'network_id': utils.get_network_id(subnets),
                         'fixed_ips': ovu.osvif_to_neutron_fixed_ips(subnets),
                         'device_owner': kl_const.DEVICE_OWNER,
                         'admin_state_up': True,
                         'binding:host_id': utils.get_host_id(pod)}

        # if unbound argument is set to true, it means the port requested
        # should not be bound and not associated to the pod. Thus the port dict
        # is filled with a generic name (constants.KURYR_PORT_NAME) if
        # port_debug is enabled, and without device_id
        if unbound and config.CONF.kubernetes.port_debug:
            port_req_body['name'] = constants.KURYR_PORT_NAME
        else:
            # only set the name if port_debug is enabled
            if config.CONF.kubernetes.port_debug:
                port_req_body['name'] = utils.get_port_name(pod)
            port_req_body['device_id'] = utils.get_device_id(pod)

        if security_groups:
            port_req_body['security_groups'] = security_groups

        return {'port': port_req_body}

    def _get_vif_plugin(self, port):
        return port.get('binding:vif_type')
