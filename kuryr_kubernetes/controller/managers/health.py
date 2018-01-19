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

from flask import Flask
from keystoneauth1 import exceptions as k_exc
from keystoneclient import client as keystone_client
from kuryr.lib._i18n import _
from kuryr.lib import config as kuryr_config
from kuryr.lib import utils
from kuryr_kubernetes.handlers import health as h_health
import os
from oslo_config import cfg
from oslo_log import log as logging
import requests
from six.moves import http_client as httplib

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

    def readiness_status(self):
        data = 'ok'

        if CONF.kubernetes.vif_pool_driver != 'noop':
            if not os.path.exists('/tmp/pools_loaded'):
                error_message = 'Ports not loaded into the pools.'
                LOG.error(error_message)
                return error_message, httplib.NOT_FOUND, self.headers

        k8s_conn, status = self.verify_k8s_connection()
        if not k8s_conn:
            error_message = 'Error when processing k8s healthz request.'
            LOG.error(error_message)
            return error_message, status, self.headers
        try:
            self.verify_keystone_connection()
        except k_exc.http.HttpError as h_ex:
            error_message = 'Error when processing Keystone request %s.' % h_ex
            LOG.exception(error_message)
            return error_message, h_ex.http_status, self.headers
        except Exception as ex:
            error_message = 'Error when creating a Keystone client: %s.' % ex
            LOG.exception(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers
        try:
            self.verify_neutron_connection()
        except Exception as ex:
            error_message = 'Error when creating a Neutron client: %s.' % ex
            LOG.exception(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        LOG.info('Kuryr Controller readiness verified.')
        return data, httplib.OK, self.headers

    def liveness_status(self):
        data = 'ok'
        for component in self._registry:
            if not component.is_healthy():
                LOG.debug('Kuryr Controller not healthy.')
                return '', httplib.INTERNAL_SERVER_ERROR, self.headers
        LOG.debug('Kuryr Controller Liveness verified.')
        return data, httplib.OK, self.headers

    def run(self):
        address = ''
        try:
            LOG.info('Starting health check server.')
            self.application.run(address, CONF.health_server.port)
        except Exception:
            LOG.exception('Failed to start health check server.')
            raise

    def verify_k8s_connection(self):
        path = '/healthz'
        address = CONF.kubernetes.api_root
        url = address + path
        resp = requests.get(url, headers={'Connection': 'close'})
        return resp.content == 'ok', resp.status_code

    def verify_keystone_connection(self):
        conf_group = kuryr_config.neutron_group.name
        auth_plugin = utils.get_auth_plugin(conf_group)
        sess = utils.get_keystone_session(conf_group, auth_plugin)
        endpoint_type = getattr(getattr(cfg.CONF, conf_group), 'endpoint_type')
        ks = keystone_client.Client(session=sess, auth=auth_plugin,
                                    endpoint_type=endpoint_type)
        ks.projects.list()

    def verify_neutron_connection(self):
        neutron = utils.get_neutron_client()
        neutron.list_extensions()
