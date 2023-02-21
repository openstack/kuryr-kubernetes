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
import eventlet
import functools
import threading
from unittest import mock
import uuid

import ddt
from openstack import exceptions as os_exc
from openstack.network.v2 import network as os_network
from openstack.network.v2 import port as os_port
from oslo_config import cfg as oslo_cfg

from os_vif.objects import network as osv_network
from os_vif.objects import vif as osv_vif

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import nested_vlan_vif
from kuryr_kubernetes.controller.drivers import neutron_vif
from kuryr_kubernetes.controller.drivers import utils
from kuryr_kubernetes.controller.drivers import vif_pool
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import os_vif_util as ovu
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests import fake
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
            'uid': '452176db-4a85-11e7-80bd-fa163e29dbbb',
            'annotations': {
                'openstack.org/kuryr-vif': {}
            }
        }}


def get_pod_name(pod):
    return "%(namespace)s/%(name)s" % pod['metadata']


AVAILABLE_PORTS_TYPE = functools.partial(collections.defaultdict,
                                         collections.OrderedDict)


@ddt.ddt
class BaseVIFPool(test_base.TestCase):

    def test_request_vif(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj()
        project_id = str(uuid.uuid4())
        subnet_id = str(uuid.uuid4())
        net_id = str(uuid.uuid4())
        _net = os_network.Network(
            id=net_id,
            name=None,
            mtu=None,
            provider_network_type=None,
        )
        network = ovu.neutron_to_osvif_network(_net)
        subnets = {subnet_id: network}
        security_groups = [mock.sentinel.security_groups]
        vif = mock.sentinel.vif

        m_driver._get_port_from_pool.return_value = vif
        m_driver._recovered_pools = True
        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        self.assertEqual(vif, cls.request_vif(m_driver, pod, project_id,
                                              subnets, security_groups))

    def test_request_vif_empty_pool(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        host_addr = mock.sentinel.host_addr
        pod_status = mock.MagicMock()
        pod_status.__getitem__.return_value = host_addr
        pod = mock.MagicMock()
        pod.__getitem__.return_value = pod_status
        project_id = str(uuid.uuid4())
        subnet_id = str(uuid.uuid4())
        net_id = str(uuid.uuid4())
        _net = os_network.Network(
            id=net_id,
            name=None,
            mtu=None,
            provider_network_type=None,
        )
        network = ovu.neutron_to_osvif_network(_net)
        subnets = {subnet_id: network}
        security_groups = [mock.sentinel.security_groups]
        m_driver._recovered_pools = True
        m_driver._get_port_from_pool.side_effect = (
            exceptions.ResourceNotReady(pod))

        self.assertRaises(exceptions.ResourceNotReady, cls.request_vif,
                          m_driver, pod, project_id, subnets, security_groups)
        m_driver._populate_pool.assert_called_once()

    def test_request_vif_pod_without_host(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj()
        project_id = str(uuid.uuid4())
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        m_driver._get_host_addr.side_effect = KeyError
        m_driver._recovered_pools = True

        resp = cls.request_vif(m_driver, pod, project_id, subnets,
                               security_groups)
        self.assertIsNone(resp)

    def test_request_vif_multi_vif_pod_without_host(self):
        cls = vif_pool.MultiVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj().copy()
        del pod['spec']['nodeName']
        project_id = str(uuid.uuid4())
        subnets = mock.sentinel.subnets
        security_groups = [mock.sentinel.security_groups]
        m_driver._vif_drvs = {}
        m_driver._vif_drvs['nested-vlan'] = 'NestedVIFPool'
        m_driver._get_pod_vif_type.side_effect = KeyError

        resp = cls.request_vif(m_driver, pod, project_id, subnets,
                               security_groups)
        self.assertIsNone(resp)

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('time.time', return_value=50)
    @ddt.data((neutron_vif.NeutronPodVIFDriver),
              (nested_vlan_vif.NestedVlanPodVIFDriver))
    def test__populate_pool(self, m_vif_driver, m_time,
                            m_get_kubernetes_client):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        cls_vif_driver = m_vif_driver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pod = mock.sentinel.pod
        project_id = str(uuid.uuid4())
        subnets = mock.sentinel.subnets
        security_groups = ['test-sg']
        pool_key = (mock.sentinel.host_addr, project_id)
        vif = osv_vif.VIFOpenVSwitch(id='0fa0e837-d34e-4580-a6c4-04f5f607d93e')
        vifs = [vif]

        m_driver._existing_vifs = {}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._recovered_pools = True
        m_driver._lock = threading.Lock()
        m_driver._populate_pool_lock = {
            pool_key: mock.MagicMock(spec=threading.Lock())}
        m_driver._create_ports_semaphore = mock.MagicMock(
            spec=eventlet.semaphore.Semaphore(20))

        oslo_cfg.CONF.set_override('ports_pool_min',
                                   5,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('ports_pool_update_frequency',
                                   15,
                                   group='vif_pool')
        m_driver._get_pool_size.return_value = 2
        vif_driver.request_vifs.return_value = vifs

        cls._populate_pool(m_driver, pool_key, pod, subnets,
                           tuple(security_groups))
        m_driver._get_pool_size.assert_called_once()
        m_driver._drv_vif.request_vifs.assert_called_once()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @ddt.data((neutron_vif.NeutronPodVIFDriver),
              (nested_vlan_vif.NestedVlanPodVIFDriver))
    def test__populate_pool_not_ready(self, m_vif_driver,
                                      m_get_kubernetes_client):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        cls_vif_driver = m_vif_driver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pod = mock.sentinel.pod
        project_id = str(uuid.uuid4())
        subnets = mock.sentinel.subnets
        security_groups = 'test-sg'
        pool_key = (mock.sentinel.host_addr, project_id)
        m_driver._recovered_pools = False

        self.assertFalse(cls._populate_pool(
                          m_driver, pool_key, pod, subnets,
                          tuple(security_groups)))
        m_driver._drv_vif.request_vifs.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @ddt.data((neutron_vif.NeutronPodVIFDriver),
              (nested_vlan_vif.NestedVlanPodVIFDriver))
    def test__populate_pool_not_ready_dont_raise(self, m_vif_driver,
                                                 m_get_kubernetes_client):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        cls_vif_driver = m_vif_driver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pod = mock.sentinel.pod
        project_id = str(uuid.uuid4())
        subnets = mock.sentinel.subnets
        security_groups = 'test-sg'
        pool_key = (mock.sentinel.host_addr, project_id)
        m_driver._recovered_pools = False

        cls._populate_pool(m_driver, pool_key, pod, subnets,
                           tuple(security_groups))
        m_driver._drv_vif.request_vifs.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    @mock.patch('time.time', return_value=0)
    @ddt.data((neutron_vif.NeutronPodVIFDriver),
              (nested_vlan_vif.NestedVlanPodVIFDriver))
    def test__populate_pool_no_update(self, m_vif_driver, m_time,
                                      m_get_kubernetes_client):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        pod = mock.sentinel.pod
        project_id = str(uuid.uuid4())
        subnets = mock.sentinel.subnets
        security_groups = 'test-sg'
        pool_key = (mock.sentinel.host_addr, project_id)
        m_driver._get_pool_size.return_value = 4

        cls_vif_driver = m_vif_driver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        oslo_cfg.CONF.set_override('ports_pool_update_frequency',
                                   15,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('ports_pool_min',
                                   3,
                                   group='vif_pool')
        m_driver._get_pool_size.return_value = 10
        m_driver._recovered_pools = True

        cls._populate_pool(m_driver, pool_key, pod, subnets,
                           tuple(security_groups))
        m_driver._get_pool_size.assert_called()
        m_driver._drv_vif.request_vifs.assert_not_called()

    def test_release_vif(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)
        m_driver._recyclable_ports = {}
        m_driver._existing_vifs = {}

        pod = get_pod_obj()
        project_id = mock.sentinel.project_id
        security_groups = [mock.sentinel.security_groups]
        net_id = str(uuid.uuid4())
        _net = os_network.Network(
            id=net_id,
            name=None,
            mtu=None,
            provider_network_type=None,
        )
        network = ovu.neutron_to_osvif_network(_net)
        vif = osv_vif.VIFOpenVSwitch(id='0fa0e837-d34e-4580-a6c4-04f5f607d93e',
                                     network=network)

        m_driver._return_ports_to_pool.return_value = None
        m_driver._recovered_pools = True

        cls.release_vif(m_driver, pod, vif, project_id, security_groups)

        m_driver._return_ports_to_pool.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_vifs')
    def test__get_in_use_ports(self, get_vifs):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        pod = get_pod_obj()
        port_id = str(uuid.uuid4())
        port_network = osv_network.Network(id=str(uuid.uuid4()))
        pod_vif = osv_vif.VIFBase(id=port_id, network=port_network)
        get_vifs.return_value = {'eth0': pod_vif}
        items = [pod]
        kubernetes.get.return_value = {'items': items}
        network = {}

        resp = cls._get_in_use_ports_info(m_driver)
        network[port_network.id] = port_network
        self.assertEqual(resp, ([port_id], network))

    def test__get_in_use_ports_empty(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        kubernetes = self.useFixture(k_fix.MockK8sClient()).client
        items = []
        kubernetes.get.return_value = {'items': items}

        resp = cls._get_in_use_ports_info(m_driver)

        self.assertEqual(resp, ([], {}))

    def test_cleanup_leftover_ports(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        port_id = str(uuid.uuid4())
        port = fake.get_port_obj(port_id=port_id)
        net_id = port.network_id
        tags = 'clusterTest'
        port.tags = [tags]
        os_net.ports.return_value = [port]
        oslo_cfg.CONF.set_override('resource_tags',
                                   tags,
                                   group='neutron_defaults')
        self.addCleanup(oslo_cfg.CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')

        os_net.networks.return_value = [os_network.Network(id=net_id)]

        cls._cleanup_leftover_ports(m_driver)
        os_net.networks.assert_called()
        os_net.delete_port.assert_not_called()

    def test_cleanup_leftover_ports_different_network(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        port_id = str(uuid.uuid4())
        port = fake.get_port_obj(port_id=port_id)
        tags = 'clusterTest'
        port.tags = [tags]
        os_net.ports.return_value = [port]
        oslo_cfg.CONF.set_override('resource_tags',
                                   tags,
                                   group='neutron_defaults')
        self.addCleanup(oslo_cfg.CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')
        os_net.networks.return_value = []

        cls._cleanup_leftover_ports(m_driver)
        os_net.networks.assert_called()
        os_net.delete_port.assert_not_called()

    def test_cleanup_leftover_ports_no_binding(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        port_id = str(uuid.uuid4())
        port = fake.get_port_obj(port_id=port_id)
        net_id = port.network_id
        tags = 'clusterTest'
        port.tags = [tags]
        port.binding_host_id = None
        os_net.ports.return_value = [port]
        oslo_cfg.CONF.set_override('resource_tags',
                                   tags,
                                   group='neutron_defaults')
        self.addCleanup(oslo_cfg.CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')

        os_net.networks.return_value = [os_network.Network(id=net_id)]

        cls._cleanup_leftover_ports(m_driver)
        os_net.networks.assert_called()
        os_net.delete_port.assert_called_once_with(port.id)

    def test_cleanup_leftover_ports_no_tags(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        port_id = str(uuid.uuid4())
        port = fake.get_port_obj(port_id=port_id)
        net_id = port.network_id
        tags = 'clusterTest'
        os_net.ports.return_value = [port]
        oslo_cfg.CONF.set_override('resource_tags',
                                   tags,
                                   group='neutron_defaults')
        self.addCleanup(oslo_cfg.CONF.clear_override, 'resource_tags',
                        group='neutron_defaults')

        os_net.networks.return_value = [os_network.Network(id=net_id)]

        cls._cleanup_leftover_ports(m_driver)
        os_net.networks.assert_called()
        os_net.delete_port.assert_called_once_with(port.id)

    def test_cleanup_leftover_ports_no_tagging(self):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        port_id = str(uuid.uuid4())
        port = fake.get_port_obj(port_id=port_id)
        os_net.ports.return_value = [port]

        cls._cleanup_leftover_ports(m_driver)
        os_net.networks.assert_not_called()
        os_net.delete_port.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.delete_ports')
    def test_cleanup_leftover_ports_no_tagging_no_binding(self, m_del_ports):
        cls = vif_pool.BaseVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        port_id = str(uuid.uuid4())
        port = fake.get_port_obj(port_id=port_id)
        port.binding_host_id = None
        os_net.ports.return_value = [port]

        cls._cleanup_leftover_ports(m_driver)
        os_net.networks.assert_not_called()
        m_del_ports.assert_called_once_with([port])


@ddt.ddt
class NeutronVIFPool(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_port_name')
    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool(self, m_eventlet, m_get_port_name):
        m_driver = vif_pool.NeutronVIFPool()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = mock.sentinel.pool_key
        port_id = str(uuid.uuid4())
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)

        oslo_cfg.CONF.set_override('port_debug',
                                   True, group='kubernetes')
        pod = get_pod_obj()
        m_get_port_name.return_value = get_pod_name(pod)

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][sgs] = [port_id]
        m_driver._existing_vifs = {port_id: port}
        m_get_port_name.return_value = get_pod_name(pod)

        oslo_cfg.CONF.set_override('ports_pool_min', 5, group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug', True, group='kubernetes')
        m_driver._get_pool_size = mock.Mock(return_value=5)

        self.assertEqual(port, m_driver._get_port_from_pool(
            pool_key, pod, subnets, sgs))

        os_net.update_port.assert_called_once_with(
            port_id, name=get_pod_name(pod), device_id=pod['metadata']['uid'])
        # 2 calls from the constructor, so no calls in _get_port_from_pool()
        self.assertEqual(3, m_eventlet.call_count)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_port_name')
    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool_pool_populate(self, m_eventlet,
                                               m_get_port_name):
        m_driver = vif_pool.NeutronVIFPool()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = mock.sentinel.pool_key
        port_id = str(uuid.uuid4())
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)

        pod = get_pod_obj()

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][sgs] = [port_id]
        m_driver._existing_vifs = {port_id: port}
        m_get_port_name.return_value = get_pod_name(pod)

        oslo_cfg.CONF.set_override('ports_pool_min', 5, group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug', True, group='kubernetes')
        m_driver._get_pool_size = mock.Mock(return_value=3)

        self.assertEqual(port, m_driver._get_port_from_pool(
            pool_key, pod, subnets, sgs))

        os_net.update_port.assert_called_once_with(
            port_id, name=get_pod_name(pod), device_id=pod['metadata']['uid'])
        # 2 calls come from the constructor, so 1 call in _get_port_from_pool()
        self.assertEqual(3, m_eventlet.call_count)

    def test__get_port_from_pool_empty_pool(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pod = get_pod_obj()
        pool_key = mock.sentinel.pool_key
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][sgs] = []

        self.assertRaises(exceptions.ResourceNotReady, cls._get_port_from_pool,
                          m_driver, pool_key, pod, subnets, sgs)

        os_net.update_port.assert_not_called()

    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool_empty_pool_reuse(self, m_eventlet):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pod = get_pod_obj()
        port_id = str(uuid.uuid4())
        port_id_2 = str(uuid.uuid4())
        port = mock.sentinel.port
        port_2 = mock.sentinel.port_2
        pool_key = mock.sentinel.pool_key
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)
        sgs_2 = ('test-sg2',)
        sgs_3 = ('test-sg3',)

        oslo_cfg.CONF.set_override('port_debug', False, group='kubernetes')

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][sgs] = []
        m_driver._available_ports_pools[pool_key][sgs_2] = [port_id]
        m_driver._available_ports_pools[pool_key][sgs_3] = [port_id_2]
        m_driver._existing_vifs = {port_id: port, port_id_2: port_2}

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets, sgs))

        os_net.update_port.assert_called_once_with(
            port_id, security_groups=list(sgs))
        m_eventlet.assert_called()

    def test__get_port_from_pool_empty_pool_reuse_no_ports(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pod = get_pod_obj()
        pool_key = mock.sentinel.pool_key
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)
        sgs_2 = ('test-sg2',)

        oslo_cfg.CONF.set_override('port_debug', False, group='kubernetes')
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][(sgs_2,)] = []
        m_driver._available_ports_pools[pool_key][(sgs,)] = []

        self.assertRaises(exceptions.ResourceNotReady, cls._get_port_from_pool,
                          m_driver, pool_key, pod, subnets, sgs)

        os_net.update_port.assert_not_called()

    @ddt.data((0), (10))
    def test__trigger_return_to_pool(self, max_pool):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._recovered_pools = True
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   max_pool,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        os_net.ports.return_value = [
            os_port.Port(
                id=port_id,
                security_group_ids=['security_group_modified'],
            ),
        ]
        m_driver._get_pool_size.return_value = pool_length

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_called_once_with(
            port_id, name=constants.KURYR_PORT_NAME, device_id='')
        os_net.delete_port.assert_not_called()

    @ddt.data((0), (10))
    def test__trigger_return_to_pool_no_update(self, max_pool):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   max_pool,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   False,
                                   group='kubernetes')

        port = fake.get_port_obj(port_id=port_id)
        port.security_group_ids = ['security_group']
        os_net.ports.return_value = (p for p in [port])
        m_driver._get_pool_size.return_value = pool_length
        m_driver._recovered_pools = True

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_not_called()
        os_net.delete_port.assert_not_called()

    def test__trigger_return_to_pool_delete_port(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 10
        vif = mock.sentinel.vif

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {port_id: vif}
        m_driver._recovered_pools = True
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   10,
                                   group='vif_pool')
        os_net.ports.return_value = [
            os_port.Port(
                id=port_id,
                security_group_ids=['security_group_modified'],
            ),
        ]
        m_driver._get_pool_size.return_value = pool_length

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_not_called()
        os_net.delete_port.assert_called_once_with(port_id)

    def test__trigger_return_to_pool_update_exception(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._recovered_pools = True
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   0,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        os_net.ports.return_value = [
            os_port.Port(
                id=port_id,
                security_group_ids=['security_group_modified'],
            ),
        ]
        m_driver._get_pool_size.return_value = pool_length
        os_net.update_port.side_effect = os_exc.SDKException

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_called_once_with(
            port_id, name=constants.KURYR_PORT_NAME, device_id='')
        os_net.delete_port.assert_not_called()

    def test__trigger_return_to_pool_delete_exception(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 10
        vif = mock.sentinel.vif

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {port_id: vif}
        m_driver._recovered_pools = True
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   5,
                                   group='vif_pool')
        os_net.ports.return_value = [
            os_port.Port(
                id=port_id,
                security_group_ids=['security_group_modified'],
            ),
        ]
        m_driver._get_pool_size.return_value = pool_length

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_not_called()
        os_net.delete_port.assert_called_once_with(port_id)

    def test__trigger_return_to_pool_delete_key_error(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 10

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {}
        m_driver._recovered_pools = True
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   5,
                                   group='vif_pool')
        os_net.ports.return_value = [
            os_port.Port(
                id=port_id,
                security_group_ids=['security_group_modified'],
            ),
        ]
        m_driver._get_pool_size.return_value = pool_length

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_not_called()
        os_net.delete_port.assert_not_called()

    @mock.patch('kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif')
    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    def test__recover_precreated_ports(self, m_get_subnet, m_to_osvif):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        cls_vif_driver = neutron_vif.NeutronPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        m_driver._existing_vifs = {}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()

        port_id = str(uuid.uuid4())
        port = fake.get_port_obj(port_id=port_id)
        filtered_ports = [port]
        os_net.ports.return_value = filtered_ports
        vif_plugin = mock.sentinel.plugin
        port.binding_vif_type = vif_plugin

        oslo_cfg.CONF.set_override('port_debug',
                                   False,
                                   group='kubernetes')

        subnet_id = port.fixed_ips[0]['subnet_id']
        net_id = str(uuid.uuid4())
        _net = os_network.Network(
            id=net_id,
            name=None,
            mtu=None,
            provider_network_type=None,
        )
        network = ovu.neutron_to_osvif_network(_net)
        subnet = {subnet_id: network}
        m_get_subnet.return_value = network
        vif = mock.sentinel.vif
        m_to_osvif.return_value = vif
        m_driver._get_in_use_ports_info.return_value = [], {}

        pool_key = (port.binding_host_id, port.project_id, net_id)
        m_driver._get_pool_key.return_value = pool_key
        m_driver._get_trunks_info.return_value = ({}, {}, {})

        cls._recover_precreated_ports(m_driver)

        os_net.ports.assert_called_once()
        m_get_subnet.assert_called_with(subnet_id)
        m_to_osvif.assert_called_once_with(vif_plugin, port, subnet)

        self.assertEqual(m_driver._existing_vifs[port_id], vif)
        self.assertEqual(m_driver._available_ports_pools[pool_key],
                         {tuple(port.security_group_ids): [port_id]})

    @mock.patch('kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif')
    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    def test__recover_precreated_ports_empty(self, m_get_subnet, m_to_osvif):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        filtered_ports = []
        os_net.ports.return_value = filtered_ports
        m_driver._get_trunks_info.return_value = ({}, {}, {})
        m_driver._get_in_use_ports_info.return_value = [], {}

        oslo_cfg.CONF.set_override('port_debug',
                                   False,
                                   group='kubernetes')

        cls._recover_precreated_ports(m_driver)

        os_net.ports.assert_called_once()
        m_get_subnet.assert_not_called()
        m_to_osvif.assert_not_called()

    @mock.patch('eventlet.GreenPool')
    def test_delete_network_pools(self, m_green_pool):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        m_pool = mock.MagicMock()
        m_green_pool.return_value = m_pool

        net_id = mock.sentinel.net_id
        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][('sg',)] = [port_id]
        m_driver._lock = threading.Lock()
        m_driver._populate_pool_lock = {
            pool_key: mock.MagicMock(spec=threading.Lock())}
        m_driver._existing_vifs = {port_id: mock.sentinel.vif}
        m_driver._recovered_pools = True

        m_driver._get_pool_key_net.return_value = net_id

        cls.delete_network_pools(m_driver, net_id)

        m_driver._trigger_return_to_pool.assert_called_once()
        m_driver._get_pool_key_net.assert_called_once()
        m_pool.imap.assert_called_once_with(utils.delete_neutron_port,
                                            [port_id])

    def test_delete_network_pools_not_ready(self):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        net_id = mock.sentinel.net_id
        m_driver._recovered_pools = False

        self.assertRaises(exceptions.ResourceNotReady,
                          cls.delete_network_pools, m_driver, net_id)

        m_driver._trigger_return_to_pool.assert_not_called()
        m_driver._get_pool_key_net.assert_not_called()
        os_net.delete_port.assert_not_called()

    @mock.patch('eventlet.GreenPool')
    def test_delete_network_pools_missing_port_id(self, m_green_pool):
        cls = vif_pool.NeutronVIFPool
        m_driver = mock.MagicMock(spec=cls)
        m_pool = mock.MagicMock()
        m_green_pool.return_value = m_pool

        net_id = mock.sentinel.net_id
        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][('sgs',)] = [port_id]
        m_driver._lock = threading.Lock()
        m_driver._populate_pool_lock = {
            pool_key: mock.MagicMock(spec=threading.Lock())}
        m_driver._existing_vifs = {}
        m_driver._recovered_pools = True

        m_driver._get_pool_key_net.return_value = net_id

        cls.delete_network_pools(m_driver, net_id)

        m_driver._trigger_return_to_pool.assert_called_once()
        m_driver._get_pool_key_net.assert_called_once()
        m_pool.imap.assert_called_once_with(utils.delete_neutron_port,
                                            [port_id])


@ddt.ddt
class NestedVIFPool(test_base.TestCase):

    def _get_trunk_obj(self, port_id=None, subport_id=None, trunk_id=None):
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
        if trunk_id:
            trunk_obj['id'] = trunk_id

        return trunk_obj

    def _get_parent_ports(self, trunk_objs):
        parent_ports = {}
        for trunk_obj in trunk_objs:
            parent_ports[trunk_obj['id']] = {
                'ip': 'kuryr-devstack',
                'subports': trunk_obj['sub_ports']}
        return parent_ports

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_port_name')
    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool(self, m_eventlet, m_get_port_name):
        m_driver = vif_pool.NestedVIFPool()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = mock.sentinel.pool_key
        port_id = str(uuid.uuid4())
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)

        pod = get_pod_obj()

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][sgs] = [port_id]
        m_driver._existing_vifs = {port_id: port}
        m_get_port_name.return_value = get_pod_name(pod)

        oslo_cfg.CONF.set_override('ports_pool_min', 5, group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug', True, group='kubernetes')
        m_driver._get_pool_size = mock.Mock(return_value=5)

        self.assertEqual(port, m_driver._get_port_from_pool(
            pool_key, pod, subnets, sgs))

        os_net.update_port.assert_called_once_with(
            port_id, name=get_pod_name(pod))
        self.assertEqual(3, m_eventlet.call_count)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.get_port_name')
    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool_pool_populate(self, m_eventlet,
                                               m_get_port_name):
        m_driver = vif_pool.NestedVIFPool()
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = mock.sentinel.pool_key
        port_id = str(uuid.uuid4())
        port = mock.sentinel.port
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)

        pod = get_pod_obj()

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][sgs] = [port_id]
        m_driver._existing_vifs = {port_id: port}
        m_get_port_name.return_value = get_pod_name(pod)

        oslo_cfg.CONF.set_override('ports_pool_min', 5, group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug', True, group='kubernetes')
        m_driver._get_pool_size = mock.Mock(return_value=3)

        self.assertEqual(port, m_driver._get_port_from_pool(
            pool_key, pod, subnets, sgs))

        os_net.update_port.assert_called_once_with(
            port_id, name=get_pod_name(pod))
        # 2 calls come from the constructor, so 1 call in _get_port_from_pool()
        self.assertEqual(3, m_eventlet.call_count)

    def test__get_port_from_pool_empty_pool(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pod = mock.sentinel.pod
        pool_key = mock.sentinel.pool_key
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][sgs] = []

        self.assertRaises(exceptions.ResourceNotReady, cls._get_port_from_pool,
                          m_driver, pool_key, pod, subnets, sgs)

        os_net.update_port.assert_not_called()

    @mock.patch('eventlet.spawn')
    def test__get_port_from_pool_empty_pool_reuse(self, m_eventlet):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pod = mock.sentinel.pod
        port_id = str(uuid.uuid4())
        port_id_2 = str(uuid.uuid4())
        port = mock.sentinel.port
        port_2 = mock.sentinel.port_2
        pool_key = mock.sentinel.pool_key
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)
        sgs_2 = ('test-sg2',)
        sgs_3 = ('test-sg3',)

        oslo_cfg.CONF.set_override('port_debug', False, group='kubernetes')
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][sgs] = []
        m_driver._available_ports_pools[pool_key][sgs_2] = [port_id]
        m_driver._available_ports_pools[pool_key][sgs_3] = [port_id_2]
        m_driver._existing_vifs = {port_id: port, port_id_2: port_2}

        self.assertEqual(port, cls._get_port_from_pool(
            m_driver, pool_key, pod, subnets, sgs))

        os_net.update_port.assert_called_once_with(
            port_id, security_groups=list(sgs))
        m_eventlet.assert_called()

    def test__get_port_from_pool_empty_pool_reuse_no_ports(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pod = mock.sentinel.pod
        pool_key = mock.sentinel.pool_key
        subnets = mock.sentinel.subnets
        sgs = ('test-sg',)
        sgs_2 = ('test-sg2',)

        oslo_cfg.CONF.set_override('port_debug', False, group='kubernetes')
        pool_length = 5
        m_driver._get_pool_size.return_value = pool_length

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][sgs] = []
        m_driver._available_ports_pools[pool_key][sgs_2] = []

        self.assertRaises(exceptions.ResourceNotReady, cls._get_port_from_pool,
                          m_driver, pool_key, pod, subnets, sgs)

        os_net.update_port.assert_not_called()

    @ddt.data((0), (10))
    def test__trigger_return_to_pool(self, max_pool):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   max_pool,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        os_net.ports.return_value = [
            os_port.Port(
                id=port_id,
                security_group_ids=['security_group_modified'],
            ),
        ]
        m_driver._get_pool_size.return_value = pool_length
        m_driver._recovered_pools = True

        cls._trigger_return_to_pool(m_driver)

        (os_net.update_port
         .assert_called_once_with(port_id,
                                  name=constants.KURYR_PORT_NAME))
        os_net.delete_port.assert_not_called()

    @ddt.data((0), (10))
    def test__trigger_return_to_pool_no_update(self, max_pool):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   max_pool,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   False,
                                   group='kubernetes')
        port = fake.get_port_obj(port_id=port_id)
        port.security_group_ids = ['security_group']
        os_net.ports.return_value = [port]
        m_driver._get_pool_size.return_value = pool_length
        m_driver._recovered_pools = True

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_not_called()
        os_net.delete_port.assert_not_called()

    def test__trigger_return_to_pool_delete_port(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 10
        vif = mock.MagicMock()
        vif.vlan_id = mock.sentinel.vlan_id
        trunk_id = str(uuid.uuid4())

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {port_id: vif}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   10,
                                   group='vif_pool')
        port = fake.get_port_obj(port_id=port_id)
        port.security_group_ids = ['security_group_modified']
        os_net.ports.return_value = [port]
        m_driver._get_pool_size.return_value = pool_length
        m_driver._get_trunk_id.return_value = trunk_id
        m_driver._known_trunk_ids = {}
        m_driver._recovered_pools = True

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_not_called()
        os_net.delete_port.assert_called_once_with(port_id)
        m_driver._get_trunk_id.assert_called_once()
        m_driver._drv_vif._remove_subport.assert_called_once_with(trunk_id,
                                                                  port_id)

    def test__trigger_return_to_pool_update_exception(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 5

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   0,
                                   group='vif_pool')
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        port = fake.get_port_obj(port_id=port_id)
        port.security_group_ids = ['security_group_modified']
        os_net.ports.return_value = [port]
        m_driver._get_pool_size.return_value = pool_length
        os_net.update_port.side_effect = os_exc.SDKException
        m_driver._recovered_pools = True

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_called_once_with(
            port_id, name=constants.KURYR_PORT_NAME)
        os_net.delete_port.assert_not_called()

    def test__trigger_return_to_pool_delete_exception(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 10
        vif = mock.MagicMock()
        vif.vlan_id = mock.sentinel.vlan_id
        trunk_id = str(uuid.uuid4())

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {port_id: vif}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   5,
                                   group='vif_pool')
        port = fake.get_port_obj(port_id=port_id)
        port.security_group_ids = ['security_group_modified']
        os_net.ports.return_value = [port]
        m_driver._get_pool_size.return_value = pool_length
        m_driver._get_trunk_id.return_value = trunk_id
        m_driver._known_trunk_ids = {}
        m_driver._recovered_pools = True

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_not_called()
        m_driver._get_trunk_id.assert_called_once()
        m_driver._drv_vif._remove_subport.assert_called_once_with(trunk_id,
                                                                  port_id)
        os_net.delete_port.assert_called_once_with(port_id)

    def test__trigger_return_to_pool_delete_key_error(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        pool_length = 10
        trunk_id = str(uuid.uuid4())

        m_driver._recyclable_ports = {port_id: pool_key}
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {}
        oslo_cfg.CONF.set_override('ports_pool_max',
                                   5,
                                   group='vif_pool')
        port = fake.get_port_obj(port_id=port_id)
        port.security_group_ids = ['security_group_modified']
        os_net.ports.return_value = [port]
        m_driver._get_pool_size.return_value = pool_length
        m_driver._known_trunk_ids = {}
        m_driver._get_trunk_id.return_value = trunk_id
        m_driver._recovered_pools = True

        cls._trigger_return_to_pool(m_driver)

        os_net.update_port.assert_not_called()
        m_driver._get_trunk_id.assert_called_once()
        m_driver._drv_vif._remove_subport.assert_called_once_with(trunk_id,
                                                                  port_id)
        os_net.delete_port.assert_not_called()

    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    def test__get_trunk_info(self, m_get_subnet):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        port_id = str(uuid.uuid4())
        trunk_port = fake.get_port_obj(port_id=port_id)
        trunk_id = str(uuid.uuid4())
        trunk_details = {
            'trunk_id': trunk_id,
            'sub_ports': [{
                'port_id': '85104e7d-8597-4bf7-94e7-a447ef0b50f1',
                'segmentation_type': 'vlan',
                'segmentation_id': 4056}]}
        trunk_port.trunk_details = trunk_details

        subport_id = str(uuid.uuid4())
        subport = fake.get_port_obj(port_id=subport_id,
                                    device_owner='trunk:subport')
        os_net.ports.return_value = [trunk_port, subport]
        m_driver._get_in_use_ports_info.return_value = [], {}
        subnet = mock.sentinel.subnet
        m_get_subnet.return_value = subnet

        exp_p_ports = {trunk_id: {
            'ip': trunk_port.fixed_ips[0]['ip_address'],
            'subports': trunk_details['sub_ports']}}
        exp_subnets = {subport.fixed_ips[0]['subnet_id']:
                       {subport.fixed_ips[0]['subnet_id']: subnet}}

        r_p_ports, r_subports, r_subnets = cls._get_trunks_info(m_driver)

        self.assertEqual(r_p_ports, exp_p_ports)
        self.assertDictEqual(r_subports[subport_id].to_dict(),
                             subport.to_dict())
        self.assertEqual(r_subnets, exp_subnets)

    def test__get_trunk_info_empty(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        os_net.ports.return_value = []
        m_driver._get_in_use_ports_info.return_value = [], {}

        r_p_ports, r_subports, r_subnets = cls._get_trunks_info(m_driver)

        self.assertEqual(r_p_ports, {})
        self.assertEqual(r_subports, {})
        self.assertEqual(r_subnets, {})

    def test__get_trunk_info_no_trunk_details(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        port_id = str(uuid.uuid4())
        port = fake.get_port_obj(port_id=port_id, device_owner='compute:nova')
        os_net.ports.return_value = [port]
        m_driver._get_in_use_ports_info.return_value = [], {}

        r_p_ports, r_subports, r_subnets = cls._get_trunks_info(m_driver)

        self.assertEqual(r_p_ports, {})
        self.assertEqual(r_subports, {})
        self.assertEqual(r_subnets, {})

    @mock.patch('kuryr_kubernetes.os_vif_util.'
                'neutron_to_osvif_vif_nested_vlan')
    def test__precreated_ports_recover(self, m_to_osvif):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {}

        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        port_id = str(uuid.uuid4())
        trunk_id = str(uuid.uuid4())
        trunk_obj = self._get_trunk_obj(port_id=trunk_id, subport_id=port_id)
        port = fake.get_port_obj(port_id=port_id, device_owner='trunk:subport')

        p_ports = self._get_parent_ports([trunk_obj])
        a_subports = {port_id: port}
        subnet_id = port.fixed_ips[0]['subnet_id']
        net_id = str(uuid.uuid4())
        _net = os_network.Network(
            id=net_id,
            name=None,
            mtu=None,
            provider_network_type=None,
        )
        network = ovu.neutron_to_osvif_network(_net)
        subnets = {subnet_id: {subnet_id: network}}
        m_driver._get_trunks_info.return_value = (p_ports, a_subports,
                                                  subnets)

        vif = mock.sentinel.vif
        m_to_osvif.return_value = vif

        pool_key = (port.binding_host_id, port.project_id, net_id)
        m_driver._get_pool_key.return_value = pool_key

        cls._precreated_ports(m_driver, 'recover')

        m_driver._get_trunks_info.assert_called_once()
        self.assertEqual(m_driver._existing_vifs[port_id], vif)
        self.assertEqual(m_driver._available_ports_pools[pool_key],
                         {tuple(port.security_group_ids): [port_id]})
        os_net.delete_port.assert_not_called()

    @mock.patch('kuryr_kubernetes.os_vif_util.'
                'neutron_to_osvif_vif_nested_vlan')
    def test__precreated_ports_recover_plus_port_cleanup(self, m_to_osvif):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {}

        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')

        port_id = str(uuid.uuid4())
        trunk_id = str(uuid.uuid4())
        trunk_obj = self._get_trunk_obj(port_id=trunk_id, subport_id=port_id)
        port = fake.get_port_obj(port_id=port_id, device_owner='trunk:subport')
        port_to_delete_id = str(uuid.uuid4())
        port_to_delete = fake.get_port_obj(port_id=port_to_delete_id,
                                           device_owner='trunk:subport')

        p_ports = self._get_parent_ports([trunk_obj])
        a_subports = {port_id: port, port_to_delete_id: port_to_delete}
        subnet_id = port.fixed_ips[0]['subnet_id']
        net_id = str(uuid.uuid4())
        _net = os_network.Network(
            id=net_id,
            name=None,
            mtu=None,
            provider_network_type=None,
        )
        network = ovu.neutron_to_osvif_network(_net)
        subnets = {subnet_id: {subnet_id: network}}
        m_driver._get_trunks_info.return_value = (p_ports, a_subports,
                                                  subnets)

        vif = mock.sentinel.vif
        m_to_osvif.return_value = vif

        pool_key = (port.binding_host_id, port.project_id, net_id)
        m_driver._get_pool_key.return_value = pool_key

        cls._precreated_ports(m_driver, 'recover')

        m_driver._get_trunks_info.assert_called_once()
        self.assertEqual(m_driver._existing_vifs[port_id], vif)
        self.assertEqual(m_driver._available_ports_pools[pool_key],
                         {tuple(port.security_group_ids): [port_id]})
        os_net.delete_port.assert_called_with(port_to_delete_id)

    def test__precreated_ports_free(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        os_net = self.useFixture(k_fix.MockNetworkClient()).client
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')

        port_id = str(uuid.uuid4())
        trunk_id = str(uuid.uuid4())
        trunk_obj = self._get_trunk_obj(port_id=trunk_id, subport_id=port_id)
        port = fake.get_port_obj(port_id=port_id,
                                 device_owner='trunk:subport')

        p_ports = self._get_parent_ports([trunk_obj])
        a_subports = {port_id: port}
        subnet_id = port.fixed_ips[0]['subnet_id']
        net_id = str(uuid.uuid4())
        _net = os_network.Network(
            id=net_id,
            name=None,
            mtu=None,
            provider_network_type=None,
        )
        network = ovu.neutron_to_osvif_network(_net)
        subnets = {subnet_id: {subnet_id: network}}
        m_driver._get_trunks_info.return_value = (p_ports, a_subports,
                                                  subnets)

        pool_key = (port.binding_host_id, port.project_id, net_id)
        m_driver._get_pool_key.return_value = pool_key
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][
            tuple(port.security_group_ids)] = [port_id]
        m_driver._existing_vifs = {port_id: mock.sentinel.vif}

        cls._precreated_ports(m_driver, 'free')

        m_driver._get_trunks_info.assert_called_once()
        m_driver._drv_vif._remove_subport.assert_called_once()
        os_net.delete_port.assert_called_once()
        m_driver._drv_vif._release_vlan_id.assert_called_once()

        self.assertEqual(m_driver._existing_vifs, {})
        self.assertEqual(m_driver._available_ports_pools[pool_key][tuple(
            port.security_group_ids)], [])

    @mock.patch('kuryr_kubernetes.os_vif_util.'
                'neutron_to_osvif_vif_nested_vlan')
    def test__precreated_ports_recover_several_trunks(self, m_to_osvif):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {}

        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')

        port_id1 = str(uuid.uuid4())
        trunk_id1 = str(uuid.uuid4())

        port_id2 = str(uuid.uuid4())
        trunk_id2 = str(uuid.uuid4())

        trunk_obj1 = self._get_trunk_obj(port_id=trunk_id1,
                                         subport_id=port_id1)
        trunk_obj2 = self._get_trunk_obj(port_id=trunk_id2,
                                         subport_id=port_id2,
                                         trunk_id=str(uuid.uuid4()))

        port1 = fake.get_port_obj(port_id=port_id1,
                                  device_owner='trunk:subport')
        port2 = fake.get_port_obj(port_id=port_id2,
                                  device_owner='trunk:subport')

        p_ports = self._get_parent_ports([trunk_obj1, trunk_obj2])
        a_subports = {port_id1: port1, port_id2: port2}
        subnet_id = port1.fixed_ips[0]['subnet_id']
        net_id = str(uuid.uuid4())
        _net = os_network.Network(
            id=net_id,
            name=None,
            mtu=None,
            provider_network_type=None,
        )
        network = ovu.neutron_to_osvif_network(_net)
        subnets = {subnet_id: {subnet_id: network}}

        m_driver._get_trunks_info.return_value = (p_ports, a_subports,
                                                  subnets)
        vif = mock.sentinel.vif
        m_to_osvif.return_value = vif

        cls._precreated_ports(m_driver, 'recover')

        m_driver._get_trunks_info.assert_called_once()
        self.assertEqual(m_driver._existing_vifs, {port_id1: vif,
                                                   port_id2: vif})
        os_net.delete_port.assert_not_called()

    @mock.patch('kuryr_kubernetes.os_vif_util.'
                'neutron_to_osvif_vif_nested_vlan')
    def test__precreated_ports_recover_several_subports(self, m_to_osvif):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {}

        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')

        port_id1 = str(uuid.uuid4())
        port_id2 = str(uuid.uuid4())
        trunk_id = str(uuid.uuid4())
        trunk_obj = self._get_trunk_obj(port_id=trunk_id,
                                        subport_id=port_id1)
        trunk_obj['sub_ports'].append({'port_id': port_id2,
                                       'segmentation_type': 'vlan',
                                       'segmentation_id': 101})
        port1 = fake.get_port_obj(port_id=port_id1,
                                  device_owner='trunk:subport')
        port2 = fake.get_port_obj(port_id=port_id2,
                                  device_owner='trunk:subport')

        p_ports = self._get_parent_ports([trunk_obj])
        a_subports = {port_id1: port1, port_id2: port2}
        subnet_id = port1.fixed_ips[0]['subnet_id']
        net_id = str(uuid.uuid4())
        _net = os_network.Network(
            id=net_id,
            name=None,
            mtu=None,
            provider_network_type=None,
        )
        network = ovu.neutron_to_osvif_network(_net)
        subnets = {subnet_id: {subnet_id: network}}

        m_driver._get_trunks_info.return_value = (p_ports, a_subports,
                                                  subnets)

        vif = mock.sentinel.vif
        m_to_osvif.return_value = vif

        pool_key = (port1.binding_host_id, port1.project_id, net_id)
        m_driver._get_pool_key.return_value = pool_key
        cls._precreated_ports(m_driver, 'recover')

        m_driver._get_trunks_info.assert_called_once()
        self.assertEqual(m_driver._existing_vifs, {port_id1: vif,
                                                   port_id2: vif})
        self.assertEqual(m_driver._available_ports_pools[pool_key],
                         {tuple(port1.security_group_ids): [port_id1,
                                                            port_id2]})
        os_net.delete_port.assert_not_called()

    @ddt.data(('recover'), ('free'))
    def test__precreated_ports_no_ports(self, m_action):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {}

        port_id = mock.sentinel.port_id
        trunk_id = mock.sentinel.trunk_id
        trunk_obj = self._get_trunk_obj(port_id=trunk_id, subport_id=port_id)

        p_ports = self._get_parent_ports([trunk_obj])
        a_subports = {}
        subnets = {}
        m_driver._get_trunks_info.return_value = (p_ports, a_subports,
                                                  subnets)

        cls._precreated_ports(m_driver, m_action)

        m_driver._get_trunks_info.assert_called_once()
        self.assertEqual(m_driver._existing_vifs, {})
        self.assertEqual(m_driver._available_ports_pools, {})
        os_net.delete_port.assert_not_called()

    @ddt.data(('recover'), ('free'))
    def test__precreated_ports_no_trunks(self, m_action):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._existing_vifs = {}
        oslo_cfg.CONF.set_override('port_debug',
                                   True,
                                   group='kubernetes')

        port_id = str(uuid.uuid4())
        port = fake.get_port_obj(port_id=port_id,
                                 device_owner='trunk:subport')

        p_ports = {}
        a_subports = {}
        subnet_id = port.fixed_ips[0]['subnet_id']
        subnet = mock.sentinel.subnet
        subnets = {subnet_id: {subnet_id: subnet}}
        m_driver._get_trunks_info.return_value = (p_ports, a_subports,
                                                  subnets)
        cls._precreated_ports(m_driver, m_action)
        m_driver._get_trunks_info.assert_called_once()
        self.assertEqual(m_driver._existing_vifs, {})
        self.assertEqual(m_driver._available_ports_pools, {})
        os_net.delete_port.assert_not_called()

    @mock.patch('eventlet.GreenPool')
    def test_delete_network_pools(self, m_green_pool):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver
        m_pool = mock.MagicMock()
        m_green_pool.return_value = m_pool

        net_id = mock.sentinel.net_id
        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        trunk_id = str(uuid.uuid4())
        vif = mock.MagicMock()
        vlan_id = mock.sentinel.vlan_id
        vif.vlan_id = vlan_id
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][('sg',)] = [port_id]
        m_driver._lock = threading.Lock()
        m_driver._populate_pool_lock = {
            pool_key: mock.MagicMock(spec=threading.Lock())}
        m_driver._existing_vifs = {port_id: vif}
        m_driver._recovered_pools = True

        m_driver._get_trunk_id.return_value = trunk_id
        m_driver._get_pool_key_net.return_value = net_id

        cls.delete_network_pools(m_driver, net_id)

        m_driver._trigger_return_to_pool.assert_called_once()
        m_driver._get_pool_key_net.assert_called_once()
        m_driver._get_trunk_id.assert_called_once_with(pool_key)
        m_driver._drv_vif._remove_subports.assert_called_once_with(trunk_id,
                                                                   [port_id])
        m_driver._drv_vif._release_vlan_id.assert_called_once_with(vlan_id)
        m_pool.imap.assert_called_once_with(utils.delete_neutron_port,
                                            [port_id])

    def test_delete_network_pools_not_ready(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver
        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        net_id = mock.sentinel.net_id
        m_driver._recovered_pools = False

        self.assertRaises(exceptions.ResourceNotReady,
                          cls.delete_network_pools, m_driver, net_id)

        m_driver._trigger_return_to_pool.assert_not_called()
        m_driver._get_pool_key_net.assert_not_called()
        m_driver._get_trunk_id.assert_not_called()
        m_driver._drv_vif._remove_subports.assert_not_called()
        os_net.delete_port.assert_not_called()

    def test_delete_network_pools_exception(self):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver

        os_net = self.useFixture(k_fix.MockNetworkClient()).client

        net_id = mock.sentinel.net_id
        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        trunk_id = str(uuid.uuid4())
        vif = mock.MagicMock()
        vlan_id = mock.sentinel.vlan_id
        vif.vlan_id = vlan_id
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][('sg',)] = [port_id]
        m_driver._existing_vifs = {port_id: vif}
        m_driver._recovered_pools = True

        m_driver._get_trunk_id.return_value = trunk_id
        m_driver._get_pool_key_net.return_value = net_id
        m_driver._drv_vif._remove_subports.side_effect = os_exc.SDKException

        self.assertRaises(exceptions.ResourceNotReady,
                          cls.delete_network_pools, m_driver, net_id)

        m_driver._trigger_return_to_pool.assert_called_once()
        m_driver._get_pool_key_net.assert_called_once()
        m_driver._get_trunk_id.assert_called_once_with(pool_key)
        m_driver._drv_vif._remove_subports.assert_called_once_with(trunk_id,
                                                                   [port_id])
        m_driver._drv_vif._release_vlan_id.assert_not_called()
        os_net.delete_port.assert_not_called()

    @mock.patch('eventlet.GreenPool')
    def test_delete_network_pools_missing_port(self, m_green_pool):
        cls = vif_pool.NestedVIFPool
        m_driver = mock.MagicMock(spec=cls)
        cls_vif_driver = nested_vlan_vif.NestedVlanPodVIFDriver
        vif_driver = mock.MagicMock(spec=cls_vif_driver)
        m_driver._drv_vif = vif_driver
        m_pool = mock.MagicMock()
        m_green_pool.return_value = m_pool

        net_id = mock.sentinel.net_id
        pool_key = ('node_ip', 'project_id')
        port_id = str(uuid.uuid4())
        trunk_id = str(uuid.uuid4())
        vif = mock.MagicMock()
        vlan_id = mock.sentinel.vlan_id
        vif.vlan_id = vlan_id
        m_driver._available_ports_pools = AVAILABLE_PORTS_TYPE()
        m_driver._available_ports_pools[pool_key][('sg',)] = [port_id]
        m_driver._lock = threading.Lock()
        m_driver._populate_pool_lock = {
            pool_key: mock.MagicMock(spec=threading.Lock())}
        m_driver._existing_vifs = {}
        m_driver._recovered_pools = True

        m_driver._get_trunk_id.return_value = trunk_id
        m_driver._get_pool_key_net.return_value = net_id

        cls.delete_network_pools(m_driver, net_id)

        m_driver._trigger_return_to_pool.assert_called_once()
        m_driver._get_pool_key_net.assert_called_once()
        m_driver._get_trunk_id.assert_called_once_with(pool_key)
        m_driver._drv_vif._remove_subports.assert_called_once_with(trunk_id,
                                                                   [port_id])
        m_driver._drv_vif._release_vlan_id.assert_not_called()
        m_pool.imap.assert_called_once_with(utils.delete_neutron_port,
                                            [port_id])
