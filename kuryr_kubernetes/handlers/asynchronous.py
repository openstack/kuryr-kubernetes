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

import itertools
import queue as py_queue
import time

from oslo_concurrency import lockutils
from oslo_log import log as logging


from kuryr_kubernetes.handlers import base

LOG = logging.getLogger(__name__)

DEFAULT_QUEUE_DEPTH = 100
DEFAULT_GRACE_PERIOD = 5
STALE_PERIOD = 0.5


class Async(base.EventHandler):
    """Handles events asynchronously.

    `Async` can be used to decorate another `handler` to be run asynchronously
    using the specified `thread_group`. `Async` distinguishes *related* and
    *unrelated* events (based on the result of `group_by`(`event`) function)
    and handles *unrelated* events concurrently while *related* events are
    handled serially and in the same order they arrived to `Async`.
    """

    def __init__(self, handler, thread_group, group_by, info_func,
                 queue_depth=DEFAULT_QUEUE_DEPTH,
                 grace_period=DEFAULT_GRACE_PERIOD):
        self._handler = handler
        self._thread_group = thread_group
        self._group_by = group_by
        self._info_func = info_func
        self._queue_depth = queue_depth
        self._grace_period = grace_period
        self._queues = {}

    def __call__(self, event, *args, **kwargs):
        group = self._group_by(event)
        with lockutils.lock(group):
            try:
                queue = self._queues[group]
                # NOTE(dulek): We don't want to risk injecting an outdated
                #              state if events for that resource are in queue.
                if kwargs.get('injected', False):
                    return
            except KeyError:
                queue = py_queue.Queue(self._queue_depth)
                self._queues[group] = queue
                info = self._info_func(event)
                thread = self._thread_group.add_thread(self._run, group, queue,
                                                       info)
                thread.link(self._done, group, info)
        queue.put((event, args, kwargs))

    def _run(self, group, queue, info):
        LOG.trace("Asynchronous handler started processing %s (%s)", group,
                  info)
        for _ in itertools.count():
            # NOTE(ivc): this is a mock-friendly replacement for 'while True'
            # to allow more controlled environment for unit-tests (e.g. to
            # avoid tests getting stuck in infinite loops)
            try:
                event, args, kwargs = queue.get(timeout=self._grace_period)
            except py_queue.Empty:
                break
            # FIXME(ivc): temporary workaround to skip stale events
            # If K8s updates resource while the handler is processing it,
            # when the handler finishes its work it can fail to update an
            # annotation due to the 'resourceVersion' conflict. K8sClient
            # was updated to allow *new* annotations to be set ignoring
            # 'resourceVersion', but it leads to another problem as the
            # Handler will receive old events (i.e. before annotation is set)
            # and will start processing the event 'from scratch'.
            # It has negative effect on handlers' performance (VIFHandler
            # creates ports only to later delete them and LBaaS handler also
            # produces some excess requests to Neutron, although with lesser
            # impact).
            # Possible solutions (can be combined):
            #  - use K8s ThirdPartyResources to store data/annotations instead
            #    of native K8s resources (assuming Kuryr-K8s will own those
            #    resources and no one else would update them)
            #  - use the resulting 'resourceVersion' received from K8sClient's
            #    'annotate' to provide feedback to Async to skip all events
            #    until that version
            #  - stick to the 'get-or-create' behaviour in handlers and
            #    also introduce cache for long operations
            time.sleep(STALE_PERIOD)
            while not queue.empty():
                event, args, kwargs = queue.get()
                if queue.empty():
                    time.sleep(STALE_PERIOD)
            self._handler(event, *args, **kwargs)

    def _done(self, thread, group, info):
        LOG.trace("Asynchronous handler stopped processing group %s (%s)",
                  group, info)
        queue = self._queues.pop(group)

        if not queue.empty():
            LOG.critical(
                "Asynchronous handler thread terminated abnormally; %(count)s "
                "events dropped for %(group)s (%(info)s)",
                {'count': queue.qsize(), 'group': group, 'info': info})

        if not self._queues:
            LOG.trace("Asynchronous handler is idle")
