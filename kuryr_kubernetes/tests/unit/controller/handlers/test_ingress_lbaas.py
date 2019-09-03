# Copyright (c) 2018 RedHat, Inc.
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
import uuid

from kuryr_kubernetes.controller.handlers import ingress_lbaas as h_ing_lbaas
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.tests.unit.controller.handlers import \
    test_lbaas as t_lbaas


class TestIngressLoadBalancerHandler(t_lbaas.TestLoadBalancerHandler):

    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    def test_init(self, m_get_drv_lbaas):
        m_get_drv_lbaas.return_value = mock.sentinel.drv_lbaas

        handler = h_ing_lbaas.IngressLoadBalancerHandler()

        self.assertEqual(mock.sentinel.drv_lbaas, handler._drv_lbaas)

    @mock.patch('kuryr_kubernetes.utils.get_lbaas_spec')
    def test_on_present_no_ing_ctrlr(self, m_get_lbaas_spec):
        endpoints = mock.sentinel.endpoints

        m_handler = mock.Mock(spec=h_ing_lbaas.IngressLoadBalancerHandler)
        m_handler._l7_router = None
        h_ing_lbaas.IngressLoadBalancerHandler.on_present(m_handler, endpoints)

        m_get_lbaas_spec.assert_not_called()
        m_handler._should_ignore.assert_not_called()

    def test_should_ignore(self):
        endpoints = mock.sentinel.endpoints
        lbaas_spec = mock.sentinel.lbaas_spec

        m_handler = mock.Mock(spec=h_ing_lbaas.IngressLoadBalancerHandler)
        m_handler._has_pods.return_value = False

        ret = h_ing_lbaas.IngressLoadBalancerHandler._should_ignore(
            m_handler, endpoints, lbaas_spec)
        self.assertEqual(True, ret)

        m_handler._has_pods.assert_called_once_with(endpoints)

    def test_should_ignore_with_pods(self):
        endpoints = mock.sentinel.endpoints
        lbaas_spec = mock.sentinel.lbaas_spec

        m_handler = mock.Mock(spec=h_ing_lbaas.IngressLoadBalancerHandler)
        m_handler._has_pods.return_value = True

        ret = h_ing_lbaas.IngressLoadBalancerHandler._should_ignore(
            m_handler, endpoints, lbaas_spec)
        self.assertEqual(False, ret)

        m_handler._has_pods.assert_called_once_with(endpoints)

    def _generate_route_state(self, vip, targets, project_id, subnet_id):
        name = 'DUMMY_NAME'
        drv = t_lbaas.FakeLBaaSDriver()
        lb = drv.ensure_loadbalancer(
            name, project_id, subnet_id, vip, None, 'ClusterIP')
        pool = drv.ensure_pool_attached_to_lb(lb, 'namespace',
                                              'svc_name', 'HTTP')

        members = {}
        for ip, (listen_port, target_port) in targets.items():
            members.setdefault((ip, listen_port, target_port),
                               drv.ensure_member(lb, pool,
                                                 subnet_id, ip,
                                                 target_port, None, None))
        return obj_lbaas.LBaaSRouteState(
            pool=pool,
            members=list(members.values()))

    def _sync_route_members_impl(self, m_get_drv_lbaas, m_get_drv_project,
                                 m_get_drv_subnets, subnet_id, project_id,
                                 endpoints, state, spec):
        m_drv_lbaas = mock.Mock(wraps=t_lbaas.FakeLBaaSDriver())
        m_drv_project = mock.Mock()
        m_drv_project.get_project.return_value = project_id
        m_drv_subnets = mock.Mock()
        m_drv_subnets.get_subnets.return_value = {
            subnet_id: mock.sentinel.subnet}
        m_get_drv_lbaas.return_value = m_drv_lbaas
        m_get_drv_project.return_value = m_drv_project
        m_get_drv_subnets.return_value = m_drv_subnets

        handler = h_ing_lbaas.IngressLoadBalancerHandler()

        handler._l7_router = t_lbaas.FakeLBaaSDriver().ensure_loadbalancer(
            name='L7_Router',
            project_id=project_id,
            subnet_id=subnet_id,
            ip='1.2.3.4',
            security_groups_ids=None,
            service_type='ClusterIP')

        with mock.patch.object(handler, '_get_pod_subnet') as m_get_pod_subnet:
            m_get_pod_subnet.return_value = subnet_id
            handler._sync_lbaas_route_members(endpoints, state, spec)

        observed_targets = sorted(
            (str(member.ip), (
                member.port,
                member.port))
            for member in state.members)
        return observed_targets

    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodSubnetsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    def test__sync_lbaas_route_members(self, m_get_drv_lbaas,
                                       m_get_drv_project, m_get_drv_subnets):
        project_id = str(uuid.uuid4())
        subnet_id = str(uuid.uuid4())
        current_ip = '1.1.1.1'
        current_targets = {
            '1.1.1.101': (1001, 1001),
            '1.1.1.111': (1001, 1001),
            '1.1.1.201': (2001, 2001)}
        expected_ip = '2.2.2.2'
        expected_targets = {
            '2.2.2.101': (1201, 1201),
            '2.2.2.111': (1201, 1201),
            '2.2.2.201': (2201, 2201)}
        endpoints = self._generate_endpoints(expected_targets)
        state = self._generate_route_state(
            current_ip, current_targets, project_id, subnet_id)
        spec = self._generate_lbaas_spec(expected_ip, expected_targets,
                                         project_id, subnet_id)

        observed_targets = self._sync_route_members_impl(
            m_get_drv_lbaas, m_get_drv_project, m_get_drv_subnets,
            subnet_id, project_id, endpoints, state, spec)

        self.assertEqual(sorted(expected_targets.items()), observed_targets)

    def test_on_deleted_no_ingress_controller(self):
        endpoints = mock.sentinel.endpoints
        m_handler = mock.Mock(spec=h_ing_lbaas.IngressLoadBalancerHandler)
        m_handler._l7_router = None
        h_ing_lbaas.IngressLoadBalancerHandler.on_deleted(m_handler, endpoints)

        m_handler._get_lbaas_route_state.assert_not_called()
        m_handler._remove_unused_route_members.assert_not_called()

    def test_on_deleted(self):
        endpoints = mock.sentinel.endpoints
        project_id = str(uuid.uuid4())
        subnet_id = str(uuid.uuid4())

        m_handler = mock.Mock(spec=h_ing_lbaas.IngressLoadBalancerHandler)
        m_handler._l7_router = t_lbaas.FakeLBaaSDriver().ensure_loadbalancer(
            name='L7_Router',
            project_id=project_id,
            subnet_id=subnet_id,
            ip='1.2.3.4',
            security_groups_ids=None,
            service_type='ClusterIP')

        m_handler._get_lbaas_route_state.return_value = (
            obj_lbaas.LBaaSRouteState())
        m_handler._remove_unused_route_members.return_value = True

        h_ing_lbaas.IngressLoadBalancerHandler.on_deleted(m_handler, endpoints)

        m_handler._get_lbaas_route_state.assert_called_once()
        m_handler._remove_unused_route_members.assert_called_once()
