# Copyright (c) 2018 Samsung Electronics Co.,Ltd
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

import urllib
import uuid

import eventlet
import netaddr
from openstack import exceptions as os_exc
from os_vif import objects
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import utils


OPERATORS_WITH_VALUES = [constants.K8S_OPERATOR_IN,
                         constants.K8S_OPERATOR_NOT_IN]

LOG = log.getLogger(__name__)

CONF = cfg.CONF


def get_network_id(subnets):
    ids = list({net.id for net in subnets.values()})

    if len(ids) != 1:
        raise k_exc.IntegrityError(
            "Subnet mapping %(subnets)s is not valid: "
            "%(num_networks)s unique networks found" %
            {'subnets': subnets, 'num_networks': len(ids)})

    return ids[0]


def get_port_name(pod):
    return get_resource_name(pod['metadata']['name'],
                             prefix=pod['metadata']['namespace'] + "/")


def get_device_id(pod):
    return pod['metadata']['uid']


def get_host_id(pod):
    return pod['spec']['nodeName']


def get_kuryrport(pod):
    k8s = clients.get_kubernetes_client()
    try:
        return k8s.get(f'{constants.K8S_API_CRD_NAMESPACES}/'
                       f'{pod["metadata"]["namespace"]}/kuryrports/'
                       f'{pod["metadata"]["name"]}')
    except k_exc.K8sResourceNotFound:
        return None


def get_vifs(kp):
    try:
        return {k: objects.base.VersionedObject.obj_from_primitive(v['vif'])
                for k, v in kp['status']['vifs'].items()}
    except (KeyError, AttributeError, TypeError):
        return {}


def is_pod_scheduled(pod):
    try:
        return bool(pod['spec']['nodeName'])
    except KeyError:
        return False


def get_pods(selector, namespace=None):
    """Return a k8s object list with the pods matching the selector.

    It accepts an optional parameter to state the namespace where the pod
    selector will be apply. If empty namespace is passed, then the pod
    selector is applied in all namespaces.

    param selector: k8s selector of types matchLabels or matchExpressions
    param namespace: namespace name where the selector will be applied. If
                     None, the pod selector is applied in all namespaces
    return: k8s list object containing all matching pods

    """
    kubernetes = clients.get_kubernetes_client()

    svc_selector = selector.get('selector')
    if svc_selector:
        labels = replace_encoded_characters(svc_selector)
    else:
        labels = selector.get('matchLabels', None)
        if labels:
            # Removing pod-template-hash as pods will not have it and
            # otherwise there will be no match
            labels.pop('pod-template-hash', None)
            labels = replace_encoded_characters(labels)

        exps = selector.get('matchExpressions', None)
        if exps:
            exps = ', '.join(format_expression(exp) for exp in exps)
            if labels:
                expressions = urllib.parse.quote("," + exps)
                labels += expressions
            else:
                labels = urllib.parse.quote(exps)

    if namespace:
        pods = kubernetes.get(
            '{}/namespaces/{}/pods?labelSelector={}'.format(
                constants.K8S_API_BASE, namespace, labels))
    else:
        pods = kubernetes.get(
            '{}/pods?labelSelector={}'.format(constants.K8S_API_BASE, labels))

    return pods


def get_namespaces(selector):
    """Return a k8s object list with the namespaces matching the selector.

    param selector: k8s selector of types matchLabels or matchExpressions
    return: k8s list object containing all matching namespaces

    """
    kubernetes = clients.get_kubernetes_client()
    labels = selector.get('matchLabels', None)
    if labels:
        labels = replace_encoded_characters(labels)

    exps = selector.get('matchExpressions', None)
    if exps:
        exps = ', '.join(format_expression(exp) for exp in exps)
        if labels:
            expressions = urllib.parse.quote("," + exps)
            labels += expressions
        else:
            labels = urllib.parse.quote(exps)

    namespaces = kubernetes.get(
        '{}/namespaces?labelSelector={}'.format(
            constants.K8S_API_BASE, labels))

    return namespaces


def format_expression(expression):
    key = expression['key']
    operator = expression['operator'].lower()
    if operator in OPERATORS_WITH_VALUES:
        values = expression['values']
        values = str(', '.join(values))
        values = "(%s)" % values
        return "%s %s %s" % (key, operator, values)
    else:
        if operator == constants.K8S_OPERATOR_DOES_NOT_EXIST:
            return "!%s" % key
        else:
            return key


def replace_encoded_characters(labels):
    labels = urllib.parse.urlencode(labels)
    # NOTE(ltomasbo): K8s API does not accept &, so we need to AND
    # the matchLabels with ',' or '%2C' instead
    labels = labels.replace('&', ',')
    return labels


