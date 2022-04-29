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

from oslo_config import cfg

from kuryr_kubernetes import config
from kuryr_kubernetes.controller.drivers import base


class DefaultPodProjectDriver(base.PodProjectDriver):
    """Provides project ID for Pod port based on a configuration option."""

    def get_project(self, pod):
        project_id = config.CONF.neutron_defaults.project

        if not project_id:
            raise cfg.RequiredOptError('project',
                                       cfg.OptGroup('neutron_defaults'))

        return project_id


class DefaultServiceProjectDriver(base.ServiceProjectDriver):
    """Provides project ID for Service based on a configuration option."""

    def get_project(self, service):
        project_id = config.CONF.neutron_defaults.project

        if not project_id:
            # NOTE(ivc): this option is only required for
            # DefaultServiceProjectDriver and its subclasses, but it may be
            # optional for other drivers (e.g. when each namespace has own
            # project)
            raise cfg.RequiredOptError('project',
                                       cfg.OptGroup('neutron_defaults'))

        return project_id


class DefaultNamespaceProjectDriver(base.NamespaceProjectDriver):
    """Provides project ID for Namespace based on a configuration option."""

    def get_project(self, namespace):
        project_id = config.CONF.neutron_defaults.project

        if not project_id:
            # NOTE(ivc): this option is only required for
            # DefaultNamespaceProjectDriver and its subclasses, but it may be
            # optional for other drivers (e.g. when each namespace has own
            # project)
            raise cfg.RequiredOptError('project',
                                       cfg.OptGroup('neutron_defaults'))

        return project_id


class DefaultNetworkPolicyProjectDriver(base.NetworkPolicyProjectDriver):

    def get_project(self, policy):
        project_id = config.CONF.neutron_defaults.project

        if not project_id:
            raise cfg.RequiredOptError('project',
                                       cfg.OptGroup('neutron_defaults'))
        return project_id
