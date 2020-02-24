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


def _create_sg_rule(sg_id, direction, cidr, port=None, namespace=None):
    if port:
        sg_rule = driver_utils.create_security_group_rule_body(
            sg_id, direction, port.get('port'),
            protocol=port.get('protocol'), cidr=cidr, namespace=namespace)
    else:
        sg_rule = driver_utils.create_security_group_rule_body(
            sg_id, direction, port_range_min=1,
            port_range_max=65535, cidr=cidr, namespace=namespace)

    sgr_id = driver_utils.create_security_group_rule(sg_rule)

    sg_rule['security_group_rule']['id'] = sgr_id
    return sg_rule


def _get_crd_rule(crd_rules, container_port):
    """Returns a CRD rule that matches a container port

    Retrieves the CRD rule that contains a given port in
    the range of the rule ports.
    """
    for crd_rule in crd_rules:
        remote_ip_prefixes = crd_rule.get('remote_ip_prefixes')
        min_port = crd_rule['security_group_rule'].get('port_range_min')
        max_port = crd_rule['security_group_rule'].get('port_range_max')
        if (remote_ip_prefixes and (
                min_port >= container_port and
                container_port <= max_port)):
            return crd_rule


def _create_sg_rules_with_container_ports(matched_pods, container_ports,
                                          allow_all, namespace, matched,
                                          crd_rules, sg_id, direction,
                                          port, rule_selected_pod):
    """Create security group rules based on container ports

    If it's an allow from/to everywhere rule or a rule with a
    NamespaceSelector, updates a sg rule that might already exist
    and match the named port or creates a new one with the
    remote_ip_prefixes field containing the matched pod info.
    Otherwise, creates rules for each container port without
    a remote_ip_prefixes field.

    param matched_pods: List of dicts where the key is a container
                        port and value is the pods that have the port
    param container_ports: List of tuples with pods and port values
    param allow_all: True is it's an allow from/to everywhere rule,
                     False otherwise.
    param namespace: Namespace name
    param matched: If a sg rule was created for the NP rule
    param crd_rules: List of sg rules to update when patching the CRD
    param sg_id: ID of the security group
    param direction: String representing rule direction, ingress or egress
    param port: Dict containing port and protocol
    param rule_selected_pod: K8s Pod object selected by the rules selectors

    return: True if a sg rule was created, False otherwise.
    """
    for pod, container_port in container_ports:
        pod_namespace = pod['metadata']['namespace']
        pod_ip = driver_utils.get_pod_ip(pod)
        if not pod_ip:
            LOG.debug("Skipping SG rule creation for pod %s due to "
                      "no IP assigned", pod['metadata']['name'])
            continue

        pod_info = {pod_ip: pod_namespace}
        matched = True
        if allow_all or namespace:
            crd_rule = _get_crd_rule(crd_rules, container_port)
            if crd_rule:
                crd_rule['remote_ip_prefixes'].update(pod_info)
            else:
                if container_port in matched_pods:
                    matched_pods[container_port].update(pod_info)
                else:
                    matched_pods[container_port] = pod_info
        else:
            pod_ip = driver_utils.get_pod_ip(rule_selected_pod)
            if not pod_ip:
                LOG.debug("Skipping SG rule creation for pod %s due to no IP "
                          "assigned", rule_selected_pod['metadata']['name'])
                continue
            sg_rule = driver_utils.create_security_group_rule_body(
                sg_id, direction, container_port,
                protocol=port.get('protocol'),
                cidr=pod_ip, pods=pod_info)
            sgr_id = driver_utils.create_security_group_rule(sg_rule)
            sg_rule['security_group_rule']['id'] = sgr_id
            if sg_rule not in crd_rules:
                crd_rules.append(sg_rule)
    return matched


