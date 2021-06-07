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

from os_vif import objects as obj_vif
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import dispatch as k_dis
from kuryr_kubernetes.handlers import k8s_base


LOG = logging.getLogger(__name__)


class CNIHandlerBase(k8s_base.ResourceEventHandler, metaclass=abc.ABCMeta):
    OBJECT_KIND = k_const.K8S_OBJ_KURYRPORT

    def __init__(self, cni, on_done):
        self._cni = cni
        self._callback = on_done
        self._vifs = {}

    def on_present(self, pod, *args, **kwargs):
        vifs = self._get_vifs(pod)

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

    def _get_vifs(self, pod):
        k8s = clients.get_kubernetes_client()
        try:
            kuryrport_crd = k8s.get(f'{k_const.K8S_API_CRD_NAMESPACES}/'
                                    f'{pod["metadata"]["namespace"]}/'
                                    f'kuryrports/{pod["metadata"]["name"]}')
            LOG.debug("Got CRD: %r", kuryrport_crd)
        except k_exc.K8sClientException:
            return {}

        vifs_dict = {k: obj_vif.base.VersionedObject
                     .obj_from_primitive(v['vif'])
                     for k, v in kuryrport_crd['status']['vifs'].items()}
        LOG.debug("Got vifs: %r", vifs_dict)

        return vifs_dict

    def _get_inst(self, pod):
        return obj_vif.instance_info.InstanceInfo(
            uuid=pod['metadata']['uid'], name=pod['metadata']['name'])


class CallbackHandler(CNIHandlerBase):

    def __init__(self, on_vif, on_del=None):
        super(CallbackHandler, self).__init__(None, on_vif)
        self._del_callback = on_del
        self._kuryrport = None
        self._callback_vifs = None

    def should_callback(self, kuryrport, vifs):
        """Called after all vifs have been processed

        Calls callback if there was at least one vif in the CRD

        :param kuryrport: dict containing Kubernetes KuryrPort CRD object
        :param vifs: dict containing os_vif VIF objects and ifnames
        :returns True/False
        """
        self._kuryrport = kuryrport
        self._callback_vifs = vifs
        if vifs:
            return True
        return False

    def callback(self):
        self._callback(self._kuryrport, self._callback_vifs)

    def on_deleted(self, kuryrport, *args, **kwargs):
        LOG.debug("Got kuryrport %s deletion event.",
                  kuryrport['metadata']['name'])
        if self._del_callback:
            self._del_callback(kuryrport)


class CNIPipeline(k_dis.EventPipeline):

    def _wrap_dispatcher(self, dispatcher):
        return dispatcher

    def _wrap_consumer(self, consumer):
        return consumer
