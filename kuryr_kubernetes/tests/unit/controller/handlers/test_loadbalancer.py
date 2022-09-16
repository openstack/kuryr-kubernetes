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
import uuid

import os_vif.objects.network as osv_network
import os_vif.objects.subnet as osv_subnet

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes.controller.handlers import loadbalancer as h_lb
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix

_SUPPORTED_LISTENER_PROT = ('HTTP', 'HTTPS', 'TCP')


def get_lb_crd():
    return {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            "metadata": {
                "creationTimestamp": "2020-07-28T13:13:30Z",
                "finalizers": [
                    ""
                ],
                "generation": 6,
                "name": "test",
                "namespace": "default",
                "resourceVersion": "111871",
                "uid": "584fe3ea-04dd-43f7-be2f-713e861694ec"
            },
            "spec": {
                "ip": "1.2.3.4",
                "ports": [
                    {
                        "port": 1,
                        "protocol": "TCP",
                        "targetPort": "1"
                    }
                ],
                "project_id": "1023456789120",
                "security_groups_ids": [
                    "1d134e68-5653-4192-bda2-4214319af799",
                    "31d7b8c2-75f1-4125-9565-8c15c5cf046c"
                ],
                "subnet_id": "123456789120",
                "endpointSlices": [
                    {
                        "endpoints": [
                            {
                                "addresses": ["1.1.1.1"],
                                "targetRef": {
                                    "kind": "Pod",
                                    "name": "test-f87976f9c-thjbk",
                                    "namespace": "default",
                                    "resourceVersion": "111701",
                                    "uid": "10234567800"
                                }
                            }
                        ],
                        "ports": [
                            {
                                "port": 2,
                                "protocol": "TCP"
                            }
                        ]
                    }
                ],
                "type": "LoadBalancer",
                "provider": "ovn"
                },
            "status": {
                "listeners": [
                    {
                        "id": "012345678912",
                        "loadbalancer_id": "01234567890",
                        "name": "default/test:TCP:80",
                        "port": 1,
                        "project_id": "12345678912",
                        "protocol": "TCP"
                    }
                ],
                "loadbalancer": {
                    "id": "01234567890",
                    "ip": "1.2.3.4",
                    "name": "default/test",
                    "port_id": "1023456789120",
                    "project_id": "12345678912",
                    "provider": "amphora",
                    "security_groups": [
                        "1d134e68-5653-4192-bda2-4214319af799",
                        "31d7b8c2-75f1-4125-9565-8c15c5cf046c"
                    ],
                    "subnet_id": "123456789120"
                },
                "members": [
                    {
                        "id": "0123456789",
                        "ip": "1.1.1.1",
                        "name": "default/test-f87976f9c-thjbk:8080",
                        "pool_id": "1234567890",
                        "port": 2,
                        "project_id": "12345678912",
                        "subnet_id": "123456789120"
                    }
                ],
                "pools": [
                    {
                        "id": "1234567890",
                        "listener_id": "012345678912",
                        "loadbalancer_id": "01234567890",
                        "name": "default/test:TCP:80",
                        "project_id": "12345678912",
                        "protocol": "TCP"
                    }
                ],
                'service_pub_ip_info': {
                    'ip_id': '1.2.3.5',
                    'ip_addr': 'ec29d641-fec4-4f67-928a-124a76b3a888',
                    'alloc_method': 'kk'
                }
            }
        }


