# Copyright 2018 Red Hat, Inc.
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

from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.handlers import policy
from kuryr_kubernetes.tests import base as test_base


class TestPolicyHandler(test_base.TestCase):

    def setUp(self):
        super(TestPolicyHandler, self).setUp()

        self._project_id = mock.sentinel.project_id
        self._policy_name = 'np-test'
        self._policy_uid = mock.sentinel.policy_uid
        self._policy_link = mock.sentinel.policy_link

        self._policy = {
            u'apiVersion': u'networking.k8s.io/v1',
            u'kind': u'NetworkPolicy',
            u'metadata': {
                u'name': self._policy_name,
                u'resourceVersion': u'2259309',
                u'generation': 1,
                u'creationTimestamp': u'2018-09-18T14:09:51Z',
                u'namespace': u'default',
                u'annotations': {},
                u'selfLink': self._policy_link,
                u'uid': self._policy_uid
            },
            u'spec': {
                u'egress': [{u'ports':
                             [{u'port': 5978, u'protocol': u'TCP'}]}],
                u'ingress': [{u'ports':
                              [{u'port': 6379, u'protocol': u'TCP'}]}],
                u'policyTypes': [u'Ingress', u'Egress']
            }
        }

        self._handler = mock.MagicMock(spec=policy.NetworkPolicyHandler)

        self._handler._drv_project = mock.Mock(
            spec=drivers.NetworkPolicyProjectDriver)
        self._handler._drv_policy = mock.MagicMock(
            spec=drivers.NetworkPolicyDriver)

        self._get_project = self._handler._drv_project.get_project
        self._get_project.return_value = self._project_id

    @mock.patch.object(drivers.NetworkPolicyDriver, 'get_instance')
    @mock.patch.object(drivers.NetworkPolicyProjectDriver, 'get_instance')
    def test_init(self, m_get_project_driver, m_get_policy_driver):
        handler = policy.NetworkPolicyHandler()

        m_get_project_driver.assert_called_once()
        m_get_policy_driver.assert_called_once()

        self.assertEqual(m_get_project_driver.return_value,
                         handler._drv_project)
        self.assertEqual(m_get_policy_driver.return_value, handler._drv_policy)

    def test_on_present(self):
        policy.NetworkPolicyHandler.on_present(self._handler, self._policy)
        ensure_nw_policy = self._handler._drv_policy.ensure_network_policy
        ensure_nw_policy.assert_called_once_with(self._policy,
                                                 self._project_id)
        policy.NetworkPolicyHandler.on_present(self._handler, self._policy)

    def test_on_deleted(self):
        policy.NetworkPolicyHandler.on_deleted(self._handler, self._policy)
        release_nw_policy = self._handler._drv_policy.release_network_policy
        release_nw_policy.assert_called_once_with(self._policy,
                                                  self._project_id)
        policy.NetworkPolicyHandler.on_present(self._handler, self._policy)
