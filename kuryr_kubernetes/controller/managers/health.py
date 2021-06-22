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

from http import client as httplib
import os

from oslo_config import cfg
from oslo_log import log as logging

from kuryr.lib._i18n import _
from kuryr.lib import config as kuryr_config
from kuryr.lib import utils
from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes.handlers import health as h_health
from kuryr_kubernetes import health as base_server

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

health_server_opts = [
    cfg.IntOpt('port',
               help=_('port for Health HTTP Server.'),
               default=8082),
]

CONF.register_opts(health_server_opts, "health_server")


class HealthServer(base_server.BaseHealthServer):
    """Proxy server used by readiness and liveness probes to manage health checks.

    Allows to verify connectivity with Kubernetes API, Keystone and Neutron.
    If pool ports functionality is enabled it is verified whether
    the precreated ports are loaded into the pools. Also, checks handlers
    states.
    """

    def __init__(self):
        super().__init__('controller-health', CONF.health_server.port)
        self._registry = h_health.HealthRegister.get_instance().registry

    def _components_ready(self):
        os_net = clients.get_network_client()
        project_id = config.CONF.neutron_defaults.project
        quota = os_net.get_quota(quota=project_id, details=True)

        for component in self._registry:
            if not component.is_ready(quota):
                LOG.debug('Controller component not ready: %s.' % component)
                return False
        return True

    def readiness_status(self):
        if CONF.kubernetes.vif_pool_driver != 'noop':
            if not os.path.exists('/tmp/pools_loaded'):
                error_message = 'Ports not loaded into the pools.'
                LOG.error(error_message)
                return error_message, httplib.NOT_FOUND, {}

        k8s_conn = self.verify_k8s_connection()
        if not k8s_conn:
            error_message = 'Error when processing k8s healthz request.'
            LOG.error(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, {}
        try:
            self.verify_keystone_connection()
        except Exception as ex:
            error_message = ('Error when creating a Keystone session and '
                             'getting a token: %s.' % ex)
            LOG.exception(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, {}

        try:
            if not self._components_ready():
                return '', httplib.INTERNAL_SERVER_ERROR, {}
        except Exception as ex:
            error_message = ('Error when processing neutron request %s' % ex)
            LOG.exception(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, {}

        return 'ok', httplib.OK, {}

    def liveness_status(self):
        for component in self._registry:
            if not component.is_alive():
                exc = component.get_last_exception()
                if not exc:
                    msg = f'Component {component.__class__.__name__} is dead.'
                    LOG.error(msg)
                else:
                    msg = (f'Component {component.__class__.__name__} is dead.'
                           f' Last caught exception below')
                    LOG.exception(msg, exc_info=exc)
                return msg, httplib.INTERNAL_SERVER_ERROR, {}
        return 'ok', httplib.OK, {}

    def verify_keystone_connection(self):
        # Obtain a new token to ensure connectivity with keystone
        conf_group = kuryr_config.neutron_group.name
        auth_plugin = utils.get_auth_plugin(conf_group)
        sess = utils.get_keystone_session(conf_group, auth_plugin)
        sess.get_token()
