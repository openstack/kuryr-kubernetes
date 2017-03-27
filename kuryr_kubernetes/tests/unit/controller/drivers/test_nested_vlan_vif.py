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

import mock

from kuryr.lib import constants as kl_const
from kuryr.lib import exceptions as kl_exc
from neutronclient.common import exceptions as n_exc
from oslo_config import cfg as oslo_cfg

from kuryr_kubernetes import constants as const
from kuryr_kubernetes.controller.drivers import nested_vlan_vif
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


class TestNestedVlanPodVIFDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif')
    def test_request_vif(self, m_to_vif):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = mock.sentinel.security_groups

        parent_port = mock.sentinel.parent_port
        trunk_id = mock.sentinel.trunk_id
        port_id = mock.sentinel.port_id
        port = mock.MagicMock()
        port.__getitem__.return_value = port_id
        port_request = mock.sentinel.port_request
        vlan_id = mock.sentinel.vlan_id

        vif = mock.Mock()
        vif_plugin = const.K8S_OS_VIF_NOOP_PLUGIN

        m_to_vif.return_value = vif
        m_driver._get_parent_port.return_value = parent_port
        m_driver._get_trunk_id.return_value = trunk_id
        m_driver._get_port_request.return_value = port_request
        m_driver._add_subport.return_value = vlan_id
        neutron.list_ports.return_value = {'ports': [parent_port]}
        neutron.create_port.return_value = {'port': port}

        self.assertEqual(vif, cls.request_vif(m_driver, pod, project_id,
                                              subnets, security_groups))

        m_driver._get_parent_port.assert_called_once_with(neutron, pod)
        m_driver._get_trunk_id.assert_called_once_with(parent_port)
        m_driver._get_port_request.assert_called_once_with(
            pod, project_id, subnets, security_groups)
        neutron.create_port.assert_called_once_with(port_request)
        m_driver._add_subport.assert_called_once_with(neutron,
                                                      trunk_id,
                                                      port_id)
        m_to_vif.assert_called_once_with(vif_plugin, port, subnets)
        self.assertEqual(vif.vlan_id, vlan_id)

    def test_release_vif(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        parent_port = mock.sentinel.parent_port
        trunk_id = mock.sentinel.trunk_id

        m_driver._get_parent_port.return_value = parent_port
        m_driver._get_trunk_id.return_value = trunk_id
        pod = mock.sentinel.pod
        vif = mock.Mock()

        cls.release_vif(m_driver, pod, vif)

        m_driver._get_parent_port.assert_called_once_with(neutron, pod)
        m_driver._get_trunk_id.assert_called_once_with(parent_port)
        m_driver._remove_subport.assert_called_once_with(
            neutron, trunk_id, vif.id)
        neutron.delete_port.assert_called_once_with(vif.id)

    def test_release_vif_not_found(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        parent_port = mock.sentinel.parent_port
        trunk_id = mock.sentinel.trunk_id

        m_driver._get_parent_port.return_value = parent_port
        m_driver._get_trunk_id.return_value = trunk_id
        pod = mock.sentinel.pod
        vlan_id = mock.sentinel.vlan_id
        vif = mock.Mock()
        m_driver._port_vlan_mapping = {vif.id: vlan_id}
        self.assertTrue(vif.id in m_driver._port_vlan_mapping.keys())
        neutron.delete_port.side_effect = n_exc.PortNotFoundClient

        cls.release_vif(m_driver, pod, vif)

        m_driver._get_parent_port.assert_called_once_with(neutron, pod)
        m_driver._get_trunk_id.assert_called_once_with(parent_port)
        m_driver._remove_subport.assert_called_once_with(
            neutron, trunk_id, vif.id)
        neutron.delete_port.assert_called_once_with(vif.id)

    def _test_get_port_request(self, m_to_fips, security_groups):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        port_name = mock.sentinel.port_name
        network_id = mock.sentinel.project_id
        fixed_ips = mock.sentinel.fixed_ips

        m_driver._get_port_name.return_value = port_name
        m_driver._get_network_id.return_value = network_id
        m_to_fips.return_value = fixed_ips

        expected = {'port': {'project_id': project_id,
                             'name': port_name,
                             'network_id': network_id,
                             'fixed_ips': fixed_ips,
                             'device_owner': kl_const.DEVICE_OWNER,
                             'admin_state_up': True}}

        if security_groups:
            expected['port']['security_groups'] = security_groups

        ret = cls._get_port_request(m_driver, pod, project_id, subnets,
                                    security_groups)

        self.assertEqual(expected, ret)
        m_driver._get_port_name.assert_called_once_with(pod)
        m_driver._get_network_id.assert_called_once_with(subnets)
        m_to_fips.assert_called_once_with(subnets)

    @mock.patch('kuryr_kubernetes.os_vif_util.osvif_to_neutron_fixed_ips')
    def test_get_port_request(self, m_to_fips):
        security_groups = mock.sentinel.security_groups
        self._test_get_port_request(m_to_fips, security_groups)

    @mock.patch('kuryr_kubernetes.os_vif_util.osvif_to_neutron_fixed_ips')
    def test_get_port_request_no_sg(self, m_to_fips):
        security_groups = []
        self._test_get_port_request(m_to_fips, security_groups)

    def test_get_trunk_id(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        trunk_id = mock.sentinel.trunk_id
        port = {'trunk_details': {'trunk_id': trunk_id}}

        self.assertEqual(trunk_id, cls._get_trunk_id(m_driver, port))

    def test_get_trunk_id_details_missing(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        trunk_id = mock.sentinel.trunk_id
        port = {'trunk_details_missing': {'trunk_id_missing': trunk_id}}
        self.assertRaises(k_exc.K8sNodeTrunkPortFailure,
            cls._get_trunk_id, m_driver, port)

    def test_get_parent_port(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        node_subnet_id = mock.sentinel.node_subnet_id
        oslo_cfg.CONF.set_override('worker_nodes_subnet',
                                   node_subnet_id,
                                   group='pod_vif_nested')

        node_fixed_ip = mock.sentinel.node_fixed_ip
        pod_status = mock.MagicMock()
        pod_status.__getitem__.return_value = node_fixed_ip

        pod = mock.MagicMock()
        pod.__getitem__.return_value = pod_status

        port = mock.sentinel.port
        ports = {'ports': [port]}
        neutron.list_ports.return_value = ports

        self.assertEqual(port, cls._get_parent_port(m_driver, neutron, pod))
        fixed_ips = ['subnet_id=%s' % str(node_subnet_id),
                     'ip_address=%s' % str(node_fixed_ip)]
        neutron.list_ports.assert_called_once_with(fixed_ips=fixed_ips)

    def test_get_parent_port_subnet_id_not_configured(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        oslo_cfg.CONF.set_override('worker_nodes_subnet',
                                   '',
                                   group='pod_vif_nested')
        pod = mock.MagicMock()
        self.assertRaises(oslo_cfg.RequiredOptError,
            cls._get_parent_port, m_driver, neutron, pod)

    def test_get_parent_port_trunk_not_found(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        node_subnet_id = mock.sentinel.node_subnet_id

        oslo_cfg.CONF.set_override('worker_nodes_subnet',
                                   node_subnet_id,
                                   group='pod_vif_nested')

        node_fixed_ip = mock.sentinel.node_fixed_ip
        pod_status = mock.MagicMock()
        pod_status.__getitem__.return_value = node_fixed_ip

        pod = mock.MagicMock()
        pod.__getitem__.return_value = pod_status

        ports = {'ports': []}
        neutron.list_ports.return_value = ports

        self.assertRaises(k_exc.K8sNodeTrunkPortFailure,
            cls._get_parent_port, m_driver, neutron, pod)
        fixed_ips = ['subnet_id=%s' % str(node_subnet_id),
                     'ip_address=%s' % str(node_fixed_ip)]
        neutron.list_ports.assert_called_once_with(fixed_ips=fixed_ips)

    def test_add_subport(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        trunk_id = mock.sentinel.trunk_id
        subport = mock.sentinel.subport
        vlan_id = mock.sentinel.vlan_id
        m_driver._get_vlan_id.return_value = vlan_id
        subport_dict = [{'segmentation_id': vlan_id,
                    'port_id': subport,
                    'segmentation_type': 'vlan'}]
        nested_vlan_vif.DEFAULT_MAX_RETRY_COUNT = 1
        self.assertEqual(vlan_id, cls._add_subport(m_driver,
            neutron, trunk_id, subport))
        m_driver._get_vlan_id.assert_called_once_with(trunk_id)
        neutron.trunk_add_subports.assert_called_once_with(trunk_id,
            {'sub_ports': subport_dict})

    def test_add_subport_get_vlanid_failure(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        trunk_id = mock.sentinel.trunk_id
        subport = mock.sentinel.subport
        m_driver._get_vlan_id.side_effect = n_exc.NeutronClientException
        nested_vlan_vif.DEFAULT_MAX_RETRY_COUNT = 1
        self.assertRaises(n_exc.NeutronClientException,
                cls._add_subport, m_driver, neutron, trunk_id, subport)

        m_driver._get_vlan_id.assert_called_once_with(trunk_id)

    def test_add_subport_with_vlan_id_conflict(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        trunk_id = mock.sentinel.trunk_id
        subport = mock.sentinel.subport
        vlan_id = mock.sentinel.vlan_id
        m_driver._get_vlan_id.return_value = vlan_id
        subport_dict = [{'segmentation_id': vlan_id,
                    'port_id': subport,
                    'segmentation_type': 'vlan'}]
        neutron.trunk_add_subports.side_effect = n_exc.Conflict
        nested_vlan_vif.DEFAULT_MAX_RETRY_COUNT = 1
        self.assertRaises(n_exc.Conflict, cls._add_subport, m_driver,
                          neutron, trunk_id, subport)

        neutron.trunk_add_subports.assert_called_once_with(trunk_id,
            {'sub_ports': subport_dict})

    def test_remove_subport(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        trunk_id = mock.sentinel.trunk_id
        subport_id = mock.sentinel.subport_id
        subportid_dict = [{'port_id': subport_id}]
        cls._remove_subport(m_driver, neutron, trunk_id, subport_id)

        neutron.trunk_remove_subports.assert_called_once_with(trunk_id,
            {'sub_ports': subportid_dict})

    @mock.patch('kuryr.lib.segmentation_type_drivers.allocate_segmentation_id')
    def test_get_vlan_id(self, mock_alloc_seg_id):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        vlanid_set = mock.sentinel.vlanid_set
        trunk_id = mock.sentinel.trunk_id
        m_driver._get_in_use_vlan_ids_set.return_value = vlanid_set
        cls._get_vlan_id(m_driver, trunk_id)

        mock_alloc_seg_id.assert_called_once_with(vlanid_set)

    @mock.patch('kuryr.lib.segmentation_type_drivers.allocate_segmentation_id')
    def test_get_vlan_id_exhausted(self, mock_alloc_seg_id):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        vlanid_set = mock.sentinel.vlanid_set
        trunk_id = mock.sentinel.trunk_id
        m_driver._get_in_use_vlan_ids_set.return_value = vlanid_set
        mock_alloc_seg_id.side_effect = kl_exc.SegmentationIdAllocationFailure
        self.assertRaises(kl_exc.SegmentationIdAllocationFailure,
                          cls._get_vlan_id, m_driver, trunk_id)

        mock_alloc_seg_id.assert_called_once_with(vlanid_set)

    @mock.patch('kuryr.lib.segmentation_type_drivers.release_segmentation_id')
    def test_release_vlan_id(self, mock_rel_seg_id):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        vlanid = mock.sentinel.vlanid
        cls._release_vlan_id(m_driver, vlanid)

        mock_rel_seg_id.assert_called_once_with(vlanid)

    def test_get_in_use_vlan_ids_set(self):
        cls = nested_vlan_vif.NestedVlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        vlan_ids = set()
        trunk_id = mock.sentinel.trunk_id
        vlan_ids.add('100')

        port = mock.MagicMock()
        port.__getitem__.return_value = '100'
        trunk_obj = mock.MagicMock()
        trunk_obj.__getitem__.return_value = [port]
        trunk = mock.MagicMock()
        trunk.__getitem__.return_value = trunk_obj
        neutron.show_trunk.return_value = trunk
        self.assertEqual(vlan_ids,
            cls._get_in_use_vlan_ids_set(m_driver, trunk_id))
