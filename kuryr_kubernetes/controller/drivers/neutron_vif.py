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

from kuryr.lib import constants as kl_const
from openstack import exceptions as os_exc
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import os_vif_util as ovu


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class NeutronPodVIFDriver(base.PodVIFDriver):
    """Manages normal Neutron ports to provide VIFs for Kubernetes Pods."""

    def __init__(self):
        super(NeutronPodVIFDriver, self).__init__()

        self._tag_on_creation = utils.check_tag_on_creation()
        if self._tag_on_creation:
            LOG.info('Neutron supports tagging during bulk port creation.')
        else:
            LOG.warning('Neutron does not support tagging during bulk '
                        'port creation. Kuryr will tag resources after '
                        'port creation.')

    def request_vif(self, pod, project_id, subnets, security_groups):
        os_net = clients.get_network_client()

        rq = self._get_port_request(pod, project_id, subnets, security_groups)
        port = os_net.create_port(**rq)

        self._check_port_binding([port])
        if not self._tag_on_creation:
            utils.tag_neutron_resources([port])
        return ovu.neutron_to_osvif_vif(port.binding_vif_type, port, subnets)

    def request_vifs(self, pod, project_id, subnets, security_groups,
                     num_ports, semaphore):
        os_net = clients.get_network_client()

        rq = self._get_port_request(pod, project_id, subnets, security_groups,
                                    unbound=True)

        bulk_port_rq = [rq] * num_ports
        # restrict amount of create Ports in bulk that might be running
        # in parallel.
        with semaphore:
            try:
                ports = list(os_net.create_ports(bulk_port_rq))
            except os_exc.SDKException:
                LOG.exception("Error creating bulk ports: %s", bulk_port_rq)
                raise

        vif_plugin = ports[0].binding_vif_type

        # NOTE(ltomasbo): Due to the bug (1696051) on neutron bulk port
        # creation request returning the port objects without binding
        # information, an additional port show is performed to get the binding
        # information
        if vif_plugin == 'unbound':
            port_info = os_net.get_port(ports[0].id)
            vif_plugin = port_info.binding_vif_type

        self._check_port_binding(ports)
        if not self._tag_on_creation:
            utils.tag_neutron_resources(ports)
        vifs = []
        for port in ports:
            vif = ovu.neutron_to_osvif_vif(vif_plugin, port, subnets)
            vifs.append(vif)
        return vifs

    def release_vif(self, pod, vif, project_id=None):
        clients.get_network_client().delete_port(vif.id)

    def activate_vif(self, vif, **kwargs):
        if vif.active:
            return

        os_net = clients.get_network_client()
        try:
            port = os_net.get_port(vif.id)
        except os_exc.SDKException:
            LOG.debug("Unable to obtain port information, retrying.")
            raise k_exc.ResourceNotReady(vif)

        if port['status'] != kl_const.PORT_STATUS_ACTIVE:
            raise k_exc.PortNotReady(vif.id, port['status'])

        vif.active = True

    def update_vif_sgs(self, pod, security_groups):
        os_net = clients.get_network_client()
        kp = utils.get_kuryrport(pod)
        vifs = utils.get_vifs(kp)
        if vifs:
            # NOTE(ltomasbo): It just updates the default_vif security group
            port_id = vifs[constants.DEFAULT_IFNAME].id
            os_net.update_port(port_id, security_groups=list(security_groups))

    def _get_port_request(self, pod, project_id, subnets, security_groups,
                          unbound=False):
        port_req_body = {'project_id': project_id,
                         'network_id': utils.get_network_id(subnets),
                         'fixed_ips': ovu.osvif_to_neutron_fixed_ips(subnets),
                         'device_owner': kl_const.DEVICE_OWNER,
                         'admin_state_up': True,
                         'binding_host_id': utils.get_host_id(pod)}

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

        if self._tag_on_creation:
            tags = CONF.neutron_defaults.resource_tags
            if tags:
                port_req_body['tags'] = tags

        return port_req_body

    def _check_port_binding(self, ports):
        if ports[0].binding_vif_type == "binding_failed":
            for port in ports:
                clients.get_network_client().delete_port(port.id)
            LOG.error("Binding failed error for ports: %s."
                      " Please check Neutron for errors.", ports)
            raise k_exc.ResourceNotReady(ports)
