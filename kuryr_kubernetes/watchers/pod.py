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

from kuryr_kubernetes.watchers import base

LOG = logging.getLogger(__name__)


class PodWatcher(base.AbstractBaseWatcher):

    ENDPOINT = "/api/v1/pods"

    def __init__(self, event_loop):
        super().__init__(event_loop)

    def get_api_endpoint(self):
        return self.ENDPOINT

    async def on_add(self, event): # flake8: noqa
        LOG.info(_LI('Received an ADDED event on a Pod'))

    async def on_modify(self, event):
        LOG.info(_LI('Received a MODIFIED event on a Pod'))

    async def on_delete(self, event):
        LOG.info(_LI('Received a DELETED event on a Pod'))
