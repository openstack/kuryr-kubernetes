# Copyright (c) 2022 Troila
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
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import utils as driver_utils

LOG = logging.getLogger(__name__)


class AnnotationProjectBaseDriver(
        base.PodProjectDriver, base.ServiceProjectDriver,
        base.NamespaceProjectDriver, base.NetworkPolicyProjectDriver):
    """Provides project ID based on resource's annotation."""

    project_annotation = constants.K8s_ANNOTATION_PROJECT

    def _get_namespace_project(self, namespace):
        ns_md = namespace['metadata']
        project = ns_md.get('annotations', {}).get(self.project_annotation)
        if not project:
            LOG.debug("Namespace %s has no project annotation, try to get "
                      "project id from the configuration option.",
                      namespace['metadata']['name'])
            project = config.CONF.neutron_defaults.project
        if not project:
            raise cfg.RequiredOptError('project',
                                       cfg.OptGroup('neutron_defaults'))
        return project

    def get_project(self, resource):
        res_ns = resource['metadata']['namespace']
        namespace_path = f"{constants.K8S_API_NAMESPACES}/{res_ns}"
        namespace = driver_utils.get_k8s_resource(namespace_path)
        return self._get_namespace_project(namespace)


class AnnotationPodProjectDriver(AnnotationProjectBaseDriver):
    pass


class AnnotationServiceProjectDriver(AnnotationProjectBaseDriver):
    pass


class AnnotationNamespaceProjectDriver(AnnotationProjectBaseDriver):

    def get_project(self, namespace):
        return self._get_namespace_project(namespace)


class AnnotationNetworkPolicyProjectDriver(AnnotationProjectBaseDriver):
    pass
