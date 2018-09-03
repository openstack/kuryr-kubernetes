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
import time


from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes import exceptions
from oslo_log import log as logging


_OCP_ROUTE_HANDLER = 'ocproute'
_INGRESS_LB_HANDLER = 'ingresslb'
_ROUTER_POLL_INTERVAL = 10
# NOTE(yboaron): LoadBalancers creation at Devstack is very slow, could take
# up to 20 minutes
_ROUTER_MANUAL_CREATION_TIMEOUT = 1200

LOG = logging.getLogger(__name__)


class L7Router(object):
    """L7Router is responsible for create/verify L7 LoadBalancer entity."""

    def __init__(self, router_uuid):

        # Note(yboaron) the LBaaS driver is used as the L7 router driver
        self._drv_l7_router = drv_base.LBaaSDriver.get_instance()
        self._l7_router_uuid = router_uuid
        self._l7_router_listeners = None
        self._router_lb = None

    def ensure_router(self):
        # retrieve router details
        self._router_lb = self._drv_l7_router.get_lb_by_uuid(
            self._l7_router_uuid)
        if not self._router_lb:
            LOG.error("Failed to retrieve L7_Router (UUID=%s)",
                      self._l7_router_uuid)
            raise exceptions.IngressControllerFailure
        # verify that loadbalancer is active
        try:
            self._drv_l7_router._wait_for_provisioning(
                self._router_lb, _ROUTER_MANUAL_CREATION_TIMEOUT)
        except exceptions.ResourceNotReady as e:
            LOG.error("Timed out waiting for L7 router to appear in "
                      "ACTIVE state: %s.", e)
            raise exceptions.IngressControllerFailure

        LOG.info("Ingress controller - "
                 "retrieve '%s' router details", self._router_lb)

        # TODO(yboaron) add support for HTTPS listener
        # create/verify listeners
        self._l7_router_listeners = {}
        listener = self._drv_l7_router.ensure_listener(
            self._router_lb, 'HTTP', k_const.KURYR_L7_ROUTER_HTTP_PORT,
            service_type=None)
        LOG.info("Ingress controller - "
                 "retrieve HTTP listener details '%s'", listener)

        self._l7_router_listeners[k_const.KURYR_L7_ROUTER_HTTP_PORT] = listener

    def get_router(self):
        return self._router_lb

    def get_router_listeners(self):
        return self._l7_router_listeners


class IngressCtrlr(object):
    """IngressCtrlr is responsible for the Ingress controller capability

    The Ingress controller should create or verify (in case router pre-created
    by admin) L7 router/LB - the entity that will do the actual L7 routing.
    In addition the Ingress controller should provide the L7 router details
    to Ingress/ocp-route handlers and Endpoint handler.
    Both Ingress/ocp-route handlers and Endpoint handler should update the
    L7 rules of the L7 router.

    """
    instances = {}

    @classmethod
    def get_instance(cls):
        if cls not in IngressCtrlr.instances:
            IngressCtrlr.instances[cls] = cls()
        return IngressCtrlr.instances[cls]

    def __init__(self):
        self._l7_router = None
        self._status = 'DOWN'

    def _start_operation_impl(self):
        LOG.info('Ingress controller is enabled')
        self._l7_router = L7Router(config.CONF.ingress.l7_router_uuid)
        try:
            self._status = 'IN_PROGRESS'
            self._l7_router.ensure_router()
        except Exception as e:
            self._status = 'DOWN'
            LOG.error("Ingress controller - failed to get L7 router (%s)", e)
            return
        self._status = 'ACTIVE'
        LOG.info("Ingress controller - ACTIVE")

    def _is_ingress_controller_disabled(self):
        # Note(yboaron) To enable the ingress controller admin should :
        # A. Set the L7-router/LB UUID in kuryr.conf
        # and
        # B. Add K8S-ingress and OCP-route handlers to pluggable
        # handlers list
        configured_handlers = config.CONF.kubernetes.enabled_handlers
        return not (any(handler in configured_handlers for handler in
                        (_OCP_ROUTE_HANDLER, _INGRESS_LB_HANDLER)) and
                    config.CONF.ingress.l7_router_uuid)

    def start_operation(self):
        if self._is_ingress_controller_disabled():
            LOG.info('To enable Ingress controller either OCP-Route or '
                     'Ingress-LB  handlers should be enabled, and '
                     'l7_router_uuid should be specified')
            return
        self._start_operation_impl()

    def get_router_and_listener(self):
        """This function returns L7 router and Listeners details,

        The caller to this function will be blocked until Ingress controller
        status is in stable (not in progress), the consumers of this function
        will be the OCP-Route and K8S-Ingress handlers
        """
        get_router_threshold = (time.time() + _ROUTER_MANUAL_CREATION_TIMEOUT)
        while True:
            if self._status != 'IN_PROGRESS':
                if self._l7_router:
                    return (self._l7_router.get_router(),
                            self._l7_router.get_router_listeners())
                else:
                    return None, None
            if time.time() > get_router_threshold:
                LOG.error("Ingress controller: get router - timeout expired")
                return None, None
            LOG.debug("Ingress controller - waiting till status is "
                      "!= IN_PROGRESS")
            time.sleep(_ROUTER_POLL_INTERVAL)
