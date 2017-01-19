# Copyright (c) 2016 Mirantis, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import signal
import sys

import os_vif
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes.cni import api as cni_api
from kuryr_kubernetes.cni import handlers as h_cni
from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import objects
from kuryr_kubernetes import watcher as k_watcher

LOG = logging.getLogger(__name__)
_CNI_TIMEOUT = 180


class K8sCNIPlugin(cni_api.CNIPlugin):

    def add(self, params):
        self._setup(params)
        self._pipeline.register(h_cni.AddHandler(params, self._done))
        self._watcher.start()
        return self._vif

    def delete(self, params):
        self._setup(params)
        self._pipeline.register(h_cni.DelHandler(params, self._done))
        self._watcher.start()

    def _done(self, vif):
        self._vif = vif
        self._watcher.stop()

    def _setup(self, params):
        args = ['--config-file', params.config.kuryr_conf]

        try:
            if params.config.debug:
                args.append('-d')
        except AttributeError:
            pass

        config.init(args)
        config.setup_logging()
        os_vif.initialize()
        clients.setup_kubernetes_client()
        self._pipeline = h_cni.CNIPipeline()
        self._watcher = k_watcher.Watcher(self._pipeline)
        self._watcher.add(
            "%(base)s/namespaces/%(namespace)s/pods"
            "?fieldSelector=metadata.name=%(pod)s" % {
                'base': k_const.K8S_API_BASE,
                'namespace': params.args.K8S_POD_NAMESPACE,
                'pod': params.args.K8S_POD_NAME})


def run():
    # REVISIT(ivc): current CNI implementation provided by this package is
    # experimental and its primary purpose is to enable development of other
    # components (e.g. functional tests, service/LBaaSv2 support)

    # TODO(vikasc): Should be done using dynamically loadable OVO types plugin.
    objects.register_locally_defined_vifs()

    runner = cni_api.CNIRunner(K8sCNIPlugin())

    def _timeout(signum, frame):
        runner._write_dict(sys.stdout, {
            'msg': 'timeout',
            'code': k_const.CNI_TIMEOUT_CODE,
        })
        LOG.debug('timed out')
        sys.exit(1)

    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(_CNI_TIMEOUT)
    status = runner.run(os.environ, sys.stdin, sys.stdout)
    LOG.debug("Exiting with status %s", status)
    if status:
        sys.exit(status)
