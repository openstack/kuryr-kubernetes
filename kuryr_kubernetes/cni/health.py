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
from pyroute2 import IPDB

from kuryr.lib._i18n import _
from kuryr_kubernetes import clients
from kuryr_kubernetes.cni import utils
from kuryr_kubernetes import exceptions as exc
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
    cfg.StrOpt(
        'cg_path',
        help=_('sysfs path to the CNI cgroup. This is used for resource '
               'tracking and as such should point to the cgroup hierarchy '
               'leaf. It only applies when non containerized'),
        default='/sys/fs/cgroup/memory/system.slice/kuryr-cni.service')
]

CONF.register_opts(cni_health_server_opts, "cni_health_server")

TOP_CGROUP_MEMORY_PATH = '/sys/fs/cgroup/memory'
MEMSW_FILENAME = 'memory.memsw.usage_in_bytes'
BYTES_AMOUNT = 1048576
CAP_NET_ADMIN = 12  # Taken from linux/capabilities.h
EFFECTIVE_CAPS = 'CapEff:\t'


def _has_cap(capability, entry, proc_status_path='/proc/self/status'):
    """Returns true iff the process has the specified capability.

    :param capability: the bit number for the capability to check as seen
                       in linux/capabilities.h.
    :param entry: Whether to check CapInh, CapEff or CapBnd.
    :param proc_status_path: Which process status should be checked. If none
                             is passed, it will check the current process.
    :return: Whether the specified process has the capability bit set
    """
    with open(proc_status_path, 'r') as pstat:
        for line in pstat:
            if line.startswith(entry):
                caps = int(line[len(entry):], 16)
    return (caps & (1 << capability)) != 0


def _get_cni_cgroup_path():
    """Returns the path to the CNI process cgroup memory directory."""
    if utils.running_under_container_runtime():
        # We are running inside a container. This means the root cgroup
        # is the one we need to track as it will be the CNI parent proc
        cg_memsw_path = TOP_CGROUP_MEMORY_PATH
    else:
        cg_memsw_path = CONF.cni_health_server.cg_path

    return cg_memsw_path


def _get_memsw_usage(cgroup_mem_path):
    """Returns the group's resident memory plus swap usage."""
    with open(os.path.join(cgroup_mem_path, MEMSW_FILENAME)) as memsw:
        memsw_in_bytes = int(memsw.read())
    return memsw_in_bytes / BYTES_AMOUNT


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
        data = 'ok'
        k8s_conn = self.verify_k8s_connection()

        if not _has_cap(CAP_NET_ADMIN, EFFECTIVE_CAPS):
            error_message = 'NET_ADMIN capabilities not present.'
            LOG.error(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers
        if not k8s_conn:
            error_message = 'Error when processing k8s healthz request.'
            LOG.error(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        LOG.info('CNI driver readiness verified.')
        return data, httplib.OK, self.headers

    def liveness_status(self):
        data = 'ok'
        no_limit = -1
        try:
            with IPDB():
                pass
        except Exception:
            error_message = 'IPDB not in working order.'
            LOG.error(error_message)
            return error_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        if CONF.cni_health_server.max_memory_usage != no_limit:
            mem_usage = _get_memsw_usage(_get_cni_cgroup_path())

            if mem_usage > CONF.cni_health_server.max_memory_usage:
                err_message = 'CNI daemon exceeded maximum memory usage.'
                LOG.error(err_message)
                return err_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        with self._components_healthy.get_lock():
            if not self._components_healthy.value:
                err_message = 'Kuryr CNI components not healthy.'
                LOG.error(err_message)
                return err_message, httplib.INTERNAL_SERVER_ERROR, self.headers

        LOG.debug('Kuryr CNI Liveness verified.')
        return data, httplib.OK, self.headers

    def run(self):
        address = '0.0.0.0'
        try:
            LOG.info('Starting CNI health check server.')
            self.application.run(address, CONF.cni_health_server.port)
        except Exception:
            LOG.exception('Failed to start CNI health check server.')
            raise

    def verify_k8s_connection(self):
        k8s = clients.get_kubernetes_client()
        try:
            k8s.get('/healthz', json=False, headers={'Connection': 'close'})
        except exc.K8sClientException:
            LOG.exception('Exception when trying to reach Kubernetes API.')
            return False
        return True
