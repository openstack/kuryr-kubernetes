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

import sys
import time

from kuryr.lib._i18n import _LI
from oslo_log import log as logging
from oslo_service import service

from kuryr_kubernetes import config


LOG = logging.getLogger(__name__)


class KuryrK8sService(service.Service):

    def __init__(self):
        super(KuryrK8sService, self).__init__()

    def start(self):
        # TODO(devvesa): Remove this line as soon as it does anything
        LOG.info(_LI("I am doing nothing"))
        try:
            while(True):
                time.sleep(5)
                # TODO(devvesa): Remove this line as soon as does anything
                LOG.info(_LI("Keep doing nothing"))
        finally:
            sys.exit(1)

    def wait(self):
        """Waits for K8sController to complete."""
        super(KuryrK8sService, self).wait()

    def stop(self, graceful=False):
        """Stops the event loop if it's not stopped already."""
        super(KuryrK8sService, self).stop(graceful)


def start():
    config.init(sys.argv[1:])
    config.setup_logging()
    kuryrk8s_launcher = service.launch(config.CONF, KuryrK8sService())
    kuryrk8s_launcher.wait()


if __name__ == '__main__':
    start()
