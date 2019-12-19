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
import requests

from neutronclient.common import exceptions as n_exc
from openstack import exceptions as o_exc
from openstack.load_balancer.v2 import l7_policy as o_l7p
from openstack.load_balancer.v2 import l7_rule as o_l7r
from openstack.load_balancer.v2 import listener as o_lis
from openstack.load_balancer.v2 import load_balancer as o_lb
from openstack.load_balancer.v2 import member as o_mem
from openstack.load_balancer.v2 import pool as o_pool
from oslo_config import cfg

from kuryr_kubernetes.controller.drivers import lbaasv2 as d_lbaasv2
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.tests import base as test_base
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


class TestLBaaSv2Driver(test_base.TestCase):
    @mock.patch('kuryr_kubernetes.controller.drivers.lbaasv2.LBaaSv2Driver.'
                'get_octavia_version', return_value=(2, 5))
    def test_add_tags(self, _m_get):
        CONF.set_override('resource_tags', ['foo'], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')
        d = d_lbaasv2.LBaaSv2Driver()
        req = {}
        d._add_tags('loadbalancer', req)
        self.assertEqual({'tags': ['foo']}, req)

    @mock.patch('kuryr_kubernetes.controller.drivers.lbaasv2.LBaaSv2Driver.'
                'get_octavia_version', return_value=(2, 5))
    def test_add_tags_no_tag(self, _m_get):
        d = d_lbaasv2.LBaaSv2Driver()
        req = {}
        d._add_tags('loadbalancer', req)
        self.assertEqual({}, req)

    @mock.patch('kuryr_kubernetes.controller.drivers.lbaasv2.LBaaSv2Driver.'
                'get_octavia_version', return_value=(2, 4))
    def test_add_tags_no_support(self, _m_get):
        CONF.set_override('resource_tags', ['foo'], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')
        d = d_lbaasv2.LBaaSv2Driver()
        for res in ('loadbalancer', 'listener', 'pool', 'l7policy'):
            req = {}
            d._add_tags(res, req)
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
            d._add_tags(res, req)
            self.assertEqual({}, req, 'Unnecessary description added to '
                                      'resource %s' % res)

    def test_get_octavia_version(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lbaas.get_all_version_data.return_value = OCTAVIA_VERSIONS
        self.assertEqual((2, 2),
                         d_lbaasv2.LBaaSv2Driver.get_octavia_version(
                             d_lbaasv2.LBaaSv2Driver()))

    def test_ensure_loadbalancer(self):
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = obj_lbaas.LBaaSLoadBalancer(
            provider='octavia', port_id='D3FA400A-F543-4B91-9CD3-047AF0CE42E2',
            security_groups=[])
        project_id = 'TEST_PROJECT'
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        sg_ids = ['foo', 'bar']
        lb_name = 'just_a_name'

        m_driver._ensure.return_value = expected_resp
        neutron.update_port = mock.Mock()
        resp = cls.ensure_loadbalancer(m_driver, lb_name, project_id,
                                       subnet_id, ip, sg_ids, 'ClusterIP')
        m_driver._ensure.assert_called_once_with(mock.ANY,
                                                 m_driver._create_loadbalancer,
                                                 m_driver._find_loadbalancer)
        req = m_driver._ensure.call_args[0][0]
        self.assertEqual(lb_name, req.name)
        self.assertEqual(project_id, req.project_id)
        self.assertEqual(subnet_id, req.subnet_id)
        self.assertEqual(ip, str(req.ip))
        self.assertEqual(expected_resp, resp)
        neutron.update_port.assert_not_called()

    def test_ensure_loadbalancer_not_ready(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        name = 'TEST_NAME'
        project_id = 'TEST_PROJECT'
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        # TODO(ivc): handle security groups
        sg_ids = []

        m_driver._ensure.return_value = None
        self.assertRaises(k_exc.ResourceNotReady, cls.ensure_loadbalancer,
                          m_driver, name, project_id, subnet_id, ip,
                          sg_ids, 'ClusterIP')

    def test_cascade_release_loadbalancer(self):
        self.useFixture(k_fix.MockNeutronClient()).client
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lbaas.lbaas_loadbalancer_path = "boo %s"
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.Mock()

        cls.release_loadbalancer(m_driver, loadbalancer)

        m_driver._release.assert_called_once_with(
            loadbalancer, loadbalancer, lbaas.delete_load_balancer,
            loadbalancer.id, cascade=True)

    def _test_ensure_listener(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        name = 'TEST_NAME'
        project_id = 'TEST_PROJECT'
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        protocol = 'TCP'
        provider = 'amphora'
        port = 1234
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            id=loadbalancer_id, name=name, project_id=project_id,
            subnet_id=subnet_id, ip=ip, provider=provider)
        # TODO(ivc): handle security groups
        m_driver._ensure_provisioned.return_value = expected_resp

        resp = cls.ensure_listener(m_driver, loadbalancer,
                                   protocol, port)

        m_driver._ensure_provisioned.assert_called_once_with(
            loadbalancer, mock.ANY, m_driver._create_listener,
            m_driver._find_listener, d_lbaasv2._LB_STS_POLL_SLOW_INTERVAL)
        listener = m_driver._ensure_provisioned.call_args[0][1]

        self.assertEqual("%s:%s:%s" % (loadbalancer.name, protocol, port),
                         listener.name)
        self.assertEqual(project_id, listener.project_id)
        self.assertEqual(loadbalancer_id, listener.loadbalancer_id)
        self.assertEqual(protocol, listener.protocol)
        self.assertEqual(port, listener.port)
        self.assertEqual(expected_resp, resp)

    def test_ensure_listener_bad_request_exception(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        name = 'TEST_NAME'
        project_id = 'TEST_PROJECT'
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        port = 1234
        protocol = 'TCP'
        provider = 'amphora'
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            id=loadbalancer_id, name=name, project_id=project_id,
            subnet_id=subnet_id, ip=ip, provider=provider)
        m_driver._ensure_provisioned.side_effect = o_exc.BadRequestException

        resp = cls.ensure_listener(m_driver, loadbalancer,
                                   protocol, port)
        self.assertIsNone(resp)

    def test_release_listener(self):
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        neutron.list_security_group_rules.return_value = {
            'security_group_rules': []}
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        m_driver._get_vip_port.return_value = {
            'security_groups': [mock.sentinel.sg_id]}
        loadbalancer = mock.Mock()
        listener = mock.Mock()

        cls.release_listener(m_driver, loadbalancer, listener)

        m_driver._release.assert_called_once_with(loadbalancer, listener,
                                                  lbaas.delete_listener,
                                                  listener.id)

    def test_ensure_pool(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        listener = obj_lbaas.LBaaSListener(
            id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            name='TEST_LISTENER_NAME',
            protocol='TCP')
        m_driver._ensure_provisioned.return_value = expected_resp

        resp = cls.ensure_pool(m_driver, loadbalancer, listener)

        m_driver._ensure_provisioned.assert_called_once_with(
            loadbalancer, mock.ANY, m_driver._create_pool,
            m_driver._find_pool)
        pool = m_driver._ensure_provisioned.call_args[0][1]
        self.assertEqual(listener.name, pool.name)
        self.assertEqual(loadbalancer.project_id, pool.project_id)
        self.assertEqual(listener.id, pool.listener_id)
        self.assertEqual(listener.protocol, pool.protocol)
        self.assertEqual(expected_resp, resp)

    def test_release_pool(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.Mock()
        pool = mock.Mock()

        cls.release_pool(m_driver, loadbalancer, pool)

        m_driver._release.assert_called_once_with(loadbalancer, pool,
                                                  lbaas.delete_pool,
                                                  pool.id)

    def test_ensure_member(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        pool = obj_lbaas.LBaaSPool(project_id='TEST_PROJECT',
                                   id='D4F35594-27EB-4F4C-930C-31DD40F53B77')
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
            m_driver._find_member)
        member = m_driver._ensure_provisioned.call_args[0][1]
        self.assertEqual("%s/%s:%s" % (namespace, name, port), member.name)
        self.assertEqual(pool.project_id, member.project_id)
        self.assertEqual(pool.id, member.pool_id)
        self.assertEqual(subnet_id, member.subnet_id)
        self.assertEqual(ip, str(member.ip))
        self.assertEqual(port, member.port)
        self.assertEqual(expected_resp, resp)

    def test_release_member(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.Mock()
        member = mock.Mock()

        cls.release_member(m_driver, loadbalancer, member)

        m_driver._release.assert_called_once_with(loadbalancer, member,
                                                  lbaas.delete_member,
                                                  member.id, member.pool_id)

    def test_create_loadbalancer(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            security_groups=[])
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        req = {
            'name': loadbalancer.name,
            'project_id': loadbalancer.project_id,
            'vip_address': str(loadbalancer.ip),
            'vip_subnet_id': loadbalancer.subnet_id,
        }
        resp = o_lb.LoadBalancer(id=loadbalancer_id, provider='haproxy')
        m_driver._post_lb_resource.return_value = resp
        m_driver._get_vip_port.return_value = {'id': mock.sentinel.port_id}

        ret = cls._create_loadbalancer(m_driver, loadbalancer)
        m_driver._post_lb_resource.assert_called_once_with(o_lb.LoadBalancer,
                                                           req)
        for attr in loadbalancer.obj_fields:
            self.assertEqual(getattr(loadbalancer, attr),
                             getattr(ret, attr))
        self.assertEqual(loadbalancer_id, ret.id)

    def test_create_loadbalancer_provider_defined(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            security_groups=[],
            provider='amphora')
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        req = {
            'name': loadbalancer.name,
            'project_id': loadbalancer.project_id,
            'vip_address': str(loadbalancer.ip),
            'vip_subnet_id': loadbalancer.subnet_id,
            'provider': loadbalancer.provider,
        }
        resp = o_lb.LoadBalancer(id=loadbalancer_id, provider='amphora')
        m_driver._post_lb_resource.return_value = resp
        m_driver._get_vip_port.return_value = {'id': mock.sentinel.port_id}

        ret = cls._create_loadbalancer(m_driver, loadbalancer)
        m_driver._post_lb_resource.assert_called_once_with(o_lb.LoadBalancer,
                                                           req)
        for attr in loadbalancer.obj_fields:
            self.assertEqual(getattr(loadbalancer, attr),
                             getattr(ret, attr))
        self.assertEqual(loadbalancer_id, ret.id)

    def test_create_loadbalancer_provider_mismatch(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            security_groups=[],
            provider='amphora')
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        req = {
            'name': loadbalancer.name,
            'project_id': loadbalancer.project_id,
            'vip_address': str(loadbalancer.ip),
            'vip_subnet_id': loadbalancer.subnet_id,
            'provider': loadbalancer.provider,
        }
        resp = o_lb.LoadBalancer(id=loadbalancer_id, provider='haproxy')
        m_driver._post_lb_resource.return_value = resp
        m_driver._get_vip_port.return_value = {'id': mock.sentinel.port_id}

        ret = cls._create_loadbalancer(m_driver, loadbalancer)
        m_driver._post_lb_resource.assert_called_once_with(o_lb.LoadBalancer,
                                                           req)
        self.assertIsNone(ret)

    def test_find_loadbalancer(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            provider='haproxy', security_groups=[])
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        resp = iter([o_lb.LoadBalancer(id=loadbalancer_id, provider='haproxy',
                                       provisioning_status='ACTIVE')])
        lbaas.load_balancers.return_value = resp
        m_driver._get_vip_port.return_value = {'id': mock.sentinel.port_id}

        ret = cls._find_loadbalancer(m_driver, loadbalancer)
        lbaas.load_balancers.assert_called_once_with(
            name=loadbalancer.name,
            project_id=loadbalancer.project_id,
            vip_address=str(loadbalancer.ip),
            vip_subnet_id=loadbalancer.subnet_id)
        for attr in loadbalancer.obj_fields:
            self.assertEqual(getattr(loadbalancer, attr),
                             getattr(ret, attr))
        self.assertEqual(loadbalancer_id, ret.id)
        m_driver.release_loadbalancer.assert_not_called()

    def test_find_loadbalancer_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1')
        resp = iter([])
        lbaas.load_balancers.return_value = resp

        ret = cls._find_loadbalancer(m_driver, loadbalancer)
        lbaas.load_balancers.assert_called_once_with(
            name=loadbalancer.name,
            project_id=loadbalancer.project_id,
            vip_address=str(loadbalancer.ip),
            vip_subnet_id=loadbalancer.subnet_id)
        self.assertIsNone(ret)
        m_driver.release_loadbalancer.assert_not_called()

    def test_find_loadbalancer_error(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1')
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        resp = iter([o_lb.LoadBalancer(id=loadbalancer_id, provider='haproxy',
                                       provisioning_status='ERROR')])
        lbaas.load_balancers.return_value = resp
        m_driver._get_vip_port.return_value = {'id': mock.sentinel.port_id}

        ret = cls._find_loadbalancer(m_driver, loadbalancer)
        lbaas.load_balancers.assert_called_once_with(
            name=loadbalancer.name,
            project_id=loadbalancer.project_id,
            vip_address=str(loadbalancer.ip),
            vip_subnet_id=loadbalancer.subnet_id)
        self.assertIsNone(ret)
        m_driver.release_loadbalancer.assert_called_once()

    def test_create_listener(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        listener = obj_lbaas.LBaaSListener(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            port=1234, loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        listener_id = 'A57B7771-6050-4CA8-A63C-443493EC98AB'
        req = {
            'name': listener.name,
            'project_id': listener.project_id,
            'loadbalancer_id': listener.loadbalancer_id,
            'protocol': listener.protocol,
            'protocol_port': listener.port}
        resp = o_lis.Listener(id=listener_id)
        m_driver._post_lb_resource.return_value = resp

        ret = cls._create_listener(m_driver, listener)
        m_driver._post_lb_resource.assert_called_once_with(o_lis.Listener, req)
        for attr in listener.obj_fields:
            self.assertEqual(getattr(listener, attr),
                             getattr(ret, attr))
        self.assertEqual(listener_id, ret.id)

    def test_find_listener(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        listener = obj_lbaas.LBaaSListener(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            port=1234, loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        listener_id = 'A57B7771-6050-4CA8-A63C-443493EC98AB'
        lbaas.listeners.return_value = iter([o_lis.Listener(id=listener_id)])

        ret = cls._find_listener(m_driver, listener)
        lbaas.listeners.assert_called_once_with(
            name=listener.name,
            project_id=listener.project_id,
            load_balancer_id=listener.loadbalancer_id,
            protocol=listener.protocol,
            protocol_port=listener.port)
        for attr in listener.obj_fields:
            self.assertEqual(getattr(listener, attr),
                             getattr(ret, attr))
        self.assertEqual(listener_id, ret.id)

    def test_find_listener_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        listener = obj_lbaas.LBaaSListener(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            port=1234, loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        resp = iter([])
        lbaas.listeners.return_value = resp

        ret = cls._find_listener(m_driver, listener)
        lbaas.listeners.assert_called_once_with(
            name=listener.name,
            project_id=listener.project_id,
            load_balancer_id=listener.loadbalancer_id,
            protocol=listener.protocol,
            protocol_port=listener.port)
        self.assertIsNone(ret)

    def test_create_pool(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lb_algorithm = 'ROUND_ROBIN'
        pool = obj_lbaas.LBaaSPool(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            listener_id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        pool_id = 'D4F35594-27EB-4F4C-930C-31DD40F53B77'
        req = {
            'name': pool.name,
            'project_id': pool.project_id,
            'listener_id': pool.listener_id,
            'loadbalancer_id': pool.loadbalancer_id,
            'protocol': pool.protocol,
            'lb_algorithm': lb_algorithm}
        resp = o_pool.Pool(id=pool_id)
        m_driver._post_lb_resource.return_value = resp

        ret = cls._create_pool(m_driver, pool)
        m_driver._post_lb_resource.assert_called_once_with(o_pool.Pool, req)
        for attr in pool.obj_fields:
            self.assertEqual(getattr(pool, attr),
                             getattr(ret, attr))
        self.assertEqual(pool_id, ret.id)

    def test_create_pool_conflict(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lb_algorithm = 'ROUND_ROBIN'
        pool = obj_lbaas.LBaaSPool(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            listener_id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        req = {
            'name': pool.name,
            'project_id': pool.project_id,
            'listener_id': pool.listener_id,
            'loadbalancer_id': pool.loadbalancer_id,
            'protocol': pool.protocol,
            'lb_algorithm': lb_algorithm}
        m_driver._post_lb_resource.side_effect = n_exc.StateInvalidClient

        self.assertRaises(n_exc.StateInvalidClient, cls._create_pool, m_driver,
                          pool)
        m_driver._post_lb_resource.assert_called_once_with(o_pool.Pool, req)

    def test_find_pool_by_listener(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        pool = obj_lbaas.LBaaSPool(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            listener_id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        pool_id = 'D4F35594-27EB-4F4C-930C-31DD40F53B77'
        resp = [o_pool.Pool(id=pool_id,
                            listeners=[{"id": pool.listener_id}])]
        lbaas.pools.return_value = resp

        ret = cls._find_pool(m_driver, pool)
        lbaas.pools.assert_called_once_with(
            name=pool.name,
            project_id=pool.project_id,
            loadbalancer_id=pool.loadbalancer_id,
            protocol=pool.protocol)
        for attr in pool.obj_fields:
            self.assertEqual(getattr(pool, attr),
                             getattr(ret, attr))
        self.assertEqual(pool_id, ret.id)

    def test_find_pool_by_listener_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        pool = obj_lbaas.LBaaSPool(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            listener_id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        resp = []
        lbaas.pools.return_value = resp

        ret = cls._find_pool(m_driver, pool)
        lbaas.pools.assert_called_once_with(
            name=pool.name,
            project_id=pool.project_id,
            loadbalancer_id=pool.loadbalancer_id,
            protocol=pool.protocol)
        self.assertIsNone(ret)

    def test_create_member(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        member = obj_lbaas.LBaaSMember(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            port=1234, subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            pool_id='D4F35594-27EB-4F4C-930C-31DD40F53B77')
        member_id = '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'
        req = {
            'name': member.name,
            'project_id': member.project_id,
            'subnet_id': member.subnet_id,
            'address': str(member.ip),
            'protocol_port': member.port}
        resp = o_mem.Member(id=member_id)
        m_driver._post_lb_resource.return_value = resp

        ret = cls._create_member(m_driver, member)
        m_driver._post_lb_resource.assert_called_once_with(
            o_mem.Member, req, pool_id=member.pool_id)
        for attr in member.obj_fields:
            self.assertEqual(getattr(member, attr),
                             getattr(ret, attr))
        self.assertEqual(member_id, ret.id)

    def test_find_member(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        member = obj_lbaas.LBaaSMember(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            port=1234, subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            pool_id='D4F35594-27EB-4F4C-930C-31DD40F53B77')
        member_id = '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'
        resp = iter([o_mem.Member(id=member_id)])
        lbaas.members.return_value = resp

        ret = cls._find_member(m_driver, member)
        lbaas.members.assert_called_once_with(
            member.pool_id,
            name=member.name,
            project_id=member.project_id,
            subnet_id=member.subnet_id,
            address=member.ip,
            protocol_port=member.port)
        for attr in member.obj_fields:
            self.assertEqual(getattr(member, attr),
                             getattr(ret, attr))
        self.assertEqual(member_id, ret.id)

    def test_find_member_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        member = obj_lbaas.LBaaSMember(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            port=1234, subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            pool_id='D4F35594-27EB-4F4C-930C-31DD40F53B77')
        resp = iter([])
        lbaas.members.return_value = resp

        ret = cls._find_member(m_driver, member)
        lbaas.members.assert_called_once_with(
            member.pool_id,
            name=member.name,
            project_id=member.project_id,
            subnet_id=member.subnet_id,
            address=member.ip,
            protocol_port=member.port)
        self.assertIsNone(ret)

    def test_ensure(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        obj = mock.Mock()
        m_create = mock.Mock()
        m_find = mock.Mock()
        expected_result = mock.sentinel.expected_result
        m_create.return_value = expected_result

        ret = cls._ensure(m_driver, obj, m_create, m_find)
        m_create.assert_called_once_with(obj)
        self.assertEqual(expected_result, ret)

    def _verify_ensure_with_exception(self, exception_value):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        obj = mock.Mock()
        m_create = mock.Mock()
        m_find = mock.Mock()
        expected_result = mock.sentinel.expected_result
        m_create.side_effect = exception_value
        m_find.return_value = expected_result

        ret = cls._ensure(m_driver, obj, m_create, m_find)
        m_create.assert_called_once_with(obj)
        m_find.assert_called_once_with(obj)
        self.assertEqual(expected_result, ret)

    def test_ensure_with_conflict(self):
        self._verify_ensure_with_exception(
            o_exc.ConflictException(http_status=409))

    def test_ensure_with_internalservererror(self):
        self._verify_ensure_with_exception(
            o_exc.HttpException(http_status=500))

    def test_ensure_with_httperrors(self):
        resp = requests.Response()
        resp.status_code = 409
        self._verify_ensure_with_exception(
            requests.exceptions.HTTPError(response=resp))
        resp.status_code = 500
        self._verify_ensure_with_exception(
            requests.exceptions.HTTPError(response=resp))

    def test_request(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.sentinel.loadbalancer
        obj = mock.sentinel.obj
        create = mock.sentinel.create
        find = mock.sentinel.find
        timer = [mock.sentinel.t0]
        m_driver._provisioning_timer.return_value = timer
        resp = requests.Response()
        resp.status_code = 400
        m_driver._ensure.side_effect = requests.exceptions.HTTPError(
            response=resp)

        self.assertRaises(requests.exceptions.HTTPError,
                          cls._ensure_provisioned, m_driver,
                          loadbalancer, obj, create, find)

        m_driver._wait_for_provisioning.assert_has_calls(
            [mock.call(loadbalancer, t, d_lbaasv2._LB_STS_POLL_FAST_INTERVAL)
             for t in timer])
        m_driver._ensure.assert_has_calls(
            [mock.call(obj, create, find) for _ in timer])

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
            [mock.call(obj, create, find) for _ in timer])

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
        m_delete.side_effect = [o_exc.BadRequestException, None]

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
        m_delete.side_effect = o_exc.NotFoundException

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
        m_delete.side_effect = o_exc.ConflictException

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
        loadbalancer = mock.Mock()
        timeout = mock.sentinel.timeout
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer
        resp = o_lb.LoadBalancer(provisioning_status='ACTIVE')
        lbaas.get_load_balancer.return_value = resp

        cls._wait_for_provisioning(m_driver, loadbalancer, timeout)

        lbaas.get_load_balancer.assert_called_once_with(loadbalancer.id)

    def test_wait_for_provisioning_not_ready(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.Mock()
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

    def test_get_pool_by_name_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)

        pools = o_pool.Pool(name='KUKU',
                            id='a2a62ea7-e3bf-40df-8c09-aa0c29876a6b')
        lbaas.pools.return_value = [pools]
        pool_name = 'NOT_KUKU'
        project_id = 'TEST_PROJECT'

        pool_id = cls.get_pool_by_name(m_driver, pool_name, project_id)
        self.assertIsNone(pool_id)

    def test_get_pool_by_name_found(self):
        self._test_get_pool_by_name_found(listener_is_empty=False)

    def test_get_pool_by_name_found_listener_is_empty(self):
        self._test_get_pool_by_name_found(listener_is_empty=True)

    def _test_get_pool_by_name_found(self, listener_is_empty):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)

        pool_name = 'KUKU'
        pool_lb_id = "607226db-27ef-4d41-ae89-f2a800e9c2db"
        pool_project_id = "e3cd678b11784734bc366148aa37580e"
        pool_id = "ddb2b28f-89e9-45d3-a329-a359c3e39e4a"
        pool_protocol = "HTTP"
        pool_listener_id = "023f2e34-7806-443b-bfae-16c324569a3d"

        if listener_is_empty:
            resp_listeners = []
        else:
            resp_listeners = [o_lis.Listener(id=pool_listener_id)]

        listener_id = (resp_listeners[0].id if resp_listeners else None)
        expected_result = obj_lbaas.LBaaSPool(
            name=pool_name, project_id=pool_project_id,
            loadbalancer_id=pool_lb_id,
            listener_id=listener_id,
            protocol=pool_protocol,
            id=pool_id)

        resp = [o_pool.Pool(
            protocol=pool_protocol,
            loadbalancers=[o_lb.LoadBalancer(id=pool_lb_id)],
            listeners=resp_listeners,
            project_id=pool_project_id,
            id=pool_id,
            name=pool_name,
        )]

        lbaas.pools.return_value = resp

        pool = cls.get_pool_by_name(m_driver, pool_name, pool_project_id)
        lbaas.pools.assert_called_once()
        for attr in expected_result.obj_fields:
            self.assertEqual(getattr(expected_result, attr),
                             getattr(pool, attr))

    def test_get_pool_by_name_empty_list(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        pools = {}
        lbaas.pools.return_value = [pools]
        pool_name = 'NOT_KUKU'
        project_id = 'TEST_PROJECT'

        pool = cls.get_pool_by_name(m_driver, pool_name, project_id)
        self.assertIsNone(pool)

    def test_get_lb_by_uuid(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)

        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        loadbalancer_vip = '1.2.3.4'
        loadbalancer_vip_port_id = '00EE9E11-91C2-41CF-8FD4-7970579EFFFF'
        loadbalancer_project_id = '00EE9E11-91C2-41CF-8FD4-7970579EAAAA'
        loadbalancer_name = 'MyName'
        loadbalancer_subnet_id = '00EE9E11-91C2-41CF-8FD4-7970579EBBBB'
        loadbalancer_provider = 'haproxy'

        expected_lb = obj_lbaas.LBaaSLoadBalancer(
            id=loadbalancer_id, port_id=loadbalancer_vip_port_id,
            name=loadbalancer_name, project_id=loadbalancer_project_id,
            subnet_id=loadbalancer_subnet_id, ip=loadbalancer_vip,
            security_groups=None, provider=loadbalancer_provider)

        resp = o_lb.LoadBalancer(id=loadbalancer_id,
                                 vip_port_id=loadbalancer_vip_port_id,
                                 name=loadbalancer_name,
                                 project_id=loadbalancer_project_id,
                                 vip_subnet_id=loadbalancer_subnet_id,
                                 vip_address=loadbalancer_vip,
                                 provider=loadbalancer_provider)

        lbaas.get_load_balancer.return_value = resp

        ret = cls.get_lb_by_uuid(m_driver, loadbalancer_id)
        lbaas.get_load_balancer.assert_called_once()
        for attr in expected_lb.obj_fields:
            self.assertEqual(getattr(expected_lb, attr),
                             getattr(ret, attr))
        self.assertEqual(loadbalancer_id, ret.id)

    def test_get_lb_by_uuid_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)

        resp = {'loadbalancer': {}}
        lbaas.get_load_balancer.return_value = resp

        requested_uuid = '00EE9E11-91C2-41CF-8FD4-7970579EFFFF'
        lbaas.get_load_balancer.side_effect = o_exc.ResourceNotFound

        ret = cls.get_lb_by_uuid(m_driver, requested_uuid)
        lbaas.get_load_balancer.assert_called_once()
        self.assertIsNone(ret)

    def test_ensure_l7policy(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        loadbalancer = mock.sentinel.expected_resp
        route_name = 'ROUTE_NAME'
        namespace = 'NAMESPACE'
        listener_id = 'D4F35594-27EB-4F4C-930C-31DD40F53B77'
        pool = obj_lbaas.LBaaSPool(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT',
            name='NAME',
            loadbalancer_id='010101',
            listener_id='12345',
            protocol='TCP'
        )

        m_driver._ensure_provisioned.return_value = expected_resp

        cls.ensure_l7_policy(
            m_driver, namespace, route_name, loadbalancer, pool, listener_id)

        m_driver._ensure_provisioned.assert_called_once_with(
            loadbalancer, mock.ANY, m_driver._create_l7_policy,
            m_driver._find_l7_policy)
        l7policy = m_driver._ensure_provisioned.call_args[0][1]

        self.assertEqual("%s%s" % (namespace, route_name), l7policy.name)
        self.assertEqual(listener_id, l7policy.listener_id)
        self.assertEqual(pool.id, l7policy.redirect_pool_id)
        self.assertEqual(pool.project_id, l7policy.project_id)

    def test_release_l7policy(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)

        loadbalancer = mock.Mock()
        l7_policy = mock.Mock()
        cls.release_l7_policy(m_driver, loadbalancer, l7_policy)

        m_driver._release.assert_called_once_with(
            loadbalancer, l7_policy, lbaas.delete_l7_policy,
            l7_policy.id)

    def test_create_l7policy(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)

        l7_policy = obj_lbaas.LBaaSL7Policy(
            name='TEST_NAME',
            project_id='TEST_PROJECT',
            listener_id='D4F35594-27EB-4F4C-930C-31DD40F53B77',
            redirect_pool_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1')

        l7policy_id = '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'
        req = {
            'action': 'REDIRECT_TO_POOL',
            'listener_id': l7_policy.listener_id,
            'name': l7_policy.name,
            'project_id': l7_policy.project_id,
            'redirect_pool_id': l7_policy.redirect_pool_id}
        resp = {'id': l7policy_id}
        m_driver._post_lb_resource.return_value = resp

        ret = cls._create_l7_policy(m_driver, l7_policy)
        m_driver._post_lb_resource.assert_called_once_with(o_l7p.L7Policy, req)
        for attr in l7_policy.obj_fields:
            self.assertEqual(getattr(l7_policy, attr),
                             getattr(ret, attr))
        self.assertEqual(l7policy_id, ret.id)

    def test_find_l7_policy(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        l7_policy = obj_lbaas.LBaaSL7Policy(
            name='TEST_NAME',
            project_id='TEST_PROJECT',
            listener_id='D4F35594-27EB-4F4C-930C-31DD40F53B77',
            redirect_pool_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1')

        l7policy_id = '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'

        resp = iter([o_l7p.L7Policy(id=l7policy_id)])
        lbaas.l7_policies.return_value = resp

        ret = cls._find_l7_policy(m_driver, l7_policy)
        lbaas.l7_policies.assert_called_once_with(
            name=l7_policy.name,
            project_id=l7_policy.project_id,
            redirect_pool_id=l7_policy.redirect_pool_id,
            listener_id=l7_policy.listener_id)
        for attr in l7_policy.obj_fields:
            self.assertEqual(getattr(l7_policy, attr),
                             getattr(ret, attr))
        self.assertEqual(l7policy_id, ret.id)

    def test_find_l7_policy_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        l7_policy = obj_lbaas.LBaaSL7Policy(
            name='TEST_NAME',
            project_id='TEST_PROJECT',
            listener_id='D4F35594-27EB-4F4C-930C-31DD40F53B77',
            redirect_pool_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1')

        resp = iter([])
        lbaas.l7_policies.return_value = resp

        ret = cls._find_l7_policy(m_driver, l7_policy)
        lbaas.l7_policies.assert_called_once_with(
            name=l7_policy.name,
            project_id=l7_policy.project_id,
            redirect_pool_id=l7_policy.redirect_pool_id,
            listener_id=l7_policy.listener_id)
        self.assertIsNone(ret)

    def test_ensure_l7_rule(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        loadbalancer = mock.sentinel.expected_resp
        compare_type = 'EQUAL_TO'
        type = 'HOST_NAME'
        value = 'www.test.com'
        l7_policy = obj_lbaas.LBaaSL7Policy(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            name='TEST_NAME',
            project_id='TEST_PROJECT',
            listener_id='D4F35594-27EB-4F4C-930C-31DD40F53B77',
            redirect_pool_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1')

        m_driver._ensure_provisioned.return_value = expected_resp

        cls.ensure_l7_rule(
            m_driver, loadbalancer, l7_policy, compare_type, type, value)

        m_driver._ensure_provisioned.assert_called_once_with(
            loadbalancer, mock.ANY, m_driver._create_l7_rule,
            m_driver._find_l7_rule)
        l7rule = m_driver._ensure_provisioned.call_args[0][1]

        self.assertEqual(compare_type, l7rule.compare_type)
        self.assertEqual(type, l7rule.type)
        self.assertEqual(value, l7rule.value)

    def test_release_l7_rule(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)

        loadbalancer = mock.Mock()
        l7_rule = mock.Mock()
        cls.release_l7_rule(m_driver, loadbalancer, l7_rule)

        m_driver._release.assert_called_once_with(
            loadbalancer, l7_rule, lbaas.delete_l7_rule,
            l7_rule.id, l7_rule.l7policy_id)

    def test_create_l7_rule(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)

        l7_rule = obj_lbaas.LBaaSL7Rule(
            compare_type='EQUAL_TO',
            l7policy_id='D4F35594-27EB-4F4C-930C-31DD40F53B77',
            type='HOST_NAME',
            value='www.test.com')

        l7_rule_id = '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'

        req = {'compare_type': l7_rule.compare_type,
               'type': l7_rule.type,
               'value': l7_rule.value}

        resp = {'id': l7_rule_id}
        m_driver._post_lb_resource.return_value = resp

        ret = cls._create_l7_rule(m_driver, l7_rule)
        m_driver._post_lb_resource.assert_called_once_with(
            o_l7r.L7Rule, req, l7policy_id=l7_rule.l7policy_id)
        for attr in l7_rule.obj_fields:
            self.assertEqual(getattr(l7_rule, attr),
                             getattr(ret, attr))
        self.assertEqual(l7_rule_id, ret.id)

    def test_find_l7_rule(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        l7_rule = obj_lbaas.LBaaSL7Rule(
            compare_type='EQUAL_TO',
            l7policy_id='D4F35594-27EB-4F4C-930C-31DD40F53B77',
            type='HOST_NAME',
            value='www.test.com')

        l7_rule_id = '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'
        resp = iter([o_l7r.L7Rule(id=l7_rule_id)])
        lbaas.l7_rules.return_value = resp

        ret = cls._find_l7_rule(m_driver, l7_rule)
        lbaas.l7_rules.assert_called_once_with(
            l7_rule.l7policy_id,
            type=l7_rule.type,
            value=l7_rule.value,
            compare_type=l7_rule.compare_type)

        for attr in l7_rule.obj_fields:
            self.assertEqual(getattr(l7_rule, attr),
                             getattr(ret, attr))
        self.assertEqual(l7_rule_id, ret.id)

    def test_find_l7_rule_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        l7_rule = obj_lbaas.LBaaSL7Rule(
            compare_type='EQUAL_TO',
            l7policy_id='D4F35594-27EB-4F4C-930C-31DD40F53B77',
            type='HOST_NAME',
            value='www.test.com')

        resp = iter([])
        lbaas.l7_rules.return_value = resp

        ret = cls._find_l7_rule(m_driver, l7_rule)
        lbaas.l7_rules.assert_called_once_with(
            l7_rule.l7policy_id,
            type=l7_rule.type,
            value=l7_rule.value,
            compare_type=l7_rule.compare_type)
        self.assertIsNone(ret)
