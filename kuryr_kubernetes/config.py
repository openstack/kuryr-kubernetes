# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import os
import sys

from kuryr.lib._i18n import _, _LI
from kuryr.lib import config as lib_config
from oslo_config import cfg
from oslo_log import log as logging

from pbr import version as pbr_version

LOG = logging.getLogger(__name__)

kuryr_k8s_opts = [
    cfg.StrOpt('pybasedir',
        help=_('Directory where Kuryr-kubernetes python module is '
               'installed.'),
        default=os.path.abspath(
            os.path.join(os.path.dirname(__file__),
            '../../'))),
]

k8s_opts = [
    cfg.StrOpt('api_root',
        help=_("The root URL of the Kubernetes API"),
        default=os.environ.get('K8S_API', 'http://localhost:8080')),
    cfg.StrOpt('config_map',
        help=_("The dict that stores the relationships between watchers and"
               " translators."),
        default=('kuryr_kubernetes.CONFIG_MAP'))
]


CONF = cfg.CONF

CONF.register_opts(lib_config.core_opts)
CONF.register_opts(lib_config.neutron_opts, group='neutron_client')
CONF.register_opts(lib_config.keystone_opts, group='keystone_client')
CONF.register_opts(lib_config.binding_opts, 'binding')

CONF.register_opts(kuryr_k8s_opts)
CONF.register_opts(k8s_opts, group='kubernetes')
logging.register_options(CONF)


def init(args, **kwargs):
    version_k8s = pbr_version.VersionInfo('kuryr-kubernetes').version_string()
    CONF(args=args, project='kuryr-k8s', version=version_k8s, **kwargs)


def setup_logging():

    logging.setup(CONF, 'kuryr-kubernetes')
    logging.set_defaults(default_log_levels=logging.get_default_log_levels())
    version_k8s = pbr_version.VersionInfo('kuryr-kubernetes').version_string()
    LOG.info(_LI("Logging enabled!"))
    LOG.info(_LI("%(prog)s version %(version)s"),
             {'prog': sys.argv[0],
              'version': version_k8s})
