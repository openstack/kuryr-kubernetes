# Copyright 2020 Red Hat, Inc.
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

from openstack import exceptions as os_exc
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class KuryrNetworkHandler(k8s_base.ResourceEventHandler):
    """Controller side of KuryrNetwork process for Kubernetes pods.

    `KuryrNetworkHandler` runs on the Kuryr-Kubernetes controller and is
    responsible for creating the OpenStack resources associated to the
    newly created namespaces, and update the KuryrNetwork CRD status with
    them.
    """
    OBJECT_KIND = constants.K8S_OBJ_KURYRNETWORK
    OBJECT_WATCH_PATH = constants.K8S_API_CRD_KURYRNETWORKS

    def __init__(self):
        super(KuryrNetworkHandler, self).__init__()
        self._drv_project = drivers.NamespaceProjectDriver.get_instance()
        self._drv_subnets = drivers.PodSubnetsDriver.get_instance()
        self._drv_sg = drivers.PodSecurityGroupsDriver.get_instance()
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            specific_driver='multi_pool')
        self._drv_vif_pool.set_vif_driver()
        if driver_utils.is_network_policy_enabled():
            self._drv_lbaas = drivers.LBaaSDriver.get_instance()
            self._drv_svc_sg = (
                drivers.ServiceSecurityGroupsDriver.get_instance())
        self.k8s = clients.get_kubernetes_client()

    def on_present(self, kuryrnet_crd, *args, **kwargs):
        ns_name = kuryrnet_crd['spec']['nsName']
        project_id = kuryrnet_crd['spec']['projectId']
        kns_status = kuryrnet_crd.get('status', {})
        namespace = driver_utils.get_namespace(ns_name)

        crd_creation = False
        net_id = kns_status.get('netId')
        if not net_id:
            try:
                net_id = self._drv_subnets.create_network(namespace,
                                                          project_id)
            except os_exc.SDKException as ex:
                self.k8s.add_event(kuryrnet_crd, 'CreateNetworkFailed',
                                   f'Error during creating Neutron network: '
                                   f'{ex.details}', 'Warning')
                raise
            status = {'netId': net_id}
            self._patch_kuryrnetwork_crd(kuryrnet_crd, status)
            self.k8s.add_event(kuryrnet_crd, 'CreateNetworkSucceed',
                               f'Neutron network {net_id} for namespace')
            crd_creation = True
        subnet_id = kns_status.get('subnetId')
        if not subnet_id or crd_creation:
            try:
                subnet_id, subnet_cidr = self._drv_subnets.create_subnet(
                    namespace, project_id, net_id)
            except os_exc.ConflictException as ex:
                self.k8s.add_event(kuryrnet_crd, 'CreateSubnetFailed',
                                   f'Error during creating Neutron subnet '
                                   f'for network {net_id}: {ex.details}',
                                   'Warning')
                raise
            status = {'subnetId': subnet_id, 'subnetCIDR': subnet_cidr}
            self._patch_kuryrnetwork_crd(kuryrnet_crd, status)
            self.k8s.add_event(kuryrnet_crd, 'CreateSubnetSucceed',
                               f'Neutron subnet {subnet_id} for network '
                               f'{net_id}')
            crd_creation = True
        if not kns_status.get('routerId') or crd_creation:
            try:
                router_id = self._drv_subnets.add_subnet_to_router(subnet_id)
            except os_exc.SDKException as ex:
                self.k8s.add_event(kuryrnet_crd, 'AddingSubnetToRouterFailed',
                                   f'Error adding Neutron subnet {subnet_id} '
                                   f'to router: {ex.details}',
                                   'Warning')
                raise
            status = {'routerId': router_id, 'populated': False}
            self._patch_kuryrnetwork_crd(kuryrnet_crd, status)
            self.k8s.add_event(kuryrnet_crd, 'AddingSubnetToRouterSucceed',
                               f'Neutron subnet {subnet_id} added to router '
                               f'{router_id}')
            crd_creation = True

        # check labels to create sg rules
        ns_labels = kns_status.get('nsLabels', {})
        if (crd_creation or
                ns_labels != kuryrnet_crd['spec']['nsLabels']):
            # update SG and svc SGs
            crd_selectors = self._drv_sg.update_namespace_sg_rules(namespace)
            if (driver_utils.is_network_policy_enabled() and crd_selectors and
                    oslo_cfg.CONF.octavia_defaults.enforce_sg_rules):
                services = driver_utils.get_services()
                self._update_services(services, crd_selectors, project_id)
            # update status
            status = {'nsLabels': kuryrnet_crd['spec']['nsLabels']}
            self._patch_kuryrnetwork_crd(kuryrnet_crd, status, labels=True)
            self.k8s.add_event(kuryrnet_crd, 'SGUpdateTriggered',
                               'Neutron security groups update has been '
                               'triggered')

    def on_finalize(self, kuryrnet_crd, *args, **kwargs):
        LOG.debug("Deleting kuryrnetwork CRD resources: %s", kuryrnet_crd)

        net_id = kuryrnet_crd.get('status', {}).get('netId')
        if net_id:
            self._drv_vif_pool.delete_network_pools(net_id)
            try:
                self._drv_subnets.delete_namespace_subnet(kuryrnet_crd)
            except k_exc.ResourceNotReady:
                LOG.debug("Subnet is not ready to be removed.")
                # TODO(ltomasbo): Once KuryrPort CRDs is supported, we should
                # execute a delete network ports method here to remove the
                # ports associated to the namespace/subnet, ensuring next
                # retry will be successful
                raise
        else:
            # NOTE(gryf): It may happen, that even if KuryrNetworkCRD was not
            # updated (when controller crash in between), but the network and
            # possibly subnet is there, so it needs to be searched manually.
            ns = self.k8s.get(f'{constants.K8S_API_NAMESPACES}/'
                              f'{kuryrnet_crd["spec"]["nsName"]}')
            ns_name = ns['metadata']['name']
            ns_uid = ns['metadata']['uid']
            net_name = driver_utils.get_resource_name(ns_name)
            old_net_name = driver_utils.get_resource_name(ns_name,
                                                          prefix='ns/',
                                                          suffix='-net')
            # TODO(gryf): remove old_net_name support in next release.
            os_net = clients.get_network_client()
            networks = os_net.networks(name=(net_name, old_net_name))
            for net in networks:
                if ns_uid == net.description:
                    LOG.warning('Found Neutron network associated with '
                                'namespace `%s`, while it is not registered '
                                'on KuryrNetwork CRD. Trying to remove.',
                                ns_name)
                    self._drv_vif_pool.delete_network_pools(net.id)

                    try:
                        os_net.delete_network(net)
                    except os_exc.ConflictException:
                        LOG.warning("One or more ports in use on the network "
                                    "%s. Retrying.", net.id)
                        raise k_exc.ResourceNotReady(net.id)

        namespace = {
            'metadata': {'name': kuryrnet_crd['spec']['nsName']}}
        crd_selectors = self._drv_sg.delete_namespace_sg_rules(namespace)

        if (driver_utils.is_network_policy_enabled() and crd_selectors and
                oslo_cfg.CONF.octavia_defaults.enforce_sg_rules):
            project_id = kuryrnet_crd['spec']['projectId']
            services = driver_utils.get_services()
            self._update_services(services, crd_selectors, project_id)

        LOG.debug('Removing finalizer for KuryrNetwork CRD %s', kuryrnet_crd)
        try:
            self.k8s.remove_finalizer(kuryrnet_crd,
                                      constants.KURYRNETWORK_FINALIZER)
        except k_exc.K8sClientException:
            LOG.exception('Error removing KuryrNetwork CRD finalizer for %s',
                          kuryrnet_crd)
            raise

    def _update_services(self, services, crd_selectors, project_id):
        for service in services.get('items'):
            if not driver_utils.service_matches_affected_pods(
                    service, crd_selectors):
                continue
            sgs = self._drv_svc_sg.get_security_groups(service,
                                                       project_id)
            self._drv_lbaas.update_lbaas_sg(service, sgs)

    def _patch_kuryrnetwork_crd(self, kuryrnet_crd, status, labels=False):
        LOG.debug('Patching KuryrNetwork CRD %s', kuryrnet_crd)
        try:
            if labels:
                self.k8s.patch_crd('status',
                                   utils.get_res_link(kuryrnet_crd), status)
            else:
                self.k8s.patch('status', utils.get_res_link(kuryrnet_crd),
                               status)
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrNetwork CRD not found %s', kuryrnet_crd)
        except k_exc.K8sClientException:
            LOG.exception('Error updating kuryrNetwork CRD %s', kuryrnet_crd)
            raise
