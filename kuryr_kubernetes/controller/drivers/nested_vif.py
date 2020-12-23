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

import abc

from kuryr.lib import exceptions as kl_exc
from openstack import exceptions as os_exc
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import neutron_vif


CONF = oslo_cfg.CONF
LOG = logging.getLogger(__name__)


class NestedPodVIFDriver(neutron_vif.NeutronPodVIFDriver,
                         metaclass=abc.ABCMeta):
    """Skeletal handler driver for VIFs for Nested Pods."""

    def __init__(self):
        super().__init__()
        self.nodes_subnets_driver = base.NodesSubnetsDriver.get_instance()

    def _get_parent_port_by_host_ip(self, node_fixed_ip):
        os_net = clients.get_network_client()
        node_subnet_ids = self.nodes_subnets_driver.get_nodes_subnets(
            raise_on_empty=True)

        fixed_ips = ['ip_address=%s' % str(node_fixed_ip)]
        filters = {'fixed_ips': fixed_ips}
        tags = CONF.neutron_defaults.resource_tags
        if tags:
            filters['tags'] = tags
        try:
            ports = os_net.ports(**filters)
        except os_exc.SDKException:
            LOG.error("Parent VM port with fixed IPs %s not found!", fixed_ips)
            raise

        for port in ports:
            for fip in port.fixed_ips:
                if fip.get('subnet_id') in node_subnet_ids:
                    return port

        LOG.error("Neutron port for VM port with fixed IPs %s not found!",
                  fixed_ips)
        raise kl_exc.NoResourceException()

    def _get_parent_port(self, pod):
        try:
            # REVISIT(vikasc): Assumption is being made that hostIP is the IP
            #              of trunk interface on the node(vm).
            node_fixed_ip = pod['status']['hostIP']
        except KeyError:
            if pod['status']['conditions'][0]['type'] != "Initialized":
                LOG.debug("Pod condition type is not 'Initialized'")

            LOG.error("Failed to get parent vm port ip")
            raise
        return self._get_parent_port_by_host_ip(node_fixed_ip)
