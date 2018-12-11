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
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class CNIHandlerBase(k8s_base.ResourceEventHandler):
    OBJECT_KIND = k_const.K8S_OBJ_POD

    def __init__(self, cni, on_done):
        self._cni = cni
        self._callback = on_done
        self._vifs = {}

    def on_present(self, pod):
        vifs = self._get_vifs(pod)

        for ifname, vif in vifs.items():
            self.on_vif(pod, vif, ifname)

        if self.should_callback(pod, vifs):
            self.callback()

    @abc.abstractmethod
    def should_callback(self, pod, vifs):
        """Called after all vifs have been processed

        Should determine if the CNI is ready to call the callback

        :param pod: dict containing Kubernetes Pod object
        :param vifs: dict containing os_vif VIF objects and ifnames
        :returns True/False
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def callback(self):
        """Called if should_callback returns True"""
        raise NotImplementedError()

    @abc.abstractmethod
    def on_vif(self, pod, vif, ifname):
        raise NotImplementedError()

    def _get_vifs(self, pod):
        # TODO(ivc): same as VIFHandler._get_vif
        try:
            annotations = pod['metadata']['annotations']
            state_annotation = annotations[k_const.K8S_ANNOTATION_VIF]
        except KeyError:
            return {}
        state_annotation = jsonutils.loads(state_annotation)
        state = utils.extract_pod_annotation(state_annotation)
        vifs_dict = state.vifs
        LOG.debug("Got VIFs from annotation: %r", vifs_dict)
        return vifs_dict

    def _get_inst(self, pod):
        return obj_vif.instance_info.InstanceInfo(
            uuid=pod['metadata']['uid'], name=pod['metadata']['name'])


class AddHandler(CNIHandlerBase):

    def __init__(self, cni, on_done):
        LOG.debug("AddHandler called with CNI env: %r", cni)
        super(AddHandler, self).__init__(cni, on_done)

    def on_vif(self, pod, vif, ifname):
        """Called once for every vif of a Pod on every event.

        If it is the first time we see this vif, plug it in.

        :param pod: dict containing Kubernetes Pod object
        :param vif: os_vif VIF object
        :param ifname: string, name of the interfaces inside container
        """
        if ifname not in self._vifs:

            self._vifs[ifname] = vif
            _vif = vif.obj_clone()
            _vif.active = True

            # set eth0's gateway as default
            is_default_gateway = (ifname == self._cni.CNI_IFNAME)
            b_base.connect(_vif, self._get_inst(pod),
                           ifname, self._cni.CNI_NETNS,
                           is_default_gateway=is_default_gateway,
                           container_id=self._cni.CNI_CONTAINERID)

    def should_callback(self, pod, vifs):
        """Called after all vifs have been processed

        Determines if CNI is ready to call the callback and stop watching for
        more events. For AddHandler the callback should be called if there
        is at least one VIF in the annotation and all the
        VIFs received are marked active

        :param pod: dict containing Kubernetes Pod object
        :param vifs: dict containing os_vif VIF objects and ifnames
        :returns True/False
        """
        all_vifs_active = vifs and all(vif.active for vif in vifs.values())

        if all_vifs_active:
            if self._cni.CNI_IFNAME in self._vifs:
                self.callback_vif = self._vifs[self._cni.CNI_IFNAME]
            else:
                self.callback_vif = self._vifs.values()[0]
            LOG.debug("All VIFs are active, exiting. Will return %s",
                      self.callback_vif)
            return True
        else:
            LOG.debug("Waiting for all vifs to become active")
            return False

    def callback(self):
        self._callback(self.callback_vif)


class DelHandler(CNIHandlerBase):

    def on_vif(self, pod, vif, ifname):
        b_base.disconnect(vif, self._get_inst(pod),
                          self._cni.CNI_IFNAME, self._cni.CNI_NETNS,
                          container_id=self._cni.CNI_CONTAINERID)

    def should_callback(self, pod, vifs):
        """Called after all vifs have been processed

        Calls callback if there was at least one vif in the Pod

        :param pod: dict containing Kubernetes Pod object
        :param vifs: dict containing os_vif VIF objects and ifnames
        :returns True/False
        """
        if vifs:
            return True
        return False

    def callback(self):
        self._callback(None)


class CallbackHandler(CNIHandlerBase):

    def __init__(self, on_vif, on_del=None):
        super(CallbackHandler, self).__init__(None, on_vif)
        self._del_callback = on_del
        self._pod = None
        self._callback_vifs = None

    def on_vif(self, pod, vif, ifname):
        pass

    def should_callback(self, pod, vifs):
        """Called after all vifs have been processed

        Calls callback if there was at least one vif in the Pod

        :param pod: dict containing Kubernetes Pod object
        :param vifs: dict containing os_vif VIF objects and ifnames
        :returns True/False
        """
        self._pod = pod
        self._callback_vifs = vifs
        if vifs:
            return True
        return False

    def callback(self):
        self._callback(self._pod, self._callback_vifs)

    def on_deleted(self, pod):
        LOG.debug("Got pod %s deletion event.", pod['metadata']['name'])
        if self._del_callback:
            self._del_callback(pod)


class CNIPipeline(k_dis.EventPipeline):

    def _wrap_dispatcher(self, dispatcher):
        return dispatcher

    def _wrap_consumer(self, consumer):
        return consumer
