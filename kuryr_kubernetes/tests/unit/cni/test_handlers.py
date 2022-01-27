# Copyright 2021 Red Hat, Inc.
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

from unittest import mock

from kuryr_kubernetes.cni import handlers
from kuryr_kubernetes.tests import base


class TestCNIDaemonHandlers(base.TestCase):
    def setUp(self):
        super().setUp()
        self.registry = {}
        self.pod = {'metadata': {'namespace': 'testing',
                                 'name': 'default'},
                    'vif_unplugged': False,
                    'del_receieved': False}
        self.healthy = mock.Mock()
        self.port_handler = handlers.CNIKuryrPortHandler(self.registry)
        self.pod_handler = handlers.CNIPodHandler(self.registry)

    @mock.patch('oslo_concurrency.lockutils.lock')
    def test_kp_on_deleted(self, m_lock):
        pod = self.pod
        pod['vif_unplugged'] = True
        pod_name = 'testing/default'
        self.registry[pod_name] = pod
        self.port_handler.on_deleted(pod)
        self.assertNotIn(pod_name, self.registry)

    @mock.patch('oslo_concurrency.lockutils.lock')
    def test_kp_on_deleted_false(self, m_lock):
        pod = self.pod
        pod_name = 'testing/default'
        self.registry[pod_name] = pod
        self.port_handler.on_deleted(pod)
        self.assertIn(pod_name, self.registry)
        self.assertIs(True, pod['del_received'])

    @mock.patch('oslo_concurrency.lockutils.lock')
    def test_pod_on_finalize(self, m_lock):
        pod = self.pod
        pod_name = 'testing/default'
        self.pod_handler.on_finalize(pod)
        self.assertIn(pod_name, self.registry)
        self.assertIsNone(self.registry[pod_name])
        m_lock.assert_called_once_with(pod_name, external=True)

    @mock.patch('oslo_concurrency.lockutils.lock')
    def test_pod_on_finalize_exists(self, m_lock):
        pod = self.pod
        pod_name = 'testing/default'
        self.registry[pod_name] = pod
        self.pod_handler.on_finalize(pod)
        self.assertIn(pod_name, self.registry)
        self.assertIsNotNone(self.registry[pod_name])
        m_lock.assert_called_once_with(pod_name, external=True)
