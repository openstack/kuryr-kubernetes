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

import abc

from flask import Flask
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class BaseHealthServer(abc.ABC):
    """Base class of server used to provide readiness and liveness probes."""

    def __init__(self, app_name, port):
        self.app_name = app_name
        self.port = port
        self.ctx = None
        self.application = Flask(app_name)
        self.application.add_url_rule(
            '/ready', methods=['GET'], view_func=self.readiness_status)
        self.application.add_url_rule(
            '/alive', methods=['GET'], view_func=self.liveness_status)

        def apply_conn_close(response):
            response.headers['Connection'] = 'close'
            return response

        self.application.after_request(apply_conn_close)

    @abc.abstractmethod
    def readiness_status(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def liveness_status(self):
        raise NotImplementedError()

    def run(self):
        # Disable obtrusive werkzeug logs.
        logging.getLogger('werkzeug').setLevel(logging.WARNING)

        address = '::'
        LOG.info('Starting %s health check server on %s:%d.', self.app_name,
                 address, self.port)
        try:
            self.application.run(address, self.port)
        except Exception:
            LOG.exception('Failed to start %s health check server.',
                          self.app_name)
            raise

    def verify_k8s_connection(self):
        k8s = clients.get_kubernetes_client()
        try:
            k8s.get('/healthz', json=False, headers={'Connection': 'close'})
        except Exception as e:
            # Not LOG.exception to make sure long message from K8s API is not
            # repeated.
            LOG.error('Exception when trying to reach Kubernetes API: %s.', e)
            return False

        return True
