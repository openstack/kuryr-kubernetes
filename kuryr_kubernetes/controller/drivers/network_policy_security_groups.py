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

from six.moves.urllib.parse import urlencode

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions

from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


def _get_kuryrnetpolicy_crds(labels=None, namespace='default'):
    kubernetes = clients.get_kubernetes_client()
    try:
        if labels:
            LOG.debug("Using labels %s", labels)
            labels.pop('pod-template-hash', None)
            # removing pod-template-hash is necessary to fetch the proper list
            labels = urlencode(labels)
            # NOTE(maysams): K8s API does not accept &, so we need to replace
            # it with ',' or '%2C' instead
            labels = labels.replace('&', ',')
            knp_path = '{}/{}/kuryrnetpolicies?labelSelector={}'.format(
                constants.K8S_API_CRD_NAMESPACES, namespace, labels)
            LOG.debug("K8s API Query %s", knp_path)
            knps = kubernetes.get(knp_path)
            LOG.debug("Return Kuryr Network Policies with label %s", knps)
        else:
            knps = kubernetes.get('{}/{}/kuryrnetpolicies'.format(
                constants.K8S_API_CRD_NAMESPACES, namespace))
    except exceptions.K8sResourceNotFound:
        LOG.exception("KuryrNetPolicy CRD not found")
        raise
    except exceptions.K8sClientException:
        LOG.exception("Kubernetes Client Exception")
        raise
    return knps


class NetworkPolicySecurityGroupsDriver(base.PodSecurityGroupsDriver):
    """Provides security groups for pods based on network policies"""

    def get_security_groups(self, pod, project_id):
        sg_list = []
        pod_namespace = pod['metadata']['namespace']
        pod_labels = pod['metadata'].get('labels')
        LOG.debug("Using labels %s", pod_labels)

        if pod_labels:
            knp_crds = _get_kuryrnetpolicy_crds(pod_labels,
                                                namespace=pod_namespace)
            for crd in knp_crds.get('items'):
                LOG.debug("Appending %s", str(crd['spec']['securityGroupId']))
                sg_list.append(str(crd['spec']['securityGroupId']))

        knp_namespace_crds = _get_kuryrnetpolicy_crds(namespace=pod_namespace)
        for crd in knp_namespace_crds.get('items'):
            if not crd['metadata'].get('labels'):
                LOG.debug("Appending %s", str(crd['spec']['securityGroupId']))
                sg_list.append(str(crd['spec']['securityGroupId']))

        if not knp_namespace_crds.get('items') and not sg_list:
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

        if svc_labels:
            knp_crds = _get_kuryrnetpolicy_crds(svc_labels,
                                                namespace=svc_namespace)
            for crd in knp_crds.get('items'):
                LOG.debug("Appending %s", str(crd['spec']['securityGroupId']))
                sg_list.append(str(crd['spec']['securityGroupId']))

        knp_namespace_crds = _get_kuryrnetpolicy_crds(namespace=svc_namespace)
        for crd in knp_namespace_crds.get('items'):
            if not crd['metadata'].get('labels'):
                LOG.debug("Appending %s", str(crd['spec']['securityGroupId']))
                sg_list.append(str(crd['spec']['securityGroupId']))

        if not knp_namespace_crds.get('items') and not sg_list:
            sg_list = config.CONF.neutron_defaults.pod_security_groups
            if not sg_list:
                raise cfg.RequiredOptError('pod_security_groups',
                                           cfg.OptGroup('neutron_defaults'))

        return sg_list[:]
