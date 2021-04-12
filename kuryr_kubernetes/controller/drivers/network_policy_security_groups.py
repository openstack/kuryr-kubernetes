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

from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


def _get_namespace_labels(namespace):
    kubernetes = clients.get_kubernetes_client()

    try:
        path = '{}/{}'.format(constants.K8S_API_NAMESPACES, namespace)
        namespaces = kubernetes.get(path)
        LOG.debug("Return Namespace: %s", namespaces)
    except exceptions.K8sResourceNotFound:
        LOG.exception("Namespace not found")
        raise
    except exceptions.K8sClientException:
        LOG.exception("Kubernetes Client Exception")
        raise
    return namespaces['metadata'].get('labels')


def _create_sg_rules_with_container_ports(container_ports, matched):
    """Checks if security group rules based on container ports will be updated

    param container_ports: List of tuples with pods and port values
    param matched: If a sg rule was created for the NP rule

    return: True if a sg rule needs to be created, False otherwise.
    """
    for pod, container_port in container_ports:
        pod_ip = driver_utils.get_pod_ip(pod)
        if not pod_ip:
            LOG.debug("Skipping SG rule creation for pod %s due to "
                      "no IP assigned", pod['metadata']['name'])
            continue
        return matched
    return False


def _create_sg_rule_on_text_port(direction, port, rule_selected_pods, matched,
                                 crd):
    spec_pod_selector = crd['spec'].get('podSelector')
    policy_namespace = crd['metadata']['namespace']
    spec_pods = driver_utils.get_pods(
        spec_pod_selector, policy_namespace).get('items')
    if direction == 'ingress':
        for spec_pod in spec_pods:
            container_ports = driver_utils.get_ports(spec_pod, port)
            matched = _create_sg_rules_with_container_ports(
                container_ports, matched)
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
                container_ports, matched)
    return matched


def _create_sg_rules(crd, pod, pod_selector, rule_block, direction, matched):
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
            if 'ports' in rule_block:
                for port in rule_block['ports']:
                    if type(port.get('port')) is not int:
                        matched = _create_sg_rule_on_text_port(
                            direction, port, [pod], matched, crd)
                    else:
                        matched = True
            else:
                matched = True
    else:
        # NOTE (maysams) When a policy with namespaceSelector and text port
        # is applied the port on the pods needs to be retrieved.
        if 'ports' in rule_block:
            for port in rule_block['ports']:
                if type(port.get('port')) is not int:
                    matched = _create_sg_rule_on_text_port(
                        direction, port, [pod], matched, crd)
    return matched


def _parse_selectors_on_pod(crd, pod, pod_selector, namespace_selector,
                            rule_block, direction, matched):
    pod_namespace = pod['metadata']['namespace']
    pod_namespace_labels = _get_namespace_labels(pod_namespace)
    policy_namespace = crd['metadata']['namespace']

    if namespace_selector == {}:
        matched = _create_sg_rules(crd, pod, pod_selector, rule_block,
                                   direction, matched)
    elif namespace_selector:
        if (pod_namespace_labels and
            driver_utils.match_selector(namespace_selector,
                                        pod_namespace_labels)):
            matched = _create_sg_rules(crd, pod, pod_selector,
                                       rule_block, direction, matched)
    else:
        if pod_namespace == policy_namespace:
            matched = _create_sg_rules(crd, pod, pod_selector, rule_block,
                                       direction, matched)
    return matched


def _parse_selectors_on_namespace(crd, direction, pod_selector,
                                  ns_selector, rule_block, namespace, matched):
    ns_name = namespace['metadata'].get('name')
    ns_labels = namespace['metadata'].get('labels')

    if (ns_selector and ns_labels and
            driver_utils.match_selector(ns_selector, ns_labels)):
        if pod_selector:
            pods = driver_utils.get_pods(pod_selector, ns_name).get('items')
            if 'ports' in rule_block:
                for port in rule_block['ports']:
                    if type(port.get('port')) is not int:
                        matched = (
                            _create_sg_rule_on_text_port(
                                direction, port, pods, matched, crd))
                    else:
                        for pod in pods:
                            pod_ip = driver_utils.get_pod_ip(pod)
                            if not pod_ip:
                                pod_name = pod['metadata']['name']
                                LOG.debug("Skipping SG rule creation for pod "
                                          "%s due to no IP assigned", pod_name)
                                continue
                            matched = True
            else:
                for pod in pods:
                    pod_ip = driver_utils.get_pod_ip(pod)
                    if not pod_ip:
                        pod_name = pod['metadata']['name']
                        LOG.debug("Skipping SG rule creation for pod %s due"
                                  " to no IP assigned", pod_name)
                        continue
                    matched = True
        else:
            ns_pods = driver_utils.get_pods(ns_selector)['items']
            if 'ports' in rule_block:
                for port in rule_block['ports']:
                    if type(port.get('port')) is not int:
                        matched = (
                            _create_sg_rule_on_text_port(
                                direction, port, ns_pods, matched, crd))
                    else:
                        matched = True
            else:
                matched = True
    return matched


