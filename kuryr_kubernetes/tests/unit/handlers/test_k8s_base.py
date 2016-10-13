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

from kuryr_kubernetes.handlers import k8s_base as h_k8s
from kuryr_kubernetes.tests import base as test_base


class TestResourceEventHandler(test_base.TestCase):

    @mock.patch.object(h_k8s.ResourceEventHandler, 'on_added')
    @mock.patch.object(h_k8s.ResourceEventHandler, 'on_present')
    def test_added(self, m_added, m_present):
        obj = mock.sentinel.obj
        event = {'type': 'ADDED', 'object': obj}
        handler = h_k8s.ResourceEventHandler()

        handler(event)

        m_added.assert_called_once_with(obj)
        m_present.assert_called_once_with(obj)

    @mock.patch.object(h_k8s.ResourceEventHandler, 'on_modified')
    @mock.patch.object(h_k8s.ResourceEventHandler, 'on_present')
    def test_modified(self, m_modified, m_present):
        obj = mock.sentinel.obj
        event = {'type': 'MODIFIED', 'object': obj}
        handler = h_k8s.ResourceEventHandler()

        handler(event)

        m_modified.assert_called_once_with(obj)
        m_present.assert_called_once_with(obj)

    @mock.patch.object(h_k8s.ResourceEventHandler, 'on_deleted')
    def test_deleted(self, m_deleted):
        obj = mock.sentinel.obj
        event = {'type': 'DELETED', 'object': obj}
        handler = h_k8s.ResourceEventHandler()

        handler(event)

        m_deleted.assert_called_once_with(obj)

    def test_unknown(self):
        event = {'type': 'UNKNOWN'}
        handler = h_k8s.ResourceEventHandler()

        handler(event)

        self.assertTrue(True)
