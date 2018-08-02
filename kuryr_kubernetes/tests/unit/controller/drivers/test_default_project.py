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
        self.assertRaises(cfg.RequiredOptError, driver.get_project, pod)


class TestDefaultServiceProjectDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_project(self, m_cfg):
        project_id = mock.sentinel.project_id
        service = mock.sentinel.service
        m_cfg.neutron_defaults.project = project_id
        driver = default_project.DefaultServiceProjectDriver()

        self.assertEqual(project_id, driver.get_project(service))

    def test_get_project_not_set(self):
        service = mock.sentinel.service
        driver = default_project.DefaultServiceProjectDriver()
        self.assertRaises(cfg.RequiredOptError, driver.get_project, service)


class TestDefaultNamespaceProjectDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_project(self, m_cfg):
        project_id = mock.sentinel.project_id
        namespace = mock.sentinel.namespace
        m_cfg.neutron_defaults.project = project_id
        driver = default_project.DefaultNamespaceProjectDriver()

        self.assertEqual(project_id, driver.get_project(namespace))

    def test_get_project_not_set(self):
        namespace = mock.sentinel.namespace
        driver = default_project.DefaultNamespaceProjectDriver()
        self.assertRaises(cfg.RequiredOptError, driver.get_project, namespace)


class TestDefaultNetworkPolicyProjectDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_project(self, m_cfg):
        project_id = mock.sentinel.project_id
        policy = mock.sentinel.policy
        m_cfg.neutron_defaults.project = project_id
        driver = default_project.DefaultNetworkPolicyProjectDriver()

        self.assertEqual(project_id, driver.get_project(policy))

    def test_get_project_not_set(self):
        policy = mock.sentinel.policy
        driver = default_project.DefaultNamespaceProjectDriver()
        self.assertRaises(cfg.RequiredOptError, driver.get_project, policy)