def _parse_rules(direction, crd, policy, pod=None, namespace=None):
    rule_direction = 'from'
    if direction == 'egress':
        rule_direction = 'to'

    matched = False
    rule_list = policy.get(direction, [])
    for rule_block in rule_list:
        for rule in rule_block.get(rule_direction, []):
            namespace_selector = rule.get('namespaceSelector')
            pod_selector = rule.get('podSelector')
            if pod:
                matched = _parse_selectors_on_pod(
                    crd, pod, pod_selector, namespace_selector,
                    rule_block, direction, matched)
            elif namespace:
                matched = _parse_selectors_on_namespace(
                    crd, direction, pod_selector, namespace_selector,
                    rule_block, namespace, matched)

        # NOTE(maysams): Cover the case of a network policy that allows
        # from everywhere on a named port, e.g., when there is no 'from'
        # specified.
        if pod and not matched:
            for port in rule_block.get('ports', []):
                if type(port.get('port')) is not int:
                    if (not rule_block.get(rule_direction, [])
                            or direction == "ingress"):
                        matched = _create_sg_rule_on_text_port(
                            direction, port, [pod], matched, crd)
    return matched


def _parse_rules_on_delete_namespace(rule_list, direction, ns_name):
    for rule in rule_list:
        LOG.debug('Parsing %(dir)s Rule %(r)s', {'dir': direction, 'r': rule})
        rule_namespace = rule.get('namespace', None)
        affectedPods = rule.get('affectedPods', [])
        if rule_namespace and rule_namespace == ns_name:
            return True
        elif affectedPods:
            for pod_info in affectedPods:
                if pod_info['podNamespace'] == ns_name:
                    return True
    return False


def _parse_rules_on_delete_pod(rule_list, direction, pod_ip):
    for rule in rule_list:
        LOG.debug('Parsing %(dir)s Rule %(r)s', {'dir': direction, 'r': rule})
        remote_ip_prefix = rule['sgRule'].get('remote_ip_prefix')
        affectedPods = rule.get('affectedPods', [])
        if remote_ip_prefix and remote_ip_prefix == pod_ip:
            return True
        elif affectedPods:
            for pod_info in affectedPods:
                if pod_info['podIP'] == pod_ip:
                    return True
    return False


