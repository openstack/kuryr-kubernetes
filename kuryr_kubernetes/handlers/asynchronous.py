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
from six.moves import queue as six_queue

from kuryr.lib._i18n import _LC
from oslo_log import log as logging


from kuryr_kubernetes.handlers import base

LOG = logging.getLogger(__name__)

DEFAULT_QUEUE_DEPTH = 100
DEFAULT_GRACE_PERIOD = 5
INF = float("inf")


class Async(base.EventHandler):
    """Handles events asynchronously.

    `Async` can be used to decorate another `handler` to be run asynchronously
    using the specified `thread_group`. `Async` distinguishes *related* and
    *unrelated* events (based on the result of `group_by`(`event`) function)
    and handles *unrelated* events concurrently while *related* events are
    handled serially and in the same order they arrived to `Async`.
    """

    def __init__(self, handler, thread_group, group_by,
                 queue_depth=DEFAULT_QUEUE_DEPTH,
                 grace_period=DEFAULT_GRACE_PERIOD):
        self._handler = handler
        self._thread_group = thread_group
        self._group_by = group_by
        self._queue_depth = queue_depth
        self._grace_period = grace_period
        self._queues = {}

    def __call__(self, event):
        group = self._group_by(event)
        try:
            queue = self._queues[group]
        except KeyError:
            queue = six_queue.Queue(self._queue_depth)
            self._queues[group] = queue
            thread = self._thread_group.add_thread(self._run, group, queue)
            thread.link(self._done, group)
        queue.put(event)

    def _run(self, group, queue):
        LOG.debug("Asynchronous handler started processing %s", group)
        for _ in itertools.count():
            # NOTE(ivc): this is a mock-friendly replacement for 'while True'
            # to allow more controlled environment for unit-tests (e.g. to
            # avoid tests getting stuck in infinite loops)
            try:
                event = queue.get(timeout=self._grace_period)
            except six_queue.Empty:
                break
            self._handler(event)

    def _done(self, thread, group):
        LOG.debug("Asynchronous handler stopped processing %s", group)
        queue = self._queues.pop(group)

        if not queue.empty():
            LOG.critical(_LC("Asynchronous handler terminated abnormally; "
                             "%(count)s events dropped for %(group)s"),
                         {'count': queue.qsize(), 'group': group})

        if not self._queues:
            LOG.debug("Asynchronous handler is idle")
