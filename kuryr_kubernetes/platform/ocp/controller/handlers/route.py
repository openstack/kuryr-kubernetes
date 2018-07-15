# Copyright (c) 2017 RedHat, Inc.
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

from kuryr.lib._i18n import _

from kuryr_kubernetes import clients
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes.controller.ingress import ingress_ctl
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from kuryr_kubernetes.objects import route as obj_route
from kuryr_kubernetes.platform import constants as ocp_const
from oslo_log import log as logging
from oslo_serialization import jsonutils

LOG = logging.getLogger(__name__)


class OcpRouteHandler(k8s_base.ResourceEventHandler):
    """OcpRouteHandler handles OCP route events.

    An OpenShift route allows service to be externally-reachable via host name.
    This host name is then used to route traffic to the service.
    The OcpRouteHandler is responsible for processing all route resource
    events.

    """

    OBJECT_KIND = ocp_const.OCP_OBJ_ROUTE
    OBJECT_WATCH_PATH = "%s/%s" % (ocp_const.OCP_API_BASE, "routes")

    def __init__(self):
        self._drv_lbaas = drv_base.LBaaSDriver.get_instance()
        self._l7_router = None
        self._l7_router_listeners = None

    def on_present(self, route):
        if not self._l7_router or not self._l7_router_listeners:
            ing_ctl = ingress_ctl.IngressCtrlr.get_instance()
            self._l7_router, self._l7_router_listeners = (
                ing_ctl.get_router_and_listener())
            if not self._l7_router or not self._l7_router_listeners:
                LOG.info("No L7 router found - do nothing")
                return

        route_spec = self._get_route_spec(route)
        if not route_spec:
            route_spec = obj_route.RouteSpec()

        if self._should_ignore(route, route_spec):
            return
        route_state = self._get_route_state(route)
        if not route_state:
            route_state = obj_route.RouteState()

        self._sync_router_pool(route, route_spec, route_state)
        self._sync_l7_policy(route, route_spec, route_state)
        self._sync_host_l7_rule(route, route_spec, route_state)
        self._sync_path_l7_rule(route, route_spec, route_state)

        self._set_route_state(route, route_state)
        self._set_route_spec(route, route_spec)
        self._send_route_notification_to_ep(
            route, route_spec.to_service)

    def _get_endpoints_link_by_route(self, route_link, ep_name):
        route_link = route_link.replace(
            ocp_const.OCP_API_BASE, k_const.K8S_API_BASE)
        link_parts = route_link.split('/')
        if link_parts[-2] != 'routes':
            raise k_exc.IntegrityError(_(
                "Unsupported route link: %(link)s") % {
                'link': route_link})
        link_parts[-2] = 'endpoints'
        link_parts[-1] = ep_name
        return "/".join(link_parts)

    def _send_route_notification_to_ep(self, route, ep_name):
        route_link = route['metadata']['selfLink']
        ep_link = self._get_endpoints_link_by_route(route_link, ep_name)
        k8s = clients.get_kubernetes_client()
        try:
            k8s.get(ep_link)
        except k_exc.K8sClientException:
            LOG.debug("Failed to get EP link : %s", ep_link)
            return

        route_notifier = obj_lbaas.LBaaSRouteNotifier()
        route_notifier.routes.append(
            obj_lbaas.LBaaSRouteNotifEntry(
                route_id=route['metadata']['uid'], msg='RouteChanged'))
        route_notifier.obj_reset_changes(recursive=True)
        LOG.debug("Setting LBaaSRouteNotifier annotation: %r", route_notifier)
        annotation = jsonutils.dumps(route_notifier.obj_to_primitive(),
                                     sort_keys=True)
        k8s.annotate(
            ep_link,
            {k_const.K8S_ANNOTATION_LBAAS_RT_NOTIF: annotation},
            resource_version=route['metadata']['resourceVersion'])

    def _should_ignore(self, route, route_spec):
        spec = route['spec']
        return ((not self._l7_router)
                or
                ((spec.get('host') == route_spec.host) and
                (spec.get('path') == route_spec.path) and
                (spec['to'].get('name') == route_spec.to_service)))

    def on_deleted(self, route):
        if not self._l7_router:
            LOG.info("No L7 router found - do nothing")
            return

        route_state = self._get_route_state(route)
        if not route_state:
            return
        # NOTE(yboaron): deleting l7policy deletes also l7rules
        if route_state.l7_policy:
            self._drv_lbaas.release_l7_policy(
                self._l7_router, route_state.l7_policy)

        if route_state.router_pool:
            if self._drv_lbaas.is_pool_used_by_other_l7policies(
                    route_state.l7_policy, route_state.router_pool):
                LOG.debug("Can't delete pool (pointed by another route)")
            else:
                self._drv_lbaas.release_pool(
                    self._l7_router, route_state.router_pool)
                # no more routes pointing to this pool/ep - update ep
                spec = route['spec']
                self._send_route_notification_to_ep(
                    route, spec['to'].get('name'))

    def _sync_router_pool(self, route, route_spec, route_state):
        if route_state.router_pool:
            return

        pool_name = self._drv_lbaas.get_loadbalancer_pool_name(
            self._l7_router, route['metadata']['namespace'],
            route['spec']['to']['name'])
        pool = self._drv_lbaas.get_pool_by_name(
            pool_name, self._l7_router.project_id)
        if not pool:
            pool = self._drv_lbaas.ensure_pool_attached_to_lb(
                self._l7_router, route['metadata']['namespace'],
                route['spec']['to']['name'], protocol='HTTP')

        route_state.router_pool = pool
        route_spec.to_service = route['spec']['to']['name']

    def _sync_l7_policy(self, route, route_spec, route_state):
        if route_state.l7_policy:
            return
        # TBD , take care of listener HTTPS
        listener = self._l7_router_listeners[k_const.KURYR_L7_ROUTER_HTTP_PORT]

        route_state.l7_policy = self._drv_lbaas.ensure_l7_policy(
            route['metadata']['namespace'], route['metadata']['name'],
            self._l7_router, route_state.router_pool, listener.id)

    def _sync_host_l7_rule(self, route, route_spec, route_state):
        if route_spec.host == route['spec']['host']:
            return
        if not route_spec.host:
            route_state.h_l7_rule = self._drv_lbaas.ensure_l7_rule(
                self._l7_router, route_state.l7_policy,
                'EQUAL_TO', 'HOST_NAME', route['spec']['host'])
        else:
            self._drv_lbaas.update_l7_rule(
                route_state.h_l7_rule, route['spec']['host'])
            route_state.h_l7_rule.value = route['spec']['host']

        route_spec.host = route['spec']['host']

    def _sync_path_l7_rule(self, route, route_spec, route_state):
        if route_spec.path == route['spec'].get('path'):
            return
        if not route_spec.path:
            route_state.p_l7_rule = self._drv_lbaas.ensure_l7_rule(
                self._l7_router, route_state.l7_policy,
                'STARTS_WITH', 'PATH', route['spec']['path'])
        else:
            if route['spec']['path']:
                self._drv_lbaas.update_l7_rule(
                    route_state.p_l7_rule, route['spec']['path'])
                route_state.p_l7_rule.value = route['spec']['path']
            else:
                self._drv_lbaas.release_l7_rule(route_state.p_l7_rule)
                route_state.p_l7_rule = None

        route_spec.path = route['spec']['path']

    def _get_route_spec(self, route):
        try:
            annotations = route['metadata']['annotations']
            annotation = annotations[k_const.K8S_ANNOTATION_ROUTE_SPEC]
        except KeyError:
            return obj_route.RouteSpec()
        obj_dict = jsonutils.loads(annotation)
        obj = obj_route.RouteSpec.obj_from_primitive(obj_dict)
        LOG.debug("Got RouteSpec from annotation: %r", obj)
        return obj

    def _set_route_spec(self, route, route_spec):
        if route_spec is None:
            LOG.debug("Removing RouteSpec annotation: %r", route_spec)
            annotation = None
        else:
            route_spec.obj_reset_changes(recursive=True)
            LOG.debug("Setting RouteSpec annotation: %r", route_spec)
            annotation = jsonutils.dumps(route_spec.obj_to_primitive(),
                                         sort_keys=True)
        k8s = clients.get_kubernetes_client()
        k8s.annotate(route['metadata']['selfLink'],
                     {k_const.K8S_ANNOTATION_ROUTE_SPEC: annotation},
                     resource_version=route['metadata']['resourceVersion'])

    def _get_route_state(self, route):
        try:
            annotations = route['metadata']['annotations']
            annotation = annotations[k_const.K8S_ANNOTATION_ROUTE_STATE]
        except KeyError:
            return obj_route.RouteState()
        obj_dict = jsonutils.loads(annotation)
        obj = obj_route.RouteState.obj_from_primitive(obj_dict)
        LOG.debug("Got RouteState from annotation: %r", obj)
        return obj

    def _set_route_state(self, route, route_state):
        if route_state is None:
            LOG.debug("Removing RouteState annotation: %r", route_state)
            annotation = None
        else:
            route_state.obj_reset_changes(recursive=True)
            LOG.debug("Setting RouteState annotation: %r", route_state)
            annotation = jsonutils.dumps(route_state.obj_to_primitive(),
                                         sort_keys=True)
        k8s = clients.get_kubernetes_client()
        k8s.annotate(route['metadata']['selfLink'],
                     {k_const.K8S_ANNOTATION_ROUTE_STATE: annotation},
                     resource_version=route['metadata']['resourceVersion'])
