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
        subnet_id = self._get_namespace_subnet(pod_namespace)

        return {subnet_id: utils.get_subnet(subnet_id)}

    def _get_namespace_subnet(self, namespace):
        kubernetes = clients.get_kubernetes_client()
        try:
            ns = kubernetes.get('%s/namespaces/%s' % (constants.K8S_API_BASE,
                                                      namespace))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise exceptions.ResourceNotReady(namespace)

        try:
            annotations = ns['metadata']['annotations']
            net_crd_name = annotations[constants.K8S_ANNOTATION_NET_CRD]
        except KeyError:
            LOG.exception("Namespace missing CRD annotations for selecting "
                          "the corresponding subnet.")
            raise exceptions.ResourceNotReady(namespace)

        try:
            net_crd = kubernetes.get('%s/kuryrnets/%s' % (
                constants.K8S_API_CRD, net_crd_name))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise

        return net_crd['spec']['subnetId']

    def delete_namespace_subnet(self, net_crd):
        neutron = clients.get_neutron_client()

        router_id = oslo_cfg.CONF.namespace_subnet.pod_router
        subnet_id = net_crd['spec']['subnetId']
        net_id = net_crd['spec']['netId']

        try:
            neutron.remove_interface_router(router_id,
                                            {"subnet_id": subnet_id})
        except n_exc.NotFound:
            LOG.debug("Subnet %(subnet)s not attached to router %(router)s",
                      {'subnet': subnet_id, 'router': router_id})
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
            LOG.exception("One or more ports in use on the network %s.",
                          net_id)
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

            # create a subnet within that network
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

            # connect the subnet to the router
            neutron.add_interface_router(router_id,
                                         {"subnet_id": neutron_subnet['id']})
        except n_exc.NeutronClientException as ex:
            LOG.error("Error creating neutron resources for the namespace "
                      "%s: %s", namespace, ex)
            raise ex
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
