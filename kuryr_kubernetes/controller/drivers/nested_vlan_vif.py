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
from time import sleep

from kuryr.lib._i18n import _
from kuryr.lib import constants as kl_const
from kuryr.lib import segmentation_type_drivers as seg_driver
from neutronclient.common import exceptions as n_exc
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants as const
from kuryr_kubernetes.controller.drivers import generic_vif
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import os_vif_util as ovu


LOG = logging.getLogger(__name__)

DEFAULT_MAX_RETRY_COUNT = 3
DEFAULT_RETRY_INTERVAL = 1


# Moved out from neutron_defaults group
nested_vif_driver_opts = [
    oslo_cfg.StrOpt('worker_nodes_subnet',
        help=_("Neutron subnet ID for k8s worker node vms.")),
]


oslo_cfg.CONF.register_opts(nested_vif_driver_opts, "pod_vif_nested")


class NestedVlanPodVIFDriver(generic_vif.GenericPodVIFDriver):
    """Manages ports for nested-containers to provide VIFs."""

    def request_vif(self, pod, project_id, subnets, security_groups):
        neutron = clients.get_neutron_client()
        parent_port = self._get_parent_port(neutron, pod)
        trunk_id = self._get_trunk_id(parent_port)

        rq = self._get_port_request(pod, project_id, subnets, security_groups)
        port = neutron.create_port(rq).get('port')

        vlan_id = self._add_subport(neutron, trunk_id, port['id'])

        vif_plugin = const.K8S_OS_VIF_NOOP_PLUGIN
        vif = ovu.neutron_to_osvif_vif(vif_plugin, port, subnets)
        vif.vlan_id = vlan_id
        return vif

    def release_vif(self, pod, vif):
        neutron = clients.get_neutron_client()
        parent_port = self._get_parent_port(neutron, pod)
        trunk_id = self._get_trunk_id(parent_port)
        self._remove_subport(neutron, trunk_id, vif.id)
        self._release_vlan_id(vif.vlan_id)
        try:
            neutron.delete_port(vif.id)
        except n_exc.PortNotFoundClient:
            LOG.debug('Unable to release port %s as it no longer exists.',
                      vif.id)

    def _get_port_request(self, pod, project_id, subnets, security_groups):
        port_req_body = {'project_id': project_id,
                         'name': self._get_port_name(pod),
                         'network_id': self._get_network_id(subnets),
                         'fixed_ips': ovu.osvif_to_neutron_fixed_ips(subnets),
                         'device_owner': kl_const.DEVICE_OWNER,
                         'admin_state_up': True}

        if security_groups:
            port_req_body['security_groups'] = security_groups

        return {'port': port_req_body}

    def _get_trunk_id(self, port):
        try:
            return port['trunk_details']['trunk_id']
        except KeyError:
            LOG.error("Neutron port is missing trunk details. "
                      "Please ensure that k8s node port is associated "
                      "with a Neutron vlan trunk")
            raise k_exc.K8sNodeTrunkPortFailure

    def _get_parent_port(self, neutron, pod):
        node_subnet_id = oslo_cfg.CONF.pod_vif_nested.worker_nodes_subnet
        if not node_subnet_id:
            raise oslo_cfg.RequiredOptError('worker_nodes_subnet',
                    'pod_vif_nested')

        try:
            # REVISIT(vikasc): Assumption is being made that hostIP is the IP
            #		       of trunk interface on the node(vm).
            node_fixed_ip = pod['status']['hostIP']
        except KeyError:
            if pod['status']['conditions'][0]['type'] != "Initialized":
                LOG.debug("Pod condition type is not 'Initialized'")

            LOG.error("Failed to get parent vm port ip")
            raise

        try:
            fixed_ips = ['subnet_id=%s' % str(node_subnet_id),
                         'ip_address=%s' % str(node_fixed_ip)]
            ports = neutron.list_ports(fixed_ips=fixed_ips)
        except n_exc.NeutronClientException as ex:
            LOG.error("Parent vm port with fixed ips %s not found!",
                      fixed_ips)
            raise ex

        if ports['ports']:
            return ports['ports'][0]
        else:
            LOG.error("Neutron port for vm port with fixed ips %s"
                      " not found!", fixed_ips)
            raise k_exc.K8sNodeTrunkPortFailure

    def _add_subport(self, neutron, trunk_id, subport):
        """Adds subport port to Neutron trunk

        This method gets vlanid allocated from kuryr segmentation driver.
        In active/active HA type deployment, possibility of vlanid conflict
        is there. In such a case, vlanid will be requested again and subport
        addition is re-tried. This is tried DEFAULT_MAX_RETRY_COUNT times in
        case of vlanid conflict.
        """
        # TODO(vikasc): Better approach for retrying in case of
        # vlan-id conflict.
        retry_count = 1
        while True:
            try:
                vlan_id = self._get_vlan_id(trunk_id)
            except n_exc.NeutronClientException as ex:
                LOG.error("Getting VlanID for subport on "
                          "trunk %s failed!!", trunk_id)
                raise ex
            subport = [{'segmentation_id': vlan_id,
                        'port_id': subport,
                       'segmentation_type': 'vlan'}]
            try:
                neutron.trunk_add_subports(trunk_id,
                                           {'sub_ports': subport})
            except n_exc.Conflict as ex:
                if retry_count < DEFAULT_MAX_RETRY_COUNT:
                    LOG.error("vlanid already in use on trunk, "
                              "%s. Retrying...", trunk_id)
                    retry_count += 1
                    sleep(DEFAULT_RETRY_INTERVAL)
                    continue
                else:
                    LOG.error(
                        "MAX retry count reached. Failed to add subport")
                    raise ex

            except n_exc.NeutronClientException as ex:
                LOG.error("Error happened during subport"
                          "addition to trunk, %s", trunk_id)
                raise ex
            return vlan_id

    def _remove_subport(self, neutron, trunk_id, subport_id):
        subport_id = [{'port_id': subport_id}]
        try:
            neutron.trunk_remove_subports(trunk_id,
                                       {'sub_ports': subport_id})
        except n_exc.NeutronClientException as ex:
            LOG.error(
                "Error happened during subport removal from "
                "trunk, %s", trunk_id)
            raise ex

    def _get_vlan_id(self, trunk_id):
        vlan_ids = self._get_in_use_vlan_ids_set(trunk_id)
        return seg_driver.allocate_segmentation_id(vlan_ids)

    def _release_vlan_id(self, id):
        return seg_driver.release_segmentation_id(id)

    def _get_in_use_vlan_ids_set(self, trunk_id):
        vlan_ids = set()
        neutron = clients.get_neutron_client()
        trunk = neutron.show_trunk(trunk_id)
        for port in trunk['trunk']['sub_ports']:
            vlan_ids.add(port['segmentation_id'])

        return vlan_ids
