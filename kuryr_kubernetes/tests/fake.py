# Copyright (c) 2017 Red Hat.
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

import uuid

from os_vif import objects as osv_objects
from os_vif.objects import vif as osv_vif
from oslo_serialization import jsonutils


def _fake_vif(cls=osv_vif.VIFOpenVSwitch):
    vif = cls(
        id=uuid.uuid4(),
        vif_name='h_interface',
        bridge_name='bridge',
        address='3e:94:b7:31:a0:83',
        port_profile=osv_objects.vif.VIFPortProfileOpenVSwitch(
            interface_id='89eccd45-43e9-43d8-b4cc-4c13db13f782',
            profile_id=str(uuid.uuid4()),
        ),
    )
    vif.network = osv_objects.network.Network(id=uuid.uuid4(), mtu=1)
    subnet = osv_objects.subnet.Subnet(
        uuid=uuid.uuid4(),
        dns=['192.168.0.1'],
        cidr='192.168.0.0/24',
        gateway='192.168.0.1',
        routes=osv_objects.route.RouteList(objects=[]),
    )
    subnet.ips = osv_objects.fixed_ip.FixedIPList(objects=[])
    subnet.ips.objects.append(
        osv_objects.fixed_ip.FixedIP(address='192.168.0.2'))
    vif.network.subnets.objects.append(subnet)
    vif.active = True
    return vif


def _fake_vif_dict(obj=None):
    if obj:
        return obj.obj_to_primitive()
    else:
        return _fake_vif().obj_to_primitive()


def _fake_vif_string(dictionary=None):
    if dictionary:
        return jsonutils.dumps(dictionary)
    else:
        return jsonutils.dumps(_fake_vif_dict())


def _fake_vifs(cls=osv_vif.VIFOpenVSwitch):
    return {'eth0': _fake_vif(cls)}


def _fake_vifs_dict(obj=None):
    if obj:
        return {
            ifname: vif.obj_to_primitive() for
            ifname, vif in obj.items()
        }
    else:
        return {
            ifname: vif.obj_to_primitive() for
            ifname, vif in _fake_vifs().items()
        }


def _fake_vifs_string(dictionary=None):
    if dictionary:
        return jsonutils.dumps(dictionary)
    else:
        return jsonutils.dumps(_fake_vifs_dict())
