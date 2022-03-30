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
from oslo_concurrency import lockutils
from oslo_log import log as logging

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.handlers import dispatch as k_dis
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils


LOG = logging.getLogger(__name__)


class CNIKuryrPortHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = k_const.K8S_OBJ_KURYRPORT

    def __init__(self, registry):
        super().__init__()
        self.registry = registry

    def on_vif(self, kuryrport, vifs):
        kp_name = utils.get_res_unique_name(kuryrport)
        with lockutils.lock(kp_name, external=True):
            if (kp_name not in self.registry or
                    self.registry[kp_name] == k_const.CNI_DELETED_POD_SENTINEL
                    or self.registry[kp_name]['kp']['metadata']['uid'] !=
                    kuryrport['metadata']['uid']):
                self.registry[kp_name] = {'kp': kuryrport,
                                          'vifs': vifs,
                                          'containerid': None,
                                          'vif_unplugged': False,
                                          'del_received': False}
            else:
                old_vifs = self.registry[kp_name]['vifs']
                for iface in vifs:
                    if old_vifs[iface].active != vifs[iface].active:
                        kp_dict = self.registry[kp_name]
                        kp_dict['vifs'] = vifs
                        self.registry[kp_name] = kp_dict

    def on_deleted(self, kuryrport, *args, **kwargs):
        kp_name = utils.get_res_unique_name(kuryrport)
        try:
            if (kp_name in self.registry and self.registry[kp_name]
                    != k_const.CNI_DELETED_POD_SENTINEL):
                # NOTE(ndesh): We need to lock here to avoid race condition
                #              with the deletion code for CNI DEL so that
                #              we delete the registry entry exactly once
                with lockutils.lock(kp_name, external=True):
                    if self.registry[kp_name]['vif_unplugged']:
                        del self.registry[kp_name]
                    else:
                        kp_dict = self.registry[kp_name]
                        kp_dict['del_received'] = True
                        self.registry[kp_name] = kp_dict
        except KeyError:
            # This means someone else removed it. It's odd but safe to ignore.
            LOG.debug('KuryrPort %s entry already removed from registry while '
                      'handling DELETED event. Ignoring.', kp_name)
            pass

    def on_present(self, kuryrport, *args, **kwargs):
        LOG.debug('MODIFIED event for KuryrPort %s',
                  utils.get_res_unique_name(kuryrport))
        vifs = self._get_vifs(kuryrport)
        if vifs:
            self.on_vif(kuryrport, vifs)

    def _get_vifs(self, kuryrport):
        vifs_dict = {
            k: obj_vif.base.VersionedObject.obj_from_primitive(v['vif'])
            for k, v in kuryrport['status']['vifs'].items()}
        LOG.debug("Got vifs: %r", vifs_dict)

        return vifs_dict


class CNIPodHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = k_const.K8S_OBJ_POD

    def __init__(self, registry):
        super().__init__()
        self.registry = registry

    def on_finalize(self, pod, *args, **kwargs):
        # TODO(dulek): Verify if this is the handler for such case.
        kp_name = utils.get_res_unique_name(pod)
        with lockutils.lock(kp_name, external=True):
            # If there was no KP and Pod got deleted, we need inform the
            # thread waiting for it about that. We'll insert sentinel value.
            if kp_name not in self.registry:
                self.registry[kp_name] = k_const.CNI_DELETED_POD_SENTINEL


class CNIPipeline(k_dis.EventPipeline):

    def _wrap_dispatcher(self, dispatcher):
        return dispatcher

    def _wrap_consumer(self, consumer):
        return consumer
