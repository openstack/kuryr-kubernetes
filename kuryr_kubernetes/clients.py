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

from functools import partial
import ipaddress
import os

from keystoneauth1 import session as k_session
from kuryr.lib import utils
from openstack import connection
from openstack import exceptions as os_exc
from openstack.load_balancer.v2 import listener as os_listener
from openstack.network.v2 import port as os_port
from openstack.network.v2 import trunk as os_trunk
from openstack import resource as os_resource
from openstack import utils as os_utils

from kuryr_kubernetes import config
from kuryr_kubernetes import k8s_client
from kuryr_kubernetes.pod_resources import client as pr_client

_clients = {}
_NEUTRON_CLIENT = 'neutron-client'
_KUBERNETES_CLIENT = 'kubernetes-client'
_OPENSTACKSDK = 'openstacksdk'
_POD_RESOURCES_CLIENT = 'pod-resources-client'


def get_network_client():
    return _clients[_OPENSTACKSDK].network


def get_loadbalancer_client():
    return _clients[_OPENSTACKSDK].load_balancer


def get_kubernetes_client() -> k8s_client.K8sClient:
    return _clients[_KUBERNETES_CLIENT]


def get_pod_resources_client():
    return _clients[_POD_RESOURCES_CLIENT]


def get_compute_client():
    return _clients[_OPENSTACKSDK].compute


def setup_clients():
    setup_kubernetes_client()
    setup_openstacksdk()


def setup_kubernetes_client():
    if config.CONF.kubernetes.api_root:
        api_root = config.CONF.kubernetes.api_root
    else:
        # NOTE(dulek): This is for containerized deployments, i.e. running in
        #              K8s Pods.
        host = os.environ['KUBERNETES_SERVICE_HOST']
        port = os.environ['KUBERNETES_SERVICE_PORT_HTTPS']
        try:
            addr = ipaddress.ip_address(host)
            if addr.version == 6:
                host = '[%s]' % host
        except ValueError:
            # It's not an IP addres but a hostname, it's fine, move along.
            pass
        api_root = "https://%s:%s" % (host, port)
    _clients[_KUBERNETES_CLIENT] = k8s_client.K8sClient(api_root)


def _create_ports(self, payload):
    """bulk create ports using openstacksdk module"""
    # TODO(gryf): this function should be removed while we update openstacksdk
    # version to 0.42.
    key_map = {'binding_host_id': 'binding:host_id',
               'binding_profile': 'binding:profile',
               'binding_vif_details': 'binding:vif_details',
               'binding_vif_type': 'binding:vif_type',
               'binding_vnic_type': 'binding:vnic_type'}

    for port in payload['ports']:
        for key, mapping in key_map.items():
            if key in port:
                port[mapping] = port.pop(key)

    response = self.post(os_port.Port.base_path, json=payload)

    if not response.ok:
        raise os_exc.SDKException('Error when bulk creating ports: %s' %
                                  response.text)
    return (os_port.Port(**item) for item in response.json()['ports'])


def _add_trunk_subports(self, trunk, subports):
    """Set sub_ports on trunk

    The original method on openstacksdk doesn't care about any errors. This is
    a replacement that does.
    """
    trunk = self._get_resource(os_trunk.Trunk, trunk)
    url = os_utils.urljoin('/trunks', trunk.id, 'add_subports')
    response = self.put(url, json={'sub_ports': subports})
    os_exc.raise_from_response(response)
    trunk._body.attributes.update({'sub_ports': subports})
    return trunk


def _delete_trunk_subports(self, trunk, subports):
    """Remove sub_ports from trunk

    The original method on openstacksdk doesn't care about any errors. This is
    a replacement that does.
    """
    trunk = self._get_resource(os_trunk.Trunk, trunk)
    url = os_utils.urljoin('/trunks', trunk.id, 'remove_subports')
    response = self.put(url, json={'sub_ports': subports})
    os_exc.raise_from_response(response)
    trunk._body.attributes.update({'sub_ports': subports})
    return trunk


def handle_neutron_errors(method, *args, **kwargs):
    """Handle errors on openstacksdk router methods"""
    result = method(*args, **kwargs)
    if 'NeutronError' in result:
        error = result['NeutronError']
        if error['type'] in ('RouterNotFound',
                             'RouterInterfaceNotFoundForSubnet',
                             'SubnetNotFound'):
            raise os_exc.NotFoundException(message=error['message'])
        else:
            raise os_exc.SDKException(error['type'] + ": " + error['message'])

    return result


def setup_openstacksdk():
    auth_plugin = utils.get_auth_plugin('neutron')
    session = utils.get_keystone_session('neutron', auth_plugin)

    # NOTE(mdulko): To get rid of warnings about connection pool being full
    #               we need to "tweak" the keystoneauth's adapters increasing
    #               the maximum pool size.
    for scheme in list(session.session.adapters):
        session.session.mount(scheme, k_session.TCPKeepAliveAdapter(
            pool_maxsize=1000))

    # TODO(mdulko): To use Neutron's ability to do compare-and-swap updates we
    #               need to manually add support for inserting If-Match header
    #               into requests. At the moment we only need it for ports.
    #               Remove when lower-constraints openstacksdk supports this.
    os_port.Port.if_match = os_resource.Header('If-Match')
    # TODO(maysams): We need to manually insert allowed_cidrs option
    # as it's only supported from 0.41.0 version. Remove it once
    # lower-constraints supports it.
    os_listener.Listener.allowed_cidrs = os_resource.Body('allowed_cidrs',
                                                          type=list)
    conn = connection.Connection(
        session=session,
        region_name=getattr(config.CONF.neutron, 'region_name', None))
    conn.network.create_ports = partial(_create_ports, conn.network)
    conn.network.add_trunk_subports = partial(_add_trunk_subports,
                                              conn.network)
    conn.network.delete_trunk_subports = partial(_delete_trunk_subports,
                                                 conn.network)
    _clients[_OPENSTACKSDK] = conn


def setup_pod_resources_client():
    root_dir = config.CONF.sriov.kubelet_root_dir
    _clients[_POD_RESOURCES_CLIENT] = pr_client.PodResourcesClient(root_dir)
