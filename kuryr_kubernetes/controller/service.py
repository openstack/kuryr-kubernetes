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

import sys

import os_vif
from oslo_log import log as logging
from oslo_service import service

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.handlers import lbaas as h_lbaas
from kuryr_kubernetes.controller.handlers import pipeline as h_pipeline
from kuryr_kubernetes.controller.handlers import vif as h_vif
from kuryr_kubernetes import objects
from kuryr_kubernetes import watcher

LOG = logging.getLogger(__name__)


class KuryrK8sService(service.Service):
    """Kuryr-Kubernetes controller Service."""

    def __init__(self):
        super(KuryrK8sService, self).__init__()

        objects.register_locally_defined_vifs()
        pipeline = h_pipeline.ControllerPipeline(self.tg)
        self.watcher = watcher.Watcher(pipeline, self.tg)
        # TODO(ivc): pluggable resource/handler registration
        for resource in ["pods", "services", "endpoints"]:
            self.watcher.add("%s/%s" % (constants.K8S_API_BASE, resource))
        pipeline.register(h_vif.VIFHandler())
        pipeline.register(h_lbaas.LBaaSSpecHandler())
        pipeline.register(h_lbaas.LoadBalancerHandler())

    def start(self):
        LOG.info("Service '%s' starting", self.__class__.__name__)
        super(KuryrK8sService, self).start()
        self.watcher.start()
        LOG.info("Service '%s' started", self.__class__.__name__)

    def wait(self):
        super(KuryrK8sService, self).wait()
        LOG.info("Service '%s' stopped", self.__class__.__name__)

    def stop(self, graceful=False):
        LOG.info("Service '%s' stopping", self.__class__.__name__)
        self.watcher.stop()
        super(KuryrK8sService, self).stop(graceful)


def start():
    config.init(sys.argv[1:])
    config.setup_logging()
    clients.setup_clients()
    os_vif.initialize()
    kuryrk8s_launcher = service.launch(config.CONF, KuryrK8sService())
    kuryrk8s_launcher.wait()
