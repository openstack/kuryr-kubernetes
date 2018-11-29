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

import random
import socket
import time

import requests

from os_vif import objects
from oslo_cache import core as cache
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes.objects import vif
from kuryr_kubernetes import os_vif_util


CONF = cfg.CONF
LOG = log.getLogger(__name__)

VALID_MULTI_POD_POOLS_OPTS = {'noop': ['neutron-vif',
                                       'nested-vlan',
                                       'nested-macvlan',
                                       'sriov'],
                              'neutron': ['neutron-vif'],
                              'nested': ['nested-vlan'],
                              }
DEFAULT_TIMEOUT = 180
DEFAULT_INTERVAL = 3

subnet_caching_opts = [
    cfg.BoolOpt('caching', default=True),
    cfg.IntOpt('cache_time', default=3600),
]

CONF.register_opts(subnet_caching_opts, "subnet_caching")

cache.configure(CONF)
subnet_cache_region = cache.create_region()
MEMOIZE = cache.get_memoization_decorator(
    CONF, subnet_cache_region, "subnet_caching")

cache.configure_cache_region(CONF, subnet_cache_region)


def utf8_json_decoder(byte_data):
    """Deserializes the bytes into UTF-8 encoded JSON.

    :param byte_data: The bytes to be converted into the UTF-8 encoded JSON.
    :returns: The UTF-8 encoded JSON represented by Python dictionary format.
    """
    return jsonutils.loads(byte_data.decode('utf8'))


def convert_netns(netns):
    """Convert /proc based netns path to Docker-friendly path.

    When CONF.docker_mode is set this method will change /proc to
    /CONF.netns_proc_dir. This allows netns manipulations to work when running
    in Docker container on Kubernetes host.

    :param netns: netns path to convert.
    :return: Converted netns path.
    """
    if CONF.cni_daemon.docker_mode:
        return netns.replace('/proc', CONF.cni_daemon.netns_proc_dir)
    else:
        return netns


def get_pod_unique_name(pod):
    """Returns a unique name for the pod.

    It returns a pod unique name for the pod composed of its name and the
    namespace it is running on.

    :returns: String with namespace/name of the pod
    """
    return "%(namespace)s/%(name)s" % pod['metadata']


def check_suitable_multi_pool_driver_opt(pool_driver, pod_driver):
    return pod_driver in VALID_MULTI_POD_POOLS_OPTS.get(pool_driver, [])


def exponential_sleep(deadline, attempt, interval=DEFAULT_INTERVAL):
    """Sleep for exponential duration.

    This implements a variation of exponential backoff algorithm [1] and
    ensures that there is a minimal time `interval` to sleep.
    (expected backoff E(c) = interval * 2 ** c / 2).

    [1] https://en.wikipedia.org/wiki/Exponential_backoff

    :param deadline: sleep timeout duration in seconds.
    :param attempt: attempt count of sleep function.
    :param interval: minimal time interval to sleep
    :return: the actual time that we've slept
    """
    now = time.time()
    seconds_left = deadline - now

    if seconds_left <= 0:
        return 0

    interval = random.randint(1, 2 ** attempt - 1) * DEFAULT_INTERVAL

    if interval > seconds_left:
        interval = seconds_left

    if interval < DEFAULT_INTERVAL:
        interval = DEFAULT_INTERVAL

    time.sleep(interval)
    return interval


def get_node_name():
    # leader-elector container based on K8s way of doing leader election is
    # assuming that hostname it sees is the node id. Containers within a pod
    # are sharing the hostname, so this will match what leader-elector returns.
    return socket.gethostname()


def get_leader_name():
    url = 'http://localhost:%d' % CONF.kubernetes.controller_ha_elector_port
    try:
        return requests.get(url).json()['name']
    except Exception:
        LOG.exception('Error when fetching current leader pod name.')
        # NOTE(dulek): Assuming there's no leader when we can't contact leader
        #              elector container.
        return None


@MEMOIZE
def get_subnet(subnet_id):
    neutron = clients.get_neutron_client()

    n_subnet = neutron.show_subnet(subnet_id).get('subnet')
    network_id = n_subnet['network_id']
    n_network = neutron.show_network(network_id).get('network')

    subnet = os_vif_util.neutron_to_osvif_subnet(n_subnet)
    network = os_vif_util.neutron_to_osvif_network(n_network)
    network.subnets.objects.append(subnet)

    return network


def extract_pod_annotation(annotation):
    obj = objects.base.VersionedObject.obj_from_primitive(annotation)
    # FIXME(dulek): This is code to maintain compatibility with Queens. We can
    #               remove it once we stop supporting upgrading from Queens,
    #               most likely in Stein. Note that this requires being sure
    #               that *all* the pod annotations are in new format.
    if obj.obj_name() != vif.PodState.obj_name():
        # This is old format of annotations - single VIF object. We need to
        # pack it in PodState object.
        obj = vif.PodState(default_vif=obj)

    return obj


def has_limit(quota):
    NO_LIMIT = -1
    return quota != NO_LIMIT


def is_available(resource, resource_quota, neutron_func):
    qnt_resources = len(neutron_func().get(resource))
    availability = resource_quota - qnt_resources
    if availability <= 0:
        LOG.error("Quota exceeded for resource: %s", resource)
        return False
    return True
