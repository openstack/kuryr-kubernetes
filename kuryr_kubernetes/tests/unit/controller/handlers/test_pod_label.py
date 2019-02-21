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

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.handlers import pod_label as p_label
from kuryr_kubernetes.tests import base as test_base


class TestPodLabelHandler(test_base.TestCase):

    def setUp(self):
        super(TestPodLabelHandler, self).setUp()

        self._project_id = mock.sentinel.project_id
        self._sg_id = mock.sentinel.sg_id

        self._pod_version = mock.sentinel.pod_version
        self._pod_link = mock.sentinel.pod_link
        self._pod = {
            'metadata': {'resourceVersion': self._pod_version,
                         'selfLink': self._pod_link,
                         'namespace': 'default'},
            'status': {'phase': k_const.K8S_POD_STATUS_PENDING},
            'spec': {'hostNetwork': False,
                     'nodeName': 'hostname'}
        }
        self._handler = mock.MagicMock(spec=p_label.PodLabelHandler)
        self._handler._drv_project = mock.Mock(spec=drivers.PodProjectDriver)
        self._handler._drv_sg = mock.Mock(spec=drivers.PodSecurityGroupsDriver)
        self._handler._drv_vif_pool = mock.MagicMock(
            spec=drivers.VIFPoolDriver)

        self._get_project = self._handler._drv_project.get_project
        self._get_security_groups = self._handler._drv_sg.get_security_groups
        self._set_vif_driver = self._handler._drv_vif_pool.set_vif_driver
        self._get_pod_labels = self._handler._get_pod_labels
        self._set_pod_labels = self._handler._set_pod_labels
        self._has_pod_state = self._handler._has_pod_state
        self._update_vif_sgs = self._handler._drv_vif_pool.update_vif_sgs

        self._get_project.return_value = self._project_id
        self._get_security_groups.return_value = [self._sg_id]

    @mock.patch.object(drivers.VIFPoolDriver, 'get_instance')
    @mock.patch.object(drivers.PodSecurityGroupsDriver, 'get_instance')
    @mock.patch.object(drivers.PodProjectDriver, 'get_instance')
    @mock.patch.object(drivers.LBaaSDriver, 'get_instance')
    def test_init(self, m_get_lbaas_driver, m_get_project_driver,
                  m_get_sg_driver, m_get_vif_pool_driver):
        project_driver = mock.sentinel.project_driver
        sg_driver = mock.sentinel.sg_driver
        lbaas_driver = mock.sentinel.lbaas_driver
        vif_pool_driver = mock.Mock(spec=drivers.VIFPoolDriver)
        m_get_lbaas_driver.return_value = lbaas_driver
        m_get_project_driver.return_value = project_driver
        m_get_sg_driver.return_value = sg_driver
        m_get_vif_pool_driver.return_value = vif_pool_driver

        handler = p_label.PodLabelHandler()

        self.assertEqual(lbaas_driver, handler._drv_lbaas)
        self.assertEqual(project_driver, handler._drv_project)
        self.assertEqual(sg_driver, handler._drv_sg)
        self.assertEqual(vif_pool_driver, handler._drv_vif_pool)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_services')
    def test_on_present(self,  m_get_services):
        m_get_services.return_value = {"items": []}
        self._has_pod_state.return_value = True
        self._get_pod_labels.return_value = {'test1': 'test'}

        p_label.PodLabelHandler.on_present(self._handler, self._pod)

        self._has_pod_state.assert_called_once_with(self._pod)
        self._get_pod_labels.assert_called_once_with(self._pod)
        self._get_project.assert_called_once()
        self._get_security_groups.assert_called_once()
        self._update_vif_sgs.assert_called_once_with(self._pod, [self._sg_id])
        self._set_pod_labels.assert_called_once_with(self._pod, None)

    def test_on_present_no_state(self):
        self._has_pod_state.return_value = False

        resp = p_label.PodLabelHandler.on_present(self._handler, self._pod)

        self.assertIsNone(resp)
        self._has_pod_state.assert_called_once_with(self._pod)
        self._get_pod_labels.assert_not_called()
        self._set_pod_labels.assert_not_called()

    def test_on_present_no_labels(self):
        self._has_pod_state.return_value = True
        self._get_pod_labels.return_value = None

        p_label.PodLabelHandler.on_present(self._handler, self._pod)

        self._has_pod_state.assert_called_once_with(self._pod)
        self._get_pod_labels.assert_called_once_with(self._pod)
        self._set_pod_labels.assert_not_called()

    def test_on_present_no_changes(self):
        self._has_pod_state.return_value = True
        pod_with_label = self._pod.copy()
        pod_with_label['metadata']['labels'] = {'test1': 'test'}
        self._get_pod_labels.return_value = {'test1': 'test'}

        p_label.PodLabelHandler.on_present(self._handler, pod_with_label)

        self._has_pod_state.assert_called_once_with(pod_with_label)
        self._get_pod_labels.assert_called_once_with(pod_with_label)
        self._set_pod_labels.assert_not_called()
