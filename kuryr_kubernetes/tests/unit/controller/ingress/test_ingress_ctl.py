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
from kuryr_kubernetes.controller.ingress import ingress_ctl
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.tests import base as test_base
import mock


class TestIngressCtrlr(test_base.TestCase):
    def test_ingress_ctrlr_instance(self):
        ing_ctrl = ingress_ctl.IngressCtrlr.get_instance()
        self.assertIsNotNone(ing_ctrl)

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_ingress_ctrlr_conf_disabled(self, m_cfg):
        m_cfg.kubernetes.enabled_handlers = ['not_ocproute']
        m_cfg.ingress.l7_router_uuid = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        ing_ctrl = ingress_ctl.IngressCtrlr.get_instance()
        ing_ctrl.start_operation()
        ret_l7router, ret_listener = ing_ctrl.get_router_and_listener()
        self.assertIsNotNone(ing_ctrl)
        self.assertIsNone(ret_l7router)
        self.assertIsNone(ret_listener)

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_ingress_ctrlr_l7router_ip_not_defined(self, m_cfg):
        m_cfg.kubernetes.enabled_handlers = ['ocproute']
        m_cfg.ingress.l7_router_uuid = None
        ing_ctrl = ingress_ctl.IngressCtrlr.get_instance()
        ing_ctrl.start_operation()

        ret_l7router, ret_listener = ing_ctrl.get_router_and_listener()
        self.assertIsNotNone(ing_ctrl)
        self.assertIsNone(ret_l7router)
        self.assertIsNone(ret_listener)

    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_ingress_ctrlr_router_enabled_k8s(self, m_cfg, m_get_lbaas_drv):

        m_cfg.kubernetes.enabled_handlers = ['ingresslb']
        m_cfg.ingress.l7_router_uuid = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        l7_router = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            security_groups=[],
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')

        m_driver = mock.Mock()
        m_driver.get_lb_by_uuid.return_value = l7_router
        m_get_lbaas_drv.return_value = m_driver

        ing_ctrl = ingress_ctl.IngressCtrlr.get_instance()
        ing_ctrl.start_operation()
        self.assertIsNotNone(ing_ctrl)
        self.assertEqual(ing_ctrl._status, 'ACTIVE')

    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_ingress_ctrlr_router_enabled_ocp(self, m_cfg, m_get_lbaas_drv):

        m_cfg.kubernetes.enabled_handlers = ['ocproute']
        m_cfg.ingress.l7_router_uuid = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'

        l7_router = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            security_groups=[],
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')

        m_driver = mock.Mock()
        m_driver.get_lb_by_uuid.return_value = l7_router
        m_get_lbaas_drv.return_value = m_driver

        ing_ctrl = ingress_ctl.IngressCtrlr.get_instance()
        ing_ctrl.start_operation()
        self.assertIsNotNone(ing_ctrl)
        self.assertEqual(ing_ctrl._status, 'ACTIVE')

    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_ingress_ctrlr_router_created(self, m_cfg, m_get_lbaas_drv):

        m_cfg.kubernetes.enabled_handlers = ['ocproute', 'ingresslb']
        m_cfg.ingress.l7_router_uuid = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'

        l7_router = obj_lbaas.LBaaSLoadBalancer(
            name='TEST_NAME', project_id='TEST_PROJECT', ip='1.2.3.4',
            subnet_id='D3FA400A-F543-4B91-9CD3-047AF0CE42D1',
            security_groups=[],
            id='00EE9E11-91C2-41CF-8FD4-7970579E5C4C')

        m_driver = mock.Mock()
        m_driver.get_lb_by_uuid.return_value = l7_router
        m_get_lbaas_drv.return_value = m_driver

        ing_ctrl = ingress_ctl.IngressCtrlr.get_instance()
        ing_ctrl._start_operation_impl()
        self.assertIsNotNone(ing_ctrl)
        self.assertEqual(ing_ctrl._status, 'ACTIVE')
        ret_l7router, ret_listener = ing_ctrl.get_router_and_listener()
        self.assertEqual(ret_l7router, l7_router)

    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_ingress_ctrlr_router_l7_router_drv_fail(
            self, m_cfg, m_get_lbaas_drv):

        m_cfg.ingress.l7_router_uuid = '00EE9E11-91C2-41CF-8FD4-7970579E5C4C'
        m_cfg.kubernetes.enabled_handlers = ['ocproute', 'ingresslb']

        m_driver = mock.Mock()
        m_driver.get_lb_by_uuid.return_value = None
        m_get_lbaas_drv.return_value = m_driver

        ing_ctrl = ingress_ctl.IngressCtrlr.get_instance()
        ing_ctrl._start_operation_impl()
        self.assertEqual(ing_ctrl._status, 'DOWN')
        self.assertIsNotNone(ing_ctrl)
