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

import ipaddress
import os

from keystoneauth1 import session as k_session
from kuryr.lib import utils
from openstack import connection
from openstack import exceptions as os_exc

from kuryr_kubernetes import config
from kuryr_kubernetes import k8s_client

_clients = {}
_NEUTRON_CLIENT = 'neutron-client'
_KUBERNETES_CLIENT = 'kubernetes-client'
_OPENSTACKSDK = 'openstacksdk'


def get_network_client():
    return _clients[_OPENSTACKSDK].network


def get_loadbalancer_client():
    return _clients[_OPENSTACKSDK].load_balancer


def get_kubernetes_client() -> k8s_client.K8sClient:
    return _clients[_KUBERNETES_CLIENT]


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


def get_neutron_error_type(ex):
    try:
        response = ex.response.json()
    except (ValueError, AttributeError):
        return None

    if response:
        try:
            return response['NeutronError']['type']
        except KeyError:
            pass
    return None


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

    conn = connection.Connection(
        session=session,
        region_name=getattr(config.CONF.neutron, 'region_name', None))
    _clients[_OPENSTACKSDK] = conn
