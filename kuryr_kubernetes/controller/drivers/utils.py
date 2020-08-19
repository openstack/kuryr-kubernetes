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
    ids = list(set(net.id for net in subnets.values()))

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


def get_kuryrport(pod):
    k8s = clients.get_kubernetes_client()
    try:
        return k8s.get(f'{constants.K8S_API_CRD_NAMESPACES}/'
                       f'{pod["metadata"]["namespace"]}/kuryrports/'
                       f'{pod["metadata"]["name"]}')
    except k_exc.K8sResourceNotFound:
        return None


def get_vifs(pod):
    kp = get_kuryrport(pod)
    try:
        return {k: objects.base.VersionedObject.obj_from_primitive(v['vif'])
                for k, v in kp['status']['vifs'].items()}
    except (KeyError, AttributeError, TypeError):
        return {}


def is_host_network(pod):
    return pod['status'].get('hostNetwork', False)


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


def create_security_group_rule(body):
    os_net = clients.get_network_client()

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
            LOG.error("Failed to create security group rule %s: %s", body,
                      ex.details)
            raise
        else:
            LOG.debug("Failed to create already existing security group "
                      "rule %s", body)
            # Get existent sg rule id from exception message
            return str(ex).split()[-1][:-1]
    except os_exc.SDKException:
        LOG.debug("Error creating security group rule")
        raise


def delete_security_group_rule(security_group_rule_id):
    os_net = clients.get_network_client()
    try:
        LOG.debug("Deleting sg rule with ID: %s", security_group_rule_id)
        os_net.delete_security_group_rule(security_group_rule_id)
    except os_exc.SDKException:
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

        kubernetes.patch_crd('spec', crd['metadata']['selfLink'], spec)
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
    if not port_range_min:
        port_range_min = 1
        port_range_max = 65535
    elif not port_range_max:
        port_range_max = port_range_min
    if not protocol:
        protocol = 'TCP'

    if cidr and netaddr.IPNetwork(cidr).version == 6:
        ethertype = 'IPv6'

    security_group_rule_body = {
        'sgRule': {
            'ethertype': ethertype,
            'description': description,
            'direction': direction,
            'protocol': protocol.lower(),
            'port_range_min': port_range_min,
            'port_range_max': port_range_max,
        }
    }
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
    kubernetes = clients.get_kubernetes_client()

    try:
        if namespace:
            knp_path = '{}/{}/kuryrnetworkpolicies'.format(
                constants.K8S_API_CRD_NAMESPACES, namespace)
        else:
            knp_path = constants.K8S_API_CRD_KURYRNETWORKPOLICIES
        knps = kubernetes.get(knp_path)
        LOG.debug("Returning KuryrNetworkPolicies %s", knps)
    except k_exc.K8sResourceNotFound:
        LOG.exception("KuryrNetworkPolicy CRD not found")
        return []
    except k_exc.K8sClientException:
        LOG.exception("Kubernetes Client Exception")
        raise
    return knps.get('items', [])


def get_networkpolicies(namespace=None):
    # FIXME(dulek): This is awful, shouldn't we have list method on k8s_client?
    kubernetes = clients.get_kubernetes_client()

    try:
        if namespace:
            np_path = '{}/{}/networkpolicies'.format(
                constants.K8S_API_CRD_NAMESPACES, namespace)
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


def zip_knp_np(knps, nps):
    """Returns tuples of matching KuryrNetworkPolicy and NetworkPolicy objs.

    :param knps: List of KuryrNetworkPolicy objects
    :param nps: List of NetworkPolicy objects
    :return: List of tuples of matching (knp, np)
    """
    pairs = []
    for knp in knps:
        for np in nps:
            if utils.get_res_unique_name(knp) == utils.get_res_unique_name(np):
                pairs.append((knp, np))
                break
    return pairs


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
        net_crd_path = (f"{constants.K8S_API_CRD_NAMESPACES}/"
                        f"{namespace['metadata']['name']}/kuryrnetworks/"
                        f"{namespace['metadata']['name']}")
        net_crd = kubernetes.get(net_crd_path)
    except k_exc.K8sResourceNotFound:
        LOG.exception('Namespace not yet ready')
        raise k_exc.ResourceNotReady(namespace)
    except k_exc.K8sClientException:
        LOG.exception("Kubernetes Client Exception.")
        raise
    try:
        subnet_cidr = net_crd['status']['subnetCIDR']
    except KeyError:
        LOG.exception('Namespace not yet ready')
        raise k_exc.ResourceNotReady(namespace)
    return subnet_cidr


def tag_neutron_resources(resources):
    """Set tags to the provided resources.

    param resources: list of openstacksdk objects to tag.
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
    try:
        return kubernetes.get(
            '{}/namespaces/{}'.format(
                constants.K8S_API_BASE, namespace_name))
    except k_exc.K8sResourceNotFound:
        LOG.debug("Namespace not found: %s",
                  namespace_name)
        return None


def update_port_pci_info(pod, vif):
    node = get_host_id(pod)
    annot_port_pci_info = get_port_annot_pci_info(node, vif.id)
    os_net = clients.get_network_client()
    LOG.debug("Neutron port %s is updated with binding:profile info %s",
              vif.id, annot_port_pci_info)
    os_net.update_port(vif.id, binding_profile=annot_port_pci_info)


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
