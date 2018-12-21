# Copyright 2018 Maysa de Macedo Souza.
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

import os
from six.moves import http_client as httplib

from flask import Flask
from oslo_config import cfg
from oslo_log import log as logging

from kuryr.lib._i18n import _
from kuryr.lib import config as kuryr_config
from kuryr.lib import utils
from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import exceptions as exc
from kuryr_kubernetes.handlers import health as h_health

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

health_server_opts = [
    cfg.IntOpt('port',
               help=_('port for Health HTTP Server.'),
               default=8082),
]

CONF.register_opts(health_server_opts, "health_server")


class HealthServer(object):
    """Proxy server used by readiness and liveness probes to manage health checks.

    Allows to verify connectivity with Kubernetes API, Keystone and Neutron.
    If pool ports functionality is enabled it is verified whether
    the precreated ports are loaded into the pools. Also, checks handlers
    states.
    """

    def __init__(self):
        self.ctx = None
        self._registry = h_health.HealthRegister.get_instance().registry
        self.application = Flask('health-daemon')
        self.application.add_url_rule(
            '/ready', methods=['GET'], view_func=self.readiness_status)
        self.application.add_url_rule(
            '/alive', methods=['GET'], view_func=self.liveness_status)
        self.headers = {'Connection': 'close'}

    def _components_ready(self):
        neutron = clients.get_neutron_client()
        project_id = config.CONF.neutron_defaults.project
        quota = neutron.show_quota(project_id).get('quota')

        for component in self._registry:
            if not component.is_ready(quota):
                LOG.debug('Controller component not ready: %s.' % component)
                return False
        return True

    def readiness_status(self):
        data = 'ok'

        if CONF.kubernetes.vif_pool_driver != 'noop':
            if not os.path.exists('/tmp/pools_loaded'):
                error_message = 'Ports not loaded into the pools.'
                LOG.error(error_message)
                return error_message, httplib.NOT_FOUND, self.headers

        k8s_conn = self.verify_k8s_connection()
        if not k8s_conn:
            error_message = 'Error when processing k8s healthz request.'
            LOG.error(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers
        try:
            self.verify_keystone_connection()
        except Exception as ex:
            error_message = ('Error when creating a Keystone session and '
                             'getting a token: %s.' % ex)
            LOG.exception(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        try:
            if not self._components_ready():
                return '', httplib.INTERNAL_SERVER_ERROR, self.headers
        except Exception as ex:
            error_message = ('Error when processing neutron request %s' % ex)
            LOG.exception(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        LOG.info('Kuryr Controller readiness verified.')
        return data, httplib.OK, self.headers

    def liveness_status(self):
        data = 'ok'
        for component in self._registry:
            if not component.is_alive():
                LOG.debug('Kuryr Controller not healthy.')
                return '', httplib.INTERNAL_SERVER_ERROR, self.headers
        LOG.debug('Kuryr Controller Liveness verified.')
        return data, httplib.OK, self.headers

    def run(self):
        address = '0.0.0.0'
        try:
            LOG.info('Starting health check server.')
            self.application.run(address, CONF.health_server.port)
        except Exception:
            LOG.exception('Failed to start health check server.')
            raise

    def verify_k8s_connection(self):
        k8s = clients.get_kubernetes_client()
        try:
            k8s.get('/healthz', json=False, headers={'Connection': 'close'})
        except exc.K8sClientException:
            LOG.exception('Exception when trying to reach Kubernetes API.')
            return False
        return True

    def verify_keystone_connection(self):
        # Obtain a new token to ensure connectivity with keystone
        conf_group = kuryr_config.neutron_group.name
        auth_plugin = utils.get_auth_plugin(conf_group)
        sess = utils.get_keystone_session(conf_group, auth_plugin)
        sess.get_token()
