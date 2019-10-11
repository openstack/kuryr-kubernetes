# Copyright 2018 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base

LOG = logging.getLogger(__name__)


class PodLabelHandler(k8s_base.ResourceEventHandler):
    """Controller side of Pod Label process for Kubernetes pods.

    `PodLabelHandler` runs on the Kuryr-Kubernetes controller and is
    responsible for triggering the vif port updates upon pod labels changes.
    """

    OBJECT_KIND = constants.K8S_OBJ_POD
    OBJECT_WATCH_PATH = "%s/%s" % (constants.K8S_API_BASE, "pods")

    def __init__(self):
        super(PodLabelHandler, self).__init__()
        self._drv_project = drivers.PodProjectDriver.get_instance()
        self._drv_sg = drivers.PodSecurityGroupsDriver.get_instance()
        self._drv_svc_sg = drivers.ServiceSecurityGroupsDriver.get_instance()
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            specific_driver='multi_pool')
        self._drv_vif_pool.set_vif_driver()
        self._drv_lbaas = drivers.LBaaSDriver.get_instance()

    def on_present(self, pod):
        if driver_utils.is_host_network(pod) or not self._has_pod_state(pod):
            # NOTE(ltomasbo): The event will be retried once the vif handler
            # annotates the pod with the pod state.
            return

        current_pod_labels = pod['metadata'].get('labels')
        previous_pod_labels = self._get_pod_labels(pod)
        LOG.debug("Got previous pod labels from annotation: %r",
                  previous_pod_labels)

        if current_pod_labels == previous_pod_labels:
            return

        crd_pod_selectors = self._drv_sg.update_sg_rules(pod)

        project_id = self._drv_project.get_project(pod)
        security_groups = self._drv_sg.get_security_groups(pod, project_id)
        self._drv_vif_pool.update_vif_sgs(pod, security_groups)
        try:
            self._set_pod_labels(pod, current_pod_labels)
        except k_exc.K8sResourceNotFound:
            LOG.debug("Pod already deleted, no need to retry.")
            return

        if oslo_cfg.CONF.octavia_defaults.enforce_sg_rules:
            services = driver_utils.get_services()
            self._update_services(services, crd_pod_selectors, project_id)

    def _get_pod_labels(self, pod):
        try:
            annotations = pod['metadata']['annotations']
            pod_labels_annotation = annotations[constants.K8S_ANNOTATION_LABEL]
        except KeyError:
            return None
        pod_labels = jsonutils.loads(pod_labels_annotation)
        return pod_labels

    def _set_pod_labels(self, pod, labels):
        if not labels:
            LOG.debug("Removing Label annotation: %r", labels)
            annotation = None
        else:
            annotation = jsonutils.dumps(labels, sort_keys=True)
            LOG.debug("Setting Labels annotation: %r", annotation)

        k8s = clients.get_kubernetes_client()
        k8s.annotate(pod['metadata']['selfLink'],
                     {constants.K8S_ANNOTATION_LABEL: annotation},
                     resource_version=pod['metadata']['resourceVersion'])

    def _has_pod_state(self, pod):
        try:
            pod_state = pod['metadata']['annotations'][
                constants.K8S_ANNOTATION_VIF]
            LOG.debug("Pod state is: %s", pod_state)
        except KeyError:
            return False
        return True

    def _update_services(self, services, crd_pod_selectors, project_id):
        for service in services.get('items'):
            if not driver_utils.service_matches_affected_pods(
                    service, crd_pod_selectors):
                continue
            sgs = self._drv_svc_sg.get_security_groups(service,
                                                       project_id)
            self._drv_lbaas.update_lbaas_sg(service, sgs)
