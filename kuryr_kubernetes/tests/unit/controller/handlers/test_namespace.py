# Copyright (c) 2018 Red Hat, Inc.
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

from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.handlers import namespace
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.tests import base as test_base


class TestNamespaceHandler(test_base.TestCase):

    def setUp(self):
        super(TestNamespaceHandler, self).setUp()

        self._project_id = mock.sentinel.project_id
        self._subnets = mock.sentinel.subnets

        self._namespace_version = mock.sentinel.namespace_version
        self._namespace_link = mock.sentinel.namespace_link

        self._namespace_name = 'ns-test'
        self._namespace = {
            'metadata': {'name': self._namespace_name,
                         'resourceVersion': self._namespace_version},
            'status': {'phase': 'Active'}
        }
        self._crd_id = 'ns-' + self._namespace_name

        self._handler = mock.MagicMock(spec=namespace.NamespaceHandler)

        self._handler._drv_project = mock.Mock(
            spec=drivers.NamespaceProjectDriver)

        self._get_project = self._handler._drv_project.get_project
        self._update_labels = self._handler._update_labels
        self._get_kns_crd = self._handler._get_kns_crd
        self._add_kuryrnetwork_crd = self._handler._add_kuryrnetwork_crd
        self._handle_namespace = self._handler._handle_namespace

        self._get_project.return_value = self._project_id

    def _get_crd(self):
        crd = {
            'kind': 'KuryrNetwork',
            'metadata': {
                'name': self._namespace_name,
                'namespace': self._namespace_name,
            },
            'spec': {}
        }
        return crd

    @mock.patch.object(drivers.NamespaceProjectDriver, 'get_instance')
    def test_init(self, m_get_project_driver):
        project_driver = mock.sentinel.project_driver
        m_get_project_driver.return_value = project_driver

        handler = namespace.NamespaceHandler()
        self.assertEqual(project_driver, handler._drv_project)

    def test_on_present(self):
        self._get_kns_crd.return_value = None
        self._handle_namespace.return_value = True

        namespace.NamespaceHandler.on_present(self._handler, self._namespace)

        self._handle_namespace.assert_called_once()
        self._get_kns_crd.assert_called_once_with(
            self._namespace['metadata']['name'])
        self._add_kuryrnetwork_crd.assert_called_once_with(
            self._namespace, {})

    def test_on_present_existing(self):
        net_crd = self._get_crd()
        self._get_kns_crd.return_value = net_crd

        namespace.NamespaceHandler.on_present(self._handler, self._namespace)

        self._handle_namespace.assert_not_called()
        self._get_kns_crd.assert_called_once_with(
            self._namespace['metadata']['name'])
        self._update_labels.assert_called_once_with(net_crd, {})
        self._add_kuryrnetwork_crd.assert_not_called()

    def test_on_present_add_kuryrnetwork_crd_exception(self):
        self._get_kns_crd.return_value = None
        self._add_kuryrnetwork_crd.side_effect = k_exc.K8sClientException
        self._handle_namespace.return_value = True

        self.assertRaises(k_exc.ResourceNotReady,
                          namespace.NamespaceHandler.on_present,
                          self._handler, self._namespace)

        self._handle_namespace.assert_called_once()
        self._get_kns_crd.assert_called_once_with(
            self._namespace['metadata']['name'])
        self._add_kuryrnetwork_crd.assert_called_once_with(
            self._namespace, {})

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_handle_namespace_no_pods(self, m_get_k8s_client):
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s
        k8s.get.return_value = {"items": []}
        self.assertFalse(namespace.NamespaceHandler._handle_namespace(
            self._handler, "test"))
        k8s.get.assert_called_once()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_handle_namespace_host_network_pods(self, m_get_k8s_client):
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s
        k8s.get.return_value = {"items": [{"spec": {"hostNetwork": True}}]}
        self.assertFalse(namespace.NamespaceHandler._handle_namespace(
            self._handler, "test"))
        k8s.get.assert_called_once()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_handle_namespace(self, m_get_k8s_client):
        k8s = mock.MagicMock()
        m_get_k8s_client.return_value = k8s
        k8s.get.return_value = {"items": [{"spec": {}}]}
        self.assertTrue(namespace.NamespaceHandler._handle_namespace(
            self._handler, "test"))
        k8s.get.assert_called_once()
