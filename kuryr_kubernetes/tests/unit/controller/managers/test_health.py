# Copyright 2018 Maysa de Macedo Souza.
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

from keystoneauth1 import exceptions
from kuryr_kubernetes.controller.managers import health
from kuryr_kubernetes.handlers import health as h_health
from kuryr_kubernetes.tests import base
import mock
from oslo_config import cfg as oslo_cfg


class _TestHandler(h_health.HealthHandler):
    def is_healthy(self):
        pass


class TestHealthServer(base.TestCase):

    def setUp(self):
        super(TestHealthServer, self).setUp()
        self.srv = health.HealthServer()
        self.srv.application.testing = True
        self.test_client = self.srv.application.test_client()

    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_neutron_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    def test_read(self, m_verify_k8s_conn, m_verify_keystone_conn,
                  m_verify_neutron_conn, m_exist):
        m_verify_k8s_conn.return_value = True, 200
        m_exist.return_value = True
        resp = self.test_client.get('/ready')
        m_verify_k8s_conn.assert_called_once()
        m_verify_keystone_conn.assert_called_once()
        m_verify_neutron_conn.assert_called_once_with()

        self.assertEqual(200, resp.status_code)
        self.assertEqual('ok', resp.data.decode())

    @mock.patch('os.path.exists')
    def test_read_not_found(self, m_exist):
        m_exist.return_value = False
        oslo_cfg.CONF.set_override('vif_pool_driver', 'neutron',
                                   group='kubernetes')
        resp = self.test_client.get('/ready')
        self.assertEqual(404, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    @mock.patch('os.path.exists')
    def test_read_k8s_error(self, m_exist, m_verify_k8s_conn):
        m_exist.return_value = True
        m_verify_k8s_conn.return_value = False, 503
        resp = self.test_client.get('/ready')

        m_verify_k8s_conn.assert_called_once()
        self.assertEqual(503, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    @mock.patch('os.path.exists')
    def test_read_unauthorized(self, m_exist, m_verify_k8s_conn,
                               m_verify_keystone_conn):
        m_exist.return_value = True
        m_verify_k8s_conn.return_value = True, 200
        m_verify_keystone_conn.side_effect = exceptions.http.Unauthorized
        resp = self.test_client.get('/ready')

        m_verify_keystone_conn.assert_called_once()
        self.assertEqual(401, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_neutron_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    @mock.patch('os.path.exists')
    def test_read_neutron_error(self, m_exist, m_verify_k8s_conn,
                                m_verify_keystone_conn, m_verify_neutron_conn):
        m_exist.return_value = True
        m_verify_k8s_conn.return_value = True, 200
        m_verify_neutron_conn.side_effect = Exception
        resp = self.test_client.get('/ready')

        m_verify_neutron_conn.assert_called_once()
        self.assertEqual(500, resp.status_code)

    @mock.patch.object(_TestHandler, 'is_healthy')
    def test_liveness(self, m_status):
        m_status.return_value = True
        self.srv._registry = [_TestHandler()]

        resp = self.test_client.get('/alive')

        m_status.assert_called_once()
        self.assertEqual(200, resp.status_code)

    @mock.patch.object(_TestHandler, 'is_healthy')
    def test_liveness_error(self, m_status):
        m_status.return_value = False
        self.srv._registry = [_TestHandler()]
        resp = self.test_client.get('/alive')

        m_status.assert_called_once()
        self.assertEqual(500, resp.status_code)
