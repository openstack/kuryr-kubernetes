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


@ddt.ddt
class GenericVIFPool(test_base.TestCase):

    def test_request_vif(self):
        cls = vif_pool.GenericVIFPool
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
        cls = vif_pool.GenericVIFPool
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

    def test_request_vif_pod_without_host_id(self):
        cls = vif_pool.GenericVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj()
        del pod['status']['hostIP']
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]

        self.assertRaises(KeyError, cls.request_vif, m_driver, pod, project_id,
                          subnets, security_groups)

    @mock.patch('time.time', return_value=50)
    def test__populate_pool(self, m_time):
        cls = vif_pool.GenericVIFPool
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
        cls = vif_pool.GenericVIFPool
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
        cls = vif_pool.GenericVIFPool
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
        cls = vif_pool.GenericVIFPool
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
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets))

        neutron.update_port.assert_called_once_with(port_id,
            {
                "port": {
                    'name': pod['metadata']['name'],
                    'device_id': pod['metadata']['uid']
                }
            })
        m_eventlet.assert_not_called()

    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool_pool_populate(self, m_eventlet):
        cls = vif_pool.GenericVIFPool
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
        pool_length = 3
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets))

        neutron.update_port.assert_called_once_with(port_id,
            {
                "port": {
                    'name': pod['metadata']['name'],
                    'device_id': pod['metadata']['uid']
                }
            })
        m_eventlet.assert_called_once()

    def test__get_port_from_pool_empty_pool(self):
        cls = vif_pool.GenericVIFPool
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
        cls = vif_pool.GenericVIFPool
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
        cls = vif_pool.GenericVIFPool
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
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_called_once_with(port_id,
            {
                "port": {
                    'name': 'available-port',
                    'device_id': '',
                    'security_groups': ['security_group']
                }
            })
        neutron.delete_port.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_delete_port(self, m_sleep):
        cls = vif_pool.GenericVIFPool
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
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        neutron.delete_port.assert_called_once_with(port_id)

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_update_exception(self, m_sleep):
        cls = vif_pool.GenericVIFPool
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
        m_driver._get_pool_size.return_value = pool_length
        neutron.update_port.side_effect = n_exc.NeutronClientException

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_called_once_with(port_id,
            {
                "port": {
                    'name': 'available-port',
                    'device_id': '',
                    'security_groups': ['security_group']
                }
            })
        neutron.delete_port.assert_not_called()

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_delete_exception(self, m_sleep):
        cls = vif_pool.GenericVIFPool
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
        m_driver._get_pool_size.return_value = pool_length
        neutron.delete_port.side_effect = n_exc.PortNotFoundClient

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        neutron.delete_port.assert_called_once_with(port_id)

    @mock.patch('eventlet.sleep', side_effect=SystemExit)
    def test__return_ports_to_pool_delete_key_error(self, m_sleep):
        cls = vif_pool.GenericVIFPool
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
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_not_called()
        neutron.delete_port.assert_not_called()


@ddt.ddt
class NestedVIFPool(test_base.TestCase):

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
        del pod['status']['hostIP']
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]

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
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets))

        neutron.update_port.assert_called_once_with(port_id,
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
        pool_length = 3
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets))

        neutron.update_port.assert_called_once_with(port_id,
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
        m_driver._get_pool_size.return_value = pool_length

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_called_once_with(port_id,
            {
                "port": {
                    'name': 'available-port',
                    'security_groups': ['security_group']
                }
            })
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
        m_driver._get_pool_size.return_value = pool_length
        neutron.update_port.side_effect = n_exc.NeutronClientException

        self.assertRaises(SystemExit, cls._return_ports_to_pool, m_driver)

        neutron.update_port.assert_called_once_with(port_id,
            {
                "port": {
                    'name': 'available-port',
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
