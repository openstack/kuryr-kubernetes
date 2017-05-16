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

import abc
import six

from os_vif import objects as obj_vif
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.handlers import dispatch as k_dis
from kuryr_kubernetes.handlers import k8s_base

LOG = logging.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class CNIHandlerBase(k8s_base.ResourceEventHandler):
    OBJECT_KIND = k_const.K8S_OBJ_POD

    def __init__(self, cni, on_done):
        self._cni = cni
        self._callback = on_done
        self._vif = None

    def on_present(self, pod):
        vif = self._get_vif(pod)

        if vif:
            self.on_vif(pod, vif)

    @abc.abstractmethod
    def on_vif(self, pod, vif):
        raise NotImplementedError()

    def _get_vif(self, pod):
        # TODO(ivc): same as VIFHandler._get_vif
        try:
            annotations = pod['metadata']['annotations']
            vif_annotation = annotations[k_const.K8S_ANNOTATION_VIF]
        except KeyError:
            return None
        vif_dict = jsonutils.loads(vif_annotation)
        vif = obj_vif.vif.VIFBase.obj_from_primitive(vif_dict)
        LOG.debug("Got VIF from annotation: %r", vif)
        return vif

    def _get_inst(self, pod):
        return obj_vif.instance_info.InstanceInfo(
            uuid=pod['metadata']['uid'], name=pod['metadata']['name'])


class AddHandler(CNIHandlerBase):

    def __init__(self, cni, on_done):
        LOG.debug("AddHandler called with CNI env: %r", cni)
        super(AddHandler, self).__init__(cni, on_done)
        self._vif = None

    def on_vif(self, pod, vif):
        if not self._vif:
            self._vif = vif.obj_clone()
            self._vif.active = True
            b_base.connect(self._vif, self._get_inst(pod),
                           self._cni.CNI_IFNAME, self._cni.CNI_NETNS)

        if vif.active:
            self._callback(vif)


class DelHandler(CNIHandlerBase):

    def on_vif(self, pod, vif):
        b_base.disconnect(vif, self._get_inst(pod),
                          self._cni.CNI_IFNAME, self._cni.CNI_NETNS)
        self._callback(vif)


class CNIPipeline(k_dis.EventPipeline):

    def _wrap_dispatcher(self, dispatcher):
        return dispatcher

    def _wrap_consumer(self, consumer):
        return consumer
