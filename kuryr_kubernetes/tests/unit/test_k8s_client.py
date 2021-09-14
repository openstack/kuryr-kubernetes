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
import os
import tempfile
from unittest import mock

from oslo_serialization import jsonutils
import requests

from kuryr_kubernetes import exceptions as exc
from kuryr_kubernetes import k8s_client
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests import fake


class TestK8sClient(test_base.TestCase):
    @mock.patch('kuryr_kubernetes.config.CONF')
    def setUp(self, m_cfg):
        super(TestK8sClient, self).setUp()
        self.base_url = 'http://127.0.0.1:12345'
        m_cfg.kubernetes.ssl_client_crt_file = None
        m_cfg.kubernetes.ssl_client_key_file = None
        m_cfg.kubernetes.ssl_ca_crt_file = None
        m_cfg.kubernetes.token_file = None
        m_cfg.kubernetes.ssl_verify_server_crt = False
        self.client = k8s_client.K8sClient(self.base_url)
        default_cert = (None, None)
        default_token = None
        self.assertEqual(default_cert, self.client.cert)
        self.assertEqual(False, self.client.verify_server)
        self.assertEqual(default_token, self.client.token)

    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_https_client_init(self, m_cfg, m_exist):
        m_cfg.kubernetes.ssl_client_crt_file = 'dummy_crt_file_path'
        m_cfg.kubernetes.ssl_client_key_file = 'dummy_key_file_path'
        m_cfg.kubernetes.ssl_ca_crt_file = 'dummy_ca_file_path'
        m_cfg.kubernetes.token_file = None
        m_cfg.kubernetes.ssl_verify_server_crt = True
        m_exist.return_value = True
        test_client = k8s_client.K8sClient(self.base_url)
        cert = ('dummy_crt_file_path', 'dummy_key_file_path')
        self.assertEqual(cert, test_client.cert)
        self.assertEqual('dummy_ca_file_path', test_client.verify_server)

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_https_client_init_invalid_client_crt_path(self, m_cfg):
        m_cfg.kubernetes.ssl_client_crt_file = 'dummy_crt_file_path'
        m_cfg.kubernetes.ssl_client_key_file = 'dummy_key_file_path'
        m_cfg.kubernetes.token_file = None
        self.assertRaises(RuntimeError, k8s_client.K8sClient, self.base_url)

    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_https_client_init_invalid_ca_path(self, m_cfg, m_exist):
        m_cfg.kubernetes.ssl_client_crt_file = 'dummy_crt_file_path'
        m_cfg.kubernetes.ssl_client_key_file = 'dummy_key_file_path'
        m_cfg.kubernetes.ssl_ca_crt_file = None
        m_cfg.kubernetes.ssl_verify_server_crt = True
        m_cfg.kubernetes.token_file = None
        m_exist.return_value = True
        self.assertRaises(RuntimeError, k8s_client.K8sClient, self.base_url)

    @mock.patch('requests.sessions.Session.send')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_bearer_token(self, m_cfg, m_send):
        token_content = (
            "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJrdWJlcm5ldGVzL3Nl"
            "cnZpY2VhY2NvdW50Iiwia3ViZXJuZXRlcy5pby9zZXJ2aWNlYWNjb3VudC9uYW1lc"
            "3BhY2UiOiJrdWJlLXN5c3RlbSIsImt1YmVybmV0ZXMuaW8vc2VydmljZWFjY291bn"
            "Qvc2VjcmV0Lm5hbWUiOiJkZWZhdWx0LXRva2VuLWh4M3QxIiwia3ViZXJuZXRlcy5"
            "pby9zZXJ2aWNlYWNjb3VudC9zZXJ2aWNlLWFjY291bnQubmFtZSI6ImRlZmF1bHQi"
            "LCJrdWJlcm5ldGVzLmlvL3NlcnZpY2VhY2NvdW50L3NlcnZpY2UtYWNjb3VudC51a"
            "WQiOiIxYTkyM2ZmNi00MDkyLTExZTctOTMwYi1mYTE2M2VkY2ViMDUiLCJzdWIiOi"
            "JzeXN0ZW06c2VydmljZWFjY291bnQ6a3ViZS1zeXN0ZW06ZGVmYXVsdCJ9.lzcPef"
            "DQ-uzF5cD-5pLwTKpRvtvvxKB4LX8TLymrPLMTth8WGr1vT6jteJPmLiDZM2C5dZI"
            "iFJpOw4LL1XLullik-ls-CmnTWq97NvlW1cZolC0mNyRz6JcL7gkH8WfUSjLA7x80"
            "ORalanUxtl9-ghMGKCtKIACAgvr5gGT4iznGYQQRx_hKURs4O6Js5vhwNM6UuOKeW"
            "GDDAlhgHMG0u59z3bhiBLl6jbQktZsu8c3diXniQb3sYqYQcGKUm1IQFujyA_ByDb"
            "5GUtCv1BOPL_-IjYtvdJD8ZzQ_UnPFoYQklpDyJLB7_7qCGcfVEQbnSCh907NdKo4"
            "w_8Wkn2y-Tg")
        token_file = tempfile.NamedTemporaryFile(mode="w+t", delete=False)
        try:
            m_cfg.kubernetes.token_file = token_file.name
            token_file.write(token_content)
            token_file.close()
            m_cfg.kubernetes.ssl_verify_server_crt = False

            path = '/test'
            client = k8s_client.K8sClient(self.base_url)
            client.get(path)

            self.assertEqual(f'Bearer {token_content}',
                             m_send.call_args[0][0].headers['Authorization'])
        finally:
            os.unlink(m_cfg.kubernetes.token_file)

    @mock.patch('requests.sessions.Session.get')
    def test_get(self, m_get):
        path = '/test'
        ret = {'kind': 'Pod', 'apiVersion': 'v1'}

        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.json.return_value = ret
        m_get.return_value = m_resp

        self.assertEqual(ret, self.client.get(path))
        m_get.assert_called_once_with(self.base_url + path, headers=None)

    @mock.patch('requests.sessions.Session.get')
    def test_get_list(self, m_get):
        path = '/test'
        ret = {'kind': 'PodList',
               'apiVersion': 'v1',
               'items': [{'metadata': {'name': 'pod1'},
                          'spec': {},
                          'status': {}}]}
        res = {'kind': 'PodList',
               'apiVersion': 'v1',
               'items': [{'metadata': {'name': 'pod1'},
                          'spec': {},
                          'status': {},
                          'kind': 'Pod',
                          'apiVersion': 'v1'}]}

        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.json.return_value = ret
        m_get.return_value = m_resp

        self.assertDictEqual(res, self.client.get(path))
        m_get.assert_called_once_with(self.base_url + path, headers=None)

    @mock.patch('requests.sessions.Session.get')
    def test_get_exception(self, m_get):
        path = '/test'

        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_get.return_value = m_resp

        self.assertRaises(exc.K8sClientException, self.client.get, path)

    @mock.patch('requests.sessions.Session.get')
    def test_get_null_on_items_list(self, m_get):
        path = '/test'

        req = {'kind': 'PodList',
               'apiVersion': 'v1',
               'metadata': {},
               'items': None}

        ret = {'kind': 'PodList',
               'apiVersion': 'v1',
               'metadata': {},
               'items': []}

        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.json.return_value = req
        m_get.return_value = m_resp

        self.assertEqual(self.client.get(path), ret)

    @mock.patch('itertools.count')
    @mock.patch('requests.sessions.Session.patch')
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
    @mock.patch('requests.sessions.Session.patch')
    def test_annotate_exception(self, m_patch, m_count):
        m_count.return_value = list(range(1, 5))
        path = '/test'

        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_patch.return_value = m_resp

        self.assertRaises(exc.K8sClientException, self.client.annotate,
                          path, {})

    @mock.patch('itertools.count')
    @mock.patch('requests.sessions.Session.patch')
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
                      headers=mock.ANY)])

    @mock.patch('itertools.count')
    @mock.patch('requests.sessions.Session.patch')
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
    @mock.patch('requests.sessions.Session.patch')
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
        good_obj = {'metadata': {
            'annotations': annotations,
            'resourceVersion': new_resource_version}}
        conflicting_data = jsonutils.dumps(conflicting_obj, sort_keys=True)
        good_data = jsonutils.dumps(good_obj, sort_keys=True)

        m_resp_conflict = mock.MagicMock()
        m_resp_conflict.ok = False
        m_resp_conflict.status_code = requests.codes.conflict
        m_patch.return_value = m_resp_conflict
        m_resp_good = mock.MagicMock()
        m_resp_good.ok = True
        m_resp_good.json.return_value = conflicting_obj
        m_patch.side_effect = [m_resp_conflict, m_resp_good]

        with mock.patch.object(self.client, 'get') as m_get:
            m_get.return_value = actual_obj
            self.assertEqual(annotations, self.client.annotate(
                path, annotations,
                resource_version=resource_version))
        m_patch.assert_has_calls([
            mock.call(self.base_url + path,
                      data=conflicting_data,
                      headers=mock.ANY),
            mock.call(self.base_url + path,
                      data=good_data,
                      headers=mock.ANY)])

    @mock.patch('itertools.count')
    @mock.patch('requests.sessions.Session.patch')
    def test_annotate_resource_not_found(self, m_patch, m_count):
        m_count.return_value = list(range(1, 5))
        path = '/test'
        annotations = {'a1': 'v1', 'a2': 'v2'}
        resource_version = "123"
        annotate_obj = {'metadata': {
            'annotations': annotations,
            'resourceVersion': resource_version}}
        annotate_data = jsonutils.dumps(annotate_obj, sort_keys=True)

        m_resp_not_found = mock.MagicMock()
        m_resp_not_found.ok = False
        m_resp_not_found.status_code = requests.codes.not_found
        m_patch.return_value = m_resp_not_found

        self.assertRaises(exc.K8sResourceNotFound,
                          self.client.annotate,
                          path,
                          annotations,
                          resource_version=resource_version)
        m_patch.assert_called_once_with(self.base_url + path,
                                        data=annotate_data,
                                        headers=mock.ANY)

    @mock.patch('requests.sessions.Session.get')
    def test_watch(self, m_get):
        path = '/test'
        data = [{'obj': 'obj%s' % i} for i in range(3)]
        lines = [jsonutils.dump_as_bytes(i) for i in data]

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

    @mock.patch('requests.sessions.Session.get')
    def test_watch_restart(self, m_get):
        path = '/test'
        data = [{'object': {'metadata': {'name': 'obj%s' % i,
                                         'resourceVersion': i}}}
                for i in range(3)]
        lines = [jsonutils.dump_as_bytes(i) for i in data]

        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.iter_lines.side_effect = [lines, requests.ReadTimeout, lines]
        m_get.return_value = m_resp

        self.assertEqual(data * 2,
                         list(itertools.islice(self.client.watch(path),
                                               len(data) * 2)))
        self.assertEqual(3, m_get.call_count)
        self.assertEqual(3, m_resp.close.call_count)
        m_get.assert_any_call(
            self.base_url + path, stream=True, params={"watch": "true"})
        m_get.assert_any_call(
            self.base_url + path, stream=True, params={"watch": "true",
                                                       "resourceVersion": 2})

    @mock.patch('requests.sessions.Session.get')
    def test_watch_exception(self, m_get):
        path = '/test'

        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_get.return_value = m_resp

        self.assertRaises(exc.K8sClientException, next,
                          self.client.watch(path))

    @mock.patch('requests.sessions.Session.post')
    def test_post(self, m_post):
        path = '/test'
        body = {'test': 'body'}
        ret = {'test': 'value'}

        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.json.return_value = ret
        m_post.return_value = m_resp

        self.assertEqual(ret, self.client.post(path, body))
        m_post.assert_called_once_with(self.base_url + path, json=body,
                                       headers=mock.ANY)

    @mock.patch('requests.sessions.Session.post')
    def test_post_exception(self, m_post):
        path = '/test'
        body = {'test': 'body'}

        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_post.return_value = m_resp

        self.assertRaises(exc.K8sClientException,
                          self.client.post, path, body)

    @mock.patch('requests.sessions.Session.delete')
    def test_delete(self, m_delete):
        path = '/test'
        ret = {'test': 'value'}

        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.json.return_value = ret
        m_delete.return_value = m_resp

        self.assertEqual(ret, self.client.delete(path))
        m_delete.assert_called_once_with(self.base_url + path,
                                         headers=mock.ANY)

    @mock.patch('requests.sessions.Session.delete')
    def test_delete_exception(self, m_delete):
        path = '/test'

        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_delete.return_value = m_resp

        self.assertRaises(exc.K8sClientException,
                          self.client.delete, path)

    def test__raise_from_response(self):
        m_resp = mock.MagicMock()
        m_resp.ok = True
        m_resp.status_code = 202
        self.client._raise_from_response(m_resp)

    def test__raise_from_response_404(self):
        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_resp.status_code = 404
        self.assertRaises(exc.K8sResourceNotFound,
                          self.client._raise_from_response, m_resp)

    def test__raise_from_response_500(self):
        m_resp = mock.MagicMock()
        m_resp.ok = False
        m_resp.status_code = 500
        self.assertRaises(exc.K8sClientException,
                          self.client._raise_from_response, m_resp)

    def test_add_event(self):
        self.client.post = mock.MagicMock()
        get_hex_ts = self.client._get_hex_timestamp = mock.MagicMock()
        get_hex_ts.return_value = 'deadc0de'

        namespace = 'n1'
        uid = 'deadbeef'
        name = 'pod-123'
        pod = fake.get_k8s_pod(name=name, namespace=namespace, uid=uid)
        event_name = f'{name}.deadc0de'

        self.client.add_event(pod, 'reason', 'message')

        # Event path
        url = self.client.post.call_args[0][0]
        data = self.client.post.call_args[0][1]
        self.assertEqual(url, f'/api/v1/namespaces/{namespace}/events')

        # Event fields
        self.assertEqual(data['metadata']['name'], event_name)
        self.assertEqual(data['reason'], 'reason')
        self.assertEqual(data['message'], 'message')
        self.assertEqual(data['type'], 'Normal')

        # involvedObject
        self.assertDictEqual(data['involvedObject'],
                             {'apiVersion': pod['apiVersion'],
                              'kind': pod['kind'],
                              'name': name,
                              'namespace': namespace,
                              'uid': uid})

    def test_add_event_k8s_exception(self):
        self.client.post = mock.MagicMock()
        self.client.post.side_effect = exc.K8sClientException
        pod = fake.get_k8s_pod()

        self.assertDictEqual(self.client.add_event(pod, 'reason1', 'message2'),
                             {})
