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
import prometheus_client
from prometheus_client.exposition import generate_latest

from oslo_config import cfg
from oslo_log import log as logging


LOG = logging.getLogger(__name__)
CONF = cfg.CONF
_INF = float("inf")


class CNIPrometheusExporter(object):
    """Provides metrics to Prometheus"""

    def __init__(self):
        self.application = flask.Flask('prometheus-exporter')
        self.ctx = None
        self.application.add_url_rule(
            '/metrics', methods=['GET'], view_func=self.metrics)
        self.headers = {'Connection': 'close'}
        self._create_metric()

    def update_metric(self, labels, duration):
        """Observes the request duration value and count it in buckets"""
        self.cni_requests_duration.labels(**labels).observe(duration)

    def metrics(self):
        """Provides the registered metrics"""
        collected_metric = generate_latest(self.registry)
        return flask.Response(collected_metric, mimetype='text/plain')

    def run(self):
        # Disable obtrusive werkzeug logs.
        logging.getLogger('werkzeug').setLevel(logging.WARNING)

        address = '::'
        try:
            LOG.info('Starting CNI Prometheus exporter')
            self.application.run(
                address, CONF.prometheus_exporter.cni_exporter_port)
        except Exception:
            LOG.exception('Failed to start Prometheus exporter')
            raise

    def _create_metric(self):
        """Creates a registry and records a new Histogram metric."""
        self.registry = prometheus_client.CollectorRegistry()
        metric_name = 'kuryr_cni_request_duration_seconds'
        metric_description = 'The duration of CNI requests'
        buckets = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120,
                   130, 140, 150, 160, 170, 180, _INF)
        self.cni_requests_duration = prometheus_client.Histogram(
            metric_name, metric_description,
            labelnames={'command', 'error'}, buckets=buckets,
            registry=self.registry)
