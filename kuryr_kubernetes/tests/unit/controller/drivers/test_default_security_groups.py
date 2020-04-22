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

from unittest import mock

from oslo_config import cfg

from kuryr_kubernetes.controller.drivers import default_security_groups
from kuryr_kubernetes.tests import base as test_base


class TestDefaultPodSecurityGroupsDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_security_groups(self, m_cfg):
        sg_list = [mock.sentinel.sg_id]
        project_id = mock.sentinel.project_id
        pod = mock.sentinel.pod
        m_cfg.neutron_defaults.pod_security_groups = sg_list
        driver = default_security_groups.DefaultPodSecurityGroupsDriver()

        ret = driver.get_security_groups(pod, project_id)

        self.assertEqual(sg_list, ret)
        self.assertIsNot(sg_list, ret)

    def test_get_security_groups_not_set(self):
        project_id = mock.sentinel.project_id
        pod = mock.sentinel.pod
        driver = default_security_groups.DefaultPodSecurityGroupsDriver()

        self.assertRaises(cfg.RequiredOptError, driver.get_security_groups,
                          pod, project_id)


class TestDefaultServiceSecurityGroupsDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_security_groups(self, m_cfg):
        sg_list = [mock.sentinel.sg_id]
        project_id = mock.sentinel.project_id
        service = mock.sentinel.service
        m_cfg.neutron_defaults.pod_security_groups = sg_list
        driver = default_security_groups.DefaultServiceSecurityGroupsDriver()

        ret = driver.get_security_groups(service, project_id)

        self.assertEqual(sg_list, ret)
        self.assertIsNot(sg_list, ret)

    def test_get_security_groups_not_set(self):
        project_id = mock.sentinel.project_id
        service = mock.sentinel.service
        driver = default_security_groups.DefaultServiceSecurityGroupsDriver()

        self.assertRaises(cfg.RequiredOptError, driver.get_security_groups,
                          service, project_id)
