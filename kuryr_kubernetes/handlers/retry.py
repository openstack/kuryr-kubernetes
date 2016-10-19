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
import random
import time

from oslo_log import log as logging
from oslo_utils import excutils

from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import base

LOG = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 180
DEFAULT_INTERVAL = 3


class Retry(base.EventHandler):
    """Retries handler on failure.

    `Retry` can be used to decorate another `handler` to be retried whenever
    it raises any of the specified `exceptions`. If the `handler` does not
    succeed within the time limit specified by `timeout`, `Retry` will
    raise the exception risen by `handler`. `Retry` does not interrupt the
    `handler`, so the actual time spent within a single call to `Retry` may
    exceed the `timeout` depending on responsiveness of the `handler`.

    `Retry` implements a variation of exponential backoff algorithm [1] and
    ensures that there is a minimal time `interval` after the failed
    `handler` is retried for the same `event` (expected backoff E(c) =
    interval * 2 ** c / 2).

    [1] https://en.wikipedia.org/wiki/Exponential_backoff
    """

    def __init__(self, handler, exceptions=Exception,
                 timeout=DEFAULT_TIMEOUT, interval=DEFAULT_INTERVAL):
        self._handler = handler
        self._exceptions = exceptions
        self._timeout = timeout
        self._interval = interval

    def __call__(self, event):
        deadline = time.time() + self._timeout
        for attempt in itertools.count(1):
            try:
                self._handler(event)
                break
            except self._exceptions:
                with excutils.save_and_reraise_exception() as ex:
                    if self._sleep(deadline, attempt, ex.value):
                        ex.reraise = False

    def _sleep(self, deadline, attempt, exception):
        now = time.time()
        seconds_left = deadline - now

        if seconds_left <= 0:
            LOG.debug("Handler %s failed (attempt %s; %s), "
                      "timeout exceeded (%s seconds)",
                      self._handler, attempt, exceptions.format_msg(exception),
                      self._timeout)
            return 0

        interval = random.randint(1, 2 ** attempt - 1) * self._interval

        if interval > seconds_left:
            interval = seconds_left

        if interval < self._interval:
            interval = self._interval

        LOG.debug("Handler %s failed (attempt %s; %s), "
                  "retrying in %s seconds",
                  self._handler, attempt, exceptions.format_msg(exception),
                  interval)

        time.sleep(interval)
        return interval
