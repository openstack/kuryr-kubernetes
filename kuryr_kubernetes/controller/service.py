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

import functools
import six
import sys

import os_vif
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import periodic_task
from oslo_service import service
from stevedore.named import NamedExtensionManager

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.handlers import pipeline as h_pipeline
from kuryr_kubernetes.controller.ingress import ingress_ctl
from kuryr_kubernetes.controller.managers import health
from kuryr_kubernetes import objects
from kuryr_kubernetes import utils
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


class KuryrK8sServiceMeta(type(service.Service),
                          type(periodic_task.PeriodicTasks)):
    pass


class KuryrK8sService(six.with_metaclass(KuryrK8sServiceMeta,
                                         service.Service,
                                         periodic_task.PeriodicTasks)):
    """Kuryr-Kubernetes controller Service."""

    def __init__(self):
        super(KuryrK8sService, self).__init__()
        periodic_task.PeriodicTasks.__init__(self, CONF)

        objects.register_locally_defined_vifs()
        pipeline = h_pipeline.ControllerPipeline(self.tg)
        self.watcher = watcher.Watcher(pipeline, self.tg)
        self.health_manager = health.HealthServer()
        self.current_leader = None
        self.node_name = utils.get_node_name()

        handlers = _load_kuryr_ctrlr_handlers()
        for handler in handlers:
            self.watcher.add(handler.get_watch_path())
            pipeline.register(handler)
        self.pool_driver = drivers.VIFPoolDriver.get_instance(
            specific_driver='multi_pool')
        self.pool_driver.set_vif_driver()

    def is_leader(self):
        return self.current_leader == self.node_name

    def start(self):
        LOG.info("Service '%s' starting", self.__class__.__name__)
        ingress_ctrl = ingress_ctl.IngressCtrlr.get_instance()
        ingress_ctrl.start_operation()
        super(KuryrK8sService, self).start()

        if not CONF.kubernetes.controller_ha:
            LOG.info('Running in non-HA mode, starting watcher immediately.')
            self.watcher.start()
            self.pool_driver.sync_pools()
        else:
            LOG.info('Running in HA mode, watcher will be started later.')
            f = functools.partial(self.run_periodic_tasks, None)
            self.tg.add_timer(1, f)

        self.health_manager.run()
        LOG.info("Service '%s' started", self.__class__.__name__)

    @periodic_task.periodic_task(spacing=5, run_immediately=True)
    def monitor_leader(self, context):
        leader = utils.get_leader_name()
        if leader is None:
            # Error when fetching current leader. We're paranoid, so just to
            # make sure we won't break anything we'll try to step down.
            self.on_revoke_leader()
        elif leader != self.current_leader and leader == self.node_name:
            # I'm becoming the leader.
            self.on_become_leader()
        elif leader != self.current_leader and self.is_leader():
            # I'm revoked from being the leader.
            self.on_revoke_leader()
        elif leader == self.current_leader and self.is_leader():
            # I continue to be the leader
            self.on_continue_leader()

        self.current_leader = leader

    def on_become_leader(self):
        LOG.info('Controller %s becomes the leader, starting watcher.',
                 self.node_name)
        self.watcher.start()
        self.pool_driver.sync_pools()

    def on_revoke_leader(self):
        LOG.info('Controller %s stops being the leader, stopping watcher.',
                 self.node_name)
        if self.watcher.is_running():
            self.watcher.stop()

    def on_continue_leader(self):
        # Just make sure my watcher is running.
        if not self.watcher.is_running():
            LOG.warning('Controller %s is the leader, but has watcher '
                        'stopped. Restarting it.')
            self.watcher.start()

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
