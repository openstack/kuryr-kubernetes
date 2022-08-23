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

import threading

from openstack import exceptions as o_exc
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config as kuryr_config
from kuryr_kubernetes.controller.drivers import nested_vif
from kuryr_kubernetes.controller.drivers import utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import os_vif_util as ovu

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class NestedMacvlanPodVIFDriver(nested_vif.NestedPodVIFDriver):
    """Manages ports for nested-containers using MACVLAN to provide VIFs."""

    def __init__(self):
        self.lock = threading.Lock()

    def request_vif(self, pod, project_id, subnets, security_groups):
        os_net = clients.get_network_client()
        req = self._get_port_request(pod, project_id, subnets,
                                     security_groups)
        attempts = kuryr_config.CONF.pod_vif_nested.rev_update_attempts
        container_port = None
        while attempts > 0:
            vm_port = self._get_parent_port(pod)

            if not container_port:
                container_port = os_net.create_port(**req)
                self._check_port_binding([container_port])
            if not self._tag_on_creation:
                utils.tag_neutron_resources([container_port])

            container_mac = container_port.mac_address
            container_ips = frozenset(entry['ip_address'] for entry in
                                      container_port.fixed_ips)

            attempts = self._try_update_port(
                attempts, self._add_to_allowed_address_pairs, vm_port,
                container_ips, container_mac)

        return ovu.neutron_to_osvif_vif_nested_macvlan(container_port, subnets)

    def request_vifs(self, pod, project_id, subnets, security_groups,
                     num_ports):
        # TODO(mchiappe): provide an implementation
        raise NotImplementedError()

    def release_vif(self, pod, vif, project_id=None):
        os_net = clients.get_network_client()

        attempts = kuryr_config.CONF.pod_vif_nested.rev_update_attempts
        while attempts > 0:
            container_port = os_net.get_port(vif.id)

            container_mac = container_port.mac_address
            container_ips = frozenset(entry['ip_address'] for entry in
                                      container_port.fixed_ips)
            vm_port = self._get_parent_port(pod)
            attempts = self._try_update_port(
                attempts, self._remove_from_allowed_address_pairs,
                vm_port, container_ips, container_mac)

        try:
            os_net.delete_port(vif.id, ignore_missing=False)
        except o_exc.ResourceNotFound:
            LOG.warning("Unable to release port %s as it no longer exists.",
                        vif.id)

    def activate_vif(self, vif, **kwargs):
        # NOTE(mchiappe): there is no way to get feedback on the actual
        # interface creation or activation as no plugging can happen for this
        # interface type. However the status of the port is not relevant as
        # it is used for IPAM purposes only, thus just set 'active'
        # immediately to let the CNI driver make progress.
        vif.active = True

    def _add_to_allowed_address_pairs(self, port, ip_addresses,
                                      mac_address=None):
        if not ip_addresses:
            raise k_exc.IntegrityError(
                "Cannot add pair from the "
                "allowed_address_pairs of port %s: missing IP address" %
                port.id)

        mac = mac_address if mac_address else port.mac_address
        address_pairs = port.allowed_address_pairs

        # look for duplicates or near-matches
        for pair in address_pairs:
            if pair['ip_address'] in ip_addresses:
                if pair['mac_address'] is mac:
                    raise k_exc.AllowedAddressAlreadyPresent(
                        "Pair %s already "
                        "present in the 'allowed_address_pair' list. This is "
                        "due to a misconfiguration or a bug" % str(pair))
                else:
                    LOG.warning(
                        "A pair with IP %s but different MAC address "
                        "is already present in the 'allowed_address_pair'. "
                        "This could indicate a misconfiguration or a "
                        "bug", pair['ip_address'])

        for ip in ip_addresses:
            address_pairs.append({'ip_address': ip, 'mac_address': mac})

        self._update_port_address_pairs(
            port.id, address_pairs,
            revision_number=port.revision_number)

        LOG.debug("Added allowed_address_pair %s %s" %
                  (str(ip_addresses,), mac_address))

    def _remove_from_allowed_address_pairs(self, port, ip_addresses,
                                           mac_address=None):
        if not ip_addresses:
            raise k_exc.IntegrityError(
                "Cannot remove pair from the "
                "allowed_address_pairs of port %s: missing IP address" %
                port.id)

        mac = mac_address if mac_address else port.mac_address
        address_pairs = port.allowed_address_pairs
        updated = False

        for ip in ip_addresses:
            try:
                address_pairs.remove({'ip_address': ip, 'mac_address': mac})
                updated = True
            except ValueError:
                LOG.error("No {'ip_address': %s, 'mac_address': %s} pair "
                          "found in the 'allowed_address_pair' list while "
                          "trying to remove it.", ip, mac)

        if updated:
            self._update_port_address_pairs(
                port.id,
                address_pairs,
                revision_number=port.revision_number)

    def _update_port_address_pairs(self, port_id, address_pairs,
                                   revision_number=None):
        os_net = clients.get_network_client()
        os_net.update_port(port_id, allowed_address_pairs=address_pairs,
                           if_revision=revision_number)

    def _try_update_port(self, attempts, f,
                         vm_port, container_ips, container_mac):
        try:
            with self.lock:
                f(vm_port, container_ips, container_mac)
                attempts = 0
        except o_exc.SDKException:
            attempts -= 1
            if attempts == 0:
                LOG.exception("Error happened during updating port %s",
                              vm_port['id'] if vm_port else None)
                raise

        return attempts
