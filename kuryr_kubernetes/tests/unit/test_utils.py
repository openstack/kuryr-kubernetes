# Copyright 2018 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from unittest import mock

import munch
from openstack import exceptions as os_exc
from os_vif import objects
from oslo_config import cfg

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.objects import vif
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix
from kuryr_kubernetes import utils

CONF = cfg.CONF


class TestUtils(test_base.TestCase):

    @mock.patch('socket.gethostname')
    def test_get_node_name(self, m_gethostname):
        m_gethostname.return_value = 'foo'
        res = utils.get_node_name()
        self.assertEqual('foo', res)
        m_gethostname.assert_called_once_with()

    @mock.patch('requests.get')
    def test_get_leader_name(self, m_get):
        m_get.return_value = mock.Mock(json=mock.Mock(
            return_value={'name': 'foo'}))
        res = utils.get_leader_name()
        m_get.assert_called_once_with(
            'http://localhost:%d' % CONF.kubernetes.controller_ha_elector_port)
        self.assertEqual('foo', res)

    @mock.patch('requests.get')
    def test_get_leader_name_malformed(self, m_get):
        m_get.return_value = mock.Mock(json=mock.Mock(
            return_value={'name2': 'foo'}))
        res = utils.get_leader_name()
        m_get.assert_called_once_with(
            'http://localhost:%d' % CONF.kubernetes.controller_ha_elector_port)
        self.assertIsNone(res)

    @mock.patch('requests.get')
    def test_get_leader_name_exc(self, m_get):
        m_get.side_effect = Exception
        res = utils.get_leader_name()
        m_get.assert_called_once_with(
            'http://localhost:%d' % CONF.kubernetes.controller_ha_elector_port)
        self.assertIsNone(res)

    @mock.patch('kuryr_kubernetes.os_vif_util.neutron_to_osvif_network')
    @mock.patch('kuryr_kubernetes.os_vif_util.neutron_to_osvif_subnet')
    def test_get_subnet(self, m_osv_subnet, m_osv_network):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        subnet = mock.MagicMock()
        network = mock.MagicMock()
        subnet_id = mock.sentinel.subnet_id
        network_id = mock.sentinel.network_id

        neutron_subnet = munch.Munch({'network_id': network_id})
        neutron_network = mock.sentinel.neutron_network

        os_net.get_subnet.return_value = neutron_subnet
        os_net.get_network.return_value = neutron_network

        m_osv_subnet.return_value = subnet
        m_osv_network.return_value = network

        ret = utils.get_subnet(subnet_id)

        self.assertEqual(network, ret)
        os_net.get_subnet.assert_called_once_with(subnet_id)
        os_net.get_network.assert_called_once_with(network_id)
        m_osv_subnet.assert_called_once_with(neutron_subnet)
        m_osv_network.assert_called_once_with(neutron_network)
        network.subnets.objects.append.assert_called_once_with(subnet)

    def test_extract_pod_annotation(self):
        vif_obj = objects.vif.VIFBase()
        ps = vif.PodState(default_vif=vif_obj)
        d = ps.obj_to_primitive()
        result = utils.extract_pod_annotation(d)
        self.assertEqual(vif.PodState.obj_name(), result.obj_name())
        self.assertEqual(vif_obj, result.default_vif)

    def test_extract_pod_annotation_convert(self):
        vif_obj = objects.vif.VIFBase()
        d = vif_obj.obj_to_primitive()
        result = utils.extract_pod_annotation(d)
        self.assertEqual(vif.PodState.obj_name(), result.obj_name())
        self.assertEqual(vif_obj, result.default_vif)

    def test__has_kuryrnetwork_crd(self):
        kuryrnet_crd = {
            "apiVersion": "openstack.org/v1",
            "items": [

            ],
            "kind": "KuryrNetworkList",
            "metadata": {
                "continue": "",
                "resourceVersion": "33018",
            }
        }

        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        kubernetes.get.return_value = kuryrnet_crd

        kuryrnets_url = k_const.K8S_API_CRD_KURYRNETWORKS
        resp = utils.has_kuryr_crd(kuryrnets_url)

        self.assertEqual(resp, True)

    def test__has_kuryrnetpolicy_crd(self):
        kuryrnetpolicies_crd = {
            "apiVersion": "openstack.org/v1",
            "items": [

            ],
            "kind": "KuryrNetPolicyList",
            "metadata": {
                "continue": "",
                "resourceVersion": "34186",
            }
        }
        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        kubernetes.get.return_value = kuryrnetpolicies_crd

        kuryrnetpolicies_url = k_const.K8S_API_CRD_KURYRNETPOLICIES
        resp = utils.has_kuryr_crd(kuryrnetpolicies_url)

        self.assertEqual(resp, True)

    def test__has_kuryr_crd_error(self):
        crds = [k_const.K8S_API_CRD_KURYRNETWORKS,
                k_const.K8S_API_CRD_KURYRNETPOLICIES,
                k_const.K8S_API_CRD_KURYRLOADBALANCERS]

        for crd_url in crds:
            kubernetes = self.useFixture(k_fix.MockK8sClient()).client
            kubernetes.get.side_effect = k_exc.K8sClientException

            resp = utils.has_kuryr_crd(crd_url)
            self.assertEqual(resp, False)

            kubernetes.get.assert_called_once()

    def test_get_endpoints_link(self):
        service = {'apiVersion': 'v1',
                   'kind': 'Service',
                   'metadata': {'namespace': 'default',
                                'name': 'test'}}
        ret = utils.get_endpoints_link(service)
        expected_link = "/api/v1/namespaces/default/endpoints/test"
        self.assertEqual(expected_link, ret)

    def test_get_service_ports(self):
        service = {'spec': {'ports': [
            {'port': 1, 'targetPort': 1},
            {'port': 2, 'name': 'X', 'protocol': 'UDP', 'targetPort': 2},
            {'port': 3, 'name': 'Y', 'protocol': 'SCTP', 'targetPort': 3}
        ]}}
        expected_ret = [
            {'port': 1, 'name': None, 'protocol': 'TCP', 'targetPort': '1'},
            {'port': 2, 'name': 'X', 'protocol': 'UDP', 'targetPort': '2'},
            {'port': 3, 'name': 'Y', 'protocol': 'SCTP', 'targetPort': '3'}]

        ret = utils.get_service_ports(service)
        self.assertEqual(expected_ret, ret)

    @mock.patch('kuryr_kubernetes.utils.get_service_ports')
    def test_has_port_changes(self, m_get_service_ports):
        service = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'name': 'serv-1',
                'namespace': 'ns1'
            },
            'spec': {
                'ports': [
                    {
                        'port': 1,
                        'name': 'X',
                        'protocol': 'TCP',
                        'targetPort': '1'
                    }
                ]
            }
        }
        lb_crd_spec = {
            'spec': {
                'ports': [
                    {
                        'name': 'Y',
                        'protocol': 'TCP',
                        'port': 2,
                        'targetPort': 2
                    }
                ]
            }
        }
        ret = utils.has_port_changes(service, lb_crd_spec)
        self.assertTrue(ret)

    @mock.patch('kuryr_kubernetes.utils.get_service_ports')
    def test_has_port_changes_more_ports(self, m_get_service_ports):
        service = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'name': 'serv-1',
                'namespace': 'ns1'
            },
            'spec': {
                'ports': [
                    {
                        'port': 1,
                        'name': 'X',
                        'protocol': 'TCP',
                        'targetPort': '1'
                    }
                ]
            }
        }
        lb_crd_spec = {
            'spec': {
                'ports': [
                    {
                        'name': 'X',
                        'protocol': 'TCP',
                        'port': 1,
                        'targetPort': 1
                    },
                    {
                        'name': 'Y',
                        'protocol': 'TCP',
                        'port': 2,
                        'targetPort': 2
                    }
                ]
            }
        }

        ret = utils.has_port_changes(service, lb_crd_spec)
        self.assertTrue(ret)

    @mock.patch('kuryr_kubernetes.utils.get_service_ports')
    def test_has_port_changes_no_changes(self, m_get_service_ports):

        service = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'name': 'serv-1',
                'namespace': 'ns1'
            },
            'spec': {
                'ports': [
                    {
                        'port': 1,
                        'name': 'X',
                        'protocol': 'TCP',
                        'targetPort': '1'
                    },
                    {
                        'name': 'Y',
                        'protocol': 'TCP',
                        'port': 2,
                        'targetPort': '2'
                    }
                ]
            }
        }

        lb_crd_spec = {
            'spec': {
                'ports': [
                    {
                        'name': 'X',
                        'protocol': 'TCP',
                        'port': 1,
                        'targetPort': '1'
                    },
                    {
                        'name': 'Y',
                        'protocol': 'TCP',
                        'port': 2,
                        'targetPort': '2'
                    }
                ]
            }
        }

        ret = utils.has_port_changes(service, lb_crd_spec)
        self.assertFalse(ret)

    def test_get_nodes_ips(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        ip1 = munch.Munch({'fixed_ips': [{'ip_address': '10.0.0.1',
                                          'subnet_id': 'foo'}],
                           'trunk_details': True})
        ip2 = munch.Munch({'fixed_ips': [{'ip_address': '10.0.0.2',
                                         'subnet_id': 'bar'}],
                           'trunk_details': True})
        ip3 = munch.Munch({'fixed_ips': [{'ip_address': '10.0.0.3',
                                          'subnet_id': 'baz'}],
                           'trunk_details': None})
        ip4 = munch.Munch({'fixed_ips': [{'ip_address': '10.0.0.4',
                                          'subnet_id': 'zab'}],
                           'trunk_details': True})
        ports = (p for p in [ip1, ip2, ip3, ip4])

        os_net.ports.return_value = ports
        trunk_ips = utils.get_nodes_ips(['foo', 'bar'])
        os_net.ports.assert_called_once_with(status='ACTIVE')
        self.assertEqual(trunk_ips, [ip1.fixed_ips[0]['ip_address'],
                                     ip2.fixed_ips[0]['ip_address']])

    def test_get_nodes_ips_tagged(self):
        CONF.set_override('resource_tags', ['foo'], group='neutron_defaults')
        self.addCleanup(CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')

        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        ip1 = munch.Munch({'fixed_ips': [{'ip_address': '10.0.0.1',
                                          'subnet_id': 'foo'}],
                           'trunk_details': True})
        ip2 = munch.Munch({'fixed_ips': [{'ip_address': '10.0.0.2',
                                          'subnet_id': 'bar'}],
                           'trunk_details': False})
        ports = (p for p in [ip1, ip2])

        os_net.ports.return_value = ports
        trunk_ips = utils.get_nodes_ips(['foo'])
        os_net.ports.assert_called_once_with(status='ACTIVE', tags=['foo'])
        self.assertEqual(trunk_ips, [ip1.fixed_ips[0]['ip_address']])

    def test_get_subnet_cidr(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        subnet_id = mock.sentinel.subnet_id
        subnet = munch.Munch(cidr='10.0.0.0/24')
        os_net.get_subnet.return_value = subnet

        result = utils.get_subnet_cidr(subnet_id)
        os_net.get_subnet.assert_called_once_with(subnet_id)
        self.assertEqual(result, '10.0.0.0/24')

    def test_get_subnet_cidr_no_such_subnet(self):
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        subnet_id = mock.sentinel.subnet_id
        os_net.get_subnet.side_effect = os_exc.ResourceNotFound

        self.assertRaises(os_exc.ResourceNotFound, utils.get_subnet_cidr,
                          subnet_id)
        os_net.get_subnet.assert_called_once_with(subnet_id)

    def test_get_current_endpoints_target_with_target_ref(self):
        ep = {'addresses': ['10.0.2.107'], 'conditions': {'ready': True},
              'targetRef': {'kind': 'Pod', 'name': 'test-868d9cbd68-xq2fl',
                            'namespace': 'test2'}}
        port = {'port': 8080, 'protocol': 'TCP'}
        spec_ports = {None: '31d59e41-05db-4a39-8aca-6a9a572c83cd'}
        ep_name = 'test'
        target = utils.get_current_endpoints_target(
                ep, port, spec_ports, ep_name)
        self.assertEqual(
            target, ('10.0.2.107', 'test-868d9cbd68-xq2fl', 8080,
                     '31d59e41-05db-4a39-8aca-6a9a572c83cd'))

    def test_get_current_endpoints_target_without_target_ref(self):
        ep = {'addresses': ['10.0.1.208'], 'conditions': {'ready': True}}
        port = {'port': 8080, 'protocol': 'TCP'}
        spec_ports = {None: '4472fab1-f01c-46a7-b197-5cba4f2d7135'}
        ep_name = 'test'
        target = utils.get_current_endpoints_target(
                ep, port, spec_ports, ep_name)
        self.assertEqual(
            target, ('10.0.1.208', 'test', 8080,
                     '4472fab1-f01c-46a7-b197-5cba4f2d7135'))

    def test_get_klb_crd_path(self):
        res = {'apiVersion': 'v1',
               'kind': 'Endpoints',
               'metadata': {'name': 'my-service',
                            'namespace': 'default'}}
        self.assertEqual(utils.get_klb_crd_path(res),
                         '/apis/openstack.org/v1/namespaces/default/'
                         'kuryrloadbalancers/my-service')

    def test_get_res_link_core_res(self):
        res = {'apiVersion': 'v1',
               'kind': 'Pod',
               'metadata': {'name': 'pod-1',
                            'namespace': 'default'}}
        self.assertEqual(utils.get_res_link(res),
                         '/api/v1/namespaces/default/pods/pod-1')

    def test_get_res_link_no_existent(self):
        res = {'apiVersion': 'customapi/v1',
               'kind': 'ItsATrap!',
               'metadata': {'name': 'pod-1',
                            'namespace': 'default'}}
        self.assertRaises(KeyError, utils.get_res_link, res)

    def test_get_res_link_beta_res(self):
        res = {'apiVersion': 'networking.k8s.io/v2beta2',
               'kind': 'NetworkPolicy',
               'metadata': {'name': 'np-1',
                            'namespace': 'default'}}
        self.assertEqual(utils.get_res_link(res), '/apis/networking.k8s.io/'
                         'v2beta2/namespaces/default/networkpolicies/np-1')

    def test_get_res_link_no_namespace(self):
        res = {'apiVersion': 'v1',
               'kind': 'Namespace',
               'metadata': {'name': 'ns-1'}}

        self.assertEqual(utils.get_res_link(res), '/api/v1/namespaces/ns-1')

    def test_get_res_link_custom_api(self):
        res = {'apiVersion': 'openstack.org/v1',
               'kind': 'KuryrPort',
               'metadata': {'name': 'kp-1',
                            'namespace': 'default'}}

        self.assertEqual(utils.get_res_link(res),
                         '/apis/openstack.org/v1/namespaces/default/'
                         'kuryrports/kp-1')

    def test_get_res_link_no_apiversion(self):
        res = {'kind': 'KuryrPort',
               'metadata': {'name': 'kp-1',
                            'namespace': 'default'}}
        self.assertRaises(KeyError, utils.get_res_link, res)

    def test_get_api_ver_core_api(self):
        path = '/api/v1/namespaces/default/pods/pod-123'
        self.assertEqual(utils.get_api_ver(path), 'v1')

    def test_get_api_ver_custom_resource(self):
        path = '/apis/openstack.org/v1/namespaces/default/kuryrport/pod-123'
        self.assertEqual(utils.get_api_ver(path), 'openstack.org/v1')

    def test_get_api_ver_random_path(self):
        path = '/?search=foo'
        self.assertRaises(ValueError, utils.get_api_ver, path)

    def test_get_res_selflink_still_available(self):
        res = {'metadata': {'selfLink': '/foo'}}

        self.assertEqual(utils.get_res_link(res), '/foo')

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test_get_subnet_id(self, m_get_net):
        m_net = mock.Mock()
        m_get_net.return_value = m_net
        subnets = (mock.Mock(id=mock.sentinel.subnet1),
                   mock.Mock(id=mock.sentinel.subnet2))
        m_net.subnets.return_value = iter(subnets)
        filters = {'name': 'foo', 'tags': 'bar'}
        sub = utils.get_subnet_id(**filters)
        m_net.subnets.assert_called_with(**filters)
        self.assertEqual(mock.sentinel.subnet1, sub)

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    def test_get_subnet_not_found(self, m_get_net):
        m_net = mock.Mock()
        m_get_net.return_value = m_net
        m_net.subnets.return_value = iter(())
        filters = {'name': 'foo', 'tags': 'bar'}
        sub = utils.get_subnet_id(**filters)
        m_net.subnets.assert_called_with(**filters)
        self.assertIsNone(sub)

    def test_is_pod_completed_pending(self):
        self.assertFalse(utils.is_pod_completed({'status': {'phase':
                         k_const.K8S_POD_STATUS_PENDING}}))

    def test_is_pod_completed_succeeded(self):
        self.assertTrue(utils.is_pod_completed({'status': {'phase':
                        k_const.K8S_POD_STATUS_SUCCEEDED}}))

    def test_is_pod_completed_failed(self):
        self.assertTrue(utils.is_pod_completed({'status': {'phase':
                        k_const.K8S_POD_STATUS_FAILED}}))
