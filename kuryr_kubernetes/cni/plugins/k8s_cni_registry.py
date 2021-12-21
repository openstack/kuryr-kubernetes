# Copyright 2017 Red Hat, Inc.
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

import retrying

from os_vif import objects as obj_vif
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes.cni.plugins import base as base_cni
from kuryr_kubernetes.cni import utils
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils as k_utils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
RETRY_DELAY = 1000  # 1 second in milliseconds

# TODO(dulek, gryf): Another corner case is (and was) when pod is deleted
# before it's corresponding CRD was created and populated by vifs by
# controller or even noticed by any watcher. Kubelet will try to delete such
# vif, but we will have no data about it. This is currently worked around by
# returning successfully in case of timing out in delete. To solve this
# properly we need to watch for pod deletes as well, or perhaps create
# finalizer for the pod as soon, as we know, that kuryrport CRD will be
# created.


class K8sCNIRegistryPlugin(base_cni.CNIPlugin):
    def __init__(self, registry, healthy):
        self.healthy = healthy
        self.registry = registry
        self.k8s = clients.get_kubernetes_client()

    def _get_obj_name(self, params):
        return "%(namespace)s/%(name)s" % {
            'namespace': params.args.K8S_POD_NAMESPACE,
            'name': params.args.K8S_POD_NAME}

    def add(self, params):
        kp_name = self._get_obj_name(params)
        timeout = CONF.cni_daemon.vif_annotation_timeout

        # Try to confirm if CRD in the registry is not stale cache. If it is,
        # remove it.
        with lockutils.lock(kp_name, external=True):
            if kp_name in self.registry:
                cached_kp = self.registry[kp_name]['kp']
                try:
                    kp = self.k8s.get(k_utils.get_res_link(cached_kp))
                except Exception:
                    LOG.exception('Error when getting KuryrPort %s', kp_name)
                    raise exceptions.ResourceNotReady(kp_name)

                if kp['metadata']['uid'] != cached_kp['metadata']['uid']:
                    LOG.warning('Stale KuryrPort %s detected in cache. (API '
                                'uid=%s, cached uid=%s). Removing it from '
                                'cache.', kp_name, kp['metadata']['uid'],
                                cached_kp['metadata']['uid'])
                    del self.registry[kp_name]

        vifs = self._do_work(params, b_base.connect, timeout)

        # NOTE(dulek): Saving containerid to be able to distinguish old DEL
        #              requests that we should ignore. We need a lock to
        #              prevent race conditions and replace whole object in the
        #              dict for multiprocessing.Manager to notice that.
        with lockutils.lock(kp_name, external=True):
            d = self.registry[kp_name]
            d['containerid'] = params.CNI_CONTAINERID
            self.registry[kp_name] = d
            LOG.debug('Saved containerid = %s for CRD %s',
                      params.CNI_CONTAINERID, kp_name)

        # Wait for timeout sec, 1 sec between tries, retry when even one
        # vif is not active.
        @retrying.retry(stop_max_delay=timeout * 1000, wait_fixed=RETRY_DELAY,
                        retry_on_result=utils.any_vif_inactive)
        def wait_for_active(kp_name):
            return self.registry[kp_name]['vifs']

        data = {'metadata': {'name': params.args.K8S_POD_NAME,
                             'namespace': params.args.K8S_POD_NAMESPACE}}
        pod = k_utils.get_referenced_object(data, 'Pod')

        try:
            self.k8s.add_event(pod, 'CNIWaitingForVIFs',
                               f'Waiting for Neutron ports of {kp_name} to '
                               f'become ACTIVE after binding.',
                               component='kuryr-daemon')
            vifs = wait_for_active(kp_name)
        except retrying.RetryError:
            self.k8s.add_event(pod, 'CNITimedOutWaitingForVIFs',
                               f'Timed out waiting for Neutron ports of '
                               f'{kp_name} to become ACTIVE after binding.',
                               'Warning', 'kuryr-daemon')
            raise exceptions.CNINeutronPortActivationTimeout(
                kp_name, self.registry[kp_name]['vifs'])

        return vifs[k_const.DEFAULT_IFNAME]

    def delete(self, params):
        kp_name = self._get_obj_name(params)
        try:
            reg_ci = self.registry[kp_name]['containerid']
            LOG.debug('Read containerid = %s for KuryrPort %s', reg_ci,
                      kp_name)
            if reg_ci and reg_ci != params.CNI_CONTAINERID:
                # NOTE(dulek): This is a DEL request for some older (probably
                #              failed) ADD call. We should ignore it or we'll
                #              unplug a running pod.
                LOG.warning('Received DEL request for unknown ADD call for '
                            'Kuryrport %s (CNI_CONTAINERID=%s). Ignoring.',
                            kp_name, params.CNI_CONTAINERID)
                return
        except KeyError:
            pass

        # Passing arbitrary 5 seconds as timeout, as it does not make any sense
        # to wait on CNI DEL. If kuryrport got deleted from API - VIF info is
        # gone. If kuryrport got the vif info removed - it is now gone too.
        # The number's not 0, because we need to anticipate for restarts and
        # delay before registry is populated by watcher.
        try:
            self._do_work(params, b_base.disconnect, 5)
        except exceptions.CNIKuryrPortTimeout:
            # So the VIF info seems to be lost at this point, we don't even
            # know what binding driver was used to plug it. Let's at least
            # try to remove the interface we created from the netns to prevent
            # possible VLAN ID conflicts.
            b_base.cleanup(params.CNI_IFNAME, params.CNI_NETNS)
            raise

        # NOTE(ndesh): We need to lock here to avoid race condition
        #              with the deletion code in the watcher to ensure that
        #              we delete the registry entry exactly once
        try:
            with lockutils.lock(kp_name, external=True):
                if self.registry[kp_name]['del_received']:
                    del self.registry[kp_name]
                else:
                    kp_dict = self.registry[kp_name]
                    kp_dict['vif_unplugged'] = True
                    self.registry[kp_name] = kp_dict
        except KeyError:
            # This means the kuryrport was removed before vif was unplugged.
            # This shouldn't happen, but we can't do anything about it now
            LOG.debug('KuryrPort %s not found registry while handling DEL '
                      'request. Ignoring.', kp_name)
            pass

    def report_drivers_health(self, driver_healthy):
        if not driver_healthy:
            with self.healthy.get_lock():
                LOG.debug("Reporting CNI driver not healthy.")
                self.healthy.value = driver_healthy

    def _do_work(self, params, fn, timeout):
        kp_name = self._get_obj_name(params)

        # In case of KeyError retry for `timeout` s, wait 1 s between tries.
        @retrying.retry(stop_max_delay=timeout * 1000, wait_fixed=RETRY_DELAY,
                        retry_on_exception=lambda e: isinstance(e, KeyError))
        def find():
            return self.registry[kp_name]

        try:
            d = find()
            kp = d['kp']
            vifs = d['vifs']
        except KeyError:
            data = {'metadata': {'name': params.args.K8S_POD_NAME,
                                 'namespace': params.args.K8S_POD_NAMESPACE}}
            pod = k_utils.get_referenced_object(data, 'Pod')
            self.k8s.add_event(pod, 'CNITimeoutKuryrPortRegistry',
                               f'Timed out waiting for Neutron ports to be '
                               f'created for {kp_name}. Check '
                               f'kuryr-controller logs.', 'Warning',
                               'kuryr-daemon')
            raise exceptions.CNIKuryrPortTimeout(kp_name)

        for ifname, vif in vifs.items():
            is_default_gateway = (ifname == k_const.DEFAULT_IFNAME)
            if is_default_gateway:
                # NOTE(ygupta): if this is the default interface, we should
                # use the ifname supplied in the CNI ADD request
                ifname = params.CNI_IFNAME

            fn(vif, self._get_inst(kp), ifname, params.CNI_NETNS,
                report_health=self.report_drivers_health,
                is_default_gateway=is_default_gateway,
                container_id=params.CNI_CONTAINERID)
        return vifs

    def _get_inst(self, kp):
        return (obj_vif.instance_info
                .InstanceInfo(uuid=kp['spec']['podUid'],
                              name=kp['metadata']['name']))
