# Copyright 2017 Red Hat, Inc.
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

import collections
import ddt
import mock

from neutronclient.common import exceptions as n_exc
from oslo_config import cfg as oslo_cfg

from os_vif.objects import vif as osv_vif

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import nested_vlan_vif
from kuryr_kubernetes.controller.drivers import neutron_vif
from kuryr_kubernetes.controller.drivers import vif_pool
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


def get_pod_obj():
    return {
        'status': {
            'qosClass': 'BestEffort',
            'hostIP': '192.168.1.2',
        },
        'kind': 'Pod',
        'spec': {
            'schedulerName': 'default-scheduler',
            'containers': [{
                'name': 'busybox',
                'image': 'busybox',
                'resources': {}
            }],
            'nodeName': 'kuryr-devstack'
        },
        'metadata': {
            'name': 'busybox-sleep1',
            'namespace': 'default',
            'resourceVersion': '53808',
            'selfLink': '/api/v1/namespaces/default/pods/busybox-sleep1',
            'uid': '452176db-4a85-11e7-80bd-fa163e29dbbb'
        }}


def get_port_obj(port_id=None, device_owner=None, ip_address=None):
    port_obj = {
        'allowed_address_pairs': [],
        'extra_dhcp_opts': [],
        'device_owner': 'compute:kuryr',
        'revision_number': 9,
        'port_security_enabled': True,
        'binding:profile': {},
        'fixed_ips': [
            {
                'subnet_id': 'e1942bb1-5f51-4646-9885-365b66215592',
                'ip_address': '10.10.0.5'},
            {
                'subnet_id': '4894baaf-df06-4a54-9885-9cd99d1cc245',
                'ip_address': 'fd35:7db5:e3fc:0:f816:3eff:fe80:d421'}],
        'id': '07cfe856-11cc-43d9-9200-ff4dc02d3620',
        'security_groups': ['cfb3dfc4-7a43-4ba1-b92d-b8b2650d7f88'],
        'binding:vif_details': {
            'port_filter': True,
            'ovs_hybrid_plug': False},
        'binding:vif_type': 'ovs',
        'mac_address': 'fa:16:3e:80:d4:21',
        'project_id': 'b6e8fb2bde594673923afc19cf168f3a',
        'status': 'DOWN',
        'binding:host_id': 'kuryr-devstack',
        'description': '',
        'tags': [],
        'device_id': '',
        'name': constants.KURYR_PORT_NAME,
        'admin_state_up': True,
        'network_id': 'ba44f957-c467-412b-b985-ae720514bc46',
        'tenant_id': 'b6e8fb2bde594673923afc19cf168f3a',
        'created_at': '2017-06-09T13:23:24Z',
        'binding:vnic_type': 'normal'}

    if ip_address:
        port_obj['fixed_ips'][0]['ip_address'] = ip_address
    if port_id:
        port_obj['id'] = port_id
    if device_owner:
        port_obj['device_owner'] = device_owner

    return port_obj


