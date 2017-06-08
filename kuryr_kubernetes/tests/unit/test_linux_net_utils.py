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
from oslo_concurrency import processutils as utils

from kuryr_kubernetes import linux_net_utils as linux_net
from kuryr_kubernetes.tests import base as test_base


class LinuxNetworkUtilsTestCase(test_base.TestCase):

    def test_ovs_vif_port_cmd(self):
        expected = ['--', '--if-exists',
                    'del-port', 'fake-dev', '--', 'add-port',
                    'fake-bridge', 'fake-dev',
                    '--', 'set', 'Interface', 'fake-dev',
                    'external-ids:iface-id=fake-iface-id',
                    'external-ids:iface-status=active',
                    'external-ids:attached-mac=fake-mac',
                    'external-ids:vm-uuid=fake-instance-uuid']
        cmd = linux_net._create_ovs_vif_cmd('fake-bridge', 'fake-dev',
                                            'fake-iface-id', 'fake-mac',
                                            'fake-instance-uuid')

        self.assertEqual(expected, cmd)

    def test_create_ovs_vif_port(self):
        calls = [
            mock.call('ovs-vsctl', '--', '--if-exists',
                      'del-port', 'fake-dev', '--', 'add-port',
                      'fake-bridge', 'fake-dev',
                      '--', 'set', 'Interface', 'fake-dev',
                      'external-ids:iface-id=fake-iface-id',
                      'external-ids:iface-status=active',
                      'external-ids:attached-mac=fake-mac',
                      'external-ids:vm-uuid=fake-instance-uuid',
                      run_as_root=True)]
        with mock.patch.object(utils, 'execute', return_value=('', '')) as ex:
            linux_net.create_ovs_vif_port('fake-bridge', 'fake-dev',
                                          'fake-iface-id', 'fake-mac',
                                          'fake-instance-uuid')
            ex.assert_has_calls(calls)

    def test_delete_ovs_vif_port(self):
        calls = [
            mock.call('ovs-vsctl', '--', '--if-exists',
                      'del-port', 'fake-bridge', 'fake-dev',
                      run_as_root=True)]
        with mock.patch.object(utils, 'execute', return_value=('', '')) as ex:
            linux_net.delete_ovs_vif_port('fake-bridge', 'fake-dev')
            ex.assert_has_calls(calls)
