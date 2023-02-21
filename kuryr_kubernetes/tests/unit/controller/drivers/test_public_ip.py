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

from openstack import exceptions as os_exc
from openstack.network.v2 import floating_ip as os_fip
from unittest import mock

from kuryr_kubernetes.controller.drivers import public_ip\
    as d_public_ip
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


class TestFipPubIpDriver(test_base.TestCase):
    def setUp(self):
        super(TestFipPubIpDriver, self).setUp()
        self.driver = d_public_ip.FipPubIpDriver()
        self.os_net = self.useFixture(k_fix.MockNetworkClient()).client

    def test_is_ip_available_none_param(self):
        fip_id = self.driver.is_ip_available(None)
        self.assertIsNone(fip_id)

    def test_is_ip_available_ip_not_exist(self):
        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.4',
            port_id=None,
            id='a2a62ea7-e3bf-40df-8c09-aa0c29876a6b',
        )
        self.os_net.ips.return_value = (ip for ip in [fip])

        fip_ip_addr = '1.1.1.1'
        fip_id = self.driver.is_ip_available(fip_ip_addr)
        self.assertIsNone(fip_id)

    def test_is_ip_available_empty_fip_list(self):
        self.os_net.ips.return_value = (ip for ip in [])

        fip_ip_addr = '1.1.1.1'
        fip_id = self.driver.is_ip_available(fip_ip_addr)
        self.assertIsNone(fip_id)

    def test_is_ip_available_occupied_fip(self):
        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.4',
            port_id='ec29d641-fec4-4f67-928a-124a76b3a8e6',
        )
        self.os_net.ips.return_value = (ip for ip in [fip])
        fip_ip_addr = '1.2.3.4'
        fip_id = self.driver.is_ip_available(fip_ip_addr)
        self.assertIsNone(fip_id)

    def test_is_ip_available_ip_exist_and_available(self):
        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.4',
            port_id=None,
            id='a2a62ea7-e3bf-40df-8c09-aa0c29876a6b',
        )
        self.os_net.ips.return_value = (ip for ip in [fip])

        fip_ip_addr = '1.2.3.4'
        fip_id = self.driver.is_ip_available(fip_ip_addr)
        self.assertEqual(fip_id, 'a2a62ea7-e3bf-40df-8c09-aa0c29876a6b')

    def test_allocate_ip_all_green(self):
        pub_net_id = mock.sentinel.pub_net_id
        pub_subnet_id = mock.sentinel.pub_subnet_id
        project_id = mock.sentinel.project_id
        description = mock.sentinel.description

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )
        self.os_net.create_ip.return_value = fip

        fip_id, fip_addr = self.driver.allocate_ip(pub_net_id, project_id,
                                                   pub_subnet_id, description)
        self.assertEqual(fip_id, fip.id)
        self.assertEqual(fip_addr, fip.floating_ip_address)

    def test_allocate_ip_neutron_exception(self):
        pub_net_id = mock.sentinel.pub_net_id
        pub_subnet_id = mock.sentinel.pub_subnet_id
        project_id = mock.sentinel.project_id
        description = mock.sentinel.description

        self.os_net.create_ip.side_effect = os_exc.SDKException

        self.assertRaises(os_exc.SDKException, self.driver.allocate_ip,
                          pub_net_id, project_id, pub_subnet_id, description)

    def test_free_ip_neutron_exception(self):
        res_id = mock.sentinel.res_id

        self.os_net.delete_ip.side_effect = os_exc.SDKException
        rc = self.driver.free_ip(res_id)
        self.assertIs(rc, False)

    def test_free_ip_succeeded(self):
        res_id = mock.sentinel.res_id

        rc = self.driver.free_ip(res_id)
        self.assertIs(rc, True)

    def test_associate_neutron_exception(self):
        res_id = mock.sentinel.res_id
        vip_port_id = mock.sentinel.vip_port_id

        uf = self.os_net.update_ip
        uf.side_effect = os_exc.SDKException
        self.assertRaises(os_exc.SDKException, self.driver.associate,
                          res_id, vip_port_id)

    def test_associate_conflict_correct(self):
        driver = d_public_ip.FipPubIpDriver()
        res_id = mock.sentinel.res_id
        vip_port_id = mock.sentinel.vip_port_id

        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.update_ip.side_effect = os_exc.ConflictException
        os_net.get_ip.return_value = os_fip.FloatingIP(
            id=res_id, port_id=vip_port_id,
        )
        self.assertIsNone(driver.associate(res_id, vip_port_id))

    def test_associate_conflict_incorrect(self):
        driver = d_public_ip.FipPubIpDriver()
        res_id = mock.sentinel.res_id
        vip_port_id = mock.sentinel.vip_port_id

        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.update_ip.side_effect = os_exc.ConflictException
        os_net.get_ip.return_value = os_fip.FloatingIP(
            id=res_id, port_id='foo',
        )
        self.assertRaises(os_exc.ConflictException, driver.associate, res_id,
                          vip_port_id)

    def test_associate_succeeded(self):
        res_id = mock.sentinel.res_id
        vip_port_id = mock.sentinel.vip_port_id

        retcode = self.driver.associate(res_id, vip_port_id)
        self.assertIsNone(retcode)

    def test_disassociate_neutron_exception(self):
        res_id = mock.sentinel.res_id

        uf = self.os_net.update_ip
        uf.side_effect = os_exc.SDKException
        self.assertRaises(os_exc.SDKException,
                          self.driver.disassociate, res_id)

    def test_disassociate_succeeded(self):
        res_id = mock.sentinel.res_id

        self.assertIsNone(self.driver.disassociate(res_id))
