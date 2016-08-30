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

from kuryr.lib._i18n import _LI
from oslo_log import log as logging

from kuryr_kubernetes.translators import base

LOG = logging.getLogger(__name__)


class PortTranslator(base.AbstractBaseTranslator):

    def __init__(self):
        super().__init__()

    def get_annotation(self):
        return 'kuryr.kubernetes.org/neutron-port'

    async def on_add(self, event): # flake8: noqa
        LOG.info(_LI('Creating a port'))
        # TODO(devvesa): remove this part ASAP. This statement it only applies
        # when checking that the result is serialized on a real K8s. We don't
        # have any end-to-end test yet, so it allows reviewers to see that
        # works.
        return {'port-created': False}

    async def on_modify(self, event):
        LOG.info(_LI('Modifying a port'))

    async def on_delete(self, event):
        LOG.info(_LI('Deleting a port'))
