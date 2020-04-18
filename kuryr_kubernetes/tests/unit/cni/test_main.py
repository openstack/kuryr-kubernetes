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

from unittest import mock

from kuryr_kubernetes.cni import main
from kuryr_kubernetes.tests import base as test_base


class TestCNIMain(test_base.TestCase):
    @mock.patch('kuryr_kubernetes.cni.main.jsonutils.load')
    @mock.patch('sys.exit')
    @mock.patch('sys.stdin')
    @mock.patch('kuryr_kubernetes.cni.utils.CNIConfig')
    @mock.patch('kuryr_kubernetes.cni.api')
    @mock.patch('kuryr_kubernetes.config.init')
    @mock.patch('kuryr_kubernetes.config.setup_logging')
    @mock.patch('kuryr_kubernetes.cni.api.CNIDaemonizedRunner')
    def test_daemonized_run(self, m_cni_dr, m_setup_logging, m_config_init,
                            m_api, m_conf, m_sys, m_sysexit, m_json):
        m_conf.debug = mock.Mock()
        m_conf.debug.return_value = True
        m_cni_dr.return_value = mock.MagicMock()
        m_cni_daemon = m_cni_dr.return_value

        main.run()

        m_config_init.assert_called()
        m_setup_logging.assert_called()
        m_cni_daemon.run.assert_called()
        m_sysexit.assert_called()
