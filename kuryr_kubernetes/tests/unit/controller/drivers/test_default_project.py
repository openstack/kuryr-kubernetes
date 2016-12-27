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

from oslo_config import cfg

from kuryr_kubernetes.controller.drivers import default_project
from kuryr_kubernetes.tests import base as test_base


class TestDefaultPodProjectDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_project(self, m_cfg):
        project_id = mock.sentinel.project_id
        pod = mock.sentinel.pod
        m_cfg.neutron_defaults.project = project_id
        driver = default_project.DefaultPodProjectDriver()

        self.assertEqual(project_id, driver.get_project(pod))

    def test_get_project_not_set(self):
        pod = mock.sentinel.pod
        driver = default_project.DefaultPodProjectDriver()
        msg = "value required for option project in group \[neutron_defaults\]"
        self.assertRaisesRegex(cfg.RequiredOptError, msg,
                               driver.get_project, pod)
