# Copyright 2018 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from kuryr.lib._i18n import _
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import default_subnet
from kuryr_kubernetes.controller.drivers import utils as c_utils
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils

from neutronclient.common import exceptions as n_exc

LOG = logging.getLogger(__name__)

namespace_subnet_driver_opts = [
    oslo_cfg.StrOpt('pod_router',
                    help=_("Default Neutron router ID where pod subnet(s) is "
                           "connected")),
    oslo_cfg.StrOpt('pod_subnet_pool',
                    help=_("Default Neutron subnet pool ID where pod subnets "
                           "get their cidr from")),
]

oslo_cfg.CONF.register_opts(namespace_subnet_driver_opts, "namespace_subnet")


class NamespacePodSubnetDriver(default_subnet.DefaultPodSubnetDriver):
    """Provides subnet for Pod port based on a Pod's namespace."""

    def get_subnets(self, pod, project_id):
        pod_namespace = pod['metadata']['namespace']
        return self.get_namespace_subnet(pod_namespace)

    def get_namespace_subnet(self, namespace, subnet_id=None):
        if not subnet_id:
            subnet_id = self._get_namespace_subnet_id(namespace)
        return {subnet_id: utils.get_subnet(subnet_id)}

    def _get_namespace_subnet_id(self, namespace):
        kubernetes = clients.get_kubernetes_client()
        try:
            ns = kubernetes.get('%s/namespaces/%s' % (constants.K8S_API_BASE,
                                                      namespace))
        except exceptions.K8sResourceNotFound:
            LOG.warning("Namespace %s not found", namespace)
            raise
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise exceptions.ResourceNotReady(namespace)

        try:
            annotations = ns['metadata']['annotations']
            net_crd_name = annotations[constants.K8S_ANNOTATION_NET_CRD]
        except KeyError:
            LOG.debug("Namespace missing CRD annotations for selecting "
                      "the corresponding subnet.")
            raise exceptions.ResourceNotReady(namespace)

        try:
            net_crd = kubernetes.get('%s/kuryrnets/%s' % (
                constants.K8S_API_CRD, net_crd_name))
        except exceptions.K8sResourceNotFound:
            LOG.debug("Kuryrnet resource not yet created, retrying...")
            raise exceptions.ResourceNotReady(net_crd_name)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise

        return net_crd['spec']['subnetId']

    def delete_namespace_subnet(self, net_crd):
        subnet_id = net_crd['spec']['subnetId']
        net_id = net_crd['spec']['netId']

        self._delete_namespace_network_resources(subnet_id, net_id)

    def _delete_namespace_network_resources(self, subnet_id, net_id):
        neutron = clients.get_neutron_client()
        if subnet_id:
            router_id = oslo_cfg.CONF.namespace_subnet.pod_router
            try:
                neutron.remove_interface_router(router_id,
                                                {"subnet_id": subnet_id})
            except n_exc.NotFound:
                LOG.debug("Subnet %(subnet)s not attached to router "
                          "%(router)s", {'subnet': subnet_id,
                                         'router': router_id})
            except n_exc.NeutronClientException:
                LOG.exception("Error deleting subnet %(subnet)s from router "
                              "%(router)s.", {'subnet': subnet_id, 'router':
                                              router_id})
                raise

        try:
            neutron.delete_network(net_id)
        except n_exc.NotFound:
            LOG.debug("Neutron Network not found: %s", net_id)
        except n_exc.NetworkInUseClient:
            LOG.exception("One or more ports in use on the network %s. "
                          "Deleting leftovers ports before retrying", net_id)
            leftover_ports = c_utils.get_ports_by_attrs(status='DOWN',
                                                        network_id=net_id)
            for leftover_port in leftover_ports:
                try:
                    neutron.delete_port(leftover_port['id'])
                except n_exc.PortNotFoundClient:
                    LOG.debug("Port already deleted.")
                except n_exc.NeutronClientException as e:
                    if "currently a subport for trunk" in str(e):
                        LOG.warning("Port %s is in DOWN status but still "
                                    "associated to a trunk. This should not "
                                    "happen. Trying to delete it from the "
                                    "trunk.", leftover_port['id'])
                        # Get the trunk_id from the error message
                        trunk_id = (
                            str(e).split('trunk')[1].split('.')[0].strip())
                        neutron.trunk_remove_subports(
                            trunk_id, {'sub_ports': [
                                {'port_id': leftover_port['id']}]})
                    else:
                        LOG.exception("Unexpected error deleting leftover "
                                      "port %s. Skiping it and continue with "
                                      "the other rest.", leftover_port['id'])
            raise exceptions.ResourceNotReady(net_id)
        except n_exc.NeutronClientException:
            LOG.exception("Error deleting network %s.", net_id)
            raise

    def create_namespace_network(self, namespace, project_id):
        neutron = clients.get_neutron_client()

        router_id = oslo_cfg.CONF.namespace_subnet.pod_router
        subnet_pool_id = oslo_cfg.CONF.namespace_subnet.pod_subnet_pool

        # create network with namespace as name
        network_name = "ns/" + namespace + "-net"
        subnet_name = "ns/" + namespace + "-subnet"
        try:
            neutron_net = neutron.create_network(
                {
                    "network": {
                        "name": network_name,
                        "project_id": project_id
                    }
                }).get('network')
            c_utils.tag_neutron_resources('networks', [neutron_net['id']])

            # create a subnet within that network
            try:
                neutron_subnet = neutron.create_subnet(
                    {
                        "subnet": {
                            "network_id": neutron_net['id'],
                            "ip_version": 4,
                            "name": subnet_name,
                            "enable_dhcp": False,
                            "subnetpool_id": subnet_pool_id,
                            "project_id": project_id
                        }
                    }).get('subnet')
            except n_exc.Conflict:
                LOG.debug("Max number of retries on neutron side achieved, "
                          "raising ResourceNotReady to retry subnet creation "
                          "for %s", subnet_name)
                raise exceptions.ResourceNotReady(subnet_name)
            c_utils.tag_neutron_resources('subnets', [neutron_subnet['id']])

            # connect the subnet to the router
            neutron.add_interface_router(router_id,
                                         {"subnet_id": neutron_subnet['id']})
        except n_exc.NeutronClientException:
            LOG.exception("Error creating neutron resources for the namespace "
                          "%s", namespace)
            raise
        return {'netId': neutron_net['id'],
                'routerId': router_id,
                'subnetId': neutron_subnet['id'],
                'subnetCIDR': neutron_subnet['cidr']}

    def rollback_network_resources(self, net_crd_spec, namespace):
        neutron = clients.get_neutron_client()
        try:
            neutron.remove_interface_router(net_crd_spec['routerId'],
                                            {'subnet_id':
                                             net_crd_spec['subnetId']})
            neutron.delete_network(net_crd_spec['netId'])
        except n_exc.NeutronClientException:
            LOG.exception("Failed to clean up network resources associated to "
                          "%(net_id)s, created for the namespace: "
                          "%(namespace)s." % {'net_id': net_crd_spec['netId'],
                                              'namespace': namespace})

    def cleanup_namespace_networks(self, namespace):
        neutron = clients.get_neutron_client()
        net_name = 'ns/' + namespace + '-net'
        filters = {'name': net_name}
        tags = oslo_cfg.CONF.neutron_defaults.resource_tags
        if tags:
            filters['tags'] = tags
        networks = neutron.list_networks(**filters)['networks']
        if networks:
            for net in networks:
                net_id = net['id']
                subnets = net.get('subnets')
                subnet_id = None
                if subnets:
                    # NOTE(ltomasbo): Each network created by kuryr only has
                    # one subnet
                    subnet_id = subnets[0]
                self._delete_namespace_network_resources(subnet_id, net_id)
