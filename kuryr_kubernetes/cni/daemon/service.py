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
import errno
from http import client as httplib
import multiprocessing
import os
import queue
import sys
import threading
import time
import urllib3

import cotyledon
import flask
import pyroute2
from pyroute2.ipdb import transactional
from werkzeug import serving

import os_vif
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes.cni.daemon import watcher_service
from kuryr_kubernetes.cni import health
from kuryr_kubernetes.cni.plugins import k8s_cni_registry
from kuryr_kubernetes.cni import prometheus_exporter
from kuryr_kubernetes.cni import utils as cni_utils
from kuryr_kubernetes import config
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import objects

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
ErrContainerUnknown = 3
ErrInvalidEnvironmentVariables = 4
ErrTryAgainLater = 11
ErrInternal = 999


class DaemonServer(object):
    def __init__(self, plugin, healthy, metrics):
        self.ctx = None
        self.plugin = plugin
        self.healthy = healthy
        self.metrics = metrics
        self.failure_count = multiprocessing.Value('i', 0)
        self.application = flask.Flask('kuryr-daemon')
        self.application.add_url_rule(
            '/addNetwork', methods=['POST'], view_func=self.add)
        self.application.add_url_rule(
            '/delNetwork', methods=['POST'], view_func=self.delete)
        self.headers = {'ContentType': 'application/json',
                        'Connection': 'close'}
        self._server = None

    def _prepare_request(self):
        params = cni_utils.CNIParameters(flask.request.get_json())
        LOG.debug('Received %s request. CNI Params: %s',
                  params.CNI_COMMAND, params)
        return params

    def _error(self, error_code, message, details=""):
        template = {
            "code": error_code,
            "msg": message,
            "details": details
        }
        data = jsonutils.dumps(template)
        return data

    def _update_metrics(self, command, error, duration):
        """Add a new metric value to the shared metrics dict"""
        labels = {'command': command, 'error': error}
        self.metrics.put({'labels': labels, 'duration': duration})

    @cni_utils.measure_time('ADD')
    def add(self):
        try:
            params = self._prepare_request()
        except Exception:
            self._check_failure()
            LOG.exception('Exception when reading CNI params.')
            error = self._error(ErrInvalidEnvironmentVariables,
                                "Required CNI params missing.")
            return error, httplib.BAD_REQUEST, self.headers

        try:
            vif = self.plugin.add(params)
            data = jsonutils.dumps(vif.obj_to_primitive())
        except (exceptions.CNIPodGone, exceptions.CNIPodUidMismatch) as e:
            LOG.warning('Pod deleted while processing ADD request')
            error = self._error(ErrContainerUnknown, str(e))
            return error, httplib.GONE, self.headers
        except exceptions.CNITimeout as e:
            LOG.exception('Timeout on ADD request')
            error = self._error(ErrTryAgainLater, f"{e}. Try Again Later.")
            return error, httplib.GATEWAY_TIMEOUT, self.headers
        except pyroute2.NetlinkError as e:
            if e.code == errno.EEXIST:
                self._check_failure()
                LOG.warning(
                    f'Creation of pod interface failed due to VLAN ID '
                    f'conflict. Probably the CRI had not cleaned up the '
                    f'network namespace of deleted pods. Attempting to retry.')
                error = self._error(ErrTryAgainLater,
                                    "Creation of pod interface failed due to "
                                    "VLAN ID conflict. Try Again Later")
                return error, httplib.GATEWAY_TIMEOUT, self.headers
            raise
        except Exception:
            if not self.healthy.value:
                error = self._error(ErrInternal,
                                    "Maximum CNI ADD Failures Reached.",
                                    "Error when processing addNetwork request."
                                    " CNI Params: {}".format(params))
            else:
                self._check_failure()
                error = self._error(ErrInternal,
                                    "Error processing request",
                                    "Failure processing addNetwork request. "
                                    "CNI Params: {}".format(params))
            LOG.exception('Error when processing addNetwork request. CNI '
                          'Params: %s', params)
            return error, httplib.INTERNAL_SERVER_ERROR, self.headers

        return data, httplib.ACCEPTED, self.headers

    @cni_utils.measure_time('DEL')
    def delete(self):
        try:
            params = self._prepare_request()
        except Exception:
            LOG.exception('Exception when reading CNI params.')
            error = self._error(ErrInvalidEnvironmentVariables,
                                "Required CNI params missing.")
            return error, httplib.BAD_REQUEST, self.headers

        try:
            self.plugin.delete(params)
        except (exceptions.CNIKuryrPortTimeout, exceptions.CNIPodUidMismatch):
            # NOTE(dulek): It's better to ignore these errors - most of the
            #              time it will happen when pod is long gone and CRI
            #              overzealously tries to delete it from the network.
            #              We cannot really do anything without VIF annotation,
            #              so let's just tell CRI to move along.
            LOG.warning('Error when processing delNetwork request. '
                        'Ignoring this error, pod is most likely gone')
            return '', httplib.NO_CONTENT, self.headers
        except Exception:
            if not self.healthy.value:
                error = self._error(ErrInternal,
                                    "Maximum CNI DEL Failures Reached.",
                                    "Error processing delNetwork request. "
                                    "CNI Params: {}".format(params))
            else:
                self._check_failure()
                error = self._error(ErrInternal,
                                    "Error processing request",
                                    "Failure processing delNetwork request. "
                                    "CNI Params: {}".format(params))
            LOG.exception('Error when processing delNetwork request. CNI '
                          'Params: %s.', params)
            return error, httplib.INTERNAL_SERVER_ERROR, self.headers
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

        if CONF.cni_daemon.worker_num <= 1:
            msg = ('[cni_daemon]worker_num needs to be set to a value higher '
                   'than 1')
            LOG.critical(msg)
            raise exceptions.InvalidKuryrConfiguration(msg)

        try:
            self._server = serving.make_server(
                address, port, self.application, threaded=False,
                processes=CONF.cni_daemon.worker_num)
            self._server.serve_forever()
        except Exception:
            LOG.exception('Failed to start kuryr-daemon.')
            raise

    def stop(self):
        LOG.info("Waiting for DaemonServer worker processes to exit...")
        self._server._block_on_close = True
        self._server.shutdown()
        self._server.server_close()
        LOG.info("All DaemonServer workers finished gracefully.")

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

    def __init__(self, worker_id, registry, healthy, metrics):
        super(CNIDaemonServerService, self).__init__(worker_id)
        self.registry = registry
        self.healthy = healthy
        self.plugin = k8s_cni_registry.K8sCNIRegistryPlugin(registry,
                                                            self.healthy)
        self.metrics = metrics
        self.server = DaemonServer(self.plugin, self.healthy, self.metrics)

    def run(self):
        # NOTE(dulek): We might do a *lot* of pyroute2 operations, let's
        #              make the pyroute2 timeout configurable to make sure
        #              kernel will have chance to catch up.
        transactional.SYNC_TIMEOUT = CONF.cni_daemon.pyroute2_timeout

        # Run HTTP server
        self.server.run()

    def terminate(self):
        self.server.stop()


