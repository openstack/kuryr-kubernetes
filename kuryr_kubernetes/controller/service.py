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
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import service
from stevedore.named import NamedExtensionManager

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes.controller.handlers import pipeline as h_pipeline
from kuryr_kubernetes.controller.managers import health
from kuryr_kubernetes import objects
from kuryr_kubernetes import watcher


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def _handler_not_found(names):
    LOG.exception('Handlers "%s" were not found.', names)
    LOG.critical('Handlers "%s" were not found.', names)
    raise SystemExit()


def _handler_not_loaded(manager, entrypoint, exception):
    LOG.exception('Exception when loading handlers %s.', entrypoint)
    LOG.critical('Handlers entrypoint "%s" failed to load due to %s.',
                 entrypoint, exception)
    raise SystemExit()


def _load_kuryr_ctrlr_handlers():
    configured_handlers = CONF.kubernetes.enabled_handlers
    LOG.info('Configured handlers: %s', configured_handlers)
    handlers = NamedExtensionManager(
        'kuryr_kubernetes.controller.handlers',
        configured_handlers,
        invoke_on_load=True,
        on_missing_entrypoints_callback=_handler_not_found,
        on_load_failure_callback=_handler_not_loaded)
    LOG.info('Loaded handlers: %s', handlers.names())
    ctrlr_handlers = []
    for handler in handlers.extensions:
        ctrlr_handlers.append(handler.obj)
    return ctrlr_handlers


class KuryrK8sService(service.Service):
    """Kuryr-Kubernetes controller Service."""

    def __init__(self):
        super(KuryrK8sService, self).__init__()

        objects.register_locally_defined_vifs()
        pipeline = h_pipeline.ControllerPipeline(self.tg)
        self.watcher = watcher.Watcher(pipeline, self.tg)
        self.health_manager = health.HealthServer()

        handlers = _load_kuryr_ctrlr_handlers()
        for handler in handlers:
            self.watcher.add(handler.get_watch_path())
            pipeline.register(handler)

    def start(self):
        LOG.info("Service '%s' starting", self.__class__.__name__)
        super(KuryrK8sService, self).start()
        self.watcher.start()
        self.health_manager.run()
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
