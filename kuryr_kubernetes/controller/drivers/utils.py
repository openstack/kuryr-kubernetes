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

from oslo_cache import core as cache
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from six.moves.urllib import parse

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import os_vif_util as ovu
from kuryr_kubernetes import utils

from neutronclient.common import exceptions as n_exc

OPERATORS_WITH_VALUES = [constants.K8S_OPERATOR_IN,
                         constants.K8S_OPERATOR_NOT_IN]

LOG = log.getLogger(__name__)

CONF = cfg.CONF

pod_ip_caching_opts = [
    cfg.BoolOpt('caching', default=True),
    cfg.IntOpt('cache_time', default=3600),
]

CONF.register_opts(pod_ip_caching_opts, "pod_ip_caching")

cache.configure(CONF)
pod_ip_cache_region = cache.create_region()
MEMOIZE = cache.get_memoization_decorator(
    CONF, pod_ip_cache_region, "pod_ip_caching")

cache.configure_cache_region(CONF, pod_ip_cache_region)


def get_network_id(subnets):
    ids = ovu.osvif_to_neutron_network_ids(subnets)

    if len(ids) != 1:
        raise k_exc.IntegrityError(
            "Subnet mapping %(subnets)s is not valid: "
            "%(num_networks)s unique networks found" %
            {'subnets': subnets, 'num_networks': len(ids)})

    return ids[0]


def get_port_name(pod):
    return "%(namespace)s/%(name)s" % pod['metadata']


def get_device_id(pod):
    return pod['metadata']['uid']


def get_host_id(pod):
    return pod['spec']['nodeName']


def get_pod_state(pod):
    try:
        annotations = pod['metadata']['annotations']
        state_annotation = annotations[constants.K8S_ANNOTATION_VIF]
    except KeyError:
        return None
    state_annotation = jsonutils.loads(state_annotation)
    state = utils.extract_pod_annotation(state_annotation)
    return state


def is_host_network(pod):
    return pod['spec'].get('hostNetwork', False)


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
                expressions = parse.quote("," + exps)
                labels += expressions
            else:
                labels = parse.quote(exps)

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
            expressions = parse.quote("," + exps)
            labels += expressions
        else:
            labels = parse.quote(exps)

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
    labels = parse.urlencode(labels)
    # NOTE(ltomasbo): K8s API does not accept &, so we need to AND
    # the matchLabels with ',' or '%2C' instead
    labels = labels.replace('&', ',')
    return labels


def create_security_group_rule(body):
    neutron = clients.get_neutron_client()
    sgr = ''
    try:
        sgr = neutron.create_security_group_rule(
            body=body)
    except n_exc.Conflict as ex:
        LOG.debug("Failed to create already existing security group "
                  "rule %s", body)
        # Get existent sg rule id from exception message
        sgr_id = str(ex).split("Rule id is", 1)[1].split()[0][:-1]
        return sgr_id
    except n_exc.NeutronClientException:
        LOG.debug("Error creating security group rule")
        raise
    return sgr["security_group_rule"]["id"]


def delete_security_group_rule(security_group_rule_id):
    neutron = clients.get_neutron_client()
    try:
        LOG.debug("Deleting sg rule with ID: %s", security_group_rule_id)
        neutron.delete_security_group_rule(
            security_group_rule=security_group_rule_id)
    except n_exc.NotFound:
        LOG.debug("Error deleting security group rule as it does not "
                  "exist: %s", security_group_rule_id)
    except n_exc.NeutronClientException:
        LOG.debug("Error deleting security group rule: %s",
                  security_group_rule_id)
        raise


def patch_kuryrnet_crd(crd, populated=True):
    kubernetes = clients.get_kubernetes_client()
    crd_name = crd['metadata']['name']
    LOG.debug('Patching KuryrNet CRD %s' % crd_name)
    try:
        kubernetes.patch_crd('spec', crd['metadata']['selfLink'],
                             {'populated': populated})
    except k_exc.K8sClientException:
        LOG.exception('Error updating kuryrnet CRD %s', crd_name)
        raise


def patch_kuryrnetworkpolicy_crd(crd, i_rules, e_rules, pod_selector,
                                 np_spec=None):
    kubernetes = clients.get_kubernetes_client()
    crd_name = crd['metadata']['name']
    if not np_spec:
        np_spec = crd['spec']['networkpolicy_spec']
    LOG.debug('Patching KuryrNetPolicy CRD %s' % crd_name)
    try:
        kubernetes.patch_crd('spec', crd['metadata']['selfLink'],
                             {'ingressSgRules': i_rules,
                              'egressSgRules': e_rules,
                              'podSelector': pod_selector,
                              'networkpolicy_spec': np_spec})
    except k_exc.K8sResourceNotFound:
        LOG.debug('KuryrNetPolicy CRD not found %s', crd_name)
    except k_exc.K8sClientException:
        LOG.exception('Error updating kuryrnetpolicy CRD %s', crd_name)
        raise


