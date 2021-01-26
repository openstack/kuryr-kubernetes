# Copyright 2020 Red Hat, Inc.
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

from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes.controller.drivers import base

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ConfigNodesSubnets(base.NodesSubnetsDriver):
    """Provides list of nodes subnets from configuration."""

    def get_nodes_subnets(self, raise_on_empty=False):
        node_subnet_ids = CONF.pod_vif_nested.worker_nodes_subnets
        if not node_subnet_ids:
            if raise_on_empty:
                raise cfg.RequiredOptError(
                    'worker_nodes_subnets', cfg.OptGroup('pod_vif_nested'))
            else:
                return []

        return node_subnet_ids

    def add_node(self, node):
        return False

    def delete_node(self, node):
        return False
