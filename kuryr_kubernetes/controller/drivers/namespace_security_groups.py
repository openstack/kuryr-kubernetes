# Copyright (c) 2018 Red Hat, Inc.
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

from kuryr.lib._i18n import _
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import utils
from kuryr_kubernetes import exceptions

from neutronclient.common import exceptions as n_exc

LOG = logging.getLogger(__name__)

namespace_sg_driver_opts = [
    cfg.StrOpt('sg_allow_from_namespaces',
               help=_("Default security group to allow traffic from the "
                      "namespaces into the default namespace.")),
    cfg.StrOpt('sg_allow_from_default',
               help=_("Default security group to allow traffic from the "
                      "default namespaces into the other namespaces."))
]

cfg.CONF.register_opts(namespace_sg_driver_opts, "namespace_sg")

DEFAULT_NAMESPACE = 'default'


def _get_net_crd(namespace):
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
        LOG.debug("Namespace missing CRD annotations for selecting the "
                  "corresponding security group. Action will be retried.")
        raise exceptions.ResourceNotReady(namespace)
    try:
        net_crd = kubernetes.get('%s/kuryrnets/%s' % (constants.K8S_API_CRD,
                                                      net_crd_name))
    except exceptions.K8sClientException:
        LOG.exception("Kubernetes Client Exception.")
        raise

    return net_crd


class NamespacePodSecurityGroupsDriver(base.PodSecurityGroupsDriver):
    """Provides security groups for Pod based on a configuration option."""

    def get_security_groups(self, pod, project_id):
        namespace = pod['metadata']['namespace']
        net_crd = _get_net_crd(namespace)

        sg_list = [str(net_crd['spec']['sgId'])]

        extra_sgs = self._get_extra_sg(namespace)
        for sg in extra_sgs:
            sg_list.append(str(sg))

        sg_list.extend(config.CONF.neutron_defaults.pod_security_groups)

        return sg_list[:]

    def _get_extra_sg(self, namespace):
        # Differentiates between default namespace and the rest
        if namespace == DEFAULT_NAMESPACE:
            return [cfg.CONF.namespace_sg.sg_allow_from_namespaces]
        else:
            return [cfg.CONF.namespace_sg.sg_allow_from_default]

    def create_namespace_sg(self, namespace, project_id, crd_spec):
        neutron = clients.get_neutron_client()

        sg_name = "ns/" + namespace + "-sg"
        # create the associated SG for the namespace
        try:
            # default namespace is different from the rest
            # Default allows traffic from everywhere
            # The rest can be accessed from the default one
            sg = neutron.create_security_group(
                {
                    "security_group": {
                        "name": sg_name,
                        "project_id": project_id
                    }
                }).get('security_group')
            utils.tag_neutron_resources('security-groups', [sg['id']])
            neutron.create_security_group_rule(
                {
                    "security_group_rule": {
                        "direction": "ingress",
                        "remote_ip_prefix": crd_spec['subnetCIDR'],
                        "security_group_id": sg['id']
                    }
                })
        except n_exc.NeutronClientException:
            LOG.exception("Error creating security group for the namespace "
                          "%s", namespace)
            raise
        return {'sgId': sg['id']}

    def delete_sg(self, sg_id):
        neutron = clients.get_neutron_client()
        try:
            neutron.delete_security_group(sg_id)
        except n_exc.NotFound:
            LOG.debug("Security Group not found: %s", sg_id)
        except n_exc.NeutronClientException:
            LOG.exception("Error deleting security group %s.", sg_id)
            raise

    def delete_namespace_sg_rules(self, namespace):
        LOG.debug("Security group driver does not create SG rules for "
                  "namespace.")

    def create_namespace_sg_rules(self, namespace):
        LOG.debug("Security group driver does not create SG rules for "
                  "namespace.")

    def update_namespace_sg_rules(self, namespace):
        LOG.debug("Security group driver does not create SG rules for "
                  "namespace.")

    def create_sg_rules(self, pod):
        LOG.debug("Security group driver does not create SG rules for "
                  "the pods.")

    def delete_sg_rules(self, pod):
        LOG.debug("Security group driver does not delete SG rules for "
                  "the pods.")

    def update_sg_rules(self, pod):
        LOG.debug("Security group driver does not update SG rules for "
                  "the pods.")


class NamespaceServiceSecurityGroupsDriver(base.ServiceSecurityGroupsDriver):
    """Provides security groups for Service based on a configuration option."""

    def get_security_groups(self, service, project_id):
        namespace = service['metadata']['namespace']
        net_crd = _get_net_crd(namespace)

        sg_list = []
        sg_list.append(str(net_crd['spec']['sgId']))

        extra_sgs = self._get_extra_sg(namespace)
        for sg in extra_sgs:
            sg_list.append(str(sg))

        return sg_list[:]

    def _get_extra_sg(self, namespace):
        # Differentiates between default namespace and the rest
        if namespace == DEFAULT_NAMESPACE:
            return [cfg.CONF.namespace_sg.sg_allow_from_default]
        else:
            return [cfg.CONF.namespace_sg.sg_allow_from_namespaces]
