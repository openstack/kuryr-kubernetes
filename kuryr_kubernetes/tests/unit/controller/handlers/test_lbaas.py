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

import os_vif.objects.network as osv_network
import os_vif.objects.subnet as osv_subnet

from kuryr_kubernetes.controller.handlers import lbaas as h_lbaas
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.tests import base as test_base

_SUPPORTED_LISTENER_PROT = ('HTTP', 'HTTPS', 'TCP')


class TestServiceHandler(test_base.TestCase):

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
        handler = h_lbaas.ServiceHandler()

        self.assertEqual(mock.sentinel.drv_project, handler._drv_project)
        self.assertEqual(mock.sentinel.drv_subnets, handler._drv_subnets)
        self.assertEqual(mock.sentinel.drv_sg, handler._drv_sg)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_on_present(self, get_k8s_client):
        svc_event = {
            "metadata": {
                "creationTimestamp": "2020-07-25T18:15:12Z",
                "finalizers": [
                    "openstack.org/service"
                ],
                "labels": {
                    "run": "test"
                },
                "name": "test",
                "namespace": "test",
                "resourceVersion": "413753",
                "selfLink": "",
                "uid": "a026ae48-6141-4029-b743-bac48dae7f06"
            },
            "spec": {
                "clusterIP": "2.2.2.2",
                "ports": [
                    {
                        "port": 1,
                        "protocol": "TCP",
                        "targetPort": 1
                    }
                ],
                "selector": {
                    "run": "test"
                },
                "sessionAffinity": "None",
                "type": "ClusterIP"
            },
            "status": {
                "loadBalancer": {}
            }
        }

        old_spec = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': 'test',
                'finalizers': [''],
                },
            'spec': {
                'ip': '1.1.1.1'
                }
            }
        new_spec = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': 'test',
                'finalizers': [''],
                },
            'spec': {
                'ip': '2.2.2.2'
                }
            }

        project_id = mock.sentinel.project_id
        m_drv_project = mock.Mock()
        m_drv_project.get_project.return_value = project_id

        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        m_handler._has_lbaas_spec_changes.return_value = True
        m_handler.create_crd_spec.return_value = new_spec
        m_handler._should_ignore.return_value = False
        m_handler._drv_project = m_drv_project

        h_lbaas.ServiceHandler.on_present(m_handler, svc_event)
        m_handler.create_crd_spec(svc_event)
        m_handler._has_lbaas_spec_changes.return_value = True
        m_handler._update_crd_spec(old_spec, svc_event)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_on_present_no_changes(self, get_k8s_client):
        svc_event = {
            "metadata": {
                "creationTimestamp": "2020-07-25T18:15:12Z",
                "finalizers": [
                    "openstack.org/service"
                ],
                "labels": {
                    "run": "test"
                },
                "name": "test",
                "namespace": "test",
                "resourceVersion": "413753",
                "selfLink": "",
                "uid": "a026ae48-6141-4029-b743-bac48dae7f06"
            },
            "spec": {
                "clusterIP": "2.2.2.2",
                "ports": [
                    {
                        "port": 1,
                        "protocol": "TCP",
                        "targetPort": 1
                    }
                ],
                "selector": {
                    "run": "test"
                },
                "sessionAffinity": "None",
                "type": "ClusterIP"
            },
            "status": {
                "loadBalancer": {}
            }
        }

        old_spec = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': 'test',
                'finalizers': [''],
                },
            'spec': {
                'ip': '1.1.1.1'
                }
            }

        project_id = mock.sentinel.project_id
        m_drv_project = mock.Mock()
        m_drv_project.get_project.return_value = project_id

        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        m_handler._has_lbaas_spec_changes.return_value = True
        m_handler.create_crd_spec.return_value = old_spec
        m_handler._should_ignore.return_value = False
        m_handler._drv_project = m_drv_project

        h_lbaas.ServiceHandler.on_present(m_handler, svc_event)
        m_handler.create_crd_spec(svc_event)
        m_handler._has_lbaas_spec_changes.return_value = False

    def test_get_service_ip(self):
        svc_body = {'spec': {'type': 'ClusterIP',
                             'clusterIP': mock.sentinel.cluster_ip}}
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)

        ret = h_lbaas.ServiceHandler._get_service_ip(m_handler, svc_body)
        self.assertEqual(mock.sentinel.cluster_ip, ret)

        svc_body = {'spec': {'type': 'LoadBalancer',
                             'clusterIP': mock.sentinel.cluster_ip}}
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)

        ret = h_lbaas.ServiceHandler._get_service_ip(m_handler, svc_body)
        self.assertEqual(mock.sentinel.cluster_ip, ret)

    def test_is_supported_type_clusterip(self):
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        svc_body = {'spec': {'type': 'ClusterIP',
                             'clusterIP': mock.sentinel.cluster_ip}}

        ret = h_lbaas.ServiceHandler._is_supported_type(m_handler, svc_body)
        self.assertEqual(ret, True)

    def test_is_supported_type_loadbalancer(self):
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        svc_body = {'spec': {'type': 'LoadBalancer',
                             'clusterIP': mock.sentinel.cluster_ip}}

        ret = h_lbaas.ServiceHandler._is_supported_type(m_handler, svc_body)
        self.assertEqual(ret, True)

    def _make_test_net_obj(self, cidr_list):
        subnets = [osv_subnet.Subnet(cidr=cidr) for cidr in cidr_list]
        subnets_list = osv_subnet.SubnetList(objects=subnets)
        return osv_network.Network(subnets=subnets_list)

    @mock.patch('kuryr_kubernetes.utils.has_port_changes')
    def test_has_lbaas_spec_changes(self, m_port_changes):
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        service = mock.sentinel.service
        lbaas_spec = mock.sentinel.lbaas_spec

        for has_ip_changes in (True, False):
            for has_port_changes in (True, False):
                m_handler._has_ip_changes.return_value = has_ip_changes
                m_port_changes.return_value = has_port_changes
                ret = h_lbaas.ServiceHandler._has_lbaas_spec_changes(
                    m_handler, service, lbaas_spec)
                self.assertEqual(has_ip_changes or has_port_changes, ret)

    def test_has_ip_changes(self):
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        m_service = mock.MagicMock()
        m_handler._get_service_ip.return_value = '1.1.1.1'
        m_lbaas_spec = mock.MagicMock()
        m_lbaas_spec.ip.__str__.return_value = '2.2.2.2'

        ret = h_lbaas.ServiceHandler._has_ip_changes(
            m_handler, m_service, m_lbaas_spec)
        self.assertTrue(ret)

    def test_has_ip_changes__no_changes(self):
        service = {
            "metadata": {
                "creationTimestamp": "2020-07-25T18:15:12Z",
                "finalizers": [
                    "openstack.org/service"
                ],
                "labels": {
                    "run": "test"
                },
                "name": "test",
                "namespace": "test",
                "resourceVersion": "413753",
                "selfLink": "",
                "uid": "a026ae48-6141-4029-b743-bac48dae7f06"
            },
            "spec": {
                "clusterIP": "1.1.1.1"
            }
        }
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        m_handler._get_service_ip.return_value = '1.1.1.1'
        lb_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': 'test',
                'finalizers': [''],
                },
            'spec': {
                'ip': '1.1.1.1'
                }
            }

        ret = h_lbaas.ServiceHandler._has_ip_changes(
            m_handler, service, lb_crd)
        self.assertFalse(ret)

    def test_has_ip_changes__no_spec(self):
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        m_handler._get_service_ip.return_value = '1.1.1.1'
        service = {
            "metadata": {
                "creationTimestamp": "2020-07-25T18:15:12Z",
                "finalizers": [
                    "openstack.org/service"
                ],
                "labels": {
                    "run": "test"
                },
                "name": "test",
                "namespace": "test",
                "resourceVersion": "413753",
                "selfLink": "",
                "uid": "a026ae48-6141-4029-b743-bac48dae7f06"
            },
            "spec": {
                "clusterIP": "1.1.1.1"
            }
        }
        lb_crd = {
            "spec": {
                "ip": None
            }
        }

        ret = h_lbaas.ServiceHandler._has_ip_changes(
            m_handler, service, lb_crd)
        self.assertTrue(ret)

    def test_has_ip_changes__no_nothing(self):
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        service = {
            "metadata": {
                "creationTimestamp": "2020-07-25T18:15:12Z",
                "finalizers": [
                    "openstack.org/service"
                ],
                "labels": {
                    "run": "test"
                },
                "name": "test",
                "namespace": "test",
                "resourceVersion": "413753",
                "selfLink": "",
                "uid": "a026ae48-6141-4029-b743-bac48dae7f06"
            },
            "spec": {
                "clusterIP": "1.1.1.1"
            }
        }
        lb_crd = {
            "spec": {
                "ip": None
            }
        }
        m_handler._get_service_ip.return_value = None

        ret = h_lbaas.ServiceHandler._has_ip_changes(
            m_handler, service, lb_crd)
        self.assertFalse(ret)

    @mock.patch('kuryr_kubernetes.utils.get_service_ports')
    def test_generate_lbaas_port_specs(self, m_get_service_ports):
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        m_get_service_ports.return_value = [
            {'port': 1, 'name': 'X', 'protocol': 'TCP'},
            {'port': 2, 'name': 'Y', 'protocol': 'TCP'}
        ]
        expected_ports = [
            obj_lbaas.LBaaSPortSpec(name='X', protocol='TCP', port=1),
            obj_lbaas.LBaaSPortSpec(name='Y', protocol='TCP', port=2),
        ]

        ret = h_lbaas.ServiceHandler._generate_lbaas_port_specs(
            m_handler, mock.sentinel.service)
        self.assertEqual(expected_ports, ret)
        m_get_service_ports.assert_called_once_with(
            mock.sentinel.service)

    @mock.patch('kuryr_kubernetes.utils.get_service_ports')
    def test_generate_lbaas_port_specs_udp(self, m_get_service_ports):
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        m_get_service_ports.return_value = [
            {'port': 1, 'name': 'X', 'protocol': 'TCP'},
            {'port': 2, 'name': 'Y', 'protocol': 'UDP'}
        ]
        expected_ports = [
            obj_lbaas.LBaaSPortSpec(name='X', protocol='TCP', port=1),
            obj_lbaas.LBaaSPortSpec(name='Y', protocol='UDP', port=2),
        ]

        ret = h_lbaas.ServiceHandler._generate_lbaas_port_specs(
            m_handler, mock.sentinel.service)
        self.assertEqual(expected_ports, ret)
        m_get_service_ports.assert_called_once_with(
            mock.sentinel.service)

    def test_set_lbaas_spec(self):
        self.skipTest("skipping until generalised annotation handling is "
                      "implemented")

    def test_get_lbaas_spec(self):
        self.skipTest("skipping until generalised annotation handling is "
                      "implemented")
