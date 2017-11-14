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

from oslo_cache import core as cache
from oslo_config import cfg

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import os_vif_util


CONF = cfg.CONF

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


@MEMOIZE
def _get_subnet(subnet_id):
    neutron = clients.get_neutron_client()

    n_subnet = neutron.show_subnet(subnet_id).get('subnet')
    network_id = n_subnet['network_id']
    n_network = neutron.show_network(network_id).get('network')

    subnet = os_vif_util.neutron_to_osvif_subnet(n_subnet)
    network = os_vif_util.neutron_to_osvif_network(n_network)
    network.subnets.objects.append(subnet)

    return network


class DefaultPodSubnetDriver(base.PodSubnetsDriver):
    """Provides subnet for Pod port based on a configuration option."""

    def get_subnets(self, pod, project_id):
        subnet_id = config.CONF.neutron_defaults.pod_subnet

        if not subnet_id:
            # NOTE(ivc): this option is only required for
            # DefaultPodSubnetDriver and its subclasses, but it may be
            # optional for other drivers (e.g. when each namespace has own
            # subnet)
            raise cfg.RequiredOptError('pod_subnet',
                                       cfg.OptGroup('neutron_defaults'))

        return {subnet_id: _get_subnet(subnet_id)}


class DefaultServiceSubnetDriver(base.ServiceSubnetsDriver):
    """Provides subnet for Service's LBaaS based on a configuration option."""

    def get_subnets(self, service, project_id):
        subnet_id = config.CONF.neutron_defaults.service_subnet

        if not subnet_id:
            # NOTE(ivc): this option is only required for
            # DefaultServiceSubnetDriver and its subclasses, but it may be
            # optional for other drivers (e.g. when each namespace has own
            # subnet)
            raise cfg.RequiredOptError('service_subnet',
                                       cfg.OptGroup('neutron_defaults'))

        return {subnet_id: _get_subnet(subnet_id)}
