# Copyright Red Hat, Inc. 2018
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import tempfile

import ddt
from kuryr_kubernetes.cni import utils
from kuryr_kubernetes.tests import base


@ddt.ddt
class TestCNIUtils(base.TestCase):
    @ddt.data(*utils.CONTAINER_RUNTIME_CGROUP_IDS)
    def test_running_under_container_runtime(self, container_runtime_id):
        with tempfile.NamedTemporaryFile() as proc_one_cgroup:
            proc_one_cgroup.write(container_runtime_id.encode())
            proc_one_cgroup.write(b'\n')
            proc_one_cgroup.flush()
            self.assertTrue(
                utils.running_under_container_runtime(proc_one_cgroup.name))

    def test_not_running_under_container_runtime(self):
        with tempfile.NamedTemporaryFile() as proc_one_cgroup:
            self.assertFalse(
                utils.running_under_container_runtime(proc_one_cgroup.name))
