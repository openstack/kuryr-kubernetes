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

import mock
import uuid

from kuryr_kubernetes.controller.drivers import sriov as drvs
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import os_vif_util as ovu
from kuryr_kubernetes import utils

from oslo_config import cfg as oslo_cfg


SRIOV_RESOURCE_NAME_A = "sriov_a"
SRIOV_RESOURCE_NAME_B = "sriov_b"

AMOUNT_FOR_SUBNET_A = 2
AMOUNT_FOR_SUBNET_B = 3

SRIOV_PHYSNET_A = "physnet_a"
SRIOV_PHYSNET_B = "physnet_b"


class TestSriovVIFDriver(test_base.TestCase):

    def setUp(self):
        super(TestSriovVIFDriver, self).setUp()

        self._res_map = {SRIOV_PHYSNET_A: SRIOV_RESOURCE_NAME_A,
                         SRIOV_PHYSNET_B: SRIOV_RESOURCE_NAME_B}
        sriov_request = {drvs.sriov_make_resource(k_const.K8S_SRIOV_PREFIX,
                                                  SRIOV_RESOURCE_NAME_A): (
                         str(AMOUNT_FOR_SUBNET_A)),
                         drvs.sriov_make_resource(k_const.K8S_SRIOV_PREFIX,
                                                  SRIOV_RESOURCE_NAME_B): (
                         str(AMOUNT_FOR_SUBNET_B))}

        self._pod = {
            'metadata': {
                'resourceVersion': mock.sentinel.pod_version,
                'selfLink': mock.sentinel.pod_link,
                'name': 'podname'},
            'status': {'phase': k_const.K8S_POD_STATUS_PENDING},
            'spec': {
                'hostNetwork': False,
                'nodeName': 'hostname',
                'containers': [{
                    'resources': {
                        'requests': sriov_request
                        }
                    }]
                }
            }

    def test_activate_vif(self):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        pod = mock.sentinel.pod
        vif = mock.Mock()
        vif.active = False

        cls.activate_vif(m_driver, pod, vif)
        self.assertEqual(True, vif.active)

    @mock.patch('kuryr_kubernetes.os_vif_util.osvif_to_neutron_fixed_ips')
    @mock.patch.object(ovu, 'neutron_to_osvif_vif')
    def test_request_vif(self, m_to_vif, m_to_fips):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        project_id = mock.sentinel.project_id
        fixed_ips = mock.sentinel.fixed_ips
        m_to_fips.return_value = fixed_ips
        network = mock.sentinel.Network
        subnet_id = str(uuid.uuid4())
        subnets = {subnet_id: network}
        security_groups = mock.sentinel.security_groups
        port_fixed_ips = mock.sentinel.port_fixed_ips
        port_id = mock.sentinel.port_id
        port = {
            'fixed_ips': port_fixed_ips,
            'id': port_id
        }
        port_request = mock.sentinel.port_request
        m_driver._get_port_request.return_value = port_request
        vif = mock.sentinel.vif
        m_to_vif.return_value = vif
        neutron.create_port.return_value = {'port': port}
        utils.get_subnet.return_value = subnets

        self.assertEqual(vif, cls.request_vif(m_driver, self._pod, project_id,
                                              subnets, security_groups))

        neutron.create_port.assert_called_once_with(port_request)

    @mock.patch('kuryr_kubernetes.os_vif_util.osvif_to_neutron_fixed_ips')
    @mock.patch.object(ovu, 'neutron_to_osvif_vif')
    def test_request_vif_not_enough_vfs(self, m_to_vif, m_to_fips):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        m_driver._get_remaining_sriov_vfs.return_value = 0
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        project_id = mock.sentinel.project_id
        network = mock.sentinel.Network
        subnet_id = str(uuid.uuid4())
        subnets = {subnet_id: network}
        security_groups = mock.sentinel.security_groups

        self.assertIsNone(cls.request_vif(m_driver, self._pod, project_id,
                                          subnets, security_groups))

        neutron.create_port.assert_not_called()

    def test_get_sriov_num_vf(self):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        m_driver._physnet_resname_mapping = self._res_map
        m_driver._res_prefix = k_const.K8S_SRIOV_PREFIX
        amount = cls._get_remaining_sriov_vfs(m_driver, self._pod,
                                              SRIOV_PHYSNET_A)
        self.assertEqual(amount, AMOUNT_FOR_SUBNET_A)

        amount = cls._get_remaining_sriov_vfs(m_driver, self._pod,
                                              SRIOV_PHYSNET_B)
        self.assertEqual(amount, AMOUNT_FOR_SUBNET_B)

    def test_reduce_remaining_sriov_vfs(self):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        m_driver._physnet_resname_mapping = self._res_map
        m_driver._res_prefix = k_const.K8S_SRIOV_PREFIX

        cls._reduce_remaining_sriov_vfs(m_driver, self._pod, SRIOV_PHYSNET_A)
        amount = cls._get_remaining_sriov_vfs(m_driver, self._pod,
                                              SRIOV_PHYSNET_A)
        self.assertEqual(amount, AMOUNT_FOR_SUBNET_A - 1)

        cls._reduce_remaining_sriov_vfs(m_driver, self._pod, SRIOV_PHYSNET_B)
        amount = cls._get_remaining_sriov_vfs(m_driver, self._pod,
                                              SRIOV_PHYSNET_B)
        self.assertEqual(amount, AMOUNT_FOR_SUBNET_B - 1)

    def test_get_physnet_subnet_mapping(self):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        subnet_id = str(uuid.uuid4())
        oslo_cfg.CONF.set_override('default_physnet_subnets',
                                   'physnet10_4:'+str(subnet_id),
                                   group='sriov')

        mapping = cls._get_physnet_subnet_mapping(m_driver)
        self.assertEqual(mapping, {subnet_id: 'physnet10_4'})

    def test_get_physnet_resname_mapping(self):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        oslo_cfg.CONF.set_override('physnet_resource_mappings',
                                   SRIOV_PHYSNET_A + ':' +
                                   SRIOV_RESOURCE_NAME_A + ',' +
                                   SRIOV_PHYSNET_B + ':' +
                                   SRIOV_RESOURCE_NAME_B,
                                   group='sriov')

        mapping = cls._get_physnet_resname_mapping(m_driver)
        self.assertEqual(mapping, self._res_map)

    def test_empty_physnet_resname_mapping(self):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        empty_res_map = {SRIOV_PHYSNET_A: SRIOV_PHYSNET_A,
                         SRIOV_PHYSNET_B: SRIOV_PHYSNET_B}
        subnet_id = str(uuid.uuid4())
        subnet_id_2 = str(uuid.uuid4())
        m_driver._physnet_subnet_mapping = {subnet_id: SRIOV_PHYSNET_A,
                                            subnet_id_2: SRIOV_PHYSNET_B}
        mapping = cls._get_physnet_resname_mapping(m_driver)
        self.assertEqual(mapping, empty_res_map)

    def test_get_physnet_for_subnet_id(self):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        subnet_id = str(uuid.uuid4())
        m_driver._physnet_subnet_mapping = {subnet_id: 'physnet10_4'}

        physnet = cls._get_physnet_for_subnet_id(m_driver, subnet_id)
        self.assertEqual(physnet, 'physnet10_4')

    def test_get_physnet_for_subnet_id_error(self):
        cls = drvs.SriovVIFDriver
        m_driver = mock.Mock(spec=cls)

        subnet_id = str(uuid.uuid4())
        m_driver._physnet_subnet_mapping = {}

        self.assertRaises(KeyError, cls._get_physnet_for_subnet_id,
                          m_driver, subnet_id)
