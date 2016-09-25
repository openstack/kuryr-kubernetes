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

import mock

from kuryr_kubernetes.tests import base as test_base


class TestControllerCmd(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.controller.service.start')
    @mock.patch('eventlet.monkey_patch')
    def test_start(self, m_evmp, m_start):
        # NOTE(ivc): eventlet.monkey_patch is invoked during the module
        # import, so the controller cmd has to be imported locally to verify
        # that monkey_patch is called
        from kuryr_kubernetes.cmd.eventlet import controller

        controller.start()

        m_evmp.assert_called()
        m_start.assert_called()
