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

from oslo_versionedobjects import base as obj_base
from oslo_versionedobjects import fields as obj_fields

from os_vif.objects import vif as obj_osvif

from kuryr_kubernetes import constants
from kuryr_kubernetes.objects import base
from kuryr_kubernetes.objects import fields


@obj_base.VersionedObjectRegistry.register
class PodState(base.KuryrK8sObjectBase):
    VERSION = '1.0'

    # FIXME(dulek): I know it's an ugly hack, but turns out you cannot
    #               serialize-deserialize objects containing objects from
    #               different namespaces, so we need 'os_vif' namespace here.
    OBJ_PROJECT_NAMESPACE = 'os_vif'

    fields = {
        'default_vif': obj_fields.ObjectField(obj_osvif.VIFBase.__name__,
                                              subclasses=True, nullable=False),
        'additional_vifs': fields.DictOfVIFsField(default={}),
    }

    @property
    def vifs(self):
        d = {
            constants.DEFAULT_IFNAME: self.default_vif,
        }
        d.update(self.additional_vifs)
        return d


@obj_base.VersionedObjectRegistry.register
class VIFVlanNested(obj_osvif.VIFBase):
    # This is OVO based vlan vif.

    VERSION = '1.0'

    fields = {
        # Name of the device to create
        'vif_name': obj_fields.StringField(),
        # vlan ID allocated to this vif
        'vlan_id': obj_fields.IntegerField()
    }


@obj_base.VersionedObjectRegistry.register
class VIFMacvlanNested(obj_osvif.VIFBase):
    # This is OVO based macvlan vif.

    VERSION = '1.0'

    fields = {
        # Name of the device to create
        'vif_name': obj_fields.StringField(),
    }


@obj_base.VersionedObjectRegistry.register
class VIFSriov(obj_osvif.VIFDirect):
    # This is OVO based SRIOV vif.
    # Version 1.0: Initial version
    # Version 1.1: Added pod_name field and pod_link field.
    VERSION = '1.1'

    fields = {
        # physnet of the VIF
        'physnet': obj_fields.StringField(),
        'pod_name': obj_fields.StringField(),
        'pod_link': obj_fields.StringField(),
    }
