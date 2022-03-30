# Copyright (c) 2017 NEC Technologies India Pvt Ltd.
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

import functools
import time

from http import client as httplib
from oslo_log import log as logging


PROC_ONE_CGROUP_PATH = '/proc/1/cgroup'
CONTAINER_RUNTIME_CGROUP_IDS = (
    'docker',  # This is set by docker/moby
    'libpod',  # This is set by podman
)

LOG = logging.getLogger(__name__)
SUCCESSFUL_REQUEST_CODE = (httplib.NO_CONTENT, httplib.ACCEPTED)


def running_under_container_runtime(proc_one_cg_path=PROC_ONE_CGROUP_PATH):
    """Returns True iff the CNI process is under a known container runtime."""
    with open(proc_one_cg_path, 'r') as cgroup_info:
        proc_one_cg_info = cgroup_info.read()
    return any(runtime in proc_one_cg_info for runtime in
               CONTAINER_RUNTIME_CGROUP_IDS)


def any_vif_inactive(vifs):
    """Return True if there is at least one VIF that's not ACTIVE."""
    return any(not vif.active for vif in vifs.values())


class CNIConfig(dict):
    def __init__(self, cfg):
        super(CNIConfig, self).__init__(cfg)

        for k, v in self.items():
            if not k.startswith('_'):
                setattr(self, k, v)


class CNIArgs(object):
    def __init__(self, value):
        for item in value.split(';'):
            k, v = item.split('=', 1)
            if not k.startswith('_'):
                setattr(self, k, v)

    def __contains__(self, key):
        return hasattr(self, key)


class CNIParameters(object):
    def __init__(self, env, cfg=None):
        for k, v in env.items():
            if k.startswith('CNI_'):
                setattr(self, k, v)
        if cfg is None:
            self.config = CNIConfig(env['config_kuryr'])
        else:
            self.config = cfg
        self.args = CNIArgs(self.CNI_ARGS)

    def __repr__(self):
        return repr({key: value for key, value in self.__dict__.items() if
                     key.startswith('CNI_')})


def log_ipdb(func):
    @functools.wraps(func)
    def with_logging(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RuntimeError as e:
            try:
                LOG.error('Error when manipulating network interfaces')
                LOG.error(e.debug['traceback'])
                LOG.debug('Full debugging info: %s', e.debug)
            except AttributeError:
                pass
            raise
    return with_logging


def measure_time(command):
    """Measures CNI ADD/DEL resquest duration"""
    def decorator(method):
        def wrapper(obj, *args, **kwargs):
            start_time = time.time()
            result = method(obj, *args, **kwargs)
            cni_request_error = (
                result[1] not in SUCCESSFUL_REQUEST_CODE)
            obj._update_metrics(
                command, cni_request_error, time.time() - start_time)
            return result
        wrapper.__name__ = method.__name__
        return wrapper
    return decorator
