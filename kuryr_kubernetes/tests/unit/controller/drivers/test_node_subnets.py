# Copyright 2020 Red Hat, Inc.
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
from openstack.network.v2 import subnet as os_subnet
from oslo_config import cfg

from kuryr_kubernetes.controller.drivers import node_subnets
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base as test_base


class TestConfigNodesSubnetsDriver(test_base.TestCase):

    def test_get_nodes_subnets(self):
        subnets = ['subnet1', 'subnet2']
        cfg.CONF.set_override('worker_nodes_subnets', subnets,
                              group='pod_vif_nested')
        driver = node_subnets.ConfigNodesSubnets()

        self.assertEqual(subnets, driver.get_nodes_subnets())

    def test_get_nodes_subnets_alias(self):
        subnet = 'subnet1'
        cfg.CONF.set_override('worker_nodes_subnet', subnet,
                              group='pod_vif_nested')
        driver = node_subnets.ConfigNodesSubnets()

        self.assertEqual([subnet], driver.get_nodes_subnets())

    def test_get_project_not_set_raise(self):
        cfg.CONF.set_override('worker_nodes_subnets', None,
                              group='pod_vif_nested')
        driver = node_subnets.ConfigNodesSubnets()

        self.assertRaises(cfg.RequiredOptError, driver.get_nodes_subnets,
                          raise_on_empty=True)

    def test_get_project_not_set(self):
        cfg.CONF.set_override('worker_nodes_subnets', None,
                              group='pod_vif_nested')
        driver = node_subnets.ConfigNodesSubnets()

        self.assertEqual([], driver.get_nodes_subnets())

    def test_add_node(self):
        driver = node_subnets.ConfigNodesSubnets()
        self.assertFalse(driver.add_node('node'))

    def test_delete_node(self):
        driver = node_subnets.ConfigNodesSubnets()
        self.assertFalse(driver.delete_node('node'))


