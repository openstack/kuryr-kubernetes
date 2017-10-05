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

import itertools
import mock
import os_vif.objects.network as osv_network
import os_vif.objects.subnet as osv_subnet
from oslo_utils import uuidutils

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes.controller.handlers import lbaas as h_lbaas
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.tests import base as test_base


class TestLBaaSSpecHandler(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.ServiceSecurityGroupsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.ServiceSubnetsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.ServiceProjectDriver.get_instance')
    def test_init(self, m_get_drv_project, m_get_drv_subnets, m_get_drv_sg):
        m_get_drv_project.return_value = mock.sentinel.drv_project
        m_get_drv_subnets.return_value = mock.sentinel.drv_subnets
        m_get_drv_sg.return_value = mock.sentinel.drv_sg
        handler = h_lbaas.LBaaSSpecHandler()

        self.assertEqual(mock.sentinel.drv_project, handler._drv_project)
        self.assertEqual(mock.sentinel.drv_subnets, handler._drv_subnets)
        self.assertEqual(mock.sentinel.drv_sg, handler._drv_sg)

    def test_on_present(self):
        svc_event = mock.sentinel.svc_event
        old_spec = mock.sentinel.old_spec
        new_spec = mock.sentinel.new_spec

        project_id = mock.sentinel.project_id
        m_drv_project = mock.Mock()
        m_drv_project.get_project.return_value = project_id

        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_handler._get_lbaas_spec.return_value = old_spec
        m_handler._has_lbaas_spec_changes.return_value = True
        m_handler._generate_lbaas_spec.return_value = new_spec
        m_handler._should_ignore.return_value = False
        m_handler._drv_project = m_drv_project

        h_lbaas.LBaaSSpecHandler.on_present(m_handler, svc_event)

        m_handler._get_lbaas_spec.assert_called_once_with(svc_event)
        m_handler._has_lbaas_spec_changes.assert_called_once_with(svc_event,
                                                                  old_spec)
        m_handler._generate_lbaas_spec.assert_called_once_with(svc_event)
        m_handler._set_lbaas_spec.assert_called_once_with(svc_event, new_spec)

    def test_on_present_no_changes(self):
        svc_event = mock.sentinel.svc_event
        old_spec = mock.sentinel.old_spec

        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_handler._get_lbaas_spec.return_value = old_spec
        m_handler._has_lbaas_spec_changes.return_value = False
        m_handler._should_ignore.return_value = False

        h_lbaas.LBaaSSpecHandler.on_present(m_handler, svc_event)

        m_handler._get_lbaas_spec.assert_called_once_with(svc_event)
        m_handler._has_lbaas_spec_changes.assert_called_once_with(svc_event,
                                                                  old_spec)
        m_handler._generate_lbaas_spec.assert_not_called()
        m_handler._set_lbaas_spec.assert_not_called()

    def test_on_present_no_selector(self):
        svc_event = mock.sentinel.svc_event
        old_spec = mock.sentinel.old_spec

        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_handler._get_lbaas_spec.return_value = old_spec
        m_handler._should_ignore.return_value = True

        h_lbaas.LBaaSSpecHandler.on_present(m_handler, svc_event)

        m_handler._get_lbaas_spec.assert_called_once_with(svc_event)
        m_handler._has_lbaas_spec_changes.assert_not_called()
        m_handler._generate_lbaas_spec.assert_not_called()
        m_handler._set_lbaas_spec.assert_not_called()

    def test_get_service_ip(self):
        svc_body = {'spec': {'type': 'ClusterIP',
                             'clusterIP': mock.sentinel.cluster_ip}}
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)

        ret = h_lbaas.LBaaSSpecHandler._get_service_ip(m_handler, svc_body)
        self.assertEqual(mock.sentinel.cluster_ip, ret)

        svc_body = {'spec': {'type': 'LoadBalancer',
                             'clusterIP': mock.sentinel.cluster_ip}}
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)

        ret = h_lbaas.LBaaSSpecHandler._get_service_ip(m_handler, svc_body)
        self.assertEqual(mock.sentinel.cluster_ip, ret)

    def test_is_supported_type_clusterip(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        svc_body = {'spec': {'type': 'ClusterIP',
                             'clusterIP': mock.sentinel.cluster_ip}}

        ret = h_lbaas.LBaaSSpecHandler._is_supported_type(m_handler, svc_body)
        self.assertEqual(ret, True)

    def test_is_supported_type_loadbalancer(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        svc_body = {'spec': {'type': 'LoadBalancer',
                             'clusterIP': mock.sentinel.cluster_ip}}

        ret = h_lbaas.LBaaSSpecHandler._is_supported_type(m_handler, svc_body)
        self.assertEqual(ret, True)

    def _make_test_net_obj(self, cidr_list):
        subnets = [osv_subnet.Subnet(cidr=cidr) for cidr in cidr_list]
        subnets_list = osv_subnet.SubnetList(objects=subnets)
        return osv_network.Network(subnets=subnets_list)

    def test_generate_lbaas_spec(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)

        service = mock.sentinel.service
        project_id = mock.sentinel.project_id
        ip = mock.sentinel.ip
        subnet_id = mock.sentinel.subnet_id
        ports = mock.sentinel.ports
        sg_ids = mock.sentinel.sg_ids

        m_drv_project = mock.Mock()
        m_drv_project.get_project.return_value = project_id
        m_drv_sg = mock.Mock()
        m_drv_sg.get_security_groups.return_value = sg_ids
        m_handler._drv_project = m_drv_project
        m_handler._drv_sg = m_drv_sg
        m_handler._get_service_ip.return_value = ip
        m_handler._get_subnet_id.return_value = subnet_id
        m_handler._generate_lbaas_port_specs.return_value = ports

        spec_ctor_path = 'kuryr_kubernetes.objects.lbaas.LBaaSServiceSpec'
        with mock.patch(spec_ctor_path) as m_spec_ctor:
            m_spec_ctor.return_value = mock.sentinel.ret_obj
            service = {'spec': {'type': 'ClusterIP'}}

            ret_obj = h_lbaas.LBaaSSpecHandler._generate_lbaas_spec(
                m_handler, service)
            self.assertEqual(mock.sentinel.ret_obj, ret_obj)
            m_spec_ctor.assert_called_once_with(
                ip=ip,
                project_id=project_id,
                subnet_id=subnet_id,
                ports=ports,
                security_groups_ids=sg_ids,
                type='ClusterIP',
                lb_ip=None)

        m_drv_project.get_project.assert_called_once_with(service)
        m_handler._get_service_ip.assert_called_once_with(service)
        m_handler._get_subnet_id.assert_called_once_with(
            service, project_id, ip)
        m_handler._generate_lbaas_port_specs.assert_called_once_with(service)
        m_drv_sg.get_security_groups.assert_called_once_with(
            service, project_id)

    def test_has_lbaas_spec_changes(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        service = mock.sentinel.service
        lbaas_spec = mock.sentinel.lbaas_spec

        for has_ip_changes in (True, False):
            for has_port_changes in (True, False):
                m_handler._has_ip_changes.return_value = has_ip_changes
                m_handler._has_port_changes.return_value = has_port_changes
                ret = h_lbaas.LBaaSSpecHandler._has_lbaas_spec_changes(
                    m_handler, service, lbaas_spec)
                self.assertEqual(has_ip_changes or has_port_changes, ret)

    def test_get_service_ports(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        service = {'spec': {'ports': [
            {'port': 1},
            {'port': 2, 'name': 'X', 'protocol': 'UDP'}
        ]}}
        expected_ret = [
            {'port': 1, 'name': None, 'protocol': 'TCP'},
            {'port': 2, 'name': 'X', 'protocol': 'UDP'}]

        ret = h_lbaas.LBaaSSpecHandler._get_service_ports(m_handler, service)
        self.assertEqual(expected_ret, ret)

    def test_has_port_changes(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_service = mock.MagicMock()
        m_handler._get_service_ports.return_value = [
            {'port': 1, 'name': 'X', 'protocol': 'TCP'},
        ]

        m_lbaas_spec = mock.MagicMock()
        m_lbaas_spec.ports = [
            obj_lbaas.LBaaSPortSpec(name='X', protocol='TCP', port=1),
            obj_lbaas.LBaaSPortSpec(name='Y', protocol='TCP', port=2),
        ]

        ret = h_lbaas.LBaaSSpecHandler._has_port_changes(
            m_handler, m_service, m_lbaas_spec)

        self.assertTrue(ret)

    def test_has_port_changes__no_changes(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_service = mock.MagicMock()
        m_handler._get_service_ports.return_value = [
            {'port': 1, 'name': 'X', 'protocol': 'TCP'},
            {'port': 2, 'name': 'Y', 'protocol': 'TCP'}
        ]

        m_lbaas_spec = mock.MagicMock()
        m_lbaas_spec.ports = [
            obj_lbaas.LBaaSPortSpec(name='X', protocol='TCP', port=1),
            obj_lbaas.LBaaSPortSpec(name='Y', protocol='TCP', port=2),
        ]

        ret = h_lbaas.LBaaSSpecHandler._has_port_changes(
            m_handler, m_service, m_lbaas_spec)

        self.assertFalse(ret)

    def test_has_ip_changes(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_service = mock.MagicMock()
        m_handler._get_service_ip.return_value = '1.1.1.1'
        m_lbaas_spec = mock.MagicMock()
        m_lbaas_spec.ip.__str__.return_value = '2.2.2.2'

        ret = h_lbaas.LBaaSSpecHandler._has_ip_changes(
            m_handler, m_service, m_lbaas_spec)
        self.assertTrue(ret)

    def test_has_ip_changes__no_changes(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_service = mock.MagicMock()
        m_handler._get_service_ip.return_value = '1.1.1.1'
        m_lbaas_spec = mock.MagicMock()
        m_lbaas_spec.ip.__str__.return_value = '1.1.1.1'

        ret = h_lbaas.LBaaSSpecHandler._has_ip_changes(
            m_handler, m_service, m_lbaas_spec)
        self.assertFalse(ret)

    def test_has_ip_changes__no_spec(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_service = mock.MagicMock()
        m_handler._get_service_ip.return_value = '1.1.1.1'
        m_lbaas_spec = None

        ret = h_lbaas.LBaaSSpecHandler._has_ip_changes(
            m_handler, m_service, m_lbaas_spec)
        self.assertTrue(ret)

    def test_has_ip_changes__no_nothing(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_service = mock.MagicMock()
        m_handler._get_service_ip.return_value = None
        m_lbaas_spec = None

        ret = h_lbaas.LBaaSSpecHandler._has_ip_changes(
            m_handler, m_service, m_lbaas_spec)
        self.assertFalse(ret)

    def test_generate_lbaas_port_specs(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_handler._get_service_ports.return_value = [
            {'port': 1, 'name': 'X', 'protocol': 'TCP'},
            {'port': 2, 'name': 'Y', 'protocol': 'TCP'}
        ]
        expected_ports = [
            obj_lbaas.LBaaSPortSpec(name='X', protocol='TCP', port=1),
            obj_lbaas.LBaaSPortSpec(name='Y', protocol='TCP', port=2),
        ]

        ret = h_lbaas.LBaaSSpecHandler._generate_lbaas_port_specs(
            m_handler, mock.sentinel.service)
        self.assertEqual(expected_ports, ret)
        m_handler._get_service_ports.assert_called_once_with(
            mock.sentinel.service)

    def test_get_endpoints_link(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        service = {'metadata': {
            'selfLink': "/api/v1/namespaces/default/services/test"}}
        ret = h_lbaas.LBaaSSpecHandler._get_endpoints_link(m_handler, service)
        expected_link = "/api/v1/namespaces/default/endpoints/test"
        self.assertEqual(expected_link, ret)

    def test_get_endpoints_link__integrity_error(self):
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        service = {'metadata': {
            'selfLink': "/api/v1/namespaces/default/not-services/test"}}
        self.assertRaises(k_exc.IntegrityError,
                          h_lbaas.LBaaSSpecHandler._get_endpoints_link,
                          m_handler, service)

    def test_set_lbaas_spec(self):
        self.skipTest("skipping until generalised annotation handling is "
                      "implemented")

    def test_get_lbaas_spec(self):
        self.skipTest("skipping until generalised annotation handling is "
                      "implemented")


class FakeLBaaSDriver(drv_base.LBaaSDriver):
    def ensure_loadbalancer(self, endpoints, project_id, subnet_id, ip,
                            security_groups_ids):
        name = str(ip)
        return obj_lbaas.LBaaSLoadBalancer(name=name,
                                           project_id=project_id,
                                           subnet_id=subnet_id,
                                           ip=ip,
                                           id=uuidutils.generate_uuid())

    def ensure_listener(self, endpoints, loadbalancer, protocol, port):
        name = "%s:%s:%s" % (loadbalancer.name, protocol, port)
        return obj_lbaas.LBaaSListener(name=name,
                                       project_id=loadbalancer.project_id,
                                       loadbalancer_id=loadbalancer.id,
                                       protocol=protocol,
                                       port=port,
                                       id=uuidutils.generate_uuid())

    def ensure_pool(self, endpoints, loadbalancer, listener):
        return obj_lbaas.LBaaSPool(name=listener.name,
                                   project_id=loadbalancer.project_id,
                                   loadbalancer_id=loadbalancer.id,
                                   listener_id=listener.id,
                                   protocol=listener.protocol,
                                   id=uuidutils.generate_uuid())

    def ensure_member(self, endpoints, loadbalancer, pool, subnet_id, ip, port,
                      target_ref):
        name = "%s:%s:%s" % (loadbalancer.name, ip, port)
        return obj_lbaas.LBaaSMember(name=name,
                                     project_id=pool.project_id,
                                     pool_id=pool.id,
                                     subnet_id=subnet_id,
                                     ip=ip,
                                     port=port,
                                     id=uuidutils.generate_uuid())

    def release_loadbalancer(self, endpoints, loadbalancer):
        pass

    def release_listener(self, endpoints, loadbalancer, listener):
        pass

    def release_pool(self, endpoints, loadbalancer, pool):
        pass

    def release_member(self, endpoints, loadbalancer, member):
        pass


class TestLoadBalancerHandler(test_base.TestCase):
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.ServicePubIpDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodSubnetsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    def test_init(self, m_get_drv_lbaas, m_get_drv_project,
                  m_get_drv_subnets, m_get_drv_service_pub_ip):
        m_get_drv_lbaas.return_value = mock.sentinel.drv_lbaas
        m_get_drv_project.return_value = mock.sentinel.drv_project
        m_get_drv_subnets.return_value = mock.sentinel.drv_subnets
        m_get_drv_service_pub_ip.return_value = mock.sentinel.drv_lb_ip
        handler = h_lbaas.LoadBalancerHandler()

        self.assertEqual(mock.sentinel.drv_lbaas, handler._drv_lbaas)
        self.assertEqual(mock.sentinel.drv_project, handler._drv_pod_project)
        self.assertEqual(mock.sentinel.drv_subnets, handler._drv_pod_subnets)
        self.assertEqual(mock.sentinel.drv_lb_ip, handler._drv_service_pub_ip)

    def test_on_present(self):
        lbaas_spec = mock.sentinel.lbaas_spec
        lbaas_state = mock.sentinel.lbaas_state
        endpoints = mock.sentinel.endpoints

        m_handler = mock.Mock(spec=h_lbaas.LoadBalancerHandler)
        m_handler._get_lbaas_spec.return_value = lbaas_spec
        m_handler._should_ignore.return_value = False
        m_handler._get_lbaas_state.return_value = lbaas_state
        m_handler._sync_lbaas_members.return_value = True

        h_lbaas.LoadBalancerHandler.on_present(m_handler, endpoints)

        m_handler._get_lbaas_spec.assert_called_once_with(endpoints)
        m_handler._should_ignore.assert_called_once_with(endpoints, lbaas_spec)
        m_handler._get_lbaas_state.assert_called_once_with(endpoints)
        m_handler._sync_lbaas_members.assert_called_once_with(
            endpoints, lbaas_state, lbaas_spec)
        m_handler._set_lbaas_state.assert_called_once_with(
            endpoints, lbaas_state)

    @mock.patch('kuryr_kubernetes.objects.lbaas'
                '.LBaaSServiceSpec')
    def test_on_deleted(self, m_svc_spec_ctor):
        endpoints = mock.sentinel.endpoints
        empty_spec = mock.sentinel.empty_spec
        lbaas_state = mock.sentinel.lbaas_state
        m_svc_spec_ctor.return_value = empty_spec

        m_handler = mock.Mock(spec=h_lbaas.LoadBalancerHandler)
        m_handler._get_lbaas_state.return_value = lbaas_state

        h_lbaas.LoadBalancerHandler.on_deleted(m_handler, endpoints)

        m_handler._get_lbaas_state.assert_called_once_with(endpoints)
        m_handler._sync_lbaas_members.assert_called_once_with(
            endpoints, lbaas_state, empty_spec)

    def test_should_ignore(self):
        endpoints = mock.sentinel.endpoints
        lbaas_spec = mock.sentinel.lbaas_spec

        # REVISIT(ivc): ddt?
        m_handler = mock.Mock(spec=h_lbaas.LoadBalancerHandler)
        m_handler._has_pods.return_value = True
        m_handler._is_lbaas_spec_in_sync.return_value = True

        ret = h_lbaas.LoadBalancerHandler._should_ignore(
            m_handler, endpoints, lbaas_spec)
        self.assertEqual(False, ret)

        m_handler._has_pods.assert_called_once_with(endpoints)
        m_handler._is_lbaas_spec_in_sync.assert_called_once_with(
            endpoints, lbaas_spec)

    def test_is_lbaas_spec_in_sync(self):
        names = ['a', 'b', 'c']
        endpoints = {'subsets': [{'ports': [{'name': n} for n in names]}]}
        lbaas_spec = obj_lbaas.LBaaSServiceSpec(ports=[
            obj_lbaas.LBaaSPortSpec(name=n) for n in reversed(names)])

        m_handler = mock.Mock(spec=h_lbaas.LoadBalancerHandler)
        ret = h_lbaas.LoadBalancerHandler._is_lbaas_spec_in_sync(
            m_handler, endpoints, lbaas_spec)

        self.assertEqual(True, ret)

    def test_has_pods(self):
        # REVISIT(ivc): ddt?
        endpoints = {'subsets': [
            {},
            {'addresses': []},
            {'addresses': [{'targetRef': {}}]},
            {'addresses': [{'targetRef': {'kind': k_const.K8S_OBJ_POD}}]}
        ]}

        m_handler = mock.Mock(spec=h_lbaas.LoadBalancerHandler)

        ret = h_lbaas.LoadBalancerHandler._has_pods(m_handler, endpoints)

        self.assertEqual(True, ret)

    def test_get_pod_subnet(self):
        subnet_id = mock.sentinel.subnet_id
        project_id = mock.sentinel.project_id
        target_ref = {'kind': k_const.K8S_OBJ_POD,
                      'name': 'pod-name',
                      'namespace': 'default'}
        ip = '1.2.3.4'
        m_handler = mock.Mock(spec=h_lbaas.LoadBalancerHandler)
        m_drv_pod_project = mock.Mock()
        m_drv_pod_project.get_project.return_value = project_id
        m_handler._drv_pod_project = m_drv_pod_project
        m_drv_pod_subnets = mock.Mock()
        m_drv_pod_subnets.get_subnets.return_value = {
            subnet_id: osv_network.Network(subnets=osv_subnet.SubnetList(
                objects=[osv_subnet.Subnet(cidr='1.2.3.0/24')]))}
        m_handler._drv_pod_subnets = m_drv_pod_subnets

        observed_subnet_id = h_lbaas.LoadBalancerHandler._get_pod_subnet(
            m_handler, target_ref, ip)

        self.assertEqual(subnet_id, observed_subnet_id)

    def _generate_lbaas_state(self, vip, targets, project_id, subnet_id):
        endpoints = mock.sentinel.endpoints
        drv = FakeLBaaSDriver()
        lb = drv.ensure_loadbalancer(
            endpoints, project_id, subnet_id, vip, None)
        listeners = {}
        pools = {}
        members = {}
        for ip, (listen_port, target_port) in targets.items():
            lsnr = listeners.setdefault(listen_port, drv.ensure_listener(
                endpoints, lb, 'TCP', listen_port))
            pool = pools.setdefault(listen_port, drv.ensure_pool(
                endpoints, lb, lsnr))
            members.setdefault((ip, listen_port, target_port),
                               drv.ensure_member(endpoints, lb, pool,
                                                 subnet_id, ip,
                                                 target_port, None))
        return obj_lbaas.LBaaSState(
            loadbalancer=lb,
            listeners=list(listeners.values()),
            pools=list(pools.values()),
            members=list(members.values()))

    def _generate_lbaas_spec(self, vip, targets, project_id, subnet_id):
        return obj_lbaas.LBaaSServiceSpec(
            ip=vip,
            project_id=project_id,
            subnet_id=subnet_id,
            ports=[obj_lbaas.LBaaSPortSpec(name=str(port),
                                           protocol='TCP',
                                           port=port)
                   for port in set(t[0] for t in targets.values())])

    def _generate_endpoints(self, targets):
        def _target_to_port(item):
            _, (listen_port, target_port) = item
            return {'port': target_port, 'name': str(listen_port)}
        port_with_addrs = [
            (p, [e[0] for e in grp])
            for p, grp in itertools.groupby(
                sorted(targets.items()), _target_to_port)]
        return {
            'subsets': [
                {
                    'addresses': [
                        {
                            'ip': ip,
                            'targetRef': {
                                'kind': k_const.K8S_OBJ_POD,
                                'name': ip,
                                'namespace': 'default'
                            }
                        }
                        for ip in addrs
                    ],
                    'ports': [port]
                }
                for port, addrs in port_with_addrs
            ]
        }

    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodSubnetsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    def test_sync_lbaas_members(self, m_get_drv_lbaas, m_get_drv_project,
                                m_get_drv_subnets):
        # REVISIT(ivc): test methods separately and verify ensure/release
        project_id = uuidutils.generate_uuid()
        subnet_id = uuidutils.generate_uuid()
        current_ip = '1.1.1.1'
        current_targets = {
            '1.1.1.101': (1001, 10001),
            '1.1.1.111': (1001, 10001),
            '1.1.1.201': (2001, 20001)}
        expected_ip = '2.2.2.2'
        expected_targets = {
            '2.2.2.101': (1201, 12001),
            '2.2.2.111': (1201, 12001),
            '2.2.2.201': (2201, 22001)}
        endpoints = self._generate_endpoints(expected_targets)
        state = self._generate_lbaas_state(
            current_ip, current_targets, project_id, subnet_id)
        spec = self._generate_lbaas_spec(expected_ip, expected_targets,
                                         project_id, subnet_id)

        m_drv_lbaas = mock.Mock(wraps=FakeLBaaSDriver())
        m_drv_project = mock.Mock()
        m_drv_project.get_project.return_value = project_id
        m_drv_subnets = mock.Mock()
        m_drv_subnets.get_subnets.return_value = {
            subnet_id: mock.sentinel.subnet}
        m_get_drv_lbaas.return_value = m_drv_lbaas
        m_get_drv_project.return_value = m_drv_project
        m_get_drv_subnets.return_value = m_drv_subnets

        handler = h_lbaas.LoadBalancerHandler()

        with mock.patch.object(handler, '_get_pod_subnet') as m_get_pod_subnet:
            m_get_pod_subnet.return_value = subnet_id
            handler._sync_lbaas_members(endpoints, state, spec)

        lsnrs = {lsnr.id: lsnr for lsnr in state.listeners}
        pools = {pool.id: pool for pool in state.pools}
        observed_targets = sorted(
            (str(member.ip), (
                lsnrs[pools[member.pool_id].listener_id].port,
                member.port))
            for member in state.members)
        self.assertEqual(sorted(expected_targets.items()), observed_targets)
        self.assertEqual(expected_ip, str(state.loadbalancer.ip))

    def test_get_lbaas_spec(self):
        self.skipTest("skipping until generalised annotation handling is "
                      "implemented")

    def test_get_lbaas_state(self):
        self.skipTest("skipping until generalised annotation handling is "
                      "implemented")

    def test_set_lbaas_state(self):
        self.skipTest("skipping until generalised annotation handling is "
                      "implemented")
