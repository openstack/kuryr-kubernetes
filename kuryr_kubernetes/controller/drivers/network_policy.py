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

from openstack import exceptions as os_exc
from oslo_log import log as logging

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
        self.os_net = clients.get_network_client()
        self.kubernetes = clients.get_kubernetes_client()

    def ensure_network_policy(self, policy):
        """Create security group rules out of network policies

        Triggered by events from network policies, this method ensures that
        KuryrNetworkPolicy object is created with the security group rules
        definitions required to represent the NetworkPolicy.
        """
        LOG.debug("Creating network policy %s", policy['metadata']['name'])

        i_rules, e_rules = self._get_security_group_rules_from_network_policy(
            policy)

        knp = self._get_knp_crd(policy)
        if not knp:
            try:
                self._create_knp_crd(policy, i_rules, e_rules)
            except exceptions.K8sNamespaceTerminating:
                LOG.warning('Namespace %s is being terminated, ignoring '
                            'NetworkPolicy %s in that namespace.',
                            policy['metadata']['namespace'],
                            policy['metadata']['name'])
                return
        else:
            self._patch_knp_crd(policy, i_rules, e_rules, knp)

    def _convert_old_sg_rule(self, rule):
        del rule['security_group_rule']['id']
        del rule['security_group_rule']['security_group_id']
        result = {
            'sgRule': rule['security_group_rule'],
        }

        if 'namespace' in rule:
            result['namespace'] = rule['namespace']

        if 'remote_ip_prefixes' in rule:
            result['affectedPods'] = []
            for ip, namespace in rule['remote_ip_prefixes']:
                if not ip:
                    continue
                result['affectedPods'].append({
                    'podIP': ip,
                    'podNamespace': namespace,
                })

        return result

    def get_from_old_crd(self, netpolicy):
        name = netpolicy['metadata']['name'][3:]  # Remove 'np-'
        namespace = netpolicy['metadata']['namespace']
        link = (f'{constants.K8S_API_NETWORKING}/namespaces/{namespace}/'
                f'networkpolicies/{name}')
        knp = {
            'apiVersion': constants.K8S_API_CRD_VERSION,
            'kind': constants.K8S_OBJ_KURYRNETWORKPOLICY,
            'metadata': {
                'namespace': namespace,
                'name': name,
                'annotations': {
                    'networkPolicyLink': link,
                },
                'finalizers': [constants.NETWORKPOLICY_FINALIZER],
            },
            'spec': {
                'podSelector':
                    netpolicy['spec']['networkpolicy_spec']['podSelector'],
                'egressSgRules': [self._convert_old_sg_rule(r) for r in
                                  netpolicy['spec']['egressSgRules']],
                'ingressSgRules': [self._convert_old_sg_rule(r) for r in
                                   netpolicy['spec']['ingressSgRules']],
                'policyTypes':
                    netpolicy['spec']['networkpolicy_spec']['policyTypes'],
            },
            'status': {
                'podSelector': netpolicy['spec']['podSelector'],
                'securityGroupId': netpolicy['spec']['securityGroupId'],
                # We'll just let KuryrNetworkPolicyHandler figure out if rules
                # are created on its own.
                'securityGroupRules': [],
            },
        }

        return knp

    def _get_security_group_rules_from_network_policy(self, policy):
        """Get security group rules required to represent an NP

        This method creates the security group rules bodies coming out of a
        network policies' parsing.
        """
        i_rules, e_rules = self.parse_network_policy_rules(policy)
        # Add default rules to allow traffic from host and svc subnet
        i_rules += self._get_default_np_rules()

        return i_rules, e_rules

    def _get_default_np_rules(self):
        """Add extra SG rule to allow traffic from svcs and host.

        This method adds the base security group rules for the NP security
        group:
        - Ensure traffic is allowed from the services subnet
        - Ensure traffic is allowed from the host
        """
        rules = []
        default_cidrs = []
        if CONF.octavia_defaults.enforce_sg_rules:
            default_cidrs.append(utils.get_subnet_cidr(
                CONF.neutron_defaults.service_subnet))
        worker_subnet_id = CONF.pod_vif_nested.worker_nodes_subnet
        if worker_subnet_id:
            default_cidrs.append(utils.get_subnet_cidr(worker_subnet_id))
        for cidr in default_cidrs:
            ethertype = constants.IPv4
            if ipaddress.ip_network(cidr).version == constants.IP_VERSION_6:
                ethertype = constants.IPv6
            rules.append({
                'sgRule': {
                    'ethertype': ethertype,
                    'direction': 'ingress',
                    'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                    'remote_ip_prefix': cidr,
                }})

        return rules

    def create_security_group(self, knp, project_id):
        sg_name = ("sg-" + knp['metadata']['namespace'] + "-" +
                   knp['metadata']['name'])
        desc = ("Kuryr-Kubernetes Network Policy %s SG" %
                utils.get_res_unique_name(knp))
        try:
            # Create initial security group
            sg = self.os_net.create_security_group(name=sg_name,
                                                   project_id=project_id,
                                                   description=desc)
            driver_utils.tag_neutron_resources([sg])
            # NOTE(dulek): Neutron populates every new SG with two rules
            #              allowing egress on IPv4 and IPv6. This collides with
            #              how network policies are supposed to work, because
            #              initially even egress traffic should be blocked.
            #              To work around this we will delete those two SG
            #              rules just after creation.
            for sgr in sg.security_group_rules:
                self.os_net.delete_security_group_rule(sgr['id'])
        except (os_exc.SDKException, exceptions.ResourceNotReady):
            LOG.exception("Error creating security group for network policy "
                          " %s", knp['metadata']['name'])
            raise

        return sg.id

    def _get_pods(self, pod_selector, namespace=None, namespace_selector=None):
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
            crd_rules, direction, port, pod_selector=None,
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
                    direction, container_port,
                    protocol=port.get('protocol'),
                    cidr=cidr, pods=pods)
                if sg_rule not in crd_rules:
                    crd_rules.append(sg_rule)
                if direction == 'egress':
                    self._create_svc_egress_sg_rule(
                        policy_namespace, crd_rules,
                        resource=resource, port=container_port,
                        protocol=port.get('protocol'))

    def _create_sg_rule_body_on_text_port(self, direction, port,
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
                        crd_rules, direction, port)
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
                    crd_rules, direction, port, pod_selector,
                    policy_namespace)
        if allow_all:
            container_port = None
            for container_port, pods in matched_pods.items():
                for ethertype in (constants.IPv4, constants.IPv6):
                    sg_rule = driver_utils.create_security_group_rule_body(
                        direction, container_port,
                        protocol=port.get('protocol'),
                        ethertype=ethertype,
                        pods=pods)
                    crd_rules.append(sg_rule)
            if direction == 'egress':
                self._create_svc_egress_sg_rule(
                    policy_namespace, crd_rules,
                    port=container_port, protocol=port.get('protocol'))

    def _create_sg_rule_on_number_port(self, allowed_resources,
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
                    direction, port.get('port'),
                    protocol=port.get('protocol'),
                    cidr=cidr,
                    namespace=ns))
            sg_rule_body_list.append(sg_rule)
            if direction == 'egress':
                self._create_svc_egress_sg_rule(
                    policy_namespace, sg_rule_body_list,
                    resource=resource, port=port.get('port'),
                    protocol=port.get('protocol'))

    def _create_all_pods_sg_rules(self, port, direction,
                                  sg_rule_body_list, pod_selector,
                                  policy_namespace):
        if type(port.get('port')) is not int:
            all_pods = driver_utils.get_namespaced_pods().get('items')
            self._create_sg_rule_body_on_text_port(
                direction, port, all_pods,
                sg_rule_body_list, pod_selector, policy_namespace,
                allow_all=True)
        else:
            for ethertype in (constants.IPv4, constants.IPv6):
                sg_rule = (
                    driver_utils.create_security_group_rule_body(
                        direction, port.get('port'),
                        ethertype=ethertype,
                        protocol=port.get('protocol')))
                sg_rule_body_list.append(sg_rule)
                if direction == 'egress':
                    self._create_svc_egress_sg_rule(
                        policy_namespace, sg_rule_body_list,
                        port=port.get('port'),
                        protocol=port.get('protocol'))

    def _create_default_sg_rule(self, direction, sg_rule_body_list):
        for ethertype in (constants.IPv4, constants.IPv6):
            default_rule = {
                'sgRule': {
                    'ethertype': ethertype,
                    'direction': direction,
                    'description': 'Kuryr-Kubernetes NetPolicy SG rule',
                }}
            sg_rule_body_list.append(default_rule)

    def _parse_sg_rules(self, sg_rule_body_list, direction, policy):
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
                    self._create_default_sg_rule(direction, sg_rule_body_list)
            elif direction == 'egress':
                if policy_types and 'Egress' not in policy_types:
                    # NOTE(ltomasbo): add default rule to enable all egress
                    # traffic as NP policy is not affecting egress
                    LOG.debug('Applying default all open for egress for '
                              'policy %s', policy['metadata']['selfLink'])
                    self._create_default_sg_rule(direction, sg_rule_body_list)
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
            for ethertype in (constants.IPv4, constants.IPv6):
                rule = driver_utils.create_security_group_rule_body(
                    direction, ethertype=ethertype)
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
                                direction, port, allowed_resources,
                                sg_rule_body_list, pod_selector,
                                policy_namespace)
                        else:
                            self._create_sg_rule_on_number_port(
                                allowed_resources, direction, port,
                                sg_rule_body_list, policy_namespace)
                        if allow_all:
                            self._create_all_pods_sg_rules(
                                port, direction, sg_rule_body_list,
                                pod_selector, policy_namespace)
                    else:
                        self._create_all_pods_sg_rules(
                            port, direction, sg_rule_body_list,
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
                        direction,
                        port_range_min=1,
                        port_range_max=65535,
                        cidr=cidr,
                        namespace=namespace)
                    sg_rule_body_list.append(rule)
                    if direction == 'egress':
                        self._create_svc_egress_sg_rule(
                            policy_namespace, sg_rule_body_list,
                            resource=resource)
                if allow_all:
                    for ethertype in (constants.IPv4, constants.IPv6):
                        rule = driver_utils.create_security_group_rule_body(
                            direction,
                            port_range_min=1,
                            port_range_max=65535,
                            ethertype=ethertype)
                        sg_rule_body_list.append(rule)
                        if direction == 'egress':
                            self._create_svc_egress_sg_rule(policy_namespace,
                                                            sg_rule_body_list)
            else:
                LOG.debug('This network policy specifies no %(direction)s '
                          '%(rule_direction)s and no ports: %(policy)s',
                          {'direction': direction,
                           'rule_direction': rule_direction,
                           'policy': policy['metadata']['selfLink']})

    def _create_svc_egress_sg_rule(self, policy_namespace, sg_rule_body_list,
                                   resource=None, port=None, protocol=None):
        services = driver_utils.get_services()
        if not resource:
            svc_subnet = utils.get_subnet_cidr(
                CONF.neutron_defaults.service_subnet)
            rule = driver_utils.create_security_group_rule_body(
                'egress', port, protocol=protocol, cidr=svc_subnet)
            if rule not in sg_rule_body_list:
                sg_rule_body_list.append(rule)
            return

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
                'egress', port, protocol=protocol,
                cidr=cluster_ip)
            if rule not in sg_rule_body_list:
                sg_rule_body_list.append(rule)

    def _pods_in_ip_block(self, pods, resource):
        for pod in pods:
            pod_ip = driver_utils.get_pod_ip(pod)
            if (ipaddress.ip_address(pod_ip)
                    in ipaddress.ip_network(resource.get('cidr'))):
                return True
        return False

    def parse_network_policy_rules(self, policy):
        """Create security group rule bodies out of network policies.

        Whenever a notification from the handler 'on-present' method is
        received, security group rules are created out of network policies'
        ingress and egress ports blocks.
        """
        LOG.debug('Parsing Network Policy %s' % policy['metadata']['name'])
        ingress_sg_rule_body_list = []
        egress_sg_rule_body_list = []

        self._parse_sg_rules(ingress_sg_rule_body_list, 'ingress', policy)
        self._parse_sg_rules(egress_sg_rule_body_list, 'egress', policy)

        return ingress_sg_rule_body_list, egress_sg_rule_body_list

    def delete_np_sg(self, sg_id):
        try:
            self.os_net.delete_security_group(sg_id)
        except os_exc.ConflictException:
            LOG.debug("Security Group %s still in use!", sg_id)
            # raising ResourceNotReady to retry this action in case ports
            # associated to affected pods are not updated on time, i.e.,
            # they are still using the security group to be removed
            raise exceptions.ResourceNotReady(sg_id)
        except os_exc.SDKException:
            LOG.exception("Error deleting security group %s.", sg_id)
            raise

    def release_network_policy(self, policy):
        return self._del_knp_crd(policy)

    def _get_knp_crd(self, policy):
        netpolicy_crd_name = policy['metadata']['name']
        netpolicy_crd_namespace = policy['metadata']['namespace']
        try:
            netpolicy_crd = self.kubernetes.get(
                '{}/{}/kuryrnetworkpolicies/{}'.format(
                    constants.K8S_API_CRD_NAMESPACES, netpolicy_crd_namespace,
                    netpolicy_crd_name))
        except exceptions.K8sResourceNotFound:
            return None
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return netpolicy_crd

    def _create_knp_crd(self, policy, i_rules, e_rules):
        networkpolicy_name = policy['metadata']['name']
        namespace = policy['metadata']['namespace']
        pod_selector = policy['spec'].get('podSelector')
        policy_types = policy['spec'].get('policyTypes', [])
        netpolicy_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': constants.K8S_OBJ_KURYRNETWORKPOLICY,
            'metadata': {
                'name': networkpolicy_name,
                'namespace': namespace,
                'annotations': {
                    'networkPolicyLink': policy['metadata']['selfLink'],
                },
                'finalizers': [constants.NETWORKPOLICY_FINALIZER],
            },
            'spec': {
                'ingressSgRules': i_rules,
                'egressSgRules': e_rules,
                'podSelector': pod_selector,
                'policyTypes': policy_types,
            },
            'status': {
                'securityGroupRules': [],
            },
        }

        try:
            LOG.debug("Creating KuryrNetworkPolicy CRD %s" % netpolicy_crd)
            url = '{}/{}/kuryrnetworkpolicies'.format(
                constants.K8S_API_CRD_NAMESPACES,
                namespace)
            netpolicy_crd = self.kubernetes.post(url, netpolicy_crd)
        except exceptions.K8sNamespaceTerminating:
            raise
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating "
                          "KuryrNetworkPolicy CRD.")
            raise
        return netpolicy_crd

    def _patch_knp_crd(self, policy, i_rules, e_rules, knp):
        networkpolicy_name = policy['metadata']['name']
        namespace = policy['metadata']['namespace']
        pod_selector = policy['spec'].get('podSelector')
        url = (f'{constants.K8S_API_CRD_NAMESPACES}/{namespace}'
               f'/kuryrnetworkpolicies/{networkpolicy_name}')

        # FIXME(dulek): Rules should be hashable objects, not dict so that
        #               we could compare them easily here.
        data = {
            'ingressSgRules': i_rules,
            'egressSgRules': e_rules,
        }
        if knp['spec'].get('podSelector') != pod_selector:
            data['podSelector'] = pod_selector

        self.kubernetes.patch_crd('spec', url, data)

    def _del_knp_crd(self, policy):
        try:
            ns = policy['metadata']['namespace']
            name = policy['metadata']['name']
            LOG.debug("Deleting KuryrNetworkPolicy CRD %s" % name)
            self.kubernetes.delete('{}/{}/kuryrnetworkpolicies/{}'.format(
                constants.K8S_API_CRD_NAMESPACES, ns, name))
            return True
        except exceptions.K8sResourceNotFound:
            LOG.debug("KuryrNetworkPolicy CRD Object not found: %s", name)
            return False
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception deleting "
                          "KuryrNetworkPolicy CRD %s." % name)
            raise

    def affected_pods(self, policy, selector=None):
        if selector is not None:
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
