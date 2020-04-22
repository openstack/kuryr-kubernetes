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

from kuryr_kubernetes.tests import base as test_base


class TestDaemonCmd(test_base.TestCase):
    @mock.patch('kuryr_kubernetes.cni.daemon.service.start')
    def test_start(self, m_start):
        from kuryr_kubernetes.cmd import daemon  # To make it import a mock.
        daemon.start()

        m_start.assert_called()