def _create_sg_rule_on_text_port(sg_id, direction, port, rule_selected_pods,
                                 crd_rules, matched, crd,
                                 allow_all=False, namespace=None):
    matched_pods = {}

    spec_pod_selector = crd['spec'].get('podSelector')
    policy_namespace = crd['metadata']['namespace']
    spec_pods = driver_utils.get_pods(
        spec_pod_selector, policy_namespace).get('items')
    if direction == 'ingress':
        for spec_pod in spec_pods:
            container_ports = driver_utils.get_ports(spec_pod, port)
            for rule_selected_pod in rule_selected_pods:
                matched = _create_sg_rules_with_container_ports(
                    matched_pods, container_ports, allow_all, namespace,
                    matched, crd_rules, sg_id, direction, port,
                    rule_selected_pod)
    elif direction == 'egress':
        for rule_selected_pod in rule_selected_pods:
            pod_label = rule_selected_pod['metadata'].get('labels')
            pod_ns = rule_selected_pod['metadata'].get('namespace')
            # NOTE(maysams) Do not allow egress traffic to the actual
            # set of pods the NP is enforced on.
            if (driver_utils.match_selector(spec_pod_selector, pod_label) and
                    policy_namespace == pod_ns):
                continue
            container_ports = driver_utils.get_ports(
                rule_selected_pod, port)
            matched = _create_sg_rules_with_container_ports(
                matched_pods, container_ports, allow_all,
                namespace, matched, crd_rules, sg_id, direction,
                port, rule_selected_pod)
    for container_port, pods in matched_pods.items():
        if allow_all:
            sg_rule = driver_utils.create_security_group_rule_body(
                sg_id, direction, container_port,
                protocol=port.get('protocol'),
                pods=pods)
        else:
            namespace_obj = driver_utils.get_namespace(namespace)
            namespace_cidr = driver_utils.get_namespace_subnet_cidr(
                namespace_obj)
            sg_rule = driver_utils.create_security_group_rule_body(
                sg_id, direction, container_port,
                protocol=port.get('protocol'), cidr=namespace_cidr,
                pods=pods)
        sgr_id = driver_utils.create_security_group_rule(sg_rule)
        sg_rule['security_group_rule']['id'] = sgr_id
        crd_rules.append(sg_rule)
    return matched


def _create_sg_rules(crd, pod, pod_selector, rule_block,
                     crd_rules, direction, matched, namespace=None,
                     allow_all=False):
    pod_labels = pod['metadata'].get('labels')
    pod_ip = driver_utils.get_pod_ip(pod)
    if not pod_ip:
        LOG.debug("Skipping SG rule creation for pod %s due to "
                  "no IP assigned", pod['metadata']['name'])
        return None

    # NOTE (maysams) No need to differentiate between podSelector
    # with empty value or with '{}', as they have same result in here.
    if pod_selector:
        if driver_utils.match_selector(pod_selector, pod_labels):
            sg_id = crd['spec']['securityGroupId']
            if 'ports' in rule_block:
                for port in rule_block['ports']:
                    if type(port.get('port')) is not int:
                        matched = _create_sg_rule_on_text_port(
                            sg_id, direction, port, [pod],
                            crd_rules, matched, crd)
                    else:
                        matched = True
                        sg_rule = _create_sg_rule(
                            sg_id, direction, cidr=pod_ip, port=port,
                            namespace=namespace)
                        crd_rules.append(sg_rule)
            else:
                matched = True
                sg_rule = _create_sg_rule(
                    sg_id, direction, cidr=pod_ip, namespace=namespace)
                crd_rules.append(sg_rule)
    else:
        # NOTE (maysams) When a policy with namespaceSelector and text port
        # is applied the port on the pods needs to be retrieved.
        sg_id = crd['spec']['securityGroupId']
        if 'ports' in rule_block:
            for port in rule_block['ports']:
                if type(port.get('port')) is not int:
                    matched = (
                        _create_sg_rule_on_text_port(
                            sg_id, direction, port, [pod],
                            crd_rules, matched, crd,
                            allow_all=allow_all, namespace=namespace))
    return matched


