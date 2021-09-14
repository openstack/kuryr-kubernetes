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

from openstack.network.v2 import port as os_port
from openstack.network.v2 import security_group_rule as os_sgr
from os_vif import objects as osv_objects
from os_vif.objects import vif as osv_vif
from oslo_serialization import jsonutils

from kuryr_kubernetes import constants


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


def _fake_vifs(cls=osv_vif.VIFOpenVSwitch, prefix='eth'):
    return {'eth0': _fake_vif(cls), prefix+'1': _fake_vif(cls)}


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


def get_port_obj(port_id='07cfe856-11cc-43d9-9200-ff4dc02d3620',
                 device_owner='compute:kuryr', ip_address=None,
                 vif_details=None, **kwargs):

    fixed_ips = [{'subnet_id': 'e1942bb1-5f51-4646-9885-365b66215592',
                  'ip_address': '10.10.0.5'},
                 {'subnet_id': '4894baaf-df06-4a54-9885-9cd99d1cc245',
                  'ip_address': 'fd35:7db5:e3fc:0:f816:3eff:fe80:d421'}]
    if ip_address:
        fixed_ips[0]['ip_address'] = ip_address
    security_group_ids = ['cfb3dfc4-7a43-4ba1-b92d-b8b2650d7f88']

    if not vif_details:
        vif_details = {'port_filter': True, 'ovs_hybrid_plug': False}

    port_data = {'allowed_address_pairs': [],
                 'binding_host_id': 'kuryr-devstack',
                 'binding_profile': {},
                 'binding_vif_details': vif_details,
                 'binding_vif_type': 'ovs',
                 'binding_vnic_type': 'normal',
                 'created_at': '2017-06-09T13:23:24Z',
                 'data_plane_status': None,
                 'description': '',
                 'device_id': '',
                 'device_owner': device_owner,
                 'dns_assignment': None,
                 'dns_domain': None,
                 'dns_name': None,
                 'extra_dhcp_opts': [],
                 'fixed_ips': fixed_ips,
                 'id': port_id,
                 'ip_address': None,
                 'is_admin_state_up': True,
                 'is_port_security_enabled': True,
                 'location': None,
                 'mac_address': 'fa:16:3e:80:d4:21',
                 'name': constants.KURYR_PORT_NAME,
                 'network_id': 'ba44f957-c467-412b-b985-ae720514bc46',
                 'option_name': None,
                 'option_value': None,
                 'project_id': 'b6e8fb2bde594673923afc19cf168f3a',
                 'qos_policy_id': None,
                 'revision_number': 9,
                 'security_group_ids': security_group_ids,
                 'status': u'DOWN',
                 'subnet_id': None,
                 'tags': [],
                 'trunk_details': None,
                 'updated_at': u'2019-12-04T15:06:09Z'}
    port_data.update(kwargs)
    return os_port.Port(**port_data)


def get_sgr_obj(sgr_id='7621d1e0-a2d2-4496-94eb-ffd375d20877',
                sg_id='cfb3dfc4-7a43-4ba1-b92d-b8b2650d7f88',
                protocol='tcp', direction='ingress'):

    sgr_data = {'description': '',
                'direction': direction,
                'ether_type': 'IPv4',
                'id': sgr_id,
                'port_range_max': 8080,
                'port_range_min': 8080,
                'project_id': '5ea46368c7fe436bb8732738c149fbce',
                'protocol': protocol,
                'remote_group_id': None,
                'remote_ip_prefix': None,
                'security_group_id': sg_id,
                'tenant_id': '5ea46368c7fe436bb8732738c149fbce'}

    return os_sgr.SecurityGroupRule(**sgr_data)


def get_k8s_pod(name='pod-5bb648d658-55n76', namespace='namespace',
                uid='683da866-6bb1-4da2-bf6a-a5f4137c38e7'):

    return {'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {'creationTimestamp': '2020-12-22T09:04:29Z',
                         'finalizers': ['kuryr.openstack.org/pod-finalizer'],
                         'generateName': 'pod-5bb648d658-',
                         'labels': {'app': 'pod',
                                    'pod-template-hash': '5bb648d658'},
                         'operation': 'Update',
                         'name': name,
                         'namespace': namespace,
                         'resourceVersion': '19416',
                         'uid': uid},
            'spec': {},
            'status': {}}
