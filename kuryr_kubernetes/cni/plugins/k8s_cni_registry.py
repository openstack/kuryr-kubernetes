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
from os_vif.objects import base
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes.cni.plugins import base as base_cni
from kuryr_kubernetes.cni import utils
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import exceptions

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
RETRY_DELAY = 1000  # 1 second in milliseconds

# TODO(dulek): Another corner case is (and was) when pod is deleted before it's
#              annotated by controller or even noticed by any watcher. Kubelet
#              will try to delete such vif, but we will have no data about it.
#              This is currently worked around by returning successfully in
#              case of timing out in delete. To solve this properly we need
#              to watch for pod deletes as well.


class K8sCNIRegistryPlugin(base_cni.CNIPlugin):
    def __init__(self, registry, healthy):
        self.healthy = healthy
        self.registry = registry

    def _get_pod_name(self, params):
        return "%(namespace)s/%(name)s" % {
            'namespace': params.args.K8S_POD_NAMESPACE,
            'name': params.args.K8S_POD_NAME}

    def add(self, params):
        vifs = self._do_work(params, b_base.connect)

        pod_name = self._get_pod_name(params)

        # NOTE(dulek): Saving containerid to be able to distinguish old DEL
        #              requests that we should ignore. We need a lock to
        #              prevent race conditions and replace whole object in the
        #              dict for multiprocessing.Manager to notice that.
        with lockutils.lock(pod_name, external=True):
            d = self.registry[pod_name]
            d['containerid'] = params.CNI_CONTAINERID
            self.registry[pod_name] = d
            LOG.debug('Saved containerid = %s for pod %s',
                      params.CNI_CONTAINERID, pod_name)

        # Wait for VIFs to become active.
        timeout = CONF.cni_daemon.vif_annotation_timeout

        # Wait for timeout sec, 1 sec between tries, retry when even one
        # vif is not active.
        @retrying.retry(stop_max_delay=timeout * 1000, wait_fixed=RETRY_DELAY,
                        retry_on_result=utils.any_vif_inactive)
        def wait_for_active(pod_name):
            return {
                ifname: base.VersionedObject.obj_from_primitive(vif_obj) for
                ifname, vif_obj in self.registry[pod_name]['vifs'].items()
            }

        vifs = wait_for_active(pod_name)
        for vif in vifs.values():
            if not vif.active:
                LOG.error("Timed out waiting for vifs to become active")
                raise exceptions.ResourceNotReady(pod_name)

        return vifs[k_const.DEFAULT_IFNAME]

    def delete(self, params):
        pod_name = self._get_pod_name(params)
        try:
            reg_ci = self.registry[pod_name]['containerid']
            LOG.debug('Read containerid = %s for pod %s', reg_ci, pod_name)
            if reg_ci and reg_ci != params.CNI_CONTAINERID:
                # NOTE(dulek): This is a DEL request for some older (probably
                #              failed) ADD call. We should ignore it or we'll
                #              unplug a running pod.
                LOG.warning('Received DEL request for unknown ADD call. '
                            'Ignoring.')
                return
        except KeyError:
            pass
        self._do_work(params, b_base.disconnect)
        # NOTE(ndesh): We need to lock here to avoid race condition
        #              with the deletion code in the watcher to ensure that
        #              we delete the registry entry exactly once
        try:
            with lockutils.lock(pod_name, external=True):
                if self.registry[pod_name]['del_received']:
                    del self.registry[pod_name]
                else:
                    pod_dict = self.registry[pod_name]
                    pod_dict['vif_unplugged'] = True
                    self.registry[pod_name] = pod_dict
        except KeyError:
            # This means the pod was removed before vif was unplugged. This
            # shouldn't happen, but we can't do anything about it now
            LOG.debug('Pod %s not found registry while handling DEL request. '
                      'Ignoring.', pod_name)
            pass

    def report_drivers_health(self, driver_healthy):
        if not driver_healthy:
            with self.healthy.get_lock():
                LOG.debug("Reporting CNI driver not healthy.")
                self.healthy.value = driver_healthy

    def _do_work(self, params, fn):
        pod_name = self._get_pod_name(params)

        timeout = CONF.cni_daemon.vif_annotation_timeout

        # In case of KeyError retry for `timeout` s, wait 1 s between tries.
        @retrying.retry(stop_max_delay=timeout * 1000, wait_fixed=RETRY_DELAY,
                        retry_on_exception=lambda e: isinstance(e, KeyError))
        def find():
            return self.registry[pod_name]

        try:
            d = find()
            pod = d['pod']
            vifs = {
                ifname: base.VersionedObject.obj_from_primitive(vif_obj) for
                ifname, vif_obj in d['vifs'].items()
            }
        except KeyError:
            LOG.error("Timed out waiting for requested pod to appear in "
                      "registry")
            raise exceptions.ResourceNotReady(pod_name)

        for ifname, vif in vifs.items():
            is_default_gateway = (ifname == k_const.DEFAULT_IFNAME)
            if is_default_gateway:
                # NOTE(ygupta): if this is the default interface, we should
                # use the ifname supplied in the CNI ADD request
                ifname = params.CNI_IFNAME

            fn(vif, self._get_inst(pod), ifname, params.CNI_NETNS,
                report_health=self.report_drivers_health,
                is_default_gateway=is_default_gateway,
                container_id=params.CNI_CONTAINERID)
        return vifs

    def _get_inst(self, pod):
        return obj_vif.instance_info.InstanceInfo(
            uuid=pod['metadata']['uid'], name=pod['metadata']['name'])
