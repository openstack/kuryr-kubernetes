# Copyright 2017 Red Hat, Inc.
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

from ctypes import c_bool
import multiprocessing
import os
from six.moves import http_client as httplib
import socket
import sys
import threading
import time

import cotyledon
import flask
from pyroute2.ipdb import transactional

import os_vif
from os_vif.objects import base
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes.cni import handlers as h_cni
from kuryr_kubernetes.cni import health
from kuryr_kubernetes.cni.plugins import k8s_cni_registry
from kuryr_kubernetes.cni import utils as cni_utils
from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import objects
from kuryr_kubernetes import utils
from kuryr_kubernetes import watcher as k_watcher

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
HEALTH_CHECKER_DELAY = 5


class DaemonServer(object):
    def __init__(self, plugin, healthy):
        self.ctx = None
        self.plugin = plugin
        self.healthy = healthy
        self.failure_count = multiprocessing.Value('i', 0)
        self.application = flask.Flask('kuryr-daemon')
        self.application.add_url_rule(
            '/addNetwork', methods=['POST'], view_func=self.add)
        self.application.add_url_rule(
            '/delNetwork', methods=['POST'], view_func=self.delete)
        self.headers = {'ContentType': 'application/json',
                        'Connection': 'close'}

    def _prepare_request(self):
        params = cni_utils.CNIParameters(flask.request.get_json())
        LOG.debug('Received %s request. CNI Params: %s',
                  params.CNI_COMMAND, params)
        return params

    def add(self):
        try:
            params = self._prepare_request()
        except Exception:
            self._check_failure()
            LOG.exception('Exception when reading CNI params.')
            return '', httplib.BAD_REQUEST, self.headers

        try:
            vif = self.plugin.add(params)
            data = jsonutils.dumps(vif.obj_to_primitive())
        except exceptions.ResourceNotReady:
            self._check_failure()
            LOG.error('Error when processing addNetwork request')
            return '', httplib.GATEWAY_TIMEOUT, self.headers
        except Exception:
            self._check_failure()
            LOG.exception('Error when processing addNetwork request. CNI '
                          'Params: %s', params)
            return '', httplib.INTERNAL_SERVER_ERROR, self.headers

        return data, httplib.ACCEPTED, self.headers

    def delete(self):
        try:
            params = self._prepare_request()
        except Exception:
            LOG.exception('Exception when reading CNI params.')
            return '', httplib.BAD_REQUEST, self.headers

        try:
            self.plugin.delete(params)
        except exceptions.ResourceNotReady:
            # NOTE(dulek): It's better to ignore this error - most of the time
            #              it will happen when pod is long gone and kubelet
            #              overzealously tries to delete it from the network.
            #              We cannot really do anything without VIF annotation,
            #              so let's just tell kubelet to move along.
            LOG.warning('Error when processing delNetwork request. '
                        'Ignoring this error, pod is most likely gone')
            return '', httplib.NO_CONTENT, self.headers
        except Exception:
            self._check_failure()
            LOG.exception('Error when processing delNetwork request. CNI '
                          'Params: %s.', params)
            return '', httplib.INTERNAL_SERVER_ERROR, self.headers
        return '', httplib.NO_CONTENT, self.headers

    def run(self):
        server_pair = CONF.cni_daemon.bind_address
        LOG.info('Starting server on %s.', server_pair)
        try:
            address, port = server_pair.split(':')
            port = int(port)
        except ValueError:
            LOG.exception('Cannot start server on %s.', server_pair)
            raise

        try:
            self.application.run(address, port, threaded=False,
                                 processes=CONF.cni_daemon.worker_num)
        except Exception:
            LOG.exception('Failed to start kuryr-daemon.')
            raise

    def _check_failure(self):
        with self.failure_count.get_lock():
            if self.failure_count.value < CONF.cni_daemon.cni_failures_count:
                self.failure_count.value += 1
            else:
                with self.healthy.get_lock():
                    LOG.debug("Reporting maximum CNI ADD/DEL failures "
                              "reached.")
                    self.healthy.value = False


class CNIDaemonServerService(cotyledon.Service):
    name = "server"

    def __init__(self, worker_id, registry, healthy):
        super(CNIDaemonServerService, self).__init__(worker_id)
        self.run_queue_reading = False
        self.registry = registry
        self.healthy = healthy
        self.plugin = k8s_cni_registry.K8sCNIRegistryPlugin(registry,
                                                            self.healthy)
        self.server = DaemonServer(self.plugin, self.healthy)

    def run(self):
        # NOTE(dulek): We might do a *lot* of pyroute2 operations, let's
        #              make the pyroute2 timeout configurable to make sure
        #              kernel will have chance to catch up.
        transactional.SYNC_TIMEOUT = CONF.cni_daemon.pyroute2_timeout

        # Run HTTP server
        self.server.run()


