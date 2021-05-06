# Copyright 2019 Red Hat, Inc.
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
from unittest import mock

from oslo_config import cfg

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import utils
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix

CONF = cfg.CONF


class TestUtils(test_base.TestCase):

    def test_get_namespace_not_found(self):
        namespace_name = mock.sentinel.namespace_name
        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        kubernetes.get.side_effect = exceptions.K8sResourceNotFound(
            mock.sentinel.resource)

        resp = utils.get_namespace(namespace_name)

        self.assertIsNone(resp)
        kubernetes.get.assert_called_once_with('{}/namespaces/{}'.format(
            constants.K8S_API_BASE, namespace_name))

    def test_get_network_id(self):
        id_a = mock.sentinel.id_a
        net1 = mock.Mock()
        net1.id = id_a
        net2 = mock.Mock()
        net2.id = id_a
        subnets = {1: net1, 2: net2}

        ret = utils.get_network_id(subnets)

        self.assertEqual(ret, id_a)

    def test_get_network_id_invalid(self):
        id_a = mock.sentinel.id_a
        id_b = mock.sentinel.id_b
        net1 = mock.Mock()
        net1.id = id_a
        net2 = mock.Mock()
        net2.id = id_b
        net3 = mock.Mock()
        net3.id = id_a
        subnets = {1: net1, 2: net2, 3: net3}

        self.assertRaises(exceptions.IntegrityError, utils.get_network_id,
                          subnets)

    def test_get_network_id_empty(self):
        self.assertRaises(exceptions.IntegrityError, utils.get_network_id, {})

    def test_match_selector(self):
        self.assertFalse(
            utils.match_selector({'matchLabels': {'app': 'demo'}}, None))
        self.assertFalse(
            utils.match_selector({'matchLabels': {'app': 'demo'}}, {}))
        self.assertFalse(
            utils.match_selector({'matchLabels': {'app': 'demo'}},
                                 {'app': 'foobar'}))
        self.assertTrue(
            utils.match_selector({'matchLabels': {'app': 'demo'}},
                                 {'app': 'demo'}))
        self.assertTrue(
            utils.match_selector({'matchLabels': {'app': 'demo'}},
                                 {'app': 'demo', 'foo': 'bar'}))
        self.assertTrue(
            utils.match_selector({'matchLabels': {'app': 'demo',
                                                  'foo': 'bar'}},
                                 {'app': 'demo', 'foo': 'bar'}))
        self.assertFalse(
            utils.match_selector({'matchLabels': {'app': 'demo',
                                                  'foo': 'bar'}},
                                 {'app': 'demo'}))

    def test_is_network_policy_enabled(self):
        CONF.set_override('enabled_handlers', ['fake_handler'],
                          group='kubernetes')
        CONF.set_override('service_security_groups_driver', 'foo',
                          group='kubernetes')

        self.assertFalse(utils.is_network_policy_enabled())

        CONF.set_override('enabled_handlers', ['policy'],
                          group='kubernetes')
        CONF.set_override('service_security_groups_driver', 'foo',
                          group='kubernetes')

        self.assertFalse(utils.is_network_policy_enabled())

        CONF.set_override('enabled_handlers', ['policy'],
                          group='kubernetes')
        self.addCleanup(CONF.clear_override, 'enabled_handlers',
                        group='kubernetes')
        CONF.set_override('service_security_groups_driver', 'policy',
                          group='kubernetes')
        self.addCleanup(CONF.clear_override, 'service_security_groups_driver',
                        group='kubernetes')

        self.assertTrue(utils.is_network_policy_enabled())