def _get_pod_sgs(pod):
    sg_list = []

    pod_labels = pod['metadata'].get('labels')
    pod_namespace = pod['metadata']['namespace']

    knp_crds = driver_utils.get_kuryrnetworkpolicy_crds(
        namespace=pod_namespace)
    for crd in knp_crds:
        pod_selector = crd['spec'].get('podSelector')
        if driver_utils.match_selector(pod_selector, pod_labels):
            sg_id = crd['status'].get('securityGroupId')
            if not sg_id:
                # NOTE(dulek): We could just assume KNP handler will apply it,
                #              but it's possible that when it gets this pod it
                #              will have no IP yet and will be skipped.
                LOG.warning('SG for NP %s not created yet, will retry.',
                            utils.get_res_unique_name(crd))
                raise exceptions.ResourceNotReady(pod)
            LOG.debug("Appending %s", crd['status']['securityGroupId'])
            sg_list.append(crd['status']['securityGroupId'])

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
        return _get_pod_sgs(pod)

    def create_sg_rules(self, pod):
        LOG.debug("Creating SG rules for pod: %s", pod['metadata']['name'])
        crd_pod_selectors = []
        knp_crds = driver_utils.get_kuryrnetworkpolicy_crds()
        nps = driver_utils.get_networkpolicies()
        pairs = driver_utils.zip_knp_np(knp_crds, nps)

        for crd, policy in pairs:
            crd_selector = crd['spec'].get('podSelector')
            spec = policy.get('spec')

            i_matched = _parse_rules('ingress', crd, spec, pod=pod)
            e_matched = _parse_rules('egress', crd, spec, pod=pod)

            if i_matched or e_matched:
                try:
                    driver_utils.bump_networkpolicy(crd)
                except exceptions.K8sResourceNotFound:
                    # The NP got deleted, ignore it.
                    continue
            if i_matched:
                crd_pod_selectors.append(crd_selector)
        return crd_pod_selectors

    def delete_sg_rules(self, pod):
        LOG.debug("Deleting SG rules for pod: %s", pod['metadata']['name'])
        pod_ip = driver_utils.get_pod_ip(pod)
        crd_pod_selectors = []
        if not pod_ip:
            LOG.debug("Skipping SG rule deletion as pod %s has no IP assigned",
                      pod['metadata']['name'])
            return crd_pod_selectors
        knp_crds = driver_utils.get_kuryrnetworkpolicy_crds()
        for crd in knp_crds:
            crd_selector = crd['spec'].get('podSelector')
            ingress_rule_list = crd['spec'].get('ingressSgRules')
            egress_rule_list = crd['spec'].get('egressSgRules')

            i_matched = _parse_rules_on_delete_pod(
                ingress_rule_list, "ingress", pod_ip)
            e_matched = _parse_rules_on_delete_pod(
                egress_rule_list, "egress", pod_ip)

            if i_matched or e_matched:
                try:
                    driver_utils.bump_networkpolicy(crd)
                except exceptions.K8sResourceNotFound:
                    # The NP got deleted, ignore it.
                    continue
            if i_matched:
                crd_pod_selectors.append(crd_selector)
        return crd_pod_selectors

    def update_sg_rules(self, pod):
        LOG.debug("Updating SG rules for pod: %s", pod['metadata']['name'])
        # FIXME(dulek): No need to bump twice.
        crd_pod_selectors = []
        crd_pod_selectors.extend(self.delete_sg_rules(pod))
        crd_pod_selectors.extend(self.create_sg_rules(pod))
        return crd_pod_selectors

    def delete_namespace_sg_rules(self, namespace):
        ns_name = namespace['metadata']['name']
        LOG.debug("Deleting SG rules for namespace: %s", ns_name)

        crd_selectors = []
        knp_crds = driver_utils.get_kuryrnetworkpolicy_crds()
        for crd in knp_crds:
            crd_selector = crd['spec'].get('podSelector')
            ingress_rule_list = crd['spec'].get('ingressSgRules')
            egress_rule_list = crd['spec'].get('egressSgRules')

            i_matched = _parse_rules_on_delete_namespace(
                ingress_rule_list, "ingress", ns_name)
            e_matched = _parse_rules_on_delete_namespace(
                egress_rule_list, "egress", ns_name)

            if i_matched or e_matched:
                try:
                    driver_utils.bump_networkpolicy(crd)
                except exceptions.K8sResourceNotFound:
                    # The NP got deleted, ignore it.
                    continue
            if i_matched:
                crd_selectors.append(crd_selector)
        return crd_selectors

    def create_namespace_sg_rules(self, namespace):
        ns_name = namespace['metadata']['name']
        LOG.debug("Creating SG rules for namespace: %s", ns_name)
        crd_selectors = []
        knp_crds = driver_utils.get_kuryrnetworkpolicy_crds()
        nps = driver_utils.get_networkpolicies()
        pairs = driver_utils.zip_knp_np(knp_crds, nps)
        for crd, policy in pairs:
            crd_selector = crd['spec'].get('podSelector')
            spec = policy.get('spec')
            i_matched = _parse_rules('ingress', crd, spec, namespace=namespace)
            e_matched = _parse_rules('egress', crd, spec, namespace=namespace)

            if i_matched or e_matched:
                try:
                    driver_utils.bump_networkpolicy(crd)
                except exceptions.K8sResourceNotFound:
                    # The NP got deleted, ignore it.
                    continue
            if i_matched:
                crd_selectors.append(crd_selector)
        return crd_selectors

    def update_namespace_sg_rules(self, namespace):
        LOG.debug("Updating SG rules for namespace: %s",
                  namespace['metadata']['name'])
        crd_selectors = []
        crd_selectors.extend(self.delete_namespace_sg_rules(namespace))
        crd_selectors.extend(self.create_namespace_sg_rules(namespace))
        return crd_selectors


class NetworkPolicyServiceSecurityGroupsDriver(
        base.ServiceSecurityGroupsDriver):
    """Provides security groups for services based on network policies"""

    def get_security_groups(self, service, project_id):
        sg_list = []
        svc_namespace = service['metadata']['namespace']
        svc_selector = service['spec'].get('selector')

        if svc_selector:
            # get affected pods by svc selector
            pods = driver_utils.get_pods({'selector': svc_selector},
                                         svc_namespace).get('items')
            # NOTE(ltomasbo): We assume all the pods pointed by a service
            # have the same labels, and the same policy will be applied to
            # all of them. Hence only considering the security groups applied
            # to the first one.
            if pods:
                return _get_pod_sgs(pods[0])
        else:
            # NOTE(maysams): Network Policy is not enforced on Services
            # without selectors.
            sg_list = config.CONF.neutron_defaults.pod_security_groups
            if not sg_list:
                raise cfg.RequiredOptError('pod_security_groups',
                                           cfg.OptGroup('neutron_defaults'))
        return sg_list[:]
