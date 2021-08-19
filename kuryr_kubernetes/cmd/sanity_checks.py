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

"""
CLI interface for kuryr sanity commands.
"""

import sys

from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes.cmd.sanity import checks
from kuryr_kubernetes import config
from kuryr_kubernetes.controller.drivers import vif_pool  # noqa

LOG = logging.getLogger(__name__)


class BoolOptCallback(cfg.BoolOpt):
    def __init__(self, name, callback, **kwargs):
        if 'default' not in kwargs:
            kwargs['default'] = False
        self.callback = callback
        super(BoolOptCallback, self).__init__(name, **kwargs)


def check_ports_pool_min_max():
    result = checks.ports_pool_min_max()
    if not result:
        LOG.warning("The ports_pool_max is enabled, "
                    "the ports_pool_min should be smaller than "
                    "ports_pool_max. Either disable ports_pool_max "
                    "setting it to 0 or increase it's value.")
    return result


def check_ports_pool_min_batch():
    result = checks.ports_pool_min_batch()
    if not result:
        LOG.warning("The ports_pool_min should be lower than "
                    "ports_pool_batch. Please decrease it's value.")
    return result


def check_ports_pool_max_batch():
    result = checks.ports_pool_max_batch()
    if not result:
        LOG.warning("The ports_pool_max is enabled, "
                    "the ports_pool_max should be higher than "
                    "ports_pool_batch. Either disable ports_pool_max "
                    "setting it to 0 or decrease it's value.")
    return result


# Define CLI opts to test specific features, with a callback for the test
OPTS = [
    BoolOptCallback('vif_pool_min_max', check_ports_pool_min_max,
                    default=False,
                    help='Check configuration sanity of ports_pool_min and '
                         'ports_pool_max.'),
    BoolOptCallback('vif_pool_min_batch', check_ports_pool_min_batch,
                    default=False,
                    help='Check configuration sanity of ports_pool_min and '
                         'ports_pool_batch.'),
    BoolOptCallback('vif_pool_max_batch', check_ports_pool_max_batch,
                    default=False,
                    help='Check configuration sanity of ports_pool_max and '
                         'ports_pool_batch.'),
]

CLI_OPTS = [
    cfg.BoolOpt('sanity_check_error', default=False,
                help='If this flag is configured, the sanity command fails '
                     'if any of the sanity tests fails.'),
]


def all_tests_passed():
    results = [opt.callback() for opt in OPTS if cfg.CONF.get(opt.name)]
    return all(results)


def main():
    cfg.CONF.register_cli_opts(OPTS)
    cfg.CONF.register_cli_opts(CLI_OPTS)
    config.init(sys.argv[1:], default_config_files=['/etc/kuryr/kuryr.conf'])
    config.setup_logging()
    return 0 if all_tests_passed() else 1


if __name__ == '__main__':
    main()
