# Copyright (C) 2020 Intel Corporation
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

import ddt

from kuryr_kubernetes.controller.drivers import nested_dpdk_vif
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix

from openstack import exceptions as o_exc


@ddt.ddt
class TestNestedDpdkVIFDriver(test_base.TestCase):

    @mock.patch(
        'kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif_dpdk')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_network_id')
    def test_request_vif(self, m_get_network_id, m_to_vif):
        cls = nested_dpdk_vif.NestedDpdkPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        compute = self.useFixture(k_fix.MockComputeClient()).client

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = mock.sentinel.security_groups
        vm_id = mock.sentinel.parent_port_id
        net_id = mock.sentinel.net_id
        port_id = mock.sentinel.port_id
        port = mock.sentinel.port

        parent_port = mock.MagicMock()
        vif = mock.Mock()
        result = mock.Mock()

        parent_port.device_id = vm_id
        result.port_id = port_id
        compute.create_server_interface.return_value = result
        m_to_vif.return_value = vif
        m_driver._get_parent_port.return_value = parent_port
        m_get_network_id.return_value = net_id
        os_net.get_port.return_value = port

        self.assertEqual(vif, cls.request_vif(m_driver, pod, project_id,
                                              subnets, security_groups))

        m_driver._get_parent_port.assert_called_once_with(pod)
        m_get_network_id.assert_called_once_with(subnets)
        compute.create_server_interface.assert_called_once_with(
            vm_id, net_id=net_id)
        os_net.get_port.assert_called_once_with(result.port_id)
        m_to_vif.assert_called_once_with(port, subnets, pod)

    @mock.patch(
        'kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif_dpdk')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_network_id')
    def test_request_vif_parent_not_found(self, m_get_network_id, m_to_vif):
        cls = nested_dpdk_vif.NestedDpdkPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        compute = self.useFixture(k_fix.MockComputeClient()).client

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = mock.sentinel.security_groups
        vm_id = mock.sentinel.parent_port_id
        net_id = mock.sentinel.net_id
        port_id = mock.sentinel.port_id
        port = mock.sentinel.port

        parent_port = mock.MagicMock()
        vif = mock.Mock()
        result = mock.Mock()

        parent_port.__getitem__.return_value = vm_id
        result.port_id = port_id
        compute.create_server_interface.return_value = result
        m_to_vif.return_value = vif
        m_driver._get_parent_port.side_effect = \
            o_exc.SDKException
        m_get_network_id.return_value = net_id
        os_net.get_port.return_value = port

        self.assertRaises(o_exc.SDKException, cls.request_vif,
                          m_driver, pod, project_id, subnets, security_groups)

        m_driver._get_parent_port.assert_called_once_with(pod)
        m_get_network_id.assert_not_called()
        compute.create_server_interface.assert_not_called()
        os_net.get_port.assert_not_called()
        m_to_vif.assert_not_called()

    @mock.patch(
        'kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif_dpdk')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_network_id')
    def test_request_vif_attach_failed(self, m_get_network_id, m_to_vif):
        cls = nested_dpdk_vif.NestedDpdkPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        compute = self.useFixture(k_fix.MockComputeClient()).client

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = mock.sentinel.security_groups
        vm_id = mock.sentinel.parent_port_id
        net_id = mock.sentinel.net_id
        port_id = mock.sentinel.port_id
        port = mock.sentinel.port

        parent_port = mock.MagicMock()
        vif = mock.Mock()
        result = mock.Mock()

        parent_port.device_id = vm_id
        result.port_id = port_id
        m_to_vif.return_value = vif
        m_driver._get_parent_port.return_value = parent_port
        m_get_network_id.return_value = net_id
        os_net.get_port.return_value = port
        compute.create_server_interface.side_effect = o_exc.SDKException

        self.assertRaises(o_exc.SDKException, cls.request_vif,
                          m_driver, pod, project_id, subnets, security_groups)

        m_driver._get_parent_port.assert_called_once_with(pod)
        m_get_network_id.assert_called_once_with(subnets)
        compute.create_server_interface.assert_called_once_with(
            vm_id, net_id=net_id)
        os_net.get_port.assert_not_called()
        m_to_vif.assert_not_called()

    def test_release_vif(self):
        cls = nested_dpdk_vif.NestedDpdkPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        compute = self.useFixture(k_fix.MockComputeClient()).client

        port_id = mock.sentinel.port_id
        pod = mock.sentinel.pod
        vif = mock.Mock()
        vif.id = port_id

        vm_id = mock.sentinel.vm_id
        vm_port = mock.MagicMock()
        vm_port.device_id = vm_id

        m_driver._get_parent_port.return_value = vm_port

        cls.release_vif(m_driver, pod, vif)

        m_driver._get_parent_port.assert_called_once_with(pod)
        compute.delete_server_interface.assert_called_once_with(
            vif.id, server=vm_id)

    def test_release_parent_not_found(self):
        cls = nested_dpdk_vif.NestedDpdkPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        compute = self.useFixture(k_fix.MockComputeClient()).client

        pod = mock.sentinel.pod
        vif = mock.Mock()
        vif.id = mock.sentinel.vif_id

        vm_id = mock.sentinel.parent_port_id
        parent_port = mock.MagicMock()
        parent_port.__getitem__.return_value = vm_id

        m_driver._get_parent_port.side_effect = \
            o_exc.SDKException

        self.assertRaises(o_exc.SDKException, cls.release_vif,
                          m_driver, pod, vif)

        m_driver._get_parent_port.assert_called_once_with(pod)
        compute.delete_server_interface.assert_not_called()

    def test_release_detach_failed(self):
        cls = nested_dpdk_vif.NestedDpdkPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        compute = self.useFixture(k_fix.MockComputeClient()).client

        pod = mock.sentinel.pod
        vif = mock.Mock()
        vif.id = mock.sentinel.vif_id

        vm_id = mock.sentinel.parent_port_id
        parent_port = mock.MagicMock()
        parent_port.device_id = vm_id

        compute.delete_server_interface.side_effect = o_exc.SDKException

        m_driver._get_parent_port.return_value = parent_port

        self.assertRaises(o_exc.SDKException, cls.release_vif,
                          m_driver, pod, vif)

        m_driver._get_parent_port.assert_called_once_with(pod)
        compute.delete_server_interface.assert_called_once_with(
            vif.id, server=vm_id)

    @ddt.data((False), (True))
    def test_activate_vif(self, active_value):
        cls = nested_dpdk_vif.NestedDpdkPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        vif = mock.Mock()
        vif.active = active_value

        cls.activate_vif(m_driver, vif)

        self.assertEqual(vif.active, True)
