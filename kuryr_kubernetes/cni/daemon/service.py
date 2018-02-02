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

import multiprocessing
import os
from six.moves import http_client as httplib
import socket
import sys

import cotyledon
import flask
from pyroute2.ipdb import transactional
import retrying

import os_vif
from os_vif import objects as obj_vif
from os_vif.objects import base
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes.cni import api
from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes.cni import handlers as h_cni
from kuryr_kubernetes.cni import utils
from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import objects
from kuryr_kubernetes import watcher as k_watcher

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
RETRY_DELAY = 1000  # 1 second in milliseconds

# TODO(dulek): Another corner case is (and was) when pod is deleted before it's
#              annotated by controller or even noticed by any watcher. Kubelet
#              will try to delete such vif, but we will have no data about it.
#              This is currently worked around by returning succesfully in case
#              of timing out in delete. To solve this properly we need to watch
#              for pod deletes as well.


class K8sCNIRegistryPlugin(api.CNIPlugin):
    def __init__(self, registry):
        self.registry = registry

    def _get_name(self, pod):
        return pod['metadata']['name']

    def add(self, params):
        vif = self._do_work(params, b_base.connect)

        pod_name = params.args.K8S_POD_NAME
        # NOTE(dulek): Saving containerid to be able to distinguish old DEL
        #              requests that we should ignore. We need a lock to
        #              prevent race conditions and replace whole object in the
        #              dict for multiprocessing.Manager to notice that.
        with lockutils.lock(pod_name, external=True):
            d = self.registry[pod_name]
            d['containerid'] = params.CNI_CONTAINERID
            self.registry[pod_name] = d
            LOG.debug('Saved containerid = %s for pod %s',
                      params.CNI_CONTAINERID, pod_name)

        # Wait for VIF to become active.
        timeout = CONF.cni_daemon.vif_annotation_timeout

        # Wait for timeout sec, 1 sec between tries, retry when vif not active.
        @retrying.retry(stop_max_delay=timeout * 1000, wait_fixed=RETRY_DELAY,
                        retry_on_result=lambda x: not x.active)
        def wait_for_active(pod_name):
            return base.VersionedObject.obj_from_primitive(
                self.registry[pod_name]['vif'])

        vif = wait_for_active(pod_name)
        if not vif.active:
            raise exceptions.ResourceNotReady(pod_name)

        return vif

    def delete(self, params):
        pod_name = params.args.K8S_POD_NAME
        try:
            reg_ci = self.registry[pod_name]['containerid']
            LOG.debug('Read containerid = %s for pod %s', reg_ci, pod_name)
            if reg_ci and reg_ci != params.CNI_CONTAINERID:
                # NOTE(dulek): This is a DEL request for some older (probably
                #              failed) ADD call. We should ignore it or we'll
                #              unplug a running pod.
                LOG.warning('Received DEL request for unknown ADD call. '
                            'Ignoring.')
                return
        except KeyError:
            pass
        self._do_work(params, b_base.disconnect)

    def _do_work(self, params, fn):
        pod_name = params.args.K8S_POD_NAME

        timeout = CONF.cni_daemon.vif_annotation_timeout

        # In case of KeyError retry for `timeout` s, wait 1 s between tries.
        @retrying.retry(stop_max_delay=timeout * 1000, wait_fixed=RETRY_DELAY,
                        retry_on_exception=lambda e: isinstance(e, KeyError))
        def find():
            return self.registry[pod_name]

        try:
            d = find()
            pod = d['pod']
            vif = base.VersionedObject.obj_from_primitive(d['vif'])
        except KeyError:
            raise exceptions.ResourceNotReady(pod_name)

        fn(vif, self._get_inst(pod), params.CNI_IFNAME, params.CNI_NETNS)
        return vif

    def _get_inst(self, pod):
        return obj_vif.instance_info.InstanceInfo(
            uuid=pod['metadata']['uid'], name=pod['metadata']['name'])


