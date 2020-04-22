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

from kuryr_kubernetes.controller.managers import health
from kuryr_kubernetes.handlers import health as h_health
from kuryr_kubernetes.tests import base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix
from unittest import mock

from oslo_config import cfg as oslo_cfg


def get_quota_obj():
    return {
        'quota': {
            'subnet': {
                'used': 50,
                'limit': 100,
                'reserved': 0
            },
            'network': {
                'used': 50,
                'limit': 100,
                'reserved': 0
            },
            'floatingip': {
                'used': 25,
                'limit': 50,
                'reserved': 0
            },
            'subnetpool': {
                'used': 0,
                'limit': -1,
                'reserved': 0
            },
            'security_group_rule': {
                'used': 50,
                'limit': 100,
                'reserved': 0
            },
            'security_group': {
                'used': 5,
                'limit': 10,
                'reserved': 0
            },
            'router': {
                'used': 5,
                'limit': 10,
                'reserved': 0
            },
            'rbac_policy': {
                'used': 5,
                'limit': 10,
                'reserved': 0
            },
            'port': {
                'used': 250,
                'limit': 500,
                'reserved': 0
            }
        }
    }


class _TestHandler(h_health.HealthHandler):
    def is_alive(self):
        pass

    def is_ready(self):
        pass


class TestHealthServer(base.TestCase):

    def setUp(self):
        super(TestHealthServer, self).setUp()
        self.srv = health.HealthServer()
        self.srv.application.testing = True
        self.test_client = self.srv.application.test_client()

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                '_components_ready')
    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    def test_readiness(self, m_verify_k8s_conn, m_verify_keystone_conn,
                       m_exist, m_components_ready):
        m_verify_k8s_conn.return_value = True, 200
        m_exist.return_value = True
        m_components_ready.return_value = True

        resp = self.test_client.get('/ready')

        m_verify_k8s_conn.assert_called_once()
        m_verify_keystone_conn.assert_called_once()
        m_components_ready.assert_called_once()

        self.assertEqual(200, resp.status_code)
        self.assertEqual('ok', resp.data.decode())

    @mock.patch('os.path.exists')
    def test_readiness_not_found(self, m_exist):
        m_exist.return_value = False
        oslo_cfg.CONF.set_override('vif_pool_driver', 'neutron',
                                   group='kubernetes')
        resp = self.test_client.get('/ready')
        self.assertEqual(404, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    @mock.patch('os.path.exists')
    def test_readiness_k8s_error(self, m_exist, m_verify_k8s_conn):
        m_exist.return_value = True
        m_verify_k8s_conn.return_value = False
        resp = self.test_client.get('/ready')

        m_verify_k8s_conn.assert_called_once()
        self.assertEqual(500, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    @mock.patch('os.path.exists')
    def test_readiness_unauthorized(self, m_exist, m_verify_k8s_conn,
                                    m_verify_keystone_conn):
        m_exist.return_value = True
        m_verify_k8s_conn.return_value = True, 200
        m_verify_keystone_conn.side_effect = Exception
        resp = self.test_client.get('/ready')

        m_verify_keystone_conn.assert_called_once()
        self.assertEqual(500, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                '_components_ready')
    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    def test_readiness_neutron_error(self, m_verify_k8s_conn,
                                     m_verify_keystone_conn,
                                     m_exist, m_components_ready):
        m_components_ready.side_effect = Exception

        resp = self.test_client.get('/ready')

        m_components_ready.assert_called_once()
        self.assertEqual(500, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                '_components_ready')
    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    def test_readiness_components_ready_error(self, m_verify_k8s_conn,
                                              m_verify_keystone_conn,
                                              m_exist, m_components_ready):
        m_components_ready.return_value = False

        resp = self.test_client.get('/ready')

        m_components_ready.assert_called_once()
        self.assertEqual(500, resp.status_code)

    @mock.patch.object(_TestHandler, 'is_ready')
    def test__components_ready(self, m_status):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.get_quota.return_value = get_quota_obj()
        self.srv._registry = [_TestHandler()]
        m_status.return_value = True

        resp = self.srv._components_ready()

        m_status.assert_called_once()
        self.assertIs(resp, True)
        os_net.get_quota.assert_called_once()

    @mock.patch.object(_TestHandler, 'is_ready')
    def test__components_ready_error(self, m_status):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.get_quota.return_value = get_quota_obj()
        self.srv._registry = [_TestHandler()]
        m_status.return_value = False

        resp = self.srv._components_ready()

        m_status.assert_called_once()
        self.assertIs(resp, False)
        os_net.get_quota.assert_called_once()

    @mock.patch.object(_TestHandler, 'is_alive')
    def test_liveness(self, m_status):
        m_status.return_value = True
        self.srv._registry = [_TestHandler()]

        resp = self.test_client.get('/alive')

        m_status.assert_called_once()
        self.assertEqual(200, resp.status_code)

    @mock.patch.object(_TestHandler, 'is_alive')
    def test_liveness_error(self, m_status):
        m_status.return_value = False
        self.srv._registry = [_TestHandler()]
        resp = self.test_client.get('/alive')

        m_status.assert_called_once()
        self.assertEqual(500, resp.status_code)
