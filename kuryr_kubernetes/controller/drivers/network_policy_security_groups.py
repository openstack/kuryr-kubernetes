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


from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions

from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


OPERATORS_WITH_VALUES = [constants.K8S_OPERATOR_IN,
                         constants.K8S_OPERATOR_NOT_IN]


def _get_kuryrnetpolicy_crds(namespace=None):
    kubernetes = clients.get_kubernetes_client()

    try:
        if namespace:
            knp_path = '{}/{}/kuryrnetpolicies'.format(
                constants.K8S_API_CRD_NAMESPACES, namespace)
        else:
            knp_path = constants.K8S_API_CRD_KURYRNETPOLICIES
        LOG.debug("K8s API Query %s", knp_path)
        knps = kubernetes.get(knp_path)
        LOG.debug("Return Kuryr Network Policies with label %s", knps)
    except exceptions.K8sResourceNotFound:
        LOG.exception("KuryrNetPolicy CRD not found")
        raise
    except exceptions.K8sClientException:
        LOG.exception("Kubernetes Client Exception")
        raise
    return knps


def _match_expressions(expressions, labels):
    for exp in expressions:
        exp_op = exp['operator'].lower()
        if labels:
            if exp_op in OPERATORS_WITH_VALUES:
                exp_values = exp['values']
                label_value = labels.get(str(exp['key']), None)
                if exp_op == constants.K8S_OPERATOR_IN:
                    if label_value is None or label_value not in exp_values:
                            return False
                elif exp_op == constants.K8S_OPERATOR_NOT_IN:
                    if label_value in exp_values:
                        return False
            else:
                if exp_op == constants.K8S_OPERATOR_EXISTS:
                    exists = labels.get(str(exp['key']), None)
                    if exists is None:
                        return False
                elif exp_op == constants.K8S_OPERATOR_DOES_NOT_EXIST:
                    exists = labels.get(str(exp['key']), None)
                    if exists is not None:
                        return False
        else:
            if exp_op in (constants.K8S_OPERATOR_IN,
                          constants.K8S_OPERATOR_EXISTS):
                return False
    return True


def _match_labels(crd_labels, labels):
    for crd_key, crd_value in crd_labels.items():
        label_value = labels.get(crd_key, None)
        if not label_value or crd_value != label_value:
                return False
    return True


def _match_selector(selector, labels):
    crd_labels = selector.get('matchLabels', None)
    crd_expressions = selector.get('matchExpressions', None)

    match_exp = match_lb = True
    if crd_expressions:
        match_exp = _match_expressions(crd_expressions,
                                       labels)
    if crd_labels and labels:
        match_lb = _match_labels(crd_labels, labels)
    return match_exp and match_lb


def _get_namespace_labels(namespace):
    kubernetes = clients.get_kubernetes_client()

    try:
        path = '{}/{}'.format(
            constants.K8S_API_NAMESPACES, namespace)
        LOG.debug("K8s API Query %s", path)
        namespaces = kubernetes.get(path)
        LOG.debug("Return Namespace: %s", namespaces)
    except exceptions.K8sResourceNotFound:
        LOG.exception("Namespace not found")
        raise
    except exceptions.K8sClientException:
        LOG.exception("Kubernetes Client Exception")
        raise
    return namespaces['metadata'].get('labels')


def _create_sg_rules(crd, pod, namespace_selector, pod_selector,
                     rule_block, crd_rules, direction,
                     matched):
    pod_labels = pod['metadata'].get('labels')

    # NOTE (maysams) No need to differentiate between podSelector
    # with empty value or with '{}', as they have same result in here.
    if (pod_selector and
            _match_selector(pod_selector, pod_labels)):
        matched = True
        pod_ip = driver_utils.get_pod_ip(pod)
        sg_id = crd['spec']['securityGroupId']
        if 'ports' in rule_block:
            for port in rule_block['ports']:
                sg_rule = driver_utils.create_security_group_rule_body(
                    sg_id, direction, port.get('port'),
                    protocol=port.get('protocol'), cidr=pod_ip)
                sgr_id = driver_utils.create_security_group_rule(sg_rule)
                sg_rule['security_group_rule']['id'] = sgr_id
                crd_rules.append(sg_rule)
        else:
            sg_rule = driver_utils.create_security_group_rule_body(
                sg_id, direction,
                port_range_min=1,
                port_range_max=65535,
                cidr=pod_ip)
            sgr_id = driver_utils.create_security_group_rule(sg_rule)
            sg_rule['security_group_rule']['id'] = sgr_id
            crd_rules.append(sg_rule)
    return matched


def _parse_rules(direction, crd, pod):
    policy = crd['spec']['networkpolicy_spec']

    pod_namespace = pod['metadata']['namespace']
    pod_namespace_labels = _get_namespace_labels(pod_namespace)
    policy_namespace = crd['metadata']['namespace']

    rule_direction = 'from'
    crd_rules = crd['spec'].get('ingressSgRules')
    if direction == 'egress':
        rule_direction = 'to'
        crd_rules = crd['spec'].get('egressSgRules')

    matched = False
    rule_list = policy.get(direction, None)
    for rule_block in rule_list:
        for rule in rule_block.get(rule_direction, []):
            namespace_selector = rule.get('namespaceSelector')
            pod_selector = rule.get('podSelector')
            if namespace_selector == {}:
                if _create_sg_rules(crd, pod, namespace_selector,
                                    pod_selector, rule_block, crd_rules,
                                    direction, matched):
                    matched = True
            elif namespace_selector:
                if (pod_namespace_labels and
                    _match_selector(namespace_selector,
                                    pod_namespace_labels)):
                    if _create_sg_rules(crd, pod, namespace_selector,
                                        pod_selector, rule_block, crd_rules,
                                        direction, matched):
                        matched = True
            else:
                if pod_namespace == policy_namespace:
                    if _create_sg_rules(crd, pod, namespace_selector,
                                        pod_selector, rule_block, crd_rules,
                                        direction, matched):
                        matched = True
    return matched, crd_rules


