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
from kuryr.lib import constants as kl_const
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import default_subnet
from kuryr_kubernetes.controller.drivers import utils as c_utils
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils

from openstack import exceptions as os_exc

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
TAGS = oslo_cfg.CONF.neutron_defaults.resource_tags


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
            net_crd_path = (f"{constants.K8S_API_CRD_NAMESPACES}/"
                            f"{namespace}/kuryrnetworks/{namespace}")
            net_crd = kubernetes.get(net_crd_path)
        except exceptions.K8sResourceNotFound:
            LOG.debug("Kuryrnetwork resource not yet created, retrying...")
            raise exceptions.ResourceNotReady(namespace)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise

        try:
            subnet_id = net_crd['status']['subnetId']
        except KeyError:
            LOG.debug("Subnet for namespace %s not yet created, retrying.",
                      namespace)
            raise exceptions.ResourceNotReady(namespace)
        return subnet_id

    def delete_namespace_subnet(self, net_crd):
        subnet_id = net_crd['status'].get('subnetId')
        net_id = net_crd['status'].get('netId')

        if net_id:
            self._delete_namespace_network_resources(subnet_id, net_id)

    def _delete_namespace_network_resources(self, subnet_id, net_id):
        os_net = clients.get_network_client()
        if subnet_id:
            router_id = oslo_cfg.CONF.namespace_subnet.pod_router
            try:
                clients.handle_neutron_errors(
                    os_net.remove_interface_from_router, router_id,
                    subnet_id=subnet_id)
            except os_exc.NotFoundException as e:
                # Nothing to worry about, either router or subnet is no more,
                # or subnet is already detached.
                LOG.debug(e.message)
                pass
            except os_exc.SDKException:
                LOG.exception("Error deleting subnet %(subnet)s from router "
                              "%(router)s.",
                              {'subnet': subnet_id, 'router': router_id})
                raise

        try:
            os_net.delete_network(net_id)
        except os_exc.ConflictException:
            LOG.warning("One or more ports in use on the network %s. "
                        "Deleting leftovers ports before retrying", net_id)
            # NOTE(dulek): '' is there because Neutron seems to unset
            #              device_owner on detach.
            leftover_ports = [p for p in os_net.ports(network_id=net_id)
                              if p.device_owner in
                              ['', 'trunk:subport', kl_const.DEVICE_OWNER]]
            c_utils.delete_ports(leftover_ports)
            raise exceptions.ResourceNotReady(net_id)
        except os_exc.SDKException:
            LOG.exception("Error deleting network %s.", net_id)
            raise

    def create_network(self, ns, project_id):
        os_net = clients.get_network_client()
        ns_name = ns['metadata']['name']
        ns_uid = ns['metadata']['uid']
        net_name = c_utils.get_resource_name(ns_name, ns_uid)
        old_net_name = c_utils.get_resource_name(ns_name, prefix='ns/',
                                                 suffix='-net')
        # TODO(gryf): remove old_net_name support in next release, and precise
        # the query by adding additional query parameter 'description' which
        # should contain namespace uid.
        networks = os_net.networks(name=(net_name, old_net_name))
        tags = ",".join(TAGS)

        try:
            # NOTE(ltomasbo): only one network must exists
            net = next(networks)
            # NOTE(gryf): It might happen, that network has been created, but
            # for some reason tagging has failed.
            if TAGS and not set(TAGS).issubset(set(net.tags)):
                c_utils.tag_neutron_resources([net], exceptions=True)
            return net.id
        except (StopIteration, ValueError):
            LOG.debug('Network does not exist. Creating.')

        mtu_cfg = oslo_cfg.CONF.neutron_defaults.network_device_mtu
        attrs = {'name': net_name, 'project_id': project_id,
                 'description': tags}
        if mtu_cfg:
            attrs['mtu'] = mtu_cfg

        try:
            net = os_net.create_network(**attrs)
        except os_exc.SDKException:
            LOG.exception("Error creating neutron resources for the namespace "
                          "%s", ns_name)
            raise
        c_utils.tag_neutron_resources([net], exceptions=True)
        return net.id

    def create_subnet(self, ns, project_id, net_id):
        os_net = clients.get_network_client()
        ns_name = ns['metadata']['name']
        ns_uid = ns['metadata']['uid']
        tags = ",".join(TAGS)

        # NOTE(gryf): assumption is, that all the subnets (well, currently
        # only one) in specific k8s namespaces are under exactly one network,
        # which have proper namespace uid in its description, so there is no
        # need to put it on the subnet as well.
        subnet_name = c_utils.get_resource_name(ns_name, ns_uid)
        subnets = os_net.subnets(network_id=net_id)

        try:
            # NOTE(ltomasbo): only one subnet must exists
            subnet = next(subnets)
            # NOTE(gryf): same situation as in networks.
            if TAGS and not set(TAGS).issubset(set(subnet.tags)):
                c_utils.tag_neutron_resources([subnet], exceptions=True)
            return subnet.id, subnet.cidr
        except StopIteration:
            LOG.debug('Subnet does not exist. Creating.')

        # create subnet with namespace as name
        subnet_pool_id = oslo_cfg.CONF.namespace_subnet.pod_subnet_pool
        ip_version = utils.get_subnetpool_version(subnet_pool_id)
        try:
            neutron_subnet = (os_net
                              .create_subnet(network_id=net_id,
                                             description=tags,
                                             ip_version=ip_version,
                                             name=subnet_name,
                                             enable_dhcp=False,
                                             subnetpool_id=subnet_pool_id,
                                             project_id=project_id))
        except os_exc.ConflictException:
            LOG.debug("Max number of retries on neutron side achieved, "
                      "raising ResourceNotReady to retry subnet creation "
                      "for %s", subnet_name)
            raise exceptions.ResourceNotReady(subnet_name)
        c_utils.tag_neutron_resources([neutron_subnet], exceptions=True)

        return neutron_subnet.id, neutron_subnet.cidr

    def add_subnet_to_router(self, subnet_id):
        os_net = clients.get_network_client()
        router_id = oslo_cfg.CONF.namespace_subnet.pod_router
        try:
            # connect the subnet to the router
            os_net.add_interface_to_router(router_id, subnet_id=subnet_id)
        except os_exc.BadRequestException:
            LOG.debug("Subnet %s already connected to the router", subnet_id)
        except os_exc.SDKException:
            LOG.exception("Error attaching the subnet %s to the router",
                          subnet_id)
            raise
        return router_id
