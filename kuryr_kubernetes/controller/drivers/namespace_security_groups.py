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
        LOG.exception("Namespace missing CRD annotations for selecting "
                      "the corresponding security group.")
        raise exceptions.ResourceNotReady(namespace)
    try:
        net_crd = kubernetes.get('%s/kuryrnets/%s' % (constants.K8S_API_CRD,
                                                      net_crd_name))
    except exceptions.K8sClientException:
        LOG.exception("Kubernetes Client Exception.")
        raise

    return net_crd


def _create_sg_rule(sg_id, direction, cidr, port=None, namespace=None):
    if port:
        sg_rule = utils.create_security_group_rule_body(
            sg_id, direction, port.get('port'),
            protocol=port.get('protocol'), cidr=cidr, namespace=namespace)
    else:
        sg_rule = utils.create_security_group_rule_body(
            sg_id, direction, port_range_min=1,
            port_range_max=65535, cidr=cidr, namespace=namespace)

    sgr_id = utils.create_security_group_rule(sg_rule)

    sg_rule['security_group_rule']['id'] = sgr_id
    return sg_rule


def _parse_rules(direction, crd, namespace):
    policy = crd['spec']['networkpolicy_spec']
    sg_id = crd['spec']['securityGroupId']

    ns_labels = namespace['metadata'].get('labels')
    ns_name = namespace['metadata'].get('name')
    ns_cidr = utils.get_namespace_subnet_cidr(namespace)

    rule_direction = 'from'
    crd_rules = crd['spec'].get('ingressSgRules')
    if direction == 'egress':
        rule_direction = 'to'
        crd_rules = crd['spec'].get('egressSgRules')

    matched = False
    rule_list = policy.get(direction, None)
    for rule_block in rule_list:
        for rule in rule_block.get(rule_direction, []):
            pod_selector = rule.get('podSelector')
            ns_selector = rule.get('namespaceSelector')
            if (ns_selector and ns_labels and
                    utils.match_selector(ns_selector, ns_labels)):
                if pod_selector:
                    pods = utils.get_pods(pod_selector, ns_name)
                    for pod in pods.get('items'):
                        pod_ip = utils.get_pod_ip(pod)
                        if 'ports' in rule_block:
                            for port in rule_block['ports']:
                                matched = True
                                crd_rules.append(_create_sg_rule(
                                    sg_id, direction, pod_ip, port=port,
                                    namespace=ns_name))
                        else:
                            matched = True
                            crd_rules.append(_create_sg_rule(
                                sg_id, direction, pod_ip,
                                namespace=ns_name))
                else:
                    if 'ports' in rule_block:
                        for port in rule_block['ports']:
                            matched = True
                            crd_rules.append(_create_sg_rule(
                                sg_id, direction, ns_cidr,
                                port=port, namespace=ns_name))
                    else:
                        matched = True
                        crd_rules.append(_create_sg_rule(
                            sg_id, direction, ns_cidr, namespace=ns_name))
    return matched, crd_rules


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
            neutron.create_security_group_rule(
                {
                    "security_group_rule": {
                        "direction": "ingress",
                        "remote_ip_prefix": crd_spec['subnetCIDR'],
                        "security_group_id": sg['id']
                    }
                })
        except n_exc.NeutronClientException as ex:
            LOG.error("Error creating security group for the namespace "
                      "%s: %s", namespace, ex)
            raise ex
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
        ns_name = namespace['metadata']['name']
        LOG.debug("Deleting sg rule for namespace: %s",
                  ns_name)

        knp_crds = utils.get_kuryrnetpolicy_crds()
        for crd in knp_crds.get('items'):
            crd_selector = crd['spec'].get('podSelector')
            ingress_rule_list = crd['spec'].get('ingressSgRules')
            egress_rule_list = crd['spec'].get('egressSgRules')
            i_rules = []
            e_rules = []

            matched = False
            for i_rule in ingress_rule_list:
                LOG.debug("Parsing ingress rule: %r", i_rule)
                rule_namespace = i_rule.get('namespace', None)

                if rule_namespace and rule_namespace == ns_name:
                    matched = True
                    utils.delete_security_group_rule(
                        i_rule['security_group_rule']['id'])
                else:
                    i_rules.append(i_rule)

            for e_rule in egress_rule_list:
                LOG.debug("Parsing egress rule: %r", e_rule)
                rule_namespace = e_rule.get('namespace', None)

                if rule_namespace and rule_namespace == ns_name:
                    matched = True
                    utils.delete_security_group_rule(
                        e_rule['security_group_rule']['id'])
                else:
                    e_rules.append(e_rule)

            if matched:
                utils.patch_kuryr_crd(crd, i_rules, e_rules, crd_selector)

    def create_namespace_sg_rules(self, namespace):
        kubernetes = clients.get_kubernetes_client()
        ns_name = namespace['metadata']['name']
        LOG.debug("Creating sg rule for namespace: %s", ns_name)
        namespace = kubernetes.get(
            '{}/namespaces/{}'.format(constants.K8S_API_BASE, ns_name))
        knp_crds = utils.get_kuryrnetpolicy_crds()
        for crd in knp_crds.get('items'):
            crd_selector = crd['spec'].get('podSelector')

            i_matched, i_rules = _parse_rules('ingress', crd, namespace)
            e_matched, e_rules = _parse_rules('egress', crd, namespace)

            if i_matched or e_matched:
                utils.patch_kuryr_crd(crd, i_rules,
                                      e_rules, crd_selector)

    def update_namespace_sg_rules(self, namespace):
        LOG.debug("Updating sg rule for namespace: %s",
                  namespace['metadata']['name'])
        self.delete_namespace_sg_rules(namespace)
        self.create_namespace_sg_rules(namespace)

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
