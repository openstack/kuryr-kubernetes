# Copyright 2017 Red Hat, Inc.
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

import queue
from unittest import mock

from oslo_serialization import jsonutils

from kuryr_kubernetes.cni.daemon import service
from kuryr_kubernetes.cni.plugins import k8s_cni_registry
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base
from kuryr_kubernetes.tests import fake
from kuryr_kubernetes.tests.unit import kuryr_fixtures


class TestDaemonServer(base.TestCase):
    def setUp(self):
        super(TestDaemonServer, self).setUp()
        healthy = mock.Mock()
        self.k8s_mock = self.useFixture(kuryr_fixtures.MockK8sClient())
        self.plugin = k8s_cni_registry.K8sCNIRegistryPlugin({}, healthy)
        self.health_registry = mock.Mock()
        self.metrics = queue.Queue()
        self.srv = service.DaemonServer(
            self.plugin, self.health_registry, self.metrics)

        self.srv.application.testing = True
        self.test_client = self.srv.application.test_client()
        cni_args = 'foo=bar;K8S_POD_NAMESPACE=test;K8S_POD_NAME=test'
        params = {'config_kuryr': {}, 'CNI_ARGS': cni_args,
                  'CNI_CONTAINERID': 'baz', 'CNI_COMMAND': 'ADD'}
        self.params_str = jsonutils.dumps(params)

    @mock.patch('kuryr_kubernetes.cni.plugins.k8s_cni_registry.'
                'K8sCNIRegistryPlugin.add')
    def test_add(self, m_add):
        vif = fake._fake_vif()
        m_add.return_value = vif

        resp = self.test_client.post('/addNetwork', data=self.params_str,
                                     content_type='application/json')

        m_add.assert_called_once_with(mock.ANY)
        self.assertEqual(
            fake._fake_vif_string(vif.obj_to_primitive()).encode(), resp.data)
        self.assertEqual(202, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.plugins.k8s_cni_registry.'
                'K8sCNIRegistryPlugin.add')
    def test_add_timeout(self, m_add):
        m_add.side_effect = exceptions.CNIKuryrPortTimeout('bar')

        resp = self.test_client.post('/addNetwork', data=self.params_str,
                                     content_type='application/json')

        m_add.assert_called_once_with(mock.ANY)
        self.assertEqual(504, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.plugins.k8s_cni_registry.'
                'K8sCNIRegistryPlugin.add')
    def test_add_error(self, m_add):
        m_add.side_effect = Exception

        resp = self.test_client.post('/addNetwork', data=self.params_str,
                                     content_type='application/json')

        m_add.assert_called_once_with(mock.ANY)
        self.assertEqual(500, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.plugins.k8s_cni_registry.'
                'K8sCNIRegistryPlugin.delete')
    def test_delete(self, m_delete):
        resp = self.test_client.post('/delNetwork', data=self.params_str,
                                     content_type='application/json')

        m_delete.assert_called_once_with(mock.ANY)
        self.assertEqual(204, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.plugins.k8s_cni_registry.'
                'K8sCNIRegistryPlugin.delete')
    def test_delete_timeout(self, m_delete):
        m_delete.side_effect = exceptions.CNIKuryrPortTimeout('foo')
        resp = self.test_client.post('/delNetwork', data=self.params_str,
                                     content_type='application/json')

        m_delete.assert_called_once_with(mock.ANY)
        self.assertEqual(204, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.plugins.k8s_cni_registry.'
                'K8sCNIRegistryPlugin.delete')
    def test_delete_error(self, m_delete):
        m_delete.side_effect = Exception
        resp = self.test_client.post('/delNetwork', data=self.params_str,
                                     content_type='application/json')

        m_delete.assert_called_once_with(mock.ANY)
        self.assertEqual(500, resp.status_code)
