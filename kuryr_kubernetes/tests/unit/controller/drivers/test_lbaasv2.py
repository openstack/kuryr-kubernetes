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
from openstack.load_balancer.v2 import listener as o_lis
from openstack.load_balancer.v2 import load_balancer as o_lb
from openstack.load_balancer.v2 import member as o_mem
from openstack.load_balancer.v2 import pool as o_pool
from openstack.network.v2 import port as os_port
from oslo_config import cfg

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import lbaasv2 as d_lbaasv2
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests import fake
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix

CONF = cfg.CONF

OCTAVIA_VERSIONS = {
    'regionOne': {
        'public': {
            'load-balancer': [
                {
                    'status': 'SUPPORTED',
                    'version': '2.0',
                    'raw_status': u'SUPPORTED',
                },
                {
                    'status': 'SUPPORTED',
                    'version': '2.1',
                    'raw_status': u'SUPPORTED',
                },
                {
                    'status': 'CURRENT',
                    'version': '2.2',
                    'raw_status': u'CURRENT',
                },
            ],
        },
    },
}

BAD_OCTAVIA_VERSIONS = {
    'regionOne': {
        'public': {
            'load-balancer': [
                {
                    'status': 'CURRENT',
                    'version': None,
                    'raw_status': u'CURRENT',
                },
            ],
        },
    },
}


