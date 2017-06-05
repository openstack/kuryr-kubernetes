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
    objects and pass them to the CNI driver in form of the Kubernetes pod
    annotation.
    """

    OBJECT_KIND = constants.K8S_OBJ_POD
    OBJECT_WATCH_PATH = "%s/%s" % (constants.K8S_API_BASE, "pods")

    def __init__(self):
        super(VIFHandler, self).__init__()
        self._drv_project = drivers.PodProjectDriver.get_instance()
        self._drv_subnets = drivers.PodSubnetsDriver.get_instance()
        self._drv_sg = drivers.PodSecurityGroupsDriver.get_instance()
        # REVISIT(ltomasbo): The VIF Handler should not be aware of the pool
        # directly. Due to the lack of a mechanism to load and set the
        # VIFHandler driver, for now it is aware of the pool driver, but this
        # will be reverted as soon as a mechanism is in place.
        self._drv_vif_pool = drivers.VIFPoolDriver.get_instance(
            driver_alias='multi_pool')
        self._drv_vif_pool.set_vif_driver()

    def on_present(self, pod):
        if self._is_host_network(pod) or not self._is_pending_node(pod):
            # REVISIT(ivc): consider an additional configurable check that
            # would allow skipping pods to enable heterogeneous environments
            # where certain pods/namespaces/nodes can be managed by other
            # networking solutions/CNI drivers.
            return
        vifs = self._get_vifs(pod)

        if not vifs:
            vifs = {}

            project_id = self._drv_project.get_project(pod)
            security_groups = self._drv_sg.get_security_groups(pod, project_id)
            subnets = self._drv_subnets.get_subnets(pod, project_id)

            # NOTE(danil): There is currently no way to actually request
            # multiple VIFs. However we're packing the main_vif 'eth0' in a
            # dict here to facilitate future work in this area
            main_vif = self._drv_vif_pool.request_vif(
                pod, project_id, subnets, security_groups)
            vifs[constants.DEFAULT_IFNAME] = main_vif

            try:
                self._set_vifs(pod, vifs)
            except k_exc.K8sClientException as ex:
                LOG.debug("Failed to set annotation: %s", ex)
                # FIXME(ivc): improve granularity of K8sClient exceptions:
                # only resourceVersion conflict should be ignored
                for ifname, vif in vifs.items():
                    self._drv_for_vif(vif).release_vif(pod, vif, project_id,
                                                       security_groups)
        else:
            changed = False
            for ifname, vif in vifs.items():
                if not vif.active:
                    self._drv_for_vif(vif).activate_vif(pod, vif)
                    changed = True
            if changed:
                self._set_vifs(pod, vifs)

    def on_deleted(self, pod):
        if self._is_host_network(pod):
            return
        project_id = self._drv_project.get_project(pod)
        security_groups = self._drv_sg.get_security_groups(pod, project_id)

        vifs = self._get_vifs(pod)
        for ifname, vif in vifs.items():
            self._drv_for_vif(vif).release_vif(pod, vif, project_id,
                                               security_groups)

    def _drv_for_vif(self, vif):
        # TODO(danil): a better polymorphism is required here
        return self._drv_vif_pool

    @staticmethod
    def _is_host_network(pod):
        return pod['spec'].get('hostNetwork', False)

    @staticmethod
    def _is_pending_node(pod):
        """Checks if Pod is in PENDGING status and has node assigned."""
        try:
            return (pod['spec']['nodeName'] and
                    pod['status']['phase'] == constants.K8S_POD_STATUS_PENDING)
        except KeyError:
            return False

    def _set_vifs(self, pod, vifs):
        # TODO(ivc): extract annotation interactions
        if not vifs:
            LOG.debug("Removing VIFs annotation: %r", vifs)
            annotation = None
        else:
            vifs_dict = {}
            for ifname, vif in vifs.items():
                vif.obj_reset_changes(recursive=True)
                vifs_dict[ifname] = vif.obj_to_primitive()

            annotation = jsonutils.dumps(vifs_dict,
                                         sort_keys=True)
            LOG.debug("Setting VIFs annotation: %r", annotation)
        k8s = clients.get_kubernetes_client()
        k8s.annotate(pod['metadata']['selfLink'],
                     {constants.K8S_ANNOTATION_VIF: annotation},
                     resource_version=pod['metadata']['resourceVersion'])

    def _get_vifs(self, pod):
        # TODO(ivc): same as '_set_vif'
        try:
            annotations = pod['metadata']['annotations']
            vif_annotation = annotations[constants.K8S_ANNOTATION_VIF]
        except KeyError:
            return {}
        vif_annotation = jsonutils.loads(vif_annotation)
        vifs = {
            ifname: obj_vif.vif.VIFBase.obj_from_primitive(vif_obj) for
            ifname, vif_obj in vif_annotation.items()
        }
        LOG.debug("Got VIFs from annotation: %r", vifs)
        return vifs
