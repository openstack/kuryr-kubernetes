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
from oslo_serialization import jsonutils

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
        self._pod_uid = mock.sentinel.pod_uid
        self._pod_name = 'pod1'
        self._pod = {
            'metadata': {'resourceVersion': self._pod_version,
                         'selfLink': self._pod_link,
                         'name': self._pod_name,
                         'namespace': self._pod_namespace},
            'status': {'phase': k_const.K8S_POD_STATUS_PENDING},
            'spec': {'hostNetwork': False,
                     'nodeName': 'hostname'}
        }

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

        self._get_project = self._handler._drv_project.get_project
        self._get_subnets = self._handler._drv_subnets.get_subnets
        self._get_security_groups = self._handler._drv_sg.get_security_groups
        self._set_vifs_driver = self._handler._drv_vif_pool.set_vif_driver
        self._request_vif = self._handler._drv_vif_pool.request_vif
        self._release_vif = self._handler._drv_vif_pool.release_vif
        self._activate_vif = self._handler._drv_vif_pool.activate_vif
        self._matc = self._handler._move_annotations_to_crd
        self._is_pod_scheduled = self._handler._is_pod_scheduled
        self._is_pod_completed = self._handler._is_pod_completed
        self._request_additional_vifs = \
            self._multi_vif_drv.request_additional_vifs

        self._request_vif.return_value = self._vif
        self._request_additional_vifs.return_value = self._additioan_vifs
        self._is_pod_scheduled.return_value = True
        self._is_pod_completed.return_value = False
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

    def test_is_pod_completed_pending(self):
        self.assertFalse(h_vif.VIFHandler._is_pod_completed(self._pod))

    def test_is_pod_completed_succeeded(self):
        self.assertTrue(h_vif.VIFHandler._is_pod_completed({'status': {'phase':
                        k_const.K8S_POD_STATUS_SUCCEEDED}}))

    def test_is_pod_completed_failed(self):
        self.assertTrue(h_vif.VIFHandler._is_pod_completed({'status': {'phase':
                        k_const.K8S_POD_STATUS_FAILED}}))

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_host_network(self, m_get_kuryrport, m_host_network,
                                     m_get_k8s_client):
        m_get_kuryrport.return_value = self._kp
        m_host_network.return_value = True
        self._matc.return_value = False
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        k8s.add_finalizer.assert_not_called()
        self._matc.assert_not_called()
        m_get_kuryrport.assert_not_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_not_scheduled(self, m_get_kuryrport, m_host_network,
                                      m_get_k8s_client):
        m_get_kuryrport.return_value = self._kp
        m_host_network.return_value = False
        self._is_pod_scheduled.return_value = False
        self._matc.return_value = False
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        k8s.add_finalizer.assert_not_called()
        self._matc.assert_not_called()
        m_get_kuryrport.assert_not_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_on_completed_with_annotation(self, m_get_kuryrport,
                                                     m_get_k8s_client):
        self._is_pod_completed.return_value = True
        m_get_kuryrport.return_value = self._kp
        self._matc.return_value = False
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        k8s.add_finalizer.assert_called_once_with(self._pod,
                                                  k_const.POD_FINALIZER)
        self._matc.assert_called_once_with(self._pod)
        self._handler.on_finalize.assert_called_once_with(self._pod)
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_on_completed_without_annotation(self, m_get_kuryrport,
                                                        m_get_k8s_client):
        self._is_pod_completed.return_value = True
        m_get_kuryrport.return_value = None
        self._matc.return_value = False
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        k8s.add_finalizer.assert_called_once_with(self._pod,
                                                  k_const.POD_FINALIZER)
        self._matc.assert_called_once_with(self._pod)
        self._handler.on_finalize.assert_not_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_create(self, m_get_kuryrport, m_host_network,
                               m_get_k8s_client):
        m_get_kuryrport.return_value = None
        m_host_network.return_value = False
        self._matc.return_value = False
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        k8s.add_finalizer.assert_called_once_with(self._pod,
                                                  k_const.POD_FINALIZER)
        m_get_kuryrport.assert_called_once_with(self._pod)
        self._matc.assert_called_once_with(self._pod)
        self._handler._add_kuryrport_crd.assert_called_once_with(self._pod)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_update(self, m_get_kuryrport, m_host_network,
                               m_get_k8s_client):
        m_get_kuryrport.return_value = self._kp
        m_host_network.return_value = False
        self._matc.return_value = False
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        k8s.add_finalizer.assert_called_once_with(self._pod,
                                                  k_const.POD_FINALIZER)
        self._matc.assert_called_once_with(self._pod)
        m_get_kuryrport.assert_called_once_with(self._pod)
        self._handler._add_kuryrport_crd.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_present_upgrade(self, m_get_kuryrport, m_host_network,
                                m_get_k8s_client):
        m_get_kuryrport.return_value = self._kp
        m_host_network.return_value = False
        self._matc.return_value = True
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_present(self._handler, self._pod)

        k8s.add_finalizer.assert_called_once_with(self._pod,
                                                  k_const.POD_FINALIZER)
        self._matc.assert_called_once_with(self._pod)
        m_get_kuryrport.assert_not_called()
        self._request_vif.assert_not_called()
        self._request_additional_vifs.assert_not_called()
        self._activate_vif.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.is_host_network')
    def test_on_present_pod_finalizer_exception(self, m_host_network,
                                                m_get_k8s_client):
        m_host_network.return_value = False
        self._matc.return_value = True
        k8s = mock.MagicMock()
        k8s.add_finalizer.side_effect = k_exc.K8sClientException
        m_get_k8s_client.return_value = k8s

        self.assertRaises(k_exc.K8sClientException,
                          h_vif.VIFHandler.on_present, self._handler,
                          self._pod)

        k8s.add_finalizer.assert_called_once_with(self._pod,
                                                  k_const.POD_FINALIZER)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_finalize_crd(self, m_get_kuryrport, m_get_k8s_client):
        m_get_kuryrport.return_value = self._kp
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        h_vif.VIFHandler.on_finalize(self._handler, self._pod)

        k8s.delete.assert_called_once_with(
            h_vif.KURYRPORT_URI.format(
                ns=self._pod["metadata"]["namespace"],
                crd=self._pod["metadata"]["name"]))

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_finalize_crd_exception(self, m_get_kuryrport,
                                       m_get_k8s_client):
        m_get_kuryrport.return_value = self._kp
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s
        k8s.delete.side_effect = k_exc.K8sClientException

        self.assertRaises(k_exc.ResourceNotReady, h_vif.VIFHandler
                          .on_finalize, self._handler, self._pod)

        k8s.delete.assert_called_once_with(
            h_vif.KURYRPORT_URI.format(
                ns=self._pod["metadata"]["namespace"],
                crd=self._pod["metadata"]["name"]))

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_kuryrport')
    def test_on_finalize_crd_not_found(self, m_get_kuryrport,
                                       m_get_k8s_client):
        m_get_kuryrport.return_value = self._kp
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s
        k8s.delete.side_effect = k_exc.K8sResourceNotFound(self._pod)

        h_vif.VIFHandler.on_finalize(self._handler, self._pod)

        k8s.delete.assert_called_once_with(
            h_vif.KURYRPORT_URI.format(
                ns=self._pod["metadata"]["namespace"],
                crd=self._pod["metadata"]["name"]))
        (k8s.remove_finalizer
         .assert_called_once_with(self._pod, k_const.POD_FINALIZER))

    def test_move_annotations_to_crd_no_annotations(self):
        res = h_vif.VIFHandler._move_annotations_to_crd(self._handler,
                                                        self._pod)
        self.assertFalse(res)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_move_annotations_to_crd_with_annotations(self, m_get_k8s_client):
        vifobj = os_obj.vif.VIFOpenVSwitch()
        state = vif.PodState(default_vif=vifobj)
        annotation = jsonutils.dumps(state.obj_to_primitive())
        self._pod['metadata']['annotations'] = {
            k_const.K8S_ANNOTATION_VIF: annotation}
        vifs = {'eth0': {'default': True, 'vif': vifobj.obj_to_primitive()}}
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s

        res = h_vif.VIFHandler._move_annotations_to_crd(self._handler,
                                                        self._pod)
        self.assertTrue(res)
        self._handler._add_kuryrport_crd.assert_called_once_with(self._pod,
                                                                 vifs)

        m_get_k8s_client.assert_called_once()
        k8s.remove_annotations.assert_called_once_with(
            self._pod['metadata']['selfLink'], k_const.K8S_ANNOTATION_VIF)
