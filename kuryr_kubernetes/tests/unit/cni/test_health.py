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

from ctypes import c_bool
from kuryr_kubernetes.cni import health
from kuryr_kubernetes.tests import base
import mock
import multiprocessing

from oslo_config import cfg


class TestResourceUsage(object):
    pass


class TestCNIHealthServer(base.TestCase):

    def setUp(self):
        super(TestCNIHealthServer, self).setUp()
        healthy = multiprocessing.Value(c_bool, True)
        self.srv = health.CNIHealthServer(healthy)
        self.srv.application.testing = True
        self.test_client = self.srv.application.test_client()

    @mock.patch('kuryr_kubernetes.cni.health._has_cap')
    @mock.patch('kuryr_kubernetes.cni.health.CNIHealthServer.'
                'verify_k8s_connection')
    def test_readiness_status(self, m_verify_k8s_conn, cap_tester):
        cap_tester.return_value = True
        m_verify_k8s_conn.return_value = True, 200
        resp = self.test_client.get('/ready')
        self.assertEqual(200, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.health._has_cap')
    @mock.patch('kuryr_kubernetes.cni.health.CNIHealthServer.'
                'verify_k8s_connection')
    def test_readiness_status_net_admin_error(self, m_verify_k8s_conn,
                                              cap_tester):
        cap_tester.return_value = False
        m_verify_k8s_conn.return_value = True, 200
        resp = self.test_client.get('/ready')
        self.assertEqual(500, resp.status_code)

    @mock.patch('kuryr_kubernetes.cni.health._has_cap')
    @mock.patch('kuryr_kubernetes.cni.health.CNIHealthServer.'
                'verify_k8s_connection')
    def test_readiness_status_k8s_error(self, m_verify_k8s_conn, cap_tester):
        cap_tester.return_value = True
        m_verify_k8s_conn.return_value = False, 503
        resp = self.test_client.get('/ready')
        self.assertEqual(503, resp.status_code)

    @mock.patch('pyroute2.IPDB.release')
    def test_liveness_status(self, m_ipdb):
        self.srv._components_healthy.value = True
        resp = self.test_client.get('/alive')
        m_ipdb.assert_called()
        self.assertEqual(200, resp.status_code)

    def test_liveness_status_components_error(self):
        self.srv._components_healthy.value = False
        resp = self.test_client.get('/alive')
        self.assertEqual(500, resp.status_code)

    @mock.patch('pyroute2.IPDB.release')
    def test_liveness_status_ipdb_error(self, m_ipdb):
        m_ipdb.side_effect = Exception
        resp = self.test_client.get('/alive')
        self.assertEqual(500, resp.status_code)

    @mock.patch('psutil.Process.memory_info')
    def test_liveness_status_mem_usage_error(self, m_resource):
        cfg.CONF.set_override('max_memory_usage', 4096,
                              group='cni_health_server')
        cls = TestResourceUsage()
        cls.rss = 5368709120
        m_resource.return_value = cls
        resp = self.test_client.get('/alive')
        self.assertEqual(500, resp.status_code)


class TestCNIHealthUtils(base.TestCase):
    def test_has_cap(self):
        self.assertTrue(health._has_cap(health.CAP_NET_ADMIN, 'CapBnd:\t'))