def _parse_selectors_on_pod(crd, pod, pod_selector, namespace_selector,
                            rule_block, crd_rules, direction, matched):
    pod_namespace = pod['metadata']['namespace']
    pod_namespace_labels = _get_namespace_labels(pod_namespace)
    policy_namespace = crd['metadata']['namespace']

    if namespace_selector == {}:
        matched = _create_sg_rules(crd, pod, pod_selector, rule_block,
                                   crd_rules, direction, matched,
                                   allow_all=True)
    elif namespace_selector:
        if (pod_namespace_labels and
            driver_utils.match_selector(namespace_selector,
                                        pod_namespace_labels)):
            matched = _create_sg_rules(crd, pod, pod_selector,
                                       rule_block, crd_rules,
                                       direction, matched,
                                       namespace=pod_namespace)
    else:
        if pod_namespace == policy_namespace:
            matched = _create_sg_rules(crd, pod, pod_selector, rule_block,
                                       crd_rules, direction, matched,
                                       namespace=pod_namespace)
    return matched, crd_rules


def _parse_selectors_on_namespace(crd, direction, pod_selector,
                                  ns_selector, rule_block, crd_rules,
                                  namespace, matched):
    ns_name = namespace['metadata'].get('name')
    ns_labels = namespace['metadata'].get('labels')
    sg_id = crd['spec']['securityGroupId']

    if (ns_selector and ns_labels and
            driver_utils.match_selector(ns_selector, ns_labels)):
        if pod_selector:
            pods = driver_utils.get_pods(pod_selector, ns_name).get('items')
            if 'ports' in rule_block:
                for port in rule_block['ports']:
                    if type(port.get('port')) is not int:
                        matched = (
                            _create_sg_rule_on_text_port(
                                sg_id, direction, port, pods,
                                crd_rules, matched, crd))
                    else:
                        matched = True
                        for pod in pods:
                            pod_ip = driver_utils.get_pod_ip(pod)
                            if not pod_ip:
                                pod_name = pod['metadata']['name']
                                LOG.debug("Skipping SG rule creation for pod "
                                          "%s due to no IP assigned", pod_name)
                                continue
                            crd_rules.append(_create_sg_rule(
                                sg_id, direction, pod_ip, port=port,
                                namespace=ns_name))
            else:
                for pod in pods:
                    pod_ip = driver_utils.get_pod_ip(pod)
                    if not pod_ip:
                        pod_name = pod['metadata']['name']
                        LOG.debug("Skipping SG rule creation for pod %s due"
                                  " to no IP assigned", pod_name)
                        continue
                    matched = True
                    crd_rules.append(_create_sg_rule(
                        sg_id, direction, pod_ip,
                        namespace=ns_name))
        else:
            ns_pods = driver_utils.get_pods(ns_selector)['items']
            ns_cidr = driver_utils.get_namespace_subnet_cidr(namespace)
            if 'ports' in rule_block:
                for port in rule_block['ports']:
                    if type(port.get('port')) is not int:
                        matched = (
                            _create_sg_rule_on_text_port(
                                sg_id, direction, port, ns_pods,
                                crd_rules, matched, crd))
                    else:
                        matched = True
                        crd_rules.append(_create_sg_rule(
                            sg_id, direction, ns_cidr,
                            port=port, namespace=ns_name))
            else:
                matched = True
                crd_rules.append(_create_sg_rule(
                    sg_id, direction, ns_cidr,
                    namespace=ns_name))
    return matched, crd_rules