def create_security_group_rule_body(
        security_group_id, direction, port_range_min=None,
        port_range_max=None, protocol=None, ethertype='IPv4', cidr=None,
        description="Kuryr-Kubernetes NetPolicy SG rule", namespace=None,
        pods=None):
    if not port_range_min:
        port_range_min = 1
        port_range_max = 65535
    elif not port_range_max:
        port_range_max = port_range_min
    if not protocol:
        protocol = 'TCP'
    security_group_rule_body = {
        u'security_group_rule': {
            u'ethertype': ethertype,
            u'security_group_id': security_group_id,
            u'description': description,
            u'direction': direction,
            u'protocol': protocol.lower(),
            u'port_range_min': port_range_min,
            u'port_range_max': port_range_max,
        }
    }
    if cidr:
        security_group_rule_body[u'security_group_rule'][
            u'remote_ip_prefix'] = cidr
    if namespace:
        security_group_rule_body['namespace'] = namespace
    if pods:
        security_group_rule_body['remote_ip_prefixes'] = pods
    LOG.debug("Creating sg rule body %s", security_group_rule_body)
    return security_group_rule_body


@MEMOIZE
def get_pod_ip(pod):
    try:
        pod_metadata = pod['metadata']['annotations']
        vif = pod_metadata[constants.K8S_ANNOTATION_VIF]
    except KeyError:
        return None
    vif = jsonutils.loads(vif)
    vif = vif['versioned_object.data']['default_vif']
    network = (vif['versioned_object.data']['network']
                  ['versioned_object.data'])
    first_subnet = (network['subnets']['versioned_object.data']
                    ['objects'][0]['versioned_object.data'])
    first_subnet_ip = (first_subnet['ips']['versioned_object.data']
                       ['objects'][0]['versioned_object.data']['address'])
    return first_subnet_ip


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


def get_kuryrnetpolicy_crds(namespace=None):
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
    except k_exc.K8sResourceNotFound:
        LOG.exception("KuryrNetPolicy CRD not found")
        raise
    except k_exc.K8sClientException:
        LOG.exception("Kubernetes Client Exception")
        raise
    return knps


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
    crd_labels = selector.get('matchLabels', None)
    crd_expressions = selector.get('matchExpressions', None)

    match_exp = match_lb = True
    if crd_expressions:
        match_exp = match_expressions(crd_expressions,
                                      labels)
    if crd_labels and labels:
        match_lb = match_labels(crd_labels, labels)
    return match_exp and match_lb


def get_namespace_subnet_cidr(namespace):
    kubernetes = clients.get_kubernetes_client()
    try:
        ns_annotations = namespace['metadata']['annotations']
        ns_name = ns_annotations[constants.K8S_ANNOTATION_NET_CRD]
    except KeyError:
        LOG.exception('Namespace handler must be enabled to support '
                      'Network Policies with namespaceSelector')
        raise k_exc.ResourceNotReady(namespace)
    try:
        net_crd = kubernetes.get('{}/kuryrnets/{}'.format(
            constants.K8S_API_CRD, ns_name))
    except k_exc.K8sClientException:
        LOG.exception("Kubernetes Client Exception.")
        raise
    return net_crd['spec']['subnetCIDR']


def tag_neutron_resources(resource, res_ids):
    tags = CONF.neutron_defaults.resource_tags
    if tags:
        neutron = clients.get_neutron_client()
        for res_id in res_ids:
            try:
                neutron.replace_tag(resource, res_id, body={"tags": tags})
            except n_exc.NeutronClientException:
                LOG.warning("Failed to tag %s %s with %s. Ignoring, but this "
                            "is still unexpected.", resource, res_id, tags,
                            exc_info=True)


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
    if is_host_network(pod):
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
    return kubernetes.get(
        '{}/namespaces/{}'.format(
            constants.K8S_API_BASE, namespace_name))


def update_port_pci_info(pod, vif):
    node = get_host_id(pod)
    annot_port_pci_info = get_port_annot_pci_info(node, vif.id)
    neutron = clients.get_neutron_client()
    LOG.debug("Neutron port %s is updated with binding:profile info %s",
              vif.id, annot_port_pci_info)
    neutron.update_port(
        vif.id,
        {
            "port": {
                'binding:profile': annot_port_pci_info
            }
        })


def get_port_annot_pci_info(nodename, neutron_port):
    k8s = clients.get_kubernetes_client()
    annot_name = constants.K8S_ANNOTATION_NODE_PCI_DEVICE_INFO
    annot_name = annot_name + '-' + neutron_port

    node_info = k8s.get('/api/v1/nodes/{}'.format(nodename))
    annotations = node_info['metadata']['annotations']
    try:
        json_pci_info = annotations[annot_name]
        pci_info = jsonutils.loads(json_pci_info)
    except KeyError:
        pci_info = {}
    except Exception:
        LOG.exception('Exception when reading annotations '
                      '%s and converting from json', annot_name)
    return pci_info


def get_ports_by_attrs(**attrs):
    neutron = clients.get_neutron_client()
    ports = neutron.list_ports(**attrs)
    return ports['ports']