@ddt.ddt
class NeutronVIFPool(test_base.TestCase):

    def test_request_vif(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj()
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        vif = mock.sentinel.vif

        m_driver._get_port_from_pool.return_value = vif
        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(vif, cls.request_vif(m_driver, pod, project_id,
                                              subnets, security_groups))

    @mock.patch('eventlet.spawn')
    def test_request_vif_empty_pool(self, m_eventlet):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        host_addr = mock.sentinel.host_addr
        pod_status = mock.MagicMock()
        pod_status.__getitem__.return_value = host_addr
        pod = mock.MagicMock()
        pod.__getitem__.return_value = pod_status
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        m_driver._get_port_from_pool.side_effect = (
            exceptions.ResourceNotReady(pod))

        self.assertRaises(exceptions.ResourceNotReady, cls.request_vif,
                          m_driver, pod, project_id, subnets, security_groups)
        m_eventlet.assert_called_once()

    def test_request_vif_pod_without_host_name(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj()
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        m_driver._get_host_addr.side_effect = KeyError

        self.assertRaises(KeyError, cls.request_vif, m_driver, pod, project_id,
                          subnets, security_groups)

    @mock.patch('time.time', return_value=50)
    def test__populate_pool(self, m_time):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        cls_vif_driver = neutron_vif.NeutronPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        pool_key = (mock.sentinel.host_addr, project_id,
                    tuple(security_groups))
        vif = osv_vif.VIFOpenVSwitch(id='0fa0e837-d34e-4580-a6c4-04f5f607d93e')
        vifs = [vif]

        m_driver._existing_vifs = {}
        m_driver._available_ports_pools = {}
        m_driver._last_update = {pool_key: 1}

        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('ports_pool_update_frequency',
                                   15,
                                   group='vif_pool')
        m_driver._get_pool_size.return_value = 2
        vif_driver.request_vifs.return_value = vifs

        cls._populate_pool(m_driver, pool_key, pod, subnets)
        m_driver._get_pool_size.assert_called_once()
        m_driver._drv_vif.request_vifs.assert_called_once()

    @mock.patch('time.time', return_value=0)
    def test__populate_pool_no_update(self, m_time):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        pool_key = (mock.sentinel.host_addr, project_id,
                    tuple(security_groups))

        oslo_cfg.CONF.set_override('ports_pool_update_frequency',
                                   15,
                                   group='vif_pool')
        m_driver._last_update = {pool_key: 1}

        cls._populate_pool(m_driver, pool_key, pod, subnets)
        m_driver._get_pool_size.assert_not_called()

    @mock.patch('time.time', return_value=50)
    def test__populate_pool_large_pool(self, m_time):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        cls_vif_driver = neutron_vif.NeutronPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        pool_key = (mock.sentinel.host_addr, project_id,
                    tuple(security_groups))

        oslo_cfg.CONF.set_override('ports_pool_update_frequency',
                                   15,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        m_driver._last_update = {pool_key: 1}
        m_driver._get_pool_size.return_value = 10

        cls._populate_pool(m_driver, pool_key, pod, subnets)
        m_driver._get_pool_size.assert_called_once()
        m_driver._drv_vif.request_vifs.assert_not_called()

    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool(self, m_eventlet):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = mock.sentinel.pool_key
        port_id = mock.sentinel.port_id
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets

        pod = get_pod_obj()

        m_driver._available_ports_pools = {
            pool_key: collections.deque([port_id])}
        m_driver._existing_vifs = {port_id: port}

        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets))

        neutron.update_port.assert_called_once_with(
            port_id,
            {
                "port": {
                    'name': pod['metadata']['name'],
                    'device_id': pod['metadata']['uid']
                }
            })
        m_eventlet.assert_not_called()

    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool_pool_populate(self, m_eventlet):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = mock.sentinel.pool_key
        port_id = mock.sentinel.port_id
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets

        pod = get_pod_obj()

        m_driver._available_ports_pools = {
            pool_key: collections.deque([port_id])}
        m_driver._existing_vifs = {port_id: port}

        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        pool_length = 3
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets))

        neutron.update_port.assert_called_once_with(
            port_id,
            {
                "port": {
                    'name': pod['metadata']['name'],
                    'device_id': pod['metadata']['uid']
                }
            })
        m_eventlet.assert_called_once()

    def test__get_port_from_pool_empty_pool(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pod = get_pod_obj()
        pool_key = mock.sentinel.pool_key
        subnets = mock.sentinel.subnets

        m_driver._available_ports_pools = {pool_key: collections.deque([])}

        self.assertRaises(exceptions.ResourceNotReady, cls._get_port_from_pool,
                          m_driver, pool_key, pod, subnets)

        neutron.update_port.assert_not_called()

    def test_release_vif(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        m_driver._recyclable_ports = {}

        pod = get_pod_obj()
        project_id = mock.sentinel.project_id
        security_groups = [mock.sentinel.security_groups]
        vif = osv_vif.VIFOpenVSwitch(id='0fa0e837-d34e-4580-a6c4-04f5f607d93e')

        m_driver._return_ports_to_pool.return_value = None

        cls.release_vif(m_driver, pod, vif, project_id, security_groups)

        m_driver._return_ports_to_pool.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    @ddt.data((0), (10))
    def test__return_ports_to_pool(self, max_pool, m_sleep):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   max_pool,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_called_once_with(
            port_id,
            {
                "port": {
                    'name': constants.KURYR_PORT_NAME,
                    'device_id': '',
                    'security_groups': ['security_group']
                }
            })
        neutron.delete_port.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    @ddt.data((0), (10))
    def test__return_ports_to_pool_no_update(self, max_pool, m_sleep):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   max_pool,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   False,
                                   group='kubernetes')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group']}]
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        neutron.delete_port.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_delete_port(self, m_sleep):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 10
        vif = mock.sentinel.vif

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        m_driver._existing_vifs = {port_id: vif}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   10,
                                   group='vif_pool')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        neutron.delete_port.assert_called_once_with(port_id)

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_update_exception(self, m_sleep):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   0,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length
        neutron.update_port.side_effect = n_exc.NeutronClientException

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_called_once_with(
            port_id,
            {
                "port": {
                    'name': constants.KURYR_PORT_NAME,
                    'device_id': '',
                    'security_groups': ['security_group']
                }
            })
        neutron.delete_port.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_delete_exception(self, m_sleep):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 10
        vif = mock.sentinel.vif

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        m_driver._existing_vifs = {port_id: vif}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   5,
                                   group='vif_pool')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length
        neutron.delete_port.side_effect = n_exc.PortNotFoundClient

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        neutron.delete_port.assert_called_once_with(port_id)

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_delete_key_error(self, m_sleep):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 10

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        m_driver._existing_vifs = {}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   5,
                                   group='vif_pool')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        neutron.delete_port.assert_not_called()

    @mock.patch('kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                '_get_subnet')
    def test__recover_precreated_ports(self, m_get_subnet, m_to_osvif):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        cls_vif_driver = neutron_vif.NeutronPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        m_driver._existing_vifs = {}
        m_driver._available_ports_pools = {}

        port_id = mock.sentinel.port_id
        port = get_port_obj(port_id=port_id)
        filtered_ports = [port]
        m_driver._get_ports_by_attrs.return_value = filtered_ports
        vif_plugin = mock.sentinel.plugin
        m_driver._drv_vif._get_vif_plugin.return_value = vif_plugin

        oslo_cfg.CONF.set_override('port_debug',
                                   False,
                                   group='kubernetes')
        subnet = mock.sentinel.subnet
        subnet_id = port['fixed_ips'][0]['subnet_id']
        m_get_subnet.return_value = subnet
        vif = mock.sentinel.vif
        m_to_osvif.return_value = vif

        cls._recover_precreated_ports(m_driver)

        m_driver._get_ports_by_attrs.assert_called_once()
        m_get_subnet.assert_called_with(subnet_id)
        m_driver._drv_vif._get_vif_plugin.assert_called_once_with(port)
        m_to_osvif.assert_called_once_with(vif_plugin, port,
                                           {subnet_id: subnet})

        self.assertEqual(m_driver._existing_vifs[port_id], vif)
        pool_key = (port['binding:host_id'], port['project_id'],
                    tuple(port['security_groups']))
        self.assertEqual(m_driver._available_ports_pools[pool_key], [port_id])

    @mock.patch('kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                '_get_subnet')
    def test__recover_precreated_ports_empty(self, m_get_subnet, m_to_osvif):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        filtered_ports = []
        m_driver._get_ports_by_attrs.return_value = filtered_ports

        oslo_cfg.CONF.set_override('port_debug',
                                   False,
                                   group='kubernetes')

        cls._recover_precreated_ports(m_driver)

        m_driver._get_ports_by_attrs.assert_called_once()
        m_get_subnet.assert_not_called()
        m_to_osvif.assert_not_called()


@ddt.ddt
class NestedVIFPool(test_base.TestCase):

    def _get_trunk_obj(self, port_id=None, subport_id=None):
        trunk_obj = {
            'status': 'ACTIVE',
            'name': 'trunk-01aa31ea-5adf-4776-9c5d-21b50dba0ccc',
            'admin_state_up': True,
            'tenant_id': '18fbc0e645d74e83931193ef99dfe5c5',
            'sub_ports': [{'port_id': '85104e7d-8597-4bf7-94e7-a447ef0b50f1',
                           'segmentation_type': 'vlan',
                           'segmentation_id': 4056}],
            'updated_at': '2017-06-09T13:25:01Z',
            'id': 'd1217757-848f-45dd-9ff2-3640f9b053dc',
            'revision_number': 2359,
            'project_id': '18fbc0e645d74e83931193ef99dfe5c5',
            'port_id': '01aa31ea-5adf-4776-9c5d-21b50dba0ccc',
            'created_at': '2017-05-19T16:43:22Z',
            'description': ''
        }

        if port_id:
            trunk_obj['port_id'] = port_id
        if subport_id:
            trunk_obj['sub_ports'][0]['port_id'] = subport_id

        return trunk_obj

    def test_request_vif(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj()
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        vif = mock.sentinel.vif

        m_driver._get_port_from_pool.return_value = vif
        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(vif, cls.request_vif(m_driver, pod, project_id,
                                              subnets, security_groups))

    @mock.patch('eventlet.spawn')
    def test_request_vif_empty_pool(self, m_eventlet):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj()
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]

        m_driver._get_port_from_pool.side_effect = exceptions.ResourceNotReady(
            pod)

        self.assertRaises(exceptions.ResourceNotReady, cls.request_vif,
                          m_driver, pod, project_id, subnets, security_groups)
        m_eventlet.assert_called_once()

    def test_request_vif_pod_without_host_id(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj()
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        m_driver._get_host_addr.side_effect = KeyError

        self.assertRaises(KeyError, cls.request_vif, m_driver, pod, project_id,
                          subnets, security_groups)

    @mock.patch('time.time', return_value=50)
    def test__populate_pool(self, m_time):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        pool_key = (mock.sentinel.host_addr, project_id,
                    tuple(security_groups))
        vif = osv_vif.VIFOpenVSwitch(id='0fa0e837-d34e-4580-a6c4-04f5f607d93e')
        vifs = [vif]

        m_driver._existing_vifs = {}
        m_driver._available_ports_pools = {}
        m_driver._last_update = {pool_key: 1}

        oslo_cfg.CONF.set_override('ports_pool_update_frequency',
                                   15,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        m_driver._get_pool_size.return_value = 2
        vif_driver.request_vifs.return_value = vifs

        cls._populate_pool(m_driver, pool_key, pod, subnets)
        m_driver._get_pool_size.assert_called_once()
        m_driver._drv_vif.request_vifs.assert_called_once()

    @mock.patch('time.time', return_value=0)
    def test__populate_pool_no_update(self, m_time):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        pool_key = (mock.sentinel.host_addr, project_id,
                    tuple(security_groups))

        oslo_cfg.CONF.set_override('ports_pool_update_frequency',
                                   15,
                                   group='vif_pool')
        m_driver._last_update = {pool_key: 1}

        cls._populate_pool(m_driver, pool_key, pod, subnets)
        m_driver._get_pool_size.assert_not_called()

    @mock.patch('time.time', return_value=50)
    def test__populate_pool_large_pool(self, m_time):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        pool_key = (mock.sentinel.host_addr, project_id,
                    tuple(security_groups))

        oslo_cfg.CONF.set_override('ports_pool_update_frequency',
                                   15,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        m_driver._last_update = {pool_key: 1}
        m_driver._get_pool_size.return_value = 10

        cls._populate_pool(m_driver, pool_key, pod, subnets)
        m_driver._get_pool_size.assert_called_once()
        m_driver._drv_vif.request_vifs.assert_not_called()

    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool(self, m_eventlet):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = mock.sentinel.pool_key
        port_id = mock.sentinel.port_id
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets

        pod = get_pod_obj()

        m_driver._available_ports_pools = {
            pool_key: collections.deque([port_id])}
        m_driver._existing_vifs = {port_id: port}

        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets))

        neutron.update_port.assert_called_once_with(
            port_id,
            {
                "port": {
                    'name': pod['metadata']['name'],
                }
            })
        m_eventlet.assert_not_called()

    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool_pool_populate(self, m_eventlet):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = mock.sentinel.pool_key
        port_id = mock.sentinel.port_id
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets

        pod = get_pod_obj()

        m_driver._available_ports_pools = {
            pool_key: collections.deque([port_id])}
        m_driver._existing_vifs = {port_id: port}

        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        pool_length = 3
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets))

        neutron.update_port.assert_called_once_with(
            port_id,
            {
                "port": {
                    'name': pod['metadata']['name'],
                }
            })
        m_eventlet.assert_called_once()

    def test__get_port_from_pool_empty_pool(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pod = mock.sentinel.pod
        pool_key = mock.sentinel.pool_key
        subnets = mock.sentinel.subnets

        m_driver._available_ports_pools = {pool_key: collections.deque([])}

        self.assertRaises(exceptions.ResourceNotReady, cls._get_port_from_pool,
                          m_driver, pool_key, pod, subnets)

        neutron.update_port.assert_not_called()

    def test_release_vif(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        m_driver._recyclable_ports = {}

        pod = get_pod_obj()
        project_id = mock.sentinel.project_id
        security_groups = [mock.sentinel.security_groups]
        vif = osv_vif.VIFOpenVSwitch(id='0fa0e837-d34e-4580-a6c4-04f5f607d93e')

        m_driver._return_ports_to_pool.return_value = None

        cls.release_vif(m_driver, pod, vif, project_id, security_groups)

        m_driver._return_ports_to_pool.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    @ddt.data((0), (10))
    def test__return_ports_to_pool(self, max_pool, m_sleep):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   max_pool,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_called_once_with(
            port_id,
            {
                "port": {
                    'name': constants.KURYR_PORT_NAME,
                    'security_groups': ['security_group']
                }
            })
        neutron.delete_port.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    @ddt.data((0), (10))
    def test__return_ports_to_pool_no_update(self, max_pool, m_sleep):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   max_pool,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   False,
                                   group='kubernetes')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group']}]
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        neutron.delete_port.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_delete_port(self, m_sleep):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 10
        vif = mock.MagicMock()
        vif.vlan_id = mock.sentinel.vlan_id
        p_port = mock.sentinel.p_port
        trunk_id = mock.sentinel.trunk_id

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        m_driver._existing_vifs = {port_id: vif}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   10,
                                   group='vif_pool')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length
        m_driver._known_trunk_ids = {}
        m_driver._drv_vif._get_parent_port_by_host_ip.return_value = p_port
        m_driver._drv_vif._get_trunk_id.return_value = trunk_id

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        neutron.delete_port.assert_called_once_with(port_id)
        m_driver._drv_vif._get_parent_port_by_host_ip.assert_called_once()
        m_driver._drv_vif._get_trunk_id.assert_called_once_with(p_port)
        m_driver._drv_vif._remove_subport.assert_called_once_with(neutron,
                                                                  trunk_id,
                                                                  port_id)

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_update_exception(self, m_sleep):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   0,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length
        neutron.update_port.side_effect = n_exc.NeutronClientException

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_called_once_with(
            port_id,
            {
                "port": {
                    'name': constants.KURYR_PORT_NAME,
                    'security_groups': ['security_group']
                }
            })
        neutron.delete_port.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_delete_exception(self, m_sleep):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 10
        vif = mock.MagicMock()
        vif.vlan_id = mock.sentinel.vlan_id
        p_port = mock.sentinel.p_port
        trunk_id = mock.sentinel.trunk_id

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        m_driver._existing_vifs = {port_id: vif}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   5,
                                   group='vif_pool')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length
        neutron.delete_port.side_effect = n_exc.PortNotFoundClient
        m_driver._known_trunk_ids = {}
        m_driver._drv_vif._get_parent_port_by_host_ip.return_value = p_port
        m_driver._drv_vif._get_trunk_id.return_value = trunk_id

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        m_driver._drv_vif._get_parent_port_by_host_ip.assert_called_once()
        m_driver._drv_vif._get_trunk_id.assert_called_once_with(p_port)
        m_driver._drv_vif._remove_subport.assert_called_once_with(neutron,
                                                                  trunk_id,
                                                                  port_id)
        neutron.delete_port.assert_called_once_with(port_id)

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_delete_key_error(self, m_sleep):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pool_key = ('node_ip', 'project_id', tuple(['security_group']))
        port_id = mock.sentinel.port_id
        pool_length = 10
        p_port = mock.sentinel.p_port
        trunk_id = mock.sentinel.trunk_id

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = {}
        m_driver._existing_vifs = {}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   5,
                                   group='vif_pool')
        m_driver._get_ports_by_attrs.return_value = [
            {'id': port_id, 'security_groups': ['security_group_modified']}]
        m_driver._get_pool_size.return_value = pool_length
        m_driver._known_trunk_ids = {}
        m_driver._drv_vif._get_parent_port_by_host_ip.return_value = p_port
        m_driver._drv_vif._get_trunk_id.return_value = trunk_id

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        m_driver._drv_vif._get_parent_port_by_host_ip.assert_called_once()
        m_driver._drv_vif._get_trunk_id.assert_called_once_with(p_port)
        m_driver._drv_vif._remove_subport.assert_called_once_with(neutron,
                                                                  trunk_id,
                                                                  port_id)
        neutron.delete_port.assert_not_called()

    def test__get_parent_port_ip(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = mock.sentinel.port_id
        ip_address = mock.sentinel.ip_address

        port_obj = get_port_obj(ip_address=ip_address)
        neutron.show_port.return_value = {'port': port_obj}

        self.assertEqual(ip_address, cls._get_parent_port_ip(m_driver,
                                                             port_id))

    @mock.patch('kuryr_kubernetes.os_vif_util.'
                'neutron_to_osvif_vif_nested_vlan')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                '_get_subnet')
    def test__precreated_ports_recover(self, m_get_subnet, m_to_osvif):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = mock.sentinel.port_id
        host_addr = mock.sentinel.host_addr

        m_driver._get_ports_by_attrs.side_effect = [[get_port_obj(
            port_id=port_id, device_owner='trunk:subport')], []]
        trunk_id = mock.sentinel.trunk_id
        trunk_obj = self._get_trunk_obj(port_id=trunk_id, subport_id=port_id)
        neutron.list_trunks.return_value = {'trunks': [trunk_obj]}
        m_driver._get_parent_port_ip.return_value = host_addr

        m_get_subnet.return_value = mock.sentinel.subnet
        m_to_osvif.return_value = mock.sentinel.vif

        cls._precreated_ports(m_driver, 'recover')
        neutron.list_trunks.assert_called_once()
        m_driver._get_parent_port_ip.assert_called_with(trunk_id)

    def test__precreated_ports_free(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        port_id = mock.sentinel.port_id
        host_addr = mock.sentinel.host_addr

        subport_obj = get_port_obj(port_id=port_id,
                                   device_owner='trunk:subport')
        m_driver._get_ports_by_attrs.side_effect = [[subport_obj], []]
        trunk_id = mock.sentinel.trunk_id
        trunk_obj = self._get_trunk_obj(port_id=trunk_id, subport_id=port_id)
        pool_key = (host_addr, subport_obj['id'],
                    tuple(subport_obj['security_groups']))
        m_driver._available_ports_pools = {pool_key: port_id}

        neutron.list_trunks.return_value = {'trunks': [trunk_obj]}
        m_driver._get_parent_port_ip.return_value = host_addr

        cls._precreated_ports(m_driver, 'free')
        neutron.list_trunks.assert_called_once()
        m_driver._get_parent_port_ip.assert_called_with(trunk_id)
        m_driver._drv_vif._remove_subport.assert_called_once()
        neutron.delete_port.assert_called_once()
        m_driver._drv_vif._release_vlan_id.assert_called_once()

    @mock.patch('kuryr_kubernetes.os_vif_util.'
                'neutron_to_osvif_vif_nested_vlan')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                '_get_subnet')
    def test__precreated_ports_recover_several_trunks(self, m_get_subnet,
                                                      m_to_osvif):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id1 = mock.sentinel.port_id1
        host_addr1 = mock.sentinel.host_addr1
        trunk_id1 = mock.sentinel.trunk_id1

        port_id2 = mock.sentinel.port_id2
        host_addr2 = mock.sentinel.host_addr2
        trunk_id2 = mock.sentinel.trunk_id2

        port1 = get_port_obj(port_id=port_id1, device_owner='trunk:subport')
        port2 = get_port_obj(port_id=port_id2, device_owner='trunk:subport')
        m_driver._get_ports_by_attrs.side_effect = [[port1, port2], []]

        trunk_obj1 = self._get_trunk_obj(port_id=trunk_id1,
                                         subport_id=port_id1)
        trunk_obj2 = self._get_trunk_obj(port_id=trunk_id2,
                                         subport_id=port_id2)
        neutron.list_trunks.return_value = {'trunks': [trunk_obj1,
                                                       trunk_obj2]}
        m_driver._get_parent_port_ip.side_effect = [host_addr1, host_addr2]

        subnet = mock.sentinel.subnet
        m_get_subnet.return_value = subnet
        m_to_osvif.return_value = mock.sentinel.vif

        cls._precreated_ports(m_driver, 'recover')
        neutron.list_trunks.asser_called_once()
        m_driver._get_parent_port_ip.assert_has_calls([mock.call(trunk_id1),
                                                       mock.call(trunk_id2)])
        calls = [mock.call(port1, {port1['fixed_ips'][0]['subnet_id']: subnet},
                           trunk_obj1['sub_ports'][0]['segmentation_id']),
                 mock.call(port2, {port2['fixed_ips'][0]['subnet_id']: subnet},
                           trunk_obj2['sub_ports'][0]['segmentation_id'])]
        m_to_osvif.assert_has_calls(calls)

    @mock.patch('kuryr_kubernetes.os_vif_util.'
                'neutron_to_osvif_vif_nested_vlan')
    @mock.patch('kuryr_kubernetes.controller.drivers.default_subnet.'
                '_get_subnet')
    def test__precreated_ports_recover_several_subports(self, m_get_subnet,
                                                        m_to_osvif):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id1 = mock.sentinel.port_id1
        host_addr = mock.sentinel.host_addr
        trunk_id = mock.sentinel.trunk_id

        port_id2 = mock.sentinel.port_id2

        port1 = get_port_obj(port_id=port_id1, device_owner='trunk:subport')
        port2 = get_port_obj(port_id=port_id2, device_owner='trunk:subport')
        m_driver._get_ports_by_attrs.side_effect = [[port1, port2], []]

        trunk_obj = self._get_trunk_obj(port_id=trunk_id,
                                        subport_id=port_id1)
        trunk_obj['sub_ports'].append({'port_id': port_id2,
                                       'segmentation_type': 'vlan',
                                       'segmentation_id': 101})
        neutron.list_trunks.return_value = {'trunks': [trunk_obj]}
        m_driver._get_parent_port_ip.return_value = [host_addr]

        subnet = mock.sentinel.subnet
        m_get_subnet.return_value = subnet
        m_to_osvif.return_value = mock.sentinel.vif

        cls._precreated_ports(m_driver, 'recover')
        neutron.list_trunks.asser_called_once()
        m_driver._get_parent_port_ip.assert_called_once_with(trunk_id)
        calls = [mock.call(port1, {port1['fixed_ips'][0]['subnet_id']: subnet},
                           trunk_obj['sub_ports'][0]['segmentation_id']),
                 mock.call(port2, {port2['fixed_ips'][0]['subnet_id']: subnet},
                           trunk_obj['sub_ports'][1]['segmentation_id'])]
        m_to_osvif.assert_has_calls(calls)

    @ddt.data(('recover'), ('free'))
    def test__precreated_ports_no_ports(self, m_action):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        m_driver._get_ports_by_attrs.return_value = []

        cls._precreated_ports(m_driver, m_action)
        neutron.list_trunks.assert_not_called()

    @ddt.data(('recover'), ('free'))
    def test__precreated_ports_no_trunks(self, m_action):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        m_driver._get_ports_by_attrs.side_effect = [[get_port_obj(
            device_owner='trunk:subport')], []]
        neutron.list_trunks.return_value = {'trunks': []}

        cls._precreated_ports(m_driver, m_action)
        neutron.list_trunks.assert_called()
        m_driver._get_parent_port_ip.assert_not_called()

    @ddt.data(('recover'), ('free'))
    def test__precreated_ports_exception(self, m_action):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = mock.sentinel.port_id
        m_driver._get_ports_by_attrs.side_effect = [[get_port_obj(
            port_id=port_id, device_owner='trunk:subport')], []]
        trunk_id = mock.sentinel.trunk_id
        trunk_obj = self._get_trunk_obj(port_id=trunk_id)
        neutron.list_trunks.return_value = {'trunks': [trunk_obj]}
        m_driver._get_parent_port_ip.side_effect = n_exc.PortNotFoundClient

        self.assertIsNone(cls._precreated_ports(m_driver, m_action))
        neutron.list_trunks.assert_called()
        m_driver._get_parent_port_ip.assert_called_with(trunk_id)
