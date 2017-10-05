# Copyright (c) 2017 RedHat, Inc.
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
from neutronclient.common import exceptions as n_exc

from kuryr_kubernetes.controller.drivers import public_ip\
    as d_public_ip
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


class TestFipPubIpDriver(test_base.TestCase):
    def test_is_ip_available_none_param(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        fip_ip_addr = None
        fip_id = cls.is_ip_available(m_driver, fip_ip_addr)

        self.assertIsNone(fip_id)

    def test_is_ip_available_empty_param(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        fip_ip_addr = None
        fip_id = cls.is_ip_available(m_driver, fip_ip_addr)

        self.assertIsNone(fip_id)

    def test_is_ip_available_ip_not_exist(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        floating_ip = {'floating_ip_address': '1.2.3.4', 'port_id': None,
                       'id': 'a2a62ea7-e3bf-40df-8c09-aa0c29876a6b'}
        neutron.list_floatingips.return_value = {'floatingips': [floating_ip]}

        fip_ip_addr = '1.1.1.1'
        fip_id = cls.is_ip_available(m_driver, fip_ip_addr)
        self.assertIsNone(fip_id)

    def test_is_ip_available_empty_fip_list(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        floating_ip = None
        neutron.list_floatingips.return_value = {'floatingips': [floating_ip]}

        fip_ip_addr = '1.1.1.1'
        fip_id = cls.is_ip_available(m_driver, fip_ip_addr)
        self.assertIsNone(fip_id)

    def test_is_ip_available_occupied_fip(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        floating_ip = {'floating_ip_address': '1.2.3.4',
                       'port_id': 'ec29d641-fec4-4f67-928a-124a76b3a8e6'}
        neutron.list_floatingips.return_value = {'floatingips': [floating_ip]}
        fip_ip_addr = '1.2.3.4'
        fip_id = cls.is_ip_available(m_driver, fip_ip_addr)
        self.assertIsNone(fip_id)

    def test_is_ip_available_ip_exist_and_available(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        floating_ip = {'floating_ip_address': '1.2.3.4', 'port_id': None,
                       'id': 'a2a62ea7-e3bf-40df-8c09-aa0c29876a6b'}
        neutron.list_floatingips.return_value = {'floatingips': [floating_ip]}

        fip_ip_addr = '1.2.3.4'
        fip_id = cls.is_ip_available(m_driver, fip_ip_addr)
        self.assertEqual(fip_id, 'a2a62ea7-e3bf-40df-8c09-aa0c29876a6b')

    def test_allocate_ip_all_green(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        pub_net_id = mock.sentinel.pub_net_id
        pub_subnet_id = mock.sentinel.pub_subnet_id
        project_id = mock.sentinel.project_id
        description = mock.sentinel.description

        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}
        neutron.create_floatingip.return_value = {'floatingip': floating_ip}

        fip_id, fip_addr = cls.allocate_ip(
            m_driver, pub_net_id, pub_subnet_id, project_id, description)
        self.assertEqual(fip_id, floating_ip['id'])
        self.assertEqual(fip_addr, floating_ip['floating_ip_address'])

    def test_allocate_ip_neutron_exception(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        pub_net_id = mock.sentinel.pub_net_id
        pub_subnet_id = mock.sentinel.pub_subnet_id
        project_id = mock.sentinel.project_id
        description = mock.sentinel.description

        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.create_floatingip.side_effect = n_exc.NeutronClientException

        self.assertRaises(
            n_exc.NeutronClientException, cls.allocate_ip,
            m_driver, pub_net_id, pub_subnet_id, project_id, description)

    def test_free_ip_neutron_exception(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        res_id = mock.sentinel.res_id

        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.delete_floatingip.side_effect = n_exc.NeutronClientException

        self.assertRaises(
            n_exc.NeutronClientException, cls.free_ip, m_driver, res_id)

    def test_free_ip_succeeded(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        res_id = mock.sentinel.res_id

        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.delete_floatingip.return_value = None
        try:
            cls.free_ip(m_driver, res_id)
        except Exception:
            self.fail("Encountered an unexpected exception.")

    def test_associate_neutron_exception(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        res_id = mock.sentinel.res_id
        vip_port_id = mock.sentinel.vip_port_id

        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.side_effect = n_exc.NeutronClientException
        retcode = cls.associate(m_driver, res_id, vip_port_id)
        self.assertIsNone(retcode)

    def test_associate_succeeded(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        res_id = mock.sentinel.res_id
        vip_port_id = mock.sentinel.vip_port_id

        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.return_value = None

        retcode = cls.associate(m_driver, res_id, vip_port_id)
        self.assertIsNone(retcode)

    def test_disassociate_neutron_exception(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        res_id = mock.sentinel.res_id

        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.side_effect = n_exc.NeutronClientException
        self.assertIsNone(cls.disassociate
                          (m_driver, res_id))

    def test_disassociate_succeeded(self):
        cls = d_public_ip.FipPubIpDriver
        m_driver = mock.Mock(spec=cls)
        res_id = mock.sentinel.res_id

        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.return_value = None

        self.assertIsNone(cls.disassociate
                          (m_driver, res_id))
