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

import queue
from unittest import mock

from kuryr_kubernetes.handlers import asynchronous as h_async
from kuryr_kubernetes.tests import base as test_base


class TestAsyncHandler(test_base.TestCase):

    def test_call(self):
        event = mock.sentinel.event
        group = mock.sentinel.group
        m_queue = mock.Mock()
        m_handler = mock.Mock()
        m_group_by = mock.Mock(return_value=group)
        m_info = mock.Mock(return_value=group)
        async_handler = h_async.Async(m_handler, mock.Mock(), m_group_by,
                                      m_info)
        async_handler._queues[group] = m_queue

        async_handler(event)

        m_handler.assert_not_called()
        self.assertEqual({group: m_queue}, async_handler._queues)
        m_queue.put.assert_called_once_with((event, (), {}))

    @mock.patch('queue.Queue')
    def test_call_new(self, m_queue_type):
        event = mock.sentinel.event
        group = mock.sentinel.group
        queue_depth = mock.sentinel.queue_depth
        m_queue = mock.Mock()
        m_queue_type.return_value = m_queue
        m_handler = mock.Mock()
        m_th = mock.Mock()
        m_tg = mock.Mock()
        m_tg.add_thread.return_value = m_th
        m_group_by = mock.Mock(return_value=group)
        m_info = mock.Mock(return_value=group)
        async_handler = h_async.Async(m_handler, m_tg, m_group_by, m_info,
                                      queue_depth=queue_depth)

        async_handler(event)

        m_handler.assert_not_called()
        m_queue_type.assert_called_once_with(queue_depth)
        self.assertEqual({group: m_queue}, async_handler._queues)
        m_tg.add_thread.assert_called_once_with(async_handler._run, group,
                                                m_queue, group)
        m_th.link.assert_called_once_with(async_handler._done, group, group)
        m_queue.put.assert_called_once_with((event, (), {}))

    def test_call_injected(self):
        event = mock.sentinel.event
        group = mock.sentinel.group
        m_queue = mock.Mock()
        m_handler = mock.Mock()
        m_group_by = mock.Mock(return_value=group)
        m_info = mock.Mock(return_value=group)
        async_handler = h_async.Async(m_handler, mock.Mock(), m_group_by,
                                      m_info)
        async_handler._queues[group] = m_queue

        async_handler(event, injected=True)

        m_handler.assert_not_called()
        self.assertEqual({group: m_queue}, async_handler._queues)
        m_queue.put.assert_not_called()

    @mock.patch('itertools.count')
    def test_run(self, m_count):
        event = mock.sentinel.event
        group = mock.sentinel.group
        m_queue = mock.Mock()
        m_queue.empty.return_value = True
        m_queue.get.return_value = (event, (), {})
        m_handler = mock.Mock()
        m_count.return_value = [1]
        async_handler = h_async.Async(m_handler, mock.Mock(), mock.Mock(),
                                      mock.Mock(), queue_depth=1)

        with mock.patch('time.sleep'):
            async_handler._run(group, m_queue, None)

        m_handler.assert_called_once_with(event)

    @mock.patch('itertools.count')
    def test_run_empty(self, m_count):
        events = [(x, (), {}) for x in (mock.sentinel.event1,
                                        mock.sentinel.event2)]
        group = mock.sentinel.group
        m_queue = mock.Mock()
        m_queue.empty.return_value = True
        m_queue.get.side_effect = events + [queue.Empty()]
        m_handler = mock.Mock()
        m_count.return_value = list(range(5))
        async_handler = h_async.Async(m_handler, mock.Mock(), mock.Mock(),
                                      mock.Mock())

        with mock.patch('time.sleep'):
            async_handler._run(group, m_queue, None)

        m_handler.assert_has_calls([mock.call(event[0]) for event in events])
        self.assertEqual(len(events), m_handler.call_count)

    @mock.patch('itertools.count')
    def test_run_stale(self, m_count):
        events = [(x, (), {}) for x in (mock.sentinel.event1,
                                        mock.sentinel.event2)]
        group = mock.sentinel.group
        m_queue = mock.Mock()
        m_queue.empty.side_effect = [False, True, True]
        m_queue.get.side_effect = events + [queue.Empty()]
        m_handler = mock.Mock()
        m_count.return_value = list(range(5))
        async_handler = h_async.Async(m_handler, mock.Mock(), mock.Mock(),
                                      mock.Mock())

        with mock.patch('time.sleep'):
            async_handler._run(group, m_queue, None)

        m_handler.assert_called_once_with(mock.sentinel.event2)

    def test_done(self):
        group = mock.sentinel.group
        m_queue = mock.Mock()
        async_handler = h_async.Async(mock.Mock(), mock.Mock(), mock.Mock(),
                                      mock.Mock())
        async_handler._queues[group] = m_queue

        async_handler._done(mock.Mock(), group, None)

        self.assertFalse(async_handler._queues)

    @mock.patch('kuryr_kubernetes.handlers.asynchronous.LOG.critical')
    def test_done_terminated(self, m_critical):
        group = mock.sentinel.group
        m_queue = mock.Mock()
        m_queue.empty.return_value = False
        async_handler = h_async.Async(mock.Mock(), mock.Mock(), mock.Mock(),
                                      mock.Mock())
        async_handler._queues[group] = m_queue

        async_handler._done(mock.Mock(), group, None)

        m_critical.assert_called_once()
