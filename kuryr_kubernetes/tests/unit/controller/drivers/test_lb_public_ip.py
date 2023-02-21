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
from openstack.network.v2 import subnet as os_subnet
from unittest import mock

from oslo_config import cfg

from kuryr_kubernetes.controller.drivers import lb_public_ip\
    as d_lb_public_ip
from kuryr_kubernetes.controller.drivers import public_ip
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix

CONF = cfg.CONF


class TestFloatingIpServicePubIPDriverDriver(test_base.TestCase):

    def test_acquire_service_pub_ip_info_clusterip(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        project_id = mock.sentinel.project_id
        cur_service_pub_ip_info = None
        service = {'spec': {'type': 'ClusterIP'}}

        result = cls.acquire_service_pub_ip_info(m_driver, service, project_id,
                                                 cur_service_pub_ip_info)
        self.assertIsNone(result)

    def test_acquire_service_pub_ip_info_usr_specified_ip(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.4',
            port_id=None,
            id='a2a62ea7-e3bf-40df-8c09-aa0c29876a6b',
        )
        os_net.ips.return_value = (ip for ip in [fip])
        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = '1.2.3.4'
        CONF.set_override('external_svc_net',
                          '9767e1bd-40a7-4294-8e59-29dd77edb0e3',
                          group='neutron_defaults')

        expected_resp = {
            'ip_id': fip.id,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'user'
        }

        result = cls.acquire_service_pub_ip_info(m_driver, spec_type,
                                                 spec_lb_ip,  project_id)
        self.assertEqual(result, expected_resp)

    def test_acquire_service_pub_ip_info_user_specified_non_exist_fip(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            port_id=None,
        )
        os_net.ips.return_value = (ip for ip in [fip])

        project_id = mock.sentinel.project_id

        spec_type = 'LoadBalancer'
        spec_lb_ip = '1.2.3.4'

        result = cls.acquire_service_pub_ip_info(m_driver, spec_type,
                                                 spec_lb_ip,  project_id)
        self.assertIsNone(result)

    def test_acquire_service_pub_ip_info_user_specified_occupied_fip(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.4',
            port_id='ec29d641-fec4-4f67-928a-124a76b3a8e6',
        )
        os_net.ips.return_value = (ip for ip in [fip])

        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = '1.2.3.4'

        result = cls.acquire_service_pub_ip_info(m_driver, spec_type,
                                                 spec_lb_ip,  project_id)
        self.assertIsNone(result)

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_acquire_service_pub_ip_info_pool_net_not_defined(self, m_cfg):
        driver = d_lb_public_ip.FloatingIpServicePubIPDriver()
        public_net = ''
        m_cfg.neutron_defaults.external_svc_net = public_net
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.ips.return_value = (ip for ip in [])
        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = None

        result = driver.acquire_service_pub_ip_info(
            spec_type, spec_lb_ip, project_id)
        self.assertIsNone(result)

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_acquire_service_pub_ip_info_pool_subnet_is_none(self, m_cfg):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        public_net = mock.sentinel.public_subnet
        m_cfg.neutron_defaults.external_svc_net = public_net
        m_cfg.neutron_defaults.external_svc_subnet = None

        os_net.get_subnet.return_value = os_subnet.Subnet(
            network_id='ec29d641-fec4-4f67-928a-124a76b3a8e6',
        )
        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )
        os_net.create_ip.return_value = fip

        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = None

        expected_resp = {
            'ip_id': fip.id,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'pool'
        }

        result = cls.acquire_service_pub_ip_info(m_driver, spec_type,
                                                 spec_lb_ip,  project_id)
        self.assertEqual(result, expected_resp)

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_acquire_service_pub_ip_info_alloc_from_pool(self, m_cfg):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        m_cfg.neutron_defaults.external_svc_subnet = (mock.sentinel
                                                      .external_svc_subnet)

        os_net.get_subnet.return_value = os_subnet.Subnet(
            network_id='ec29d641-fec4-4f67-928a-124a76b3a8e6',
        )
        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )
        os_net.create_ip.return_value = fip

        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = None

        expected_resp = {
            'ip_id': fip.id,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'pool'
        }

        result = cls.acquire_service_pub_ip_info(m_driver, spec_type,
                                                 spec_lb_ip,  project_id)
        self.assertEqual(result, expected_resp)

    def test_release_pub_ip_empty_lb_ip_info(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        service_pub_ip_info = None

        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertIs(rc, True)

    def test_release_pub_ip_alloc_method_non_pool(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )

        service_pub_ip_info = {
            'ip_id': fip.id,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'kk'
        }

        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertIs(rc, True)

    def test_release_pub_ip_alloc_method_user(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )

        service_pub_ip_info = {
            'ip_id': fip.id,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'user'
        }

        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertIs(rc, True)

    def test_release_pub_ip_alloc_method_pool_neutron_exception(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.delete_ip.side_effect = os_exc.SDKException

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )

        service_pub_ip_info = {
            'ip_id': fip.id,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'pool'
        }
        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertIs(rc, False)

    def test_release_pub_ip_alloc_method_pool_neutron_succeeded(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        self.useFixture(k_fix.MockNetworkClient()).client

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )

        service_pub_ip_info = {
            'ip_id': fip.id,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'pool'
        }
        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertIs(rc, True)

    def test_associate_pub_ip_empty_params(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.update_floatingip.return_value = None

        service_pub_ip_info = None
        vip_port_id = None

        result = cls.associate_pub_ip(m_driver, service_pub_ip_info,
                                      vip_port_id)
        self.assertIsNone(result)

    def test_associate_lb_fip_id_not_exist(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.update_floatingip.return_value = None
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )
        service_pub_ip_info = (obj_lbaas
                               .LBaaSPubIp(ip_id=0,
                                           ip_addr=fip.floating_ip_address,
                                           alloc_method='pool'))
        service_pub_ip_info = {
            'ip_id': 0,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'pool'
        }

        vip_port_id = 'ec29d641-fec4-4f67-928a-124a76b3a777'

        result = cls.associate_pub_ip(m_driver, service_pub_ip_info,
                                      vip_port_id)
        self.assertIsNone(result)

    def test_associate_lb_fip_id_not_exist_neutron_exception(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.update_ip.side_effect = os_exc.SDKException

        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )

        service_pub_ip_info = {
            'ip_id': fip.id,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'pool'
        }
        vip_port_id = 'ec29d641-fec4-4f67-928a-124a76b3a777'

        self.assertRaises(os_exc.SDKException, cls.associate_pub_ip,
                          m_driver, service_pub_ip_info, vip_port_id)

    def test_disassociate_pub_ip_empty_param(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        self.useFixture(k_fix.MockNetworkClient()).client
        service_pub_ip_info = None

        result = cls.disassociate_pub_ip(m_driver, service_pub_ip_info)

        self.assertIsNone(result)

    def test_disassociate_pub_ip_fip_id_not_exist(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.update_floatingip.return_value = None
        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )
        service_pub_ip_info = {
            'ip_id': 0,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'pool'
        }

        result = cls.disassociate_pub_ip(m_driver, service_pub_ip_info)

        self.assertIsNone(result)

    def test_disassociate_pub_ip_neutron_exception(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        os_net.update_ip.side_effect = os_exc.SDKException
        fip = os_fip.FloatingIP(
            floating_ip_address='1.2.3.5',
            id='ec29d641-fec4-4f67-928a-124a76b3a888',
        )

        service_pub_ip_info = {
            'ip_id': fip.id,
            'ip_addr': fip.floating_ip_address,
            'alloc_method': 'pool'
        }

        self.assertRaises(os_exc.SDKException, cls.disassociate_pub_ip,
                          m_driver, service_pub_ip_info)
