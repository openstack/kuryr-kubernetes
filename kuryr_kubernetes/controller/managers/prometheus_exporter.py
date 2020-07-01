# Copyright 2020 Red Hat, Inc.
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

import flask
import netaddr
import prometheus_client
from prometheus_client.exposition import generate_latest

from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
RESOURCES = ('ports', 'subnets', 'networks', 'security_groups',
             'security_group_rules')
_NO_QUOTA = 0
_INF = float("inf")
_NO_LIMIT = -1


class ControllerPrometheusExporter(object):
    """Provides metrics to Prometheus"""

    instance = None

    def __init__(self):
        self.application = flask.Flask('prometheus-exporter')
        self.ctx = None
        self.application.add_url_rule(
            '/metrics', methods=['GET'], view_func=self.metrics)
        self.headers = {'Connection': 'close'}
        self._os_net = clients.get_network_client()
        self._project_id = config.CONF.neutron_defaults.project
        self._create_metrics()

    def metrics(self):
        """Provides the registered metrics"""
        self._record_quota_free_count_metric()
        self._record_ports_quota_per_subnet_metric()

        collected_metric = generate_latest(self.registry)
        return flask.Response(collected_metric, mimetype='text/plain')

    def record_pod_creation_metric(self, duration):
        """Records pod creation duration to the registry"""
        self.pod_creation_latency.observe(duration)

    @classmethod
    def get_instance(cls):
        if not ControllerPrometheusExporter.instance:
            ControllerPrometheusExporter.instance = cls()
        return ControllerPrometheusExporter.instance

    def run(self):
        address = '::'
        try:
            LOG.info('Starting Prometheus exporter')
            self.application.run(
                address, CONF.prometheus_exporter.controller_exporter_port)
        except Exception:
            LOG.exception('Failed to start Prometheus exporter')
            raise

    def _record_quota_free_count_metric(self):
        """Records Network resources availability to the registry"""
        quota = self._os_net.get_quota(quota=self._project_id, details=True)
        for resource in RESOURCES:
            resource_quota = quota[resource]
            labels = {'resource': resource}
            quota_limit = resource_quota['limit']
            if quota_limit == _NO_LIMIT:
                self.quota_free_count.labels(**labels).set(quota_limit)
                continue
            quota_used = resource_quota['used']
            availability = quota_limit - quota_used
            if availability >= _NO_QUOTA:
                self.quota_free_count.labels(**labels).set(availability)

    def _record_ports_quota_per_subnet_metric(self):
        """Records the ports quota per subnet to the registry"""
        subnets = self._os_net.subnets(project_id=self._project_id)
        namespace_prefix = 'ns/'
        for subnet in subnets:
            if namespace_prefix not in subnet.name:
                continue
            total_num_addresses = 0
            ports_availability = 0
            for allocation in subnet.allocation_pools:
                total_num_addresses += netaddr.IPRange(
                    netaddr.IPAddress(allocation['start']),
                    netaddr.IPAddress(allocation['end'])).size
                ports_count = len(list(self._os_net.ports(
                    network_id=subnet.network_id,
                    project_id=self._project_id)))
            labels = {'subnet_id': subnet.id, 'subnet_name': subnet.name}
            ports_availability = total_num_addresses-ports_count
            self.port_quota_per_subnet.labels(**labels).set(ports_availability)

    def _create_metrics(self):
        """Creates a registry and records a new Gauge metric"""
        self.registry = prometheus_client.CollectorRegistry()
        self.quota_free_count = prometheus_client.Gauge(
            'kuryr_quota_free_count', 'Amount of quota available'
            ' for the network resource', labelnames={'resource'},
            registry=self.registry)

        self.port_quota_per_subnet = prometheus_client.Gauge(
            'kuryr_port_quota_per_subnet', 'Amount of ports available'
            ' on Subnet', labelnames={'subnet_id', 'subnet_name'},
            registry=self.registry)

        buckets = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, _INF)
        self.pod_creation_latency = prometheus_client.Histogram(
            'kuryr_pod_creation_latency', 'Time taken for a pod to have'
            ' Kuryr annotations set', buckets=buckets, registry=self.registry)
