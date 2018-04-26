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

from neutronclient.common import exceptions as n_exc

from kuryr_kubernetes.controller.drivers import lbaasv2 as d_lbaasv2
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


class TestLBaaSv2Driver(test_base.TestCase):
    def test_ensure_loadbalancer(self):
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = obj_lbaas.LBaaSLoadBalancer(
            provider='octavia', port_id='D3FA400A-F543-4B91-9CD3-047AF0CE42E2',
            security_groups=[])
        namespace = 'TEST_NAMESPACE'
        name = 'TEST_NAME'
        project_id = 'TEST_PROJECT'
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        sg_ids = ['foo', 'bar']
        endpoints = {'metadata': {'namespace': namespace, 'name': name}}

        m_driver._ensure.return_value = expected_resp
        neutron.update_port = mock.Mock()
        resp = cls.ensure_loadbalancer(m_driver, endpoints, project_id,
                                       subnet_id, ip, sg_ids, 'ClusterIP')
        m_driver._ensure.assert_called_once_with(mock.ANY,
                                                 m_driver._create_loadbalancer,
                                                 m_driver._find_loadbalancer)
        req = m_driver._ensure.call_args[0][0]
        self.assertEqual("%s/%s" % (namespace, name), req.name)
        self.assertEqual(project_id, req.project_id)
        self.assertEqual(subnet_id, req.subnet_id)
        self.assertEqual(ip, str(req.ip))
        self.assertEqual(expected_resp, resp)
        neutron.update_port.assert_not_called()

    def test_ensure_loadbalancer_not_ready(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        namespace = 'TEST_NAMESPACE'
        name = 'TEST_NAME'
        project_id = 'TEST_PROJECT'
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        # TODO(ivc): handle security groups
        sg_ids = []
        endpoints = {'metadata': {'namespace': namespace, 'name': name}}

        m_driver._ensure.return_value = None
        self.assertRaises(k_exc.ResourceNotReady, cls.ensure_loadbalancer,
                          m_driver, endpoints, project_id, subnet_id, ip,
                          sg_ids, 'ClusterIP')

    def test_release_loadbalancer(self):
        self.useFixture(k_fix.MockNeutronClient()).client
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lbaas.cascading_capable = False
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        endpoints = mock.sentinel.endpoints
        loadbalancer = mock.Mock()

        cls.release_loadbalancer(m_driver, endpoints, loadbalancer)

        m_driver._release.assert_called_once_with(loadbalancer, loadbalancer,
                                                  lbaas.delete_loadbalancer,
                                                  loadbalancer.id)

    def test_cascade_release_loadbalancer(self):
        self.useFixture(k_fix.MockNeutronClient()).client
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lbaas.cascading_capable = True
        lbaas.lbaas_loadbalancer_path = "boo %s"
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        endpoints = mock.sentinel.endpoints
        loadbalancer = mock.Mock()

        cls.release_loadbalancer(m_driver, endpoints, loadbalancer)

        m_driver._release.assert_called_once_with(
            loadbalancer, loadbalancer, lbaas.delete,
            lbaas.lbaas_loadbalancer_path % loadbalancer.id,
            params={'cascade': True})

    def test_ensure_listener(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        namespace = 'TEST_NAMESPACE'
        name = 'TEST_NAME'
        project_id = 'TEST_PROJECT'
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        protocol = 'TCP'
        port = 1234
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            id=loadbalancer_id, name=name, project_id=project_id,
            subnet_id=subnet_id, ip=ip)
        # TODO(ivc): handle security groups
        endpoints = {'metadata': {'namespace': namespace, 'name': name}}
        m_driver._ensure_provisioned.return_value = expected_resp

        resp = cls.ensure_listener(m_driver, endpoints, loadbalancer,
                                   protocol, port)

        m_driver._ensure_provisioned.assert_called_once_with(
            loadbalancer, mock.ANY, m_driver._create_listener,
            m_driver._find_listener)
        listener = m_driver._ensure_provisioned.call_args[0][1]
        self.assertEqual("%s/%s:%s:%s" % (namespace, name, protocol, port),
                         listener.name)
        self.assertEqual(project_id, listener.project_id)
        self.assertEqual(loadbalancer_id, listener.loadbalancer_id)
        self.assertEqual(protocol, listener.protocol)
        self.assertEqual(port, listener.port)
        self.assertEqual(expected_resp, resp)

    def test_release_listener(self):
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        neutron.list_security_group_rules.return_value = {
            'security_group_rules': []}
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        endpoints = mock.sentinel.endpoints
        loadbalancer = mock.Mock()
        listener = mock.Mock()

        cls.release_listener(m_driver, endpoints, loadbalancer, listener)

        m_driver._release.assert_called_once_with(loadbalancer, listener,
                                                  lbaas.delete_listener,
                                                  listener.id)

    def test_ensure_pool(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        endpoints = mock.sentinel.endpoints
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        listener = obj_lbaas.LBaaSListener(
            id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            name='TEST_LISTENER_NAME',
            protocol='TCP')
        m_driver._ensure_provisioned.return_value = expected_resp

        resp = cls.ensure_pool(m_driver, endpoints, loadbalancer, listener)

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
        endpoints = mock.sentinel.endpoints
        loadbalancer = mock.Mock()
        pool = mock.Mock()

        cls.release_pool(m_driver, endpoints, loadbalancer, pool)

        m_driver._release.assert_called_once_with(loadbalancer, pool,
                                                  lbaas.delete_lbaas_pool,
                                                  pool.id)

    def test_ensure_member(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        expected_resp = mock.sentinel.expected_resp
        endpoints = mock.sentinel.endpoints
        loadbalancer = mock.sentinel.loadbalancer
        pool = obj_lbaas.LBaaSPool(project_id='TEST_PROJECT',
                                   id='D4F35594-27EB-4F4C-930C-31DD40F53B77')
        subnet_id = 'D3FA400A-F543-4B91-9CD3-047AF0CE42D1'
        ip = '1.2.3.4'
        port = 1234
        namespace = 'TEST_NAMESPACE'
        name = 'TEST_NAME'
        target_ref = {'namespace': namespace, 'name': name}
        m_driver._ensure_provisioned.return_value = expected_resp

        resp = cls.ensure_member(m_driver, endpoints, loadbalancer, pool,
                                 subnet_id, ip, port, target_ref)

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
        endpoints = mock.sentinel.endpoints
        loadbalancer = mock.Mock()
        member = mock.Mock()

        cls.release_member(m_driver, endpoints, loadbalancer, member)

        m_driver._release.assert_called_once_with(loadbalancer, member,
                                                  lbaas.delete_lbaas_member,
                                                  member.id, member.pool_id)

    def test_create_loadbalancer(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            security_groups=[])
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        req = {'loadbalancer': {
            'name': loadbalancer.name,
            'project_id': loadbalancer.project_id,
            'vip_address': str(loadbalancer.ip),
            'vip_subnet_id': loadbalancer.subnet_id,
        }}
        resp = {'loadbalancer': {'id': loadbalancer_id, 'provider': 'haproxy'}}
        lbaas.create_loadbalancer.return_value = resp

        ret = cls._create_loadbalancer(m_driver, loadbalancer)
        lbaas.create_loadbalancer.assert_called_once_with(req)
        for attr in loadbalancer.obj_fields:
            self.assertEqual(getattr(loadbalancer, attr),
                             getattr(ret, attr))
        self.assertEqual(loadbalancer_id, ret.id)

    def test_find_loadbalancer(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            provider='haproxy', security_groups=[])
        loadbalancer_id = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        resp = {'loadbalancers': [{'id': loadbalancer_id,
                                   'provider': 'haproxy'}]}
        lbaas.list_loadbalancers.return_value = resp

        ret = cls._find_loadbalancer(m_driver, loadbalancer)
        lbaas.list_loadbalancers.assert_called_once_with(
            name=loadbalancer.name,
            project_id=loadbalancer.project_id,
            vip_address=str(loadbalancer.ip),
            vip_subnet_id=loadbalancer.subnet_id)
        for attr in loadbalancer.obj_fields:
            self.assertEqual(getattr(loadbalancer, attr),
                             getattr(ret, attr))
        self.assertEqual(loadbalancer_id, ret.id)

    def test_find_loadbalancer_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1')
        resp = {'loadbalancers': []}
        lbaas.list_loadbalancers.return_value = resp

        ret = cls._find_loadbalancer(m_driver, loadbalancer)
        lbaas.list_loadbalancers.assert_called_once_with(
            name=loadbalancer.name,
            project_id=loadbalancer.project_id,
            vip_address=str(loadbalancer.ip),
            vip_subnet_id=loadbalancer.subnet_id)
        self.assertIsNone(ret)

    def test_create_listener(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        listener = obj_lbaas.LBaaSListener(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            port=1234, loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        listener_id = 'A57B7771-6050-4CA8-A63C-443493EC98AB'
        req = {'listener': {
            'name': listener.name,
            'project_id': listener.project_id,
            'loadbalancer_id': listener.loadbalancer_id,
            'protocol': listener.protocol,
            'protocol_port': listener.port}}
        resp = {'listener': {'id': listener_id}}
        lbaas.create_listener.return_value = resp

        ret = cls._create_listener(m_driver, listener)
        lbaas.create_listener.assert_called_once_with(req)
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
        resp = {'listeners': [{'id': listener_id}]}
        lbaas.list_listeners.return_value = resp

        ret = cls._find_listener(m_driver, listener)
        lbaas.list_listeners.assert_called_once_with(
            name=listener.name,
            project_id=listener.project_id,
            loadbalancer_id=listener.loadbalancer_id,
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
        resp = {'listeners': []}
        lbaas.list_listeners.return_value = resp

        ret = cls._find_listener(m_driver, listener)
        lbaas.list_listeners.assert_called_once_with(
            name=listener.name,
            project_id=listener.project_id,
            loadbalancer_id=listener.loadbalancer_id,
            protocol=listener.protocol,
            protocol_port=listener.port)
        self.assertIsNone(ret)

    def test_create_pool(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lb_algorithm = 'ROUND_ROBIN'
        pool = obj_lbaas.LBaaSPool(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            listener_id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        pool_id = 'D4F35594-27EB-4F4C-930C-31DD40F53B77'
        req = {'pool': {
            'name': pool.name,
            'project_id': pool.project_id,
            'listener_id': pool.listener_id,
            'loadbalancer_id': pool.loadbalancer_id,
            'protocol': pool.protocol,
            'lb_algorithm': lb_algorithm}}
        resp = {'pool': {'id': pool_id}}
        lbaas.create_lbaas_pool.return_value = resp

        ret = cls._create_pool(m_driver, pool)
        lbaas.create_lbaas_pool.assert_called_once_with(req)
        for attr in pool.obj_fields:
            self.assertEqual(getattr(pool, attr),
                             getattr(ret, attr))
        self.assertEqual(pool_id, ret.id)

    def test_create_pool_conflict(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        lb_algorithm = 'ROUND_ROBIN'
        pool = obj_lbaas.LBaaSPool(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            listener_id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        req = {'pool': {
            'name': pool.name,
            'project_id': pool.project_id,
            'listener_id': pool.listener_id,
            'loadbalancer_id': pool.loadbalancer_id,
            'protocol': pool.protocol,
            'lb_algorithm': lb_algorithm}}
        lbaas.create_lbaas_pool.side_effect = n_exc.StateInvalidClient

        self.assertRaises(n_exc.StateInvalidClient, cls._create_pool, m_driver,
                          pool)
        lbaas.create_lbaas_pool.assert_called_once_with(req)
        m_driver._cleanup_bogus_pool.assert_called_once_with(lbaas, pool,
                                                             lb_algorithm)

    def test_cleanup_bogus_pool(self):
        # TODO(ivc): add unit test or get rid of _cleanup_bogus_pool
        self.skipTest("not implemented")

    def test_find_pool(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        pool = obj_lbaas.LBaaSPool(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            listener_id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        pool_id = 'D4F35594-27EB-4F4C-930C-31DD40F53B77'
        resp = {'pools': [{'id': pool_id,
                           'listeners': [{'id': pool.listener_id}]}]}
        lbaas.list_lbaas_pools.return_value = resp

        ret = cls._find_pool(m_driver, pool)
        lbaas.list_lbaas_pools.assert_called_once_with(
            name=pool.name,
            project_id=pool.project_id,
            loadbalancer_id=pool.loadbalancer_id,
            protocol=pool.protocol)
        for attr in pool.obj_fields:
            self.assertEqual(getattr(pool, attr),
                             getattr(ret, attr))
        self.assertEqual(pool_id, ret.id)

    def test_find_pool_not_found(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        pool = obj_lbaas.LBaaSPool(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            listener_id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        resp = {'pools': []}
        lbaas.list_lbaas_pools.return_value = resp

        ret = cls._find_pool(m_driver, pool)
        lbaas.list_lbaas_pools.assert_called_once_with(
            name=pool.name,
            project_id=pool.project_id,
            loadbalancer_id=pool.loadbalancer_id,
            protocol=pool.protocol)
        self.assertIsNone(ret)

    def test_create_member(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        member = obj_lbaas.LBaaSMember(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            port=1234, subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            pool_id='D4F35594-27EB-4F4C-930C-31DD40F53B77')
        member_id = '3A70CEC0-392D-4BC1-A27C-06E63A0FD54F'
        req = {'member': {
            'name': member.name,
            'project_id': member.project_id,
            'subnet_id': member.subnet_id,
            'address': str(member.ip),
            'protocol_port': member.port}}
        resp = {'member': {'id': member_id}}
        lbaas.create_lbaas_member.return_value = resp

        ret = cls._create_member(m_driver, member)
        lbaas.create_lbaas_member.assert_called_once_with(
            member.pool_id, req)
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
        resp = {'members': [{'id': member_id}]}
        lbaas.list_lbaas_members.return_value = resp

        ret = cls._find_member(m_driver, member)
        lbaas.list_lbaas_members.assert_called_once_with(
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
        resp = {'members': []}
        lbaas.list_lbaas_members.return_value = resp

        ret = cls._find_member(m_driver, member)
        lbaas.list_lbaas_members.assert_called_once_with(
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

    def test_ensure_with_conflict(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        obj = mock.Mock()
        m_create = mock.Mock()
        m_find = mock.Mock()
        expected_result = mock.sentinel.expected_result
        m_create.side_effect = n_exc.Conflict
        m_find.return_value = expected_result

        ret = cls._ensure(m_driver, obj, m_create, m_find)
        m_create.assert_called_once_with(obj)
        m_find.assert_called_once_with(obj)
        self.assertEqual(expected_result, ret)

    def test_request(self):
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.sentinel.loadbalancer
        obj = mock.sentinel.obj
        create = mock.sentinel.create
        find = mock.sentinel.find
        expected_result = mock.sentinel.expected_result
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer
        m_driver._ensure.side_effect = [n_exc.StateInvalidClient,
                                        expected_result]

        ret = cls._ensure_provisioned(m_driver, loadbalancer, obj, create,
                                      find)

        m_driver._wait_for_provisioning.assert_has_calls(
            [mock.call(loadbalancer, t) for t in timer])
        m_driver._ensure.assert_has_calls(
            [mock.call(obj, create, find) for _ in timer])
        self.assertEqual(expected_result, ret)

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
            [mock.call(loadbalancer, t) for t in timer])
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
        m_delete.side_effect = [n_exc.StateInvalidClient, None]

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
        m_delete.side_effect = n_exc.NotFound

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
        m_delete.side_effect = n_exc.StateInvalidClient

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
        resp = {'loadbalancer': {'provisioning_status': 'ACTIVE'}}
        lbaas.show_loadbalancer.return_value = resp

        cls._wait_for_provisioning(m_driver, loadbalancer, timeout)

        lbaas.show_loadbalancer.assert_called_once_with(loadbalancer.id)

    def test_wait_for_provisioning_not_ready(self):
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        cls = d_lbaasv2.LBaaSv2Driver
        m_driver = mock.Mock(spec=d_lbaasv2.LBaaSv2Driver)
        loadbalancer = mock.Mock()
        timeout = mock.sentinel.timeout
        timer = [mock.sentinel.t0, mock.sentinel.t1]
        m_driver._provisioning_timer.return_value = timer
        resp = {'loadbalancer': {'provisioning_status': 'NOT_ACTIVE'}}
        lbaas.show_loadbalancer.return_value = resp

        self.assertRaises(k_exc.ResourceNotReady, cls._wait_for_provisioning,
                          m_driver, loadbalancer, timeout)

        self.assertEqual(len(timer), lbaas.show_loadbalancer.call_count)

    def test_provisioning_timer(self):
        # REVISIT(ivc): add test if _provisioning_timer is to stay
        self.skipTest("not implemented")
