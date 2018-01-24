# Copyright (c) 2018 RedHat, Inc.
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
from kuryr_kubernetes.objects import base as k_obj
from kuryr_kubernetes.objects import lbaas as lbaas_obj
from oslo_versionedobjects import base as obj_base
from oslo_versionedobjects import fields as obj_fields


@obj_base.VersionedObjectRegistry.register
class RouteState(k_obj.KuryrK8sObjectBase):
    VERSION = '1.0'
    fields = {
        'router_pool': obj_fields.ObjectField(
            lbaas_obj.LBaaSPool.__name__, nullable=True, default=None),
        'l7_policy': obj_fields.ObjectField(
            lbaas_obj.LBaaSL7Policy.__name__, nullable=True, default=None),
        'h_l7_rule': obj_fields.ObjectField(
            lbaas_obj.LBaaSL7Rule.__name__, nullable=True, default=None),
        'p_l7_rule': obj_fields.ObjectField(
            lbaas_obj.LBaaSL7Rule.__name__, nullable=True, default=None),
    }


@obj_base.VersionedObjectRegistry.register
class RouteSpec(k_obj.KuryrK8sObjectBase):
    VERSION = '1.0'
    fields = {
        'host': obj_fields.StringField(nullable=True, default=None),
        'path': obj_fields.StringField(nullable=True, default=None),
        'to_service': obj_fields.StringField(nullable=True, default=None),
    }
