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

from eventlet import greenlet
from unittest import mock

from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures
from kuryr_kubernetes import watcher
from requests import exceptions


class TestWatcher(test_base.TestCase):
    def setUp(self):
        super(TestWatcher, self).setUp()
        mock_client = self.useFixture(kuryr_fixtures.MockK8sClient())
        self.client = mock_client.client

    @mock.patch.object(watcher.Watcher, '_start_watch')
    def test_add(self, m_start_watch):
        paths = ['/test%s' % i for i in range(3)]
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)

        for path in paths:
            watcher_obj.add(path)

        self.assertEqual(set(paths), watcher_obj._resources)
        m_start_watch.assert_not_called()

    @mock.patch.object(watcher.Watcher, '_start_watch')
    def test_add_running(self, m_start_watch):
        paths = ['/test%s' % i for i in range(3)]
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)
        watcher_obj._running = True

        for path in paths:
            watcher_obj.add(path)

        self.assertEqual(set(paths), watcher_obj._resources)
        m_start_watch.assert_has_calls([mock.call(path) for path in paths],
                                       any_order=True)

    @mock.patch.object(watcher.Watcher, '_start_watch')
    def test_add_watching(self, m_start_watch):
        paths = ['/test%s' % i for i in range(3)]
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)
        watcher_obj._running = True
        m_watching = watcher_obj._watching = mock.MagicMock()
        m_watching.__contains__.return_value = True

        for path in paths:
            watcher_obj.add(path)

        self.assertEqual(set(paths), watcher_obj._resources)
        m_start_watch.assert_not_called()

    @mock.patch.object(watcher.Watcher, '_stop_watch')
    def test_remove(self, m_stop_watch):
        path = '/test'
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)
        watcher_obj._resources.add(path)

        watcher_obj.remove(path)

        self.assertEqual(set(), watcher_obj._resources)
        m_stop_watch.assert_not_called()

    @mock.patch.object(watcher.Watcher, '_stop_watch')
    def test_remove_watching(self, m_stop_watch):
        path = '/test'
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)
        watcher_obj._resources.add(path)
        m_watching = watcher_obj._watching = mock.MagicMock()
        m_watching.__contains__.return_value = True

        watcher_obj.remove(path)

        self.assertEqual(set(), watcher_obj._resources)
        m_stop_watch.assert_called_once_with(path)

    @mock.patch.object(watcher.Watcher, '_start_watch')
    def test_start(self, m_start_watch):
        paths = ['/test%s' % i for i in range(3)]
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)
        watcher_obj._resources.update(paths)

        watcher_obj.start()

        self.assertTrue(watcher_obj._running)
        m_start_watch.assert_has_calls([mock.call(path) for path in paths],
                                       any_order=True)

    @mock.patch.object(watcher.Watcher, '_start_watch')
    def test_start_already_watching(self, m_start_watch):
        paths = ['/test%s' % i for i in range(3)]
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)
        watcher_obj._resources.update(paths)
        m_watching = watcher_obj._watching = mock.MagicMock()
        m_watching.__iter__.return_value = paths

        watcher_obj.start()

        self.assertTrue(watcher_obj._running)
        m_start_watch.assert_not_called()

    @mock.patch.object(watcher.Watcher, '_stop_watch')
    def test_stop(self, m_stop_watch):
        paths = ['/test%s' % i for i in range(3)]
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)
        watcher_obj._resources.update(paths)

        watcher_obj.stop()

        self.assertFalse(watcher_obj._running)
        m_stop_watch.assert_not_called()

    @mock.patch.object(watcher.Watcher, '_stop_watch')
    def test_stop_watching(self, m_stop_watch):
        paths = ['/test%s' % i for i in range(3)]
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)
        watcher_obj._resources.update(paths)
        m_watching = watcher_obj._watching = mock.MagicMock()
        m_watching.__iter__.return_value = paths

        watcher_obj.stop()

        self.assertFalse(watcher_obj._running)
        m_stop_watch.assert_has_calls([mock.call(path) for path in paths],
                                      any_order=True)

    @mock.patch.object(watcher.Watcher, '_watch')
    def test_start_watch(self, m_watch):
        path = '/test'
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler)

        watcher_obj._start_watch(path)

        m_watch.assert_called_once_with(path)
        self.assertTrue(watcher_obj._idle.get(path))
        self.assertIn(path, watcher_obj._watching)

    def test_start_watch_threaded(self):
        path = '/test'
        m_tg = mock.Mock()
        m_tg.add_thread.return_value = mock.sentinel.watch_thread
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler, m_tg)

        watcher_obj._start_watch(path)

        m_tg.add_thread.assert_called_once_with(watcher_obj._watch, path)
        self.assertTrue(watcher_obj._idle.get(path))
        self.assertEqual(mock.sentinel.watch_thread,
                         watcher_obj._watching.get(path))

    def test_stop_watch_threaded(self):
        path = '/test'
        m_tg = mock.Mock()
        m_th = mock.Mock()
        m_tt = mock.Mock()
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler, m_tg)
        watcher_obj._idle[path] = True
        watcher_obj._watching[path] = m_th
        watcher_obj._timers[path] = m_tt

        watcher_obj._stop_watch(path)

        m_tt.stop.assert_called()
        m_th.stop.assert_called()

    def test_stop_watch_idle(self):
        path = '/test'
        m_tg = mock.Mock()
        m_th = mock.Mock()
        m_handler = mock.Mock()
        watcher_obj = watcher.Watcher(m_handler, m_tg)
        watcher_obj._idle[path] = False
        watcher_obj._watching[path] = m_th

        watcher_obj._stop_watch(path)

        m_th.kill.assert_not_called()

    def _test_watch_mock_events(self, watcher_obj, events):
        def client_watch(client_path):
            for e in events:
                self.assertTrue(watcher_obj._idle[client_path])
                yield e
                self.assertTrue(watcher_obj._idle[client_path])
        self.client.watch.side_effect = client_watch

    @staticmethod
    def _test_watch_create_watcher(path, handler, timeout=0):
        watcher_obj = watcher.Watcher(handler, timeout=timeout)
        watcher_obj._running = True
        watcher_obj._resources.add(path)
        watcher_obj._idle[path] = True
        watcher_obj._watching[path] = None
        return watcher_obj

    @mock.patch('sys.exit')
    def test_watch(self, m_sys_exit):
        path = '/test'
        events = [{'e': i} for i in range(3)]

        def handler(event):
            self.assertFalse(watcher_obj._idle[path])

        m_handler = mock.Mock()
        m_handler.side_effect = handler
        watcher_obj = self._test_watch_create_watcher(path, m_handler)
        self._test_watch_mock_events(watcher_obj, events)

        watcher_obj._watch(path)

        self.assertEqual(0, watcher_obj._timeout)
        m_handler.assert_has_calls([mock.call(e) for e in events])
        # After all events have been "handled", since there is only
        # one handler, we'll gracefully exit
        m_sys_exit.assert_called_once_with(1)

    @mock.patch('sys.exit')
    def test_watch_stopped(self, m_sys_exit):
        path = '/test'
        events = [{'e': i} for i in range(3)]

        def handler(event):
            self.assertFalse(watcher_obj._idle[path])
            watcher_obj._running = False

        m_handler = mock.Mock()
        m_handler.side_effect = handler
        watcher_obj = self._test_watch_create_watcher(path, m_handler)
        self._test_watch_mock_events(watcher_obj, events)

        watcher_obj._watch(path)

        m_handler.assert_called_once_with(events[0])
        self.assertNotIn(path, watcher_obj._idle)
        self.assertNotIn(path, watcher_obj._watching)
        m_sys_exit.assert_called_once_with(1)

    @mock.patch('sys.exit')
    def test_watch_removed(self, m_sys_exit):
        path = '/test'
        events = [{'e': i} for i in range(3)]

        def handler(event):
            self.assertFalse(watcher_obj._idle[path])
            watcher_obj._resources.remove(path)

        m_handler = mock.Mock()
        m_handler.side_effect = handler
        watcher_obj = self._test_watch_create_watcher(path, m_handler)
        self._test_watch_mock_events(watcher_obj, events)

        watcher_obj._watch(path)

        m_handler.assert_called_once_with(events[0])
        self.assertNotIn(path, watcher_obj._idle)
        self.assertNotIn(path, watcher_obj._watching)
        m_sys_exit.assert_called_once_with(1)

    @mock.patch('sys.exit')
    def test_watch_interrupted(self, m_sys_exit):
        path = '/test'
        events = [{'e': i} for i in range(3)]

        def handler(event):
            self.assertFalse(watcher_obj._idle[path])
            raise greenlet.GreenletExit()

        m_handler = mock.Mock()
        m_handler.side_effect = handler
        watcher_obj = self._test_watch_create_watcher(path, m_handler)
        self._test_watch_mock_events(watcher_obj, events)

        self.assertRaises(greenlet.GreenletExit, watcher_obj._watch, path)

        m_handler.assert_called_once_with(events[0])
        self.assertNotIn(path, watcher_obj._idle)
        self.assertNotIn(path, watcher_obj._watching)
        m_sys_exit.assert_called_once_with(1)

    @mock.patch('sys.exit')
    def test_watch_client_request_failed(self, m_sys_exit):
        path = '/test'
        m_handler = mock.Mock()
        watcher_obj = self._test_watch_create_watcher(path, m_handler)
        watcher_obj._watch(path)
        self.client.watch.side_effect = exceptions.ChunkedEncodingError(
            "Connection Broken")

        self.client.watch.assert_called_once()
        self.assertFalse(watcher_obj._alive)
        m_sys_exit.assert_called_once_with(1)

    @mock.patch('sys.exit')
    def test_watch_retry(self, m_sys_exit):
        path = '/test'
        events = [{'e': i} for i in range(3)]
        side_effects = [exceptions.ChunkedEncodingError("Connection Broken")]
        side_effects.extend(None for _ in events)

        m_handler = mock.Mock()
        m_handler.side_effect = side_effects
        watcher_obj = self._test_watch_create_watcher(path, m_handler, 10)
        self._test_watch_mock_events(watcher_obj, events)

        watcher_obj._watch(path)

        m_handler.assert_has_calls([mock.call(e) for e in events])
        m_sys_exit.assert_called_once_with(1)

    def test_watch_restart(self):
        tg = mock.Mock()
        w = watcher.Watcher(lambda e: None, tg)
        w.add('/test')
        w.start()
        tg.add_thread.assert_called_once_with(mock.ANY, '/test')
        w.stop()
        tg.add_thread = mock.Mock()  # Reset mock.
        w.start()
        tg.add_thread.assert_called_once_with(mock.ANY, '/test')
