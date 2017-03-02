# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock
from stevedore import extension

import os_vif
from os_vif import objects

from kuryr_kubernetes.objects import vif as k_vif
from kuryr_kubernetes.os_vif_plug_noop import NoOpPlugin
from kuryr_kubernetes.tests import base


class TestNoOpPlugin(base.TestCase):

    def setUp(self):
        super(TestNoOpPlugin, self).setUp()
        os_vif._EXT_MANAGER = None

    @mock.patch('stevedore.extension.ExtensionManager')
    def test_initialize(self, mock_EM):
        self.assertIsNone(os_vif._EXT_MANAGER)
        os_vif.initialize()
        mock_EM.assert_called_once_with(
            invoke_on_load=False, namespace='os_vif')
        self.assertIsNotNone(os_vif._EXT_MANAGER)

    @mock.patch.object(NoOpPlugin, "plug")
    def test_plug(self, mock_plug):
        plg = extension.Extension(name="noop",
                                  entry_point="os-vif",
                                  plugin=NoOpPlugin,
                                  obj=None)
        with mock.patch('stevedore.extension.ExtensionManager.names',
                        return_value=['foobar']),\
                mock.patch('stevedore.extension.ExtensionManager.__getitem__',
                           return_value=plg):
            os_vif.initialize()
            info = mock.sentinel.info
            vif = mock.MagicMock()
            vif.plugin_name = 'noop'
            os_vif.plug(vif, info)
            mock_plug.assert_called_once_with(vif, info)

    @mock.patch.object(NoOpPlugin, "unplug")
    def test_unplug(self, mock_unplug):
        plg = extension.Extension(name="demo",
                                  entry_point="os-vif",
                                  plugin=NoOpPlugin,
                                  obj=None)
        with mock.patch('stevedore.extension.ExtensionManager.names',
                        return_value=['foobar']),\
                mock.patch('stevedore.extension.ExtensionManager.__getitem__',
                           return_value=plg):
            os_vif.initialize()
            info = mock.sentinel.info
            vif = mock.MagicMock()
            vif.plugin_name = 'noop'
            os_vif.unplug(vif, info)
            mock_unplug.assert_called_once_with(vif, info)

    def test_describe_noop_plugin(self):
        os_vif.initialize()
        noop_plugin = NoOpPlugin.load('noop')
        result = noop_plugin.describe()

        expected = objects.host_info.HostPluginInfo(
            plugin_name='noop',
            vif_info=[
                objects.host_info.HostVIFInfo(
                    vif_object_name=k_vif.VIFVlanNested.__name__,
                    min_version="1.0",
                    max_version="1.0"),
                objects.host_info.HostVIFInfo(
                    vif_object_name=k_vif.VIFMacvlanNested.__name__,
                    min_version="1.0",
                    max_version="1.0"),
            ])
        self.assertEqual(expected, result)
