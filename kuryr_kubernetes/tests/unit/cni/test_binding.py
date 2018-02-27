# Copyright 2017 Red Hat, Inc.
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

from os_vif import objects as osv_objects
from oslo_config import cfg

from kuryr_kubernetes.cni.binding import base
from kuryr_kubernetes import objects
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests import fake

CONF = cfg.CONF


class TestDriverMixin(test_base.TestCase):
    def setUp(self):
        super(TestDriverMixin, self).setUp()
        self.instance_info = osv_objects.instance_info.InstanceInfo(
            uuid=uuid.uuid4(), name='foo')
        self.ifname = 'c_interface'
        self.netns = '/proc/netns/1234'

        # Mock IPDB context managers
        self.ipdbs = {}
        self.m_bridge_iface = mock.Mock(__exit__=mock.Mock(return_value=None))
        self.m_c_iface = mock.Mock()
        self.m_h_iface = mock.Mock()
        self.h_ipdb, self.h_ipdb_exit = self._mock_ipdb_context_manager(None)
        self.c_ipdb, self.c_ipdb_exit = self._mock_ipdb_context_manager(
            self.netns)
        self.m_create = mock.Mock()
        self.h_ipdb.create = mock.Mock(
            return_value=mock.Mock(
                __enter__=mock.Mock(return_value=self.m_create),
                __exit__=mock.Mock(return_value=None)))
        self.c_ipdb.create = mock.Mock(
            return_value=mock.Mock(
                __enter__=mock.Mock(return_value=self.m_create),
                __exit__=mock.Mock(return_value=None)))

    def _mock_ipdb_context_manager(self, netns):
        mock_ipdb = mock.Mock(
            interfaces={
                'bridge': mock.Mock(
                    __enter__=mock.Mock(return_value=self.m_bridge_iface),
                    __exit__=mock.Mock(return_value=None),
                ),
                'c_interface': mock.Mock(
                    __enter__=mock.Mock(return_value=self.m_c_iface),
                    __exit__=mock.Mock(return_value=None),
                ),
                'h_interface': mock.Mock(
                    __enter__=mock.Mock(return_value=self.m_h_iface),
                    __exit__=mock.Mock(return_value=None),
                ),
            }
        )
        mock_exit = mock.Mock(return_value=None)
        self.ipdbs[netns] = mock.Mock(
            __enter__=mock.Mock(return_value=mock_ipdb),
            __exit__=mock_exit)
        return mock_ipdb, mock_exit

    @mock.patch('kuryr_kubernetes.cni.binding.base.get_ipdb')
    @mock.patch('os_vif.plug')
    def _test_connect(self, m_vif_plug, m_get_ipdb, report=None):
        def get_ipdb(netns=None):
            return self.ipdbs[netns]

        m_get_ipdb.side_effect = get_ipdb

        base.connect(self.vif, self.instance_info, self.ifname, self.netns,
                     report)
        m_vif_plug.assert_called_once_with(self.vif, self.instance_info)
        self.m_c_iface.add_ip.assert_called_once_with('192.168.0.2/24')
        if report:
            report.assert_called_once()

    @mock.patch('os_vif.unplug')
    def _test_disconnect(self, m_vif_unplug, report=None):
        base.disconnect(self.vif, self.instance_info, self.ifname, self.netns,
                        report)
        m_vif_unplug.assert_called_once_with(self.vif, self.instance_info)
        if report:
            report.assert_called_once()


