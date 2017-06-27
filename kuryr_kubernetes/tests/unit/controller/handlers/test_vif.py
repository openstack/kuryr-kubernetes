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

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.handlers import vif as h_vif
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.tests import base as test_base


class TestVIFHandler(test_base.TestCase):

    def setUp(self):
        super(TestVIFHandler, self).setUp()

        self._project_id = mock.sentinel.project_id
        self._subnets = mock.sentinel.subnets
        self._security_groups = mock.sentinel.security_groups
        self._vif = mock.Mock()
        self._vif.active = True
        self._vif_serialized = mock.sentinel.vif_serialized

        self._pod_version = mock.sentinel.pod_version
        self._pod_link = mock.sentinel.pod_link
        self._pod = {
            'metadata': {'resourceVersion': self._pod_version,
                         'selfLink': self._pod_link},
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

        self._get_project = self._handler._drv_project.get_project
        self._get_subnets = self._handler._drv_subnets.get_subnets
        self._get_security_groups = self._handler._drv_sg.get_security_groups
        self._set_vif_driver = self._handler._drv_vif_pool.set_vif_driver
        self._request_vif = self._handler._drv_vif_pool.request_vif
        self._release_vif = self._handler._drv_vif_pool.release_vif
        self._activate_vif = self._handler._drv_vif_pool.activate_vif
        self._get_vif = self._handler._get_vif
        self._set_vif = self._handler._set_vif
        self._is_host_network = self._handler._is_host_network
        self._is_pending_node = self._handler._is_pending_node

        self._request_vif.return_value = self._vif
        self._get_vif.return_value = self._vif
        self._is_host_network.return_value = False
        self._is_pending_node.return_value = True
        self._get_project.return_value = self._project_id
        self._get_subnets.return_value = self._subnets
        self._get_security_groups.return_value = self._security_groups
        self._set_vif_driver.return_value = mock.Mock(
            spec=drivers.PodVIFDriver)

    @mock.patch.object(drivers.VIFPoolDriver, 'set_vif_driver')
    @mock.patch.object(drivers.VIFPoolDriver, 'get_instance')
    @mock.patch.object(drivers.PodVIFDriver, 'get_instance')
    @mock.patch.object(drivers.PodSecurityGroupsDriver, 'get_instance')
    @mock.patch.object(drivers.PodSubnetsDriver, 'get_instance')
    @mock.patch.object(drivers.PodProjectDriver, 'get_instance')
    def test_init(self, m_get_project_driver, m_get_subnets_driver,
                  m_get_sg_driver, m_get_vif_driver, m_get_vif_pool_driver,
                  m_set_vif_driver):
        project_driver = mock.sentinel.project_driver
        subnets_driver = mock.sentinel.subnets_driver
        sg_driver = mock.sentinel.sg_driver
        vif_driver = mock.sentinel.vif_driver
        vif_pool_driver = mock.Mock(spec=drivers.VIFPoolDriver)
        m_get_project_driver.return_value = project_driver
        m_get_subnets_driver.return_value = subnets_driver
        m_get_sg_driver.return_value = sg_driver
        m_get_vif_driver.return_value = vif_driver
        m_get_vif_pool_driver.return_value = vif_pool_driver

        handler = h_vif.VIFHandler()

        self.assertEqual(project_driver, handler._drv_project)
        self.assertEqual(subnets_driver, handler._drv_subnets)
        self.assertEqual(sg_driver, handler._drv_sg)
        self.assertEqual(vif_pool_driver, handler._drv_vif_pool)

    def test_is_host_network(self):
        self._pod['spec']['hostNetwork'] = True
        self.assertTrue(h_vif.VIFHandler._is_host_network(self._pod))

    def test_is_not_host_network(self):
        self.assertFalse(h_vif.VIFHandler._is_host_network(self._pod))

    def test_unset_host_network(self):
        pod = self._pod.copy()
        del pod['spec']['hostNetwork']
        self.assertFalse(h_vif.VIFHandler._is_host_network(pod))

    def test_is_pending_node(self):
        self.assertTrue(h_vif.VIFHandler._is_pending_node(self._pod))

    def test_is_not_pending(self):
        self._pod['status']['phase'] = 'Unknown'
        self.assertFalse(h_vif.VIFHandler._is_pending_node(self._pod))

    def test_is_pending_no_node(self):
        self._pod['spec']['nodeName'] = None
        self.assertFalse(h_vif.VIFHandler._is_pending_node(self._pod))

    def test_unset_pending(self):
        self.assertFalse(h_vif.VIFHandler._is_pending_node({'spec': {},
                                                            'status': {}}))

    def test_on_present(self):
        h_vif.VIFHandler.on_present(self._handler, self._pod)

        self._get_vif.assert_called_once_with(self._pod)
        self._request_vif.assert_not_called()
        self._activate_vif.assert_not_called()
        self._set_vif.assert_not_called()

    def test_on_present_host_network(self):
        self._is_host_network.return_value = True

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        self._get_vif.assert_not_called()
        self._request_vif.assert_not_called()
        self._activate_vif.assert_not_called()
        self._set_vif.assert_not_called()

    def test_on_present_not_pending(self):
        self._is_pending_node.return_value = False

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        self._get_vif.assert_not_called()
        self._request_vif.assert_not_called()
        self._activate_vif.assert_not_called()
        self._set_vif.assert_not_called()

    def test_on_present_activate(self):
        self._vif.active = False

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        self._get_vif.assert_called_once_with(self._pod)
        self._activate_vif.assert_called_once_with(self._pod, self._vif)
        self._set_vif.assert_called_once_with(self._pod, self._vif)
        self._request_vif.assert_not_called()

    def test_on_present_create(self):
        self._get_vif.return_value = None

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        self._get_vif.assert_called_once_with(self._pod)
        self._request_vif.assert_called_once_with(
            self._pod, self._project_id, self._subnets, self._security_groups)
        self._set_vif.assert_called_once_with(self._pod, self._vif)
        self._activate_vif.assert_not_called()

    def test_on_present_rollback(self):
        self._get_vif.return_value = None
        self._set_vif.side_effect = k_exc.K8sClientException

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        self._get_vif.assert_called_once_with(self._pod)
        self._request_vif.assert_called_once_with(
            self._pod, self._project_id, self._subnets, self._security_groups)
        self._set_vif.assert_called_once_with(self._pod, self._vif)
        self._release_vif.assert_called_once_with(self._pod, self._vif,
                                                  self._project_id,
                                                  self._security_groups)
        self._activate_vif.assert_not_called()

    def test_on_deleted(self):
        h_vif.VIFHandler.on_deleted(self._handler, self._pod)

        self._get_vif.assert_called_once_with(self._pod)
        self._release_vif.assert_called_once_with(self._pod, self._vif,
                                                  self._project_id,
                                                  self._security_groups)

    def test_on_deleted_host_network(self):
        self._is_host_network.return_value = True

        h_vif.VIFHandler.on_deleted(self._handler, self._pod)

        self._get_vif.assert_not_called()
        self._release_vif.assert_not_called()

    def test_on_deleted_no_annotation(self):
        self._get_vif.return_value = None

        h_vif.VIFHandler.on_deleted(self._handler, self._pod)

        self._get_vif.assert_called_once_with(self._pod)
        self._release_vif.assert_not_called()