def get_lb_crds():
    return [
            {
                'apiVersion': 'openstack.org/v1',
                'kind': 'KuryrLoadBalancer',
                "metadata": {
                    "creationTimestamp": "2020-07-28T13:13:30Z",
                    "finalizers": [
                        ""
                    ],
                    "generation": 6,
                    "name": "test",
                    "namespace": "default",
                    "resourceVersion": "111871",
                    "uid": "584fe3ea-04dd-43f7-be2f-713e861694ec"
                },
                "status": {
                    "listeners": [
                        {
                            "id": "012345678912",
                            "loadbalancer_id": "01234567890",
                            "name": "default/test:TCP:80",
                            "port": 1,
                            "project_id": "12345678912",
                            "protocol": "TCP"
                        }
                    ],
                    "loadbalancer": {
                        "id": "01234567890",
                        "ip": "1.2.3.4",
                        "name": "default/test",
                        "port_id": "1023456789120",
                        "project_id": "12345678912",
                        "provider": "amphora",
                        "security_groups": [
                            "1d134e68-5653-4192-bda2-4214319af799",
                            "31d7b8c2-75f1-4125-9565-8c15c5cf046c"
                        ],
                        "subnet_id": "123456789120"
                    },
                    "pools": [
                        {
                            "id": "1234567890",
                            "listener_id": "012345678912",
                            "loadbalancer_id": "01234567890",
                            "name": "default/test:TCP:80",
                            "project_id": "12345678912",
                            "protocol": "TCP"
                        }
                    ],
                    "members": [
                        {
                            "id": "0123456789a",
                            "ip": "1.1.1.1",
                            "name": "default/test-f87976f9c-thjbk:8080",
                            "pool_id": "1234567890",
                            "port": 2,
                            "project_id": "12345678912",
                            "subnet_id": "123456789120"
                        }
                    ],
                }
            },
            {
             'apiVersion': 'openstack.org/v1',
             'kind': 'KuryrLoadBalancer',
             "metadata": {
                "creationTimestamp": "2020-07-28T13:13:30Z",
                "finalizers": [
                    ""
                ],
                "generation": 6,
                "name": "demo",
                "namespace": "default",
                "resourceVersion": "111871",
                "uid": "584fe3ea-04dd-43f7-be2f-713e861694ec"
                },
             "status": {
                 "listeners": [
                    {
                        "id": "012345678913",
                        "loadbalancer_id": "01234567891",
                        "name": "default/demo:TCP:80",
                        "port": 1,
                        "project_id": "12345678912",
                        "protocol": "TCP"
                    }
                 ],
                 "loadbalancer": {
                     "id": "01234567891",
                     "ip": "1.2.3.4",
                     "name": "default/demo",
                     "port_id": "1023456789120",
                     "project_id": "12345678912",
                     "provider": "amphora",
                     "security_groups": [
                         "1d134e68-5653-4192-bda2-4214319af799",
                         "31d7b8c2-75f1-4125-9565-8c15c5cf046c"
                     ],
                     "subnet_id": "123456789120"
                    },
                 "pools": [
                     {
                         "id": "1234567891",
                         "listener_id": "012345678913",
                         "loadbalancer_id": "01234567891",
                         "name": "default/test:TCP:80",
                         "project_id": "12345678912",
                         "protocol": "TCP"
                     }
                 ],
                 "members": [
                     {
                         "id": "0123456789b",
                         "ip": "1.1.1.1",
                         "name": "default/test_1-f87976f9c-thjbk:8080",
                         "pool_id": "1234567891",
                         "port": 2,
                         "project_id": "12345678913",
                         "subnet_id": "123456789121"
                     }
                 ],
                }
            }
        ]


class FakeLBaaSDriver(drv_base.LBaaSDriver):

    def ensure_loadbalancer(self, name, project_id, subnet_id, ip,
                            security_groups_ids, service_type, provider=None):

        return {
            'name': name,
            'project_id': project_id,
            'subnet_id': subnet_id,
            'ip': ip,
            'id': str(uuid.uuid4()),
            'provider': provider
        }

    def ensure_listener(self, loadbalancer, protocol, port,
                        service_type='ClusterIP'):
        if protocol not in _SUPPORTED_LISTENER_PROT:
            return None

        name = "%s:%s:%s" % (loadbalancer['name'], protocol, port)
        return {
            'name': name,
            'project_id': loadbalancer['project_id'],
            'loadbalancer_id': loadbalancer['id'],
            'protocol': protocol,
            'port': port,
            'id': str(uuid.uuid4())
        }

    def ensure_pool(self, loadbalancer, listener):
        return {
            'name': listener['name'],
            'project_id': loadbalancer['project_id'],
            'loadbalancer_id': loadbalancer['id'],
            'listener_id': listener['id'],
            'protocol': listener['protocol'],
            'id': str(uuid.uuid4())
        }

    def ensure_member(self, loadbalancer, pool, subnet_id, ip, port,
                      target_ref_namespace, target_ref_name, listener_port=None
                      ):
        name = "%s:%s:%s" % (loadbalancer['name'], ip, port)
        return {
            'name': name,
            'project_id': pool['project_id'],
            'pool_id': pool['id'],
            'subnet_id': subnet_id,
            'ip': ip,
            'port': port,
            'id': str(uuid.uuid4())
        }


