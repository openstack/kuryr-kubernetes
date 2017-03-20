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
import os_vif.objects.network as osv_network
import os_vif.objects.subnet as osv_subnet

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

        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_handler._get_lbaas_spec.return_value = old_spec
        m_handler._has_lbaas_spec_changes.return_value = True
        m_handler._generate_lbaas_spec.return_value = new_spec

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

        h_lbaas.LBaaSSpecHandler.on_present(m_handler, svc_event)

        m_handler._get_lbaas_spec.assert_called_once_with(svc_event)
        m_handler._has_lbaas_spec_changes.assert_called_once_with(svc_event,
                                                                  old_spec)
        m_handler._generate_lbaas_spec.assert_not_called()
        m_handler._set_lbaas_spec.assert_not_called()

    def test_get_service_ip(self):
        svc_body = {'spec': {'type': 'ClusterIP',
                             'clusterIP': mock.sentinel.cluster_ip}}
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)

        ret = h_lbaas.LBaaSSpecHandler._get_service_ip(m_handler, svc_body)
        self.assertEqual(mock.sentinel.cluster_ip, ret)

    def test_get_service_ip_not_cluster_ip(self):
        svc_body = {'spec': {'type': 'notClusterIP',
                             'clusterIP': mock.sentinel.cluster_ip}}
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)

        ret = h_lbaas.LBaaSSpecHandler._get_service_ip(m_handler, svc_body)
        self.assertIsNone(ret)

    def _make_test_net_obj(self, cidr_list):
        subnets = [osv_subnet.Subnet(cidr=cidr) for cidr in cidr_list]
        subnets_list = osv_subnet.SubnetList(objects=subnets)
        return osv_network.Network(subnets=subnets_list)

    def test_get_subnet_id(self):
        test_ip = '1.2.3.4'
        test_cidr = '1.2.3.0/24'
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_drv_subnets = mock.Mock(spec=drv_base.ServiceSubnetsDriver)
        m_handler._drv_subnets = m_drv_subnets
        m_drv_subnets.get_subnets.return_value = {
            mock.sentinel.subnet_id: self._make_test_net_obj([test_cidr])
        }

        self.assertEqual(mock.sentinel.subnet_id,
                         h_lbaas.LBaaSSpecHandler._get_subnet_id(
                             m_handler,
                             mock.sentinel.service,
                             mock.sentinel.project_id,
                             test_ip))
        m_drv_subnets.get_subnets.assert_called_once_with(
            mock.sentinel.service, mock.sentinel.project_id)

    def test_get_subnet_id_invalid(self):
        test_ip = '1.2.3.4'
        test_cidr = '3.2.1.0/24'
        m_service = mock.MagicMock()
        m_handler = mock.Mock(spec=h_lbaas.LBaaSSpecHandler)
        m_drv_subnets = mock.Mock(spec=drv_base.ServiceSubnetsDriver)
        m_handler._drv_subnets = m_drv_subnets
        m_drv_subnets.get_subnets.return_value = {
            mock.sentinel.subnet_id: self._make_test_net_obj([test_cidr])
        }

        self.assertRaises(k_exc.IntegrityError,
                          h_lbaas.LBaaSSpecHandler._get_subnet_id,
                          m_handler,
                          m_service,
                          mock.sentinel.project_id,
                          test_ip)

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
            ret_obj = h_lbaas.LBaaSSpecHandler._generate_lbaas_spec(
                m_handler, service)
            self.assertEqual(mock.sentinel.ret_obj, ret_obj)
            m_spec_ctor.assert_called_once_with(
                ip=ip,
                project_id=project_id,
                subnet_id=subnet_id,
                ports=ports,
                security_groups_ids=sg_ids)

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
