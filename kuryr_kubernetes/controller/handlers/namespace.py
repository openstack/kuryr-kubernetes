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

import eventlet
import time

from openstack import exceptions as os_exc
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils


LOG = logging.getLogger(__name__)

DEFAULT_CLEANUP_INTERVAL = 60
DEFAULT_CLEANUP_RETRIES = 10


class NamespaceHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = constants.K8S_OBJ_NAMESPACE
    OBJECT_WATCH_PATH = constants.K8S_API_NAMESPACES

    def __init__(self):
        super(NamespaceHandler, self).__init__()
        self._drv_project = drivers.NamespaceProjectDriver.get_instance()
        self._drv_subnets = drivers.PodSubnetsDriver.get_instance()
        self._drv_sg = drivers.PodSecurityGroupsDriver.get_instance()
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            specific_driver='multi_pool')
        self._drv_vif_pool.set_vif_driver()
        if self._is_network_policy_enabled():
            self._drv_lbaas = drivers.LBaaSDriver.get_instance()
            self._drv_svc_sg = (
                drivers.ServiceSecurityGroupsDriver.get_instance())

        # NOTE(ltomasbo): Checks and clean up leftovers due to
        # kuryr-controller retarts
        eventlet.spawn(self._cleanup_namespace_leftovers)

    def on_present(self, namespace):
        ns_name = namespace['metadata']['name']
        current_namespace_labels = namespace['metadata'].get('labels')
        previous_namespace_labels = driver_utils.get_annotated_labels(
            namespace, constants.K8S_ANNOTATION_NAMESPACE_LABEL)
        LOG.debug("Got previous namespace labels from annotation: %r",
                  previous_namespace_labels)

        project_id = self._drv_project.get_project(namespace)
        if current_namespace_labels != previous_namespace_labels:
            crd_selectors = self._drv_sg.update_namespace_sg_rules(namespace)
            self._set_namespace_labels(namespace, current_namespace_labels)
            if (self._is_network_policy_enabled() and crd_selectors and
                    oslo_cfg.CONF.octavia_defaults.enforce_sg_rules):
                services = driver_utils.get_services()
                self._update_services(services, crd_selectors, project_id)

        net_crd_id = self._get_net_crd_id(namespace)
        if net_crd_id:
            LOG.debug("CRD existing at the new namespace")
            return

        net_crd_name = 'ns-' + ns_name
        net_crd = self._get_net_crd(net_crd_name)
        if net_crd:
            LOG.debug("Previous CRD existing at the new namespace. "
                      "Deleting namespace resources and retying its creation.")
            self.on_deleted(namespace, net_crd)
            raise exceptions.ResourceNotReady(namespace)

        # NOTE(ltomasbo): Ensure there is no previously created networks
        # leftovers due to a kuryr-controller crash/restart
        LOG.debug("Deleting leftovers network resources for namespace: %s",
                  ns_name)
        self._drv_subnets.cleanup_namespace_networks(ns_name)

        LOG.debug("Creating network resources for namespace: %s", ns_name)
        net_crd_spec = self._drv_subnets.create_namespace_network(ns_name,
                                                                  project_id)
        # create CRD resource for the network
        try:
            net_crd = self._add_kuryrnet_crd(ns_name, net_crd_spec)
            self._drv_sg.create_namespace_sg_rules(namespace)
            self._set_net_crd(namespace, net_crd)
        except (exceptions.K8sClientException,
                exceptions.K8sResourceNotFound):
            LOG.exception("Kuryrnet CRD creation failed. Rolling back "
                          "resources created for the namespace.")
            self._drv_subnets.rollback_network_resources(net_crd_spec, ns_name)
            try:
                self._del_kuryrnet_crd(net_crd_name)
            except exceptions.K8sClientException:
                LOG.exception("Error when trying to rollback the KuryrNet CRD "
                              "object %s", net_crd_name)
            raise exceptions.ResourceNotReady(namespace)

    def on_deleted(self, namespace, net_crd=None):
        LOG.debug("Deleting namespace: %s", namespace)
        if not net_crd:
            net_crd_id = self._get_net_crd_id(namespace)
            if not net_crd_id:
                LOG.warning("There is no CRD annotated at the namespace %s",
                            namespace)
                return
            net_crd = self._get_net_crd(net_crd_id)
            if not net_crd:
                LOG.warning("This should not happen. Probably this is event "
                            "is processed twice due to a restart or etcd is "
                            "not in sync")
                # NOTE(ltomasbo): We should rely on etcd properly behaving, so
                # we are returning here to prevent duplicated events processing
                # but not to prevent etcd failures.
                return

        net_crd_name = net_crd['metadata']['name']

        self._drv_vif_pool.delete_network_pools(net_crd['spec']['netId'])
        try:
            self._drv_subnets.delete_namespace_subnet(net_crd)
        except exceptions.ResourceNotReady:
            LOG.debug("Subnet is not ready to be removed.")
            # TODO(ltomasbo): Once KuryrPort CRDs is supported, we should
            # execute a delete network ports method here to remove the ports
            # associated to the namespace/subnet, ensuring next retry will be
            # successful
            raise
        self._del_kuryrnet_crd(net_crd_name)
        crd_selectors = self._drv_sg.delete_namespace_sg_rules(namespace)

        if (self._is_network_policy_enabled() and crd_selectors and
                oslo_cfg.CONF.octavia_defaults.enforce_sg_rules):
            project_id = self._drv_project.get_project(namespace)
            services = driver_utils.get_services()
            self._update_services(services, crd_selectors, project_id)

    def is_ready(self, quota):
        if not utils.has_kuryr_crd(constants.K8S_API_CRD_KURYRNETS):
            return False
        return self._check_quota(quota)

    def _check_quota(self, quota):
        resources = ('subnets', 'networks', 'security_groups')

        for resource in resources:
            resource_quota = quota[resource]
            if utils.has_limit(resource_quota):
                if not utils.is_available(resource, resource_quota):
                    return False
        return True

    def _get_net_crd_id(self, namespace):
        try:
            annotations = namespace['metadata']['annotations']
            net_crd_id = annotations[constants.K8S_ANNOTATION_NET_CRD]
        except KeyError:
            return None
        return net_crd_id

    def _get_net_crd(self, net_crd_id):
        k8s = clients.get_kubernetes_client()
        try:
            kuryrnet_crd = k8s.get('%s/kuryrnets/%s' % (constants.K8S_API_CRD,
                                                        net_crd_id))
        except exceptions.K8sResourceNotFound:
            return None
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return kuryrnet_crd

    def _set_net_crd(self, namespace, net_crd):
        LOG.debug("Setting CRD annotations: %s", net_crd)

        k8s = clients.get_kubernetes_client()
        k8s.annotate(namespace['metadata']['selfLink'],
                     {constants.K8S_ANNOTATION_NET_CRD:
                      net_crd['metadata']['name']},
                     resource_version=namespace['metadata']['resourceVersion'])

    def _add_kuryrnet_crd(self, namespace, net_crd_spec):
        kubernetes = clients.get_kubernetes_client()
        net_crd_name = "ns-" + namespace
        spec = {k: v for k, v in net_crd_spec.items()}
        # NOTE(ltomasbo): To know if the subnet has bee populated with pools.
        # This is only needed by the kuryrnet handler to skip actions. But its
        # addition does not have any impact if not used
        spec['populated'] = False

        net_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrNet',
            'metadata': {
                'name': net_crd_name,
                'annotations': {
                    'namespaceName': namespace,
                }
            },
            'spec': spec,
        }
        try:
            kubernetes.post('%s/kuryrnets' % constants.K8S_API_CRD, net_crd)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating kuryrnet "
                          "CRD.")
            raise
        return net_crd

    def _del_kuryrnet_crd(self, net_crd_name):
        kubernetes = clients.get_kubernetes_client()
        try:
            kubernetes.delete('%s/kuryrnets/%s' % (constants.K8S_API_CRD,
                                                   net_crd_name))
        except exceptions.K8sResourceNotFound:
            LOG.debug("KuryrNetPolicy CRD not found: %s", net_crd_name)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception deleting kuryrnet "
                          "CRD.")
            raise

    def _set_namespace_labels(self, namespace, labels):
        if not labels:
            LOG.debug("Removing Label annotation: %r", labels)
            annotation = None
        else:
            annotation = jsonutils.dumps(labels, sort_keys=True)
            LOG.debug("Setting Labels annotation: %r", annotation)

        k8s = clients.get_kubernetes_client()
        k8s.annotate(namespace['metadata']['selfLink'],
                     {constants.K8S_ANNOTATION_NAMESPACE_LABEL: annotation},
                     resource_version=namespace['metadata']['resourceVersion'])

    def _update_services(self, services, crd_selectors, project_id):
        for service in services.get('items'):
            if not driver_utils.service_matches_affected_pods(
                    service, crd_selectors):
                continue
            sgs = self._drv_svc_sg.get_security_groups(service,
                                                       project_id)
            self._drv_lbaas.update_lbaas_sg(service, sgs)

    def _is_network_policy_enabled(self):
        enabled_handlers = oslo_cfg.CONF.kubernetes.enabled_handlers
        svc_sg_driver = oslo_cfg.CONF.kubernetes.service_security_groups_driver
        return ('policy' in enabled_handlers and svc_sg_driver == 'policy')

    def _cleanup_namespace_leftovers(self):
        k8s = clients.get_kubernetes_client()
        for i in range(DEFAULT_CLEANUP_RETRIES):
            retry = False
            try:
                net_crds = k8s.get(constants.K8S_API_CRD_KURYRNETS)
                namespaces = k8s.get(constants.K8S_API_NAMESPACES)
            except exceptions.K8sClientException:
                LOG.warning("Error retriving namespace information")
                return
            ns_dict = {'ns-' + ns['metadata']['name']: ns
                       for ns in namespaces.get('items')}

            for net_crd in net_crds.get('items'):
                try:
                    ns_dict[net_crd['metadata']['name']]
                except KeyError:
                    # Note(ltomasbo): The CRD does not have an associated
                    # namespace. It must be deleted
                    LOG.debug("Removing namespace leftovers associated to: "
                              "%s", net_crd)
                    # removing the 'ns-' preceding the namespace name on the
                    # net CRDs
                    ns_name = net_crd['metadata']['name'][3:]
                    # only namespace name is needed for on_deleted, faking the
                    # nonexistent object
                    ns_to_delete = {'metadata': {'name': ns_name}}
                    try:
                        self.on_deleted(ns_to_delete, net_crd)
                    except exceptions.ResourceNotReady:
                        LOG.debug("Cleanup of namespace %s failed. A retry "
                                  "will be triggered.", ns_name)
                        retry = True
                        continue

            if not retry:
                break
            # Leave time between retries to help Neutron to complete actions
            time.sleep(DEFAULT_CLEANUP_INTERVAL)

        # NOTE(ltomasbo): to ensure we don't miss created network resources
        # without associated kuryrnet objects, we do a second search
        os_net = clients.get_network_client()
        tags = oslo_cfg.CONF.neutron_defaults.resource_tags
        if not tags:
            return

        for i in range(DEFAULT_CLEANUP_RETRIES):
            retry = False
            subnets = os_net.subnets(tags=tags)
            namespaces = k8s.get(constants.K8S_API_NAMESPACES)
            ns_nets = ['ns/' + ns['metadata']['name'] + '-subnet'
                       for ns in namespaces.get('items')]
            for subnet in subnets:
                # NOTE(ltomasbo): subnet name is ns/NAMESPACE_NAME-subnet
                if subnet.name not in ns_nets:
                    if (subnet.subnet_pool_id !=
                            oslo_cfg.CONF.namespace_subnet.pod_subnet_pool):
                        # Not a kuryr generated network
                        continue
                    try:
                        self._drv_subnets._delete_namespace_network_resources(
                            subnet.id, subnet.network_id)
                    except (os_exc.SDKException, exceptions.ResourceNotReady):
                        LOG.debug("Cleanup of network namespace resources %s "
                                  "failed. A retry will be triggered.",
                                  subnet.network_id)
                        retry = True
                        continue
            if not retry:
                break
            # Leave time between retries to help Neutron to complete actions
            time.sleep(DEFAULT_CLEANUP_INTERVAL)
