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

from os_vif import objects as obj_vif
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base

LOG = logging.getLogger(__name__)


class VIFHandler(k8s_base.ResourceEventHandler):
    """Controller side of VIF binding process for Kubernetes pods.

    `VIFHandler` runs on the Kuryr-Kubernetes controller and together with
    the CNI driver (that runs on 'kubelet' nodes) is responsible for providing
    networking to Kubernetes pods. `VIFHandler` relies on a set of drivers
    (which are responsible for managing Neutron resources) to define the VIF
    object and pass it to the CNI driver in form of the Kubernetes pod
    annotation.
    """

    OBJECT_KIND = constants.K8S_OBJ_POD

    def __init__(self):
        self._drv_project = drivers.PodProjectDriver.get_instance()
        self._drv_subnets = drivers.PodSubnetsDriver.get_instance()
        self._drv_sg = drivers.PodSecurityGroupsDriver.get_instance()
        self._drv_vif = drivers.PodVIFDriver.get_instance()

    def on_present(self, pod):
        if self._is_host_network(pod) or not self._is_pending(pod):
            # REVISIT(ivc): consider an additional configurable check that
            # would allow skipping pods to enable heterogeneous environments
            # where certain pods/namespaces/nodes can be managed by other
            # networking solutions/CNI drivers.
            return

        vif = self._get_vif(pod)

        if not vif:
            project_id = self._drv_project.get_project(pod)
            security_groups = self._drv_sg.get_security_groups(pod, project_id)
            subnets = self._drv_subnets.get_subnets(pod, project_id)
            vif = self._drv_vif.request_vif(pod, project_id, subnets,
                                            security_groups)
            try:
                self._set_vif(pod, vif)
            except k_exc.K8sClientException as ex:
                LOG.debug("Failed to set annotation: %s", ex)
                # FIXME(ivc): improve granularity of K8sClient exceptions:
                # only resourceVersion conflict should be ignored
                self._drv_vif.release_vif(pod, vif)
        elif not vif.active:
            self._drv_vif.activate_vif(pod, vif)
            self._set_vif(pod, vif)

    def on_deleted(self, pod):
        if self._is_host_network(pod):
            return

        vif = self._get_vif(pod)

        if vif:
            self._drv_vif.release_vif(pod, vif)

    @staticmethod
    def _is_host_network(pod):
        try:
            return pod['spec']['hostNetwork']
        except KeyError:
            return False

    @staticmethod
    def _is_pending(pod):
        try:
            return (pod['spec']['nodeName'] and
                    pod['status']['phase'] == constants.K8S_POD_STATUS_PENDING)
        except KeyError:
            return False

    def _set_vif(self, pod, vif):
        # TODO(ivc): extract annotation interactions
        if vif is None:
            LOG.debug("Removing VIF annotation: %r", vif)
            annotation = None
        else:
            vif.obj_reset_changes(recursive=True)
            LOG.debug("Setting VIF annotation: %r", vif)
            annotation = jsonutils.dumps(vif.obj_to_primitive(),
                                         sort_keys=True)
        k8s = clients.get_kubernetes_client()
        k8s.annotate(pod['metadata']['selfLink'],
                     {constants.K8S_ANNOTATION_VIF: annotation},
                     resource_version=pod['metadata']['resourceVersion'])

    def _get_vif(self, pod):
        # TODO(ivc): same as '_set_vif'
        try:
            annotations = pod['metadata']['annotations']
            vif_annotation = annotations[constants.K8S_ANNOTATION_VIF]
        except KeyError:
            return None
        vif_dict = jsonutils.loads(vif_annotation)
        vif = obj_vif.vif.VIFBase.obj_from_primitive(vif_dict)
        LOG.debug("Got VIF from annotation: %r", vif)
        return vif
