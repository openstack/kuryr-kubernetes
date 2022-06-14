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

import itertools
import time

import requests

from openstack import exceptions as os_exc
from oslo_log import log as logging
from oslo_utils import excutils

from kuryr_kubernetes import clients
from kuryr_kubernetes.controller.managers import prometheus_exporter
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class Retry(base.EventHandler):
    """Retries handler on failure.

    `Retry` can be used to decorate another `handler` to be retried whenever
    it raises any of the specified `exceptions`. If the `handler` does not
    succeed within the time limit specified by `timeout`, `Retry` will
    raise the exception risen by `handler`. `Retry` does not interrupt the
    `handler`, so the actual time spent within a single call to `Retry` may
    exceed the `timeout` depending on responsiveness of the `handler`.

    `handler` is retried for the same `event` (expected backoff E(c) =
    interval * 2 ** c / 2).
    """

    def __init__(self, handler, exceptions=Exception,
                 timeout=utils.DEFAULT_TIMEOUT,
                 interval=utils.DEFAULT_INTERVAL):
        self._handler = handler
        self._exceptions = exceptions
        self._timeout = timeout
        self._interval = interval
        self._k8s = clients.get_kubernetes_client()

    def __call__(self, event, *args, **kwargs):
        start_time = time.time()
        deadline = time.time() + self._timeout
        for attempt in itertools.count(1):
            if event.get('type') in ['MODIFIED', 'ADDED']:
                obj = event.get('object')
                if obj:
                    try:
                        obj_link = utils.get_res_link(obj)
                    except KeyError:
                        LOG.debug("Unknown object, skipping: %s", obj)
                    else:
                        try:
                            self._k8s.get(obj_link)
                        except exceptions.K8sResourceNotFound:
                            LOG.debug("There is no need to process the "
                                      "retry as the object %s has already "
                                      "been deleted.", obj_link)
                            return
                        except (exceptions.K8sClientException,
                                requests.ConnectionError):
                            LOG.debug("Kubernetes client error getting the "
                                      "object. Continuing with handler "
                                      "execution.")
            try:
                info = {
                    'elapsed': time.time() - start_time
                }
                self._handler(event, *args, retry_info=info, **kwargs)
                break
            except (exceptions.LoadBalancerNotReady,
                    exceptions.PortNotReady) as exc:
                cls_map = {'LoadBalancerNotReady': 'record_lb_failure',
                           'PortNotReady': 'record_port_failure'}
                with excutils.save_and_reraise_exception() as ex:
                    if self._sleep(deadline, attempt, ex.value):
                        ex.reraise = False
                    else:
                        exporter = (prometheus_exporter
                                    .ControllerPrometheusExporter
                                    .get_instance())
                        method = getattr(exporter, cls_map[type(exc).__name__])
                        method()
            except exceptions.KuryrLoadBalancerNotCreated:
                with excutils.save_and_reraise_exception() as ex:
                    if self._sleep(deadline, attempt, ex.value):
                        ex.reraise = False
            except os_exc.ConflictException:
                with excutils.save_and_reraise_exception() as ex:
                    error_type = clients.get_neutron_error_type(ex.value)
                    if error_type == 'OverQuota':
                        if self._sleep(deadline, attempt, ex.value):
                            ex.reraise = False
            except self._exceptions:
                with excutils.save_and_reraise_exception() as ex:
                    if self._sleep(deadline, attempt, ex.value):
                        ex.reraise = False
                    else:
                        LOG.exception('Report handler unhealthy %s',
                                      self._handler)
                        self._handler.set_liveness(alive=False, exc=ex.value)
            except Exception as ex:
                LOG.exception('Report handler unhealthy %s', self._handler)
                self._handler.set_liveness(alive=False, exc=ex)
                raise

    def _sleep(self, deadline, attempt, exception):
        LOG.debug("Handler %s failed (attempt %s; %s)",
                  self._handler, attempt, exceptions.format_msg(exception))
        interval = utils.exponential_sleep(deadline, attempt,
                                           self._interval)
        if not interval:
            LOG.debug("Handler %s failed (attempt %s; %s), "
                      "timeout exceeded (%s seconds)",
                      self._handler, attempt, exceptions.format_msg(exception),
                      self._timeout)
            return 0

        LOG.debug("Resumed after %s seconds. Retry handler %s", interval,
                  self._handler)
        return interval
