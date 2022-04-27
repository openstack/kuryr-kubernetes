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


class K8sCNIRegistryPlugin(base_cni.CNIPlugin):
    def __init__(self, registry, healthy):
        self.healthy = healthy
        self.registry = registry
        self.k8s = clients.get_kubernetes_client()

    def _get_obj_name(self, params):
        return f'{params.args.K8S_POD_NAMESPACE}/{params.args.K8S_POD_NAME}'

    def _get_pod(self, params):
        namespace = params.args.K8S_POD_NAMESPACE
        name = params.args.K8S_POD_NAME

        try:
            return self.k8s.get(
                f'{k_const.K8S_API_NAMESPACES}/{namespace}/pods/{name}')
        except exceptions.K8sResourceNotFound:
            return None
        except exceptions.K8sClientException:
            uniq_name = self._get_obj_name(params)
            LOG.exception('Error when getting Pod %s', uniq_name)
            raise

    def add(self, params):
        kp_name = self._get_obj_name(params)
        timeout = CONF.cni_daemon.vif_annotation_timeout

        # In order to fight race conditions when pods get recreated with the
        # same name (think StatefulSet), we're trying to get pod UID either
        # from the request or the API in order to use it as the ID to compare.
        if 'K8S_POD_UID' not in params.args:
            # CRI doesn't pass K8S_POD_UID, get it from the API.
            pod = self._get_pod(params)
            if not pod:
                raise exceptions.CNIPodGone(kp_name)
            params.args.K8S_POD_UID = pod['metadata']['uid']

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
            self.k8s.add_event(pod, 'CNIWaitingForActiveVIFs',
                               f'Waiting for Neutron ports of {kp_name} to '
                               f'become ACTIVE after binding.',
                               component='kuryr-daemon')
            vifs = wait_for_active(kp_name)
        except retrying.RetryError:
            self.k8s.add_event(pod, 'CNITimedOutWaitingForActiveVIFs',
                               f'Timed out waiting for Neutron ports of '
                               f'{kp_name} to become ACTIVE after binding.',
                               'Warning', 'kuryr-daemon')
            raise exceptions.CNINeutronPortActivationTimeout(
                kp_name, self.registry[kp_name]['vifs'])

        return vifs[k_const.DEFAULT_IFNAME]

    def delete(self, params):
        kp_name = self._get_obj_name(params)
        try:
            with lockutils.lock(kp_name, external=True):
                kp = self.registry[kp_name]
                if kp == k_const.CNI_DELETED_POD_SENTINEL:
                    LOG.warning(
                        'Received DEL request for deleted Pod %s without a'
                        'KuryrPort. Ignoring.', kp_name)
                    del self.registry[kp_name]
                    return
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
        except (exceptions.CNIKuryrPortTimeout, exceptions.CNIPodUidMismatch):
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

    def _get_vifs_from_registry(self, params, timeout):
        kp_name = self._get_obj_name(params)

        # In case of KeyError retry for `timeout` s, wait 1 s between tries.
        @retrying.retry(stop_max_delay=timeout * 1000, wait_fixed=RETRY_DELAY,
                        retry_on_exception=lambda e: isinstance(
                            e, (KeyError, exceptions.CNIPodUidMismatch)))
        def find():
            d = self.registry[kp_name]
            if d == k_const.CNI_DELETED_POD_SENTINEL:
                # Pod got deleted meanwhile
                raise exceptions.CNIPodGone(kp_name)

            static = d['kp']['spec'].get('podStatic', None)
            uid = d['kp']['spec']['podUid']
            # FIXME(dulek): This is weirdly structured for upgrades support.
            #               If podStatic is not set (KuryrPort created by old
            #               Kuryr version), then on uid mismatch we're fetching
            #               pod from API and check if it's static here. Pods
            #               are quite ephemeral, so will gradually get replaced
            #               after the upgrade and in a while all should have
            #               the field set and the performance penalty should
            #               be resolved. Remove in the future.
            if 'K8S_POD_UID' in params.args and uid != params.args.K8S_POD_UID:
                if static is None:
                    pod = self._get_pod(params)
                    static = k_utils.is_pod_static(pod)

                # Static pods have mirror pod UID in API, so it's always
                # mismatched. We don't raise in that case. See [1] for more.
                # [1] https://github.com/k8snetworkplumbingwg/multus-cni/
                #     issues/773
                if not static:
                    raise exceptions.CNIPodUidMismatch(
                        kp_name, params.args.K8S_POD_UID, uid)
            return d

        try:
            d = find()
            return d['kp'], d['vifs']
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

    def _do_work(self, params, fn, timeout):
        kp, vifs = self._get_vifs_from_registry(params, timeout)

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
