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

import ipaddress
import netaddr

from oslo_log import log as logging

from neutronclient.common import exceptions as n_exc

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils

CONF = config.CONF

LOG = logging.getLogger(__name__)


class NetworkPolicyDriver(base.NetworkPolicyDriver):
    """Provide security groups actions based on K8s Network Policies"""

    def __init__(self):
        self.neutron = clients.get_neutron_client()
        self.kubernetes = clients.get_kubernetes_client()

    def ensure_network_policy(self, policy, project_id):
        """Create security group rules out of network policies

        Triggered by events from network policies, this method ensures that
        security groups and security group rules are created or updated in
        reaction to kubernetes network policies events.

        In addition it returns the pods affected by the policy:
        - Creation: pods on the namespace of the created policy
        - Update: pods that needs to be updated in case of PodSelector
        modification, i.e., the pods that were affected by the previous
        PodSelector
        """
        LOG.debug("Creating network policy %s", policy['metadata']['name'])

        if self.get_kuryrnetpolicy_crd(policy):
            previous_selector = (
                self.update_security_group_rules_from_network_policy(policy))
            if previous_selector or previous_selector == {}:
                return self.affected_pods(policy, previous_selector)
            if previous_selector is None:
                return self.namespaced_pods(policy)
        else:
            self.create_security_group_rules_from_network_policy(policy,
                                                                 project_id)

    def update_security_group_rules_from_network_policy(self, policy):
        """Update security group rules

        This method updates security group rules based on CRUD events gotten
        from a configuration or patch to an existing network policy
        """
        crd = self.get_kuryrnetpolicy_crd(policy)
        crd_name = crd['metadata']['name']
        LOG.debug("Already existing CRD %s", crd_name)
        sg_id = crd['spec']['securityGroupId']
        # Fetch existing SG rules from kuryrnetpolicy CRD
        existing_sg_rules = []
        existing_i_rules = crd['spec'].get('ingressSgRules')
        existing_e_rules = crd['spec'].get('egressSgRules')
        if existing_i_rules or existing_e_rules:
            existing_sg_rules = existing_i_rules + existing_e_rules
        existing_pod_selector = crd['spec'].get('podSelector')
        # Parse network policy update and get new ruleset
        i_rules, e_rules = self.parse_network_policy_rules(policy, sg_id)
        current_sg_rules = i_rules + e_rules
        # Get existing security group rules ids
        sgr_ids = [x['security_group_rule'].pop('id') for x in
                   existing_sg_rules]
        # SG rules that are meant to be kept get their id back
        sg_rules_to_keep = [existing_sg_rules.index(rule) for rule in
                            existing_sg_rules if rule in current_sg_rules]
        for sg_rule in sg_rules_to_keep:
            sgr_id = sgr_ids[sg_rule]
            existing_sg_rules[sg_rule]['security_group_rule']['id'] = sgr_id
        # Delete SG rules that are no longer in the updated policy
        sg_rules_to_delete = [existing_sg_rules.index(rule) for rule in
                              existing_sg_rules if rule not in
                              current_sg_rules]
        for sg_rule in sg_rules_to_delete:
            try:
                driver_utils.delete_security_group_rule(sgr_ids[sg_rule])
            except n_exc.NotFound:
                LOG.debug('Trying to delete non existing sg_rule %s', sg_rule)
        # Create new rules that weren't already on the security group
        sg_rules_to_add = [rule for rule in current_sg_rules if rule not in
                           existing_sg_rules]
        for sg_rule in sg_rules_to_add:
            sgr_id = driver_utils.create_security_group_rule(sg_rule)
            if sg_rule['security_group_rule'].get('direction') == 'ingress':
                for i_rule in i_rules:
                    if sg_rule == i_rule:
                        i_rule["security_group_rule"]["id"] = sgr_id
            else:
                for e_rule in e_rules:
                    if sg_rule == e_rule:
                        e_rule["security_group_rule"]["id"] = sgr_id
        # Annotate kuryrnetpolicy CRD with current policy and ruleset
        pod_selector = policy['spec'].get('podSelector')
        driver_utils.patch_kuryrnetworkpolicy_crd(crd, i_rules, e_rules,
                                                  pod_selector,
                                                  np_spec=policy['spec'])

        if existing_pod_selector != pod_selector:
            return existing_pod_selector
        return False

    def _add_default_np_rules(self, sg_id):
        """Add extra SG rule to allow traffic from svcs and host.

        This method adds the base security group rules for the NP security
        group:
        - Ensure traffic is allowed from the services subnet
        - Ensure traffic is allowed from the host
        """
        default_cidrs = []
        if CONF.octavia_defaults.enforce_sg_rules:
            default_cidrs.append(utils.get_subnet_cidr(
                CONF.neutron_defaults.service_subnet))
        worker_subnet_id = CONF.pod_vif_nested.worker_nodes_subnet
        if worker_subnet_id:
            default_cidrs.append(utils.get_subnet_cidr(worker_subnet_id))
        for cidr in default_cidrs:
            default_rule = {
                u'security_group_rule': {
                    u'ethertype': 'IPv4',
                    u'security_group_id': sg_id,
                    u'direction': 'ingress',
                    u'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                    u'remote_ip_prefix': cidr
                }}
            driver_utils.create_security_group_rule(default_rule)

    def create_security_group_rules_from_network_policy(self, policy,
                                                        project_id):
        """Create initial security group and rules

        This method creates the initial security group for hosting security
        group rules coming out of network policies' parsing.
        """
        sg_name = ("sg-" + policy['metadata']['namespace'] + "-" +
                   policy['metadata']['name'])
        security_group_body = {
            "security_group":
                {
                    "name": sg_name,
                    "project_id": project_id,
                    "description": "Kuryr-Kubernetes NetPolicy SG"
                }
        }
        sg = None
        try:
            # Create initial security group
            sg = self.neutron.create_security_group(body=security_group_body)
            sg_id = sg['security_group']['id']
            driver_utils.tag_neutron_resources('security-groups', [sg_id])
            # NOTE(dulek): Neutron populates every new SG with two rules
            #              allowing egress on IPv4 and IPv6. This collides with
            #              how network policies are supposed to work, because
            #              initially even egress traffic should be blocked.
            #              To work around this we will delete those two SG
            #              rules just after creation.
            for sgr in sg['security_group']['security_group_rules']:
                self.neutron.delete_security_group_rule(sgr['id'])

            i_rules, e_rules = self.parse_network_policy_rules(policy, sg_id)
            for i_rule in i_rules:
                sgr_id = driver_utils.create_security_group_rule(i_rule)
                i_rule['security_group_rule']['id'] = sgr_id

            for e_rule in e_rules:
                sgr_id = driver_utils.create_security_group_rule(e_rule)
                e_rule['security_group_rule']['id'] = sgr_id

            # Add default rules to allow traffic from host and svc subnet
            self._add_default_np_rules(sg_id)
        except (n_exc.NeutronClientException, exceptions.ResourceNotReady):
            LOG.exception("Error creating security group for network policy "
                          " %s", policy['metadata']['name'])
            # If there's any issue creating sg rules, remove them
            if sg:
                self.neutron.delete_security_group(sg['security_group']['id'])
            raise
        try:
            self._add_kuryrnetpolicy_crd(policy, project_id,
                                         sg['security_group']['id'], i_rules,
                                         e_rules)
        except exceptions.K8sClientException:
            LOG.exception("Rolling back security groups")
            # Same with CRD creation
            self.neutron.delete_security_group(sg['security_group']['id'])
            raise
        try:
            crd = self.get_kuryrnetpolicy_crd(policy)
            self.kubernetes.annotate(policy['metadata']['selfLink'],
                                     {"kuryrnetpolicy_selfLink":
                                      crd['metadata']['selfLink']})
        except exceptions.K8sClientException:
            LOG.exception('Error annotating network policy')
            raise

    def _get_pods(self, pod_selector, namespace=None,
                  namespace_selector=None):
        matching_pods = {"items": []}
        if namespace_selector:
            matching_namespaces = driver_utils.get_namespaces(
                namespace_selector)
            for ns in matching_namespaces.get('items'):
                matching_pods = driver_utils.get_pods(pod_selector,
                                                      ns['metadata']['name'])
        else:
            matching_pods = driver_utils.get_pods(pod_selector, namespace)
        return matching_pods.get('items')

    def _get_namespaces(self, namespace_selector, namespace=None):
        matching_namespaces = []
        if not namespace_selector and namespace:
            matching_namespaces.append(self.kubernetes.get(
                '{}/namespaces/{}'.format(constants.K8S_API_BASE, namespace)))

        else:
            matching_namespaces.extend(driver_utils.get_namespaces(
                namespace_selector).get('items'))
        return matching_namespaces

    def _parse_selectors(self, rule_block, rule_direction, policy_namespace):
        allowed_resources = []
        allow_all = False
        selectors = False
        for rule in rule_block.get(rule_direction, []):
            namespace_selector = rule.get('namespaceSelector')
            pod_selector = rule.get('podSelector')
            if namespace_selector == {}:
                selectors = True
                if pod_selector:
                    # allow matching pods in all namespaces
                    allowed_resources.extend(self._get_pods(
                        pod_selector))
                else:
                    # allow from all
                    allow_all = True
            elif namespace_selector:
                selectors = True
                if pod_selector:
                    # allow matching pods on matching namespaces
                    allowed_resources.extend(self._get_pods(
                        pod_selector,
                        namespace_selector=namespace_selector))
                else:
                    # allow from/to all on the matching namespaces
                    allowed_resources.extend(self._get_namespaces(
                        namespace_selector))
            else:
                if pod_selector == {}:
                    # allow from/to all pods on the network policy
                    # namespace
                    selectors = True
                    allowed_resources.extend(self._get_namespaces(
                        None,
                        namespace=policy_namespace))
                elif pod_selector:
                    # allow matching pods on the network policy
                    # namespace
                    selectors = True
                    allowed_resources.extend(self._get_pods(
                        pod_selector,
                        namespace=policy_namespace))

        return allow_all, selectors, allowed_resources

    def _create_sg_rules_with_container_ports(
        self, container_ports, allow_all, resource, matched_pods,
            crd_rules, sg_id, direction, port, pod_selector=None,
            policy_namespace=None):
        cidr, ns = self._get_resource_details(resource)
        for pod, container_port in container_ports:
            pod_label = pod['metadata'].get('labels')
            pod_ip = pod['status'].get('podIP')
            pod_namespace = pod['metadata']['namespace']
            pod_info = {pod_ip: pod_namespace}
            # NOTE(maysams) Avoid to take into account pods that are also
            # matched by NetworkPolicySpec's podSelector. This way we do
            # not allow egress traffic to the actual set of pods the NP
            # is enforced on.
            if (direction == 'egress' and
                (driver_utils.match_selector(pod_selector, pod_label) and
                 policy_namespace == pod_namespace)):
                continue
            if container_port in matched_pods:
                matched_pods[container_port].update(pod_info)
            else:
                matched_pods[container_port] = pod_info
        if not allow_all and matched_pods and cidr:
            for container_port, pods in matched_pods.items():
                sg_rule = driver_utils.create_security_group_rule_body(
                    sg_id, direction, container_port,
                    protocol=port.get('protocol'),
                    cidr=cidr, pods=pods)
                if sg_rule not in crd_rules:
                    crd_rules.append(sg_rule)
                if (direction == 'egress' and
                        CONF.octavia_defaults.enforce_sg_rules):
                    rules = self._create_svc_egress_sg_rule(
                        sg_id, policy_namespace, resource=resource,
                        port=container_port,
                        protocol=port.get('protocol'))
                    crd_rules.extend(rules)

    def _create_sg_rule_body_on_text_port(self, sg_id, direction, port,
                                          resources, crd_rules, pod_selector,
                                          policy_namespace, allow_all=False):
        """Create SG rules when named port is used in the NP rule

        In case of ingress, the pods selected by NetworkPolicySpec's
        podSelector have its containers checked for ports with same name as
        the named port. If true, rules are created for the resource matched
        in the NP rule selector with that port. In case of egress, all the pods
        selected by the NetworkPolicyEgressRule's selector have its containers
        checked for containers ports with same name as the ones defined in
        NP rule, and if true the rule is created.

        param sg_id: String with the Security Group ID
        param direction: String with ingress or egress
        param port: dict containing port and protocol
        param resources: list of K8S resources(pod/namespace) or
        a dict with cird
        param crd_rules: list of parsed SG rules
        param pod_selector: dict with NetworkPolicySpec's podSelector
        param policy_namespace: string with policy namespace
        param allow_all: True if should parse a allow from/to all rule,
        False otherwise
        """
        matched_pods = {}
        if direction == "ingress":
            selected_pods = driver_utils.get_pods(
                pod_selector, policy_namespace).get('items')
            for selected_pod in selected_pods:
                container_ports = driver_utils.get_ports(selected_pod, port)
                for resource in resources:
                    self._create_sg_rules_with_container_ports(
                        container_ports, allow_all, resource, matched_pods,
                        crd_rules, sg_id, direction, port)
        elif direction == "egress":
            for resource in resources:
                # NOTE(maysams) Skipping objects that refers to ipblocks
                # and consequently do not contains a spec field
                if not resource.get('spec'):
                    LOG.warning("IPBlock for egress with named ports is "
                                "not supported.")
                    continue
                container_ports = driver_utils.get_ports(resource, port)
                self._create_sg_rules_with_container_ports(
                    container_ports, allow_all, resource, matched_pods,
                    crd_rules, sg_id, direction, port, pod_selector,
                    policy_namespace)
        if allow_all:
            for container_port, pods in matched_pods.items():
                sg_rule = driver_utils.create_security_group_rule_body(
                    sg_id, direction, container_port,
                    protocol=port.get('protocol'),
                    pods=pods)
                crd_rules.append(sg_rule)
            if (direction == 'egress' and
                    CONF.octavia_defaults.enforce_sg_rules):
                rules = self._create_svc_egress_sg_rule(
                    sg_id, policy_namespace, port=container_port,
                    protocol=port.get('protocol'))
                crd_rules.extend(rules)

    def _create_sg_rule_on_number_port(self, allowed_resources, sg_id,
                                       direction, port, sg_rule_body_list,
                                       policy_namespace):
        for resource in allowed_resources:
            cidr, ns = self._get_resource_details(resource)
            # NOTE(maysams): Skipping resource that do not have
            # an IP assigned. The security group rule creation
            # will be triggered again after the resource is running.
            if not cidr:
                continue
            sg_rule = (
                driver_utils.create_security_group_rule_body(
                    sg_id, direction, port.get('port'),
                    protocol=port.get('protocol'),
                    cidr=cidr,
                    namespace=ns))
            sg_rule_body_list.append(sg_rule)
            if (direction == 'egress' and
                    CONF.octavia_defaults.enforce_sg_rules):
                rule = self._create_svc_egress_sg_rule(
                    sg_id, policy_namespace, resource=resource,
                    port=port.get('port'), protocol=port.get('protocol'))
                sg_rule_body_list.extend(rule)

    def _create_all_pods_sg_rules(self, port, sg_id, direction,
                                  sg_rule_body_list, pod_selector,
                                  policy_namespace):
        if type(port.get('port')) is not int:
            all_pods = driver_utils.get_namespaced_pods().get('items')
            self._create_sg_rule_body_on_text_port(
                sg_id, direction, port, all_pods,
                sg_rule_body_list, pod_selector, policy_namespace,
                allow_all=True)
        else:
            sg_rule = (
                driver_utils.create_security_group_rule_body(
                    sg_id, direction, port.get('port'),
                    protocol=port.get('protocol')))
            sg_rule_body_list.append(sg_rule)
            if (direction == 'egress' and
                    CONF.octavia_defaults.enforce_sg_rules):
                rule = self._create_svc_egress_sg_rule(
                    sg_id, policy_namespace, port=port.get('port'),
                    protocol=port.get('protocol'))
                sg_rule_body_list.extend(rule)

    def _create_default_sg_rule(self, sg_id, direction, sg_rule_body_list):
        default_rule = {
            u'security_group_rule': {
                u'ethertype': 'IPv4',
                u'security_group_id': sg_id,
                u'direction': direction,
                u'description': 'Kuryr-Kubernetes NetPolicy SG rule',
            }}
        sg_rule_body_list.append(default_rule)

    def _parse_sg_rules(self, sg_rule_body_list, direction, policy, sg_id):
        """Parse policy into security group rules.

        This method inspects the policy object and create the equivalent
        security group rules associating them to the referenced sg_id.
        It returns the rules by adding them to the sg_rule_body_list list,
        for the stated direction.

        It accounts for special cases, such as:
        - PolicyTypes stating only Egress: ensuring ingress is not restricted
        - PolicyTypes not including Egress: ensuring egress is not restricted
        - {} ingress/egress rules: applying default open for all
        """
        rule_list = policy['spec'].get(direction)
        if not rule_list:
            policy_types = policy['spec'].get('policyTypes')
            if direction == 'ingress':
                if len(policy_types) == 1 and policy_types[0] == 'Egress':
                    # NOTE(ltomasbo): add default rule to enable all ingress
                    # traffic as NP policy is not affecting ingress
                    LOG.debug('Applying default all open for ingress for '
                              'policy %s', policy['metadata']['selfLink'])
                    self._create_default_sg_rule(
                        sg_id, direction, sg_rule_body_list)
            elif direction == 'egress':
                if policy_types and 'Egress' not in policy_types:
                    # NOTE(ltomasbo): add default rule to enable all egress
                    # traffic as NP policy is not affecting egress
                    LOG.debug('Applying default all open for egress for '
                              'policy %s', policy['metadata']['selfLink'])
                    self._create_default_sg_rule(
                        sg_id, direction, sg_rule_body_list)
            else:
                LOG.warning('Not supported policyType at network policy %s',
                            policy['metadata']['selfLink'])
            return

        policy_namespace = policy['metadata']['namespace']
        pod_selector = policy['spec'].get('podSelector')

        rule_direction = 'from'
        if direction == 'egress':
            rule_direction = 'to'

        if rule_list[0] == {}:
            LOG.debug('Applying default all open policy from %s',
                      policy['metadata']['selfLink'])
            rule = driver_utils.create_security_group_rule_body(sg_id,
                                                                direction)
            sg_rule_body_list.append(rule)

        for rule_block in rule_list:
            LOG.debug('Parsing %(dir)s Rule %(rule)s', {'dir': direction,
                                                        'rule': rule_block})
            allow_all, selectors, allowed_resources = self._parse_selectors(
                rule_block, rule_direction, policy_namespace)

            ipblock_list = []

            if rule_direction in rule_block:
                ipblock_list = [ipblock.get('ipBlock') for ipblock in
                                rule_block[rule_direction] if 'ipBlock'
                                in ipblock]

            for ipblock in ipblock_list:
                if ipblock.get('except'):
                    for cidr_except in ipblock.get('except'):
                        cidr_list = netaddr.cidr_exclude(
                            ipblock.get('cidr'), cidr_except)
                        cidr_list = [{'cidr': str(cidr)}
                                     for cidr in cidr_list]
                        allowed_resources.extend(cidr_list)
                else:
                    allowed_resources.append(ipblock)

            if 'ports' in rule_block:
                for port in rule_block['ports']:
                    if allowed_resources or allow_all or selectors:
                        if type(port.get('port')) is not int:
                            self._create_sg_rule_body_on_text_port(
                                sg_id, direction, port, allowed_resources,
                                sg_rule_body_list, pod_selector,
                                policy_namespace)
                        else:
                            self._create_sg_rule_on_number_port(
                                allowed_resources, sg_id, direction, port,
                                sg_rule_body_list, policy_namespace)
                        if allow_all:
                            self._create_all_pods_sg_rules(
                                port, sg_id, direction, sg_rule_body_list,
                                pod_selector, policy_namespace)
                    else:
                        self._create_all_pods_sg_rules(
                            port, sg_id, direction, sg_rule_body_list,
                            pod_selector, policy_namespace)
            elif allowed_resources or allow_all or selectors:
                for resource in allowed_resources:
                    cidr, namespace = self._get_resource_details(resource)
                    # NOTE(maysams): Skipping resource that do not have
                    # an IP assigned. The security group rule creation
                    # will be triggered again after the resource is running.
                    if not cidr:
                        continue
                    rule = driver_utils.create_security_group_rule_body(
                        sg_id, direction,
                        port_range_min=1,
                        port_range_max=65535,
                        cidr=cidr,
                        namespace=namespace)
                    sg_rule_body_list.append(rule)
                    if (direction == 'egress' and
                            CONF.octavia_defaults.enforce_sg_rules):
                        rule = self._create_svc_egress_sg_rule(
                            sg_id, policy_namespace, resource=resource)
                        sg_rule_body_list.extend(rule)
                if allow_all:
                    rule = driver_utils.create_security_group_rule_body(
                        sg_id, direction,
                        port_range_min=1,
                        port_range_max=65535)
                    if (direction == 'egress' and
                            CONF.octavia_defaults.enforce_sg_rules):
                        rule = self._create_svc_egress_sg_rule(
                            sg_id, policy_namespace)
                        sg_rule_body_list.extend(rule)
                    sg_rule_body_list.append(rule)
            else:
                LOG.debug('This network policy specifies no %(direction)s '
                          '%(rule_direction)s and no ports: %(policy)s',
                          {'direction': direction,
                           'rule_direction': rule_direction,
                           'policy': policy['metadata']['selfLink']})

    def _create_svc_egress_sg_rule(self, sg_id, policy_namespace,
                                   resource=None, port=None,
                                   protocol=None):
        sg_rule_body_list = []
        services = driver_utils.get_services()
        if not resource:
            svc_subnet = utils.get_subnet_cidr(
                CONF.neutron_defaults.service_subnet)
            rule = driver_utils.create_security_group_rule_body(
                sg_id, 'egress', port, protocol=protocol, cidr=svc_subnet)
            sg_rule_body_list.append(rule)
            return sg_rule_body_list

        for service in services.get('items'):
            if self._is_pod(resource):
                pod_labels = resource['metadata'].get('labels')
                svc_selector = service['spec'].get('selector')
                if not svc_selector or not pod_labels:
                    continue
                else:
                    if not driver_utils.match_labels(
                            svc_selector, pod_labels):
                        continue
            elif resource.get('cidr'):
                # NOTE(maysams) Accounts for traffic to pods under
                # a service matching an IPBlock rule.
                svc_namespace = service['metadata']['namespace']
                if svc_namespace != policy_namespace:
                    continue
                svc_selector = service['spec'].get('selector')
                pods = driver_utils.get_pods({'selector': svc_selector},
                                             svc_namespace).get('items')
                if not self._pods_in_ip_block(pods, resource):
                    continue
            else:
                ns_name = service['metadata']['namespace']
                if ns_name != resource['metadata']['name']:
                    continue
            cluster_ip = service['spec'].get('clusterIP')
            if not cluster_ip:
                continue
            rule = driver_utils.create_security_group_rule_body(
                sg_id, 'egress', port, protocol=protocol,
                cidr=cluster_ip)
            sg_rule_body_list.append(rule)
        return sg_rule_body_list

    def _pods_in_ip_block(self, pods, resource):
        for pod in pods:
            pod_ip = driver_utils.get_pod_ip(pod)
            if (ipaddress.ip_address(pod_ip)
                    in ipaddress.ip_network(resource.get('cidr'))):
                return True
        return False

    def parse_network_policy_rules(self, policy, sg_id):
        """Create security group rule bodies out of network policies.

        Whenever a notification from the handler 'on-present' method is
        received, security group rules are created out of network policies'
        ingress and egress ports blocks.
        """
        LOG.debug('Parsing Network Policy %s' % policy['metadata']['name'])
        ingress_sg_rule_body_list = []
        egress_sg_rule_body_list = []

        self._parse_sg_rules(ingress_sg_rule_body_list, 'ingress', policy,
                             sg_id)
        self._parse_sg_rules(egress_sg_rule_body_list, 'egress', policy,
                             sg_id)

        return ingress_sg_rule_body_list, egress_sg_rule_body_list

    def delete_np_sg(self, sg_id):
        try:
            self.neutron.delete_security_group(sg_id)
        except n_exc.NotFound:
            LOG.debug("Security Group not found: %s", sg_id)
        except n_exc.Conflict:
            LOG.debug("Security Group already in use: %s", sg_id)
            # raising ResourceNotReady to retry this action in case ports
            # associated to affected pods are not updated on time, i.e.,
            # they are still using the security group to be removed
            raise exceptions.ResourceNotReady(sg_id)
        except n_exc.NeutronClientException:
            LOG.exception("Error deleting security group %s.", sg_id)
            raise

    def release_network_policy(self, netpolicy_crd):
        if netpolicy_crd is not None:
            self.delete_np_sg(netpolicy_crd['spec']['securityGroupId'])
            self._del_kuryrnetpolicy_crd(
                netpolicy_crd['metadata']['name'],
                netpolicy_crd['metadata']['namespace'])

    def get_kuryrnetpolicy_crd(self, policy):
        netpolicy_crd_name = "np-" + policy['metadata']['name']
        netpolicy_crd_namespace = policy['metadata']['namespace']
        try:
            netpolicy_crd = self.kubernetes.get(
                '{}/{}/kuryrnetpolicies/{}'.format(
                    constants.K8S_API_CRD_NAMESPACES, netpolicy_crd_namespace,
                    netpolicy_crd_name))
        except exceptions.K8sResourceNotFound:
            return None
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return netpolicy_crd

    def knps_on_namespace(self, namespace):
        try:
            netpolicy_crds = self.kubernetes.get(
                '{}/{}/kuryrnetpolicies'.format(
                    constants.K8S_API_CRD_NAMESPACES,
                    namespace))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        if netpolicy_crds.get('items'):
            return True
        return False

    def _add_kuryrnetpolicy_crd(self, policy,  project_id, sg_id, i_rules,
                                e_rules):
        networkpolicy_name = policy['metadata']['name']
        netpolicy_crd_name = "np-" + networkpolicy_name
        namespace = policy['metadata']['namespace']
        pod_selector = policy['spec'].get('podSelector')
        netpolicy_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': constants.K8S_OBJ_KURYRNETPOLICY,
            'metadata': {
                'name': netpolicy_crd_name,
                'namespace': namespace,
                'annotations': {
                    'networkpolicy_name': networkpolicy_name,
                    'networkpolicy_namespace': namespace,
                    'networkpolicy_uid': policy['metadata']['uid'],
                },
            },
            'spec': {
                'securityGroupName': "sg-" + networkpolicy_name,
                'securityGroupId': sg_id,
                'ingressSgRules': i_rules,
                'egressSgRules': e_rules,
                'podSelector': pod_selector,
                'networkpolicy_spec': policy['spec']
            },
        }

        try:
            LOG.debug("Creating KuryrNetPolicy CRD %s" % netpolicy_crd)
            kubernetes_post = '{}/{}/kuryrnetpolicies'.format(
                constants.K8S_API_CRD_NAMESPACES,
                namespace)
            self.kubernetes.post(kubernetes_post, netpolicy_crd)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating kuryrnetpolicy"
                          " CRD. %s" % exceptions.K8sClientException)
            raise
        return netpolicy_crd

    def _del_kuryrnetpolicy_crd(self, netpolicy_crd_name,
                                netpolicy_crd_namespace):
        try:
            LOG.debug("Deleting KuryrNetPolicy CRD %s" % netpolicy_crd_name)
            self.kubernetes.delete('{}/{}/kuryrnetpolicies/{}'.format(
                constants.K8S_API_CRD_NAMESPACES,
                netpolicy_crd_namespace,
                netpolicy_crd_name))
        except exceptions.K8sResourceNotFound:
            LOG.debug("KuryrNetPolicy CRD Object not found: %s",
                      netpolicy_crd_name)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception deleting kuryrnetpolicy"
                          " CRD.")
            raise

    def affected_pods(self, policy, selector=None):
        if selector or selector == {}:
            pod_selector = selector
        else:
            pod_selector = policy['spec'].get('podSelector')
        if pod_selector:
            policy_namespace = policy['metadata']['namespace']
            pods = driver_utils.get_pods(pod_selector, policy_namespace)
            return pods.get('items')
        else:
            # NOTE(ltomasbo): It affects all the pods on the namespace
            return self.namespaced_pods(policy)

    def namespaced_pods(self, policy):
        pod_namespace = policy['metadata']['namespace']
        pods = self.kubernetes.get('{}/namespaces/{}/pods'.format(
            constants.K8S_API_BASE, pod_namespace))
        return pods.get('items')

    def _get_resource_details(self, resource):
        namespace = None
        if self._is_pod(resource):
            cidr = resource['status'].get('podIP')
            namespace = resource['metadata']['namespace']
        elif resource.get('cidr'):
            cidr = resource.get('cidr')
        else:
            cidr = driver_utils.get_namespace_subnet_cidr(resource)
            namespace = resource['metadata']['name']
        return cidr, namespace

    def _is_pod(self, resource):
        if resource.get('spec'):
            return resource['spec'].get('containers')
