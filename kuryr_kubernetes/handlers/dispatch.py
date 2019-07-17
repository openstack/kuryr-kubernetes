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

import abc
import six

from oslo_log import log as logging

from kuryr_kubernetes.handlers import base as h_base

LOG = logging.getLogger(__name__)


class Dispatcher(h_base.EventHandler):
    """Dispatches events to registered handlers.

    Dispatcher serves as both multiplexer and filter for dispatching events
    to multiple registered handlers based on the event content and
    predicates provided during the handler registration.
    """

    def __init__(self):
        self._registry = {}

    def register(self, key_fn, key, handler):
        """Adds handler to the registry.

        `key_fn` and `key` constitute the `key_fn(event) == key` predicate
        that determines if the `handler` should be called for a given `event`.

        :param key_fn: function that will be called for each event to
                       determine the event `key`
        :param key: value to match against the result of `key_fn` function
                    that determines if the `handler` should be called for an
                    event
        :param handler: `callable` object that would be called if the
                        conditions specified by `key_fn` and `key` are met
        """
        key_group = self._registry.setdefault(key_fn, {})
        handlers = key_group.setdefault(key, [])
        handlers.append(handler)

    def __call__(self, event):
        handlers = set()

        for key_fn, key_group in self._registry.items():
            key = key_fn(event)
            handlers.update(key_group.get(key, ()))

        obj = event.get('object', {})
        obj_meta = obj.get('metadata', {})

        LOG.debug("%d handler(s) available for event %s %s:%s/%s (uid: %s)",
                  len(handlers), event.get('type'), obj.get('kind'),
                  obj_meta.get('namespace'), obj_meta.get('name'),
                  obj_meta.get('uid'))

        for handler in handlers:
            handler(event)


@six.add_metaclass(abc.ABCMeta)
class EventConsumer(h_base.EventHandler):
    """Consumes events matching specified predicates.

    EventConsumer is an interface for all event handlers that are to be
    registered by the `EventPipeline`.
    """

    def __init__(self):
        super(EventConsumer, self).__init__()

    @abc.abstractproperty
    def consumes(self):
        """Predicates determining events supported by this handler.

        :return: `dict` object containing {key_fn: key} predicates to be
                 used by `Dispatcher.register`
        """
        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class EventPipeline(h_base.EventHandler):
    """Serves as an entry-point for event handling.

    Implementing subclasses should override `_wrap_dispatcher` and/or
    `_wrap_consumer` methods to sanitize the consumers passed to `register`
    (i.e. to satisfy the `Watcher` requirement that the event handler does
    not raise exceptions) and to add features like asynchronous event
    processing or retry-on-failure functionality.
    """

    def __init__(self):
        self._dispatcher = Dispatcher()
        self._handler = self._wrap_dispatcher(self._dispatcher)

    def register(self, consumer):
        """Adds handler to the registry.

        :param consumer: `EventConsumer`-type object
        """
        handler = self._wrap_consumer(consumer)
        for key_fn, key in consumer.consumes.items():
            self._dispatcher.register(key_fn, key, handler)

    def __call__(self, event):
        self._handler(event)

    @abc.abstractmethod
    def _wrap_dispatcher(self, dispatcher):
        raise NotImplementedError()

    @abc.abstractmethod
    def _wrap_consumer(self, consumer):
        raise NotImplementedError()