def create_security_group_rule(body, knp):
    os_net = clients.get_network_client()
    k8s = clients.get_kubernetes_client()

    try:
        params = dict(body)
        if 'ethertype' in params:
            # NOTE(gryf): in openstacksdk, there is ether_type attribute in
            # the security_group_rule object, in CRD we have 'ethertype'
            # instead, just like it was returned by the neutron client.
            params['ether_type'] = params['ethertype']
            del params['ethertype']
        sgr = os_net.create_security_group_rule(**params)
        return sgr.id
    except os_exc.ConflictException as ex:
        if 'quota' in ex.details.lower():
            np = utils.get_referenced_object(knp, 'NetworkPolicy')
            k8s.add_event(np, 'FailedToCreateSecurityGroupRule',
                          f'Creating security group rule for corresponding '
                          f'Network Policy has failed: {ex}',
                          'Warning')
            LOG.error("Failed to create security group rule %s: %s", body,
                      ex.details)
            raise
        else:
            LOG.debug("Failed to create already existing security group "
                      "rule %s", body)
            # Get existent sg rule id from exception message
            return str(ex).split()[-1][:-1]
    except os_exc.SDKException as exc:
        np = utils.get_referenced_object(knp, 'NetworkPolicy')
        k8s.add_event(np, 'FailedToCreateSecurityGroupRule',
                      f'Creating security group rule for corresponding '
                      f'Network Policy has failed: {exc}',
                      'Warning')
        LOG.debug("Error creating security group rule")
        raise


def check_tag_on_creation():
    """Checks if Neutron supports tagging during bulk port creation.

    :param os_net: Network proxy object from Openstacksdk.
    :return: Boolean
    """
    os_net = clients.get_network_client()
    extension = os_net.find_extension(
            name_or_id='tag-ports-during-bulk-creation')
    return bool(extension)


def delete_security_group_rule(security_group_rule_id, knp):
    os_net = clients.get_network_client()
    k8s = clients.get_kubernetes_client()

    try:
        LOG.debug("Deleting sg rule with ID: %s", security_group_rule_id)
        os_net.delete_security_group_rule(security_group_rule_id)
    except os_exc.SDKException as exc:
        np = utils.get_referenced_object(knp, 'NetworkPolicy')
        k8s.add_event(np, 'FailedToDeleteSecurityGroupRule',
                      f'Deleting security group rule for corresponding '
                      f'Network Policy has failed: {exc}',
                      'Warning')
        LOG.debug("Error deleting security group rule: %s",
                  security_group_rule_id)
        raise


def patch_kuryrnetworkpolicy_crd(crd, i_rules, e_rules):
    kubernetes = clients.get_kubernetes_client()
    crd_name = crd['metadata']['name']
    LOG.debug('Patching KuryrNetworkPolicy CRD %s' % crd_name)
    try:
        spec = {
            'ingressSgRules': i_rules,
            'egressSgRules': e_rules,
        }

        kubernetes.patch_crd('spec', utils.get_res_link(crd), spec)
    except k_exc.K8sResourceNotFound:
        LOG.debug('KuryrNetworkPolicy CRD not found %s', crd_name)
    except k_exc.K8sClientException:
        LOG.exception('Error updating KuryrNetworkPolicy CRD %s', crd_name)
        raise


def create_security_group_rule_body(
        direction, port_range_min=None, port_range_max=None, protocol=None,
        ethertype='IPv4', cidr=None,
        description="Kuryr-Kubernetes NetPolicy SG rule", namespace=None,
        pods=None):

    if port_range_min and not port_range_max:
        port_range_max = port_range_min

    if cidr and netaddr.IPNetwork(cidr).version == 6:
        ethertype = 'IPv6'

    security_group_rule_body = {
        'sgRule': {
            'ethertype': ethertype,
            'description': description,
            'direction': direction,
        }
    }
    if port_range_min and port_range_max:
        security_group_rule_body['sgRule']['port_range_min'] = port_range_min
        security_group_rule_body['sgRule']['port_range_max'] = port_range_max
    if protocol:
        security_group_rule_body['sgRule']['protocol'] = protocol.lower()
    if cidr:
        security_group_rule_body['sgRule']['remote_ip_prefix'] = cidr
    if namespace:
        security_group_rule_body['namespace'] = namespace
    if pods:
        security_group_rule_body['affectedPods'] = [
            {'podIP': ip, 'podNamespace': ns} for ip, ns in pods.items() if ip]
    LOG.debug("Creating sg rule body %s", security_group_rule_body)
    return security_group_rule_body


