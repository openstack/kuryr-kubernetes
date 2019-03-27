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

import os

from kuryr.lib import utils
from openstack import connection

from kuryr_kubernetes import config
from kuryr_kubernetes import k8s_client
from kuryr_kubernetes.pod_resources import client as pr_client

_clients = {}
_NEUTRON_CLIENT = 'neutron-client'
_KUBERNETES_CLIENT = 'kubernetes-client'
_OPENSTACKSDK = 'openstacksdk'
_POD_RESOURCES_CLIENT = 'pod-resources-client'


def get_neutron_client():
    return _clients[_NEUTRON_CLIENT]


def get_openstacksdk():
    return _clients[_OPENSTACKSDK]


def get_loadbalancer_client():
    return get_openstacksdk().load_balancer


def get_kubernetes_client():
    return _clients[_KUBERNETES_CLIENT]


def get_pod_resources_client():
    return _clients[_POD_RESOURCES_CLIENT]


def setup_clients():
    setup_neutron_client()
    setup_kubernetes_client()
    setup_openstacksdk()


def setup_neutron_client():
    _clients[_NEUTRON_CLIENT] = utils.get_neutron_client()


def setup_kubernetes_client():
    if config.CONF.kubernetes.api_root:
        api_root = config.CONF.kubernetes.api_root
    else:
        # NOTE(dulek): This is for containerized deployments, i.e. running in
        #              K8s Pods.
        host = os.environ['KUBERNETES_SERVICE_HOST']
        port = os.environ['KUBERNETES_SERVICE_PORT_HTTPS']
        api_root = "https://%s:%s" % (host, port)
    _clients[_KUBERNETES_CLIENT] = k8s_client.K8sClient(api_root)


def setup_openstacksdk():
    auth_plugin = utils.get_auth_plugin('neutron')
    session = utils.get_keystone_session('neutron', auth_plugin)
    conn = connection.Connection(session=session)
    _clients[_OPENSTACKSDK] = conn


def setup_pod_resources_client():
    root_dir = config.CONF.sriov.kubelet_root_dir
    _clients[_POD_RESOURCES_CLIENT] = pr_client.PodResourcesClient(root_dir)
