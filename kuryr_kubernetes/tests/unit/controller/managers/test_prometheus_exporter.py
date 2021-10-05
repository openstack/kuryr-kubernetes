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
import munch
import prometheus_client
from unittest import mock

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
        self.srv._project_id = mock.sentinel.project_id
        self.srv._os_net = self.useFixture(k_fix.MockNetworkClient()).client

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
        subnets = [munch.Munch(
            {'id': subnet_id, 'name': subnet_name,
             'network_id': network_id, 'allocation_pools': [
                 {'start': '10.128.70.2', 'end': '10.128.71.254'}]})]
        ports = [mock.MagicMock()]
        self.srv._os_net.subnets.return_value = subnets
        self.srv._os_net.ports.return_value = ports
        self.cls._record_ports_quota_per_subnet_metric(self.srv)
        self.srv.port_quota_per_subnet.labels.assert_called_with(
            **{'subnet_id': subnet_id, 'subnet_name': subnet_name})
        self.srv.port_quota_per_subnet.labels().set.assert_called_with(508)