def get_pod_ip(pod):
    try:
        kp = get_kuryrport(pod)
        vif = [x['vif'] for x in kp['status']['vifs'].values()
               if x['default']][0]
    except (KeyError, TypeError, IndexError):
        return None
    return (vif['versioned_object.data']['network']
            ['versioned_object.data']['subnets']
            ['versioned_object.data']['objects'][0]
            ['versioned_object.data']['ips']
            ['versioned_object.data']['objects'][0]
            ['versioned_object.data']['address'])


def get_annotations(resource, annotation):
    try:
        annotations = resource['metadata']['annotations']
        return annotations[annotation]
    except KeyError:
        return None


def get_annotated_labels(resource, annotation_labels):
    labels_annotation = get_annotations(resource, annotation_labels)
    if labels_annotation:
        return jsonutils.loads(labels_annotation)
    return None


def get_kuryrnetworkpolicy_crds(namespace=None):

    try:
        if namespace:
            knp_path = '{}/{}/kuryrnetworkpolicies'.format(
                constants.K8S_API_CRD_NAMESPACES, namespace)
        else:
            knp_path = constants.K8S_API_CRD_KURYRNETWORKPOLICIES
        knps = get_k8s_resources(knp_path)
        LOG.debug("Returning KuryrNetworkPolicies %s", knps)
    except k_exc.K8sClientException:
        LOG.exception("Exception during fetch KuryrNetworkPolicies. Retrying.")
        raise k_exc.ResourceNotReady(knp_path)
    return knps


def get_kuryrloadbalancer_crds(namespace=None):
    if namespace:
        klb_path = '{}/{}/kuryrloadbalancers'.format(
            constants.K8S_API_CRD_KURYRLOADBALANCERS, namespace)
    else:
        klb_path = constants.K8S_API_CRD_KURYRLOADBALANCERS
    klbs = get_k8s_resources(klb_path)
    return klbs


def get_k8s_resources(resource_path):
    kubernetes = clients.get_kubernetes_client()
    k8s_resource = {}
    try:
        k8s_resource = kubernetes.get(resource_path)
    except k_exc.K8sResourceNotFound:
        LOG.exception('Kubernetes CRD not found')
        return []
    return k8s_resource.get('items', [])


def get_k8s_resource(resource_path):
    kubernetes = clients.get_kubernetes_client()
    k8s_resource = {}
    try:
        k8s_resource = kubernetes.get(resource_path)
    except k_exc.K8sResourceNotFound:
        LOG.debug('Kubernetes CRD not found %s', resource_path)
        return k8s_resource
    return k8s_resource


def get_networkpolicies(namespace=None):
    # FIXME(dulek): This is awful, shouldn't we have list method on k8s_client?
    kubernetes = clients.get_kubernetes_client()

    try:
        if namespace:
            np_path = '{}/{}/networkpolicies'.format(
                constants.K8S_API_NETWORKING_NAMESPACES, namespace)
        else:
            np_path = constants.K8S_API_POLICIES
        nps = kubernetes.get(np_path)
    except k_exc.K8sResourceNotFound:
        LOG.exception("NetworkPolicy or namespace %s not found", namespace)
        raise
    except k_exc.K8sClientException:
        LOG.exception("Exception when listing NetworkPolicies.")
        raise
    return nps.get('items', [])


def zip_resources(xs, ys):
    """Returns tuples of resources matched by namespace and name.

    :param xs: List of objects x, first level of iteration.
    :param ys: List of objects y.
    :return: List of tuples of matching (x, y)
    """
    pairs = []
    for x in xs:
        for y in ys:
            if utils.get_res_unique_name(x) == utils.get_res_unique_name(y):
                pairs.append((x, y))
                break
    return pairs


def zip_knp_np(knps, nps):
    """Returns tuples of matching KuryrNetworkPolicy and NetworkPolicy objs.

    :param knps: List of KuryrNetworkPolicy objects
    :param nps: List of NetworkPolicy objects
    :return: List of tuples of matching (knp, np)
    """
    return zip_resources(knps, nps)


def match_expressions(expressions, labels):
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


def match_labels(crd_labels, labels):
    for crd_key, crd_value in crd_labels.items():
        label_value = labels.get(crd_key, None)
        if not label_value or crd_value != label_value:
            return False
    return True


def match_selector(selector, labels):
    if selector is None:
        return True
    if labels is None:
        labels = {}
    crd_labels = selector.get('matchLabels', None)
    crd_expressions = selector.get('matchExpressions', None)

    match_exp = match_lb = True
    if crd_expressions:
        match_exp = match_expressions(crd_expressions, labels)
    if crd_labels:
        match_lb = match_labels(crd_labels, labels)
    return match_exp and match_lb


