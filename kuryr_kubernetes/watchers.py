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
import asyncio
import functools
import requests

from kuryr.lib._i18n import _LI, _LW, _LE
from oslo_log import log as logging
from oslo_serialization import jsonutils

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

    It takes care of the events that receives and it triggers the appropiate
    action on the translators configured on the config.kubernetes.config_map
    structure.

    Actual watchers will only need to define the 'get_api_endpoint' method
    that return an String URL in order to suscribe to Kubernetes API events.
    (See :class PodWatcher: below).
    """

    def __init__(self, event_loop, translators):
        self._event_loop = event_loop
        self._translators = translators
        self._k8s_root = config.CONF.kubernetes.api_root

    async def _get_chunked_connection(self): # flake8: noqa
        """Get the connection response from Kubernetes API.

        Initializes the connection with Kubernetes API. Since the content type
        is Chunked (http://en.wikipedia.org/wiki/Chunked_transfer_encoding), the
        connection remains open.
        """
        connection = await aio_methods.get(
            endpoint=self.api_endpoint,
            loop=self._event_loop,
            decoder=utils.utf8_json_decoder)

        status, reason, hdrs = await connection.read_headers()
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

        return connection

    def _update_annotation(self, self_link, annotation, future):
        """Update K8s entities' annotations

        This method is the callback of all the tasks scheduled in the
        'self._on_event' method.

        In case the _on_event 'future' returns something different that None, it
        will update the annotations in resource defined by 'self_link' with the
        key 'annotation' and value 'future.get_result()'

        :param self_link: Entity link to update.
        :param annotation: Key of the annotation to update.
        :param future: Value of the annotation to update.
        """
        future_result = future.result()
        if not future_result:
            return

        patch_headers = {
            'Content-Type': 'application/strategic-merge-patch+json',
            'Accept': 'application/json',
        }

        # Annotations are supposed to be key=value, being 'value'
        # an string. So we need to dump the dict result into the annotation into
        # a json
        future_result_json = jsonutils.dumps(future_result)

        annotations = {annotation: jsonutils.dumps(future_result)}
        data = jsonutils.dumps({
            'metadata': {
                'annotations': annotations}})
        url = self._k8s_root + self_link

        # TODO(devvesa): Use the aio package to convert this call into an
        # asynchornous one. Aio package does not support patch method yet.
        result = requests.patch(url, data=data, headers=patch_headers)
        if not result.ok:
            LOG.warn(_LW("PATCH request to %(url)s for annotation update "
                          "%(data)s failed with error code %(error_code)s and "
                          "reason %(reason)s"),
                     {'url': url,
                      'data': data,
                      'error_code': result.status_code,
                      'reason': result.json()})
        LOG.debug("Annotation update %(data)s succeded on resource %(url)s",
                  {'data': data, 'url': url})


    async def _on_event(self, event):

        if not 'type' in event:
            LOG.warn(_LW('Received an event without "type":\n\n\t%(event)s'),
                     {'event': event})
            return

        event_type = event['type']
        self_link = event['object']['metadata']['selfLink']
        LOG.info(_LI('Received an %(event_type)s event on a '
                     '%(kind)s with link "%(link)s"'),
                 {'event_type': event_type,
                  'kind': event['object']['kind'],
                  'link': self_link})

        # Dispatch the event on its method
        dispatch_map = {
            ADDED_EVENT: 'on_add',
            DELETED_EVENT: 'on_delete',
            MODIFIED_EVENT: 'on_modify'}

        if not event_type in dispatch_map:
            LOG.warning(_LW("Unhandled event type '%(event_type)s'"),
                        {'event_type': event_type})
            return

        # Run the method on each of the translators defined on the config_map
        tasks = []
        for t_class in self._translators:
           translator = t_class()
           method = getattr(translator, dispatch_map[event_type])
           task = self._event_loop.create_task(method(event))
           task.add_done_callback(
                functools.partial(self._update_annotation, self_link,
                                  translator.get_annotation()))
           tasks.append(task)
        asyncio.wait(tasks)

    @property
    def api_endpoint(self):
        k8s_root = config.CONF.kubernetes.api_root
        return k8s_root + self.get_api_endpoint() + "?watch=true"

    @abc.abstractmethod
    def get_api_endpoint(self):
        pass

    async def watch(self):
        """Watches the endpoint and calls the callback with its response.

        This is an endless task that keeps the event loop running forever
        """
        connection = await self._get_chunked_connection()
        while True:
            content = await connection.read_line()
            LOG.debug('Received new event from %(watcher)s:\n\n\t'
                      '%(event)s.\n\n',
                      {'watcher': self.__class__.__name__,
                       'event': str(content)})
            await self._on_event(content)


class PodWatcher(AbstractBaseWatcher):
    """Watch the Pod endpoints on K8s API."""

    ENDPOINT = "/api/v1/pods"

    def __init__(self, event_loop, translators):
        super().__init__(event_loop, translators)

    def get_api_endpoint(self):
        return self.ENDPOINT
