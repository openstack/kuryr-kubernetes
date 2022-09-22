# Copyright (C) 2020 Intel Corporation
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

from openstack import exceptions as o_exc
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes.controller.drivers import nested_vif
from kuryr_kubernetes.controller.drivers import utils
from kuryr_kubernetes import os_vif_util as ovu


LOG = logging.getLogger(__name__)


class NestedDpdkPodVIFDriver(nested_vif.NestedPodVIFDriver):
    """Manages ports for DPDK based nested-containers to provide VIFs."""

    # TODO(garyloug): maybe log a warning if the vswitch is not ovs-dpdk?

    def request_vif(self, pod, project_id, subnets, security_groups):
        os_net = clients.get_network_client()
        compute = clients.get_compute_client()

        vm_id = self._get_parent_port(pod).device_id
        net_id = utils.get_network_id(subnets)

        try:
            result = compute.create_server_interface(vm_id, net_id=net_id)
        except o_exc.SDKException:
            LOG.warning("Unable to create interface for server %s.",
                        vm_id)
            raise
        port = os_net.get_port(result.port_id)
        return ovu.neutron_to_osvif_vif_dpdk(port, subnets, pod)

    def request_vifs(self, pod, project_id, subnets, security_groups,
                     num_ports):
        # TODO(garyloug): provide an implementation
        raise NotImplementedError()

    def release_vif(self, pod, vif, project_id=None):
        compute = clients.get_compute_client()

        vm_id = self._get_parent_port(pod).device_id
        LOG.debug("release_vif for vm_id %s %s", vm_id, vif.id)

        try:
            compute.delete_server_interface(vif.id, server=vm_id)
        except o_exc.SDKException:
            LOG.warning("Unable to delete interface %s for server %s.",
                        vif.id, vm_id)
            raise

    def activate_vif(self, vif, **kwargs):
        # NOTE(danil): new virtual interface was created in nova instance
        # during request_vif call, thus if it was not created successfully
        # an exception o_exc.SDKException would be throwed. During binding
        # process only rebinding of interface on userspace driver was done.
        # There is no any chance to check the state of rebinded interface.
        # Thus just set 'active' immediately to let the CNI driver make
        # progress.
        vif.active = True
