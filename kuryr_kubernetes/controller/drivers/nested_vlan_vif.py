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

from kuryr.lib import constants as kl_const
from kuryr.lib import exceptions as kl_exc
from kuryr.lib import segmentation_type_drivers as seg_driver
from neutronclient.common import exceptions as n_exc
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import nested_vif
from kuryr_kubernetes.controller.drivers import utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import os_vif_util as ovu


LOG = logging.getLogger(__name__)

DEFAULT_MAX_RETRY_COUNT = 3
DEFAULT_RETRY_INTERVAL = 1


class NestedVlanPodVIFDriver(nested_vif.NestedPodVIFDriver):
    """Manages ports for nested-containers using VLANs to provide VIFs."""

    def request_vif(self, pod, project_id, subnets, security_groups):
        neutron = clients.get_neutron_client()
        parent_port = self._get_parent_port(neutron, pod)
        trunk_id = self._get_trunk_id(parent_port)

        rq = self._get_port_request(pod, project_id, subnets, security_groups)
        port = neutron.create_port(rq).get('port')
        utils.tag_neutron_resources('ports', [port['id']])
        vlan_id = self._add_subport(neutron, trunk_id, port['id'])

        return ovu.neutron_to_osvif_vif_nested_vlan(port, subnets, vlan_id)

    def request_vifs(self, pod, project_id, subnets, security_groups,
                     num_ports, trunk_ip=None):
        """This method creates subports and returns a list with their vifs.

        It creates up to num_ports subports and attaches them to the trunk
        port.

        If not enough vlan ids are available for all the subports to create,
        it creates as much as available vlan ids.

        Note the neutron trunk_add_subports is an atomic operation that will
        either attach all or none of the subports. Therefore, if there is a
        vlan id collision, all the created ports will be deleted and the
        exception is raised.
        """
        neutron = clients.get_neutron_client()
        if trunk_ip:
            parent_port = self._get_parent_port_by_host_ip(neutron, trunk_ip)
        else:
            parent_port = self._get_parent_port(neutron, pod)
        trunk_id = self._get_trunk_id(parent_port)

        port_rq, subports_info = self._create_subports_info(
            pod, project_id, subnets, security_groups,
            trunk_id, num_ports, unbound=True)

        if not subports_info:
            LOG.error("There are no vlan ids available to create subports")
            return []

        bulk_port_rq = {'ports': [port_rq] * len(subports_info)}
        try:
            ports = neutron.create_port(bulk_port_rq).get('ports')
        except n_exc.NeutronClientException:
            LOG.exception("Error creating bulk ports: %s", bulk_port_rq)
            raise
        utils.tag_neutron_resources('ports', [port['id'] for port in ports])

        for index, port in enumerate(ports):
            subports_info[index]['port_id'] = port['id']

        try:
            try:
                neutron.trunk_add_subports(trunk_id,
                                           {'sub_ports': subports_info})
            except n_exc.Conflict:
                LOG.error("vlan ids already in use on trunk")
                for port in ports:
                    neutron.delete_port(port['id'])
                return []
        except n_exc.NeutronClientException:
            LOG.exception("Error happened during subport addition to trunk")
            for port in ports:
                neutron.delete_port(port['id'])
            return []

        vifs = []
        for index, port in enumerate(ports):
            vlan_id = subports_info[index]['segmentation_id']
            vif = ovu.neutron_to_osvif_vif_nested_vlan(port, subnets, vlan_id)
            vifs.append(vif)
        return vifs

    def release_vif(self, pod, vif, project_id=None, security_groups=None):
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

    def _get_port_request(self, pod, project_id, subnets, security_groups,
                          unbound=False):
        port_req_body = {'project_id': project_id,
                         'network_id': utils.get_network_id(subnets),
                         'fixed_ips': ovu.osvif_to_neutron_fixed_ips(subnets),
                         'device_owner': kl_const.DEVICE_OWNER,
                         'admin_state_up': True}

        # only set name if port_debug is enabled
        if config.CONF.kubernetes.port_debug:
            if unbound:
                port_req_body['name'] = constants.KURYR_PORT_NAME
            else:
                port_req_body['name'] = utils.get_port_name(pod)

        if security_groups:
            port_req_body['security_groups'] = security_groups

        return {'port': port_req_body}

    def _create_subports_info(self, pod, project_id, subnets,
                              security_groups, trunk_id, num_ports,
                              unbound=False):
        subports_info = []

        in_use_vlan_ids = self._get_in_use_vlan_ids_set(trunk_id)
        port_rq = self._get_port_request(pod, project_id, subnets,
                                         security_groups, unbound)['port']
        for i in range(num_ports):
            try:
                vlan_id = seg_driver.allocate_segmentation_id(in_use_vlan_ids)
            except kl_exc.SegmentationIdAllocationFailure:
                LOG.warning("There is not enough vlan ids available to "
                            "create a batch of %d subports.", num_ports)
                break
            in_use_vlan_ids.add(vlan_id)

            subports_info.append({'segmentation_id': vlan_id,
                                  'port_id': '',
                                  'segmentation_type': 'vlan'})
        return port_rq, subports_info

    def _get_trunk_id(self, port):
        try:
            return port['trunk_details']['trunk_id']
        except KeyError:
            LOG.error("Neutron port is missing trunk details. "
                      "Please ensure that k8s node port is associated "
                      "with a Neutron vlan trunk")
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
            except n_exc.NeutronClientException:
                LOG.error("Getting VlanID for subport on "
                          "trunk %s failed!!", trunk_id)
                raise
            subport = [{'segmentation_id': vlan_id,
                        'port_id': subport,
                       'segmentation_type': 'vlan'}]
            try:
                neutron.trunk_add_subports(trunk_id,
                                           {'sub_ports': subport})
            except n_exc.Conflict:
                if retry_count < DEFAULT_MAX_RETRY_COUNT:
                    LOG.error("vlanid already in use on trunk, "
                              "%s. Retrying...", trunk_id)
                    retry_count += 1
                    sleep(DEFAULT_RETRY_INTERVAL)
                    continue
                else:
                    LOG.error(
                        "MAX retry count reached. Failed to add subport")
                    raise

            except n_exc.NeutronClientException:
                LOG.exception("Error happened during subport "
                              "addition to trunk %s", trunk_id)
                raise
            return vlan_id

    def _remove_subports(self, neutron, trunk_id, subports_id):
        subports_body = []
        for subport_id in set(subports_id):
            subports_body.append({'port_id': subport_id})
        try:
            neutron.trunk_remove_subports(trunk_id,
                                          {'sub_ports': subports_body})
        except n_exc.NeutronClientException:
            LOG.exception("Error happened during subport removal from "
                          "trunk %s", trunk_id)
            raise

    def _remove_subport(self, neutron, trunk_id, subport_id):
        self._remove_subports(neutron, trunk_id, [subport_id])

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