def get_namespace_subnet_cidr(namespace):
    kubernetes = clients.get_kubernetes_client()
    try:
        net_crd_path = (f"{constants.K8S_API_CRD_NAMESPACES}/"
                        f"{namespace['metadata']['name']}/kuryrnetworks/"
                        f"{namespace['metadata']['name']}")
        net_crd = kubernetes.get(net_crd_path)
    except k_exc.K8sResourceNotFound:
        LOG.warning('Namespace %s not yet ready',
                    namespace['metadata']['name'])
        return None
    except k_exc.K8sClientException:
        LOG.exception("Kubernetes Client Exception.")
        raise
    try:
        subnet_cidr = net_crd['status']['subnetCIDR']
    except KeyError:
        LOG.exception('Namespace not yet ready')
        raise k_exc.ResourceNotReady(namespace)
    return subnet_cidr


def tag_neutron_resources(resources, exceptions=False):
    """Set tags to the provided resources.

    param resources: list of openstacksdk objects to tag.
    param exceptions: if true, SDKException will not be ignored
    """
    tags = CONF.neutron_defaults.resource_tags
    if not tags:
        return

    os_net = clients.get_network_client()
    for res in resources:
        try:
            os_net.set_tags(res, tags=tags)
        except os_exc.SDKException:
            LOG.warning("Failed to tag %s with %s. Ignoring, but this is "
                        "still unexpected.", res, tags, exc_info=True)
            if exceptions:
                raise


def get_services(namespace=None):
    kubernetes = clients.get_kubernetes_client()
    try:
        if namespace:
            services = kubernetes.get(
                '{}/namespaces/{}/services'.format(constants.K8S_API_BASE,
                                                   namespace))
        else:
            services = kubernetes.get(
                '{}/services'.format(constants.K8S_API_BASE))
    except k_exc.K8sClientException:
        LOG.exception('Exception when getting K8s services.')
        raise
    return services


def service_matches_affected_pods(service, pod_selectors):
    """Returns if the service is affected by the pod selectors

    Checks if the service selector matches the labelSelectors of
    NetworkPolicies.

    param service: k8s service
    param pod_selectors: a list of kubernetes labelSelectors
    return: True if the service is selected by any of the labelSelectors
            and False otherwise.
    """
    svc_selector = service['spec'].get('selector')
    if not svc_selector:
        return False
    for selector in pod_selectors:
        if match_selector(selector, svc_selector):
            return True
    return False


def get_namespaced_pods(namespace=None):
    kubernetes = clients.get_kubernetes_client()
    if namespace:
        namespace = namespace['metadata']['name']
        pods = kubernetes.get(
            '{}/namespaces/{}/pods'.format(
                constants.K8S_API_BASE, namespace))
    else:
        pods = kubernetes.get(
            '{}/pods'.format(
                constants.K8S_API_BASE))
    return pods


def get_container_ports(containers, np_port_name, pod):
    matched_ports = []
    if utils.is_host_network(pod):
        return matched_ports
    for container in containers:
        for container_port in container.get('ports', []):
            if container_port.get('name') == np_port_name:
                container_port = container_port.get('containerPort')
                if container_port not in matched_ports:
                    matched_ports.append((pod, container_port))
    return matched_ports


def get_ports(resource, port):
    """Returns values of ports that have a given port name

    Retrieves the values of ports, defined in the containers
    associated to the resource, that has its name matching a
    given port.

    param resource: k8s Pod or Namespace
    param port: a dict containing a port and protocol
    return: A list of tuples of port values and associated pods
    """
    containers = resource['spec'].get('containers')
    ports = []
    np_port = port.get('port')
    if containers:
        ports.extend(get_container_ports(containers, np_port, resource))
    else:
        pods = get_namespaced_pods(resource).get('items')
        for pod in pods:
            containers = pod['spec']['containers']
            ports.extend(get_container_ports(
                containers, np_port, pod))
    return ports


def get_namespace(namespace_name):
    kubernetes = clients.get_kubernetes_client()
    try:
        return kubernetes.get(
            '{}/namespaces/{}'.format(
                constants.K8S_API_BASE, namespace_name))
    except k_exc.K8sResourceNotFound:
        LOG.debug("Namespace not found: %s",
                  namespace_name)
        return None


