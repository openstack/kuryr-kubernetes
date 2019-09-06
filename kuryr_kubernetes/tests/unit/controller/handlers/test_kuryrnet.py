# Copyright 2019, Inc.
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
from kuryr_kubernetes.controller.drivers import namespace_subnet as subnet_drv
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes.controller.drivers import vif_pool
from kuryr_kubernetes.controller.handlers import kuryrnet
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes import utils


class TestKuryrNetHandler(test_base.TestCase):

    def setUp(self):
        super(TestKuryrNetHandler, self).setUp()

        self._project_id = mock.sentinel.project_id
        self._subnets = mock.sentinel.subnets
        self._kuryrnet_crd = {
            'metadata': {
                'name': 'test-namespace',
                'annotations': {
                    'namespaceName': 'test-namespace'
                }},
            'spec': {
                'subnetId': 'test-subnet'
                }
            }

        self._handler = mock.MagicMock(spec=kuryrnet.KuryrNetHandler)
        self._handler._drv_project = mock.Mock(spec=drivers.PodProjectDriver)
        # NOTE(ltomasbo): The KuryrNet handler is associated to the usage of
        # namespace subnet driver,
        self._handler._drv_subnets = mock.Mock(
            spec=subnet_drv.NamespacePodSubnetDriver)
        self._handler._drv_vif_pool = mock.MagicMock(
            spec=vif_pool.MultiVIFPool)

        self._get_project = self._handler._drv_project.get_project
        self._get_namespace_subnet = (
            self._handler._drv_subnets.get_namespace_subnet)
        self._set_vif_driver = self._handler._drv_vif_pool.set_vif_driver
        self._populate_pool = self._handler._drv_vif_pool.populate_pool

        self._get_project.return_value = self._project_id
        self._get_namespace_subnet.return_value = self._subnets

    @mock.patch.object(drivers.VIFPoolDriver, 'get_instance')
    @mock.patch.object(drivers.PodSubnetsDriver, 'get_instance')
    @mock.patch.object(drivers.NamespaceProjectDriver, 'get_instance')
    def test_init(self, m_get_project_driver, m_get_subnet_driver,
                  m_get_vif_pool_driver):
        project_driver = mock.sentinel.project_driver
        subnet_driver = mock.sentinel.subnet_driver
        vif_pool_driver = mock.Mock(spec=vif_pool.MultiVIFPool)

        m_get_project_driver.return_value = project_driver
        m_get_subnet_driver.return_value = subnet_driver
        m_get_vif_pool_driver.return_value = vif_pool_driver

        handler = kuryrnet.KuryrNetHandler()

        self.assertEqual(project_driver, handler._drv_project)
        self.assertEqual(subnet_driver, handler._drv_subnets)
        self.assertEqual(vif_pool_driver, handler._drv_vif_pool)

    @mock.patch.object(driver_utils, 'get_annotations')
    @mock.patch.object(driver_utils, 'get_namespace')
    @mock.patch.object(driver_utils, 'patch_kuryrnet_crd')
    @mock.patch.object(utils, 'get_nodes_ips')
    def test_on_added(self, m_get_nodes_ips, m_patch_kn_crd, m_get_ns,
                      m_get_ann):
        m_get_nodes_ips.return_value = ['node-ip']
        m_get_ns.return_value = mock.sentinel.ns
        m_get_ann.return_value = self._kuryrnet_crd['metadata']['name']

        kuryrnet.KuryrNetHandler.on_added(self._handler, self._kuryrnet_crd)

        self._get_project.assert_called_once()
        self._get_namespace_subnet.assert_called_once_with(
            self._kuryrnet_crd['metadata']['annotations']['namespaceName'],
            self._kuryrnet_crd['spec']['subnetId'])
        self._populate_pool.assert_called_once_with('node-ip',
                                                    self._project_id,
                                                    self._subnets,
                                                    [])
        m_patch_kn_crd.assert_called_once()
