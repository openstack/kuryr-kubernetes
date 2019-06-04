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
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.objects import route as obj_route
from kuryr_kubernetes.platform.ocp.controller.handlers import route as h_route
from kuryr_kubernetes.tests import base as test_base
import mock

OCP_ROUTE_PATH_COMP_TYPE = 'STARTS_WITH'


class TestOcpRouteHandler(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    def test_init(self, m_get_drv_lbaas):
        m_get_drv_lbaas.return_value = mock.sentinel.drv_lbaas

        handler = h_route.OcpRouteHandler()
        self.assertEqual(mock.sentinel.drv_lbaas, handler._drv_lbaas)
        self.assertIsNone(handler._l7_router)
        self.assertIsNone(handler._l7_router_listeners)

    def test_on_present(self):
        route_event = mock.sentinel.route_event
        route_spec = mock.sentinel.route_spec
        route_state = mock.sentinel.route_state
        route_spec.to_service = mock.sentinel.to_service
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._get_route_spec.return_value = route_spec
        m_handler._should_ignore.return_value = False
        m_handler._get_route_state.return_value = route_state
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        m_handler._l7_router_listeners = obj_lbaas.LBaaSListener(
            id='00EE9E11-91C2-41CF-8FD4-7970579E1234',
            project_id='TEST_PROJECT',
            name='http_listenr',
            protocol='http',
            port=80)

        h_route.OcpRouteHandler.on_present(m_handler, route_event)
        m_handler._sync_router_pool.assert_called_once_with(
            route_event, route_spec, route_state)
        m_handler._sync_l7_policy.assert_called_once_with(
            route_event, route_spec, route_state)
        m_handler._sync_host_l7_rule.assert_called_once_with(
            route_event, route_spec, route_state)
        m_handler._sync_path_l7_rule.assert_called_once_with(
            route_event, route_spec, route_state)
        m_handler._set_route_state.assert_called_once_with(
            route_event, route_state)
        m_handler._set_route_spec.assert_called_once_with(
            route_event, route_spec)
        m_handler._send_route_notification_to_ep.assert_called_once_with(
            route_event, route_spec.to_service)

    def test_on_present_no_change(self):
        route_event = mock.sentinel.route_event
        route_spec = mock.sentinel.route_spec

        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._get_route_spec.return_value = route_spec
        m_handler._should_ignore.return_value = True
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')

        m_handler._l7_router_listeners = obj_lbaas.LBaaSListener(
            id='00EE9E11-91C2-41CF-8FD4-7970579E1234',
            project_id='TEST_PROJECT',
            name='http_listenr',
            protocol='http',
            port=80)

        h_route.OcpRouteHandler.on_present(m_handler, route_event)
        m_handler._get_route_spec.assert_called_once_with(
            route_event)
        m_handler._sync_router_pool.assert_not_called()
        m_handler._sync_l7_policy.assert_not_called()
        m_handler._sync_host_l7_rule.assert_not_called()
        m_handler._sync_path_l7_rule.assert_not_called()
        m_handler._set_route_state.assert_not_called()
        m_handler._set_route_spec.assert_not_called()
        m_handler._send_route_notification_to_ep.assert_not_called()

    def test_get_endpoints_link_by_route(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        route_link = (
            '/apis/route.openshift.io/v1/namespaces/default/routes/my_route')
        ep_name = 'my_endpoint'
        expected_ep_link = '/api/v1/namespaces/default/endpoints/my_endpoint'
        ret_ep_path = h_route.OcpRouteHandler._get_endpoints_link_by_route(
            m_handler, route_link, ep_name)

        self.assertEqual(expected_ep_link, ret_ep_path)

    def test_get_endpoints_link_by_route_error(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        route_link = '/oapi/v1/namespaces/default/routes/my_route'
        ep_name = 'wrong_endpoint'
        expected_ep_link = '/api/v1/namespaces/default/endpoints/my_endpoint'
        ret_ep_path = h_route.OcpRouteHandler._get_endpoints_link_by_route(
            m_handler, route_link, ep_name)

        self.assertNotEqual(expected_ep_link, ret_ep_path)

    def test_should_ignore_l7_router_not_exist(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = None
        route = {'spec': {
            'host': 'www.test.com', 'path': 'mypath',
            'to': {'name': 'target_service'}}}

        route_spec = obj_route.RouteSpec(
            host='www.test.com',
            path='mypath',
            to_service='target_service')
        expected_result = True

        ret_value = h_route.OcpRouteHandler._should_ignore(
            m_handler, route, route_spec)

        self.assertEqual(ret_value, expected_result)

    def test_should_ignore_l7_router_exist_no_change(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        route = {'spec': {
            'host': 'www.test.com', 'path': 'mypath',
            'to': {'name': 'target_service'}}}

        route_spec = obj_route.RouteSpec(
            host='www.test.com',
            path='mypath',
            to_service='target_service')
        expected_result = True
        ret_value = h_route.OcpRouteHandler._should_ignore(
            m_handler, route, route_spec)
        self.assertEqual(ret_value, expected_result)

    def test_should_ignore_l7_router_exist_with_changes(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        route = {'spec': {
            'host': 'www.test.com', 'path': 'mypath',
            'to': {'name': 'target_service'}}}
        route_spec = obj_route.RouteSpec(
            host='www.test.com1',
            path='mypath',
            to_service='target_service')
        expected_result = False
        ret_value = h_route.OcpRouteHandler._should_ignore(
            m_handler, route, route_spec)
        self.assertEqual(ret_value, expected_result)

    def test_sync_router_pool_empty_pool(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        m_handler._drv_lbaas = mock.Mock(
            spec=drv_base.LBaaSDriver)
        m_handler._drv_lbaas.get_pool_by_name.return_value = None
        m_handler._drv_lbaas.ensure_pool_attached_to_lb.return_value = None

        route = {'metadata': {'namespace': 'namespace'},
                 'spec': {'host': 'www.test.com', 'path': 'mypath',
                          'to': {'name': 'target_service'}}}
        route_spec = obj_route.RouteSpec(
            host='www.test.com1',
            path='mypath',
            to_service='target_service')

        route_state = obj_route.RouteState()

        h_route.OcpRouteHandler._sync_router_pool(
            m_handler, route, route_spec, route_state)
        self.assertIsNone(route_state.router_pool)

    def test_sync_router_pool_valid_pool(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        m_handler._drv_lbaas = mock.Mock(
            spec=drv_base.LBaaSDriver)
        ret_pool = obj_lbaas.LBaaSPool(
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            listener_id='A57B7771-6050-4CA8-A63C-443493EC98AB',
            loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')

        m_handler._drv_lbaas.get_pool_by_name.return_value = None
        m_handler._drv_lbaas.ensure_pool_attached_to_lb.return_value = ret_pool

        route = {'metadata': {'namespace': 'namespace'},
                 'spec': {'host': 'www.test.com', 'path': 'mypath',
                          'to': {'name': 'target_service'}}}
        route_spec = obj_route.RouteSpec(
            host='www.test.com1',
            path='mypath',
            to_service='target_service')

        route_state = obj_route.RouteState()

        h_route.OcpRouteHandler._sync_router_pool(
            m_handler, route, route_spec, route_state)
        self.assertEqual(route_state.router_pool, ret_pool)

    def test_sync_l7_policy(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        m_handler._drv_lbaas = mock.Mock(
            spec=drv_base.LBaaSDriver)
        listener = obj_lbaas.LBaaSListener(
            id='123443545',
            name='TEST_NAME', project_id='TEST_PROJECT', protocol='TCP',
            port=80, loadbalancer_id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')
        m_handler._l7_router_listeners = {'80': listener}
        l7_policy = obj_lbaas.LBaaSL7Policy(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C44', name='myname',
            listener_id='00EE9E11-91C2-41CF-8FD4-7970579E5C45',
            redirect_pool_id='00EE9E11-91C2-41CF-8FD4-7970579E5C46',
            project_id='00EE9E11-91C2-41CF-8FD4-7970579E5C46')

        route_state = obj_route.RouteState()
        m_handler._drv_lbaas.ensure_l7_policy.return_value = l7_policy

        route = {'metadata': {'namespace': 'namespace', 'name': 'name'},
                 'spec': {'host': 'www.test.com', 'path': 'mypath',
                          'to': {'name': 'target_service'}}}
        route_spec = obj_route.RouteSpec(
            host='www.test.com1',
            path='mypath',
            to_service='target_service')

        h_route.OcpRouteHandler._sync_l7_policy(
            m_handler, route, route_spec, route_state)
        self.assertEqual(route_state.l7_policy, l7_policy)

    def test_sync_host_l7_rule_already_exist(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        m_handler._drv_lbaas = mock.Mock(
            spec=drv_base.LBaaSDriver)
        h_l7_rule = obj_lbaas.LBaaSL7Rule(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C44',
            compare_type='EQUAL_TO',
            l7policy_id='00EE9E11-91C2-41CF-8FD4-7970579E5C45',
            type='HOST',
            value='www.example.com')

        route_state = obj_route.RouteState(h_l7_rule=h_l7_rule)
        route = {'metadata': {'namespace': 'namespace', 'name': 'name'},
                 'spec': {'host': 'www.test.com', 'path': 'mypath',
                          'to': {'name': 'target_service'}}}

        route_spec = obj_route.RouteSpec(
            host='www.test.com',
            path='mypath',
            to_service='target_service')

        h_route.OcpRouteHandler._sync_host_l7_rule(
            m_handler, route, route_spec, route_state)
        self.assertEqual(route_state.h_l7_rule, h_l7_rule)

    def test_sync_host_l7_rule_new_host(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        m_handler._drv_lbaas = mock.Mock(
            spec=drv_base.LBaaSDriver)
        h_l7_rule = obj_lbaas.LBaaSL7Rule(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C44',
            compare_type='EQUAL_TO',
            l7policy_id='00EE9E11-91C2-41CF-8FD4-7970579E5C45',
            type='HOST',
            value='www.example.com')

        route_state = obj_route.RouteState(h_l7_rule=h_l7_rule)

        route = {'metadata': {'namespace': 'namespace', 'name': 'name'},
                 'spec': {'host': 'new.www.test.com', 'path': 'mypath',
                          'to': {'name': 'target_service'}}}
        route_spec = obj_route.RouteSpec(
            host='www.test.com',
            path='mypath',
            to_service='target_service')

        m_handler._drv_lbaas.ensure_l7_rule.return_value = h_l7_rule
        h_route.OcpRouteHandler._sync_host_l7_rule(
            m_handler, route, route_spec, route_state)
        self.assertEqual(route_state.h_l7_rule.value, route['spec']['host'])

    def test_sync_path_l7_rule(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        m_handler._drv_lbaas = mock.Mock(
            spec=drv_base.LBaaSDriver)

        l7_policy = obj_lbaas.LBaaSL7Policy(
            id='00EE9E11-91C2-41CF-8FD4-7970579E6666', name='myname',
            listener_id='00EE9E11-91C2-41CF-8FD4-7970579E5C45',
            redirect_pool_id='00EE9E11-91C2-41CF-8FD4-7970579E5C46',
            project_id='00EE9E11-91C2-41CF-8FD4-7970579E5C46')

        route_state = obj_route.RouteState(
            l7_policy=l7_policy)

        route = {'metadata': {'namespace': 'namespace', 'name': 'name'},
                 'spec': {'host': 'new.www.test.com', 'path': '/nice_path',
                          'to': {'name': 'target_service'}}}

        route_spec = obj_route.RouteSpec(
            host='www.test.com',
            path=None,
            to_service='target_service')

        ret_p_l7_rule = obj_lbaas.LBaaSL7Rule(
            id='55559E11-91C2-41CF-8FD4-7970579E5C44',
            compare_type=OCP_ROUTE_PATH_COMP_TYPE,
            l7policy_id='55559E11-91C2-41CF-8FD4-7970579E5C45',
            type='PATH',
            value='/nice_path')

        m_handler._drv_lbaas.ensure_l7_rule.return_value = ret_p_l7_rule
        h_route.OcpRouteHandler._sync_path_l7_rule(
            m_handler, route, route_spec, route_state)
        self.assertEqual(route_state.p_l7_rule, ret_p_l7_rule)
        m_handler._drv_lbaas.ensure_l7_rule.assert_called_once_with(
            m_handler._l7_router, route_state.l7_policy,
            OCP_ROUTE_PATH_COMP_TYPE, 'PATH', route['spec']['path'])

    def test_sync_path_l7_rule_edit_usecase(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        m_handler._drv_lbaas = mock.Mock(
            spec=drv_base.LBaaSDriver)

        old_p_l7_rule = obj_lbaas.LBaaSL7Rule(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C44',
            compare_type=OCP_ROUTE_PATH_COMP_TYPE,
            l7policy_id='00EE9E11-91C2-41CF-8FD4-7970579E5C45',
            type='PATH',
            value='/cur_path')

        route_state = obj_route.RouteState(p_l7_rule=old_p_l7_rule)

        route = {'metadata': {'namespace': 'namespace', 'name': 'name'},
                 'spec': {'host': 'new.www.test.com', 'path': '/new_path',
                          'to': {'name': 'target_service'}}}
        route_spec = obj_route.RouteSpec(
            host='www.test.com',
            path=old_p_l7_rule.value,
            to_service='target_service')

        ret_p_l7_rule = obj_lbaas.LBaaSL7Rule(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C44',
            compare_type=OCP_ROUTE_PATH_COMP_TYPE,
            l7policy_id='00EE9E11-91C2-41CF-8FD4-7970579E5C45',
            type='PATH',
            value=route['spec']['path'])

        m_handler._drv_lbaas.update_l7_rule.return_value = True
        h_route.OcpRouteHandler._sync_path_l7_rule(
            m_handler, route, route_spec, route_state)
        self.assertEqual(route_state.p_l7_rule.value, ret_p_l7_rule.value)
        m_handler._drv_lbaas.update_l7_rule.assert_called_once_with(
            old_p_l7_rule, route['spec']['path'])

    def test_sync_path_l7_rule_route_spec_not_sync(self):
        m_handler = mock.Mock(spec=h_route.OcpRouteHandler)
        m_handler._l7_router = obj_lbaas.LBaaSLoadBalancer(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C',
            project_id='TEST_PROJECT')
        m_handler._drv_lbaas = mock.Mock(
            spec=drv_base.LBaaSDriver)

        old_p_l7_rule = obj_lbaas.LBaaSL7Rule(
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C44',
            compare_type=OCP_ROUTE_PATH_COMP_TYPE,
            l7policy_id='00EE9E11-91C2-41CF-8FD4-7970579E5C45',
            type='PATH',
            value='/cur_path')

        route_state = obj_route.RouteState(p_l7_rule=old_p_l7_rule)

        route = {'metadata': {'namespace': 'namespace', 'name': 'name'},
                 'spec': {'host': 'new.www.test.com', 'path': 'new_path',
                          'to': {'name': 'target_service'}}}

        route_spec = obj_route.RouteSpec(
            host='www.test.com',
            path='/not_cur_path',
            to_service='target_service')
        m_handler._drv_lbaas.update_l7_rule.return_value = None

        h_route.OcpRouteHandler._sync_path_l7_rule(
            m_handler, route, route_spec, route_state)
        self.assertEqual(route_state.p_l7_rule.value, route['spec']['path'])
        self.assertEqual(route_spec.path, route['spec']['path'])
