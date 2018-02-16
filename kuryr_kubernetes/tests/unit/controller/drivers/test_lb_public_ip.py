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

from kuryr_kubernetes.controller.drivers import lb_public_ip\
    as d_lb_public_ip
from kuryr_kubernetes.controller.drivers import public_ip
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix
from oslo_config import cfg


class TestFloatingIpServicePubIPDriverDriver(test_base.TestCase):
    def test_acquire_service_pub_ip_info_clusterip(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        project_id = mock.sentinel.project_id
        cur_service_pub_ip_info = None
        service = {'spec': {'type': 'ClusterIP'}}

        self.assertIsNone(cls.acquire_service_pub_ip_info
                          (m_driver, service, project_id,
                           cur_service_pub_ip_info))

    def test_acquire_service_pub_ip_info_usr_specified_ip(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        floating_ip = {'floating_ip_address': '1.2.3.4', 'port_id': None,
                       'id': 'a2a62ea7-e3bf-40df-8c09-aa0c29876a6b'}
        neutron.list_floatingips.return_value = {'floatingips': [floating_ip]}
        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = '1.2.3.4'

        expected_resp = \
            obj_lbaas.LBaaSPubIp(ip_id=floating_ip['id'],
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='user')

        self.assertEqual(expected_resp, cls.acquire_service_pub_ip_info
                         (m_driver, spec_type, spec_lb_ip,  project_id))

    def test_acquire_service_pub_ip_info_user_specified_non_exist_fip(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'port_id': None}
        neutron.list_floatingips.return_value = {'floatingips': [floating_ip]}

        project_id = mock.sentinel.project_id

        spec_type = 'LoadBalancer'
        spec_lb_ip = '1.2.3.4'

        self.assertIsNone(cls.acquire_service_pub_ip_info
                          (m_driver, spec_type,
                           spec_lb_ip,  project_id))

    def test_acquire_service_pub_ip_info_user_specified_occupied_fip(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        floating_ip = {'floating_ip_address': '1.2.3.4',
                       'port_id': 'ec29d641-fec4-4f67-928a-124a76b3a8e6'}
        neutron.list_floatingips.return_value = {'floatingips': [floating_ip]}

        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = '1.2.3.4'

        self.assertIsNone(cls.acquire_service_pub_ip_info
                          (m_driver, spec_type,
                           spec_lb_ip,  project_id))

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_acquire_service_pub_ip_info_pool_net_not_defined(self, m_cfg):
        driver = d_lb_public_ip.FloatingIpServicePubIPDriver()
        public_net = ''
        m_cfg.neutron_defaults.external_svc_net = public_net
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.list_floatingips.return_value = {}
        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = None

        self.assertRaises(
            cfg.RequiredOptError,
            driver.acquire_service_pub_ip_info,
            spec_type, spec_lb_ip, project_id)

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_acquire_service_pub_ip_info_pool_subnet_is_none(self, m_cfg):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        public_net = mock.sentinel.public_subnet
        m_cfg.neutron_defaults.external_svc_net = public_net
        m_cfg.neutron_defaults.external_svc_subnet = None

        neutron.show_subnet.return_value =\
            {'subnet': {'network_id': 'ec29d641-fec4-4f67-928a-124a76b3a8e6'}}
        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}
        neutron.create_floatingip.return_value = {'floatingip': floating_ip}

        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = None

        expected_resp = \
            obj_lbaas.LBaaSPubIp(ip_id=floating_ip['id'],
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='pool')

        self.assertEqual(expected_resp, cls.acquire_service_pub_ip_info
                         (m_driver, spec_type, spec_lb_ip,  project_id))

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_acquire_service_pub_ip_info_alloc_from_pool(self, m_cfg):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        m_cfg.neutron_defaults.external_svc_subnet =\
            mock.sentinel.external_svc_subnet

        neutron.show_subnet.return_value =\
            {'subnet': {'network_id': 'ec29d641-fec4-4f67-928a-124a76b3a8e6'}}
        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}
        neutron.create_floatingip.return_value = {'floatingip': floating_ip}

        project_id = mock.sentinel.project_id
        spec_type = 'LoadBalancer'
        spec_lb_ip = None

        expected_resp = \
            obj_lbaas.LBaaSPubIp(ip_id=floating_ip['id'],
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='pool')

        self.assertEqual(expected_resp, cls.acquire_service_pub_ip_info
                         (m_driver, spec_type, spec_lb_ip,  project_id))

    def test_release_pub_ip_empty_lb_ip_info(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        service_pub_ip_info = None

        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertEqual(rc, True)

    def test_release_pub_ip_alloc_method_non_pool(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)

        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}

        service_pub_ip_info = \
            obj_lbaas.LBaaSPubIp(ip_id=floating_ip['id'],
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='kk')

        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertEqual(rc, True)

    def test_release_pub_ip_alloc_method_user(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)

        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}

        service_pub_ip_info = \
            obj_lbaas.LBaaSPubIp(ip_id=floating_ip['id'],
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='user')
        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertEqual(rc, True)

    def test_release_pub_ip_alloc_method_pool_neutron_exception(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.delete_floatingip.side_effect = n_exc.NeutronClientException

        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}

        service_pub_ip_info = \
            obj_lbaas.LBaaSPubIp(ip_id=floating_ip['id'],
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='pool')
        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertEqual(rc, False)

    def test_release_pub_ip_alloc_method_pool_neutron_succeeded(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.delete_floatingip.return_value = None

        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}

        service_pub_ip_info = \
            obj_lbaas.LBaaSPubIp(ip_id=floating_ip['id'],
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='pool')
        rc = cls.release_pub_ip(m_driver, service_pub_ip_info)
        self.assertEqual(rc, True)

    def test_associate_pub_ip_empty_params(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.return_value = None

        service_pub_ip_info = None
        vip_port_id = None

        self.assertIsNone(cls.associate_pub_ip
                          (m_driver, service_pub_ip_info, vip_port_id))

    def test_associate_lb_fip_id_not_exist(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.return_value = None
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()

        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}
        service_pub_ip_info = \
            obj_lbaas.LBaaSPubIp(ip_id=0,
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='pool')

        vip_port_id = 'ec29d641-fec4-4f67-928a-124a76b3a777'

        self.assertIsNone(cls.associate_pub_ip
                          (m_driver, service_pub_ip_info, vip_port_id))

    def test_associate_lb_fip_id_not_exist_neutron_exception(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.side_effect = n_exc.NeutronClientException

        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}
        service_pub_ip_info = \
            obj_lbaas.LBaaSPubIp(ip_id=floating_ip['id'],
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='pool')
        vip_port_id = 'ec29d641-fec4-4f67-928a-124a76b3a777'

        self.assertRaises(
            n_exc.NeutronClientException, cls.associate_pub_ip,
            m_driver, service_pub_ip_info, vip_port_id)

    def test_disassociate_pub_ip_empty_param(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.return_value = None
        service_pub_ip_info = None

        self.assertIsNone(cls.disassociate_pub_ip
                          (m_driver, service_pub_ip_info))

    def test_disassociate_pub_ip_fip_id_not_exist(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.return_value = None
        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}

        service_pub_ip_info = \
            obj_lbaas.LBaaSPubIp(ip_id=0,
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='pool')

        self.assertIsNone(cls.disassociate_pub_ip
                          (m_driver, service_pub_ip_info))

    def test_disassociate_pub_ip_neutron_exception(self):
        cls = d_lb_public_ip.FloatingIpServicePubIPDriver
        m_driver = mock.Mock(spec=cls)
        m_driver._drv_pub_ip = public_ip.FipPubIpDriver()
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.update_floatingip.side_effect = n_exc.NeutronClientException
        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}
        service_pub_ip_info = \
            obj_lbaas.LBaaSPubIp(ip_id=floating_ip['id'],
                                 ip_addr=floating_ip['floating_ip_address'],
                                 alloc_method='pool')

        self.assertRaises(
            n_exc.NeutronClientException, cls.disassociate_pub_ip,
            m_driver, service_pub_ip_info)