def _get_pod_sgs(pod, project_id):
    sg_list = []

    pod_labels = pod['metadata'].get('labels')
    pod_namespace = pod['metadata']['namespace']

    knp_crds = _get_kuryrnetpolicy_crds(namespace=pod_namespace)
    for crd in knp_crds.get('items'):
        pod_selector = crd['spec'].get('podSelector')
        if pod_selector:
            if _match_selector(pod_selector, pod_labels):
                LOG.debug("Appending %s",
                          str(crd['spec']['securityGroupId']))
                sg_list.append(str(crd['spec']['securityGroupId']))
        else:
            LOG.debug("Appending %s", str(crd['spec']['securityGroupId']))
            sg_list.append(str(crd['spec']['securityGroupId']))

    # NOTE(maysams) Pods that are not selected by any Networkpolicy
    # are fully accessible. Thus, the default security group is associated.
    if not sg_list:
        sg_list = config.CONF.neutron_defaults.pod_security_groups
        if not sg_list:
            raise cfg.RequiredOptError('pod_security_groups',
                                       cfg.OptGroup('neutron_defaults'))

    return sg_list[:]


class NetworkPolicySecurityGroupsDriver(base.PodSecurityGroupsDriver):
    """Provides security groups for pods based on network policies"""

    def get_security_groups(self, pod, project_id):
        return _get_pod_sgs(pod, project_id)

    def create_sg_rules(self, pod):
        LOG.debug("Creating sg rule for pod: %s", pod['metadata']['name'])
        knp_crds = _get_kuryrnetpolicy_crds()
        for crd in knp_crds.get('items'):
            crd_selector = crd['spec'].get('podSelector')

            i_matched, i_rules = _parse_rules('ingress', crd, pod)
            e_matched, e_rules = _parse_rules('egress', crd, pod)

            if i_matched or e_matched:
                driver_utils.patch_kuryr_crd(crd, i_rules,
                                             e_rules, crd_selector)

    def delete_sg_rules(self, pod):
        LOG.debug("Deleting sg rule for pod: %s", pod['metadata']['name'])
        pod_ip = driver_utils.get_pod_ip(pod)

        knp_crds = _get_kuryrnetpolicy_crds()
        for crd in knp_crds.get('items'):
            crd_selector = crd['spec'].get('podSelector')
            ingress_rule_list = crd['spec'].get('ingressSgRules')
            egress_rule_list = crd['spec'].get('egressSgRules')
            i_rules = []
            e_rules = []

            matched = False
            for i_rule in ingress_rule_list:
                LOG.debug("Parsing ingress rule: %r", i_rule)
                remote_ip_prefix = i_rule['security_group_rule'].get(
                    'remote_ip_prefix')
                if remote_ip_prefix and remote_ip_prefix == pod_ip:
                    matched = True
                    driver_utils.delete_security_group_rule(
                        i_rule['security_group_rule']['id'])
                else:
                    i_rules.append(i_rule)

            for e_rule in egress_rule_list:
                LOG.debug("Parsing egress rule: %r", e_rule)
                remote_ip_prefix = e_rule['security_group_rule'].get(
                    'remote_ip_prefix')
                if remote_ip_prefix and remote_ip_prefix == pod_ip:
                    matched = True
                    driver_utils.delete_security_group_rule(
                        e_rule['security_group_rule']['id'])
                else:
                    e_rules.append(e_rule)

            if matched:
                driver_utils.patch_kuryr_crd(crd, i_rules, e_rules,
                                             crd_selector)

    def update_sg_rules(self, pod):
        LOG.debug("Updating sg rule for pod: %s", pod['metadata']['name'])
        self.delete_sg_rules(pod)
        self.create_sg_rules(pod)

    def create_namespace_sg(self, namespace, project_id, crd_spec):
        LOG.debug("Security group driver does not create SGs for the "
                  "namespaces.")
        return {}

    def delete_sg(self, sg_id):
        LOG.debug("Security group driver does not implement deleting "
                  "SGs.")


class NetworkPolicyServiceSecurityGroupsDriver(
        base.ServiceSecurityGroupsDriver):
    """Provides security groups for services based on network policies"""

    def get_security_groups(self, service, project_id):
        sg_list = []
        svc_namespace = service['metadata']['namespace']
        svc_selector = service['spec'].get('selector')

        # skip is no selector
        if svc_selector:
            # get affected pods by svc selector
            pods = driver_utils.get_pods({'selector': svc_selector},
                                         svc_namespace).get('items')
            # NOTE(ltomasbo): We assume all the pods pointed by a service
            # have the same labels, and the same policy will be applied to
            # all of them. Hence only considering the security groups applied
            # to the first one.
            if pods:
                return _get_pod_sgs(pods[0], project_id)
        return sg_list[:]
