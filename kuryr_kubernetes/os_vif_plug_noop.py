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

from os_vif import objects
from os_vif.plugin import PluginBase

from kuryr_kubernetes.objects import vif as k_vif


class NoOpPlugin(PluginBase):
    """No Op Plugin to be used with VIF types that dont need plugging"""

    def describe(self):
        return objects.host_info.HostPluginInfo(
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

    def plug(self, vif, instance_info):
        pass

    def unplug(self, vif, instance_info):
        pass


class SriovPlugin(PluginBase):
    """Sriov Plugin to be used with sriov VIFS"""

    def describe(self):
        return objects.host_info.HostPluginInfo(
            plugin_name='sriov',
            vif_info=[
                objects.host_info.HostVIFInfo(
                    vif_object_name=objects.vif.VIFDirect.__name__,
                    min_version="1.0",
                    max_version="1.0"),
            ])

    def plug(self, vif, instance_info):
        pass

    def unplug(self, vif, instance_info):
        pass
