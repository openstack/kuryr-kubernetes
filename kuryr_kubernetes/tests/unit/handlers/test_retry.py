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

import fixtures
import time

from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import retry as h_retry
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


class _EX1(Exception):
    pass


class _EX11(_EX1):
    pass


class _EX2(Exception):
    pass


class TestRetryHandler(test_base.TestCase):

    def setUp(self):
        super(TestRetryHandler, self).setUp()

        self.now = time.time()
        f_time = self.useFixture(fixtures.MockPatch('time.time'))
        f_time.mock.return_value = self.now

        self.k8s = self.useFixture(k_fix.MockK8sClient()).client
        f_k8s = self.useFixture(fixtures.MockPatch(
            'kuryr_kubernetes.clients.get_kubernetes_client'))
        f_k8s.mock.return_value = self.k8s

    @mock.patch('time.sleep')
    def test_should_not_sleep(self, m_sleep):
        deadline = self.now - 1
        retry = h_retry.Retry(mock.Mock())

        ret = retry._sleep(deadline, 1, _EX1())

        self.assertFalse(ret)
        m_sleep.assert_not_called()

    def _test_should_sleep(self, seconds_left, slept):
        attempt = 2
        timeout = 20
        interval = 3
        deadline = self.now + seconds_left
        retry = h_retry.Retry(mock.Mock(), timeout=timeout, interval=interval)

        with mock.patch('random.randint') as m_randint, \
                mock.patch('time.sleep') as m_sleep:
            m_randint.return_value = 0  # Assume 0 as jitter

            ret = retry._sleep(deadline, attempt, _EX2())

            self.assertEqual(slept, ret)
            m_sleep.assert_called_once_with(slept)

    def test_should_sleep(self):
        self._test_should_sleep(20, 12)

    def test_should_sleep_last(self):
        self._test_should_sleep(5, 5)

    def test_should_sleep_last_capped(self):
        self._test_should_sleep(2, 3)

    @mock.patch('itertools.count')
    @mock.patch.object(h_retry.Retry, '_sleep')
    def test_call(self, m_sleep, m_count):
        m_handler = mock.Mock()
        m_count.return_value = list(range(1, 5))
        retry = h_retry.Retry(m_handler)
        event = {'type': 'DELETED'}

        retry(event)

        m_handler.assert_called_once_with(event, retry_info=mock.ANY)
        m_sleep.assert_not_called()

    @mock.patch('itertools.count')
    @mock.patch.object(h_retry.Retry, '_sleep')
    def test_call_outdated_event(self, m_sleep, m_count):
        m_handler = mock.Mock()
        m_count.return_value = list(range(1, 5))
        self_link = '/api/v1/namespaces/ns1/services/srv1'
        obj = {'apiVersion': 'v1',
               'kind': 'Service',
               'metadata': {'name': 'srv1',
                            'namespace': 'ns1'}}
        event = {'type': 'MODIFIED', 'object': obj}
        self.k8s.get.side_effect = exceptions.K8sResourceNotFound(obj)

        retry = h_retry.Retry(m_handler)
        retry(event)

        self.k8s.get.assert_called_once_with(self_link)
        m_handler.assert_not_called()
        m_sleep.assert_not_called()

    @mock.patch('itertools.count')
    @mock.patch.object(h_retry.Retry, '_sleep')
    def test_call_retry(self, m_sleep, m_count):
        attempts = 3
        timeout = 10
        deadline = self.now + timeout
        failures = [_EX1()] * (attempts - 1)
        event = {'type': 'DELETED'}
        m_handler = mock.Mock()
        m_handler.side_effect = failures + [None]
        m_sleep.return_value = 1
        m_count.return_value = list(range(1, 5))
        retry = h_retry.Retry(m_handler, timeout=timeout, exceptions=_EX1)

        retry(event)

        m_handler.assert_has_calls([mock.call(
            event, retry_info=mock.ANY)] * attempts)
        m_sleep.assert_has_calls([
            mock.call(deadline, i + 1, failures[i])
            for i in range(len(failures))])

    @mock.patch('itertools.count')
    @mock.patch.object(h_retry.Retry, '_sleep')
    def test_call_retry_raises(self, m_sleep, m_count):
        attempts = 3
        timeout = 10
        deadline = self.now + timeout
        failures = [_EX1(), _EX1(), _EX11()]
        event = {'type': 'DELETED'}
        m_handler = mock.Mock()
        m_handler.side_effect = failures
        m_sleep.side_effect = [1] * (attempts - 1) + [0]
        m_count.return_value = list(range(1, 5))
        retry = h_retry.Retry(m_handler, timeout=timeout, exceptions=_EX1)

        self.assertRaises(_EX11, retry, event)

        m_handler.assert_has_calls([mock.call(
            event, retry_info=mock.ANY)] * attempts)
        m_sleep.assert_has_calls([
            mock.call(deadline, i + 1, failures[i])
            for i in range(len(failures))])
