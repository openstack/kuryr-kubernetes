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
import time

from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import health
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class Watcher(health.HealthHandler):
    """Observes K8s resources' events using K8s '?watch=true' API.

    The `Watcher` maintains a list of K8s resources and manages the event
    processing loops for those resources. Event handling is delegated to the
    `callable` object passed as the `handler` initialization parameter that
    will be run for each K8s event observed by the `Watcher`.

    The `Watcher` can operate in two different modes based on the
    `thread_group` initialization parameter:

      - synchronous, when the event processing loops run on the same thread
        that called 'add' or 'start' methods

      - asynchronous, when each event processing loop runs on its own thread
        (`oslo_service.threadgroup.Thread`) from the `thread_group`

    When started, the `Watcher` will run the event processing loops for each
    of the K8s resources on the list. Adding a K8s resource to the running
    `Watcher` also ensures that the event processing loop for that resource is
    running.

    Stopping the `Watcher` or removing the specific K8s resource from the
    list will request the corresponding running event processing loops to
    stop gracefully, but will not interrupt any running `handler`. Forcibly
    stopping any 'stuck' `handler` is not supported by the `Watcher` and
    should be handled externally (e.g. by using `thread_group.stop(
    graceful=False)` for asynchronous `Watcher`).
    """

    def __init__(self, handler, thread_group=None, timeout=None):
        """Initializes a new Watcher instance.

        :param handler: a `callable` object to be invoked for each observed
                        K8s event with the event body as a single argument.
                        Calling `handler` should never raise any exceptions
                        other than `eventlet.greenlet.GreenletExit` caused by
                        `eventlet.greenthread.GreenThread.kill` when the
                        `Watcher` is operating in asynchronous mode.
        :param thread_group: an `oslo_service.threadgroup.ThreadGroup`
                             object used to run the event processing loops
                             asynchronously. If `thread_group` is not
                             specified, the `Watcher` will operate in a
                             synchronous mode.
        """
        super(Watcher, self).__init__()
        self._client = clients.get_kubernetes_client()
        self._handler = handler
        self._thread_group = thread_group
        self._running = False
        self._resources = set()
        self._watching = {}
        self._timers = {}
        self._idle = {}

        if timeout is None:
            timeout = CONF.kubernetes.watch_retry_timeout
        self._timeout = timeout

    def add(self, path):
        """Adds ths K8s resource to the Watcher.

        Adding a resource to a running `Watcher` also ensures that the event
        processing loop for that resource is running. This method could block
        for `Watcher`s operating in synchronous mode.

        :param path: K8s resource URL path
        """
        self._resources.add(path)
        if self._running and path not in self._watching:
            self._start_watch(path)

    def remove(self, path):
        """Removes the K8s resource from the Watcher.

        Also requests the corresponding event processing loop to stop if it
        is running.

        :param path: K8s resource URL path
        """
        self._resources.discard(path)
        if path in self._watching:
            self._stop_watch(path)

    def is_running(self):
        return self._running

    def start(self):
        """Starts the Watcher.

        Also ensures that the event processing loops are running. This method
        could block for `Watcher`s operating in synchronous mode.
        """
        self._running = True
        for path in self._resources - set(self._watching):
            self._start_watch(path)

    def stop(self):
        """Stops the Watcher.

        Also requests all running event processing loops to stop.
        """
        self._running = False
        for path in list(self._watching):
            self._stop_watch(path)

    def _reconcile(self, path):
        LOG.debug(f'Getting {path} for reconciliation.')
        try:
            response = self._client.get(path)
            resources = response['items']
        except exceptions.K8sClientException:
            LOG.exception(f'Error getting path when reconciling.')
            return

        # NOTE(gryf): For some resources (like pods) we could observe that
        # 'items' is set to None. I'm not sure if that's a K8s issue, since
        # accroding to the documentation is should be list.
        if not resources:
            return

        for resource in resources:
            event = {
                'type': 'MODIFIED',
                'object': resource,
            }
            self._handler(event, injected=True)

    def _start_watch(self, path):
        tg = self._thread_group
        self._idle[path] = True
        if tg:
            self._watching[path] = tg.add_thread(self._watch, path)
            period = CONF.kubernetes.watch_reconcile_period
            if period > 0:
                # Let's make sure handlers won't reconcile at the same time.
                initial_delay = period + 5 * len(self._timers)
                self._timers[path] = tg.add_timer_args(
                    period, self._reconcile, args=(path,),
                    initial_delay=initial_delay, stop_on_exception=False)
        else:
            self._watching[path] = None
            self._watch(path)

    def _stop_watch(self, path):
        if self._idle.get(path):
            if self._thread_group and path in self._watching:
                if CONF.kubernetes.watch_reconcile_period:
                    self._timers[path].stop()
                self._watching[path].stop()
                # NOTE(dulek): Thread gets killed immediately, so we need to
                # take care of this ourselves.
                if CONF.kubernetes.watch_reconcile_period:
                    self._timers.pop(path, None)
                self._watching.pop(path, None)
                self._idle.pop(path, None)

    def _graceful_watch_exit(self, path):
        try:
            self._watching.pop(path, None)
            if CONF.kubernetes.watch_reconcile_period:
                self._timers.pop(path, None)
            self._idle.pop(path, None)
            LOG.info("Stopped watching '%s'", path)
        except KeyError:
            LOG.error("Failed to exit watch gracefully")
        finally:
            if not self._watching and not self._idle:
                self.stop()
                LOG.info("No remaining active watchers, Exiting...")
                sys.exit(1)

    def _watch(self, path):
        attempts = 0
        deadline = 0
        while self._running and path in self._resources:
            try:
                retry = False
                if attempts == 1:
                    deadline = time.time() + self._timeout

                if (attempts > 0 and
                   utils.exponential_sleep(deadline, attempts) == 0):
                    LOG.error("Failed watching '%s': deadline exceeded", path)
                    self._alive = False
                    return

                LOG.info("Started watching '%s'", path)
                for event in self._client.watch(path):
                    # NOTE(esevan): Watcher retries watching for
                    # `self._timeout` duration with exponential backoff
                    # algorithm to tolerate against temporal exception such as
                    # temporal disconnection to the k8s api server.
                    attempts = 0
                    self._idle[path] = False
                    self._handler(event)
                    self._idle[path] = True
                    if not (self._running and path in self._resources):
                        return
            except Exception:
                LOG.exception("Caught exception while watching.")
                LOG.warning("Restarting(%s) watching '%s'.",
                            attempts, path)
                attempts += 1
                retry = True
                self._idle[path] = True
            finally:
                if not retry:
                    self._graceful_watch_exit(path)
