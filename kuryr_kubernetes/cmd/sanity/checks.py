# Copyright (c) 2021 OpenStack Foundation.
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


from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import config

CONF = config.CONF
LOG = logging.getLogger(__name__)


def _logger():
    if cfg.CONF.sanity_check_error:
        return LOG.error
    else:
        return LOG.warning


def ports_pool_min_max():
    try:
        if not cfg.CONF.vif_pool.ports_pool_max:
            return True
        pool_max = cfg.CONF.vif_pool.ports_pool_max
        pool_min = cfg.CONF.vif_pool.ports_pool_min
        if pool_max < pool_min:
            _logger()(f'The current configuration of ports_pool_min '
                      f'"{pool_min}" and ports_pool_max "{pool_max}" '
                      f'may cause infinite loop of creating '
                      f'and deleting ports.')
            return False
    except (OSError, RuntimeError, IndexError, ValueError) as e:
        LOG.debug("Exception while checking ports_pool_max. "
                  "Exception: %s", e)
        return False
    return True


def ports_pool_min_batch():
    try:
        pool_min = cfg.CONF.vif_pool.ports_pool_min
        pool_batch = cfg.CONF.vif_pool.ports_pool_batch
        if pool_min > pool_batch:
            _logger()(f'The current configuration of ports_pool_min '
                      f'"{pool_min}" and ports_pool_batch "{pool_batch}" '
                      f'may cause kuryr to send multiple unnecessary '
                      f'bulk ports creation requests. ')
            return False
    except (OSError, RuntimeError, IndexError, ValueError) as e:
        LOG.debug("Exception while checking ports_pool_batch. "
                  "Exception: %s", e)
        return False
    return True


def ports_pool_max_batch():
    try:
        if not cfg.CONF.vif_pool.ports_pool_max:
            return True
        pool_max = cfg.CONF.vif_pool.ports_pool_max
        pool_batch = cfg.CONF.vif_pool.ports_pool_batch
        if pool_max < pool_batch:
            _logger()(f'The current configuration of ports_pool_max '
                      f'"{pool_max}" and ports_pool_batch "{pool_batch}" '
                      f'may cause kuryr to create the '
                      f'ports and then delete them immediately.')
            return False
    except (OSError, RuntimeError, IndexError, ValueError) as e:
        LOG.debug("Exception while checking ports_pool_batch. "
                  "Exception: %s", e)
        return False
    return True
