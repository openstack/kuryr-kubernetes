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

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.managers import health
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import health as h_health
from kuryr_kubernetes.tests import base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix
import mock
from oslo_config import cfg as oslo_cfg


def get_quota_obj():
    return {
        'quota': {
            'subnet': 100,
            'network': 100,
            'floatingip': 50,
            'subnetpool': -1,
            'security_group_rule': 100,
            'security_group': 10,
            'router': 10,
            'rbac_policy': 10,
            'port': 500
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
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                '_has_kuryr_crd')
    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    def test_readiness(self, m_verify_k8s_conn, m_verify_keystone_conn,
                       m_exist, m_has_kuryr_crd, m_components_ready):
        m_has_kuryr_crd.side_effect = [True, True]
        m_verify_k8s_conn.return_value = True, 200
        m_exist.return_value = True
        m_components_ready.return_value = True

        resp = self.test_client.get('/ready')

        m_verify_k8s_conn.assert_called_once()
        m_verify_keystone_conn.assert_called_once()
        self.assertEqual(m_has_kuryr_crd.call_count, 2)
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
                '_has_kuryr_crd')
    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    def test_readiness_kuryrnet_crd_error(self, m_verify_k8s_conn,
                                          m_verify_keystone_conn,
                                          m_exist, m_has_kuryr_crd):
        kuryrnets_url = k_const.K8S_API_CRD_KURYRNETS
        m_has_kuryr_crd.side_effect = [False]

        resp = self.test_client.get('/ready')

        m_has_kuryr_crd.assert_called_with(kuryrnets_url)
        self.assertEqual(m_has_kuryr_crd.call_count, 1)
        self.assertEqual(500, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                '_has_kuryr_crd')
    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    def test_readiness_kuryrnetpolicy_crd_error(self, m_verify_k8s_conn,
                                                m_verify_keystone_conn,
                                                m_exist, m_has_kuryr_crd):
        kuryrnetpolicies_url = k_const.K8S_API_CRD_KURYRNETPOLICIES
        m_has_kuryr_crd.side_effect = [True, False]

        resp = self.test_client.get('/ready')

        self.assertEqual(m_has_kuryr_crd.call_count, 2)
        m_has_kuryr_crd.assert_called_with(kuryrnetpolicies_url)
        self.assertEqual(500, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                '_components_ready')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                '_has_kuryr_crd')
    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    def test_readiness_neutron_error(self, m_verify_k8s_conn,
                                     m_verify_keystone_conn,
                                     m_exist, m_has_kuryr_crd,
                                     m_components_ready):
        m_components_ready.side_effect = Exception

        resp = self.test_client.get('/ready')

        m_components_ready.assert_called_once()
        self.assertEqual(500, resp.status_code)

    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                '_components_ready')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                '_has_kuryr_crd')
    @mock.patch('os.path.exists')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_keystone_connection')
    @mock.patch('kuryr_kubernetes.controller.managers.health.HealthServer.'
                'verify_k8s_connection')
    def test_readiness_components_ready_error(self, m_verify_k8s_conn,
                                              m_verify_keystone_conn,
                                              m_exist, m_has_kuryr_crd,
                                              m_components_ready):
        m_components_ready.return_value = False

        resp = self.test_client.get('/ready')

        m_components_ready.assert_called_once()
        self.assertEqual(500, resp.status_code)

    def test__has_kuryrnet_crd(self):
        kuryrnet_crd = {
            "apiVersion": "openstack.org/v1",
            "items": [

            ],
            "kind": "KuryrNetList",
            "metadata": {
                "continue": "",
                "resourceVersion": "33018",
                "selfLink": "/apis/openstack.org/v1/kuryrnets"
            }
        }

        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        kubernetes.get.return_value = kuryrnet_crd

        kuryrnets_url = k_const.K8S_API_CRD_KURYRNETS
        resp = self.srv._has_kuryr_crd(kuryrnets_url)

        self.assertEqual(resp, True)

    def test__has_kuryrnetpolicy_crd(self):
        kuryrnetpolicies_crd = {
            "apiVersion": "openstack.org/v1",
            "items": [

            ],
            "kind": "KuryrNetPolicyList",
            "metadata": {
                "continue": "",
                "resourceVersion": "34186",
                "selfLink": "/apis/openstack.org/v1/kuryrnetpolicies"
            }
        }
        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        kubernetes.get.return_value = kuryrnetpolicies_crd

        kuryrnetpolicies_url = k_const.K8S_API_CRD_KURYRNETPOLICIES
        resp = self.srv._has_kuryr_crd(kuryrnetpolicies_url)

        self.assertEqual(resp, True)

    def test__has_kuryr_crd_error(self):
        crds = [k_const.K8S_API_CRD_KURYRNETS,
                k_const.K8S_API_CRD_KURYRNETPOLICIES]
        for crd_url in crds:
            kubernetes = self.useFixture(k_fix.MockK8sClient()).client
            kubernetes.get.side_effect = k_exc.K8sClientException

            resp = self.srv._has_kuryr_crd(crd_url)
            self.assertEqual(resp, False)

            kubernetes.get.assert_called_once()

    @mock.patch.object(_TestHandler, 'is_ready')
    def test__components_ready(self, m_status):
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.show_quota.return_value = get_quota_obj()
        self.srv._registry = [_TestHandler()]
        m_status.return_value = True

        resp = self.srv._components_ready()

        m_status.assert_called_once()
        self.assertEqual(resp, True)
        neutron.show_quota.assert_called_once()

    @mock.patch.object(_TestHandler, 'is_ready')
    def test__components_ready_error(self, m_status):
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.show_quota.return_value = get_quota_obj()
        self.srv._registry = [_TestHandler()]
        m_status.return_value = False

        resp = self.srv._components_ready()

        m_status.assert_called_once()
        self.assertEqual(resp, False)
        neutron.show_quota.assert_called_once()

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