def _parse_rules(direction, crd, pod=None, namespace=None):
    policy = crd['spec']['networkpolicy_spec']
    rule_direction = 'from'
    crd_rules = crd['spec'].get('ingressSgRules')
    if direction == 'egress':
        rule_direction = 'to'
        crd_rules = crd['spec'].get('egressSgRules')

    matched = False
    rule_list = policy.get(direction, [])
    for rule_block in rule_list:
        for rule in rule_block.get(rule_direction, []):
            namespace_selector = rule.get('namespaceSelector')
            pod_selector = rule.get('podSelector')
            if pod:
                matched, crd_rules = _parse_selectors_on_pod(
                    crd, pod, pod_selector, namespace_selector,
                    rule_block, crd_rules, direction, matched)
            elif namespace:
                matched, crd_rules = _parse_selectors_on_namespace(
                    crd, direction, pod_selector, namespace_selector,
                    rule_block, crd_rules, namespace, matched)

        # NOTE(maysams): Cover the case of a network policy that allows
        # from everywhere on a named port, e.g., when there is no 'from'
        # specified.
        if pod and not matched:
            for port in rule_block.get('ports', []):
                if type(port.get('port')) is not int:
                    sg_id = crd['spec']['securityGroupId']
                    if (not rule_block.get(rule_direction, [])
                            or direction == "ingress"):
                        matched = (_create_sg_rule_on_text_port(
                            sg_id, direction, port, [pod],
                            crd_rules, matched, crd,
                            allow_all=True))
    return matched, crd_rules


def _parse_rules_on_delete_namespace(rule_list, direction, ns_name):
    matched = False
    rules = []
    for rule in rule_list:
        LOG.debug('Parsing %(dir)s Rule %(r)s', {'dir': direction,
                                                 'r': rule})
        rule_namespace = rule.get('namespace', None)
        remote_ip_prefixes = rule.get('remote_ip_prefixes', {})
        if rule_namespace and rule_namespace == ns_name:
            matched = True
            driver_utils.delete_security_group_rule(
                rule['security_group_rule']['id'])
        for remote_ip, namespace in list(remote_ip_prefixes.items()):
            if namespace == ns_name:
                matched = True
                remote_ip_prefixes.pop(remote_ip)
                if remote_ip_prefixes:
                    rule['remote_ip_prefixes'] = remote_ip_prefixes
                    rules.append(rule)
        else:
            rules.append(rule)
    return matched, rules


def _parse_rules_on_delete_pod(rule_list, direction, pod_ip):
    matched = False
    rules = []
    for rule in rule_list:
        LOG.debug('Parsing %(dir)s Rule %(r)s', {'dir': direction,
                                                 'r': rule})
        remote_ip_prefix = rule['security_group_rule'].get(
            'remote_ip_prefix')
        remote_ip_prefixes = rule.get('remote_ip_prefixes', {})
        if remote_ip_prefix and remote_ip_prefix == pod_ip:
            matched = True
            driver_utils.delete_security_group_rule(
                rule['security_group_rule']['id'])
        elif remote_ip_prefixes:
            if pod_ip in remote_ip_prefixes:
                matched = True
                remote_ip_prefixes.pop(pod_ip)
                if remote_ip_prefixes:
                    rule['remote_ip_prefixes'] = remote_ip_prefixes
                    rules.append(rule)
        else:
            rules.append(rule)
    return matched, rules


