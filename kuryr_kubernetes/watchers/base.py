# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import abc
import requests

from kuryr.lib._i18n import _LE
from oslo_log import log as logging

from kuryr_kubernetes.aio import headers as aio_headers
from kuryr_kubernetes.aio import methods as aio_methods
from kuryr_kubernetes import config
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)

ADDED_EVENT = 'ADDED'
DELETED_EVENT = 'DELETED'
MODIFIED_EVENT = 'MODIFIED'


class AbstractBaseWatcher(object):
    """Base abstract watcher.

    This class implements the default interface for the KuryrK8sService task
    scheduler, which is the `watch` (no parameters) interface.

    It also define a serie of abstract methods that actual watchers have to
    implement in order to deal directly with events without worrying about
    connection and serialization details.

    These methods are:

        * get_endpoint(self): return a resource URL exposed on Kubernetes API
                              as a string (such as "/api/v1/pods")
        * on_add/on_modify/on_delete: actions to do according to each event
                                      type.

    These methods have to follow the async/await python3.5 syntax
    """

    def __init__(self, event_loop):
        self._event_loop = event_loop

    @abc.abstractmethod
    def get_api_endpoint(self):
        pass

    @property
    def api_endpoint(self):
        k8s_root = config.CONF.kubernetes.api_root
        return k8s_root + self.get_api_endpoint() + "?watch=true"

    async def _on_event(self, event): # flake8: noqa

        event_type = event['type']
        if event_type == ADDED_EVENT:
            await self.on_add(event)
        elif event_type == DELETED_EVENT:
            await self.on_delete(event)
        elif event_type == MODIFIED_EVENT:
            await self.on_modify(event)
        else:
            LOG.warning(_LW("Unhandled event type '%(event_type)s'"),
                        {'event_type': event})

    @abc.abstractmethod
    async def on_add(self, event):
        pass

    @abc.abstractmethod
    async def on_modify(self, event):
        pass

    @abc.abstractmethod
    async def on_delete(self, event):
        pass

    async def watch(self):
        """Watches the endpoint and calls the callback with its response.

        This is an endless task that keeps the event loop running forever
        """
        response = await self._get_chunked_response()
        while True:
            content = await response.read_line()
            LOG.debug('Received new event from %(watcher)s:\n\n\t'
                      '%(event)s.\n\n',
                      {'watcher': self.__class__.__name__,
                       'event': str(content)})
            await self._on_event(content)

    async def _get_chunked_response(self):
        """Get the response from Kubernetes API."""
        response = await aio_methods.get(
            endpoint=self.api_endpoint,
            loop=self._event_loop,
            decoder=utils.utf8_json_decoder)

        status, reason, hdrs = await response.read_headers()
        if status != requests.codes.ok:  # Function returns 200
            LOG.error(_LE('GET request to endpoint %(ep)s failed with '
                          'status %(status)s and reason %(reason)s'),
                      {'ep': endpoint, 'status': status, 'reason': reason})
            raise requests.exceptions.HTTPError('{}: {}. Endpoint {}'.format(
                status, reason, endpoint))
        if hdrs.get(aio_headers.TRANSFER_ENCODING) != 'chunked':
            LOG.error(_LE('watcher GET request to endpoint %(ep)s is not '
                          'chunked. headers: %(hdrs)s'),
                      {'ep': endpoint, 'hdrs': hdrs})
            raise IOError(_('Can only watch endpoints that returned chunked '
                            'encoded transfers'))

        return response
