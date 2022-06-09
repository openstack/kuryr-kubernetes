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

from oslo_log import log as logging
from unittest import mock

import os_vif.objects.network as osv_network
import os_vif.objects.subnet as osv_subnet

from kuryr_kubernetes.controller.handlers import lbaas as h_lbaas
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.tests import base as test_base

_SUPPORTED_LISTENER_PROT = ('HTTP', 'HTTPS', 'TCP')


@mock.patch('kuryr_kubernetes.controller.drivers.base.LBaaSDriver.'
            'get_instance', mock.Mock())
@mock.patch('kuryr_kubernetes.clients.get_kubernetes_client', mock.Mock())
class TestServiceHandler(test_base.TestCase):
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_on_present(self, get_k8s_client):
        svc_event = {
            'apiVersion': 'v1',
            'kind': 'Service',
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
        m_handler.k8s = mock.Mock()

        h_lbaas.ServiceHandler.on_present(m_handler, svc_event)
        m_handler.create_crd_spec(svc_event)
        m_handler._has_lbaas_spec_changes.return_value = True
        m_handler._update_crd_spec(old_spec, svc_event)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_on_present_no_changes(self, get_k8s_client):
        svc_event = {
            'apiVersion': 'v1',
            'kind': 'Service',
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
        m_handler.k8s = mock.Mock()

        h_lbaas.ServiceHandler.on_present(m_handler, svc_event)
        m_handler.create_crd_spec(svc_event)
        m_handler._has_lbaas_spec_changes.return_value = False

    def test_get_service_ip(self):
        svc_body = {'spec': {'type': 'ClusterIP',
                             'clusterIP': '192.168.0.11'}}
        handler = h_lbaas.ServiceHandler()
        ret = handler._get_service_ip(svc_body)
        self.assertEqual('192.168.0.11', ret)

        svc_body = {'spec': {'type': 'LoadBalancer',
                             'clusterIP': '192.168.0.11'}}
        ret = handler._get_service_ip(svc_body)
        self.assertEqual('192.168.0.11', ret)

    def test_get_service_ip_funny(self):
        svc_body = {'spec': {'type': 'ClusterIP',
                             'clusterIP': '172.30.0.011'}}
        handler = h_lbaas.ServiceHandler()

        ret = handler._get_service_ip(svc_body)
        self.assertEqual('172.30.0.11', ret)

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
                for timeout in (True, False):
                    for provider in (True, False):
                        m_handler._has_ip_changes.return_value = has_ip_changes
                        m_port_changes.return_value = has_port_changes
                        m_handler._has_timeout_changes.return_value = timeout
                        m_handler._has_provider_changes.return_value = provider
                        ret = h_lbaas.ServiceHandler._has_lbaas_spec_changes(
                            m_handler, service, lbaas_spec)
                        self.assertEqual(
                            has_ip_changes or has_port_changes or timeout
                            or provider, ret)

    def test_has_ip_changes(self):
        m_handler = mock.Mock(spec=h_lbaas.ServiceHandler)
        m_service = {'apiVersion': 'v1',
                     'kind': 'Service',
                     "metadata": {"name": "test",
                                  "namespace": "test"}}
        m_handler._get_service_ip.return_value = '1.1.1.1'
        m_lbaas_spec = mock.MagicMock()
        m_lbaas_spec.ip.__str__.return_value = '2.2.2.2'

        ret = h_lbaas.ServiceHandler._has_ip_changes(
            m_handler, m_service, m_lbaas_spec)
        self.assertTrue(ret)

    def test_has_ip_changes__no_changes(self):
        service = {
            'apiVersion': 'v1',
            'kind': 'Service',
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
            'apiVersion': 'v1',
            'kind': 'Service',
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
            'apiVersion': 'v1',
            'kind': 'Service',
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

    def test_set_lbaas_spec(self):
        self.skipTest("skipping until generalised annotation handling is "
                      "implemented")

    def test_get_lbaas_spec(self):
        self.skipTest("skipping until generalised annotation handling is "
                      "implemented")


class TestEndpointsHandler(test_base.TestCase):

    def setUp(self):
        super().setUp()
        self._ep_name = 'my-service'
        self._ep_namespace = mock.sentinel.namespace
        self._ep_ip = '1.2.3.4'

        self._ep = {
            "kind": "Endpoints",
            "apiVersion": "v1",
            "metadata": {
                "name": self._ep_name,
                "namespace": self._ep_namespace,
            },
            "subsets": [
                {
                    "addresses": [
                        {
                            "ip": self._ep_ip
                        },
                    ],
                    "ports": [
                        {
                            "port": 8080,
                            "protocol": "TCP"
                        }
                    ]
                }
            ]
        }

        self._klb_name = 'my-service'
        self._klb_ip = '1.1.1.1'

        self._klb = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': self._klb_name,
                'finalizers': [''],
            },
            'spec': {
                'ip': self._klb_ip
            }
        }

    def test_on_deleted(self):
        m_handler = mock.Mock(spec=h_lbaas.EndpointsHandler)
        h_lbaas.EndpointsHandler.on_deleted(m_handler, self._ep)
        m_handler._remove_endpoints.assert_called_once_with(self._ep)

    @mock.patch('kuryr_kubernetes.utils.get_klb_crd_path')
    def test__remove_endpoints(self, get_klb_crd_path):
        m_handler = mock.Mock()
        h_lbaas.EndpointsHandler._remove_endpoints(m_handler, self._ep)
        m_handler.k8s.patch_crd.assert_called_once_with(
            'spec', get_klb_crd_path(self._ep), 'endpointSlices',
            action='remove')

    @mock.patch.object(logging.getLogger(
                       'kuryr_kubernetes.controller.handlers.lbaas'),
                       'debug')
    def test__remove_endpoints_not_found(self, log):
        m_handler = mock.Mock()
        m_handler.k8s.patch_crd.side_effect = k_exc.K8sResourceNotFound('foo')
        h_lbaas.EndpointsHandler._remove_endpoints(m_handler, self._ep)
        log.assert_called_once()

    def test__remove_endpoints_client_exception(self):
        m_handler = mock.Mock()
        m_handler.k8s.patch_crd.side_effect = k_exc.K8sClientException()
        self.assertRaises(k_exc.K8sClientException,
                          h_lbaas.EndpointsHandler._remove_endpoints,
                          m_handler, self._ep)

    @mock.patch.object(logging.getLogger(
                       'kuryr_kubernetes.controller.handlers.lbaas'),
                       'warning')
    def test__remove_endpoints_unprocessable_entity(self, log):
        m_handler = mock.Mock()
        m_handler.k8s.patch_crd.side_effect = k_exc.K8sUnprocessableEntity(
            'bar')
        h_lbaas.EndpointsHandler._remove_endpoints(m_handler, self._ep)
        log.assert_not_called()
