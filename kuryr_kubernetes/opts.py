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
import copy

from oslo_log import _options

from kuryr.lib import opts as lib_opts
from kuryr_kubernetes.cni import health as cni_health
from kuryr_kubernetes import config
from kuryr_kubernetes.controller.drivers import namespace_security_groups
from kuryr_kubernetes.controller.drivers import namespace_subnet
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes.controller.drivers import vif_pool
from kuryr_kubernetes.controller.handlers import namespace
from kuryr_kubernetes.controller.handlers import policy
from kuryr_kubernetes.controller.handlers import vif
from kuryr_kubernetes.controller.managers import health
from kuryr_kubernetes.controller.managers import pool
from kuryr_kubernetes import utils

_kuryr_k8s_opts = [
    ('kubernetes', config.k8s_opts),
    ('kuryr-kubernetes', config.kuryr_k8s_opts),
    ('neutron_defaults', config.neutron_defaults),
    ('pod_vif_nested', config.nested_vif_driver_opts),
    ('vif_pool', vif_pool.vif_pool_driver_opts),
    ('octavia_defaults', config.octavia_defaults),
    ('cache_defaults', config.cache_defaults),
    ('subnet_caching', utils.subnet_caching_opts),
    ('node_driver_caching', vif_pool.node_vif_driver_caching_opts),
    ('pool_manager', pool.pool_manager_opts),
    ('cni_daemon', config.daemon_opts),
    ('health_server', health.health_server_opts),
    ('cni_health_server', cni_health.cni_health_server_opts),
    ('namespace_subnet', namespace_subnet.namespace_subnet_driver_opts),
    ('namespace_sg', namespace_security_groups.namespace_sg_driver_opts),
    ('ingress', config.ingress),
    ('sriov', config.sriov_opts),
    ('namespace_handler_caching', namespace.namespace_handler_caching_opts),
    ('np_handler_caching', policy.np_handler_caching_opts),
    ('vif_handler_caching', vif.vif_handler_caching_opts),
    ('pod_ip_caching', driver_utils.pod_ip_caching_opts),
]


def list_kuryr_opts():
    """Return a list of oslo_config options available in Kuryr service.

    Each element of the list is a tuple. The first element is the name of the
    group under which the list of elements in the second element will be
    registered. A group name of None corresponds to the [DEFAULT] group in
    config files.

    This function is also discoverable via the 'kuryr' entry point under
    the 'oslo_config.opts' namespace.

    The purpose of this is to allow tools like the Oslo sample config file
    generator to discover the options exposed to users by Kuryr.

    :returns: a list of (group_name, opts) tuples
    """

    return ([(k, copy.deepcopy(o)) for k, o in _kuryr_k8s_opts] +
            lib_opts.list_kuryr_opts() + _options.list_opts())