class TestLBaaSv2Driver(test_base.TestCase):
    @mock.patch('kuryr_kubernetes.controller.drivers.lbaasv2.LBaaSv2Driver.'
                'get_octavia_version', return_value=(2, 5))
    def test_add_tags(self, _m_get):
        CONF.set_override('resource_tags', ['foo'], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')
        d = d_lbaasv2.LBaaSv2Driver()
        req = {}
        d.add_tags('loadbalancer', req)
        self.assertEqual({'tags': ['foo']}, req)

    @mock.patch('kuryr_kubernetes.controller.drivers.lbaasv2.LBaaSv2Driver.'
                'get_octavia_version', return_value=(2, 5))
    def test_add_tags_no_tag(self, _m_get):
        d = d_lbaasv2.LBaaSv2Driver()
        req = {}
        d.add_tags('loadbalancer', req)
        self.assertEqual({}, req)

    @mock.patch('kuryr_kubernetes.controller.drivers.lbaasv2.LBaaSv2Driver.'
                'get_octavia_version', return_value=(2, 4))
    def test_add_tags_no_support(self, _m_get):
        CONF.set_override('resource_tags', ['foo'], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')
        d = d_lbaasv2.LBaaSv2Driver()
        for res in ('loadbalancer', 'listener', 'pool'):
            req = {}
            d.add_tags(res, req)
            self.assertEqual({'description': 'foo'}, req,
                             'No description added to resource %s' % res)

    @mock.patch('kuryr_kubernetes.controller.drivers.lbaasv2.LBaaSv2Driver.'
                'get_octavia_version', return_value=(2, 4))
    def test_add_tags_no_support_resource_no_description(self, _m_get):
        CONF.set_override('resource_tags', ['foo'], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')
        d = d_lbaasv2.LBaaSv2Driver()
        for res in ('member', 'rule'):
            req = {}
            d.add_tags(res, req)
            self.assertEqual({}, req, 'Unnecessary description added to '
                                      'resource %s' % res)

    def test_get_octavia_version(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lbaas.get_all_version_data.return_value = OCTAVIA_VERSIONS
        self.assertEqual((2, 2),
                         d_lbaasv2.LBaaSv2Driver.get_octavia_version(None))

    def test_get_octavia_version_is_none(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lbaas.get_all_version_data.return_value = BAD_OCTAVIA_VERSIONS
        self.assertRaises(k_exc.UnreachableOctavia,
                          d_lbaasv2.LBaaSv2Driver.get_octavia_version, None)

    def test_ensure_loadbalancer(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = {
            'provide': 'octavia',
            'port_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42E2',
            'security_groups': []
        }
        project_id = 'TEST_PROJECT'
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        sg_ids = ['foo', 'bar']
        lb_name = 'just_a_name'

        m_driver._ensure_loadbalancer.return_value = expected_resp
        os_net.update_port = mock.Mock()
        resp = cls.ensure_loadbalancer(m_driver, lb_name, project_id,
                                       subnet_id, ip, sg_ids, 'ClusterIP')
        m_driver._ensure_loadbalancer.assert_called_once_with(
            mock.ANY)
        req = m_driver._ensure_loadbalancer.call_args[0][0]
        self.assertEqual(lb_name, req['name'])
        self.assertEqual(project_id, req['project_id'])
        self.assertEqual(subnet_id, req['subnet_id'])
        self.assertEqual(ip, str(req['ip']))
        self.assertEqual(expected_resp, resp)
        os_net.update_port.assert_not_called()

    def test_ensure_loadbalancer_not_ready(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        name = 'TEST_NAME'
        project_id = 'TEST_PROJECT'
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        # TODO(ivc): handle security groups
        sg_ids = []

        m_driver._ensure_loadbalancer.return_value = None
        self.assertRaises(k_exc.ResourceNotReady, cls.ensure_loadbalancer,
                          m_driver, name, project_id, subnet_id, ip,
                          sg_ids, 'ClusterIP')

    def test_cascade_release_loadbalancer(self):
        self.useFixture(k_fix.MockNetworkClient()).client
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lbaas.lbaas_loadbalancer_path = "boo %s"
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'security_groups': [],
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'provider': None
        }

        cls.release_loadbalancer(m_driver, loadbalancer)

        m_driver._release.assert_called_once_with(
            loadbalancer, loadbalancer, lbaas.delete_load_balancer,
            loadbalancer['id'], cascade=True)

    def _test_ensure_listener(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        project_id = 'TEST_PROJECT'
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        protocol = 'TCP'
        port = 1234
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': project_id,
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'provider': 'amphora'
        }
        # TODO(ivc): handle security groups
        m_driver._ensure_provisioned.return_value = expected_resp

        resp = cls.ensure_listener(m_driver, loadbalancer, protocol, port)

        m_driver._ensure_provisioned.assert_called_once_with(
            loadbalancer, mock.ANY, m_driver._create_listener,
            m_driver._find_listener, d_lbaasv2._LB_STS_POLL_SLOW_INTERVAL)
        listener = m_driver._ensure_provisioned.call_args[0][1]

        self.assertEqual("%s:%s:%s" % (loadbalancer['name'], protocol, port),
                         listener['name'])
        self.assertEqual(project_id, listener['project_id'])
        self.assertEqual(loadbalancer_id, listener['loadbalancer_id'])
        self.assertEqual(protocol, listener['protocol'])
        self.assertEqual(port, listener['port'])
        self.assertEqual(expected_resp, resp)

    def test_ensure_listener_bad_request_exception(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        port = 1234
        protocol = 'TCP'
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'provider': 'amphora'
        }
        m_driver._ensure_provisioned.side_effect = os_exc.BadRequestException

        resp = cls.ensure_listener(m_driver, loadbalancer,
                                   protocol, port)
        self.assertIsNone(resp)

    def test_release_listener(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        os_net.security_group_rules.return_value = (x for x in [])
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = os_port.Port(
            security_group_ids=[mock.sentinel.sg_id],
        )
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'security_groups': [],
            'provider': 'amphora'
        }
        listener = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'protocol': 'TCP',
            'port': 1234,
            'id': 'A57B7771-6050-4CA8-A63C-443493EC98AB'
        }

        cls.release_listener(m_driver, loadbalancer, listener)

        m_driver._release.assert_called_once_with(loadbalancer, listener,
                                                  lbaas.delete_listener,
                                                  listener['id'])

    def test_ensure_pool(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        loadbalancer = {
            'project_id': 'TEST_PROJECT',
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
        }
        listener = {
            'id': 'A57B7771-6050-4CA8-A63C-443493EC98AB',
            'name': 'TEST_LISTENER_NAME',
            'protocol': 'TCP',
        }
        m_driver._ensure_provisioned.return_value = expected_resp

        resp = cls.ensure_pool(m_driver, loadbalancer, listener)

        m_driver._ensure_provisioned.assert_called_once_with(
            loadbalancer, mock.ANY, m_driver._create_pool,
            m_driver._find_pool)
        pool = m_driver._ensure_provisioned.call_args[0][1]
        self.assertEqual(listener['name'], pool['name'])
        self.assertEqual(loadbalancer['project_id'], pool['project_id'])
        self.assertEqual(listener['id'], pool['listener_id'])
        self.assertEqual(listener['protocol'], pool['protocol'])
        self.assertEqual(expected_resp, resp)

    def test_release_pool(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.Mock()
        pool = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'listener_id': 'A57B7771-6050-4CA8-A63C-443493EC98AB',
            'protocol': 'TCP',
            'id': 'D4F35594-27EB-4F4C-930C-31DD40F53B77'
        }

        cls.release_pool(m_driver, loadbalancer, pool)

        m_driver._release.assert_called_once_with(loadbalancer, pool,
                                                  lbaas.delete_pool,
                                                  pool['id'])

    def test_ensure_member(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        loadbalancer = {
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'project_id': 'TEST_PROJECT'
        }
        pool = {
            'id': 'D4F35594-27EB-4F4C-930C-31DD40F53B77',
            'project_id': 'TEST_PROJECT'
        }

        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        port = 1234
        namespace = 'TEST_NAMESPACE'
        name = 'TEST_NAME'
        target_ref = {'namespace': namespace, 'name': name}
        m_driver._ensure_provisioned.return_value = expected_resp

        resp = cls.ensure_member(m_driver, loadbalancer, pool,
                                 subnet_id, ip, port,
                                 target_ref['namespace'], target_ref['name'])

        m_driver._ensure_provisioned.assert_called_once_with(
            loadbalancer, mock.ANY, m_driver._create_member,
            m_driver._find_member, update=lbaas.update_member)
        member = m_driver._ensure_provisioned.call_args[0][1]
        self.assertEqual("%s/%s:%s" % (namespace, name, port), member['name'])
        self.assertEqual(pool['project_id'], member['project_id'])
        self.assertEqual(pool['id'], member['pool_id'])
        self.assertEqual(subnet_id, member['subnet_id'])
        self.assertEqual(ip, str(member['ip']))
        self.assertEqual(port, member['port'])
        self.assertEqual(expected_resp, resp)

    def test_release_member(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'security_groups': [],
            'provider': None
        }

        member = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'pool_id': 'D4F35594-27EB-4F4C-930C-31DD40F53B77',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'port': 1234,
            'id': '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'
        }

        cls.release_member(m_driver, loadbalancer, member)

        m_driver._release.assert_called_once_with(loadbalancer, member,
                                                  lbaas.delete_member,
                                                  member['id'],
                                                  member['pool_id'])

    def test_create_loadbalancer(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'security_groups': [],
            'provider': None
        }

        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        req = {
            'name': loadbalancer['name'],
            'project_id': loadbalancer['project_id'],
            'vip_address': str(loadbalancer['ip']),
            'vip_subnet_id': loadbalancer['subnet_id'],
        }
        resp = o_lb.LoadBalancer(id=loadbalancer_id, provider='haproxy')
        lbaas.create_load_balancer.return_value = resp
        m_driver._get_vip_port.return_value = os_port.Port(
            id=mock.sentinel.port_id,
        )

        ret = cls._create_loadbalancer(m_driver, loadbalancer)
        lbaas.create_load_balancer.assert_called_once_with(**req)
        self.assertEqual(loadbalancer, ret)
        self.assertEqual(loadbalancer_id, ret['id'])

    def test_create_loadbalancer_provider_defined(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'security_groups': [],
            'provider': 'amphora'
        }
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        req = {
            'name': loadbalancer['name'],
            'project_id': loadbalancer['project_id'],
            'vip_address': str(loadbalancer['ip']),
            'vip_subnet_id': loadbalancer['subnet_id'],
            'provider': loadbalancer['provider'],
        }
        resp = o_lb.LoadBalancer(id=loadbalancer_id, provider='amphora')
        lbaas.create_load_balancer.return_value = resp
        m_driver._get_vip_port.return_value = os_port.Port(
            id=mock.sentinel.port_id,
        )

        ret = cls._create_loadbalancer(m_driver, loadbalancer)
        lbaas.create_load_balancer.assert_called_once_with(**req)
        self.assertEqual(loadbalancer, ret)
        self.assertEqual(loadbalancer_id, ret['id'])

    def test_create_loadbalancer_provider_mismatch(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'security_groups': [],
            'provider': 'amphora'
        }
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        req = {
            'name': loadbalancer['name'],
            'project_id': loadbalancer['project_id'],
            'vip_address': str(loadbalancer['ip']),
            'vip_subnet_id': loadbalancer['subnet_id'],
            'provider': loadbalancer['provider'],
        }
        resp = o_lb.LoadBalancer(id=loadbalancer_id, provider='haproxy')
        lbaas.create_load_balancer.return_value = resp
        m_driver._get_vip_port.return_value = os_port.Port(
            id=mock.sentinel.port_id,
        )

        ret = cls._create_loadbalancer(m_driver, loadbalancer)
        lbaas.create_load_balancer.assert_called_once_with(**req)
        self.assertIsNone(ret)

    def test_find_loadbalancer(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'security_groups': [],
            'provider': 'haproxy'
        }
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        resp = iter([o_lb.LoadBalancer(id=loadbalancer_id, provider='haproxy',
                                       provisioning_status='ACTIVE')])
        lbaas.load_balancers.return_value = resp
        m_driver._get_vip_port.return_value = os_port.Port(
            id=mock.sentinel.port_id,
        )

        ret = cls._find_loadbalancer(m_driver, loadbalancer)
        lbaas.load_balancers.assert_called_once_with(
            name=loadbalancer['name'],
            project_id=loadbalancer['project_id'],
            vip_address=str(loadbalancer['ip']),
            vip_subnet_id=loadbalancer['subnet_id'],
            provider='haproxy')
        self.assertEqual(loadbalancer, ret)
        self.assertEqual(loadbalancer_id, ret['id'])
        m_driver.release_loadbalancer.assert_not_called()

    def test_find_loadbalancer_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1')
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'provider': None
        }
        resp = iter([])
        lbaas.load_balancers.return_value = resp

        ret = cls._find_loadbalancer(m_driver, loadbalancer)
        lbaas.load_balancers.assert_called_once_with(
            name=loadbalancer['name'],
            project_id=loadbalancer['project_id'],
            vip_address=str(loadbalancer['ip']),
            vip_subnet_id=loadbalancer['subnet_id'],
            provider=None)
        self.assertIsNone(ret)
        m_driver.release_loadbalancer.assert_not_called()

    def test_find_loadbalancer_error(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'name': 'test_namespace/test_name',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'provider': None
        }
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        resp = iter([o_lb.LoadBalancer(id=loadbalancer_id, provider='haproxy',
                                       provisioning_status='ERROR')])
        lbaas.load_balancers.return_value = resp
        m_driver._get_vip_port.return_value = os_port.Port(
            id=mock.sentinel.port_id,
        )

        ret = cls._find_loadbalancer(m_driver, loadbalancer)
        lbaas.load_balancers.assert_called_once_with(
            name=loadbalancer['name'],
            project_id=loadbalancer['project_id'],
            vip_address=str(loadbalancer['ip']),
            vip_subnet_id=loadbalancer['subnet_id'],
            provider=None)
        self.assertIsNone(ret)
        m_driver.release_loadbalancer.assert_called_once()

    def test_create_listener(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        listener = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'protocol': 'TCP',
            'port': 1234
        }
        listener_id = 'A57B7771-6050-4CA8-A63C-443493EC98AB'

        req = {
            'name': listener['name'],
            'project_id': listener['project_id'],
            'loadbalancer_id': listener['loadbalancer_id'],
            'protocol': listener['protocol'],
            'protocol_port': listener['port']}
        resp = o_lis.Listener(id=listener_id)
        lbaas.create_listener.return_value = resp

        ret = cls._create_listener(m_driver, listener)
        lbaas.create_listener.assert_called_once_with(**req)
        self.assertEqual(listener, ret)
        self.assertEqual(listener_id, ret['id'])

    def test_create_listener_with_different_timeouts(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        listener = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'protocol': 'TCP',
            'port': 5678,
            'timeout_client_data': 75000,
            'timeout_member_data': 0
        }
        listener_id = 'A57B7771-6050-4CA8-A63C-443493EC98AB'

        req = {
            'name': listener['name'],
            'project_id': listener['project_id'],
            'loadbalancer_id': listener['loadbalancer_id'],
            'protocol': listener['protocol'],
            'protocol_port': listener['port'],
            'timeout_client_data': listener['timeout_client_data']}
        resp = o_lis.Listener(id=listener_id)
        lbaas.create_listener.return_value = resp

        ret = cls._create_listener(m_driver, listener)
        lbaas.create_listener.assert_called_once_with(**req)
        self.assertEqual(listener, ret)
        self.assertEqual(listener_id, ret['id'])

    def test_find_listener(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
        }
        listener = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'protocol': 'TCP',
            'port': 1234
        }
        listener_id = 'A57B7771-6050-4CA8-A63C-443493EC98AB'
        lbaas.listeners.return_value = iter([o_lis.Listener(id=listener_id)])

        ret = cls._find_listener(m_driver, listener, loadbalancer)
        lbaas.listeners.assert_called_once_with(
            name=listener['name'],
            project_id=listener['project_id'],
            load_balancer_id=listener['loadbalancer_id'],
            protocol=listener['protocol'],
            protocol_port=listener['port'])
        self.assertEqual(listener, ret)
        self.assertEqual(listener_id, ret['id'])

    def test_find_listener_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
        }
        listener = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'protocol': 'TCP',
            'port': 1234
        }
        resp = iter([])
        lbaas.listeners.return_value = resp

        ret = cls._find_listener(m_driver, listener, loadbalancer)
        lbaas.listeners.assert_called_once_with(
            name=listener['name'],
            project_id=listener['project_id'],
            load_balancer_id=listener['loadbalancer_id'],
            protocol=listener['protocol'],
            protocol_port=listener['port'])
        self.assertIsNone(ret)

    def test_create_pool(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lb_algorithm = 'ROUND_ROBIN'
        pool = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'listener_id': 'A57B7771-6050-4CA8-A63C-443493EC98AB',
            'protocol': 'TCP'
        }
        pool_id = 'D4F35594-27EB-4F4C-930C-31DD40F53B77'

        req = {
            'name': pool['name'],
            'project_id': pool['project_id'],
            'listener_id': pool['listener_id'],
            'loadbalancer_id': pool['loadbalancer_id'],
            'protocol': pool['protocol'],
            'lb_algorithm': lb_algorithm}
        resp = o_pool.Pool(id=pool_id)
        lbaas.create_pool.return_value = resp

        ret = cls._create_pool(m_driver, pool)
        lbaas.create_pool.assert_called_once_with(**req)
        self.assertEqual(pool, ret)
        self.assertEqual(pool_id, ret['id'])

    def test_create_pool_with_different_lb_algorithm(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lb_algorithm = 'SOURCE_IP_PORT'
        pool = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'listener_id': 'A57B7771-6050-4CA8-A63C-443493EC98AB',
            'protocol': 'TCP'
        }
        pool_id = 'D4F35594-27EB-4F4C-930C-31DD40F53B77'
        req = {
            'name': pool['name'],
            'project_id': pool['project_id'],
            'listener_id': pool['listener_id'],
            'loadbalancer_id': pool['loadbalancer_id'],
            'protocol': pool['protocol'],
            'lb_algorithm': lb_algorithm}
        resp = o_pool.Pool(id=pool_id)
        lbaas.create_pool.return_value = resp
        CONF.set_override('lb_algorithm', lb_algorithm,
                          group='octavia_defaults')
        self.addCleanup(CONF.clear_override, 'lb_algorithm',
                        group='octavia_defaults')

        ret = cls._create_pool(m_driver, pool)
        lbaas.create_pool.assert_called_once_with(**req)
        self.assertEqual(pool, ret)
        self.assertEqual(pool_id, ret['id'])

    def test_create_pool_conflict(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lb_algorithm = 'ROUND_ROBIN'
        pool = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'listener_id': 'A57B7771-6050-4CA8-A63C-443493EC98AB',
            'protocol': 'TCP'
        }
        req = {
            'name': pool['name'],
            'project_id': pool['project_id'],
            'listener_id': pool['listener_id'],
            'loadbalancer_id': pool['loadbalancer_id'],
            'protocol': pool['protocol'],
            'lb_algorithm': lb_algorithm}
        lbaas.create_pool.side_effect = os_exc.BadRequestException

        self.assertRaises(os_exc.BadRequestException, cls._create_pool,
                          m_driver, pool)
        lbaas.create_pool.assert_called_once_with(**req)

    def test_find_pool_by_listener(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
        }
        pool = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'listener_id': 'A57B7771-6050-4CA8-A63C-443493EC98AB',
            'protocol': 'TCP'
        }
        pool_id = 'D4F35594-27EB-4F4C-930C-31DD40F53B77'
        resp = [o_pool.Pool(id=pool_id,
                            listeners=[{"id": pool['listener_id']}])]
        lbaas.pools.return_value = resp

        ret = cls._find_pool(m_driver, pool, loadbalancer)
        lbaas.pools.assert_called_once_with(
            name=pool['name'],
            project_id=pool['project_id'],
            loadbalancer_id=pool['loadbalancer_id'],
            protocol=pool['protocol'])
        self.assertEqual(pool, ret)
        self.assertEqual(pool_id, ret['id'])

    def test_find_pool_by_listener_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        }
        pool = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'loadbalancer_id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            'listener_id': 'A57B7771-6050-4CA8-A63C-443493EC98AB',
            'protocol': 'TCP'
        }
        resp = []
        lbaas.pools.return_value = resp

        ret = cls._find_pool(m_driver, pool, loadbalancer)
        lbaas.pools.assert_called_once_with(
            name=pool['name'],
            project_id=pool['project_id'],
            loadbalancer_id=pool['loadbalancer_id'],
            protocol=pool['protocol'])
        self.assertIsNone(ret)

    def test_create_member(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        member = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'pool_id': 'D4F35594-27EB-4F4C-930C-31DD40F53B77',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'port': 1234
        }
        member_id = '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'
        req = {
            'name': member['name'],
            'project_id': member['project_id'],
            'subnet_id': member['subnet_id'],
            'address': str(member['ip']),
            'protocol_port': member['port']}
        resp = o_mem.Member(id=member_id)
        lbaas.create_member.return_value = resp

        ret = cls._create_member(m_driver, member)
        lbaas.create_member.assert_called_once_with(member['pool_id'], **req)
        self.assertEqual(member, ret)
        self.assertEqual(member_id, ret['id'])

    def test_find_member(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer()
        member = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'pool_id': 'D4F35594-27EB-4F4C-930C-31DD40F53B77',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'port': 1234
        }
        member_id = '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'
        resp = iter([o_mem.Member(id=member_id, name='TEST_NAME')])
        lbaas.members.return_value = resp
        ret = cls._find_member(m_driver, member, loadbalancer)
        lbaas.members.assert_called_once_with(
            member['pool_id'],
            project_id=member['project_id'],
            subnet_id=member['subnet_id'],
            address=member['ip'],
            protocol_port=member['port'])
        # the member dict is copied, so the id is added to the return obj
        member['id'] = member_id
        self.assertEqual(member, ret)
        self.assertEqual(member_id, ret['id'])

    def test_find_member_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer()
        member = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'pool_id': 'D4F35594-27EB-4F4C-930C-31DD40F53B77',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'port': 1234
        }
        resp = iter([])
        lbaas.members.return_value = resp

        ret = cls._find_member(m_driver, member, loadbalancer)
        lbaas.members.assert_called_once_with(
            member['pool_id'],
            project_id=member['project_id'],
            subnet_id=member['subnet_id'],
            address=member['ip'],
            protocol_port=member['port'])
        self.assertIsNone(ret)

    def test_ensure(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        obj = mock.Mock()
        lb = mock.Mock()
        m_create = mock.Mock()
        m_find = mock.Mock()
        expected_result = mock.sentinel.expected_result
        m_create.return_value = expected_result

        ret = cls._ensure(m_driver, m_create, m_find,
                          obj, lb)
        m_create.assert_called_once_with(obj)
        self.assertEqual(expected_result, ret)

    def _verify_ensure_with_exception(self, exception_value):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        obj = mock.Mock()
        lb = mock.Mock()
        m_create = mock.Mock()
        m_find = mock.Mock()
        expected_result = None
        m_create.side_effect = exception_value
        m_find.return_value = expected_result

        ret = cls._ensure(m_driver, m_create, m_find,
                          obj, lb)
        m_create.assert_called_once_with(obj)
        m_find.assert_called_once_with(obj, lb)
        self.assertEqual(expected_result, ret)

    def test_ensure_with_conflict(self):
        self._verify_ensure_with_exception(
            os_exc.ConflictException(http_status=409))

    def test_ensure_with_internalservererror(self):
        self._verify_ensure_with_exception(
            os_exc.HttpException(http_status=500))

    def test_request(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.sentinel.loadbalancer
        obj = mock.sentinel.obj
        create = mock.sentinel.create
        find = mock.sentinel.find
        timer = [mock.sentinel.t0]
        m_driver._provisioning_timer.return_value = timer
        m_driver._ensure.side_effect = os_exc.BadRequestException()

        self.assertRaises(os_exc.BadRequestException,
                          cls._ensure_provisioned, m_driver,
                          loadbalancer, obj, create, find)

        m_driver._wait_for_provisioning.assert_has_calls(
            [mock.call(loadbalancer, t, d_lbaasv2._LB_STS_POLL_FAST_INTERVAL)
             for t in timer])
        m_driver._ensure.assert_has_calls(
            [mock.call(create, find, obj, loadbalancer) for _ in timer])

    def test_ensure_not_ready(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.sentinel.loadbalancer
        obj = mock.sentinel.obj
        create = mock.sentinel.create
        find = mock.sentinel.find
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer
        m_driver._ensure.return_value = None

        self.assertRaises(k_exc.ResourceNotReady, cls._ensure_provisioned,
                          m_driver,
                          loadbalancer, obj, create, find)

        m_driver._wait_for_provisioning.assert_has_calls(
            [mock.call(loadbalancer, t, d_lbaasv2._LB_STS_POLL_FAST_INTERVAL)
             for t in timer])
        m_driver._ensure.assert_has_calls(
            [mock.call(create, find, obj, loadbalancer) for _ in timer])

    def test_release(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.sentinel.loadbalancer
        obj = mock.sentinel.obj
        m_delete = mock.Mock()
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer

        cls._release(m_driver, loadbalancer, obj, m_delete)

        m_driver._wait_for_provisioning.assert_not_called()
        m_delete.assert_called_once()

    def test_release_with_wait(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.sentinel.loadbalancer
        obj = mock.sentinel.obj
        m_delete = mock.Mock()
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer
        m_delete.side_effect = [os_exc.BadRequestException, None]

        cls._release(m_driver, loadbalancer, obj, m_delete)

        m_driver._wait_for_provisioning.assert_called_once_with(loadbalancer,
                                                                mock.ANY)
        self.assertEqual(2, m_delete.call_count)

    def test_release_not_found(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.sentinel.loadbalancer
        obj = mock.sentinel.obj
        m_delete = mock.Mock()
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer
        m_delete.side_effect = os_exc.NotFoundException

        cls._release(m_driver, loadbalancer, obj, m_delete)

        m_driver._wait_for_provisioning.assert_not_called()
        self.assertEqual(1, m_delete.call_count)

    def test_release_not_ready(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.sentinel.loadbalancer
        obj = mock.sentinel.obj
        m_delete = mock.Mock()
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer
        m_delete.side_effect = os_exc.ConflictException

        self.assertRaises(k_exc.ResourceNotReady, cls._release, m_driver,
                          loadbalancer, obj, m_delete)

        call_count = len(timer)
        self.assertEqual(call_count,
                         m_driver._wait_for_provisioning.call_count)
        self.assertEqual(call_count, m_delete.call_count)

    def test_wait_for_provisioning(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'provider': None,
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        }
        timeout = mock.sentinel.timeout
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer
        resp = o_lb.LoadBalancer(provisioning_status='ACTIVE')
        lbaas.get_load_balancer.return_value = resp

        cls._wait_for_provisioning(m_driver, loadbalancer, timeout)

        lbaas.get_load_balancer.assert_called_once_with(loadbalancer['id'])

    def test_wait_for_provisioning_not_ready(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = {
            'name': 'TEST_NAME',
            'project_id': 'TEST_PROJECT',
            'subnet_id': 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            'ip': '1.2.3.4',
            'provider': None,
            'id': '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        }
        timeout = mock.sentinel.timeout
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer
        resp = o_lb.LoadBalancer(provisioning_status='NOT_ACTIVE')
        lbaas.get_load_balancer.return_value = resp

        self.assertRaises(k_exc.ResourceNotReady, cls._wait_for_provisioning,
                          m_driver, loadbalancer, timeout)

        self.assertEqual(len(timer), lbaas.get_load_balancer.call_count)

    def test_provisioning_timer(self):
        # REVISIT(ivc): add test if _provisioning_timer is to stay
        self.skipTest("not implemented")


class TestLBaaSv2AppyMembersSecurityGroup(test_base.TestCase):

    def setUp(self):
        super().setUp()
        self.lb = {'id': 'a4de5f1a-ac03-45b1-951d-39f108d52e7d',
                   'ip': '10.0.0.142',
                   'name': 'default/lb',
                   'port_id': '5be1b3c4-7d44-4597-9294-cadafdf1ec69',
                   'project_id': '7ef23242bb3f4773a58da681421ab26e',
                   'provider': 'amphora',
                   'security_groups': ['328900a2-c328-41cc-946f-56ae8720ec0d'],
                   'subnet_id': 'c85e2e10-1fad-4218-ad10-7de4aa5de7ce'}
        self.port = 80
        self.target_port = 8080
        self.protocol = 'TCP'
        self.sg_rule_name = 'default/lb:TCP:80'
        self.listener_id = '858869ec-e4fa-4715-b22f-bd08889c6235'
        self.new_sgs = ['48cfc812-a442-44bf-989f-8dbaf23a7007']
        self.vip = fake.get_port_obj()

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test__apply_members_security_groups_no_enforce(self, gnc):
        CONF.set_override('enforce_sg_rules', False, group='octavia_defaults')
        self.addCleanup(CONF.clear_override, 'enforce_sg_rules',
                        group='octavia_defaults')
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = None

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test__apply_members_security_groups_no_vip(self, gnc):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = None

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test__apply_members_security_groups_no_sg(self, gnc):
        self.new_sgs = None
        self.vip.security_group_ids = []
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip

        self.assertRaises(k_exc.ResourceNotReady,
                          cls._apply_members_security_groups, m_driver,
                          self.lb, self.port, self.target_port, self.protocol,
                          self.sg_rule_name, self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test__apply_members_security_groups_conf_with_octavia_acls(self, gnc):
        self.new_sgs = None
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port = mock.Mock(return_value=self.vip)
        m_driver._octavia_acls = True
        m_driver._create_listeners_acls = mock.Mock()

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name, self.listener_id,
                                           self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        m_driver._create_listeners_acls.assert_called_once_with(
            self.lb, self.port, self.target_port, self.protocol,
            self.vip.security_group_ids[0], self.new_sgs, self.listener_id)

    def test__apply_members_security_groups_new_sgs(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        os_net.security_group_rules.return_value = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name, self.listener_id,
                                           self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_has_calls([
            mock.call(security_group_id=self.vip.security_group_ids[0],
                      project_id=self.lb['project_id']),
            mock.call(security_group_id=self.new_sgs[0])])

    def test__apply_members_security_groups_conf_lb_sgs(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        sgr = fake.get_sgr_obj()
        os_net.security_group_rules.side_effect = ([], [sgr])
        self.new_sgs = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_has_calls([
            mock.call(security_group_id=self.vip.security_group_ids[0],
                      project_id=self.lb['project_id']),
            mock.call(security_group_id=self.lb['security_groups'][0])])
        os_net.create_security_group_rule.assert_called_once_with(
            direction='ingress',
            ether_type=k_const.IPv4,
            port_range_min=self.port,
            port_range_max=self.port,
            protocol=self.protocol,
            remote_ip_prefix=sgr.remote_ip_prefix,
            security_group_id=sgr.security_group_id,
            description=self.sg_rule_name)

    def test__apply_members_security_groups_conf_lb_sgs_conflict(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        sgr = fake.get_sgr_obj()
        os_net.security_group_rules.side_effect = ([], [sgr])
        os_net.create_security_group_rule.side_effect = (os_exc
                                                         .ConflictException)
        self.new_sgs = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_has_calls([
            mock.call(security_group_id=self.vip.security_group_ids[0],
                      project_id=self.lb['project_id']),
            mock.call(security_group_id=self.lb['security_groups'][0])])
        os_net.create_security_group_rule.assert_called_once_with(
            direction='ingress',
            ether_type=k_const.IPv4,
            port_range_min=self.port,
            port_range_max=self.port,
            protocol=self.protocol,
            remote_ip_prefix=None,
            security_group_id=self.vip.security_group_ids[0],
            description=self.sg_rule_name)

    def test__apply_members_security_groups_conf_lb_sgs_sdkexception(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        sgr = fake.get_sgr_obj()
        os_net.security_group_rules.side_effect = ([], [sgr])
        os_net.create_security_group_rule.side_effect = os_exc.SDKException
        self.new_sgs = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_has_calls([
            mock.call(security_group_id=self.vip.security_group_ids[0],
                      project_id=self.lb['project_id']),
            mock.call(security_group_id=self.lb['security_groups'][0])])
        os_net.create_security_group_rule.assert_called_once_with(
            direction='ingress',
            ether_type=k_const.IPv4,
            port_range_min=self.port,
            port_range_max=self.port,
            protocol=self.protocol,
            remote_ip_prefix=None,
            security_group_id=self.vip.security_group_ids[0],
            description=self.sg_rule_name)

    @mock.patch("kuryr_kubernetes.utils.get_service_subnet_version",
                return_value=k_const.IP_VERSION_6)
    def test__apply_members_security_groups_ipv6_add_default(self, gssv):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        os_net.security_group_rules.return_value = []
        CONF.set_override('pod_security_groups', self.new_sgs,
                          group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name, self.listener_id,
                                           self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_called_once_with(
            security_group_id=self.vip.security_group_ids[0],
            project_id=self.lb['project_id'])
        os_net.create_security_group_rule.assert_called_once_with(
            direction='ingress',
            ether_type=k_const.IPv6,
            port_range_min=self.port,
            port_range_max=self.port,
            protocol=self.protocol,
            security_group_id=self.vip.security_group_ids[0],
            description=self.sg_rule_name)

    def test__apply_members_security_groups_add_default_conflict(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        os_net.security_group_rules.return_value = []
        CONF.set_override('pod_security_groups', self.new_sgs,
                          group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')
        os_net.create_security_group_rule.side_effect = (os_exc
                                                         .ConflictException)

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name, self.listener_id,
                                           self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_called_once_with(
            security_group_id=self.vip.security_group_ids[0],
            project_id=self.lb['project_id'])
        os_net.create_security_group_rule.assert_called_once_with(
            direction='ingress',
            ether_type=k_const.IPv4,
            port_range_min=self.port,
            port_range_max=self.port,
            protocol=self.protocol,
            security_group_id=self.vip.security_group_ids[0],
            description=self.sg_rule_name)

    def test__apply_members_security_groups_add_default_sdk_exception(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        os_net.security_group_rules.return_value = []
        CONF.set_override('pod_security_groups', self.new_sgs,
                          group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')
        os_net.create_security_group_rule.side_effect = os_exc.SDKException

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name, self.listener_id,
                                           self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_called_once_with(
            security_group_id=self.vip.security_group_ids[0],
            project_id=self.lb['project_id'])
        os_net.create_security_group_rule.assert_called_once_with(
            direction='ingress',
            ether_type=k_const.IPv4,
            port_range_min=self.port,
            port_range_max=self.port,
            protocol=self.protocol,
            security_group_id=self.vip.security_group_ids[0],
            description=self.sg_rule_name)

    def test__apply_members_security_groups_same_sg(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        self.vip.security_group_ids = self.new_sgs
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        os_net.security_group_rules.return_value = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name, self.listener_id,
                                           self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_called_once_with(
            security_group_id=self.vip.security_group_ids[0],
            project_id=self.lb['project_id'])

    def test__apply_members_security_groups_unmatched_target_port(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        sgr = fake.get_sgr_obj()
        self.target_port = 9090
        os_net.security_group_rules.side_effect = ([], [sgr])
        self.new_sgs = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_has_calls([
            mock.call(security_group_id=self.vip.security_group_ids[0],
                      project_id=self.lb['project_id']),
            mock.call(security_group_id=self.lb['security_groups'][0])])
        os_net.create_security_group_rule.assert_not_called()

    def test__apply_members_security_groups_egress(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        sgr = fake.get_sgr_obj(direction='egress')
        os_net.security_group_rules.side_effect = ([], [sgr])
        self.new_sgs = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_has_calls([
            mock.call(security_group_id=self.vip.security_group_ids[0],
                      project_id=self.lb['project_id']),
            mock.call(security_group_id=self.lb['security_groups'][0])])
        os_net.create_security_group_rule.assert_not_called()

    def test__apply_members_security_groups_no_delete_lbaas_rules(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        self.lb['security_groups'] = []
        self.new_sgs = []
        sgr = fake.get_sgr_obj()
        os_net.security_group_rules.return_value = [sgr]

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_called_once_with(
            security_group_id=self.vip.security_group_ids[0],
            project_id=self.lb['project_id'])
        os_net.create_security_group_rule.assert_not_called()

    def test__apply_members_security_groups_delete_matched_lbaas_rules(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        sgr = fake.get_sgr_obj()
        os_net.security_group_rules.side_effect = ([sgr], [sgr])
        self.new_sgs = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_has_calls([
            mock.call(security_group_id=self.vip.security_group_ids[0],
                      project_id=self.lb['project_id']),
            mock.call(security_group_id=self.lb['security_groups'][0])])
        os_net.create_security_group_rule.assert_called_once_with(
            direction='ingress',
            ether_type=k_const.IPv4,
            port_range_min=self.port,
            port_range_max=self.port,
            protocol=self.protocol,
            remote_ip_prefix=sgr.remote_ip_prefix,
            security_group_id=sgr.security_group_id,
            description=self.sg_rule_name)
        os_net.delete_security_group_rule.assert_called_once_with(sgr.id)

    def test__apply_members_security_groups_delete_unmatched_lbaas_rules(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        sgr = fake.get_sgr_obj()
        os_net.security_group_rules.side_effect = ([sgr], [sgr])
        self.new_sgs = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')
        self.port = 8080

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_has_calls([
            mock.call(security_group_id=self.vip.security_group_ids[0],
                      project_id=self.lb['project_id']),
            mock.call(security_group_id=self.lb['security_groups'][0])])
        os_net.create_security_group_rule.assert_called_once_with(
            direction='ingress',
            ether_type=k_const.IPv4,
            port_range_min=self.port,
            port_range_max=self.port,
            protocol=self.protocol,
            remote_ip_prefix=sgr.remote_ip_prefix,
            security_group_id=sgr.security_group_id,
            description=self.sg_rule_name)
        m_driver._delete_rule_if_no_match.assert_called_once_with(sgr, [sgr])

    def test__apply_members_security_groups_delete_no_default_lbaas_rules(
            self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = self.vip
        m_driver._octavia_acls = False
        sgr = fake.get_sgr_obj()
        os_net.security_group_rules.side_effect = ([sgr], [sgr])
        self.new_sgs = []
        CONF.set_override('pod_security_groups', [], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'pod_security_groups',
                        group='neutron_defaults')
        m_driver._is_default_rule.return_value = False

        cls._apply_members_security_groups(m_driver, self.lb, self.port,
                                           self.target_port, self.protocol,
                                           self.sg_rule_name,
                                           self.listener_id, self.new_sgs)

        m_driver._get_vip_port.assert_called_once_with(self.lb)
        os_net.security_group_rules.assert_has_calls([
            mock.call(security_group_id=self.vip.security_group_ids[0],
                      project_id=self.lb['project_id']),
            mock.call(security_group_id=self.lb['security_groups'][0])])
        os_net.create_security_group_rule.assert_called_once_with(
            direction='ingress',
            ether_type=k_const.IPv4,
            port_range_min=self.port,
            port_range_max=self.port,
            protocol=self.protocol,
            remote_ip_prefix=sgr.remote_ip_prefix,
            security_group_id=sgr.security_group_id,
            description=self.sg_rule_name)
