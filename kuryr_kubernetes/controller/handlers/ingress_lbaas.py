# Copyright (c) 2018 RedHat, Inc.
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

from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes.controller.handlers import lbaas as h_lbaas
from kuryr_kubernetes.controller.ingress import ingress_ctl
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class IngressLoadBalancerHandler(h_lbaas.LoadBalancerHandler):
    """IngressLoadBalancerHandler handles K8s Endpoints events.

    IngressLoadBalancerHandler handles K8s Endpoints events and tracks
    changes in LBaaSServiceSpec to update Ingress Controller
    L7 router accordingly.
    """

    OBJECT_KIND = k_const.K8S_OBJ_ENDPOINTS
    OBJECT_WATCH_PATH = "%s/%s" % (k_const.K8S_API_BASE, "endpoints")

    def __init__(self):
        super(IngressLoadBalancerHandler, self).__init__()
        self._drv_lbaas = drv_base.LBaaSDriver.get_instance()
        self._l7_router = None

    def _should_ignore(self, endpoints, lbaas_spec):
        return not(lbaas_spec and
                   self._has_pods(endpoints))

    def on_present(self, endpoints):
        if not self._l7_router:
            ing_ctl = ingress_ctl.IngressCtrlr.get_instance()
            self._l7_router, listener = ing_ctl.get_router_and_listener()
            if not self._l7_router:
                LOG.info("No L7 router found - do nothing")
                return

        lbaas_spec = utils.get_lbaas_spec(endpoints)
        if self._should_ignore(endpoints, lbaas_spec):
            return

        pool_name = self._drv_lbaas.get_loadbalancer_pool_name(
            self._l7_router, endpoints['metadata']['namespace'],
            endpoints['metadata']['name'])
        pool = self._drv_lbaas.get_pool_by_name(pool_name,
                                                self._l7_router.project_id)
        if not pool:
            if self._get_lbaas_route_state(endpoints):
                self._set_lbaas_route_state(endpoints, None)
            LOG.debug("L7 routing: no route defined for service "
                      ":%s - do nothing", endpoints['metadata']['name'])
        else:
            # pool was found in L7 router LB ,verify that members are up2date
            lbaas_route_state = self._get_lbaas_route_state(endpoints)
            if not lbaas_route_state:
                lbaas_route_state = obj_lbaas.LBaaSRouteState()
            lbaas_route_state.pool = pool
            if self._sync_lbaas_route_members(endpoints,
                                              lbaas_route_state, lbaas_spec):
                self._set_lbaas_route_state(endpoints, lbaas_route_state)
        self._clear_route_notification(endpoints)

    def on_deleted(self, endpoints):
        if not self._l7_router:
            LOG.info("No L7 router found - do nothing")
            return

        lbaas_route_state = self._get_lbaas_route_state(endpoints)
        if not lbaas_route_state:
            return
        self._remove_unused_route_members(endpoints, lbaas_route_state,
                                          obj_lbaas.LBaaSServiceSpec())

    def _sync_lbaas_route_members(self, endpoints,
                                  lbaas_route_state, lbaas_spec):
        changed = False
        if self._remove_unused_route_members(
                endpoints, lbaas_route_state, lbaas_spec):
            changed = True

        if self._add_new_route_members(endpoints, lbaas_route_state):
            changed = True

        return changed

    def _add_new_route_members(self, endpoints, lbaas_route_state):
        changed = False

        current_targets = {(str(m.ip), m.port)
                           for m in lbaas_route_state.members}

        for subset in endpoints.get('subsets', []):
            subset_ports = subset.get('ports', [])
            for subset_address in subset.get('addresses', []):
                try:
                    target_ip = subset_address['ip']
                    target_ref = subset_address['targetRef']
                    if target_ref['kind'] != k_const.K8S_OBJ_POD:
                        continue
                except KeyError:
                    continue
                for subset_port in subset_ports:
                    target_port = subset_port['port']
                    if (target_ip, target_port) in current_targets:
                        continue

                    # TODO(apuimedo): Do not pass subnet_id at all when in
                    # L3 mode once old neutron-lbaasv2 is not supported, as
                    # octavia does not require it
                    if (config.CONF.octavia_defaults.member_mode ==
                            k_const.OCTAVIA_L2_MEMBER_MODE):
                        member_subnet_id = self._get_pod_subnet(target_ref,
                                                                target_ip)
                    else:
                        # We use the service subnet id so that the connectivity
                        # from VIP to pods happens in layer 3 mode, i.e.,
                        # routed.
                        member_subnet_id = self._l7_router.subnet_id
                    member = self._drv_lbaas.ensure_member(
                        loadbalancer=self._l7_router,
                        pool=lbaas_route_state.pool,
                        subnet_id=member_subnet_id,
                        ip=target_ip,
                        port=target_port,
                        target_ref_namespace=target_ref['namespace'],
                        target_ref_name=target_ref['name'])

                    lbaas_route_state.members.append(member)
                    changed = True

        return changed

    def _remove_unused_route_members(
            self, endpoints, lbaas_route_state, lbaas_spec):
        spec_port_names = {p.name for p in lbaas_spec.ports}
        current_targets = {(a['ip'], p['port'])
                           for s in endpoints['subsets']
                           for a in s['addresses']
                           for p in s['ports']
                           if p.get('name') in spec_port_names}
        removed_ids = set()
        for member in lbaas_route_state.members:
            if (str(member.ip), member.port) in current_targets:
                continue
            self._drv_lbaas.release_member(self._l7_router, member)
            removed_ids.add(member.id)
        if removed_ids:
            lbaas_route_state.members = [
                m for m in lbaas_route_state.members
                if m.id not in removed_ids]
        return bool(removed_ids)

    def _set_lbaas_route_state(self, endpoints, route_state):
        if route_state is None:
            LOG.debug("Removing LBaaSRouteState annotation: %r", route_state)
            annotation = None
        else:
            route_state.obj_reset_changes(recursive=True)
            LOG.debug("Setting LBaaSRouteState annotation: %r", route_state)
            annotation = jsonutils.dumps(route_state.obj_to_primitive(),
                                         sort_keys=True)
        k8s = clients.get_kubernetes_client()
        k8s.annotate(endpoints['metadata']['selfLink'],
                     {k_const.K8S_ANNOTATION_LBAAS_RT_STATE: annotation},
                     resource_version=endpoints['metadata']['resourceVersion'])

    def _get_lbaas_route_state(self, endpoints):
        try:
            annotations = endpoints['metadata']['annotations']
            annotation = annotations[k_const.K8S_ANNOTATION_LBAAS_RT_STATE]
        except KeyError:
            return None
        obj_dict = jsonutils.loads(annotation)
        obj = obj_lbaas.LBaaSRouteState.obj_from_primitive(obj_dict)
        LOG.debug("Got LBaaSRouteState from annotation: %r", obj)
        return obj

    def _clear_route_notification(self, endpoints):
        try:
            annotations = endpoints['metadata']['annotations']
            annotation = annotations[
                k_const.K8S_ANNOTATION_LBAAS_RT_NOTIF]
        except KeyError:
            return

        LOG.debug("Removing LBaaSRouteNotifier annotation")
        annotation = None
        k8s = clients.get_kubernetes_client()
        k8s.annotate(
            endpoints['metadata']['selfLink'],
            {k_const.K8S_ANNOTATION_LBAAS_RT_NOTIF: annotation},
            resource_version=endpoints['metadata']['resourceVersion'])