class TestOpenVSwitchDriver(TestDriverMixin, test_base.TestCase):
    def setUp(self):
        super(TestOpenVSwitchDriver, self).setUp()
        self.vif = fake._fake_vif(osv_objects.vif.VIFOpenVSwitch)

    @mock.patch('kuryr_kubernetes.cni.plugins.k8s_cni_registry.'
                'K8sCNIRegistryPlugin.report_drivers_health')
    @mock.patch('os.getpid', mock.Mock(return_value=123))
    @mock.patch('kuryr_kubernetes.linux_net_utils.create_ovs_vif_port')
    def test_connect(self, mock_create_ovs, m_report):
        self._test_connect(report=m_report)
        self.assertEqual(3, self.h_ipdb_exit.call_count)
        self.assertEqual(2, self.c_ipdb_exit.call_count)
        self.c_ipdb.create.assert_called_once_with(
            ifname=self.ifname, peer='h_interface', kind='veth')
        self.assertEqual(1, self.m_create.mtu)
        self.assertEqual(str(self.vif.address),
                         self.m_create.address)
        self.m_create.up.assert_called_once_with()
        self.assertEqual(123, self.m_h_iface.net_ns_pid)
        self.assertEqual(1, self.m_h_iface.mtu)
        self.m_h_iface.up.assert_called_once_with()

        mock_create_ovs.assert_called_once_with(
            'bridge', 'h_interface', '89eccd45-43e9-43d8-b4cc-4c13db13f782',
            '3e:94:b7:31:a0:83', 'kuryr')

    @mock.patch('kuryr_kubernetes.cni.plugins.k8s_cni_registry.'
                'K8sCNIRegistryPlugin.report_drivers_health')
    @mock.patch('kuryr_kubernetes.linux_net_utils.delete_ovs_vif_port')
    def test_disconnect(self, mock_delete_ovs, m_report):
        self._test_disconnect(report=m_report)
        mock_delete_ovs.assert_called_once_with('bridge', 'h_interface')


class TestBridgeDriver(TestDriverMixin, test_base.TestCase):
    def setUp(self):
        super(TestBridgeDriver, self).setUp()
        self.vif = fake._fake_vif(osv_objects.vif.VIFBridge)

    @mock.patch('os.getpid', mock.Mock(return_value=123))
    def test_connect(self):
        self._test_connect()

        self.m_h_iface.remove.assert_called_once_with()

        self.assertEqual(3, self.h_ipdb_exit.call_count)
        self.assertEqual(2, self.c_ipdb_exit.call_count)
        self.c_ipdb.create.assert_called_once_with(
            ifname=self.ifname, peer='h_interface', kind='veth')
        self.assertEqual(1, self.m_create.mtu)
        self.assertEqual(str(self.vif.address),
                         self.m_create.address)
        self.m_create.up.assert_called_once_with()
        self.assertEqual(123, self.m_h_iface.net_ns_pid)
        self.assertEqual(1, self.m_h_iface.mtu)
        self.m_h_iface.up.assert_called_once_with()

        self.m_bridge_iface.add_port.assert_called_once_with('h_interface')

    def test_disconnect(self):
        self._test_disconnect()


class TestNestedVlanDriver(TestDriverMixin, test_base.TestCase):
    def setUp(self):
        super(TestNestedVlanDriver, self).setUp()
        self.vif = fake._fake_vif(objects.vif.VIFVlanNested)
        self.vif.vlan_id = 7
        CONF.set_override('link_iface', 'bridge', group='binding')
        self.addCleanup(CONF.clear_override, 'link_iface', group='binding')

    def test_connect(self):
        self._test_connect()

        self.assertEqual(1, self.h_ipdb_exit.call_count)
        self.assertEqual(2, self.c_ipdb_exit.call_count)

        self.assertEqual(self.ifname, self.m_h_iface.ifname)
        self.assertEqual(1, self.m_h_iface.mtu)
        self.assertEqual(str(self.vif.address), self.m_h_iface.address)
        self.m_h_iface.up.assert_called_once_with()

    def test_disconnect(self):
        self._test_disconnect()


class TestNestedMacvlanDriver(TestDriverMixin, test_base.TestCase):
    def setUp(self):
        super(TestNestedMacvlanDriver, self).setUp()
        self.vif = fake._fake_vif(objects.vif.VIFMacvlanNested)
        CONF.set_override('link_iface', 'bridge', group='binding')
        self.addCleanup(CONF.clear_override, 'link_iface', group='binding')

    def test_connect(self):
        self._test_connect()

        self.assertEqual(1, self.h_ipdb_exit.call_count)
        self.assertEqual(2, self.c_ipdb_exit.call_count)

        self.assertEqual(self.ifname, self.m_h_iface.ifname)
        self.assertEqual(1, self.m_h_iface.mtu)
        self.assertEqual(str(self.vif.address), self.m_h_iface.address)
        self.m_h_iface.up.assert_called_once_with()

    def test_disconnect(self):
        self._test_disconnect()
