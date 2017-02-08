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

import itertools
import mock

from oslo_serialization import jsonutils
import requests

from kuryr_kubernetes import exceptions as exc
from kuryr_kubernetes import k8s_client
from kuryr_kubernetes.tests import base as test_base


class TestK8sClient(test_base.TestCase):
    def setUp(self):
        super(TestK8sClient, self).setUp()
        self.base_url = 'http://127.0.0.1:12345'
        self.client = k8s_client.K8sClient(self.base_url)

    @mock.patch('requests.get')
    def test_get(self, m_get):
        path = '/test'
        ret = {'test': 'value'}

        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.json.return_value = ret
        m_get.return_value = m_resp

        self.assertEqual(ret, self.client.get(path))
        m_get.assert_called_once_with(self.base_url + path)

    @mock.patch('requests.get')
    def test_get_exception(self, m_get):
        path = '/test'

        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_get.return_value = m_resp

        self.assertRaises(exc.K8sClientException, self.client.get, path)

    @mock.patch('itertools.count')
    @mock.patch('requests.patch')
    def test_annotate(self, m_patch, m_count):
        m_count.return_value = list(range(1, 5))
        path = '/test'
        annotations = {'a1': 'v1', 'a2': 'v2'}
        resource_version = "123"
        ret = {'metadata': {'annotations': annotations,
                            "resourceVersion": resource_version}}
        data = jsonutils.dumps(ret, sort_keys=True)

        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.json.return_value = ret
        m_patch.return_value = m_resp

        self.assertEqual(annotations, self.client.annotate(
            path, annotations, resource_version=resource_version))
        m_patch.assert_called_once_with(self.base_url + path,
                                        data=data, headers=mock.ANY)

    @mock.patch('itertools.count')
    @mock.patch('requests.patch')
    def test_annotate_exception(self, m_patch, m_count):
        m_count.return_value = list(range(1, 5))
        path = '/test'

        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_patch.return_value = m_resp

        self.assertRaises(exc.K8sClientException, self.client.annotate,
                          path, {})

    @mock.patch('itertools.count')
    @mock.patch('requests.patch')
    def test_annotate_diff_resource_vers_no_conflict(self, m_patch, m_count):
        m_count.return_value = list(range(1, 5))
        path = '/test'
        annotations = {'a1': 'v1', 'a2': 'v2'}
        resource_version = "123"
        new_resource_version = "456"
        conflicting_obj = {'metadata': {
            'annotations': annotations,
            'resourceVersion': resource_version}}
        good_obj = {'metadata': {
            'annotations': annotations,
            'resourceVersion': new_resource_version}}
        conflicting_data = jsonutils.dumps(conflicting_obj, sort_keys=True)
        good_data = jsonutils.dumps(good_obj, sort_keys=True)

        m_resp_conflict = mock.MagicMock()
        m_resp_conflict.ok = False
        m_resp_conflict.status_code = requests.codes.conflict
        m_resp_good = mock.MagicMock()
        m_resp_good.ok = True
        m_resp_good.json.return_value = conflicting_obj
        m_patch.side_effect = [m_resp_conflict, m_resp_good]

        with mock.patch.object(self.client, 'get') as m_get:
            m_get.return_value = good_obj
            self.assertEqual(annotations, self.client.annotate(
                path, annotations, resource_version=resource_version))

        m_patch.assert_has_calls([
            mock.call(self.base_url + path,
                      data=conflicting_data,
                      headers=mock.ANY),
            mock.call(self.base_url + path,
                      data=good_data,
                      headers=mock.ANY)])

    @mock.patch('itertools.count')
    @mock.patch('requests.patch')
    def test_annotate_diff_resource_vers_no_annotation(self, m_patch, m_count):
        m_count.return_value = list(range(1, 5))
        path = '/test'
        annotations = {'a1': 'v1', 'a2': 'v2'}
        annotating_resource_version = '123'
        annotating_obj = {'metadata': {
            'annotations': annotations,
            'resourceVersion': annotating_resource_version}}
        annotating_data = jsonutils.dumps(annotating_obj, sort_keys=True)

        new_resource_version = '456'
        new_obj = {'metadata': {
            'resourceVersion': new_resource_version}}

        resolution_obj = annotating_obj.copy()
        resolution_obj['metadata']['resourceVersion'] = new_resource_version
        resolution_data = jsonutils.dumps(resolution_obj, sort_keys=True)

        m_resp_conflict = mock.MagicMock()
        m_resp_conflict.ok = False
        m_resp_conflict.status_code = requests.codes.conflict
        m_resp_good = mock.MagicMock()
        m_resp_good.ok = True
        m_resp_good.json.return_value = resolution_obj
        m_patch.side_effect = (m_resp_conflict, m_resp_good)

        with mock.patch.object(self.client, 'get') as m_get:
            m_get.return_value = new_obj
            self.assertEqual(annotations, self.client.annotate(
                path, annotations,
                resource_version=annotating_resource_version))

        m_patch.assert_has_calls([
            mock.call(self.base_url + path,
                      data=annotating_data,
                      headers=mock.ANY),
            mock.call(self.base_url + path,
                      data=resolution_data,
                      headers=mock.ANY)])

    @mock.patch('itertools.count')
    @mock.patch('requests.patch')
    def test_annotate_diff_resource_vers_conflict(self, m_patch, m_count):
        m_count.return_value = list(range(1, 5))
        path = '/test'
        annotations = {'a1': 'v1', 'a2': 'v2'}
        resource_version = "123"
        new_resource_version = "456"
        conflicting_obj = {'metadata': {
            'annotations': annotations,
            'resourceVersion': resource_version}}
        actual_obj = {'metadata': {
            'annotations': {'a1': 'v2'},
            'resourceVersion': new_resource_version}}
        conflicting_data = jsonutils.dumps(conflicting_obj, sort_keys=True)

        m_resp_conflict = mock.MagicMock()
        m_resp_conflict.ok = False
        m_resp_conflict.status_code = requests.codes.conflict
        m_patch.return_value = m_resp_conflict

        with mock.patch.object(self.client, 'get') as m_get:
            m_get.return_value = actual_obj
            self.assertRaises(exc.K8sClientException,
                              self.client.annotate,
                              path, annotations,
                              resource_version=resource_version)
        m_patch.assert_called_once_with(self.base_url + path,
                                        data=conflicting_data,
                                        headers=mock.ANY)

    @mock.patch('requests.get')
    def test_watch(self, m_get):
        path = '/test'
        data = [{'obj': 'obj%s' % i} for i in range(3)]
        lines = [jsonutils.dumps(i) for i in data]

        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.iter_lines.return_value = lines
        m_get.return_value = m_resp

        cycles = 3
        self.assertEqual(
            data * cycles,
            list(itertools.islice(self.client.watch(path),
                                  len(data) * cycles)))

        self.assertEqual(cycles, m_get.call_count)
        self.assertEqual(cycles, m_resp.close.call_count)
        m_get.assert_called_with(self.base_url + path, stream=True,
                                 params={'watch': 'true'})

    @mock.patch('requests.get')
    def test_watch_exception(self, m_get):
        path = '/test'

        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_get.return_value = m_resp

        self.assertRaises(exc.K8sClientException, next,
                          self.client.watch(path))
