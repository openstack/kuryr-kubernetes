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

import gc
import os
import psutil
import requests
from six.moves import http_client as httplib
import subprocess

from flask import Flask
from pyroute2 import IPDB

from kuryr.lib._i18n import _
from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

cni_health_server_opts = [
    cfg.IntOpt('port',
               help=_('Port for CNI Health HTTP Server.'),
               default=8090),
    cfg.IntOpt('max_memory_usage',
               help=_('Maximum memory usage (MiB) for CNI Health Server '
                      'process. If this value is exceeded kuryr-daemon '
                      'will be marked as unhealthy.'),
               default=-1),
]

CONF.register_opts(cni_health_server_opts, "cni_health_server")

BYTES_AMOUNT = 1048576


class CNIHealthServer(object):
    """Server used by readiness and liveness probe to manage CNI health checks.

    Verifies presence of NET_ADMIN capabilities, IPDB in working order,
    connectivity to Kubernetes API, quantity of CNI add failure, health of
    CNI components and existence of memory leaks.
    """

    def __init__(self, components_healthy):

        self.ctx = None
        self._components_healthy = components_healthy
        self.application = Flask('cni-health-daemon')
        self.application.add_url_rule(
            '/ready', methods=['GET'], view_func=self.readiness_status)
        self.application.add_url_rule(
            '/alive', methods=['GET'], view_func=self.liveness_status)
        self.headers = {'Connection': 'close'}

    def readiness_status(self):
        net_admin_command = 'capsh --print | grep "Current:" | ' \
                            'cut -d" " -f3 | grep -q cap_net_admin'
        return_code = subprocess.call(net_admin_command, shell=True)
        data = 'ok'
        k8s_conn, k8s_status = self.verify_k8s_connection()

        if return_code != 0:
            error_message = 'NET_ADMIN capabilities not present.'
            LOG.error(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers
        if not k8s_conn:
            error_message = 'Error when processing k8s healthz request.'
            LOG.error(error_message)
            return error_message, k8s_status, self.headers

        LOG.info('CNI driver readiness verified.')
        return data, httplib.OK, self.headers

    def liveness_status(self):
        data = 'ok'
        no_limit = -1
        try:
            with IPDB() as a:
                a.release()
        except Exception:
            error_message = 'IPDB not in working order.'
            LOG.debug(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        if CONF.cni_health_server.max_memory_usage != no_limit:
            # Force gc to release unreferenced memory before actually checking
            # the memory.
            gc.collect()
            process = psutil.Process(os.getpid())
            mem_usage = process.memory_info().rss / BYTES_AMOUNT
            if mem_usage > CONF.cni_health_server.max_memory_usage:
                err_message = 'CNI daemon exceeded maximum memory usage.'
                LOG.debug(err_message)
                return err_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        with self._components_healthy.get_lock():
            if not self._components_healthy.value:
                err_message = 'Kuryr CNI components not healthy.'
                LOG.debug(err_message)
                return err_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        LOG.debug('Kuryr CNI Liveness verified.')
        return data, httplib.OK, self.headers

    def run(self):
        address = ''
        try:
            LOG.info('Starting CNI health check server.')
            self.application.run(address, CONF.cni_health_server.port)
        except Exception:
            LOG.exception('Failed to start CNI health check server.')
            raise

    def verify_k8s_connection(self):
        path = '/healthz'
        address = CONF.kubernetes.api_root
        url = address + path
        resp = requests.get(url, headers={'Connection': 'close'})
        return resp.content == 'ok', resp.status_code
