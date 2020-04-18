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

from kuryr_kubernetes.controller.drivers import default_subnet
from kuryr_kubernetes.tests import base as test_base


class TestDefaultPodSubnetDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_subnets(self, m_cfg, m_get_subnet):
        subnet_id = mock.sentinel.subnet_id
        subnet = mock.sentinel.subnet
        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        m_cfg.neutron_defaults.pod_subnet = subnet_id
        m_get_subnet.return_value = subnet
        driver = default_subnet.DefaultPodSubnetDriver()

        subnets = driver.get_subnets(pod, project_id)

        self.assertEqual({subnet_id: subnet}, subnets)
        m_get_subnet.assert_called_once_with(subnet_id)

    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    def test_get_subnets_not_set(self, m_get_subnet):
        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        driver = default_subnet.DefaultPodSubnetDriver()

        self.assertRaises(cfg.RequiredOptError, driver.get_subnets,
                          pod, project_id)
        m_get_subnet.assert_not_called()


class TestDefaultServiceSubnetDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_subnets(self, m_cfg, m_get_subnet):
        subnet_id = mock.sentinel.subnet_id
        subnet = mock.sentinel.subnet
        service = mock.sentinel.service
        project_id = mock.sentinel.project_id
        m_cfg.neutron_defaults.service_subnet = subnet_id
        m_get_subnet.return_value = subnet
        driver = default_subnet.DefaultServiceSubnetDriver()

        subnets = driver.get_subnets(service, project_id)

        self.assertEqual({subnet_id: subnet}, subnets)
        m_get_subnet.assert_called_once_with(subnet_id)

    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    def test_get_subnets_not_set(self, m_get_subnet):
        service = mock.sentinel.service
        project_id = mock.sentinel.project_id
        driver = default_subnet.DefaultPodSubnetDriver()
        self.assertRaises(cfg.RequiredOptError, driver.get_subnets,
                          service, project_id)
        m_get_subnet.assert_not_called()
