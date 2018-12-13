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
from kuryr_kubernetes import exceptions

from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


OPERATORS_WITH_VALUES = [constants.K8S_OPERATOR_IN,
                         constants.K8S_OPERATOR_NOT_IN]


def _get_kuryrnetpolicy_crds(namespace='default'):
    kubernetes = clients.get_kubernetes_client()

    try:
        knp_path = '{}/{}/kuryrnetpolicies'.format(
            constants.K8S_API_CRD_NAMESPACES, namespace)
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


def _match_expressions(expressions, pod_labels):
    for exp in expressions:
        exp_op = exp['operator'].lower()
        if pod_labels:
            if exp_op in OPERATORS_WITH_VALUES:
                exp_values = exp['values']
                pod_value = pod_labels.get(str(exp['key']), None)
                if exp_op == constants.K8S_OPERATOR_IN:
                    if pod_value is None or pod_value not in exp_values:
                            return False
                elif exp_op == constants.K8S_OPERATOR_NOT_IN:
                    if pod_value in exp_values:
                        return False
            else:
                if exp_op == constants.K8S_OPERATOR_EXISTS:
                    exists = pod_labels.get(str(exp['key']), None)
                    if exists is None:
                        return False
                elif exp_op == constants.K8S_OPERATOR_DOES_NOT_EXIST:
                    exists = pod_labels.get(str(exp['key']), None)
                    if exists is not None:
                        return False
        else:
            if exp_op in (constants.K8S_OPERATOR_IN,
                          constants.K8S_OPERATOR_EXISTS):
                return False
    return True


def _match_labels(crd_labels, pod_labels):
    for label_key, label_value in crd_labels.items():
        pod_value = pod_labels.get(label_key, None)
        if not pod_value or label_value != pod_value:
                return False
    return True


class NetworkPolicySecurityGroupsDriver(base.PodSecurityGroupsDriver):
    """Provides security groups for pods based on network policies"""

    def get_security_groups(self, pod, project_id):
        sg_list = []

        pod_labels = pod['metadata'].get('labels')
        pod_namespace = pod['metadata']['namespace']

        knp_crds = _get_kuryrnetpolicy_crds(namespace=pod_namespace)
        for crd in knp_crds.get('items'):
            pod_selector = crd['spec'].get('podSelector')
            if pod_selector:
                crd_labels = pod_selector.get('matchLabels', None)
                crd_expressions = pod_selector.get('matchExpressions', None)

                match_exp = match_lb = True
                if crd_expressions:
                    match_exp = _match_expressions(crd_expressions,
                                                   pod_labels)
                if crd_labels and pod_labels:
                    match_lb = _match_labels(crd_labels, pod_labels)
                if match_exp and match_lb:
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
        svc_labels = service['metadata'].get('labels')
        LOG.debug("Using labels %s", svc_labels)

        knp_crds = _get_kuryrnetpolicy_crds(namespace=svc_namespace)
        for crd in knp_crds.get('items'):
            pod_selector = crd['spec'].get('podSelector')
            if pod_selector:
                crd_labels = pod_selector.get('matchLabels', None)
                crd_expressions = pod_selector.get('matchExpressions', None)

                match_exp = match_lb = True
                if crd_expressions:
                    match_exp = _match_expressions(crd_expressions,
                                                   svc_labels)
                if crd_labels and svc_labels:
                    match_lb = _match_labels(crd_labels, svc_labels)
                if match_exp and match_lb:
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