def _get_pod_sgs(pod, project_id):
    sg_list = []

    pod_labels = pod['metadata'].get('labels')
    pod_namespace = pod['metadata']['namespace']

    knp_crds = driver_utils.get_kuryrnetpolicy_crds(
        namespace=pod_namespace)
    for crd in knp_crds.get('items'):
        pod_selector = crd['spec'].get('podSelector')
        if pod_selector:
            if driver_utils.match_selector(pod_selector, pod_labels):
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
        crd_pod_selectors = []
        knp_crds = driver_utils.get_kuryrnetpolicy_crds()
        for crd in knp_crds.get('items'):
            crd_selector = crd['spec'].get('podSelector')

            i_matched, i_rules = _parse_rules('ingress', crd, pod=pod)
            e_matched, e_rules = _parse_rules('egress', crd, pod=pod)

            if i_matched or e_matched:
                driver_utils.patch_kuryrnetworkpolicy_crd(crd, i_rules,
                                                          e_rules,
                                                          crd_selector)
            if i_matched:
                crd_pod_selectors.append(crd_selector)
        return crd_pod_selectors

    def delete_sg_rules(self, pod):
        LOG.debug("Deleting sg rule for pod: %s", pod['metadata']['name'])
        pod_ip = driver_utils.get_pod_ip(pod)
        if not pod_ip:
            LOG.debug("Skipping SG rule deletion as pod %s has no IP assigned",
                      pod['metadata']['name'])
            return None
        crd_pod_selectors = []
        knp_crds = driver_utils.get_kuryrnetpolicy_crds()
        for crd in knp_crds.get('items'):
            crd_selector = crd['spec'].get('podSelector')
            ingress_rule_list = crd['spec'].get('ingressSgRules')
            egress_rule_list = crd['spec'].get('egressSgRules')

            i_matched, i_rules = _parse_rules_on_delete_pod(
                ingress_rule_list, "ingress", pod_ip)
            e_matched, e_rules = _parse_rules_on_delete_pod(
                egress_rule_list, "egress", pod_ip)

            if i_matched or e_matched:
                driver_utils.patch_kuryrnetworkpolicy_crd(crd, i_rules,
                                                          e_rules,
                                                          crd_selector)
            if i_matched:
                crd_pod_selectors.append(crd_selector)
        return crd_pod_selectors

    def update_sg_rules(self, pod):
        LOG.debug("Updating sg rule for pod: %s", pod['metadata']['name'])
        crd_pod_selectors = []
        crd_pod_selectors.extend(self.delete_sg_rules(pod))
        crd_pod_selectors.extend(self.create_sg_rules(pod))
        return crd_pod_selectors

    def delete_namespace_sg_rules(self, namespace):
        ns_name = namespace['metadata']['name']
        LOG.debug("Deleting sg rule for namespace: %s",
                  ns_name)

        crd_selectors = []
        knp_crds = driver_utils.get_kuryrnetpolicy_crds()
        for crd in knp_crds.get('items'):
            crd_selector = crd['spec'].get('podSelector')
            ingress_rule_list = crd['spec'].get('ingressSgRules')
            egress_rule_list = crd['spec'].get('egressSgRules')

            i_matched, i_rules = _parse_rules_on_delete_namespace(
                ingress_rule_list, "ingress", ns_name)
            e_matched, e_rules = _parse_rules_on_delete_namespace(
                egress_rule_list, "egress", ns_name)

            if i_matched or e_matched:
                driver_utils.patch_kuryrnetworkpolicy_crd(
                    crd, i_rules, e_rules, crd_selector)
            if i_matched:
                crd_selectors.append(crd_selector)
        return crd_selectors

    def create_namespace_sg_rules(self, namespace):
        ns_name = namespace['metadata']['name']
        LOG.debug("Creating sg rule for namespace: %s", ns_name)
        crd_selectors = []
        knp_crds = driver_utils.get_kuryrnetpolicy_crds()
        for crd in knp_crds.get('items'):
            crd_selector = crd['spec'].get('podSelector')

            i_matched, i_rules = _parse_rules(
                'ingress', crd, namespace=namespace)
            e_matched, e_rules = _parse_rules(
                'egress', crd, namespace=namespace)

            if i_matched or e_matched:
                driver_utils.patch_kuryrnetworkpolicy_crd(crd, i_rules,
                                                          e_rules,
                                                          crd_selector)
            if i_matched:
                crd_selectors.append(crd_selector)
        return crd_selectors

    def update_namespace_sg_rules(self, namespace):
        LOG.debug("Updating sg rule for namespace: %s",
                  namespace['metadata']['name'])
        crd_selectors = []
        crd_selectors.extend(self.delete_namespace_sg_rules(namespace))
        crd_selectors.extend(self.create_namespace_sg_rules(namespace))
        return crd_selectors

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