class CNIDaemonHealthServerService(cotyledon.Service):
    name = "health"

    def __init__(self, worker_id, healthy):
        super(CNIDaemonHealthServerService, self).__init__(worker_id)
        self.health_server = health.CNIHealthServer(healthy)

    def run(self):
        self.health_server.run()


class CNIDaemonExporterService(cotyledon.Service):
    name = "Prometheus Exporter"

    def __init__(self, worker_id, metrics):
        super(CNIDaemonExporterService, self).__init__(worker_id)
        self.prometheus_exporter = prometheus_exporter.CNIPrometheusExporter()
        self.is_running = True
        self.metrics = metrics
        self.exporter_thread = threading.Thread(
            target=self._start_metric_updater)
        self.exporter_thread.start()

    def _start_metric_updater(self):
        while self.is_running:
            try:
                metric = self.metrics.get(timeout=1)
            except queue.Empty:
                continue
            labels = metric['labels']
            duration = metric['duration']
            self.prometheus_exporter.update_metric(labels, duration)

    def terminate(self):
        self.is_running = False
        if self.exporter_thread:
            self.exporter_thread.join()

    def run(self):
        self.prometheus_exporter.run()


class CNIDaemonServiceManager(cotyledon.ServiceManager):
    def __init__(self):
        # NOTE(mdulko): Default shutdown timeout is 60 seconds and K8s won't
        #               wait more by default anyway.
        super(CNIDaemonServiceManager, self).__init__()
        self._server_service = None
        # TODO(dulek): Use cotyledon.oslo_config_glue to support conf reload.

        # TODO(vikasc): Should be done using dynamically loadable OVO types
        #               plugin.
        objects.register_locally_defined_vifs()

        os_vif.initialize()
        clients.setup_kubernetes_client()

        self.manager = multiprocessing.Manager()
        registry = self.manager.dict()  # For Watcher->Server communication.
        healthy = multiprocessing.Value(c_bool, True)
        metrics = self.manager.Queue()
        self.add(watcher_service.KuryrPortWatcherService, workers=1,
                 args=(registry, healthy,))
        self.add(watcher_service.PodWatcherService, workers=1,
                 args=(registry, healthy,))
        self._server_service = self.add(CNIDaemonServerService, workers=1,
                                        args=(registry, healthy, metrics,))
        self.add(CNIDaemonHealthServerService, workers=1, args=(healthy,))
        self.add(CNIDaemonExporterService, workers=1, args=(metrics,))

        def shutdown_hook(service_id, worker_id, exit_code):
            LOG.critical(f'Child Service {service_id} had exited with code '
                         f'{exit_code}, stopping kuryr-daemon')
            self.shutdown()

        self.register_hooks(on_terminate=self.terminate,
                            on_dead_worker=shutdown_hook)

    def run(self):
        # FIXME(darshna): Remove pyroute2 IPDB deprecation warning, remove
        #                 once we stop using pyroute2.IPDB.
        logging.getLogger('pyroute2').setLevel(logging.ERROR)
        logging.getLogger('pr2modules.ipdb.main').setLevel(logging.ERROR)

        reaper_thread = threading.Thread(target=self._zombie_reaper,
                                         daemon=True)
        self._terminate_called = threading.Event()
        reaper_thread.start()
        super(CNIDaemonServiceManager, self).run()

    def _zombie_reaper(self):
        while True:
            try:
                res = os.waitpid(-1, os.WNOHANG)
                # don't sleep or stop if a zombie process was found
                # as there could be more
                if res != (0, 0):
                    continue
            except ChildProcessError:
                # There are no child processes yet (or they have been killed)
                pass
            except os.error:
                LOG.exception("Got OS error while reaping zombie processes")
            if self._terminate_called.isSet():
                break
            time.sleep(1)

    def terminate(self):
        self._terminate_called.set()
        if self._server_service:
            LOG.info("Gracefully stopping DaemonServer service..")
            self.reconfigure(self._server_service, 0)
            for worker in self._running_services[self._server_service]:
                worker.terminate()
            for worker in self._running_services[self._server_service]:
                worker.join()
        LOG.info("Stopping registry manager...")
        self.manager.shutdown()
        LOG.info("Continuing with shutdown")


def start():
    urllib3.disable_warnings()
    config.init(sys.argv[1:])
    config.setup_logging()

    CNIDaemonServiceManager().run()
