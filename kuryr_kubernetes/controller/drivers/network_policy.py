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


from oslo_log import log as logging

from neutronclient.common import exceptions as n_exc

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions

LOG = logging.getLogger(__name__)


class NetworkPolicyDriver(base.NetworkPolicyDriver):
    """Provides security groups actions based on K8s Network Policies"""

    def ensure_network_policy(self, policy, project_id):
        neutron = clients.get_neutron_client()
        LOG.debug("Creating network policy %s" % policy['metadata']['name'])
        if self._get_kuryrnetpolicy_crd(policy):
            LOG.debug("Already existing CRD")
            return
        security_group_body = {
            "security_group":
            {
                "name": policy['metadata']['name'],
                "project_id": project_id
                }
            }
        try:
            sg = neutron.create_security_group(body=security_group_body)
        except n_exc.NeutronClientException:
            LOG.exception("Error creating security group for network policy. ")
            raise
        try:
            self._add_kuryrnetpolicy_crd(policy, project_id,
                                         sg['security_group']['id'])
        except exceptions.K8sClientException:
            LOG.exception("Rolling back security groups")
            neutron.delete_security_group(sg['security_group']['id'])
            raise

    def release_network_policy(self, policy, project_id):
        neutron = clients.get_neutron_client()
        netpolicy_crd = self._get_kuryrnetpolicy_crd(policy)
        if netpolicy_crd is not None:
            try:
                sg_id = netpolicy_crd['spec']['securityGroupId']
                neutron.delete_security_group(sg_id)
            except n_exc.NotFound:
                LOG.debug("Security Group not found: %s", sg_id)
            except n_exc.NeutronClientException:
                LOG.exception("Error deleting security group %s.", sg_id)
                raise
            self._del_kuryrnetpolicy_crd(
                netpolicy_crd['metadata']['name'],
                netpolicy_crd['metadata']['namespace'])

    def _get_kuryrnetpolicy_crd(self, policy):
        kubernetes = clients.get_kubernetes_client()
        netpolicy_crd_name = "np-" + policy['metadata']['name']
        netpolicy_crd_namespace = policy['metadata']['namespace']
        try:
            netpolicy_crd = kubernetes.get('{}/{}/kuryrnetpolicies/{}'.format(
                constants.K8S_API_CRD_NAMESPACES, netpolicy_crd_namespace,
                netpolicy_crd_name))
        except exceptions.K8sResourceNotFound:
            return None
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return netpolicy_crd

    def _add_kuryrnetpolicy_crd(self, policy,  project_id, sg_id):
        kubernetes = clients.get_kubernetes_client()
        netpolicy_crd_name = "np-" + policy['metadata']['name']
        netpolicy_crd_namespace = policy['metadata']['namespace']
        netpolicy_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': constants.K8S_OBJ_KURYRNETPOLICY,
            'metadata': {
                'name': netpolicy_crd_name,
                'namespace': netpolicy_crd_namespace,
                'annotations': {
                    'policy': policy
                }
            },
            'spec': {
                'securityGroupName': policy['metadata']['name'],
                'securityGroupId': sg_id,
            },
        }
        try:
            LOG.debug("Creating KuryrNetPolicy CRD %s" % netpolicy_crd)
            kubernetes_post = '{}/{}/kuryrnetpolicies'.format(
                constants.K8S_API_CRD_NAMESPACES,
                netpolicy_crd_namespace)
            kubernetes.post(kubernetes_post, netpolicy_crd)
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception creating kuryrnetpolicy"
                          " CRD. %s" % exceptions.K8sClientException)
            raise
        return netpolicy_crd

    def _del_kuryrnetpolicy_crd(self, netpolicy_crd_name,
                                netpolicy_crd_namespace):
        kubernetes = clients.get_kubernetes_client()
        try:
            LOG.debug("Deleting KuryrNetPolicy CRD %s" % netpolicy_crd_name)
            kubernetes.delete('{}/{}/kuryrnetpolicies/{}'.format(
                constants.K8S_API_CRD_NAMESPACES,
                netpolicy_crd_namespace,
                netpolicy_crd_name))
        except exceptions.K8sClientException:
            LOG.exception("Kubernetes Client Exception deleting kuryrnetpolicy"
                          " CRD.")
            raise