def get_endpoints_targets(name, namespace):
    kubernetes = clients.get_kubernetes_client()
    target_ips = []
    try:
        klb_crd = kubernetes.get(
            f'{constants.K8S_API_CRD_NAMESPACES}/{namespace}/'
            f'kuryrloadbalancers/{name}')
    except k_exc.K8sResourceNotFound:
        LOG.debug("KuryrLoadBalancer %s not found on Namespace %s.",
                  name, namespace)
        return target_ips
    except k_exc.K8sClientException:
        LOG.exception('Exception when getting K8s Endpoints.')
        raise

    for ep_slice in klb_crd['spec'].get('endpointSlices', []):
        for endpoint in ep_slice.get('endpoints', []):
            target_ips.extend(endpoint.get('addresses', []))
    return target_ips


def bump_networkpolicy(knp):
    kubernetes = clients.get_kubernetes_client()

    try:
        kubernetes.annotate(
            knp['metadata']['annotations']['networkPolicyLink'],
            {constants.K8S_ANNOTATION_POLICY: str(uuid.uuid4())})
    except k_exc.K8sResourceNotFound:
        raise
    except k_exc.K8sClientException:
        LOG.exception("Failed to annotate network policy %s to force its "
                      "recalculation.", utils.get_res_unique_name(knp))
        raise


def bump_networkpolicies(namespace=None):
    k8s = clients.get_kubernetes_client()
    nps = get_networkpolicies(namespace)
    for np in nps:
        try:
            k8s.annotate(utils.get_res_link(np),
                         {constants.K8S_ANNOTATION_POLICY: str(uuid.uuid4())})
        except k_exc.K8sResourceNotFound:
            # Ignore if NP got deleted.
            pass
        except k_exc.K8sClientException:
            LOG.warning("Failed to annotate network policy %s to force its "
                        "recalculation.", utils.get_res_unique_name(np))
            continue


def is_network_policy_enabled():
    enabled_handlers = CONF.kubernetes.enabled_handlers
    svc_sg_driver = CONF.kubernetes.service_security_groups_driver
    return 'policy' in enabled_handlers and svc_sg_driver == 'policy'


def delete_port(leftover_port):
    os_net = clients.get_network_client()

    try:
        # NOTE(gryf): there is unlikely, that we get an exception
        # like PortNotFound or something, since openstacksdk
        # doesn't raise an exception if port doesn't exists nor
        # return any information.
        os_net.delete_port(leftover_port.id)
        return True
    except os_exc.SDKException as e:
        if "currently a subport for trunk" in str(e):
            if leftover_port.status == "DOWN":
                LOG.warning("Port %s is in DOWN status but still "
                            "associated to a trunk. This should "
                            "not happen. Trying to delete it from "
                            "the trunk.", leftover_port.id)

            # Get the trunk_id from the error message
            trunk_id = (
                str(e).split('trunk')[1].split('.')[0].strip())
            try:
                os_net.delete_trunk_subports(
                    trunk_id, [{'port_id': leftover_port.id}])
            except os_exc.ResourceNotFound:
                LOG.debug(
                    "Port %s already removed from trunk %s",
                    leftover_port.id, trunk_id)
            try:
                os_net.delete_port(leftover_port.id)
                return True
            except os_exc.SDKException:
                LOG.exception("Unexpected error deleting "
                              "leftover port %s. Skipping it "
                              "and continue with the other "
                              "rest.", leftover_port.id)
        else:
            LOG.exception("Unexpected error deleting leftover "
                          "port %s. Skipping it and "
                          "continue with the other "
                          "rest.", leftover_port.id)
    return False


def get_resource_name(name, uid='', prefix='', suffix=''):
    """Get OpenStack resource name out of Kubernetes resources

    Return name for the OpenStack resource, which usually is up to 255 chars
    long. And while Kubernetes allows to set resource names up to 253
    characters, that makes a risk to have too long name. This function will
    favor UID, prefix and suffix over name of the k8s resource, which will get
    truncated if needed.

    https://kubernetes.io/docs/concepts/overview/working-with-objects/names/
    """
    if uid:
        uid += '/'

    length = len(f'{prefix}{uid}{name}{suffix}')

    if length > 255:
        name = name[:254-(length-254)]

    return f'{prefix}{uid}{name}{suffix}'


def delete_ports(leftover_port_list):
    pool = eventlet.GreenPool(constants.LEFTOVER_RM_POOL_SIZE)
    return all([i for i in pool.imap(delete_port, leftover_port_list)])


def delete_neutron_port(port):
    os_net = clients.get_network_client()
    try:
        os_net.delete_port(port)
    except Exception as ex:
        # NOTE(gryf): Catching all the exceptions here is intentional, since
        # this function is intended to be run in the greenthread. User needs
        # to examine return value and decide which exception can be safely
        # skipped, and which need to be handled/raised.
        return ex
    return None