class DaemonServer(object):
    def __init__(self, plugin):
        self.ctx = None
        self.plugin = plugin

        self.application = flask.Flask('kuryr-daemon')
        self.application.add_url_rule(
            '/addNetwork', methods=['POST'], view_func=self.add)
        self.application.add_url_rule(
            '/delNetwork', methods=['POST'], view_func=self.delete)
        self.headers = {'ContentType': 'application/json',
                        'Connection': 'close'}

    def _prepare_request(self):
        params = utils.CNIParameters(flask.request.get_json())
        LOG.debug('Received %s request. CNI Params: %s',
                  params.CNI_COMMAND, params)
        return params

    def add(self):
        try:
            params = self._prepare_request()
        except Exception:
            LOG.exception('Exception when reading CNI params.')
            return '', httplib.BAD_REQUEST, self.headers

        try:
            vif = self.plugin.add(params)
            data = jsonutils.dumps(vif.obj_to_primitive())
        except exceptions.ResourceNotReady as e:
            LOG.error("Timed out waiting for requested pod to appear in "
                      "registry: %s.", e)
            return '', httplib.GATEWAY_TIMEOUT, self.headers
        except Exception:
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
        except exceptions.ResourceNotReady as e:
            # NOTE(dulek): It's better to ignore this error - most of the time
            #              it will happen when pod is long gone and kubelet
            #              overzealously tries to delete it from the network.
            #              We cannot really do anything without VIF annotation,
            #              so let's just tell kubelet to move along.
            LOG.warning("Timed out waiting for requested pod to appear in "
                        "registry: %s. Ignoring.", e)
            return '', httplib.NO_CONTENT, self.headers
        except Exception:
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
            self.application.run(address, port,
                                 processes=CONF.cni_daemon.worker_num)
        except Exception:
            LOG.exception('Failed to start kuryr-daemon.')
            raise


class CNIDaemonServerService(cotyledon.Service):
    name = "server"

    def __init__(self, worker_id, registry):
        super(CNIDaemonServerService, self).__init__(worker_id)
        self.run_queue_reading = False
        self.registry = registry
        self.plugin = K8sCNIRegistryPlugin(registry)
        self.server = DaemonServer(self.plugin)

    def run(self):
        # NOTE(dulek): We might do a *lot* of pyroute2 operations, let's
        #              make the pyroute2 timeout configurable to make sure
        #              kernel will have chance to catch up.
        transactional.SYNC_TIMEOUT = CONF.cni_daemon.pyroute2_timeout

        # Run HTTP server
        self.server.run()


class CNIDaemonWatcherService(cotyledon.Service):
    name = "watcher"

    def __init__(self, worker_id, registry):
        super(CNIDaemonWatcherService, self).__init__(worker_id)
        self.pipeline = None
        self.watcher = None
        self.registry = registry

    def _get_nodename(self):
        # NOTE(dulek): At first try to get it using environment variable,
        #              otherwise assume hostname is the nodename.
        try:
            nodename = os.environ['KUBERNETES_NODE_NAME']
        except KeyError:
            nodename = socket.gethostname()
        return nodename

    def run(self):
        self.pipeline = h_cni.CNIPipeline()
        self.pipeline.register(h_cni.CallbackHandler(self.on_done))
        self.watcher = k_watcher.Watcher(self.pipeline)
        self.watcher.add(
            "%(base)s/pods?fieldSelector=spec.nodeName=%(node_name)s" % {
                'base': k_const.K8S_API_BASE,
                'node_name': self._get_nodename()})
        self.watcher.start()

    def on_done(self, pod, vif):
        pod_name = pod['metadata']['name']
        vif_dict = vif.obj_to_primitive()
        # NOTE(dulek): We need a lock when modifying shared self.registry dict
        #              to prevent race conditions with other processes/threads.
        with lockutils.lock(pod_name, external=True):
            if pod_name not in self.registry:
                self.registry[pod_name] = {'pod': pod, 'vif': vif_dict,
                                           'containerid': None}
            else:
                # NOTE(dulek): Only update vif if its status changed, we don't
                #              need to care about other changes now.
                old_vif = base.VersionedObject.obj_from_primitive(
                    self.registry[pod_name]['vif'])
                if old_vif.active != vif.active:
                    pod_dict = self.registry[pod_name]
                    pod_dict['vif'] = vif_dict
                    self.registry[pod_name] = pod_dict

    def terminate(self):
        if self.watcher:
            self.watcher.stop()


class CNIDaemonServiceManager(cotyledon.ServiceManager):
    def __init__(self):
        super(CNIDaemonServiceManager, self).__init__()
        # TODO(dulek): Use cotyledon.oslo_config_glue to support conf reload.

        # TODO(vikasc): Should be done using dynamically loadable OVO types
        #               plugin.
        objects.register_locally_defined_vifs()

        os_vif.initialize()
        clients.setup_kubernetes_client()

        self.manager = multiprocessing.Manager()
        registry = self.manager.dict()  # For Watcher->Server communication.
        self.add(CNIDaemonWatcherService, workers=1, args=(registry,))
        self.add(CNIDaemonServerService, workers=1, args=(registry,))
        self.register_hooks(on_terminate=self.terminate)

    def run(self):
        super(CNIDaemonServiceManager, self).run()

    def terminate(self):
        self.manager.shutdown()


def start():
    config.init(sys.argv[1:])
    config.setup_logging()

    CNIDaemonServiceManager().run()