@mock.patch('kuryr_kubernetes.utils.get_subnets_id_cidrs',
            mock.Mock(return_value=[('id', 'cidr')]))
class TestKuryrLoadBalancerHandler(test_base.TestCase):
    def test_on_present(self):
        m_drv_service_pub_ip = mock.Mock()
        m_drv_service_pub_ip.acquire_service_pub_ip_info.return_value = None
        m_drv_service_pub_ip.associate_pub_ip.return_value = True

        m_handler = mock.Mock(spec=h_lb.KuryrLoadBalancerHandler)

        m_handler._should_ignore.return_value = False
        m_handler._sync_lbaas_members.return_value = True
        m_handler._drv_service_pub_ip = m_drv_service_pub_ip

        h_lb.KuryrLoadBalancerHandler.on_present(m_handler, get_lb_crd())

        m_handler._should_ignore.assert_called_once_with(get_lb_crd())
        m_handler._sync_lbaas_members.assert_called_once_with(
            get_lb_crd())

    def _fake_sync_lbaas_members(self, crd):
        loadbalancer = {
            "id": "01234567890",
            "ip": "1.2.3.4",
            "name": "default/test",
            "port_id": "1023456789120",
            "project_id": "12345678912",
            "provider": "amphora",
            "security_groups": [
                "1d134e68-5653-4192-bda2-4214319af799",
                "31d7b8c2-75f1-4125-9565-8c15c5cf046c"
            ],
            "subnet_id": "123456789120"
        }
        loadbalancer['port_id'] = 12345678
        crd['status']['loadbalancer'] = loadbalancer
        crd['status']['service_pub_ip_info'] = None
        return True

    def test_on_present_loadbalancer_service(self):
        floating_ip = {'floating_ip_address': '1.2.3.5',
                       'id': 'ec29d641-fec4-4f67-928a-124a76b3a888'}

        service_pub_ip_info = {
            'ip_id': floating_ip['id'],
            'ip_addr': floating_ip['floating_ip_address'],
            'alloc_method': 'kk'
        }
        crd = get_lb_crd()
        m_drv_service_pub_ip = mock.Mock()
        m_drv_service_pub_ip.acquire_service_pub_ip_info.return_value = (
            service_pub_ip_info)
        m_drv_service_pub_ip.associate_pub_ip.return_value = True

        h = mock.Mock(spec=h_lb.KuryrLoadBalancerHandler)
        h._should_ignore.return_value = False
        h._sync_lbaas_members.return_value = self._fake_sync_lbaas_members(crd)
        h._drv_service_pub_ip = m_drv_service_pub_ip
        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        kubernetes.get_kubernetes_client = mock.Mock()
        kubernetes.get_kubernetes_client()
        h_lb.KuryrLoadBalancerHandler.on_present(h, crd)
        h._should_ignore.assert_called_once_with(crd)
        h._update_lb_status.assert_called()

    @mock.patch('kuryr_kubernetes.utils.get_lbaas_spec')
    @mock.patch('kuryr_kubernetes.utils.set_lbaas_state')
    @mock.patch('kuryr_kubernetes.utils.get_lbaas_state')
    def test_on_present_rollback(self, m_get_lbaas_state,
                                 m_set_lbaas_state, m_get_lbaas_spec):
        m_drv_service_pub_ip = mock.Mock()
        m_drv_service_pub_ip.acquire_service_pub_ip_info.return_value = None
        m_drv_service_pub_ip.associate_pub_ip.return_value = True

        m_handler = mock.Mock(spec=h_lb.KuryrLoadBalancerHandler)
        m_handler._should_ignore.return_value = False
        m_handler._sync_lbaas_members.return_value = True
        m_handler._drv_service_pub_ip = m_drv_service_pub_ip
        h_lb.KuryrLoadBalancerHandler.on_present(m_handler, get_lb_crd())

        m_handler._should_ignore.assert_called_once_with(get_lb_crd())
        m_handler._sync_lbaas_members.assert_called_once_with(
            get_lb_crd())

    def test_on_cascade_deleted_lb_service(self):
        m_handler = mock.Mock(spec=h_lb.KuryrLoadBalancerHandler)
        m_handler._drv_lbaas = mock.Mock()
        m_handler._drv_service_pub_ip = mock.Mock()
        crd = get_lb_crd()
        m_handler._drv_lbaas.release_loadbalancer(
            loadbalancer=crd['status']['loadbalancer'])
        m_handler._drv_service_pub_ip.release_pub_ip(
            crd['status']['service_pub_ip_info'])

    def test_should_ignore(self):
        m_handler = mock.Mock(spec=h_lb.KuryrLoadBalancerHandler)
        loadbalancer_crd = get_lb_crd()
        loadbalancer_crd['status'] = {}
        m_handler._has_endpoints.return_value = True

        ret = h_lb.KuryrLoadBalancerHandler._should_ignore(
            m_handler, loadbalancer_crd)
        self.assertEqual(False, ret)

        m_handler._has_endpoints.assert_called_once_with(loadbalancer_crd)

    def test_should_ignore_member_scale_to_0(self):
        m_handler = mock.Mock(spec=h_lb.KuryrLoadBalancerHandler)
        m_handler._has_endpoints.return_value = False
        loadbalancer_crd = get_lb_crd()

        ret = h_lb.KuryrLoadBalancerHandler._should_ignore(
            m_handler, loadbalancer_crd)
        self.assertEqual(False, ret)

        m_handler._has_endpoints.assert_called_once_with(loadbalancer_crd)

    def test_has_endpoints(self):
        crd = get_lb_crd()
        m_handler = mock.Mock(spec=h_lb.KuryrLoadBalancerHandler)

        ret = h_lb.KuryrLoadBalancerHandler._has_endpoints(m_handler, crd)

        self.assertEqual(True, ret)

    def test_get_pod_subnet(self):
        subnet_id = mock.sentinel.subnet_id
        project_id = mock.sentinel.project_id
        target_ref = {'kind': k_const.K8S_OBJ_POD,
                      'name': 'pod-name',
                      'namespace': 'default',
                      'spec': {}}
        ip = '1.2.3.4'
        m_handler = mock.Mock(spec=h_lb.KuryrLoadBalancerHandler)
        m_drv_pod_project = mock.Mock()
        m_drv_pod_project.get_project.return_value = project_id
        m_handler._drv_pod_project = m_drv_pod_project
        m_drv_pod_subnets = mock.Mock()
        m_drv_pod_subnets.get_subnets.return_value = {
            subnet_id: osv_network.Network(subnets=osv_subnet.SubnetList(
                objects=[osv_subnet.Subnet(cidr='1.2.3.0/24')]))}
        m_handler._drv_pod_subnets = m_drv_pod_subnets

        observed_subnet_id = h_lb.KuryrLoadBalancerHandler._get_pod_subnet(
            m_handler, target_ref, ip)

        self.assertEqual(subnet_id, observed_subnet_id)

    def _sync_lbaas_members_impl(self, m_get_drv_lbaas, m_get_drv_project,
                                 m_get_drv_subnets, subnet_id, project_id,
                                 crd):
        m_drv_lbaas = mock.Mock(wraps=FakeLBaaSDriver())
        m_drv_project = mock.Mock()
        m_drv_project.get_project.return_value = project_id
        m_drv_subnets = mock.Mock()
        m_drv_subnets.get_subnets.return_value = {
            subnet_id: mock.sentinel.subnet}
        m_get_drv_lbaas.return_value = m_drv_lbaas
        m_get_drv_project.return_value = m_drv_project
        m_get_drv_subnets.return_value = m_drv_subnets

        handler = h_lb.KuryrLoadBalancerHandler()

        with mock.patch.object(handler, '_get_pod_subnet') as m_get_pod_subnet:
            m_get_pod_subnet.return_value = subnet_id
            handler._sync_lbaas_members(crd)

        lsnrs = {lsnr['id']: lsnr for lsnr in crd['status']['listeners']}
        pools = {pool['id']: pool for pool in crd['status']['pools']}
        observed_targets = sorted(
            (str(member['ip']), (
                lsnrs[pools[member['pool_id']]['listener_id']]['port'],
                member['port']))
            for member in crd['status']['members'])
        return observed_targets

    @mock.patch('kuryr_kubernetes.utils.get_subnet_cidr')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceSecurityGroupsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodSubnetsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.NodesSubnetsDriver.get_instance', mock.Mock())
    def test_sync_lbaas_members(self, m_get_drv_lbaas, m_get_drv_project,
                                m_get_drv_subnets, m_k8s, m_svc_project_drv,
                                m_svc_sg_drv, m_get_cidr):
        # REVISIT(ivc): test methods separately and verify ensure/release
        m_get_cidr.return_value = '10.0.0.128/26'
        project_id = str(uuid.uuid4())
        subnet_id = str(uuid.uuid4())
        expected_ip = '1.2.3.4'
        expected_targets = {
            '1.1.1.1': (1, 2),
            '1.1.1.1': (1, 2),
            '1.1.1.1': (1, 2)}
        crd = get_lb_crd()

        observed_targets = self._sync_lbaas_members_impl(
            m_get_drv_lbaas, m_get_drv_project, m_get_drv_subnets,
            subnet_id, project_id, crd)

        self.assertEqual(sorted(expected_targets.items()), observed_targets)
        self.assertEqual(expected_ip, str(crd['status']['loadbalancer']['ip']))

    @mock.patch('kuryr_kubernetes.utils.get_subnet_cidr')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceSecurityGroupsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodSubnetsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.NodesSubnetsDriver.get_instance', mock.Mock())
    def test_sync_lbaas_members_udp(self, m_get_drv_lbaas,
                                    m_get_drv_project, m_get_drv_subnets,
                                    m_k8s, m_svc_project_drv, m_svc_sg_drv,
                                    m_get_cidr):
        # REVISIT(ivc): test methods separately and verify ensure/release
        m_get_cidr.return_value = '10.0.0.128/26'
        project_id = str(uuid.uuid4())
        subnet_id = str(uuid.uuid4())
        expected_ip = "1.2.3.4"
        expected_targets = {
            '1.1.1.1': (1, 2),
            '1.1.1.1': (1, 2),
            '1.1.1.1': (1, 2)}

        crd = get_lb_crd()

        observed_targets = self._sync_lbaas_members_impl(
            m_get_drv_lbaas, m_get_drv_project, m_get_drv_subnets,
            subnet_id, project_id, crd)

        self.assertEqual(sorted(expected_targets.items()), observed_targets)
        self.assertEqual(expected_ip, str(crd['status']['loadbalancer']['ip']))

    @mock.patch('kuryr_kubernetes.utils.get_subnet_cidr')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceSecurityGroupsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodSubnetsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.NodesSubnetsDriver.get_instance', mock.Mock())
    def test_sync_lbaas_members_svc_listener_port_edit(
            self, m_get_drv_lbaas, m_get_drv_project, m_get_drv_subnets,
            m_k8s, m_svc_project_drv, m_svc_sg_drv, m_get_cidr):
        # REVISIT(ivc): test methods separately and verify ensure/release
        m_get_cidr.return_value = '10.0.0.128/26'
        project_id = str(uuid.uuid4())
        subnet_id = str(uuid.uuid4())
        expected_ip = '1.2.3.4'
        crd = get_lb_crd()

        m_drv_lbaas = mock.Mock(wraps=FakeLBaaSDriver())
        m_drv_project = mock.Mock()
        m_drv_project.get_project.return_value = project_id
        m_drv_subnets = mock.Mock()
        m_drv_subnets.get_subnets.return_value = {
            subnet_id: mock.sentinel.subnet}
        m_get_drv_lbaas.return_value = m_drv_lbaas
        m_get_drv_project.return_value = m_drv_project
        m_get_drv_subnets.return_value = m_drv_subnets

        handler = h_lb.KuryrLoadBalancerHandler()

        with mock.patch.object(handler, '_get_pod_subnet') as m_get_pod_subnet:
            m_get_pod_subnet.return_value = subnet_id
            handler._sync_lbaas_members(crd)

        self.assertEqual(expected_ip, str(crd['status']['loadbalancer']['ip']))

    @mock.patch('kuryr_kubernetes.utils.get_subnet_cidr')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceSecurityGroupsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base.'
                'ServiceProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodSubnetsDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.PodProjectDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.NodesSubnetsDriver.get_instance', mock.Mock())
    def test_add_new_members_udp(self, m_get_drv_lbaas,
                                 m_get_drv_project, m_get_drv_subnets,
                                 m_k8s, m_svc_project_drv,
                                 m_svc_sg_drv, m_get_cidr):
        m_get_cidr.return_value = '10.0.0.128/26'
        project_id = str(uuid.uuid4())
        subnet_id = str(uuid.uuid4())
        crd = get_lb_crd()

        m_drv_lbaas = mock.Mock(wraps=FakeLBaaSDriver())
        m_drv_project = mock.Mock()
        m_drv_project.get_project.return_value = project_id
        m_drv_subnets = mock.Mock()
        m_drv_subnets.get_subnets.return_value = {
            subnet_id: mock.sentinel.subnet}
        m_get_drv_lbaas.return_value = m_drv_lbaas
        m_get_drv_project.return_value = m_drv_project
        m_get_drv_subnets.return_value = m_drv_subnets

        handler = h_lb.KuryrLoadBalancerHandler()
        member_added = handler._add_new_members(crd)

        self.assertEqual(member_added, False)
        m_drv_lbaas.ensure_member.assert_not_called()

    @mock.patch('kuryr_kubernetes.utils.get_res_link')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    def test_reconcile_loadbalancers(self, m_get_drv_lbaas, m_k8s,
                                     m_get_res_link):
        loadbalancer_crds = get_lb_crds()
        m_handler = mock.MagicMock(spec=h_lb.KuryrLoadBalancerHandler)
        m_handler._drv_lbaas = m_get_drv_lbaas
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client
        lbaas.load_balancers.return_value = []
        lbaas.listeners.return_value = []
        lbaas.pools.return_value = []
        lbaas.members.return_value = []
        selflink = ('/apis/openstack.org/v1/namespaces/default/'
                    'kuryrloadbalancers/test')
        m_get_res_link.return_value = selflink
        h_lb.KuryrLoadBalancerHandler._trigger_reconciliation(
            m_handler, loadbalancer_crds)
        filters = {}
        lbaas.load_balancers.assert_called_once_with(**filters)
        m_handler._reconcile_lb.assert_called_with({'id': mock.ANY,
                                                    'selflink': selflink,
                                                    'klb': mock.ANY})

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('kuryr_kubernetes.controller.drivers.base'
                '.LBaaSDriver.get_instance')
    def test_reconcile_loadbalancers_in_sync(self, m_get_drv_lbaas, m_k8s):
        loadbalancer_crds = get_lb_crds()

        m_handler = mock.MagicMock(spec=h_lb.KuryrLoadBalancerHandler)
        m_handler._drv_lbaas = m_get_drv_lbaas
        lbaas = self.useFixture(k_fix.MockLBaaSClient()).client

        loadbalancers_id = [{'id': '01234567890'}, {'id': '01234567891'}]
        listeners_id = [{'id': '012345678912'}, {'id': '012345678913'}]
        pools_id = [{'id': '1234567890'}, {'id': '1234567891'}]
        members_id = [{"id": "0123456789a"}, {"id": "0123456789b"}]
        lbaas.load_balancers.return_value = loadbalancers_id
        lbaas.listeners.return_value = listeners_id
        lbaas.pools.return_value = pools_id
        lbaas.members.return_value = members_id

        h_lb.KuryrLoadBalancerHandler._trigger_reconciliation(
                m_handler, loadbalancer_crds)
        m_handler._reconcile_lb.assert_not_called()
