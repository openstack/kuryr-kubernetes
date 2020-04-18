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

from kuryr_kubernetes.handlers import logging as h_log
from kuryr_kubernetes.tests import base as test_base


class TestLoggingHandler(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.handlers.logging.LOG')
    def test_no_exception(self, m_log):
        m_handler = mock.Mock()
        handler = h_log.LogExceptions(m_handler)

        handler(mock.sentinel.event)

        m_handler.assert_called_once_with(mock.sentinel.event)
        m_log.exception.assert_not_called()

    @mock.patch('kuryr_kubernetes.handlers.logging.LOG')
    def test_exception(self, m_log):
        m_handler = mock.Mock()
        m_handler.side_effect = ValueError()
        handler = h_log.LogExceptions(m_handler, exceptions=ValueError)

        handler(mock.sentinel.event)

        m_handler.assert_called_once_with(mock.sentinel.event)
        m_log.exception.assert_called_once()

    @mock.patch('kuryr_kubernetes.handlers.logging.LOG')
    def test_exception_default(self, m_log):
        m_handler = mock.Mock()
        m_handler.side_effect = ValueError()
        handler = h_log.LogExceptions(m_handler)

        handler(mock.sentinel.event)

        m_handler.assert_called_once_with(mock.sentinel.event)
        m_log.exception.assert_called_once()

    @mock.patch('kuryr_kubernetes.handlers.logging.LOG')
    def test_raises(self, m_log):
        m_handler = mock.Mock()
        m_handler.side_effect = KeyError()
        handler = h_log.LogExceptions(m_handler, exceptions=ValueError)

        self.assertRaises(KeyError, handler, mock.sentinel.event)

        m_handler.assert_called_once_with(mock.sentinel.event)
        m_log.exception.assert_not_called()
