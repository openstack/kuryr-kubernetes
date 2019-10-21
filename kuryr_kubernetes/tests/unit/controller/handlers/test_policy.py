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

import mock

from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.handlers import policy
from kuryr_kubernetes.tests import base as test_base


class TestPolicyHandler(test_base.TestCase):

    def setUp(self):
        super(TestPolicyHandler, self).setUp()

        self._project_id = mock.sentinel.project_id
        self._policy_name = 'np-test'
        self._policy_uid = mock.sentinel.policy_uid
        self._policy_link = mock.sentinel.policy_link
        self._pod_sg = mock.sentinel.pod_sg

        self._policy = {
            u'apiVersion': u'networking.k8s.io/v1',
            u'kind': u'NetworkPolicy',
            u'metadata': {
                u'name': self._policy_name,
                u'resourceVersion': u'2259309',
                u'generation': 1,
                u'creationTimestamp': u'2018-09-18T14:09:51Z',
                u'namespace': u'default',
                u'annotations': {},
                u'selfLink': self._policy_link,
                u'uid': self._policy_uid
            },
            u'spec': {
                u'egress': [{u'ports':
                             [{u'port': 5978, u'protocol': u'TCP'}]}],
                u'ingress': [{u'ports':
                              [{u'port': 6379, u'protocol': u'TCP'}]}],
                u'policyTypes': [u'Ingress', u'Egress']
            }
        }

        self._handler = mock.MagicMock(spec=policy.NetworkPolicyHandler)

        self._handler._drv_project = mock.Mock(
            spec=drivers.NetworkPolicyProjectDriver)
        self._handler._drv_policy = mock.MagicMock(
            spec=drivers.NetworkPolicyDriver)
        self._handler._drv_pod_sg = mock.Mock(
            spec=drivers.PodSecurityGroupsDriver)
        self._handler._drv_svc_sg = mock.Mock(
            spec=drivers.ServiceSecurityGroupsDriver)
        self._handler._drv_vif_pool = mock.MagicMock(
            spec=drivers.VIFPoolDriver)
        self._handler._drv_lbaas = mock.Mock(
            spec=drivers.LBaaSDriver)

        self._get_project = self._handler._drv_project.get_project
        self._get_project.return_value = self._project_id
        self._get_security_groups = (
            self._handler._drv_pod_sg.get_security_groups)
        self._set_vifs_driver = self._handler._drv_vif_pool.set_vif_driver
        self._set_vifs_driver.return_value = mock.Mock(
            spec=drivers.PodVIFDriver)
        self._update_vif_sgs = self._handler._drv_vif_pool.update_vif_sgs
        self._update_vif_sgs.return_value = None
        self._update_lbaas_sg = self._handler._drv_lbaas.update_lbaas_sg
        self._update_lbaas_sg.return_value = None
        self._remove_sg = self._handler._drv_vif_pool.remove_sg_from_pools
        self._remove_sg.return_value = None

    def _get_knp_obj(self):
        knp_obj = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrNetPolicy',
            'metadata': {
                'name': 'np-test-network-policy',
                'namespace': 'test-1'
            },
            'spec': {
                'securityGroupId': 'c1ac16f5-e198-4628-9d84-253c6001be8e',
                'securityGroupName': 'sg-test-network-policy'
            }}
        return knp_obj

    @mock.patch.object(drivers.LBaaSDriver, 'get_instance')
    @mock.patch.object(drivers.ServiceSecurityGroupsDriver, 'get_instance')
    @mock.patch.object(drivers.PodSecurityGroupsDriver, 'get_instance')
    @mock.patch.object(drivers.VIFPoolDriver, 'get_instance')
    @mock.patch.object(drivers.NetworkPolicyDriver, 'get_instance')
    @mock.patch.object(drivers.NetworkPolicyProjectDriver, 'get_instance')
    def test_init(self, m_get_project_driver, m_get_policy_driver,
                  m_get_vif_driver, m_get_pod_sg_driver, m_get_svc_sg_driver,
                  m_get_lbaas_driver):
        handler = policy.NetworkPolicyHandler()

        m_get_project_driver.assert_called_once()
        m_get_policy_driver.assert_called_once()
        m_get_vif_driver.assert_called_once()
        m_get_pod_sg_driver.assert_called_once()
        m_get_svc_sg_driver.assert_called_once()
        m_get_lbaas_driver.assert_called_once()

        self.assertEqual(m_get_project_driver.return_value,
                         handler._drv_project)
        self.assertEqual(m_get_policy_driver.return_value, handler._drv_policy)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    def test_on_present(self, m_host_network, m_get_services):
        modified_pod = mock.sentinel.modified_pod
        match_pod = mock.sentinel.match_pod
        m_host_network.return_value = False

        knp_on_ns = self._handler._drv_policy.knps_on_namespace
        knp_on_ns.return_value = True
        namespaced_pods = self._handler._drv_policy.namespaced_pods
        ensure_nw_policy = self._handler._drv_policy.ensure_network_policy
        ensure_nw_policy.return_value = [modified_pod]
        affected_pods = self._handler._drv_policy.affected_pods
        affected_pods.return_value = [match_pod]
        sg1 = [mock.sentinel.sg1]
        sg2 = [mock.sentinel.sg2]
        self._get_security_groups.side_effect = [sg1, sg2]
        m_get_services.return_value = {'items': []}

        policy.NetworkPolicyHandler.on_present(self._handler, self._policy)
        namespaced_pods.assert_not_called()
        ensure_nw_policy.assert_called_once_with(self._policy,
                                                 self._project_id)
        affected_pods.assert_called_once_with(self._policy)

        calls = [mock.call(modified_pod, self._project_id),
                 mock.call(match_pod, self._project_id)]
        self._get_security_groups.assert_has_calls(calls)

        calls = [mock.call(modified_pod, sg1), mock.call(match_pod, sg2)]
        self._update_vif_sgs.assert_has_calls(calls)
        self._update_lbaas_sg.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    def test_on_present_without_knps_on_namespace(self, m_host_network,
                                                  m_get_services):
        modified_pod = mock.sentinel.modified_pod
        match_pod = mock.sentinel.match_pod
        m_host_network.return_value = False

        ensure_nw_policy = self._handler._drv_policy.ensure_network_policy
        ensure_nw_policy.return_value = [modified_pod]
        affected_pods = self._handler._drv_policy.affected_pods
        affected_pods.return_value = [match_pod]
        sg2 = [mock.sentinel.sg2]
        sg3 = [mock.sentinel.sg3]
        self._get_security_groups.side_effect = [sg2, sg3]
        m_get_services.return_value = {'items': []}

        policy.NetworkPolicyHandler.on_present(self._handler, self._policy)
        ensure_nw_policy.assert_called_once_with(self._policy,
                                                 self._project_id)
        affected_pods.assert_called_once_with(self._policy)

        calls = [mock.call(modified_pod, self._project_id),
                 mock.call(match_pod, self._project_id)]
        self._get_security_groups.assert_has_calls(calls)

        calls = [mock.call(modified_pod, sg2),
                 mock.call(match_pod, sg3)]
        self._update_vif_sgs.assert_has_calls(calls)
        self._update_lbaas_sg.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    def test_on_present_with_services(self, m_host_network, m_get_services):
        modified_pod = mock.sentinel.modified_pod
        match_pod = mock.sentinel.match_pod
        m_host_network.return_value = False

        self._handler._is_egress_only_policy.return_value = False
        self._handler._is_service_affected.return_value = True
        knp_on_ns = self._handler._drv_policy.knps_on_namespace
        knp_on_ns.return_value = True
        namespaced_pods = self._handler._drv_policy.namespaced_pods
        ensure_nw_policy = self._handler._drv_policy.ensure_network_policy
        ensure_nw_policy.return_value = [modified_pod]
        affected_pods = self._handler._drv_policy.affected_pods
        affected_pods.return_value = [match_pod]
        sg1 = [mock.sentinel.sg1]
        sg2 = [mock.sentinel.sg2]
        self._get_security_groups.side_effect = [sg1, sg2]
        service = {'metadata': {'name': 'service-test'},
                   'spec': {'selector': mock.sentinel.selector}}
        m_get_services.return_value = {'items': [service]}

        policy.NetworkPolicyHandler.on_present(self._handler, self._policy)
        namespaced_pods.assert_not_called()
        ensure_nw_policy.assert_called_once_with(self._policy,
                                                 self._project_id)
        affected_pods.assert_called_once_with(self._policy)

        calls = [mock.call(modified_pod, self._project_id),
                 mock.call(match_pod, self._project_id)]
        self._get_security_groups.assert_has_calls(calls)
        calls = [mock.call(modified_pod, sg1), mock.call(match_pod, sg2)]
        self._update_vif_sgs.assert_has_calls(calls)
        self._handler._is_service_affected.assert_called_once_with(
            service, [modified_pod, match_pod])
        self._update_lbaas_sg.assert_called_once()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    def test_on_deleted(self, m_host_network, m_get_services):
        namespace_pod = mock.sentinel.namespace_pod
        match_pod = mock.sentinel.match_pod
        m_host_network.return_value = False
        affected_pods = self._handler._drv_policy.affected_pods
        affected_pods.return_value = [match_pod]
        get_knp_crd = self._handler._drv_policy.get_kuryrnetpolicy_crd
        knp_obj = self._get_knp_obj()
        get_knp_crd.return_value = knp_obj
        sg1 = [mock.sentinel.sg1]
        sg2 = [mock.sentinel.sg2]
        self._get_security_groups.side_effect = [sg1, sg2]
        m_get_services.return_value = {'items': []}
        release_nw_policy = self._handler._drv_policy.release_network_policy
        knp_on_ns = self._handler._drv_policy.knps_on_namespace
        knp_on_ns.return_value = False
        ns_pods = self._handler._drv_policy.namespaced_pods
        ns_pods.return_value = [namespace_pod]

        policy.NetworkPolicyHandler.on_deleted(self._handler, self._policy)
        release_nw_policy.assert_called_once_with(knp_obj)
        self._get_security_groups.assert_called_once_with(match_pod,
                                                          self._project_id)
        self._update_vif_sgs.assert_called_once_with(match_pod, sg1)
        self._update_lbaas_sg.assert_not_called()
        self._remove_sg.assert_called_once()
