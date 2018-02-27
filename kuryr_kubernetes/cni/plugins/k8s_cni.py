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

from kuryr_kubernetes import clients
from kuryr_kubernetes.cni import handlers as h_cni
from kuryr_kubernetes.cni.plugins import base as base_cni
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import watcher as k_watcher


class K8sCNIPlugin(base_cni.CNIPlugin):

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
        clients.setup_kubernetes_client()
        self._pipeline = h_cni.CNIPipeline()
        self._watcher = k_watcher.Watcher(self._pipeline)
        self._watcher.add(
            "%(base)s/namespaces/%(namespace)s/pods"
            "?fieldSelector=metadata.name=%(pod)s" % {
                'base': k_const.K8S_API_BASE,
                'namespace': params.args.K8S_POD_NAMESPACE,
                'pod': params.args.K8S_POD_NAME})
