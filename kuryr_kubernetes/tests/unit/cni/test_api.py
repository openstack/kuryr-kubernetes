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

from io import StringIO
from unittest import mock

from oslo_config import cfg
from oslo_serialization import jsonutils
import requests

from kuryr_kubernetes.cni import api
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests import fake

CONF = cfg.CONF


class TestCNIRunnerMixin(object):
    def test_run_invalid(self, *args):
        m_fin = StringIO()
        m_fout = StringIO()
        code = self.runner.run(
            {'CNI_COMMAND': 'INVALID', 'CNI_ARGS': 'foo=bar'}, m_fin, m_fout)

        self.assertEqual(1, code)

    def test_run_write_version(self, *args):
        m_fin = StringIO()
        m_fout = StringIO()
        code = self.runner.run(
            {'CNI_COMMAND': 'VERSION', 'CNI_ARGS': 'foo=bar'}, m_fin, m_fout)
        result = jsonutils.loads(m_fout.getvalue())

        self.assertEqual(0, code)
        self.assertEqual(api.CNIRunner.SUPPORTED_VERSIONS,
                         result['supportedVersions'])
        self.assertEqual(api.CNIRunner.VERSION, result['cniVersion'])


@mock.patch('requests.post')
class TestCNIDaemonizedRunner(test_base.TestCase, TestCNIRunnerMixin):
    def setUp(self):
        super(TestCNIDaemonizedRunner, self).setUp()
        self.runner = api.CNIDaemonizedRunner()
        self.port = int(CONF.cni_daemon.bind_address.split(':')[1])

    def _test_run(self, cni_cmd, path, m_post):
        m_fin = StringIO()
        m_fout = StringIO()
        env = {
            'CNI_COMMAND': cni_cmd,
            'CNI_CONTAINERID': 'a4181c680a39',
            'CNI_ARGS': 'foo=bar',
            'CNI_IFNAME': 'eth0',
        }
        result = self.runner.run(env, m_fin, m_fout)
        m_post.assert_called_with(
            'http://127.0.0.1:%d/%s' % (self.port, path),
            json=mock.ANY, headers={'Connection': 'close'})
        return result

    def test_run_add(self, m_post):
        m_response = mock.Mock(status_code=202)
        m_response.json = mock.Mock(return_value=fake._fake_vif_dict())
        m_post.return_value = m_response
        result = self._test_run('ADD', 'addNetwork', m_post)
        self.assertEqual(0, result)

    def test_run_add_invalid(self, m_post):
        m_response = mock.Mock(status_code=400)
        m_response.json = mock.Mock()
        m_post.return_value = m_response
        result = self._test_run('ADD', 'addNetwork', m_post)
        self.assertEqual(1, result)
        m_response.json.assert_not_called()

    def test_run_del(self, m_post):
        m_post.return_value = mock.Mock(status_code=204)
        result = self._test_run('DEL', 'delNetwork', m_post)
        self.assertEqual(0, result)

    def test_run_del_invalid(self, m_post):
        m_post.return_value = mock.Mock(status_code=400)
        result = self._test_run('DEL', 'delNetwork', m_post)
        self.assertEqual(1, result)

    def test_run_socket_error(self, m_post):
        m_post.side_effect = requests.ConnectionError
        result = self._test_run('DEL', 'delNetwork', m_post)
        self.assertEqual(1, result)
