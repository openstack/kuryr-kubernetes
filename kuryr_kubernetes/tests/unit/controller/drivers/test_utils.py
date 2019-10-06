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
import mock

from kuryr_kubernetes.controller.drivers import utils

from kuryr_kubernetes import constants
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


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
