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

from kuryr_kubernetes.controller.handlers import pipeline as h_pipeline
from kuryr_kubernetes.handlers import dispatch as h_dis
from kuryr_kubernetes.handlers import k8s_base as h_k8s
from kuryr_kubernetes.tests import base as test_base


class TestControllerPipeline(test_base.TestCase):
    @mock.patch('kuryr_kubernetes.handlers.logging.LogExceptions')
    @mock.patch('kuryr_kubernetes.handlers.retry.Retry')
    def test_wrap_consumer(self, m_retry_type, m_logging_type):
        consumer = mock.sentinel.consumer
        retry_handler = mock.sentinel.retry_handler
        logging_handler = mock.sentinel.logging_handler
        m_retry_type.return_value = retry_handler
        m_logging_type.return_value = logging_handler
        thread_group = mock.sentinel.thread_group

        with mock.patch.object(h_dis.EventPipeline, '__init__'):
            pipeline = h_pipeline.ControllerPipeline(thread_group)
            ret = pipeline._wrap_consumer(consumer)

        self.assertEqual(logging_handler, ret)
        m_logging_type.assert_called_with(retry_handler,
                                          ignore_exceptions=mock.ANY)
        m_retry_type.assert_called_with(consumer, exceptions=mock.ANY)

    @mock.patch('kuryr_kubernetes.handlers.logging.LogExceptions')
    @mock.patch('kuryr_kubernetes.handlers.asynchronous.Async')
    def test_wrap_dispatcher(self, m_async_type, m_logging_type):
        dispatcher = mock.sentinel.dispatcher
        async_handler = mock.sentinel.async_handler
        logging_handler = mock.sentinel.logging_handler
        m_async_type.return_value = async_handler
        m_logging_type.return_value = logging_handler
        thread_group = mock.sentinel.thread_group

        with mock.patch.object(h_dis.EventPipeline, '__init__'):
            pipeline = h_pipeline.ControllerPipeline(thread_group)
            ret = pipeline._wrap_dispatcher(dispatcher)

        self.assertEqual(logging_handler, ret)
        m_logging_type.assert_called_with(async_handler)
        m_async_type.assert_called_with(dispatcher, thread_group,
                                        h_k8s.object_uid, h_k8s.object_info)
