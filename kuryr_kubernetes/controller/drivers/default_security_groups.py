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
from oslo_log import log as logging

from kuryr_kubernetes import config
from kuryr_kubernetes.controller.drivers import base

LOG = logging.getLogger(__name__)


class DefaultPodSecurityGroupsDriver(base.PodSecurityGroupsDriver):
    """Provides security groups for Pod based on a configuration option."""

    def get_security_groups(self, pod, project_id):
        sg_list = config.CONF.neutron_defaults.pod_security_groups

        if not sg_list:
            # NOTE(ivc): this option is only required for
            # Default{Pod,Service}SecurityGroupsDriver and its subclasses,
            # but it may be optional for other drivers (e.g. when each
            # namespace has own set of security groups)
            raise cfg.RequiredOptError('pod_security_groups',
                                       cfg.OptGroup('neutron_defaults'))

        return sg_list[:]

    def create_sg_rules(self, pod):
        LOG.debug("Security group driver does not create SG rules for "
                  "the pods.")

    def delete_sg_rules(self, pod):
        LOG.debug("Security group driver does not delete SG rules for "
                  "the pods.")

    def update_sg_rules(self, pod):
        LOG.debug("Security group driver does not update SG rules for "
                  "the pods.")

    def delete_namespace_sg_rules(self, namespace):
        LOG.debug("Security group driver does not delete SG rules for "
                  "namespace.")

    def create_namespace_sg_rules(self, namespace):
        LOG.debug("Security group driver does not create SG rules for "
                  "namespace.")

    def update_namespace_sg_rules(self, namespace):
        LOG.debug("Security group driver does not update SG rules for "
                  "namespace.")


class DefaultServiceSecurityGroupsDriver(base.ServiceSecurityGroupsDriver):
    """Provides security groups for Service based on a configuration option."""

    def get_security_groups(self, service, project_id):
        # NOTE(ivc): use the same option as DefaultPodSecurityGroupsDriver
        sg_list = config.CONF.neutron_defaults.pod_security_groups

        if not sg_list:
            # NOTE(ivc): this option is only required for
            # Default{Pod,Service}SecurityGroupsDriver and its subclasses,
            # but it may be optional for other drivers (e.g. when each
            # namespace has own set of security groups)
            raise cfg.RequiredOptError('pod_security_groups',
                                       cfg.OptGroup('neutron_defaults'))

        return sg_list[:]