class CNIDaemonWatcherService(cotyledon.Service):
    name = "watcher"

    def __init__(self, worker_id, registry, healthy):
        super(CNIDaemonWatcherService, self).__init__(worker_id)
        self.pipeline = None
        self.watcher = None
        self.health_thread = None
        self.registry = registry
        self.healthy = healthy

    def _get_nodename(self):
        # NOTE(dulek): At first try to get it using environment variable,
        #              otherwise assume hostname is the nodename.
        try:
            nodename = os.environ['KUBERNETES_NODE_NAME']
        except KeyError:
            # NOTE(dulek): By default K8s nodeName is lowercased hostname.
            nodename = socket.gethostname().lower()
        return nodename

    def run(self):
        self.pipeline = h_cni.CNIPipeline()
        self.pipeline.register(h_cni.CallbackHandler(self.on_done,
                                                     self.on_deleted))
        self.watcher = k_watcher.Watcher(self.pipeline)
        self.watcher.add(
            "%(base)s/pods?fieldSelector=spec.nodeName=%(node_name)s" % {
                'base': k_const.K8S_API_BASE,
                'node_name': self._get_nodename()})
        self.is_running = True
        self.health_thread = threading.Thread(
            target=self._start_watcher_health_checker)
        self.health_thread.start()
        self.watcher.start()

    def _start_watcher_health_checker(self):
        while self.is_running:
            if not self.watcher.is_alive():
                LOG.debug("Reporting watcher not healthy.")
                with self.healthy.get_lock():
                    self.healthy.value = False
            time.sleep(HEALTH_CHECKER_DELAY)

    def on_done(self, pod, vifs):
        pod_name = utils.get_pod_unique_name(pod)
        vif_dict = {
            ifname: vif.obj_to_primitive() for
            ifname, vif in vifs.items()
        }
        # NOTE(dulek): We need a lock when modifying shared self.registry dict
        #              to prevent race conditions with other processes/threads.
        with lockutils.lock(pod_name, external=True):
            if pod_name not in self.registry:
                self.registry[pod_name] = {'pod': pod, 'vifs': vif_dict,
                                           'containerid': None}
            else:
                # NOTE(dulek): Only update vif if its status changed, we don't
                #              need to care about other changes now.
                old_vifs = {
                    ifname:
                        base.VersionedObject.obj_from_primitive(vif_obj) for
                        ifname, vif_obj in (
                            self.registry[pod_name]['vifs'].items())
                }
                for iface in vifs:
                    if old_vifs[iface].active != vifs[iface].active:
                        pod_dict = self.registry[pod_name]
                        pod_dict['vifs'] = vif_dict
                        self.registry[pod_name] = pod_dict

    def on_deleted(self, pod):
        pod_name = utils.get_pod_unique_name(pod)
        try:
            if pod_name in self.registry:
                # NOTE(dulek): del on dict is atomic as long as we use standard
                #              types as keys. This is the case, so we don't
                #              need to lock here.
                del self.registry[pod_name]
        except KeyError:
            # This means someone else removed it. It's odd but safe to ignore.
            pass

    def terminate(self):
        self.is_running = False
        if self.health_thread:
            self.health_thread.join()
        if self.watcher:
            self.watcher.stop()


class CNIDaemonHealthServerService(cotyledon.Service):
    name = "health"

    def __init__(self, worker_id, healthy):
        super(CNIDaemonHealthServerService, self).__init__(worker_id)
        self.health_server = health.CNIHealthServer(healthy)

    def run(self):
        self.health_server.run()


class CNIDaemonServiceManager(cotyledon.ServiceManager):
    def __init__(self):
        super(CNIDaemonServiceManager, self).__init__()
        # TODO(dulek): Use cotyledon.oslo_config_glue to support conf reload.

        # TODO(vikasc): Should be done using dynamically loadable OVO types
        #               plugin.
        objects.register_locally_defined_vifs()

        os_vif.initialize()
        clients.setup_kubernetes_client()
        if CONF.sriov.enable_pod_resource_service:
            clients.setup_pod_resources_client()

        self.manager = multiprocessing.Manager()
        registry = self.manager.dict()  # For Watcher->Server communication.
        healthy = multiprocessing.Value(c_bool, True)
        self.add(CNIDaemonWatcherService, workers=1, args=(registry, healthy,))
        self.add(CNIDaemonServerService, workers=1, args=(registry, healthy,))
        self.add(CNIDaemonHealthServerService, workers=1, args=(healthy,))
        self.register_hooks(on_terminate=self.terminate)

    def run(self):
        super(CNIDaemonServiceManager, self).run()

    def terminate(self):
        self.manager.shutdown()


def start():
    config.init(sys.argv[1:])
    config.setup_logging()

    CNIDaemonServiceManager().run()
