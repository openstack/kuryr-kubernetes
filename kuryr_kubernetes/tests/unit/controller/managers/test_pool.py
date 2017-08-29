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

try:
    from BaseHTTPServer import BaseHTTPRequestHandler
except ImportError:
    from http.server import BaseHTTPRequestHandler

from oslo_serialization import jsonutils

from kuryr_kubernetes.controller.managers import pool as m_pool
from kuryr_kubernetes.tests import base as test_base


class TestRequestHandler(test_base.TestCase):

    def setUp(self):
        super(TestRequestHandler, self).setUp()
        client_address = 'localhost'
        server = '/tmp/server.lock'
        req = mock.MagicMock()
        with mock.patch.object(BaseHTTPRequestHandler, '__init__') as m_http:
            m_http.return_value = None
            self._req_handler = m_pool.RequestHandler(req, client_address,
                                                      server)
        self._req_handler.rfile = mock.Mock()
        self._req_handler.wfile = mock.Mock()

    def _do_POST_helper(self, method, path, headers, body, expected_resp,
                        trigger_exception, trunk_ips, num_ports=None):
        self._req_handler.headers = headers
        self._req_handler.path = path

        with mock.patch.object(self._req_handler.rfile, 'read') as m_read,\
            mock.patch.object(self._req_handler,
                              '_create_subports') as m_create,\
            mock.patch.object(self._req_handler,
                              '_delete_subports') as m_delete:
            m_read.return_value = body
            if trigger_exception:
                m_create.side_effect = Exception
                m_delete.side_effect = Exception

            with mock.patch.object(self._req_handler,
                                   'send_header') as m_send_header,\
                mock.patch.object(self._req_handler,
                                  'end_headers') as m_end_headers,\
                mock.patch.object(self._req_handler.wfile,
                                  'write') as m_write:
                self._req_handler.do_POST()

                if method == 'create':
                    if trunk_ips:
                        m_create.assert_called_once_with(num_ports, trunk_ips)
                    else:
                        m_create.assert_not_called()
                if method == 'delete':
                    m_delete.assert_called_once_with(trunk_ips)

                m_send_header.assert_called_once_with('Content-Length',
                                                      len(expected_resp))
                m_end_headers.assert_called_once()
                m_write.assert_called_once_with(expected_resp)

    def test_do_POST_populate(self):
        method = 'create'
        path = "http://localhost/populatePool"
        trunk_ips = [u"10.0.0.6"]
        num_ports = 3
        body = jsonutils.dumps({"trunks": trunk_ips,
                                "num_ports": num_ports})
        headers = {'Content-Type': 'application/json', 'Connection': 'close'}
        headers['Content-Length'] = len(body)
        trigger_exception = False

        expected_resp = ('Ports pool at {} was populated with 3 ports.'
                         .format(trunk_ips)).encode()

        self._do_POST_helper(method, path, headers, body, expected_resp,
                             trigger_exception, trunk_ips, num_ports)

    def test_do_POST_populate_exception(self):
        method = 'create'
        path = "http://localhost/populatePool"
        trunk_ips = [u"10.0.0.6"]
        num_ports = 3
        body = jsonutils.dumps({"trunks": trunk_ips,
                                "num_ports": num_ports})
        headers = {'Content-Type': 'application/json', 'Connection': 'close'}
        headers['Content-Length'] = len(body)
        trigger_exception = True

        expected_resp = ('Error while populating pool {0} with {1} ports.'
                         .format(trunk_ips, num_ports)).encode()

        self._do_POST_helper(method, path, headers, body, expected_resp,
                             trigger_exception, trunk_ips, num_ports)

    def test_do_POST_populate_no_trunks(self):
        method = 'create'
        path = "http://localhost/populatePool"
        trunk_ips = []
        num_ports = 3
        body = jsonutils.dumps({"trunks": trunk_ips,
                                "num_ports": num_ports})
        headers = {'Content-Type': 'application/json', 'Connection': 'close'}
        headers['Content-Length'] = len(body)
        trigger_exception = False

        expected_resp = ('Trunk port IP(s) missing.'
                         .format(trunk_ips, num_ports)).encode()

        self._do_POST_helper(method, path, headers, body, expected_resp,
                             trigger_exception, trunk_ips, num_ports)

    def test_do_POST_free(self):
        method = 'delete'
        path = "http://localhost/freePool"
        trunk_ips = [u"10.0.0.6"]
        body = jsonutils.dumps({"trunks": trunk_ips})
        headers = {'Content-Type': 'application/json', 'Connection': 'close'}
        headers['Content-Length'] = len(body)
        trigger_exception = False

        expected_resp = ('Ports pool belonging to {0} was freed.'
                         .format(trunk_ips)).encode()

        self._do_POST_helper(method, path, headers, body, expected_resp,
                             trigger_exception, trunk_ips)

    def test_do_POST_free_exception(self):
        method = 'delete'
        path = "http://localhost/freePool"
        trunk_ips = [u"10.0.0.6"]
        body = jsonutils.dumps({"trunks": trunk_ips})
        headers = {'Content-Type': 'application/json', 'Connection': 'close'}
        headers['Content-Length'] = len(body)
        trigger_exception = True

        expected_resp = ('Error freeing ports pool: {0}.'
                         .format(trunk_ips)).encode()

        self._do_POST_helper(method, path, headers, body, expected_resp,
                             trigger_exception, trunk_ips)

    def test_do_POST_free_no_trunks(self):
        method = 'delete'
        path = "http://localhost/freePool"
        trunk_ips = []
        body = jsonutils.dumps({"trunks": trunk_ips})
        headers = {'Content-Type': 'application/json', 'Connection': 'close'}
        headers['Content-Length'] = len(body)
        trigger_exception = False

        expected_resp = ('Ports pool belonging to all was freed.').encode()

        self._do_POST_helper(method, path, headers, body, expected_resp,
                             trigger_exception, trunk_ips)

    def test_do_POST_wrong_action(self):
        method = 'fake'
        path = "http://localhost/fakeMethod"
        trunk_ips = [u"10.0.0.6"]
        body = jsonutils.dumps({"trunks": trunk_ips})
        headers = {'Content-Type': 'application/json', 'Connection': 'close'}
        headers['Content-Length'] = len(body)
        trigger_exception = False

        expected_resp = ('Method not allowed.').encode()

        self._do_POST_helper(method, path, headers, body, expected_resp,
                             trigger_exception, trunk_ips)
