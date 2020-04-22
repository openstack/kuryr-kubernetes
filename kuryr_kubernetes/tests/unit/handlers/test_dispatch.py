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

from unittest import mock

from kuryr_kubernetes.handlers import dispatch as h_dis
from kuryr_kubernetes.tests import base as test_base


def make_event(name):
    return {'object': {'metadata': {'name': str(name)}}}


class TestDispatch(test_base.TestCase):
    def test_dispatch(self):
        events = [make_event(i) for i in range(3)]
        handler = mock.Mock()
        dispatcher = h_dis.Dispatcher()
        dispatcher.register(lambda e: True, True, handler)

        for event in events:
            dispatcher(event)

        handler.assert_has_calls([mock.call(e) for e in events])

    def test_dispatch_broadcast(self):
        handlers = [mock.Mock() for _ in range(3)]
        dispatcher = h_dis.Dispatcher()
        event = make_event(mock.sentinel.event_name)

        for handler in handlers:
            dispatcher.register(lambda e: True, True, handler)

        dispatcher(event)

        for handler in handlers:
            handler.assert_called_once_with(event)

    def test_dispatch_by_key(self):
        def key_fn(event):
            return event['object']['metadata']['name']

        events = {}
        for i in range(3):
            e = make_event(i)
            events[key_fn(e)] = e
        handlers = {key: mock.Mock() for key in events}
        dispatcher = h_dis.Dispatcher()
        for key, handler in handlers.items():
            dispatcher.register(key_fn, key, handler)

        for event in events.values():
            dispatcher(event)

        for key, handler in handlers.items():
            handler.assert_called_once_with(events[key])


class _TestEventPipeline(h_dis.EventPipeline):
    def _wrap_dispatcher(self, dispatcher):
        pass

    def _wrap_consumer(self, consumer):
        pass


class TestEventPipeline(test_base.TestCase):
    @mock.patch.object(_TestEventPipeline, '_wrap_dispatcher')
    @mock.patch('kuryr_kubernetes.handlers.dispatch.Dispatcher')
    def test_init(self, m_dispatcher_type, m_wrapper):
        m_dispatcher_type.return_value = mock.sentinel.dispatcher
        m_wrapper.return_value = mock.sentinel.handler

        pipeline = _TestEventPipeline()

        m_dispatcher_type.assert_called_once()
        m_wrapper.assert_called_once_with(mock.sentinel.dispatcher)
        self.assertEqual(mock.sentinel.dispatcher, pipeline._dispatcher)
        self.assertEqual(mock.sentinel.handler, pipeline._handler)

    @mock.patch.object(_TestEventPipeline, '_wrap_consumer')
    @mock.patch.object(_TestEventPipeline, '__init__')
    def test_register(self, m_init, m_wrap_consumer):
        consumes = {mock.sentinel.key_fn1: mock.sentinel.key1,
                    mock.sentinel.key_fn2: mock.sentinel.key2,
                    mock.sentinel.key_fn3: mock.sentinel.key3}
        m_dispatcher = mock.Mock()
        m_consumer = mock.Mock()
        m_consumer.consumes = consumes
        m_wrap_consumer.return_value = mock.sentinel.handler
        m_init.return_value = None
        pipeline = _TestEventPipeline()
        pipeline._dispatcher = m_dispatcher

        pipeline.register(m_consumer)

        m_wrap_consumer.assert_called_once_with(m_consumer)
        m_dispatcher.register.assert_has_calls([
            mock.call(key_fn, key, mock.sentinel.handler)
            for key_fn, key in consumes.items()], any_order=True)

    @mock.patch.object(_TestEventPipeline, '__init__')
    def test_call(self, m_init):
        m_init.return_value = None
        m_handler = mock.Mock()
        pipeline = _TestEventPipeline()
        pipeline._handler = m_handler

        pipeline(mock.sentinel.event)

        m_handler.assert_called_once_with(mock.sentinel.event)
