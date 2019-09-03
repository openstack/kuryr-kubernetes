# Copyright (c) 2016 Mirantis, Inc.
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

import mock

from os_vif import objects as os_obj

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.handlers import vif as h_vif
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import vif
from kuryr_kubernetes.tests import base as test_base


class TestVIFHandler(test_base.TestCase):

    def setUp(self):
        super(TestVIFHandler, self).setUp()

        self._project_id = mock.sentinel.project_id
        self._subnets = mock.sentinel.subnets
        self._security_groups = mock.sentinel.security_groups
        self._vif = os_obj.vif.VIFBase()
        self._vif.active = True
        self._vif_serialized = mock.sentinel.vif_serialized
        self._multi_vif_drv = mock.MagicMock(spec=drivers.MultiVIFDriver)
        self._additioan_vifs = []
        self._state = vif.PodState(default_vif=self._vif)

        self._pod_version = mock.sentinel.pod_version
        self._pod_link = mock.sentinel.pod_link
        self._pod_namespace = mock.sentinel.namespace
        self._pod = {
            'metadata': {'resourceVersion': self._pod_version,
                         'selfLink': self._pod_link,
                         'namespace': self._pod_namespace},
            'status': {'phase': k_const.K8S_POD_STATUS_PENDING},
            'spec': {'hostNetwork': False,
                     'nodeName': 'hostname'}
        }

        self._handler = mock.MagicMock(spec=h_vif.VIFHandler)
        self._handler._drv_project = mock.Mock(spec=drivers.PodProjectDriver)
        self._handler._drv_subnets = mock.Mock(spec=drivers.PodSubnetsDriver)
        self._handler._drv_sg = mock.Mock(spec=drivers.PodSecurityGroupsDriver)
        self._handler._drv_vif = mock.Mock(spec=drivers.PodVIFDriver)
        self._handler._drv_vif_pool = mock.MagicMock(
            spec=drivers.VIFPoolDriver)
        self._handler._drv_multi_vif = [self._multi_vif_drv]

        self._get_project = self._handler._drv_project.get_project
        self._get_subnets = self._handler._drv_subnets.get_subnets
        self._get_security_groups = self._handler._drv_sg.get_security_groups
        self._set_vifs_driver = self._handler._drv_vif_pool.set_vif_driver
        self._request_vif = self._handler._drv_vif_pool.request_vif
        self._release_vif = self._handler._drv_vif_pool.release_vif
        self._activate_vif = self._handler._drv_vif_pool.activate_vif
        self._set_pod_state = self._handler._set_pod_state
        self._is_pod_scheduled = self._handler._is_pod_scheduled
        self._request_additional_vifs = \
            self._multi_vif_drv.request_additional_vifs

        self._request_vif.return_value = self._vif
        self._request_additional_vifs.return_value = self._additioan_vifs
        self._is_pod_scheduled.return_value = True
        self._get_project.return_value = self._project_id
        self._get_subnets.return_value = self._subnets
        self._get_security_groups.return_value = self._security_groups
        self._set_vifs_driver.return_value = mock.Mock(
            spec=drivers.PodVIFDriver)

    @mock.patch.object(h_vif.VIFHandler, '_is_network_policy_enabled')
    @mock.patch.object(drivers.MultiVIFDriver, 'get_enabled_drivers')
    @mock.patch.object(drivers.VIFPoolDriver, 'set_vif_driver')
    @mock.patch.object(drivers.VIFPoolDriver, 'get_instance')
    @mock.patch.object(drivers.PodVIFDriver, 'get_instance')
    @mock.patch.object(drivers.PodSecurityGroupsDriver, 'get_instance')
    @mock.patch.object(drivers.PodSubnetsDriver, 'get_instance')
    @mock.patch.object(drivers.PodProjectDriver, 'get_instance')
    @mock.patch.object(drivers.LBaaSDriver, 'get_instance')
    @mock.patch.object(drivers.ServiceSecurityGroupsDriver, 'get_instance')
    def test_init(self, m_get_svc_sg_driver, m_get_lbaas_driver,
                  m_get_project_driver, m_get_subnets_driver, m_get_sg_driver,
                  m_get_vif_driver, m_get_vif_pool_driver, m_set_vifs_driver,
                  m_get_multi_vif_drivers, m_is_network_policy_enabled):
        project_driver = mock.sentinel.project_driver
        subnets_driver = mock.sentinel.subnets_driver
        sg_driver = mock.sentinel.sg_driver
        vif_driver = mock.sentinel.vif_driver
        vif_pool_driver = mock.Mock(spec=drivers.VIFPoolDriver)
        multi_vif_drivers = [mock.MagicMock(spec=drivers.MultiVIFDriver)]
        lbaas_driver = mock.sentinel.lbaas_driver
        svc_sg_driver = mock.Mock(spec=drivers.ServiceSecurityGroupsDriver)
        m_get_project_driver.return_value = project_driver
        m_get_subnets_driver.return_value = subnets_driver
        m_get_sg_driver.return_value = sg_driver
        m_get_vif_driver.return_value = vif_driver
        m_get_vif_pool_driver.return_value = vif_pool_driver
        m_get_multi_vif_drivers.return_value = multi_vif_drivers
        m_get_lbaas_driver.return_value = lbaas_driver
        m_get_svc_sg_driver.return_value = svc_sg_driver
        m_is_network_policy_enabled.return_value = True

        handler = h_vif.VIFHandler()

        self.assertEqual(project_driver, handler._drv_project)
        self.assertEqual(subnets_driver, handler._drv_subnets)
        self.assertEqual(sg_driver, handler._drv_sg)
        self.assertEqual(vif_pool_driver, handler._drv_vif_pool)
        self.assertEqual(multi_vif_drivers, handler._drv_multi_vif)
        self.assertEqual(lbaas_driver, handler._drv_lbaas)
        self.assertEqual(svc_sg_driver, handler._drv_svc_sg)

    def test_is_pod_scheduled(self):
        self.assertTrue(h_vif.VIFHandler._is_pod_scheduled(self._pod))

    def test_is_not_pending(self):
        self._pod['status']['phase'] = 'Unknown'
        self.assertFalse(h_vif.VIFHandler._is_pod_scheduled(self._pod))

    def test_is_pending_no_node(self):
        self._pod['spec']['nodeName'] = None
        self.assertFalse(h_vif.VIFHandler._is_pod_scheduled(self._pod))

    def test_unset_pending(self):
        self.assertFalse(h_vif.VIFHandler._is_pod_scheduled({'spec': {},
                                                             'status': {}}))

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'update_port_pci_info')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_present(self, m_get_pod_state, m_host_network, m_update_pci):
        m_get_pod_state.return_value = self._state
        m_host_network.return_value = False
        self._vif.plugin = 'sriov'
        h_vif.VIFHandler.on_present(self._handler, self._pod)

        m_get_pod_state.assert_called_once_with(self._pod)
        m_update_pci.assert_called_once_with(self._pod, self._vif)
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()
        self._set_pod_state.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_present_host_network(self, m_get_pod_state, m_host_network):
        m_get_pod_state.return_value = self._state
        m_host_network.return_value = True

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        m_get_pod_state.assert_not_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()
        self._set_pod_state.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_present_not_pending(self, m_get_pod_state, m_host_network):
        m_get_pod_state.return_value = self._state
        m_host_network.return_value = False
        self._is_pod_scheduled.return_value = False

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        m_get_pod_state.assert_not_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()
        self._set_pod_state.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'update_port_pci_info')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_present_activate(self, m_get_pod_state, m_host_network,
                                 m_get_services, m_update_pci):
        m_get_pod_state.return_value = self._state
        m_host_network.return_value = False
        m_get_services.return_value = {"items": []}
        self._vif.active = False
        self._vif.plugin = 'sriov'

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        m_get_pod_state.assert_called_once_with(self._pod)
        m_update_pci.assert_called_once_with(self._pod, self._vif)
        self._activate_vif.assert_called_once_with(self._pod, self._vif)
        self._set_pod_state.assert_called_once_with(self._pod, self._state)
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_present_create(self, m_get_pod_state, m_host_network):
        m_get_pod_state.return_value = None
        m_host_network.return_value = False

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        m_get_pod_state.assert_called_once_with(self._pod)
        self._request_vif.assert_called_once_with(
            self._pod, self._project_id, self._subnets, self._security_groups)
        self._request_additional_vifs.assert_called_once_with(
            self._pod, self._project_id, self._security_groups)
        self._set_pod_state.assert_called_once_with(self._pod, self._state)
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_present_create_with_additional_vifs(self, m_get_pod_state,
                                                    m_host_network):
        m_get_pod_state.return_value = None
        m_host_network.return_value = False
        additional_vif = os_obj.vif.VIFBase()
        self._state.additional_vifs = {'eth1': additional_vif}
        self._request_additional_vifs.return_value = [additional_vif]

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        m_get_pod_state.assert_called_once_with(self._pod)
        self._request_vif.assert_called_once_with(
            self._pod, self._project_id, self._subnets, self._security_groups)
        self._request_additional_vifs.assert_called_once_with(
            self._pod, self._project_id, self._security_groups)
        self._set_pod_state.assert_called_once_with(self._pod, self._state)
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_present_rollback(self, m_get_pod_state, m_host_network):
        m_get_pod_state.return_value = None
        m_host_network.return_value = False
        self._set_pod_state.side_effect = k_exc.K8sClientException

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        m_get_pod_state.assert_called_once_with(self._pod)
        self._request_vif.assert_called_once_with(
            self._pod, self._project_id, self._subnets, self._security_groups)
        self._request_additional_vifs.assert_called_once_with(
            self._pod, self._project_id, self._security_groups)
        self._set_pod_state.assert_called_once_with(self._pod, self._state)
        self._release_vif.assert_called_once_with(self._pod, self._vif,
                                                  self._project_id,
                                                  self._security_groups)
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_deleted(self, m_get_pod_state, m_host_network, m_get_services):
        m_get_pod_state.return_value = self._state
        m_host_network.return_value = False
        m_get_services.return_value = {"items": []}
        h_vif.VIFHandler.on_deleted(self._handler, self._pod)

        m_get_pod_state.assert_called_once_with(self._pod)
        self._release_vif.assert_called_once_with(self._pod, self._vif,
                                                  self._project_id,
                                                  self._security_groups)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_deleted_with_additional_vifs(self, m_get_pod_state,
                                             m_host_network, m_get_services):
        additional_vif = os_obj.vif.VIFBase()
        self._state.additional_vifs = {'eth1': additional_vif}
        m_get_pod_state.return_value = self._state
        m_host_network.return_value = False
        m_get_services.return_value = {"items": []}

        h_vif.VIFHandler.on_deleted(self._handler, self._pod)

        self._release_vif.assert_any_call(self._pod, self._vif,
                                          self._project_id,
                                          self._security_groups)
        self._release_vif.assert_any_call(self._pod, additional_vif,
                                          self._project_id,
                                          self._security_groups)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_deleted_host_network(self, m_get_pod_state, m_host_network):
        m_get_pod_state.return_value = self._state
        m_host_network.return_value = True

        h_vif.VIFHandler.on_deleted(self._handler, self._pod)

        m_get_pod_state.assert_not_called()
        self._release_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_pod_state')
    def test_on_deleted_no_annotation(self, m_get_pod_state, m_host_network,
                                      m_get_services):
        m_get_pod_state.return_value = None
        m_host_network.return_value = False
        m_get_services.return_value = {"items": []}

        h_vif.VIFHandler.on_deleted(self._handler, self._pod)

        m_get_pod_state.assert_called_once_with(self._pod)
        self._release_vif.assert_not_called()
