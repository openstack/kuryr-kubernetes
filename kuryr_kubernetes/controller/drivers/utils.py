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

from oslo_serialization import jsonutils
from six.moves.urllib import parse

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes import os_vif_util as ovu
from kuryr_kubernetes import utils

OPERATORS_WITH_VALUES = [constants.K8S_OPERATOR_IN,
                         constants.K8S_OPERATOR_NOT_IN]


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


def get_pods(selector, namespace):
    """Return a k8s object list with the pods matching the selector.

    It accepts an optional parameter to state the namespace where the pod
    selector will be apply. If empty namespace is passed, then the pod
    selector is applied in all namespaces.

    param selector: k8s selector of types matchLabels or matchExpressions
    param namespace: namespace name where the selector will be applied. If
                     None, the pod selector is applied in all namespaces
    return: k8s list objec containing all matching pods

    """
    kubernetes = clients.get_kubernetes_client()
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
    return: k8s list objec containing all matching namespaces

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
