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

from kuryr_kubernetes.controller.drivers import default_subnet
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


class TestDefaultPodSubnetDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.controller.drivers'
                '.default_subnet._get_subnet')
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

    @mock.patch('kuryr_kubernetes.controller.drivers'
                '.default_subnet._get_subnet')
    def test_get_subnets_not_set(self, m_get_subnet):
        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        driver = default_subnet.DefaultPodSubnetDriver()

        self.assertRaises(cfg.RequiredOptError, driver.get_subnets,
                          pod, project_id)
        m_get_subnet.assert_not_called()


class TestDefaultServiceSubnetDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.controller.drivers'
                '.default_subnet._get_subnet')
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

    @mock.patch('kuryr_kubernetes.controller.drivers'
                '.default_subnet._get_subnet')
    def test_get_subnets_not_set(self, m_get_subnet):
        service = mock.sentinel.service
        project_id = mock.sentinel.project_id
        driver = default_subnet.DefaultPodSubnetDriver()
        self.assertRaises(cfg.RequiredOptError, driver.get_subnets,
                          service, project_id)
        m_get_subnet.assert_not_called()


class TestGetSubnet(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.os_vif_util.neutron_to_osvif_network')
    @mock.patch('kuryr_kubernetes.os_vif_util.neutron_to_osvif_subnet')
    def test_get_subnet(self, m_osv_subnet, m_osv_network):
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        subnet = mock.MagicMock()
        network = mock.MagicMock()
        subnet_id = mock.sentinel.subnet_id
        network_id = mock.sentinel.network_id

        neutron_subnet = {'network_id': network_id}
        neutron_network = mock.sentinel.neutron_network

        neutron.show_subnet.return_value = {'subnet': neutron_subnet}
        neutron.show_network.return_value = {'network': neutron_network}

        m_osv_subnet.return_value = subnet
        m_osv_network.return_value = network

        ret = default_subnet._get_subnet(subnet_id)

        self.assertEqual(network, ret)
        neutron.show_subnet.assert_called_once_with(subnet_id)
        neutron.show_network.assert_called_once_with(network_id)
        m_osv_subnet.assert_called_once_with(neutron_subnet)
        m_osv_network.assert_called_once_with(neutron_network)
        network.subnets.objects.append.assert_called_once_with(subnet)
