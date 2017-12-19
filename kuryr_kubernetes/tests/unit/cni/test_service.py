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

import mock

from oslo_config import cfg
from oslo_serialization import jsonutils

from kuryr_kubernetes.cni.daemon import service
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base
from kuryr_kubernetes.tests import fake


class TestK8sCNIRegistryPlugin(base.TestCase):
    def setUp(self):
        super(TestK8sCNIRegistryPlugin, self).setUp()
        self.pod = {'metadata': {'name': 'foo', 'uid': 'bar'}}
        self.vif = fake._fake_vif_dict()
        registry = {'foo': {'pod': self.pod, 'vif': self.vif,
                            'containerid': None}}
        self.plugin = service.K8sCNIRegistryPlugin(registry)
        self.params = mock.Mock(args=mock.Mock(K8S_POD_NAME='foo'),
                                CNI_IFNAME='baz', CNI_NETNS=123,
                                CNI_CONTAINERID='cont_id')

    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch('kuryr_kubernetes.cni.binding.base.connect')
    def test_add_present(self, m_connect, m_lock):
        self.plugin.add(self.params)

        m_lock.assert_called_with('foo', external=True)
        m_connect.assert_called_with(mock.ANY, mock.ANY, 'baz', 123)
        self.assertEqual('cont_id', self.plugin.registry['foo']['containerid'])

    @mock.patch('kuryr_kubernetes.cni.binding.base.disconnect')
    def test_del_present(self, m_disconnect):
        self.plugin.delete(self.params)

        m_disconnect.assert_called_with(mock.ANY, mock.ANY, 'baz', 123)

    @mock.patch('kuryr_kubernetes.cni.binding.base.disconnect')
    def test_del_wrong_container_id(self, m_disconnect):
        registry = {'foo': {'pod': self.pod, 'vif': self.vif,
                            'containerid': 'different'}}
        self.plugin = service.K8sCNIRegistryPlugin(registry)
        self.plugin.delete(self.params)

        m_disconnect.assert_not_called()

    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch('time.sleep', mock.Mock())
    @mock.patch('kuryr_kubernetes.cni.binding.base.connect')
    def test_add_present_on_5_try(self, m_connect, m_lock):
        se = [KeyError] * 5
        se.append({'pod': self.pod, 'vif': self.vif, 'containerid': None})
        se.append({'pod': self.pod, 'vif': self.vif, 'containerid': None})
        se.append({'pod': self.pod, 'vif': self.vif, 'containerid': None})
        m_getitem = mock.Mock(side_effect=se)
        m_setitem = mock.Mock()
        m_registry = mock.Mock(__getitem__=m_getitem, __setitem__=m_setitem)
        self.plugin.registry = m_registry
        self.plugin.add(self.params)

        m_lock.assert_called_with('foo', external=True)
        m_setitem.assert_called_once_with('foo', {'pod': self.pod,
                                                  'vif': self.vif,
                                                  'containerid': 'cont_id'})
        m_connect.assert_called_with(mock.ANY, mock.ANY, 'baz', 123)

    @mock.patch('time.sleep', mock.Mock())
    def test_add_not_present(self):
        cfg.CONF.set_override('vif_annotation_timeout', 0, group='cni_daemon')
        self.addCleanup(cfg.CONF.set_override, 'vif_annotation_timeout', 120,
                        group='cni_daemon')

        m_getitem = mock.Mock(side_effect=KeyError)
        m_registry = mock.Mock(__getitem__=m_getitem)
        self.plugin.registry = m_registry
        self.assertRaises(exceptions.ResourceNotReady, self.plugin.add,
                          self.params)


class TestDaemonServer(base.TestCase):
    def setUp(self):
        super(TestDaemonServer, self).setUp()
        self.plugin = service.K8sCNIRegistryPlugin({})
        self.srv = service.DaemonServer(self.plugin)

        self.srv.application.testing = True
        self.test_client = self.srv.application.test_client()
        params = {'config_kuryr': {}, 'CNI_ARGS': 'foo=bar',
                  'CNI_CONTAINERID': 'baz', 'CNI_COMMAND': 'ADD'}
        self.params_str = jsonutils.dumps(params)

    @mock.patch('kuryr_kubernetes.cni.daemon.service.K8sCNIRegistryPlugin.add')
    def test_add(self, m_add):
        vif = fake._fake_vif()
        m_add.return_value = vif

        resp = self.test_client.post('/addNetwork', data=self.params_str,
                                     content_type='application/json')

        m_add.assert_called_once_with(mock.ANY)
        self.assertEqual(
            fake._fake_vif_string(vif.obj_to_primitive()).encode(), resp.data)
        self.assertEqual(202, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.daemon.service.K8sCNIRegistryPlugin.add')
    def test_add_timeout(self, m_add):
        m_add.side_effect = exceptions.ResourceNotReady(mock.Mock())

        resp = self.test_client.post('/addNetwork', data=self.params_str,
                                     content_type='application/json')

        m_add.assert_called_once_with(mock.ANY)
        self.assertEqual(504, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.daemon.service.K8sCNIRegistryPlugin.add')
    def test_add_error(self, m_add):
        m_add.side_effect = Exception

        resp = self.test_client.post('/addNetwork', data=self.params_str,
                                     content_type='application/json')

        m_add.assert_called_once_with(mock.ANY)
        self.assertEqual(500, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.daemon.service.'
                'K8sCNIRegistryPlugin.delete')
    def test_delete(self, m_delete):
        resp = self.test_client.post('/delNetwork', data=self.params_str,
                                     content_type='application/json')

        m_delete.assert_called_once_with(mock.ANY)
        self.assertEqual(204, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.daemon.service.'
                'K8sCNIRegistryPlugin.delete')
    def test_delete_timeout(self, m_delete):
        m_delete.side_effect = exceptions.ResourceNotReady(mock.Mock())
        resp = self.test_client.post('/delNetwork', data=self.params_str,
                                     content_type='application/json')

        m_delete.assert_called_once_with(mock.ANY)
        self.assertEqual(204, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.daemon.service.'
                'K8sCNIRegistryPlugin.delete')
    def test_delete_error(self, m_delete):
        m_delete.side_effect = Exception
        resp = self.test_client.post('/delNetwork', data=self.params_str,
                                     content_type='application/json')

        m_delete.assert_called_once_with(mock.ANY)
        self.assertEqual(500, resp.status_code)
