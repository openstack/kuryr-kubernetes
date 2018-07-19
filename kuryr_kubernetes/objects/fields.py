# Copyright (c) 2016 Mirantis, Inc.
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

from os_vif.objects import vif
from oslo_versionedobjects import fields as obj_fields


class ListOfUUIDField(obj_fields.AutoTypedField):
    AUTO_TYPE = obj_fields.List(obj_fields.UUID())


class DictOfVIFsField(obj_fields.AutoTypedField):
    AUTO_TYPE = obj_fields.Dict(obj_fields.Object(vif.VIFBase.__name__,
                                                  subclasses=True))
