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

import ddt
import mock
import threading

from kuryr.lib import utils as lib_utils
from neutronclient.common import exceptions as n_exc

from kuryr_kubernetes.controller.drivers import nested_macvlan_vif
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix


@ddt.ddt
class TestNestedMacvlanPodVIFDriver(test_base.TestCase):

    @mock.patch(
        'kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif_nested_macvlan')
    def test_request_vif(self, m_to_vif):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = mock.sentinel.security_groups
        container_mac = mock.sentinel.mac_address
        container_ip = mock.sentinel.ip_address
        container_port = self._get_fake_port(mac_address=container_mac,
                                             ip_address=container_ip)

        vif = mock.Mock()
        port_request = mock.sentinel.port_request
        vm_port = self._get_fake_port()

        m_to_vif.return_value = vif
        m_driver._get_port_request.return_value = port_request
        m_driver._get_parent_port.return_value = vm_port
        m_driver._try_update_port.return_value = 0
        m_driver.lock = mock.MagicMock(spec=threading.Lock())
        neutron.create_port.return_value = container_port

        self.assertEqual(vif, cls.request_vif(m_driver, pod, project_id,
                                              subnets, security_groups))

        m_driver._get_port_request.assert_called_once_with(
            pod, project_id, subnets, security_groups)
        neutron.create_port.assert_called_once_with(port_request)
        m_driver._get_parent_port.assert_called_once_with(neutron, pod)
        m_driver._try_update_port.assert_called_once()
        m_to_vif.assert_called_once_with(container_port['port'], subnets)

    @mock.patch(
        'kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif_nested_macvlan')
    def test_request_vif_port_create_failed(self, m_to_vif):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = mock.sentinel.security_groups

        port_request = mock.sentinel.port_request
        m_driver._get_port_request.return_value = port_request
        neutron.create_port.side_effect = n_exc.NeutronClientException

        self.assertRaises(n_exc.NeutronClientException, cls.request_vif,
                          m_driver, pod, project_id, subnets, security_groups)
        m_driver._get_port_request.assert_called_once_with(
            pod, project_id, subnets, security_groups)
        neutron.create_port.assert_called_once_with(port_request)
        m_driver._try_update_port.assert_not_called()
        m_to_vif.assert_not_called()

    @mock.patch(
        'kuryr_kubernetes.os_vif_util.neutron_to_osvif_vif_nested_macvlan')
    def test_request_vif_parent_not_found(self, m_to_vif):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pod = mock.sentinel.pod
        project_id = mock.sentinel.project_id
        subnets = mock.sentinel.subnets
        security_groups = mock.sentinel.security_groups
        container_mac = mock.sentinel.mac_address
        container_ip = mock.sentinel.ip_address
        container_port = self._get_fake_port(mac_address=container_mac,
                                             ip_address=container_ip)

        port_request = mock.sentinel.port_request
        m_driver._get_port_request.return_value = port_request
        m_driver.lock = mock.MagicMock(spec=threading.Lock())
        neutron.create_port.return_value = container_port
        m_driver._get_parent_port.side_effect = n_exc.NeutronClientException

        self.assertRaises(n_exc.NeutronClientException, cls.request_vif,
                          m_driver, pod, project_id, subnets, security_groups)
        m_driver._get_port_request.assert_called_once_with(
            pod, project_id, subnets, security_groups)
        neutron.create_port.assert_not_called()
        m_driver._get_parent_port.assert_called_once_with(neutron, pod)
        m_driver._try_update_port.assert_not_called()
        m_to_vif.assert_not_called()

    def test_release_vif(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        pod = mock.sentinel.pod
        vif = mock.Mock()
        vif.id = port_id

        container_mac = mock.sentinel.mac_address
        container_ip = mock.sentinel.ip_address
        container_port = self._get_fake_port(port_id, container_ip,
                                             container_mac)
        neutron.show_port.return_value = container_port

        vm_port = self._get_fake_port()
        m_driver._get_parent_port.return_value = vm_port
        m_driver._try_update_port.return_value = 0
        m_driver.lock = mock.MagicMock(spec=threading.Lock())

        cls.release_vif(m_driver, pod, vif)

        neutron.show_port.assert_called_once_with(port_id)
        m_driver._get_parent_port.assert_called_once_with(neutron, pod)
        m_driver._try_update_port.assert_called_once()
        neutron.delete_port.assert_called_once_with(vif.id)

    def test_release_vif_not_found(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        pod = mock.sentinel.pod
        vif = mock.Mock()
        vif.id = lib_utils.get_hash()

        neutron.show_port.side_effect = n_exc.PortNotFoundClient

        self.assertRaises(n_exc.PortNotFoundClient, cls.release_vif,
                          m_driver, pod, vif)
        m_driver._remove_from_allowed_address_pairs.assert_not_called()
        neutron.delete_port.assert_not_called()

    def test_release_vif_parent_not_found(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        pod = mock.sentinel.pod
        vif = mock.Mock()
        vif.id = port_id

        container_mac = mock.sentinel.mac_address
        container_ip = mock.sentinel.ip_address
        container_port = self._get_fake_port(port_id, container_ip,
                                             container_mac)
        neutron.show_port.return_value = container_port

        m_driver.lock = mock.MagicMock(spec=threading.Lock())
        m_driver._get_parent_port.side_effect = n_exc.NeutronClientException

        self.assertRaises(n_exc.NeutronClientException, cls.release_vif,
                          m_driver, pod, vif)
        neutron.show_port.assert_called_with(port_id)
        self.assertEqual(neutron.show_port.call_count, 1)
        m_driver._get_parent_port.assert_called_with(neutron, pod)
        self.assertEqual(m_driver._get_parent_port.call_count, 1)
        m_driver._remove_from_allowed_address_pairs.assert_not_called()
        neutron.delete_port.assert_not_called()

    def test_release_vif_delete_failed(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        pod = mock.sentinel.pod
        vif = mock.Mock()
        vif.id = port_id

        container_mac = mock.sentinel.mac_address
        container_ip = mock.sentinel.ip_addresses
        container_port = self._get_fake_port(port_id, container_ip,
                                             container_mac)
        neutron.show_port.return_value = container_port
        neutron.delete_port.side_effect = n_exc.PortNotFoundClient

        vm_port = self._get_fake_port()
        m_driver._get_parent_port.return_value = vm_port
        m_driver._try_update_port.return_value = 0
        m_driver.lock = mock.MagicMock(spec=threading.Lock())

        cls.release_vif(m_driver, pod, vif)

        neutron.show_port.assert_called_once_with(port_id)
        m_driver._get_parent_port.assert_called_once_with(neutron, pod)
        m_driver._try_update_port.assert_called_once()
        neutron.delete_port.assert_called_once_with(vif.id)

    @ddt.data((False), (True))
    def test_activate_vif(self, active_value):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        pod = mock.sentinel.pod
        vif = mock.Mock()
        vif.active = active_value

        cls.activate_vif(m_driver, pod, vif)

        self.assertEqual(vif.active, True)

    @ddt.data((None), ('fa:16:3e:71:cb:80'))
    def test_add_to_allowed_address_pairs(self, m_mac):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']

        mac_addr = 'fa:16:3e:1b:30:00' if m_mac else vm_port['mac_address']
        address_pairs = [
            {'ip_address': '10.0.0.30',
             'mac_address': mac_addr},
            {'ip_address': 'fe80::f816:3eff:fe1c:36a9',
             'mac_address': mac_addr},
        ]
        vm_port['allowed_address_pairs'].extend(address_pairs)

        ip_addr = '10.0.0.29'
        address_pairs.append(
            {'ip_address': ip_addr,
             'mac_address': m_mac if m_mac else vm_port['mac_address']}
        )

        cls._add_to_allowed_address_pairs(m_driver, neutron, vm_port,
                                          frozenset([ip_addr]), m_mac)

        m_driver._update_port_address_pairs.assert_called_once_with(
            neutron, port_id, address_pairs, revision_number=1)

    def test_add_to_allowed_address_pairs_no_ip_addresses(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']

        self.assertRaises(k_exc.IntegrityError,
                          cls._add_to_allowed_address_pairs, m_driver,
                          neutron, vm_port, frozenset())

    def test_add_to_allowed_address_pairs_same_ip(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']
        address_pairs = [
            {'ip_address': '10.0.0.30',
             'mac_address': 'fa:16:3e:1b:30:00'},
            {'ip_address': 'fe80::f816:3eff:fe1c:36a9',
             'mac_address': 'fa:16:3e:1b:30:00'},
        ]
        vm_port['allowed_address_pairs'].extend(address_pairs)

        mac_addr = 'fa:16:3e:71:cb:80'
        ip_addr = '10.0.0.30'
        address_pairs.append({'ip_address': ip_addr, 'mac_address': mac_addr})

        cls._add_to_allowed_address_pairs(m_driver, neutron, vm_port,
                                          frozenset([ip_addr]), mac_addr)

        m_driver._update_port_address_pairs.assert_called_once_with(
            neutron, port_id, address_pairs, revision_number=1)

    def test_add_to_allowed_address_pairs_already_present(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']
        address_pairs = [
            {'ip_address': '10.0.0.30',
             'mac_address': 'fa:16:3e:1b:30:00'},
            {'ip_address': 'fe80::f816:3eff:fe1c:36a9',
             'mac_address': 'fa:16:3e:1b:30:00'},
        ]
        vm_port['allowed_address_pairs'].extend(address_pairs)

        mac_addr = 'fa:16:3e:1b:30:00'
        ip_addr = '10.0.0.30'

        self.assertRaises(k_exc.AllowedAddressAlreadyPresent,
                          cls._add_to_allowed_address_pairs, m_driver, neutron,
                          vm_port, frozenset([ip_addr]), mac_addr)

    @ddt.data((None), ('fa:16:3e:71:cb:80'))
    def test_remove_from_allowed_address_pairs(self, m_mac):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']

        mac_addr = 'fa:16:3e:1b:30:00' if m_mac else vm_port['mac_address']
        address_pairs = [
            {'ip_address': '10.0.0.30',
             'mac_address': mac_addr},
            {'ip_address': 'fe80::f816:3eff:fe1c:36a9',
             'mac_address': mac_addr},
        ]
        vm_port['allowed_address_pairs'].extend(address_pairs)

        ip_addr = '10.0.0.29'
        vm_port['allowed_address_pairs'].append(
            {'ip_address': ip_addr,
             'mac_address': m_mac if m_mac else vm_port['mac_address']}
        )

        cls._remove_from_allowed_address_pairs(
            m_driver, neutron, vm_port, frozenset([ip_addr]), m_mac)

        m_driver._update_port_address_pairs.assert_called_once_with(
            neutron, port_id, address_pairs, revision_number=1)

    def test_remove_from_allowed_address_pairs_no_ip_addresses(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']

        self.assertRaises(k_exc.IntegrityError,
                          cls._remove_from_allowed_address_pairs, m_driver,
                          neutron, vm_port, frozenset())

    @ddt.data((None), ('fa:16:3e:71:cb:80'))
    def test_remove_from_allowed_address_pairs_missing(self, m_mac):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']

        mac_addr = 'fa:16:3e:1b:30:00' if m_mac else vm_port['mac_address']
        address_pairs = [
            {'ip_address': '10.0.0.30',
             'mac_address': mac_addr},
            {'ip_address': 'fe80::f816:3eff:fe1c:36a9',
             'mac_address': mac_addr},
        ]
        mac_addr = m_mac if m_mac else vm_port['mac_address']
        vm_port['allowed_address_pairs'].extend(address_pairs)
        vm_port['allowed_address_pairs'].append({'ip_address': '10.0.0.28',
                                                 'mac_address': mac_addr})
        ip_addr = ['10.0.0.29', '10.0.0.28']

        cls._remove_from_allowed_address_pairs(
            m_driver, neutron, vm_port, frozenset(ip_addr), m_mac)

        m_driver._update_port_address_pairs.assert_called_once_with(
            neutron, port_id, address_pairs, revision_number=1)

    @ddt.data((None), ('fa:16:3e:71:cb:80'))
    def test_remove_from_allowed_address_pairs_no_update(self, m_mac):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']

        mac_addr = 'fa:16:3e:1b:30:00' if m_mac else vm_port['mac_address']
        address_pairs = [
            {'ip_address': '10.0.0.30',
             'mac_address': mac_addr},
            {'ip_address': 'fe80::f816:3eff:fe1c:36a9',
             'mac_address': mac_addr},
        ]
        vm_port['allowed_address_pairs'].extend(address_pairs)

        ip_addr = ['10.0.0.29']

        cls._remove_from_allowed_address_pairs(
            m_driver, neutron, vm_port, frozenset(ip_addr), m_mac)

        m_driver._update_port_address_pairs.assert_not_called()

    def test_update_port_address_pairs(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        pairs = mock.sentinel.allowed_address_pairs

        cls._update_port_address_pairs(m_driver, neutron, port_id, pairs,
                                       revision_number=1)

        neutron.update_port.assert_called_with(
            port_id,
            {'port': {'allowed_address_pairs': pairs}},
            revision_number=1)

    def test_update_port_address_pairs_failure(self):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        pairs = mock.sentinel.allowed_address_pairs
        neutron.update_port.side_effect = n_exc.NeutronClientException

        self.assertRaises(n_exc.NeutronClientException,
                          cls._update_port_address_pairs, m_driver, neutron,
                          port_id, pairs, revision_number=1)

        neutron.update_port.assert_called_with(
            port_id,
            {'port': {'allowed_address_pairs': pairs}},
            revision_number=1)

    @mock.patch('kuryr_kubernetes.controller.drivers.nested_macvlan_vif.'
                'NestedMacvlanPodVIFDriver._add_to_allowed_address_pairs')
    def test_try_update_port(self, aaapf_mock):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        m_driver.lock = mock.MagicMock(spec=threading.Lock())
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']

        mac_addr = 'fa:16:3e:1b:30:00'
        address_pairs = [
            {'ip_address': '10.0.0.30',
             'mac_address': mac_addr},
            {'ip_address': 'fe80::f816:3eff:fe1c:36a9',
             'mac_address': mac_addr},
        ]
        vm_port['allowed_address_pairs'].extend(address_pairs)

        ip_addr = ['10.0.0.29']
        attempts = cls._try_update_port(m_driver, 3,
                                        cls._add_to_allowed_address_pairs,
                                        neutron, vm_port, frozenset(ip_addr),
                                        mac_addr)
        self.assertEqual(attempts, 0)
        aaapf_mock.assert_called_once()

    @mock.patch('kuryr_kubernetes.controller.drivers.nested_macvlan_vif.'
                'NestedMacvlanPodVIFDriver._add_to_allowed_address_pairs')
    def test_try_update_port_failure(self, aaapf_mock):
        cls = nested_macvlan_vif.NestedMacvlanPodVIFDriver
        m_driver = mock.Mock(spec=cls)
        m_driver.lock = mock.MagicMock(spec=threading.Lock())
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        port_id = lib_utils.get_hash()
        vm_port = self._get_fake_port(port_id)['port']

        mac_addr = 'fa:16:3e:1b:30:00'
        address_pairs = [
            {'ip_address': '10.0.0.30',
             'mac_address': mac_addr},
            {'ip_address': 'fe80::f816:3eff:fe1c:36a9',
             'mac_address': mac_addr},
        ]
        vm_port['allowed_address_pairs'].extend(address_pairs)

        ip_addr = ['10.0.0.29']

        aaapf_mock.side_effect = n_exc.NeutronClientException
        self.assertRaises(n_exc.NeutronClientException,
                          cls._try_update_port, m_driver, 1,
                          cls._add_to_allowed_address_pairs,
                          neutron, vm_port, frozenset(ip_addr), mac_addr)

    # TODO(garyloug) consider exending and moving to a parent class
    def _get_fake_port(self, port_id=None, ip_address=None, mac_address=None):
        fake_port = {
            'port': {
                "mac_address": "fa:16:3e:20:57:c4",
                "fixed_ips": [],
                "id": "07b21ebf-b105-4720-9f2e-95670c4032e4",
                "allowed_address_pairs": [],
                "revision_number": 1
            }
        }

        if port_id:
            fake_port['port']['id'] = port_id

        if ip_address:
            fake_port['port']['fixed_ips'].append({
                "subnet_id": lib_utils.get_hash(),
                "ip_address": ip_address
            })

        if mac_address:
            fake_port['port']['mac_address'] = mac_address

        return fake_port

    def _get_fake_ports(self, ip_address, mac_address):
        fake_port = self._get_fake_port(ip_address=ip_address,
                                        mac_address=mac_address)
        fake_port = fake_port['port']
        fake_ports = {
            'ports': [
                fake_port
            ]
        }
        return fake_ports
