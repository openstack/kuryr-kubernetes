# Copyright (c) 2020 Red Hat, Inc.
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

from openstack import exceptions as os_exc
from os_vif import objects as os_obj
from oslo_config import cfg

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import multi_vif
from kuryr_kubernetes.controller.handlers import kuryrport
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix
from kuryr_kubernetes import utils


CONF = cfg.CONF


class TestKuryrPortHandler(test_base.TestCase):

    def setUp(self):
        super().setUp()
        self._project_id = mock.sentinel.project_id
        self._subnets = mock.sentinel.subnets
        self._security_groups = mock.sentinel.security_groups
        self._host = mock.sentinel.hostname
        self._pod_version = mock.sentinel.pod_version
        self._pod_link = mock.sentinel.pod_link
        self._kp_version = mock.sentinel.kp_version
        self._kp_namespace = mock.sentinel.namespace
        self._kp_uid = mock.sentinel.kp_uid
        self._kp_name = 'pod1'
        self._pod_uid = 'deadbeef'

        self._pod = {'apiVersion': 'v1',
                     'kind': 'Pod',
                     'metadata': {
                         'resourceVersion': self._pod_version,
                         'name': self._kp_name,
                         'deletionTimestamp': mock.sentinel.date,
                         'namespace': self._kp_namespace,
                         'uid': self._pod_uid,
                     },
                     'spec': {'nodeName': self._host}}

        self._kp = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrPort',
            'metadata': {
                'resourceVersion': self._kp_version,
                'name': self._kp_name,
                'namespace': self._kp_namespace,
                'labels': {
                    constants.KURYRPORT_LABEL: self._host
                },
                'finalizers': [],
            },
            'spec': {
                'podUid': self._pod_uid,
                'podNodeName': self._host
            },
            'status': {'vifs': {}}
        }

        self._vif1 = os_obj.vif.VIFBase()
        self._vif2 = os_obj.vif.VIFBase()
        self._vif1.active = False
        self._vif2.active = False
        self._vif1.plugin = 'object'
        self._vif2.plugin = 'object'
        self._vif1_primitive = self._vif1.obj_to_primitive()
        self._vif2_primitive = self._vif2.obj_to_primitive()
        self._vifs_primitive = {'eth0': {'default': True,
                                         'vif': self._vif1_primitive},
                                'eth1': {'default': False,
                                         'vif': self._vif2_primitive}}
        self._vifs = {'eth0': {'default': True,
                               'vif': self._vif1},
                      'eth1': {'default': False,
                               'vif': self._vif2}}
        self._pod_uri = (f"{constants.K8S_API_NAMESPACES}"
                         f"/{self._kp['metadata']['namespace']}/pods/"
                         f"{self._kp['metadata']['name']}")
        self._kp_uri = utils.get_res_link(self._kp)
        self.useFixture(k_fix.MockNetworkClient())
        self._driver = multi_vif.NoopMultiVIFDriver()

    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler.get_vifs')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_present_no_vifs_create(self, ged, get_k8s_client, get_vifs):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        get_vifs.return_value = True

        kp.on_present(self._kp)

        get_vifs.assert_called_once_with(self._kp)

    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler.get_vifs')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_present_getting_vifs_failed(self, ged, get_k8s_client,
                                            get_vifs):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        get_vifs.return_value = False

        self.assertFalse(kp.on_present(self._kp))

        get_vifs.assert_called_once_with(self._kp)

    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_kuryrport_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'activate_vif')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_present(self, ged, get_k8s_client, activate_vif,
                        update_crd, get_project):
        ged.return_value = [mock.MagicMock]
        kp = kuryrport.KuryrPortHandler()
        self._kp['status']['vifs'] = self._vifs_primitive
        get_project.return_value = self._project_id

        with mock.patch.object(kp, 'k8s') as k8s:
            k8s.get.return_value = self._pod

            kp.on_present(self._kp)

            k8s.get.assert_called_once_with(self._pod_uri)

        activate_vif.assert_has_calls([mock.call(self._vif1, pod=self._pod,
                                                 retry_info=mock.ANY),
                                       mock.call(self._vif2, pod=self._pod,
                                                 retry_info=mock.ANY)])
        update_crd.assert_called_once_with(self._kp, self._vifs)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_present_active(self, ged, get_k8s_client):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        self._vif1.active = True
        self._vif2.active = True
        self._kp['status']['vifs'] = {
            'eth0': {'default': True,
                     'vif': self._vif1.obj_to_primitive()},
            'eth1': {'default': False,
                     'vif': self._vif2.obj_to_primitive()}}

        kp.on_present(self._kp)

    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_kuryrport_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'activate_vif')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_present_port_not_found(self, ged, get_k8s_client, activate_vif,
                                       update_crd):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        self._kp['status']['vifs'] = self._vifs_primitive
        activate_vif.side_effect = os_exc.ResourceNotFound()

        kp.on_present(self._kp)

        activate_vif.assert_has_calls([mock.call(self._vif1, pod=mock.ANY,
                                                 retry_info=mock.ANY),
                                       mock.call(self._vif2, pod=mock.ANY,
                                                 retry_info=mock.ANY)])

    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'activate_vif')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_present_pod_not_found(self, ged, get_k8s_client, activate_vif):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        self._kp['status']['vifs'] = self._vifs_primitive

        with mock.patch.object(kp, 'k8s') as k8s:
            k8s.get.side_effect = k_exc.K8sResourceNotFound(self._pod)

            self.assertRaises(k_exc.K8sResourceNotFound, kp.on_present,
                              self._kp)

            k8s.get.assert_called_once_with(self._pod_uri)

    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'release_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.get_security_groups')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_kuryrport_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'activate_vif')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_present_fail_update_crd(self, ged, get_k8s_client,
                                        activate_vif, update_crd, get_project,
                                        get_sg, release_vif):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        self._kp['status']['vifs'] = self._vifs_primitive
        update_crd.side_effect = k_exc.K8sResourceNotFound(self._kp)
        get_project.return_value = self._project_id
        get_sg.return_value = self._security_groups

        with mock.patch.object(kp, 'k8s') as k8s:
            k8s.get.return_value = self._pod

            kp.on_present(self._kp)

            k8s.get.assert_called_once_with(self._pod_uri)

    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'release_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.get_security_groups')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_kuryrport_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'activate_vif')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_present_exception_during_update_crd(self, ged, get_k8s_client,
                                                    activate_vif,
                                                    update_crd, get_project,
                                                    get_sg, release_vif):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        self._kp['status']['vifs'] = self._vifs_primitive
        update_crd.side_effect = k_exc.K8sClientException()
        get_project.return_value = self._project_id
        get_sg.return_value = self._security_groups

        with mock.patch.object(kp, 'k8s') as k8s:
            k8s.get.return_value = self._pod

            self.assertRaises(k_exc.ResourceNotReady, kp.on_present, self._kp)

            k8s.get.assert_called_once_with(self._pod_uri)

        update_crd.assert_called_once_with(self._kp, self._vifs)

    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.create_sg_rules')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceSecurityGroupsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.LBaaSDriver.'
                'get_instance')
    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_kuryrport_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'activate_vif')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'is_network_policy_enabled')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_present_np(self, ged, is_np_enabled, get_k8s_client,
                           activate_vif, update_crd, get_lb_instance,
                           get_sg_instance, create_sgr, update_services,
                           get_services, get_project):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        self._kp['status']['vifs'] = self._vifs_primitive

        with mock.patch.object(kp, 'k8s') as k8s:
            k8s.get.return_value = self._pod

            kp.on_present(self._kp)

            k8s.get.assert_called_once_with(self._pod_uri)

        activate_vif.assert_has_calls([mock.call(self._vif1, pod=self._pod,
                                                 retry_info=mock.ANY),
                                       mock.call(self._vif2, pod=self._pod,
                                                 retry_info=mock.ANY)])
        update_crd.assert_called_once_with(self._kp, self._vifs)
        create_sgr.assert_called_once_with(self._pod)

    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.utils.get_parent_port_id')
    @mock.patch('kuryr_kubernetes.utils.get_parent_port_ip')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_finalize_exception_on_pod(self, ged, k8s, gppip, gppid,
                                          project_driver):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        self._kp['metadata']['deletionTimestamp'] = 'foobar'
        self._kp['status']['vifs'] = self._vifs_primitive

        with mock.patch.object(kp, 'k8s') as k8s:
            k8s.get.side_effect = k_exc.K8sResourceNotFound(self._pod)

            self.assertIsNone(kp.on_finalize(self._kp))

            k8s.get.assert_called_once_with(self._pod_uri)
            k8s.remove_finalizer.assert_has_calls(
                (mock.call(mock.ANY, constants.POD_FINALIZER),
                 mock.call(self._kp, constants.KURYRPORT_FINALIZER)))

    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceSecurityGroupsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.LBaaSDriver.'
                'get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'is_network_policy_enabled')
    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'release_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.delete_sg_rules')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_finalize_np(self, ged, k8s, get_project, delete_sg_rules,
                            release_vif, is_np_enabled, get_lb_instance,
                            get_sg_instance, get_services, update_services):
        ged.return_value = [self._driver]
        CONF.set_override('enforce_sg_rules', True, group='octavia_defaults')
        self.addCleanup(CONF.clear_override, 'enforce_sg_rules',
                        group='octavia_defaults')
        kp = kuryrport.KuryrPortHandler()
        self._kp['status']['vifs'] = self._vifs_primitive
        get_project.return_value = self._project_id
        selector = mock.sentinel.selector
        delete_sg_rules.return_value = selector
        get_services.return_value = mock.sentinel.services

        with mock.patch.object(kp, 'k8s') as k8s:
            k8s.get.return_value = self._pod

            kp.on_finalize(self._kp)

            k8s.get.assert_called_once_with(self._pod_uri)
            k8s.remove_finalizer.assert_has_calls(
                [mock.call(self._pod, constants.POD_FINALIZER),
                 mock.call(self._kp, constants.KURYRPORT_FINALIZER)])

        delete_sg_rules.assert_called_once_with(self._pod)
        release_vif.assert_has_calls([mock.call(self._pod, self._vif1,
                                                self._project_id),
                                      mock.call(self._pod, self._vif2,
                                                self._project_id)])

        get_services.assert_called_once()
        update_services.assert_called_once_with(mock.sentinel.services,
                                                selector, self._project_id)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_on_finalize_pod_running(self, ged, k8s):
        ged.return_value = [self._driver]
        # copy, so it will not be affected by other tests run in parallel.
        pod = dict(self._pod)
        del(pod['metadata']['deletionTimestamp'])

        kp = kuryrport.KuryrPortHandler()

        with mock.patch.object(kp, 'k8s') as k8s:
            k8s.get.return_value = pod
            self.assertIsNone(kp.on_finalize(self._kp))
            k8s.get.assert_called_once_with(self._pod_uri)

    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_kuryrport_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'request_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                'DefaultPodSubnetDriver.get_subnets')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.get_security_groups')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_get_vifs(self, ged, k8s, get_project, get_sg, get_subnets,
                      request_vif, update_crd):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        kp.k8s.get.return_value = self._pod
        get_sg.return_value = self._security_groups
        get_project.return_value = self._project_id
        get_subnets.return_value = mock.sentinel.subnets
        request_vif.return_value = self._vif1

        self.assertTrue(kp.get_vifs(self._kp))

        kp.k8s.get.assert_called_once_with(self._pod_uri)
        get_project.assert_called_once_with(self._pod)
        get_sg.assert_called_once_with(self._pod, self._project_id)
        get_subnets.assert_called_once_with(self._pod, self._project_id)
        request_vif.assert_called_once_with(self._pod, self._project_id,
                                            mock.sentinel.subnets,
                                            self._security_groups)
        update_crd.assert_called_once_with(self._kp,
                                           {constants.DEFAULT_IFNAME:
                                            {'default': True,
                                             'vif': self._vif1}})

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_get_vifs_pod_not_found(self, ged, k8s):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        kp.k8s.get.side_effect = k_exc.K8sResourceNotFound(self._pod)

        self.assertFalse(kp.get_vifs(self._kp))

        kp.k8s.get.assert_called_once_with(self._pod_uri)
        kp.k8s.delete.assert_called_once_with(self._kp_uri)

    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                'DefaultPodSubnetDriver.get_subnets')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.get_security_groups')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_get_vifs_subnet_error(self, ged, k8s, get_project, get_sg,
                                   get_subnets):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        kp.k8s.get.return_value = self._pod
        get_sg.return_value = self._security_groups
        get_project.return_value = self._project_id
        get_subnets.side_effect = os_exc.ResourceNotFound()

        self.assertFalse(kp.get_vifs(self._kp))

        kp.k8s.get.assert_called_once_with(self._pod_uri)
        get_project.assert_called_once_with(self._pod)
        get_sg.assert_called_once_with(self._pod, self._project_id)
        get_subnets.assert_called_once_with(self._pod, self._project_id)

    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'request_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                'DefaultPodSubnetDriver.get_subnets')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.get_security_groups')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_get_vifs_no_vif(self, ged, k8s, get_project, get_sg, get_subnets,
                             request_vif):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        kp.k8s.get.return_value = self._pod
        get_sg.return_value = self._security_groups
        get_project.return_value = self._project_id
        get_subnets.return_value = mock.sentinel.subnets
        request_vif.return_value = None

        self.assertFalse(kp.get_vifs(self._kp))

        kp.k8s.get.assert_called_once_with(self._pod_uri)
        get_project.assert_called_once_with(self._pod)
        get_sg.assert_called_once_with(self._pod, self._project_id)
        get_subnets.assert_called_once_with(self._pod, self._project_id)
        request_vif.assert_called_once_with(self._pod, self._project_id,
                                            mock.sentinel.subnets,
                                            self._security_groups)

    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'request_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                'DefaultPodSubnetDriver.get_subnets')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.get_security_groups')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_get_vifs_resource_not_found(self, ged, k8s, get_project, get_sg,
                                         get_subnets, request_vif):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        kp.k8s.get.return_value = self._pod
        get_sg.return_value = self._security_groups
        get_project.return_value = self._project_id
        get_subnets.return_value = mock.sentinel.subnets
        request_vif.side_effect = os_exc.ResourceNotFound()

        self.assertRaises(k_exc.ResourceNotReady, kp.get_vifs, self._kp)

        kp.k8s.get.assert_called_once_with(self._pod_uri)
        get_project.assert_called_once_with(self._pod)
        get_sg.assert_called_once_with(self._pod, self._project_id)
        get_subnets.assert_called_once_with(self._pod, self._project_id)
        request_vif.assert_called_once_with(self._pod, self._project_id,
                                            mock.sentinel.subnets,
                                            self._security_groups)

    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_kuryrport_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'request_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                'DefaultPodSubnetDriver.get_subnets')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.get_security_groups')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_get_vifs_with_additional_vif(self, ged, k8s, get_project, get_sg,
                                          get_subnets, request_vif,
                                          update_crd):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        kp.k8s.get.return_value = self._pod
        fake_driver = mock.MagicMock()
        fake_driver.request_additional_vifs.return_value = [self._vif2]
        kp._drv_multi_vif.append(fake_driver)
        get_sg.return_value = self._security_groups
        get_project.return_value = self._project_id
        get_subnets.return_value = mock.sentinel.subnets
        request_vif.return_value = self._vif1

        self.assertTrue(kp.get_vifs(self._kp))

        kp.k8s.get.assert_called_once_with(self._pod_uri)
        get_project.assert_called_once_with(self._pod)
        get_sg.assert_called_once_with(self._pod, self._project_id)
        get_subnets.assert_called_once_with(self._pod, self._project_id)
        request_vif.assert_called_once_with(self._pod, self._project_id,
                                            mock.sentinel.subnets,
                                            self._security_groups)
        update_crd.assert_called_once_with(self._kp,
                                           {'eth0': {'default': True,
                                                     'vif': self._vif1},
                                            'eth1': {'default': False,
                                                     'vif': self._vif2}})

    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'release_vif')
    @mock.patch('kuryr_kubernetes.controller.handlers.kuryrport.'
                'KuryrPortHandler._update_kuryrport_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.vif_pool.MultiVIFPool.'
                'request_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                'DefaultPodSubnetDriver.get_subnets')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_security_groups.'
                'DefaultPodSecurityGroupsDriver.get_security_groups')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_project.'
                'DefaultPodProjectDriver.get_project')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_get_exception_on_update_crd(self, ged, k8s, get_project, get_sg,
                                         get_subnets, request_vif, update_crd,
                                         release_vif):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        kp.k8s.get.return_value = self._pod
        get_sg.return_value = self._security_groups
        get_project.return_value = self._project_id
        get_subnets.return_value = mock.sentinel.subnets
        request_vif.return_value = self._vif1
        update_crd.side_effect = k_exc.K8sClientException()

        self.assertTrue(kp.get_vifs(self._kp))

        kp.k8s.get.assert_called_once_with(self._pod_uri)
        get_project.assert_called_once_with(self._pod)
        get_sg.assert_called_once_with(self._pod, self._project_id)
        get_subnets.assert_called_once_with(self._pod, self._project_id)
        request_vif.assert_called_once_with(self._pod, self._project_id,
                                            mock.sentinel.subnets,
                                            self._security_groups)
        update_crd.assert_called_once_with(self._kp,
                                           {constants.DEFAULT_IFNAME:
                                            {'default': True,
                                             'vif': self._vif1}})
        release_vif.assert_called_once_with(self._pod, self._vif1,
                                            self._project_id)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_update_kuryrport_crd(self, ged, k8s):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()

        kp._update_kuryrport_crd(self._kp, self._vifs)
        self._vif1.obj_reset_changes()
        self._vif2.obj_reset_changes()
        vif1 = self._vif1.obj_to_primitive()
        vif2 = self._vif2.obj_to_primitive()

        arg = {'vifs': {'eth0': {'default': True, 'vif': vif1},
                        'eth1': {'default': False, 'vif': vif2}}}
        kp.k8s.patch_crd.assert_called_once_with('status',
                                                 utils.get_res_link(self._kp),
                                                 arg)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'service_matches_affected_pods')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.MultiVIFDriver.'
                'get_enabled_drivers')
    def test_update_services(self, ged, k8s, smap):
        ged.return_value = [self._driver]
        kp = kuryrport.KuryrPortHandler()
        kp._drv_lbaas = mock.MagicMock()
        kp._drv_svc_sg = mock.MagicMock()
        kp._drv_svc_sg.get_security_groups.return_value = self._security_groups

        smap.side_effect = [True, False]
        services = {'items': ['service1', 'service2']}

        kp._update_services(services, mock.sentinel.crd_pod_selectors,
                            self._project_id)

        smap.assert_has_calls([mock.call('service1',
                                         mock.sentinel.crd_pod_selectors),
                               mock.call('service2',
                                         mock.sentinel.crd_pod_selectors)])
        kp._drv_svc_sg.get_security_groups.assert_called_once_with(
            'service1', self._project_id)
        kp._drv_lbaas.update_lbaas_sg.assert_called_once_with(
            'service1', self._security_groups)
