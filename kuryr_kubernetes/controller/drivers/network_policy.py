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
        super().__init__()
        self.os_net = clients.get_network_client()
        self.kubernetes = clients.get_kubernetes_client()
        self.nodes_subnets_driver = base.NodesSubnetsDriver.get_instance()

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

    def create_security_group(self, knp, project_id):
        sg_name = driver_utils.get_resource_name(knp['metadata']['namespace'] +
                                                 '-' +
                                                 knp['metadata']['name'],
                                                 prefix='sg/')
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
        except (os_exc.SDKException, exceptions.ResourceNotReady) as exc:
            np = utils.get_referenced_object(knp, 'NetworkPolicy')
            if np:
                self.kubernetes.add_event(np, 'FailedToAddSecurityGroup',
                                          f'Adding new security group or '
                                          f'security group rules for '
                                          f'corresponding network policy has '
                                          f'failed: {exc}', 'Warning')
            LOG.exception("Error creating security group for network policy "
                          " %s", knp['metadata']['name'])
            raise

        return sg.id

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
                LOG.debug('Namespace %s is being terminated, ignoring '
                          'NetworkPolicy %s in that namespace.',
                          policy['metadata']['namespace'],
                          policy['metadata']['name'])
                return
        else:
            self._patch_knp_crd(policy, i_rules, e_rules, knp)

    def namespaced_pods(self, policy):
        pod_namespace = policy['metadata']['namespace']
        pods = self.kubernetes.get('{}/namespaces/{}/pods'.format(
            constants.K8S_API_BASE, pod_namespace))
        return pods.get('items')

    def _get_security_group_rules_from_network_policy(self, policy):
        """Get security group rules required to represent an NP

        This method creates the security group rules bodies coming out of a
        network policies' parsing.
        """
        i_rules, e_rules = self._parse_network_policy_rules(policy)
        # Add default rules to allow traffic from host and svc subnet
        i_rules += self._get_default_np_rules()
        # Add rules allowing ingress from LBs
        # FIXME(dulek): Rules added below cannot work around the Amphora
        #               source-ip problem as Amphora does not use LB VIP for
        #               LB->members traffic, but that other IP attached to the
        #               Amphora VM in the service subnet. It's ridiculous.
        i_rules += self._get_service_ingress_rules(policy)

        return i_rules, e_rules

    def _get_service_ingress_rules(self, policy):
        """Get SG rules allowing traffic from Services in the namespace

        This methods returns ingress rules allowing traffic from all
        services clusterIPs in the cluster. This is required for OVN LBs in
        order to work around the fact that it changes source-ip to LB IP in
        hairpin traffic. This shouldn't be a security problem as this can only
        happen when the pod receiving the traffic is the one that calls the
        service.

        FIXME(dulek): Once OVN supports selecting a single, configurable
                      source-IP for hairpin traffic, consider using it instead.
        """
        if CONF.octavia_defaults.enforce_sg_rules:
            # When enforce_sg_rules is True, one of the default rules will
            # open ingress from all the services subnets, so those rules would
            # be redundant.
            return []

        ns = policy['metadata']['namespace']
        rules = []
        services = self.kubernetes.get(
            f'{constants.K8S_API_NAMESPACES}/{ns}/services').get('items', [])
        for svc in services:
            if svc['metadata'].get('deletionTimestamp'):
                # Ignore services being deleted
                continue
            ip = svc['spec'].get('clusterIP')
            if not ip or ip == 'None':
                # Ignore headless services
                continue
            rules.append(driver_utils.create_security_group_rule_body(
                'ingress', cidr=ip,
                description=f"Allow traffic from local namespace service "
                            f"{svc['metadata']['name']}"))
        return rules

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
        worker_subnet_ids = self.nodes_subnets_driver.get_nodes_subnets()
        default_cidrs.extend(utils.get_subnets_cidrs(worker_subnet_ids))

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
        allowed_cidrs = None
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
                    # allow from all the cluster, which means pod subnets and
                    # service subnet.
                    allowed_cidrs = utils.get_subnetpool_cidrs(
                        CONF.namespace_subnet.pod_subnet_pool)
                    allowed_cidrs.append(utils.get_subnet_cidr(
                        CONF.neutron_defaults.service_subnet))
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

        return allowed_cidrs, selectors, allowed_resources

    def _create_sg_rules_with_container_ports(
        self, container_ports, allowed_cidrs, resource, matched_pods,
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
        if not allowed_cidrs and matched_pods and cidr:
            for container_port, pods in matched_pods.items():
                sg_rule = driver_utils.create_security_group_rule_body(
                    direction, container_port,
                    # Pod's spec.containers[].port.protocol defaults to TCP
                    protocol=port.get('protocol', 'TCP'),
                    cidr=cidr, pods=pods)
                if sg_rule not in crd_rules:
                    crd_rules.append(sg_rule)
                if direction == 'egress':
                    self._create_svc_egress_sg_rule(
                        policy_namespace, crd_rules,
                        resource=resource, port=container_port,
                        # Pod's spec.containers[].port.protocol defaults to TCP
                        protocol=port.get('protocol', 'TCP'))

    def _create_sg_rule_body_on_text_port(self, direction, port,
                                          resources, crd_rules, pod_selector,
                                          policy_namespace,
                                          allowed_cidrs=None):
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
        param allowed_cidrs: None, or a list of cidrs, where/from the traffic
                             should be allowed.
        """
        matched_pods = {}
        if direction == "ingress":
            selected_pods = driver_utils.get_pods(
                pod_selector, policy_namespace).get('items')
            for selected_pod in selected_pods:
                container_ports = driver_utils.get_ports(selected_pod, port)
                for resource in resources:
                    self._create_sg_rules_with_container_ports(
                        container_ports, allowed_cidrs, resource, matched_pods,
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
                    container_ports, allowed_cidrs, resource, matched_pods,
                    crd_rules, direction, port, pod_selector,
                    policy_namespace)
        if allowed_cidrs:
            for container_port, pods in matched_pods.items():
                for cidr in allowed_cidrs:
                    sg_rule = driver_utils.create_security_group_rule_body(
                        direction, container_port,
                        # Pod's spec.containers[].port.protocol defaults to TCP
                        protocol=port.get('protocol', 'TCP'),
                        cidr=cidr,
                        pods=pods)
                    crd_rules.append(sg_rule)

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
                    # NP's ports[].protocol defaults to TCP
                    protocol=port.get('protocol', 'TCP'),
                    cidr=cidr,
                    namespace=ns))
            sg_rule_body_list.append(sg_rule)
            if direction == 'egress':
                self._create_svc_egress_sg_rule(
                    policy_namespace, sg_rule_body_list,
                    resource=resource, port=port.get('port'),
                    # NP's ports[].protocol defaults to TCP
                    protocol=port.get('protocol', 'TCP'))

    def _create_all_pods_sg_rules(self, port, direction,
                                  sg_rule_body_list, pod_selector,
                                  policy_namespace, allowed_cidrs=None):
        if not isinstance(port.get('port'), int):
            all_pods = driver_utils.get_namespaced_pods().get('items')
            self._create_sg_rule_body_on_text_port(
                direction, port, all_pods,
                sg_rule_body_list, pod_selector, policy_namespace,
                allowed_cidrs=allowed_cidrs)
        elif allowed_cidrs:
            for cidr in allowed_cidrs:
                sg_rule = driver_utils.create_security_group_rule_body(
                        direction, port.get('port'),
                        protocol=port.get('protocol'),
                        cidr=cidr)
                sg_rule_body_list.append(sg_rule)
        else:
            for ethertype in (constants.IPv4, constants.IPv6):
                sg_rule = (
                    driver_utils.create_security_group_rule_body(
                        direction, port.get('port'),
                        ethertype=ethertype,
                        # NP's ports[].protocol defaults to TCP
                        protocol=port.get('protocol', 'TCP')))
                sg_rule_body_list.append(sg_rule)

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
        - {} ingress/egress rules: applying default open for all the cluster
        """
        _create_sg_rule_body = driver_utils.create_security_group_rule_body
        rule_list = policy['spec'].get(direction)

        if not rule_list:
            policy_types = policy['spec'].get('policyTypes')
            if direction == 'ingress':
                if len(policy_types) == 1 and policy_types[0] == 'Egress':
                    # NOTE(ltomasbo): add default rule to enable all ingress
                    # traffic as NP policy is not affecting ingress
                    LOG.debug('Applying default all open for ingress for '
                              'policy %s', utils.get_res_link(policy))
                    self._create_default_sg_rule(direction, sg_rule_body_list)
            elif direction == 'egress':
                if policy_types and 'Egress' not in policy_types:
                    # NOTE(ltomasbo): add default rule to enable all egress
                    # traffic as NP policy is not affecting egress
                    LOG.debug('Applying default all open for egress for '
                              'policy %s', utils.get_res_link(policy))
                    self._create_default_sg_rule(direction, sg_rule_body_list)
            else:
                LOG.warning('Not supported policyType at network policy %s',
                            utils.get_res_link(policy))
            return

        policy_namespace = policy['metadata']['namespace']
        pod_selector = policy['spec'].get('podSelector')

        rule_direction = 'from'
        if direction == 'egress':
            rule_direction = 'to'

        if rule_list[0] == {}:
            LOG.debug('Applying default all open policy from %s',
                      utils.get_res_link(policy))
            for ethertype in (constants.IPv4, constants.IPv6):
                rule = _create_sg_rule_body(direction, ethertype=ethertype)
                sg_rule_body_list.append(rule)

        for rule_block in rule_list:
            LOG.debug('Parsing %(dir)s Rule %(rule)s', {'dir': direction,
                                                        'rule': rule_block})
            (allowed_cidrs, selectors,
             allowed_resources) = self._parse_selectors(rule_block,
                                                        rule_direction,
                                                        policy_namespace)

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
                    if allowed_resources or allowed_cidrs or selectors:
                        if not isinstance(port.get('port'), int):
                            self._create_sg_rule_body_on_text_port(
                                direction, port, allowed_resources,
                                sg_rule_body_list, pod_selector,
                                policy_namespace)
                        else:
                            self._create_sg_rule_on_number_port(
                                allowed_resources, direction, port,
                                sg_rule_body_list, policy_namespace)
                        if allowed_cidrs:
                            self._create_all_pods_sg_rules(
                                port, direction, sg_rule_body_list,
                                pod_selector, policy_namespace, allowed_cidrs)
                    else:
                        self._create_all_pods_sg_rules(
                            port, direction, sg_rule_body_list,
                            pod_selector, policy_namespace)
            elif allowed_resources or allowed_cidrs or selectors:
                for resource in allowed_resources:
                    cidr, namespace = self._get_resource_details(resource)
                    # NOTE(maysams): Skipping resource that do not have
                    # an IP assigned. The security group rule creation
                    # will be triggered again after the resource is running.
                    if not cidr:
                        continue
                    rule = _create_sg_rule_body(direction, cidr=cidr,
                                                namespace=namespace)
                    sg_rule_body_list.append(rule)
                    if direction == 'egress':
                        self._create_svc_egress_sg_rule(
                            policy_namespace, sg_rule_body_list,
                            resource=resource)
                if allowed_cidrs:
                    for cidr in allowed_cidrs:
                        rule = _create_sg_rule_body(direction, cidr=cidr)
                        sg_rule_body_list.append(rule)
            else:
                LOG.debug('This network policy specifies no %(direction)s '
                          '%(rule_direction)s and no ports: %(policy)s',
                          {'direction': direction,
                           'rule_direction': rule_direction,
                           'policy': utils.get_res_link(policy)})

    def _create_svc_egress_sg_rule(self, policy_namespace, sg_rule_body_list,
                                   resource=None, port=None, protocol=None):
        # FIXME(dulek): We could probably filter by namespace here for pods
        #               and namespace resources?
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
            if service['metadata'].get('deletionTimestamp'):
                # Ignore services being deleted
                continue

            cluster_ip = service['spec'].get('clusterIP')
            if not cluster_ip or cluster_ip == 'None':
                # Headless services has 'None' as clusterIP, ignore.
                continue

            svc_name = service['metadata']['name']
            svc_namespace = service['metadata']['namespace']
            if self._is_pod(resource):
                pod_labels = resource['metadata'].get('labels')
                svc_selector = service['spec'].get('selector')
                if not svc_selector:
                    targets = driver_utils.get_endpoints_targets(
                            svc_name, svc_namespace)
                    pod_ip = resource['status'].get('podIP')
                    if pod_ip and pod_ip not in targets:
                        continue
                elif pod_labels:
                    if not driver_utils.match_labels(svc_selector, pod_labels):
                        continue
            elif resource.get('cidr'):
                # NOTE(maysams) Accounts for traffic to pods under
                # a service matching an IPBlock rule.
                svc_selector = service['spec'].get('selector')
                if not svc_selector:
                    # Retrieving targets of services on any Namespace
                    targets = driver_utils.get_endpoints_targets(
                        svc_name, svc_namespace)
                    if (not targets or
                            not self._targets_in_ip_block(targets, resource)):
                        continue
                else:
                    if svc_namespace != policy_namespace:
                        continue
                    pods = driver_utils.get_pods({'selector': svc_selector},
                                                 svc_namespace).get('items')
                    if not self._pods_in_ip_block(pods, resource):
                        continue
            else:
                ns_name = service['metadata']['namespace']
                if ns_name != resource['metadata']['name']:
                    continue
            rule = driver_utils.create_security_group_rule_body(
                'egress', port, protocol=protocol, cidr=cluster_ip)
            if rule not in sg_rule_body_list:
                sg_rule_body_list.append(rule)

    def _pods_in_ip_block(self, pods, resource):
        for pod in pods:
            pod_ip = driver_utils.get_pod_ip(pod)
            if (ipaddress.ip_address(pod_ip)
                    in ipaddress.ip_network(resource.get('cidr'))):
                return True
        return False

    def _targets_in_ip_block(self, targets, resource):
        for target in targets:
            if (ipaddress.ip_address(target)
                    not in ipaddress.ip_network(resource.get('cidr'))):
                return False
        return True

    def _parse_network_policy_rules(self, policy):
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

        owner_reference = {'apiVersion': policy['apiVersion'],
                           'kind': policy['kind'],
                           'name': policy['metadata']['name'],
                           'uid': policy['metadata']['uid']}

        netpolicy_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': constants.K8S_OBJ_KURYRNETWORKPOLICY,
            'metadata': {
                'name': networkpolicy_name,
                'namespace': namespace,
                'annotations': {
                    'networkPolicyLink': utils.get_res_link(policy)
                },
                'finalizers': [constants.NETWORKPOLICY_FINALIZER],
                'ownerReferences': [owner_reference]
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
        except exceptions.K8sClientException as exc:
            self.kubernetes.add_event(policy, 'FailedToCreateNetworkPolicyCRD',
                                      f'Adding corresponding Kuryr Network '
                                      f'Policy CRD has failed: {exc}',
                                      'Warning')
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
        except exceptions.K8sClientException as exc:
            self.kubernetes.add_event(policy, 'FailedToDeleteNetworkPolicyCRD',
                                      f'Deleting corresponding Kuryr Network '
                                      f'Policy CRD has failed: {exc}',
                                      'Warning')
            LOG.exception("Kubernetes Client Exception deleting "
                          "KuryrNetworkPolicy CRD %s." % name)
            raise

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
