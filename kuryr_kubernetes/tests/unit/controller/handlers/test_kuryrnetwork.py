# Copyright 2020 Red Hat, Inc.
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

from openstack.network.v2 import network as os_network
from openstack.network.v2 import subnet as os_subnet
from oslo_config import cfg as oslo_cfg

from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import namespace_subnet as subnet_drv
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes.controller.drivers import vif_pool
from kuryr_kubernetes.controller.handlers import kuryrnetwork
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


@mock.patch('kuryr_kubernetes.controller.drivers.utils.'
            'is_network_policy_enabled', mock.Mock(return_value=True))
class TestKuryrNetworkHandler(test_base.TestCase):

    def setUp(self):
        super(TestKuryrNetworkHandler, self).setUp()

        self._project_id = mock.sentinel.project_id
        self._subnets = mock.sentinel.subnets
        self._kuryrnet_crd = {
            'metadata': {
                'name': 'ns-test-namespace',
            },
            'spec': {
                'nsName': 'test-namespace',
                'projectId': 'test-project',
                'nsLabels': {},
            },
            'status': {
                }
            }

        self._handler = mock.MagicMock(
            spec=kuryrnetwork.KuryrNetworkHandler)
        self._handler._drv_project = mock.Mock(spec=drivers.PodProjectDriver)
        # NOTE(ltomasbo): The KuryrNetwork handler is associated to the usage
        # of namespace subnet driver,
        self._handler._drv_subnets = mock.Mock(
            spec=subnet_drv.NamespacePodSubnetDriver)
        self._handler._drv_sg = mock.Mock(spec=drivers.PodSecurityGroupsDriver)
        self._handler._drv_vif_pool = mock.MagicMock(
            spec=vif_pool.MultiVIFPool)
        self._handler.k8s = self.useFixture(k_fix.MockK8sClient()).client

        self._get_project = self._handler._drv_project.get_project
        self._set_vif_driver = self._handler._drv_vif_pool.set_vif_driver
        self._create_network = self._handler._drv_subnets.create_network
        self._create_subnet = self._handler._drv_subnets.create_subnet
        self._delete_namespace_subnet = (
            self._handler._drv_subnets.delete_namespace_subnet)
        self._add_subnet_to_router = (
            self._handler._drv_subnets.add_subnet_to_router)
        self._delete_ns_sg_rules = (
            self._handler._drv_sg.delete_namespace_sg_rules)
        self._update_ns_sg_rules = (
            self._handler._drv_sg.update_namespace_sg_rules)
        self._delete_network_pools = (
            self._handler._drv_vif_pool.delete_network_pools)

        self._get_project.return_value = self._project_id

    @mock.patch.object(drivers.LBaaSDriver, 'get_instance')
    @mock.patch.object(drivers.VIFPoolDriver, 'get_instance')
    @mock.patch.object(drivers.PodSecurityGroupsDriver, 'get_instance')
    @mock.patch.object(drivers.PodSubnetsDriver, 'get_instance')
    @mock.patch.object(drivers.NamespaceProjectDriver, 'get_instance')
    def test_init(self, m_get_project_driver, m_get_subnet_driver,
                  m_get_sg_driver, m_get_vif_pool_driver, m_get_lbaas_driver):
        project_driver = mock.sentinel.project_driver
        subnet_driver = mock.sentinel.subnet_driver
        sg_driver = mock.sentinel.sg_driver
        vif_pool_driver = mock.Mock(spec=vif_pool.MultiVIFPool)
        lbaas_driver = mock.sentinel.lbaas_driver

        m_get_project_driver.return_value = project_driver
        m_get_subnet_driver.return_value = subnet_driver
        m_get_sg_driver.return_value = sg_driver
        m_get_vif_pool_driver.return_value = vif_pool_driver
        m_get_lbaas_driver.return_value = lbaas_driver

        handler = kuryrnetwork.KuryrNetworkHandler()

        self.assertEqual(project_driver, handler._drv_project)
        self.assertEqual(subnet_driver, handler._drv_subnets)
        self.assertEqual(sg_driver, handler._drv_sg)
        self.assertEqual(vif_pool_driver, handler._drv_vif_pool)

    @mock.patch.object(driver_utils, 'get_services')
    @mock.patch.object(driver_utils, 'get_namespace')
    def test_on_present(self, m_get_ns, m_get_svc):
        net_id = mock.sentinel.net_id
        subnet_id = mock.sentinel.subnet_id
        subnet_cidr = mock.sentinel.subnet_cidr
        router_id = mock.sentinel.router_id
        ns = {'metadata': {'uid': 'e28127f4-bc41-450a-97cf-56d9bc76d53e',
                           'name': 'test'}}

        self._create_network.return_value = net_id
        self._create_subnet.return_value = (subnet_id, subnet_cidr)
        self._add_subnet_to_router.return_value = router_id
        m_get_ns.return_value = ns
        m_get_svc.return_value = []

        kuryrnetwork.KuryrNetworkHandler.on_present(self._handler,
                                                    self._kuryrnet_crd)

        self._handler._patch_kuryrnetwork_crd.assert_called()
        self._create_network.assert_called_once_with(
            ns,
            self._kuryrnet_crd['spec']['projectId'])
        self._create_subnet.assert_called_once_with(
            ns,
            self._kuryrnet_crd['spec']['projectId'],
            net_id)
        self._add_subnet_to_router.assert_called_once_with(subnet_id)
        m_get_ns.assert_called_once_with(self._kuryrnet_crd['spec']['nsName'])
        self._update_ns_sg_rules.assert_called_once_with(ns)
        m_get_svc.assert_called_once()
        self._handler._update_services.assert_called_once()
        self.assertEqual(self._handler.k8s.add_event.call_count, 4)

    @mock.patch.object(driver_utils, 'get_services')
    @mock.patch.object(driver_utils, 'get_namespace')
    def test_on_present_no_sg_enforce(self, m_get_ns, m_get_svc):
        net_id = mock.sentinel.net_id
        subnet_id = mock.sentinel.subnet_id
        subnet_cidr = mock.sentinel.subnet_cidr
        router_id = mock.sentinel.router_id
        ns = {'metadata': {'uid': '843645f7-d255-4fd8-86fb-09140d57c392',
                           'name': 'test'}}

        self._create_network.return_value = net_id
        self._create_subnet.return_value = (subnet_id, subnet_cidr)
        self._add_subnet_to_router.return_value = router_id
        m_get_ns.return_value = ns

        oslo_cfg.CONF.set_override('enforce_sg_rules',
                                   False,
                                   group='octavia_defaults')
        self.addCleanup(oslo_cfg.CONF.clear_override, 'enforce_sg_rules',
                        group='octavia_defaults')

        kuryrnetwork.KuryrNetworkHandler.on_present(self._handler,
                                                    self._kuryrnet_crd)

        self._handler._patch_kuryrnetwork_crd.assert_called()
        self._create_network.assert_called_once_with(
            ns,
            self._kuryrnet_crd['spec']['projectId'])
        self._create_subnet.assert_called_once_with(
            ns,
            self._kuryrnet_crd['spec']['projectId'],
            net_id)
        self._add_subnet_to_router.assert_called_once_with(subnet_id)
        m_get_ns.assert_called_once_with(self._kuryrnet_crd['spec']['nsName'])
        self._update_ns_sg_rules.assert_called_once_with(ns)
        m_get_svc.assert_not_called()
        self._handler._update_services.assert_not_called()
        self.assertEqual(self._handler.k8s.add_event.call_count, 4)

    @mock.patch.object(driver_utils, 'get_namespace')
    def test_on_present_existing(self, m_get_ns):
        net_id = mock.sentinel.net_id
        subnet_id = mock.sentinel.subnet_id
        subnet_cidr = mock.sentinel.subnet_cidr
        router_id = mock.sentinel.router_id

        kns_crd = self._kuryrnet_crd.copy()
        kns_crd['status'] = {
            'netId': net_id,
            'subnetId': subnet_id,
            'subnetCIDR': subnet_cidr,
            'routerId': router_id}

        kuryrnetwork.KuryrNetworkHandler.on_present(self._handler, kns_crd)

        self._handler._patch_kuryrnetwork_crd.assert_not_called()
        self._create_network.assert_not_called()
        self._create_subnet.assert_not_called()
        self._add_subnet_to_router.assert_not_called()
        self._handler.k8s.add_event.assert_not_called()

    @mock.patch.object(driver_utils, 'get_services')
    def test_on_finalize(self, m_get_svc):
        net_id = mock.sentinel.net_id
        kns_crd = self._kuryrnet_crd.copy()
        kns_crd['status'] = {'netId': net_id}
        crd_selector = mock.sentinel.crd_selector

        self._delete_ns_sg_rules.return_value = [crd_selector]
        m_get_svc.return_value = []

        kuryrnetwork.KuryrNetworkHandler.on_finalize(self._handler, kns_crd)

        self._delete_network_pools.assert_called_once_with(net_id)
        self._delete_namespace_subnet.assert_called_once_with(kns_crd)
        self._delete_ns_sg_rules.assert_called_once()
        m_get_svc.assert_called_once()
        self._handler._update_services.assert_called_once()
        self._handler.k8s.remove_finalizer.assert_called_once()
        self._handler.k8s.add_event.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    @mock.patch.object(driver_utils, 'get_services')
    def test_on_finalize_no_network(self, m_get_svc, m_get_net_client):
        crd_selector = mock.sentinel.crd_selector
        self._delete_ns_sg_rules.return_value = [crd_selector]
        m_get_svc.return_value = []
        net_mock = mock.MagicMock()
        net_mock.return_value = []
        m_get_net_client.return_value = net_mock
        self._handler.k8s.get.return_value = (
            {'metadata': {'name': 'test-namespace',
                          'uid': 'e237acaf-ea5f-4d96-b604-292268a938a1'}})

        kuryrnetwork.KuryrNetworkHandler.on_finalize(self._handler,
                                                     self._kuryrnet_crd)

        self._delete_network_pools.assert_not_called()
        self._delete_namespace_subnet.assert_not_called()
        self._delete_ns_sg_rules.assert_called_once()
        m_get_svc.assert_called_once()
        self._handler._update_services.assert_called_once()
        self._handler.k8s.remove_finalizer.assert_called_once()
        self._handler.k8s.add_event.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    @mock.patch.object(driver_utils, 'get_services')
    def test_on_finalize_no_network_in_kn_no_desc(self, m_get_svc,
                                                  m_get_net_client):
        crd_selector = mock.sentinel.crd_selector
        self._delete_ns_sg_rules.return_value = [crd_selector]
        m_get_svc.return_value = []
        net_mock = mock.MagicMock()
        net_id = '1612ffb1-ff7d-4590-bd9c-95aeb043705a'
        net_mock.networks.return_value = [
            os_network.Network(id=net_id, description=''),
        ]
        m_get_net_client.return_value = net_mock
        self._handler.k8s.get.return_value = (
            {'metadata': {'name': 'test-namespace', 'uid': net_id}})

        kuryrnetwork.KuryrNetworkHandler.on_finalize(self._handler,
                                                     self._kuryrnet_crd)

        self._delete_network_pools.assert_not_called()
        self._delete_ns_sg_rules.assert_called_once()
        m_get_svc.assert_called_once()
        self._handler._update_services.assert_called_once()
        self._handler.k8s.remove_finalizer.assert_called_once()
        self._handler.k8s.add_event.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    @mock.patch.object(driver_utils, 'get_services')
    def test_on_finalize_no_network_in_kn_with_subnet(self, m_get_svc,
                                                      m_get_net_client):
        crd_selector = mock.sentinel.crd_selector
        self._delete_ns_sg_rules.return_value = [crd_selector]
        m_get_svc.return_value = []
        net_id = 'db0b2c83-dae3-47ff-b4b0-9a19b7c15589'
        ns_id = '0b6d6f0b-4e44-4a1b-a711-71ab6c79bee8'
        subnet_id = 'a595fc4b-6885-48ff-b90c-d3f7aefd6d1a'
        net_mock = mock.MagicMock()
        net_mock.networks.return_value = [
            os_network.Network(id=net_id, description=ns_id),
        ]
        net_mock.subnets.return_value = [os_subnet.Subnet(id=subnet_id)]
        m_get_net_client.return_value = net_mock
        self._handler.k8s.get.return_value = (
            {'metadata': {'name': 'test-namespace', 'uid': ns_id}})

        kuryrnetwork.KuryrNetworkHandler.on_finalize(self._handler,
                                                     self._kuryrnet_crd)

        self._delete_network_pools.assert_called_once()
        self._delete_ns_sg_rules.assert_called_once()
        m_get_svc.assert_called_once()
        self._handler._update_services.assert_called_once()
        self._handler.k8s.remove_finalizer.assert_called_once()
        self._handler.k8s.add_event.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_network_client')
    @mock.patch.object(driver_utils, 'get_services')
    def test_on_finalize_no_network_in_kn_with_no_ns_match(self, m_get_svc,
                                                           m_get_net_client):
        crd_selector = mock.sentinel.crd_selector
        self._delete_ns_sg_rules.return_value = [crd_selector]
        m_get_svc.return_value = []
        net_id = 'db0b2c83-dae3-47ff-b4b0-9a19b7c15589'
        ns_id = '0b6d6f0b-4e44-4a1b-a711-71ab6c79bee8'
        subnet_id = 'a595fc4b-6885-48ff-b90c-d3f7aefd6d1a'
        net_mock = mock.MagicMock()
        net_mock.networks.return_value = [
            os_network.Network(id=net_id, description=ns_id),
        ]
        net_mock.subnets.return_value = [os_subnet.Subnet(id=subnet_id)]
        m_get_net_client.return_value = net_mock
        self._handler.k8s.get.return_value = (
            {'metadata': {'name': 'test-namespace', 'uid': net_id}})

        kuryrnetwork.KuryrNetworkHandler.on_finalize(self._handler,
                                                     self._kuryrnet_crd)

        self._delete_network_pools.assert_not_called()
        m_get_svc.assert_called_once()
        self._handler._update_services.assert_called_once()
        self._handler.k8s.remove_finalizer.assert_called_once()
        self._handler.k8s.add_event.assert_not_called()

    @mock.patch.object(driver_utils, 'get_services')
    def test_on_finalize_no_sg_enforce(self, m_get_svc):
        net_id = mock.sentinel.net_id
        kns_crd = self._kuryrnet_crd.copy()
        kns_crd['status'] = {'netId': net_id}
        crd_selector = mock.sentinel.crd_selector

        self._delete_ns_sg_rules.return_value = [crd_selector]
        m_get_svc.return_value = []
        oslo_cfg.CONF.set_override('enforce_sg_rules',
                                   False,
                                   group='octavia_defaults')
        self.addCleanup(oslo_cfg.CONF.clear_override, 'enforce_sg_rules',
                        group='octavia_defaults')

        kuryrnetwork.KuryrNetworkHandler.on_finalize(
            self._handler, kns_crd)

        self._delete_network_pools.assert_called_once_with(net_id)
        self._delete_namespace_subnet.assert_called_once_with(kns_crd)
        self._delete_ns_sg_rules.assert_called_once()
        m_get_svc.assert_not_called()
        self._handler._update_services.assert_not_called()
        self._handler.k8s.remove_finalizer.assert_called_once()
        self._handler.k8s.add_event.assert_not_called()

    def test_on_finalize_finalizer_delete_ns_subnet_exception(self):
        net_id = mock.sentinel.net_id
        kns_crd = self._kuryrnet_crd.copy()
        kns_crd['status'] = {'netId': net_id}
        crd_selector = mock.sentinel.crd_selector

        self._delete_ns_sg_rules.return_value = [crd_selector]
        self._delete_namespace_subnet.side_effect = (k_exc.
                                                     ResourceNotReady(kns_crd))

        self.assertRaises(k_exc.ResourceNotReady,
                          kuryrnetwork.KuryrNetworkHandler.on_finalize,
                          self._handler, kns_crd)

        self._delete_network_pools.assert_called_once_with(net_id)
        self._delete_namespace_subnet.assert_called_once_with(kns_crd)

    @mock.patch.object(driver_utils, 'get_services')
    def test_on_finalize_finalizer_exception(self, m_get_svc):
        net_id = mock.sentinel.net_id
        kns_crd = self._kuryrnet_crd.copy()
        kns_crd['status'] = {'netId': net_id}
        crd_selector = mock.sentinel.crd_selector

        self._delete_ns_sg_rules.return_value = [crd_selector]
        m_get_svc.return_value = []
        k8s = self._handler.k8s
        k8s.remove_finalizer.side_effect = k_exc.K8sClientException

        self.assertRaises(
            k_exc.K8sClientException,
            kuryrnetwork.KuryrNetworkHandler.on_finalize,
            self._handler, kns_crd)

        self._delete_network_pools.assert_called_once_with(net_id)
        self._delete_namespace_subnet.assert_called_once_with(kns_crd)
        self._delete_ns_sg_rules.assert_called_once()
        m_get_svc.assert_called_once()
        self._handler._update_services.assert_called_once()
        k8s.remove_finalizer.assert_called_once()
