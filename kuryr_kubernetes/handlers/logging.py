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

from oslo_log import log as logging

from kuryr_kubernetes.handlers import base

LOG = logging.getLogger(__name__)


class LogExceptions(base.EventHandler):
    """Suppresses exceptions and sends them to log.

    LogExceptions wraps `handler` passed as an initialization parameter by
    suppressing `exceptions` it raises and sending them to logging facility
    instead.
    """

    def __init__(self, handler, exceptions=Exception, ignore_exceptions=None):
        self._handler = handler
        self._exceptions = exceptions
        self._ignore_exceptions = ignore_exceptions or ()

    def __call__(self, event, *args, **kwargs):
        try:
            self._handler(event, *args, **kwargs)
        except self._ignore_exceptions:
            pass
        except self._exceptions as ex:
            # If exception comes from OpenStack SDK and contains
            # 'request_id' then print this 'request_id' along the Exception.
            # This 'request_id' can be then used to search the OpenStack
            # service logs.
            req_id = ''
            if hasattr(ex, 'request_id'):
                req_id = f' [{ex.request_id}]'
            LOG.exception("Failed to handle event%s: %s", req_id, event)