class TestOpenShiftNodesSubnetsDriver(test_base.TestCase):
    def setUp(self):
        super().setUp()
        self.machine = {
            "apiVersion": "machine.openshift.io/v1beta1",
            "kind": "Machine",
            "metadata": {
                "name": "foo-tv22d-master-2",
                "namespace": "openshift-machine-api",
            },
            "spec": {
                "metadata": {},
                "providerSpec": {
                    "value": {
                        "cloudName": "openstack",
                        "cloudsSecret": {
                            "name": "openstack-cloud-credentials",
                            "namespace": "openshift-machine-api"
                        },
                        "kind": "OpenstackProviderSpec",
                        "networks": [
                            {
                                "filter": {},
                                "subnets": [{
                                    "filter": {
                                        "name": "foo-tv22d-nodes",
                                        "tags": "openshiftClusterID=foo-tv22d"
                                    }}
                                ]
                            }
                        ],
                        "trunk": True
                    }
                }
            },
            "status": {}
        }
        cfg.CONF.set_override('worker_nodes_subnets', [],
                              group='pod_vif_nested')

    def test_get_nodes_subnets(self):
        subnets = ['subnet1', 'subnet2']
        driver = node_subnets.OpenShiftNodesSubnets()
        for subnet in subnets:
            driver.subnets.add(subnet)
        self.assertCountEqual(subnets, driver.get_nodes_subnets())

    def test_get_nodes_subnets_with_config(self):
        subnets = ['subnet1', 'subnet2']
        cfg.CONF.set_override('worker_nodes_subnets', ['subnet3', 'subnet2'],
                              group='pod_vif_nested')
        driver = node_subnets.OpenShiftNodesSubnets()
        for subnet in subnets:
            driver.subnets.add(subnet)
        self.assertCountEqual(['subnet1', 'subnet2', 'subnet3'],
                              driver.get_nodes_subnets())

    def test_get_nodes_subnets_not_raise(self):
        driver = node_subnets.OpenShiftNodesSubnets()
        self.assertEqual([], driver.get_nodes_subnets())

    def test_get_nodes_subnets_raise(self):
        driver = node_subnets.OpenShiftNodesSubnets()
        self.assertRaises(exceptions.ResourceNotReady,
                          driver.get_nodes_subnets, raise_on_empty=True)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.utils.get_subnet_id')
    def test_add_node(self, m_get_subnet_id, m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        m_get_subnet_id.return_value = 'foobar'
        self.assertTrue(driver.add_node(self.machine))
        m_get_subnet_id.assert_called_once_with(
            name='foo-tv22d-nodes', tags='openshiftClusterID=foo-tv22d')
        self.assertEqual(['foobar'], driver.get_nodes_subnets())

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.utils.get_subnet_id')
    def test_add_node_exists(self, m_get_subnet_id, m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        m_get_subnet_id.return_value = 'foobar'
        driver.subnets.add('foobar')
        self.assertFalse(driver.add_node(self.machine))
        m_get_subnet_id.assert_called_once_with(
            name='foo-tv22d-nodes', tags='openshiftClusterID=foo-tv22d')
        self.assertEqual(['foobar'], driver.get_nodes_subnets())

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.utils.get_subnet_id')
    def test_add_node_uuid(self, m_get_subnet_id, m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        net = self.machine['spec']['providerSpec']['value']['networks'][0]
        del net['subnets'][0]['filter']
        net['subnets'][0]['uuid'] = 'barfoo'
        self.assertTrue(driver.add_node(self.machine))
        m_get_subnet_id.assert_not_called()
        self.assertEqual(['barfoo'], driver.get_nodes_subnets())

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.utils.get_subnet_id')
    def test_add_node_cannot(self, m_get_subnet_id, m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        net = self.machine['spec']['providerSpec']['value']['networks'][0]
        del net['subnets']
        self.assertFalse(driver.add_node(self.machine))
        m_get_subnet_id.assert_not_called()
        self.assertEqual([], driver.get_nodes_subnets())

    @mock.patch('kuryr_kubernetes.utils.get_subnet_id')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_delete_node_cannot(self, m_get_k8s, m_get_subnet_id):
        m_k8s = mock.Mock()
        m_get_k8s.return_value = m_k8s
        driver = node_subnets.OpenShiftNodesSubnets()
        net = self.machine['spec']['providerSpec']['value']['networks'][0]
        del net['subnets']
        self.assertFalse(driver.delete_node(self.machine))
        m_get_subnet_id.assert_not_called()
        self.assertEqual([], driver.get_nodes_subnets())

    @mock.patch('kuryr_kubernetes.utils.get_subnet_id')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_delete_node(self,  m_get_k8s, m_get_subnet_id):
        m_k8s = mock.Mock()
        m_get_k8s.return_value = m_k8s
        m_k8s.get.return_value = {'items': []}

        driver = node_subnets.OpenShiftNodesSubnets()
        driver.subnets.add('foobar')
        m_get_subnet_id.return_value = 'foobar'
        self.assertTrue(driver.delete_node(self.machine))
        m_get_subnet_id.assert_called_once_with(
            name='foo-tv22d-nodes', tags='openshiftClusterID=foo-tv22d')
        self.assertEqual([], driver.get_nodes_subnets())

    @mock.patch('kuryr_kubernetes.utils.get_subnet_id')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_delete_node_still_exists(self,  m_get_k8s, m_get_subnet_id):
        m_k8s = mock.Mock()
        m_get_k8s.return_value = m_k8s
        m_k8s.get.return_value = {'items': [self.machine]}

        driver = node_subnets.OpenShiftNodesSubnets()
        driver.subnets.add('foobar')
        m_get_subnet_id.return_value = 'foobar'
        self.assertFalse(driver.delete_node(self.machine))
        m_get_subnet_id.assert_called_with(
            name='foo-tv22d-nodes', tags='openshiftClusterID=foo-tv22d')
        self.assertEqual(['foobar'], driver.get_nodes_subnets())

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_no_networks(self, m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        del self.machine['spec']['providerSpec']['value']['networks']

        self.assertIsNone(driver._get_subnet_from_machine(self.machine))

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.utils.get_subnet_id')
    def test_get_subnet_from_machine_networks_subnets(self, m_get_subnet_id,
                                                      m_get_k8s):
        subnetid = 'd467451b-ab28-4578-882f-347f0dff4c9a'
        m_get_subnet_id.return_value = subnetid
        driver = node_subnets.OpenShiftNodesSubnets()

        self.assertEqual(subnetid,
                         driver._get_subnet_from_machine(self.machine))

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_networks_wo_filters(self, m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        nets = self.machine['spec']['providerSpec']['value']['networks']
        nets[0]['subnets'] = [{'uuid': 'f8a458e5-c280-47b7-9c8a-dbd4ecd65545'}]
        self.machine['spec']['providerSpec']['value']['networks'] = nets

        result = driver._get_subnet_from_machine(self.machine)

        self.assertEqual(nets[0]['subnets'][0]['uuid'], result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test_get_subnet_from_machine_primary_subnet(self, m_get_net,
                                                    m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        psub = '622c5fd4-804c-40e8-95ab-ecd1565ac8e2'
        m_net = mock.Mock()
        m_net.find_subnet.return_value = os_subnet.Subnet(id=psub)
        m_get_net.return_value = m_net
        self.machine['spec']['providerSpec']['value']['primarySubnet'] = psub

        result = driver._get_subnet_from_machine(self.machine)

        self.assertEqual(psub, result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_ports(self, m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        subnet_id = '0530f763-899b-4acb-a2ca-deeedd760409'
        ports = [{'fixedIPs': [{'subnetID': subnet_id}]}]
        self.machine['spec']['providerSpec']['value']['ports'] = ports
        del self.machine['spec']['providerSpec']['value']['networks']

        result = driver._get_subnet_from_machine(self.machine)

        self.assertEqual(subnet_id, result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.utils.get_subnet_id')
    def test_get_subnet_from_machine_networks_and_ports(self, m_get_subnet_id,
                                                        m_get_k8s):
        """Test both: networks and ports presence, but no primarySubnet.

        Precedence would have networks over ports.
        """
        subnet_id = '7607a620-b706-478f-9481-7fdf11deeab2'
        m_get_subnet_id.return_value = subnet_id
        port_subnet_id = 'ec4c50ac-e3f6-426e-ad91-6ddc10b5c391'
        ports = [{'fixedIPs': [{'subnetID': port_subnet_id}]}]
        self.machine['spec']['providerSpec']['value']['ports'] = ports
        driver = node_subnets.OpenShiftNodesSubnets()

        result = driver._get_subnet_from_machine(self.machine)

        self.assertEqual(subnet_id, result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_empty_networks(self, m_get_k8s):
        """Test both: networks and ports presence, but no primarySubnet.

        Precedence would have networks over ports.
        """
        self.machine['spec']['providerSpec']['value']['networks'] = []
        driver = node_subnets.OpenShiftNodesSubnets()

        result = driver._get_subnet_from_machine(self.machine)

        self.assertIsNone(result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_empty_ports(self, m_get_k8s):
        """Test both: networks and ports presence, but no primarySubnet.

        Precedence would have networks over ports.
        """
        del self.machine['spec']['providerSpec']['value']['networks']
        self.machine['spec']['providerSpec']['value']['ports'] = []
        driver = node_subnets.OpenShiftNodesSubnets()

        result = driver._get_subnet_from_machine(self.machine)

        self.assertIsNone(result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_networks_no_trunk(self, m_get_k8s):
        del self.machine['spec']['providerSpec']['value']['trunk']
        driver = node_subnets.OpenShiftNodesSubnets()

        self.assertIsNone(driver._get_subnet_from_machine(self.machine))

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_ports_no_trunk(self, m_get_k8s):
        del self.machine['spec']['providerSpec']['value']['trunk']
        del self.machine['spec']['providerSpec']['value']['networks']
        subnet_id = '0530f763-899b-4acb-a2ca-deeedd760409'
        ports = [{'fixedIPs': [{'subnetID': subnet_id}]}]
        self.machine['spec']['providerSpec']['value']['ports'] = ports
        driver = node_subnets.OpenShiftNodesSubnets()

        result = driver._get_subnet_from_machine(self.machine)

        self.assertIsNone(result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_ports_no_trunk_one_with_trunk(self,
                                                                   m_get_k8s):
        del self.machine['spec']['providerSpec']['value']['trunk']
        del self.machine['spec']['providerSpec']['value']['networks']
        subnet_id = '0530f763-899b-4acb-a2ca-deeedd760409'
        ports = [{'fixedIPs': [{'subnetID': 'foo'}]},
                 {'fixedIPs': [{'subnetID': subnet_id}], 'trunk': True}]
        self.machine['spec']['providerSpec']['value']['ports'] = ports
        driver = node_subnets.OpenShiftNodesSubnets()

        result = driver._get_subnet_from_machine(self.machine)

        self.assertEqual(subnet_id, result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_ports_both_with_trunk(self, m_get_k8s):
        del self.machine['spec']['providerSpec']['value']['networks']
        subnet_id1 = '0530f763-899b-4acb-a2ca-deeedd760409'
        subnet_id2 = 'ccfe75a8-c15e-4504-9596-02e397362abf'
        ports = [{'fixedIPs': [{'subnetID': subnet_id1}], 'trunk': False},
                 {'fixedIPs': [{'subnetID': subnet_id2}], 'trunk': True}]
        self.machine['spec']['providerSpec']['value']['ports'] = ports
        driver = node_subnets.OpenShiftNodesSubnets()

        result = driver._get_subnet_from_machine(self.machine)

        self.assertEqual(subnet_id2, result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_get_subnet_from_machine_ports_both_wrong(self, m_get_k8s):
        del self.machine['spec']['providerSpec']['value']['networks']
        ports = [{'trunk': True},
                 {'fixedIPs': [{'foo': 'bar'}], 'trunk': True}]
        self.machine['spec']['providerSpec']['value']['ports'] = ports
        driver = node_subnets.OpenShiftNodesSubnets()

        result = driver._get_subnet_from_machine(self.machine)

        self.assertIsNone(result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test_get_subnet_from_machine_two_primary_subnet(self, m_get_net,
                                                        m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        sname = 'multiple subnets with the same name'
        m_net = mock.Mock()
        m_net.find_subnet.side_effect = os_exc.DuplicateResource
        m_get_net.return_value = m_net
        self.machine['spec']['providerSpec']['value']['primarySubnet'] = sname

        result = driver._get_subnet_from_machine(self.machine)

        self.assertIsNone(result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test_get_subnet_from_machine_single_named_primary_subnet(self,
                                                                 m_get_net,
                                                                 m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        sname = 'single named subnet'
        subnet_id = '9bcf85c8-1f15-4e3d-8e1e-0e2270ffd2b9'
        m_net = mock.Mock()
        m_net.find_subnet.return_value = os_subnet.Subnet(id=subnet_id)
        m_get_net.return_value = m_net
        self.machine['spec']['providerSpec']['value']['primarySubnet'] = sname

        result = driver._get_subnet_from_machine(self.machine)

        self.assertEqual(subnet_id, result)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test_get_subnet_from_machine_primary_subnet_exc(self, m_get_net,
                                                        m_get_k8s):
        driver = node_subnets.OpenShiftNodesSubnets()
        subnet = 'e621f2f5-38a4-4a9c-873f-1d447290939c'
        m_net = mock.Mock()
        m_net.find_subnet.side_effect = os_exc.SDKException
        m_get_net.return_value = m_net
        self.machine['spec']['providerSpec']['value']['primarySubnet'] = subnet

        self.assertRaises(exceptions.ResourceNotReady,
                          driver._get_subnet_from_machine, self.machine)
