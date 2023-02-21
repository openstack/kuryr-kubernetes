# Copyright 2021 Red Hat
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

import prometheus_client
from unittest import mock

from openstack.load_balancer.v2 import load_balancer as os_lb
from openstack.load_balancer.v2 import pool as os_pool
from openstack.network.v2 import subnet as os_subnet

from kuryr_kubernetes.controller.managers import prometheus_exporter
from kuryr_kubernetes.tests import base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


def get_quota_obj():
    return {
            'subnets': {
                'used': 50,
                'limit': 100,
                'reserved': 0
            },
            'networks': {
                'used': 50,
                'limit': 100,
                'reserved': 0
            },
            'security_group_rules': {
                'used': 50,
                'limit': 100,
                'reserved': 0
            },
            'security_groups': {
                'used': 5,
                'limit': 10,
                'reserved': 0
            },
            'ports': {
                'used': 250,
                'limit': 500,
                'reserved': 0
            }
        }


class TestControllerPrometheusExporter(base.TestCase):

    def setUp(self):
        super(TestControllerPrometheusExporter, self).setUp()
        self.cls = prometheus_exporter.ControllerPrometheusExporter
        self.srv = mock.MagicMock(spec=self.cls)
        self.srv.quota_free_count = mock.MagicMock(
            spec=prometheus_client.Gauge)
        self.srv.port_quota_per_subnet = mock.MagicMock(
            spec=prometheus_client.Gauge)
        self.srv.lbs_members_count = mock.MagicMock(
            spec=prometheus_client.Gauge)
        self.srv.lbs_state = mock.MagicMock(
            spec=prometheus_client.Enum)
        self.srv._project_id = mock.sentinel.project_id
        self.srv._os_net = self.useFixture(k_fix.MockNetworkClient()).client
        self.srv._os_lb = self.useFixture(k_fix.MockLBaaSClient()).client

    def test__record_quota_free_count_metric(self):
        quota = get_quota_obj()
        self.srv._os_net.get_quota.return_value = quota
        self.cls._record_quota_free_count_metric(self.srv)
        calls = []
        for resource in prometheus_exporter.RESOURCES:
            calls.extend(
                [mock.call(**{'resource': resource}),
                 mock.call().set(
                    quota[resource]['limit']-quota[resource]['used'])])
        self.srv.quota_free_count.labels.assert_has_calls(calls)

    def test__record_no_quota_free_count_metric(self):
        quota = get_quota_obj()
        for resource in quota:
            quota[resource]['used'] = quota[resource]['limit']
        self.srv._os_net.get_quota.return_value = quota
        self.cls._record_quota_free_count_metric(self.srv)
        calls = []
        for resource in prometheus_exporter.RESOURCES:
            calls.extend(
                [mock.call(**{'resource': resource}),
                 mock.call().set(0)])
        self.srv.quota_free_count.labels.assert_has_calls(calls)

    def test__record_ports_quota_per_subnet_metric(self):
        subnet_id = mock.sentinel.id
        subnet_name = 'ns/cluster-version-net'
        network_id = mock.sentinel.network_id
        subnets = [
            os_subnet.Subnet(
                id=subnet_id,
                name=subnet_name,
                network_id=network_id,
                allocation_pools=[
                    {'start': '10.128.70.2', 'end': '10.128.71.254'},
                ],
            ),
        ]
        ports = [mock.MagicMock()]
        self.srv._os_net.subnets.return_value = subnets
        self.srv._os_net.ports.return_value = ports
        self.cls._record_ports_quota_per_subnet_metric(self.srv)
        self.srv.port_quota_per_subnet.labels.assert_called_with(
            **{'subnet_id': subnet_id, 'subnet_name': subnet_name})
        self.srv.port_quota_per_subnet.labels().set.assert_called_with(509)

    @mock.patch('kuryr_kubernetes.utils.get_kuryrloadbalancer')
    def test__record_lbs_metrics(self, m_get_klb):
        lb_name = 'default/kubernetes'
        lb_id = mock.sentinel.id
        pool_name = mock.sentinel.name
        pool_id = mock.sentinel.id
        lb_state = 'ACTIVE'
        m_get_klb.return_value = {
            "status": {
                "loadbalancer": {
                    "id": lb_id,
                }
            }
        }
        self.srv._os_lb.find_load_balancer.return_value = os_lb.LoadBalancer(
            id=lb_id,
            name=lb_name,
            provisioning_status=lb_state,
            pools=[{'id': pool_id}],
        )
        self.srv._os_lb.pools.return_value = [
            os_pool.Pool(
                id=pool_id,
                name=pool_name,
                loadbalancers=[{'id': lb_id}],
                members=[{'id': mock.sentinel.id}],
            ),
        ]

        self.cls._record_lbs_metrics(self.srv)

        self.srv.lbs_state.labels.assert_called_with(
                **{'lb_name': lb_name})
        self.srv.lbs_state.labels().state.assert_called_with(lb_state)
        self.srv.lbs_members_count.labels.assert_called_with(
            **{'lb_name': lb_name, 'lb_pool_name': pool_name})
        self.srv.lbs_members_count.labels().set.assert_called_with(1)

    @mock.patch('kuryr_kubernetes.utils.get_kuryrloadbalancer')
    def test__record_no_lb_present_metric(self, m_get_klb):
        lb_name = 'default/kubernetes'
        lb_id = mock.sentinel.id
        m_get_klb.return_value = {
            "status": {
                "loadbalancer": {
                    "id": lb_id,
                }
            }
        }
        self.srv._os_lb.find_load_balancer.return_value = None
        self.cls._record_lbs_metrics(self.srv)
        self.srv.lbs_state.labels.assert_called_with(
                **{'lb_name': lb_name})
        self.srv.lbs_state.labels().state.assert_called_with('DELETED')

    @mock.patch('kuryr_kubernetes.utils.get_kuryrloadbalancer')
    def test__no_record_lbs_metrics(self, m_get_klb):
        m_get_klb.return_value = {}

        self.cls._record_lbs_metrics(self.srv)

        self.srv.lbs_state.labels.assert_not_called()
        self.srv.lbs_state.labels().state.assert_not_called()
        self.srv.lbs_members_count.labels.assert_not_called()
        self.srv.lbs_members_count.labels().set.assert_not_called()
