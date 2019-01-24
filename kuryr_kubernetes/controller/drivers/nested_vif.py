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
import six

from kuryr.lib import exceptions as kl_exc
from neutronclient.common import exceptions as n_exc
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging

from kuryr_kubernetes.controller.drivers import neutron_vif


LOG = logging.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class NestedPodVIFDriver(neutron_vif.NeutronPodVIFDriver):
    """Skeletal handler driver for VIFs for Nested Pods."""

    def _get_parent_port_by_host_ip(self, neutron, node_fixed_ip):
        node_subnet_id = oslo_cfg.CONF.pod_vif_nested.worker_nodes_subnet
        if not node_subnet_id:
            raise oslo_cfg.RequiredOptError(
                'worker_nodes_subnet', oslo_cfg.OptGroup('pod_vif_nested'))

        try:
            fixed_ips = ['subnet_id=%s' % str(node_subnet_id),
                         'ip_address=%s' % str(node_fixed_ip)]
            ports = neutron.list_ports(fixed_ips=fixed_ips)
        except n_exc.NeutronClientException:
            LOG.error("Parent vm port with fixed ips %s not found!",
                      fixed_ips)
            raise

        if ports['ports']:
            return ports['ports'][0]
        else:
            LOG.error("Neutron port for vm port with fixed ips %s"
                      " not found!", fixed_ips)
            raise kl_exc.NoResourceException

    def _get_parent_port(self, neutron, pod):
        try:
            # REVISIT(vikasc): Assumption is being made that hostIP is the IP
            #              of trunk interface on the node(vm).
            node_fixed_ip = pod['status']['hostIP']
        except KeyError:
            if pod['status']['conditions'][0]['type'] != "Initialized":
                LOG.debug("Pod condition type is not 'Initialized'")

            LOG.error("Failed to get parent vm port ip")
            raise
        return self._get_parent_port_by_host_ip(neutron, node_fixed_ip)
