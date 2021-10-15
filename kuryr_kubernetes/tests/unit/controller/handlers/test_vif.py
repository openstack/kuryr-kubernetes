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

from unittest import mock

from os_vif import objects as os_obj

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.handlers import vif as h_vif
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import vif
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests import fake


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
        self._pod_namespace = 'namespace1'
        self._pod_uid = mock.sentinel.pod_uid
        self._pod_name = 'pod1'
        self._pod = fake.get_k8s_pod()
        self._pod['status'] = {'phase': k_const.K8S_POD_STATUS_PENDING}
        self._pod['spec'] = {'hostNetwork': False, 'nodeName': 'hostname'}

        self._kp_version = mock.sentinel.kp_version
        self._kp_link = mock.sentinel.kp_link
        self._kp = {'apiVersion': 'openstack.org/v1',
                    'kind': 'KuryrPort',
                    'metadata': {'resourceVersion': self._kp_version,
                                 'selfLink': mock.sentinel.kp_link,
                                 'namespace': self._pod_namespace,
                                 'labels': mock.ANY},
                    'spec': {'podUid': self._pod_uid,
                             'podNodeName': 'hostname'},
                    'status': {'vifs': {}}}

        self._handler = mock.MagicMock(spec=h_vif.VIFHandler)
        self._handler._drv_project = mock.Mock(spec=drivers.PodProjectDriver)
        self._handler._drv_subnets = mock.Mock(spec=drivers.PodSubnetsDriver)
        self._handler._drv_sg = mock.Mock(spec=drivers.PodSecurityGroupsDriver)
        self._handler._drv_vif = mock.Mock(spec=drivers.PodVIFDriver)
        self._handler._drv_vif_pool = mock.MagicMock(
            spec=drivers.VIFPoolDriver)
        self._handler._drv_multi_vif = [self._multi_vif_drv]
        self._handler.k8s = mock.Mock()

        self._get_project = self._handler._drv_project.get_project
        self._get_subnets = self._handler._drv_subnets.get_subnets
        self._get_security_groups = self._handler._drv_sg.get_security_groups
        self._set_vifs_driver = self._handler._drv_vif_pool.set_vif_driver
        self._request_vif = self._handler._drv_vif_pool.request_vif
        self._release_vif = self._handler._drv_vif_pool.release_vif
        self._activate_vif = self._handler._drv_vif_pool.activate_vif
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

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_host_network(self, m_get_kuryrport, m_host_network,
                                     m_get_k8s_client):
        m_get_kuryrport.return_value = self._kp
        m_host_network.return_value = True
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        k8s.add_finalizer.assert_not_called()
        m_get_kuryrport.assert_not_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_k8s_resource')
    @mock.patch('kuryr_kubernetes.utils.is_pod_completed')
    @mock.patch('kuryr_kubernetes.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_not_scheduled(self, m_get_kuryrport, m_host_network,
                                      m_is_pod_completed, m_get_k8s_res):
        m_get_kuryrport.return_value = self._kp
        m_host_network.return_value = False
        m_is_pod_completed.return_value = False
        m_get_k8s_res.return_value = {}

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        self._handler.k8s.add_finalizer.assert_called()
        m_get_kuryrport.assert_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.utils.is_pod_completed')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_on_completed_without_kuryrport(self, m_get_kuryrport,
                                                       m_get_k8s_client,
                                                       m_is_pod_completed):
        m_is_pod_completed.return_value = True
        m_get_kuryrport.return_value = None
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        self._handler.on_finalize.assert_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.utils.is_pod_completed')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_on_completed_with_kuryrport(self, m_get_kuryrport,
                                                    m_get_k8s_client,
                                                    m_is_pod_completed):
        m_is_pod_completed.return_value = True
        m_get_kuryrport.return_value = mock.MagicMock()
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        self._handler.on_finalize.assert_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_k8s_resource')
    @mock.patch('kuryr_kubernetes.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_create(self, m_get_kuryrport, m_host_network,
                               m_get_k8s_res):
        m_get_kuryrport.return_value = None
        m_host_network.return_value = False
        m_get_k8s_res.return_value = {}

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        add_finalizer = self._handler.k8s.add_finalizer
        add_finalizer.assert_called_once_with(self._pod, k_const.POD_FINALIZER)
        m_get_kuryrport.assert_called_once_with(self._pod)
        self._handler._add_kuryrport_crd.assert_called_once_with(self._pod)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_k8s_resource')
    @mock.patch('kuryr_kubernetes.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_update(self, m_get_kuryrport, m_host_network,
                               m_get_k8s_res):
        m_get_kuryrport.return_value = self._kp
        m_host_network.return_value = False
        m_get_k8s_res.return_value = {}

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        add_finalizer = self._handler.k8s.add_finalizer
        add_finalizer.assert_called_once_with(self._pod, k_const.POD_FINALIZER)
        m_get_kuryrport.assert_called_once_with(self._pod)
        self._handler._add_kuryrport_crd.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_k8s_resource')
    @mock.patch('kuryr_kubernetes.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_upgrade(self, m_get_kuryrport, m_host_network,
                                m_get_k8s_res):
        m_get_kuryrport.return_value = self._kp
        m_host_network.return_value = False
        m_get_k8s_res.return_value = {}

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        add_finalizer = self._handler.k8s.add_finalizer
        add_finalizer.assert_called_once_with(self._pod, k_const.POD_FINALIZER)
        m_get_kuryrport.assert_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_k8s_resource')
    @mock.patch('kuryr_kubernetes.utils.is_host_network')
    def test_on_present_pod_finalizer_exception(self, m_host_network,
                                                m_get_k8s_res):
        m_host_network.return_value = False
        m_get_k8s_res.return_value = {}
        self._handler.k8s.add_finalizer.side_effect = k_exc.K8sClientException

        self.assertRaises(k_exc.K8sClientException,
                          h_vif.VIFHandler.on_present, self._handler,
                          self._pod)

        add_finalizer = self._handler.k8s.add_finalizer
        add_finalizer.assert_called_once_with(self._pod, k_const.POD_FINALIZER)

    def test_on_finalize_crd(self):
        self._handler.k8s.get.return_value = self._kp

        h_vif.VIFHandler.on_finalize(self._handler, self._pod)

        self._handler.k8s.delete.assert_called_once_with(
            h_vif.KURYRPORT_URI.format(
                ns=self._pod["metadata"]["namespace"],
                crd=self._pod["metadata"]["name"]))

    def test_on_finalize_crd_exception(self):
        self._handler.k8s.get.return_value = self._kp
        self._handler.k8s.delete.side_effect = k_exc.K8sClientException

        self.assertRaises(k_exc.ResourceNotReady, h_vif.VIFHandler
                          .on_finalize, self._handler, self._pod)

        self._handler.k8s.delete.assert_called_once_with(
            h_vif.KURYRPORT_URI.format(
                ns=self._pod["metadata"]["namespace"],
                crd=self._pod["metadata"]["name"]))

    def test_on_finalize_crd_not_found(self):
        self._handler.k8s.get.return_value = self._kp
        (self._handler.k8s.delete
         .side_effect) = k_exc.K8sResourceNotFound(self._pod)

        h_vif.VIFHandler.on_finalize(self._handler, self._pod)

        self._handler.k8s.delete.assert_called_once_with(
            h_vif.KURYRPORT_URI.format(
                ns=self._pod["metadata"]["namespace"],
                crd=self._pod["metadata"]["name"]))
        (self._handler.k8s.remove_finalizer
         .assert_called_once_with(self._pod, k_const.POD_FINALIZER))
