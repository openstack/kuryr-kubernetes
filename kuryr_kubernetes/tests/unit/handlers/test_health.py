# Copyright 2018 Maysa de Macedo Souza.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from kuryr_kubernetes.handlers import health as h_health
from kuryr_kubernetes.tests import base as test_base
from unittest import mock


class _TestHandler(h_health.HealthHandler):
    def is_alive(self):
        pass


class TestHealthRegister(test_base.TestCase):

    def test_register(self):
        m_component = mock.Mock()
        health_register = h_health.HealthRegister()
        health_register.register(m_component)

        self.assertEqual(health_register.registry, [m_component])


class TestHealthHandler(test_base.TestCase):

    @mock.patch.object(h_health.HealthRegister, 'get_instance')
    def test_init(self, m_health_register):
        cls = h_health.HealthRegister
        m_health_register_obj = mock.Mock(spec=cls)
        m_health_register.return_value = m_health_register_obj

        health_handler = _TestHandler()

        self.assertTrue(health_handler._alive)
        self.assertTrue(health_handler._ready)
        m_health_register_obj.register.assert_called_once_with(health_handler)
        self.assertEqual(m_health_register_obj, health_handler._manager)
