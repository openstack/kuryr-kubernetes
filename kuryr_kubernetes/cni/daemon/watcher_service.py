# Copyright 2022 Red Hat, Inc.
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

import threading
import time
import urllib.parse

import cotyledon
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes.cni import handlers
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import utils
from kuryr_kubernetes import watcher as k_watcher


HEALTH_CHECKER_DELAY = 5
LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class BaseCNIDaemonWatcherService(cotyledon.Service):
    name = "watcher"

    def __init__(self, worker_id, handler, path, registry, healthy):
        super().__init__(worker_id)
        self.pipeline = None
        self.watcher = None
        self.health_thread = None
        self.handler = handler
        self.registry = registry
        self.healthy = healthy
        self.path = path
        self.is_running = False

    def run(self):
        self.pipeline = handlers.CNIPipeline()
        self.pipeline.register(self.handler)
        self.watcher = k_watcher.Watcher(self.pipeline)
        self.watcher.add(self.path)

        self.is_running = True

        self.health_thread = threading.Thread(
            target=self._start_watcher_health_checker)
        self.health_thread.start()

        self.watcher.start()

    def _start_watcher_health_checker(self):
        while self.is_running:
            if not self.watcher.is_alive():
                LOG.warning(f"Reporting watcher {self.__class__.__name__} is "
                            f"not healthy because it's not running anymore.")
                with self.healthy.get_lock():
                    self.healthy.value = False
            time.sleep(HEALTH_CHECKER_DELAY)

    def terminate(self):
        self.is_running = False
        if self.health_thread:
            self.health_thread.join()
        if self.watcher:
            self.watcher.stop()


class KuryrPortWatcherService(BaseCNIDaemonWatcherService):
    def __init__(self, worker_id, registry, healthy):
        query_label = urllib.parse.quote_plus(f'{k_const.KURYRPORT_LABEL}='
                                              f'{utils.get_nodename()}')
        path = f'{k_const.K8S_API_CRD_KURYRPORTS}?labelSelector={query_label}'
        handler = handlers.CNIKuryrPortHandler(registry)
        super().__init__(worker_id, handler, path, registry, healthy)


class PodWatcherService(BaseCNIDaemonWatcherService):
    def __init__(self, worker_id, registry, healthy):
        query_label = urllib.parse.quote_plus(f'spec.nodeName='
                                              f'{utils.get_nodename()}')
        path = f'{k_const.K8S_API_PODS}?fieldSelector={query_label}'
        handler = handlers.CNIPodHandler(registry)
        super().__init__(worker_id, handler, path, registry, healthy)
