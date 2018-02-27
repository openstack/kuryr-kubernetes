# Copyright (c) 2017 NEC Corporation.
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

from kuryr_kubernetes.cni.plugins import k8s_cni
from kuryr_kubernetes import constants
from kuryr_kubernetes.tests import base as test_base


class TestK8sCNIPlugin(test_base.TestCase):
    @mock.patch('kuryr_kubernetes.watcher.Watcher')
    @mock.patch('kuryr_kubernetes.cni.handlers.CNIPipeline')
    @mock.patch('kuryr_kubernetes.cni.handlers.DelHandler')
    @mock.patch('kuryr_kubernetes.cni.handlers.AddHandler')
    def _test_method(self, method, m_add_handler, m_del_handler, m_cni_pipe,
                     m_watcher_class):
        self.passed_handler = None

        def _save_handler(params, handler):
            self.passed_handler = handler

        def _call_handler(*args):
            self.passed_handler(mock.sentinel.vif)

        m_add_handler.side_effect = _save_handler
        m_del_handler.side_effect = _save_handler

        m_watcher = mock.MagicMock(
            add=mock.MagicMock(),
            start=mock.MagicMock(side_effect=_call_handler))
        m_watcher_class.return_value = m_watcher

        m_params = mock.MagicMock()
        m_params.args.K8S_POD_NAMESPACE = 'k8s_pod_namespace'
        m_params.args.K8S_POD_NAME = 'k8s_pod'

        cni_plugin = k8s_cni.K8sCNIPlugin()
        result = getattr(cni_plugin, method)(m_params)
        self.assertEqual(mock.sentinel.vif, cni_plugin._vif)
        m_watcher.add.assert_called_with(
            "%(base)s/namespaces/%(namespace)s/pods"
            "?fieldSelector=metadata.name=%(pod)s" % {
                'base': constants.K8S_API_BASE,
                'namespace': m_params.args.K8S_POD_NAMESPACE,
                'pod': m_params.args.K8S_POD_NAME})

        return result

    def test_add(self):
        result = self._test_method('add')
        self.assertEqual(result, mock.sentinel.vif)

    def test_delete(self):
        self._test_method('delete')
