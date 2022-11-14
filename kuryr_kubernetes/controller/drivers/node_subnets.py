# Copyright 2020 Red Hat, Inc.
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

from openstack import exceptions as os_exc
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ConfigNodesSubnets(base.NodesSubnetsDriver):
    """Provides list of nodes subnets from configuration."""

    def get_nodes_subnets(self, raise_on_empty=False):
        node_subnet_ids = CONF.pod_vif_nested.worker_nodes_subnets
        if not node_subnet_ids:
            if raise_on_empty:
                raise cfg.RequiredOptError(
                    'worker_nodes_subnets', cfg.OptGroup('pod_vif_nested'))
            else:
                return []

        return node_subnet_ids

    def add_node(self, node):
        return False

    def delete_node(self, node):
        return False


class OpenShiftNodesSubnets(base.NodesSubnetsDriver):
    """Provides list of nodes subnets based on OpenShift Machine objects."""

    def __init__(self):
        super().__init__()
        self.subnets = set()

    def _get_subnet_from_machine(self, machine):
        spec = machine['spec'].get('providerSpec', {}).get('value')
        subnet_id = None
        trunk = spec.get('trunk')
        k8s = clients.get_kubernetes_client()

        if 'primarySubnet' in spec:
            # NOTE(gryf) in old OpenShift versions, primarySubnet was used for
            # selecting primary subnet from multiple networks. In the future
            # this field will be deprecated.

            os_net = clients.get_network_client()
            try:
                subnet = os_net.find_subnet(spec['primarySubnet'])
            except os_exc.DuplicateResource:
                LOG.error('Name "%s" defined in primarySubnet for Machine/'
                          'MachineSet found in more than one subnets, which '
                          'may lead to issues. Please, use desired subnet id '
                          'instead.', spec['primarySubnet'])
                k8s.add_event(machine, 'AmbiguousPrimarySubnet',
                              f'Name "{spec["primarySubnet"]}" defined in '
                              f'primarySubnet for Machine/MachineSet found in '
                              f'multiple subnets, which may lead to issues. '
                              f'Please, use desired subnet id instead.',
                              'Warning', 'kuryr-controller')
                return None
            except os_exc.SDKException as ex:
                raise exceptions.ResourceNotReady(f'OpenStackSDK threw an '
                                                  f'exception {ex}, retrying.')

            if not subnet:
                LOG.error('Subnet name/id `%s` provided in MachineSet '
                          'primarySubnet field does not match any subnet. '
                          'Check the configuration.', spec['primarySubnet'])
                k8s.add_event(machine, 'PrimarySubnetNotFound',
                              f'Name "{spec["primarySubnet"]}" defined in '
                              f'primarySubnet for Machine/MachineSet does '
                              f'not match any subnet. Check the configuration.'
                              'Warning', 'kuryr-controller')
                return None

            return subnet.id

        if trunk and 'networks' in spec and spec['networks']:
            subnets = spec['networks'][0].get('subnets')
            if not subnets:
                LOG.warning('No `subnets` in Machine `providerSpec.values.'
                            'networks`.')
            else:
                primary_subnet = subnets[0]
                if primary_subnet.get('uuid'):
                    subnet_id = primary_subnet['uuid']
                else:
                    subnet_filter = primary_subnet['filter']
                    subnet_id = utils.get_subnet_id(**subnet_filter)

        if not subnet_id and 'ports' in spec and spec['ports']:
            for port in spec['ports']:
                if port.get('trunk', trunk) and port.get('fixedIPs'):
                    for fip in port['fixedIPs']:
                        if fip.get('subnetID'):
                            subnet_id = fip['subnetID']
                            break

        if not subnet_id:
            LOG.warning('No `subnets` found in Machine `providerSpec`')

        return subnet_id

    def get_nodes_subnets(self, raise_on_empty=False):
        with lockutils.lock('kuryr-machine-add'):
            # We add any hardcoded ones from config anyway.
            result = self.subnets
            if CONF.pod_vif_nested.worker_nodes_subnets:
                result = result.union(
                    set(CONF.pod_vif_nested.worker_nodes_subnets))
            if not result and raise_on_empty:
                raise exceptions.ResourceNotReady(
                    'OpenShift Machines does not exist or are not yet '
                    'handled. Cannot determine worker nodes subnets.')

            return list(result)

    def add_node(self, machine):
        subnet_id = self._get_subnet_from_machine(machine)
        if not subnet_id:
            LOG.warning('Could not determine subnet of Machine %s',
                        machine['metadata']['name'])
            return False

        with lockutils.lock('kuryr-machine-add'):
            if subnet_id not in self.subnets:
                LOG.info('Adding subnet %s to the worker nodes subnets as '
                         'machine %s runs in it.', subnet_id,
                         machine['metadata']['name'])
                self.subnets.add(subnet_id)
                return True
            return False

    def delete_node(self, machine):
        k8s = clients.get_kubernetes_client()
        affected_subnet_id = self._get_subnet_from_machine(machine)
        if not affected_subnet_id:
            LOG.warning('Could not determine subnet of Machine %s',
                        machine['metadata']['name'])
            return False

        machines = k8s.get(constants.OPENSHIFT_API_CRD_MACHINES)
        for existing_machine in machines.get('items', []):
            if affected_subnet_id == self._get_subnet_from_machine(
                    existing_machine):
                return False

        # We know that subnet is no longer used, so we remove it.
        LOG.info('Removing subnet %s from the worker nodes subnets',
                 affected_subnet_id)
        with lockutils.lock('kuryr-machine-add'):
            self.subnets.remove(affected_subnet_id)

        return True
