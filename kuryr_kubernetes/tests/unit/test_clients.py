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

from openstack import exceptions as os_exc
from openstack.network.v2 import port as os_port

from kuryr_kubernetes import clients
from kuryr_kubernetes.tests import base as test_base


class TestK8sClient(test_base.TestCase):

    @mock.patch('openstack.connection.Connection')
    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch('kuryr_kubernetes.k8s_client.K8sClient')
    def test_setup_clients(self, m_k8s, m_cfg, m_openstack):
        k8s_api_root = 'http://127.0.0.1:1234'

        openstacksdk_mock = mock.Mock()
        openstacksdk_mock.load_balancer = mock.Mock()
        openstacksdk_mock.network = mock.Mock()
        openstacksdk_mock.compute = mock.Mock()
        k8s_dummy = object()

        m_cfg.kubernetes.api_root = k8s_api_root
        m_k8s.return_value = k8s_dummy
        m_openstack.return_value = openstacksdk_mock

        clients.setup_clients()

        m_k8s.assert_called_with(k8s_api_root)
        self.assertIs(k8s_dummy, clients.get_kubernetes_client())
        self.assertIs(openstacksdk_mock.load_balancer,
                      clients.get_loadbalancer_client())
        self.assertIs(openstacksdk_mock.network,
                      clients.get_network_client())
        self.assertIs(openstacksdk_mock.compute,
                      clients.get_compute_client())


class TestOpenStackSDKHack(test_base.TestCase):

    def test_create_ports_incorrect_payload(self):
        m_osdk = mock.Mock()

        self.assertRaises(KeyError, clients._create_ports, m_osdk, {})

    def test_create_no_ports(self):
        m_response = mock.Mock()
        m_response.json.return_value = {'ports': []}
        m_post = mock.Mock()
        m_post.return_value = m_response
        m_osdk = mock.Mock()
        m_osdk.post = m_post

        payload = {'ports': []}

        clients._create_ports(m_osdk, payload)
        m_post.assert_called_once_with(os_port.Port.base_path, json=payload)

    def test_create_ports(self):
        m_response = mock.Mock()
        m_response.json.return_value = {'ports': []}
        m_post = mock.Mock()
        m_post.return_value = m_response
        m_osdk = mock.Mock()
        m_osdk.post = m_post

        payload = {'ports': [{'admin_state_up': True,
                              'allowed_address_pairs': [{}],
                              'binding_host_id': 'binding-host-id-1',
                              'binding_profile': {},
                              'binding_vif_details': {},
                              'binding_vif_type': 'ovs',
                              'binding_vnic_type': 'normal',
                              'device_id': 'device-id-1',
                              'device_owner': 'compute:nova',
                              'dns_assignment': [{}],
                              'dns_name': 'dns-name-1',
                              'extra_dhcp_opts': [{}],
                              'fixed_ips': [{'subnet_id': 'subnet-id-1',
                                             'ip_address': '10.10.10.01'}],
                              'id': 'port-id-1',
                              'mac_address': 'de:ad:be:ef:de:ad',
                              'name': 'port-name-',
                              'network_id': 'network-id-1',
                              'port_security_enabled': True,
                              'security_groups': [],
                              'status': 'ACTIVE',
                              'tenant_id': 'project-id-'}]}

        expected = {'ports': [{'admin_state_up': True,
                               'allowed_address_pairs': [{}],
                               'binding:host_id': 'binding-host-id-1',
                               'binding:profile': {},
                               'binding:vif_details': {},
                               'binding:vif_type': 'ovs',
                               'binding:vnic_type': 'normal',
                               'device_id': 'device-id-1',
                               'device_owner': 'compute:nova',
                               'dns_assignment': [{}],
                               'dns_name': 'dns-name-1',
                               'extra_dhcp_opts': [{}],
                               'fixed_ips': [{'subnet_id': 'subnet-id-1',
                                              'ip_address': '10.10.10.01'}],
                               'id': 'port-id-1',
                               'mac_address': 'de:ad:be:ef:de:ad',
                               'name': 'port-name-',
                               'network_id': 'network-id-1',
                               'port_security_enabled': True,
                               'security_groups': [],
                               'status': 'ACTIVE',
                               'tenant_id': 'project-id-'}]}

        clients._create_ports(m_osdk, payload)
        m_post.assert_called_once_with(os_port.Port.base_path, json=expected)

    def test_create_ports_out_of_ports(self):
        """Simulate error response from OpenStack SDK"""
        m_response = mock.Mock()
        m_response.text = ('{"NeutronError": {"type": "OverQuota", "message": '
                           '"Quota exceeded for resources: [\'port\'].", '
                           '"detail": ""}}')
        m_response.ok = False
        m_post = mock.Mock()
        m_post.return_value = m_response
        m_osdk = mock.Mock()
        m_osdk.post = m_post

        payload = {'ports': []}

        try:
            clients._create_ports(m_osdk, payload)
        except os_exc.SDKException as ex:
            # no additional params passed to the exception class
            self.assertIsNone(ex.extra_data)
            # no formatting placeholders in message
            self.assertNotIn('%s', ex.message)

        m_post.assert_called_once_with(os_port.Port.base_path, json=payload)
