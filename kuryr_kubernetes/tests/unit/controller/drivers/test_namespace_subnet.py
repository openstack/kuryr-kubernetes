# Copyright (c) 2018 Red Hat, Inc.
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

from openstack import exceptions as os_exc
from openstack.network.v2 import network as os_network
from openstack.network.v2 import subnet as os_subnet
from oslo_config import cfg as oslo_cfg

from kuryr_kubernetes.controller.drivers import namespace_subnet as subnet_drv
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


def get_pod_obj():
    return {
        'status': {
            'qosClass': 'BestEffort',
            'hostIP': '192.168.1.2',
        },
        'kind': 'Pod',
        'spec': {
            'schedulerName': 'default-scheduler',
            'containers': [{
                'name': 'busybox',
                'image': 'busybox',
                'resources': {}
            }],
            'nodeName': 'kuryr-devstack'
        },
        'metadata': {
            'name': 'busybox-sleep1',
            'namespace': 'default',
            'resourceVersion': '53808',
            'uid': '452176db-4a85-11e7-80bd-fa163e29dbbb',
            'annotations': {
                'openstack.org/kuryr-vif': {}
            }
        }}


class TestNamespacePodSubnetDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    def test_get_subnets(self, m_get_subnet):
        pod = get_pod_obj()
        pod_namespace = pod['metadata']['namespace']
        subnet_id = mock.sentinel.subnet_id
        subnet = mock.sentinel.subnet

        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        m_driver._get_namespace_subnet_id.return_value = subnet_id
        m_get_subnet.return_value = subnet

        subnets = cls.get_namespace_subnet(m_driver, pod_namespace)

        self.assertEqual({subnet_id: subnet}, subnets)
        m_driver._get_namespace_subnet_id.assert_called_once_with(
            pod_namespace)
        m_get_subnet.assert_called_once_with(subnet_id)

    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    def test_get_subnets_namespace_not_ready(self, m_get_subnet):
        pod = get_pod_obj()
        pod_namespace = pod['metadata']['namespace']

        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        m_driver._get_namespace_subnet_id.side_effect = (
            k_exc.ResourceNotReady(pod_namespace))

        self.assertRaises(k_exc.ResourceNotReady, cls.get_namespace_subnet,
                          m_driver, pod_namespace)

        m_driver._get_namespace_subnet_id.assert_called_once_with(
            pod_namespace)
        m_get_subnet.assert_not_called()

    def test__get_namespace_subnet_id(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        namespace = mock.sentinel.namespace
        subnet_id = mock.sentinel.subnet_id
        crd = {
            'status': {
                'subnetId': subnet_id
            }
        }

        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        kubernetes.get.return_value = crd

        subnet_id_resp = cls._get_namespace_subnet_id(m_driver, namespace)
        kubernetes.get.assert_called()
        self.assertEqual(subnet_id, subnet_id_resp)

    def test__get_namespace_subnet_id_get_crd_exception(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        namespace = mock.sentinel.namespace

        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        kubernetes.get.side_effect = k_exc.K8sClientException

        self.assertRaises(k_exc.K8sClientException,
                          cls._get_namespace_subnet_id, m_driver, namespace)
        kubernetes.get.assert_called()

    def test_delete_namespace_subnet(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        net_id = mock.sentinel.net_id
        subnet_id = mock.sentinel.subnet_id
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.ports.return_value = []
        os_net.remove_interface_from_router.return_value = {}

        cls._delete_namespace_network_resources(m_driver, subnet_id, net_id)

        os_net.remove_interface_from_router.assert_called_once()
        os_net.delete_network.assert_called_once_with(net_id)

    def test_delete_namespace_subnet_openstacksdk_error(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        net_id = mock.sentinel.net_id
        subnet_id = mock.sentinel.subnet_id
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.delete_network.side_effect = os_exc.ConflictException
        os_net.ports.return_value = []
        os_net.remove_interface_from_router.return_value = {}

        self.assertRaises(k_exc.ResourceNotReady,
                          cls._delete_namespace_network_resources, m_driver,
                          subnet_id, net_id)

        os_net.remove_interface_from_router.assert_called_once()
        os_net.delete_network.assert_called_once_with(net_id)
        os_net.ports.assert_called_with(network_id=net_id)

    def test_create_network(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        ns_uid = 'e65542a5-7e82-4b59-b3c5-c04b485d19eb'
        namespace = {'metadata': {'name': 'test', 'uid': ns_uid}}
        project_id = mock.sentinel.project_id
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.networks.return_value = iter([])
        net = os_network.Network(id=mock.sentinel.net)
        os_net.create_network.return_value = net

        net_id_resp = cls.create_network(m_driver, namespace, project_id)

        self.assertEqual(net_id_resp, net['id'])
        os_net.create_network.assert_called_once()
        os_net.networks.assert_called_once()

    def test_create_network_existing(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        ns_uid = '4f7ea026-3ae4-4baa-84df-1942977fe1be'
        namespace = {'metadata': {'name': 'test', 'uid': ns_uid}}
        project_id = mock.sentinel.project_id
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        net = os_network.Network(
            id=mock.sentinel.net,
            description=ns_uid,
            name='test',
        )
        os_net.networks.return_value = iter([net])

        net_id_resp = cls.create_network(m_driver, namespace, project_id)

        self.assertEqual(net_id_resp, net['id'])
        os_net.create_network.assert_not_called()
        os_net.networks.assert_called_once()

    def test_create_subnet(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        ns_uid = '95e2a3c5-f723-4936-b598-cf3a59861bcf'
        namespace = {'metadata': {'name': 'test', 'uid': ns_uid}}
        project_id = mock.sentinel.project_id
        net_id = mock.sentinel.net_id
        subnet = os_subnet.Subnet(
            id=mock.sentinel.subnet,
            cidr=mock.sentinel.cidr,
        )
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.subnets.return_value = iter([])
        os_net.create_subnet.return_value = subnet

        subnet_id, subnet_cidr = cls.create_subnet(m_driver, namespace,
                                                   project_id, net_id)

        self.assertEqual(subnet_id, subnet['id'])
        self.assertEqual(subnet_cidr, subnet['cidr'])
        os_net.create_subnet.assert_called_once()
        os_net.subnets.assert_called_once()

    def test_create_subnet_existing(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        ns_uid = '7f3a59b4-dd81-490d-9904-8294a6c93326'
        namespace = {'metadata': {'name': 'test', 'uid': ns_uid}}
        project_id = mock.sentinel.project_id
        net_id = mock.sentinel.net_id
        subnet = os_subnet.Subnet(
            id=mock.sentinel.subnet,
            cidr=mock.sentinel.cidr,
        )
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.subnets.return_value = iter([subnet])

        subnet_id, subnet_cidr = cls.create_subnet(m_driver, namespace,
                                                   project_id, net_id)

        self.assertEqual(subnet_id, subnet['id'])
        self.assertEqual(subnet_cidr, subnet['cidr'])
        os_net.create_subnet.assert_not_called()
        os_net.subnets.assert_called_once()

    def test_add_subnet_to_router(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        subnet_id = mock.sentinel.subnet_id
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.add_interface_to_router.return_value = {}
        router_id = 'router1'
        oslo_cfg.CONF.set_override('pod_router',
                                   router_id,
                                   group='namespace_subnet')

        router_id_resp = cls.add_subnet_to_router(m_driver, subnet_id)
        self.assertEqual(router_id_resp, router_id)
        os_net.add_interface_to_router.assert_called_once()

    def test_add_subnet_to_router_already_connected(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        subnet_id = mock.sentinel.subnet_id
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.add_interface_to_router.side_effect = (
            os_exc.BadRequestException)
        router_id = 'router1'
        oslo_cfg.CONF.set_override('pod_router',
                                   router_id,
                                   group='namespace_subnet')

        router_id_resp = cls.add_subnet_to_router(m_driver, subnet_id)
        self.assertEqual(router_id_resp, router_id)
        os_net.add_interface_to_router.assert_called_once()

    def test_add_subnet_to_router_exception(self):
        cls = subnet_drv.NamespacePodSubnetDriver
        m_driver = mock.MagicMock(spec=cls)

        subnet_id = mock.sentinel.subnet_id
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.add_interface_to_router.side_effect = (
            os_exc.SDKException)
        router_id = 'router1'
        oslo_cfg.CONF.set_override('pod_router',
                                   router_id,
                                   group='namespace_subnet')

        self.assertRaises(os_exc.SDKException,
                          cls.add_subnet_to_router, m_driver, subnet_id)
        os_net.add_interface_to_router.assert_called_once()
