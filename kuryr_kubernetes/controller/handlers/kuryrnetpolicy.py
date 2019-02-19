# Copyright 2019 Red Hat, Inc.
#
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

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.handlers import k8s_base


class KuryrNetPolicyHandler(k8s_base.ResourceEventHandler):
    """Controller side of KuryrNetPolicy process for Kubernetes pods.

    `KuryrNetPolicyHandler` runs on the Kuryr-Kubernetes controller and is
    responsible for deleting associated security groups upon namespace
    deletion.
    """
    OBJECT_KIND = constants.K8S_OBJ_KURYRNETPOLICY
    OBJECT_WATCH_PATH = constants.K8S_API_CRD_KURYRNETPOLICIES

    def __init__(self):
        super(KuryrNetPolicyHandler, self).__init__()
        self._drv_policy = drivers.NetworkPolicyDriver.get_instance()

    def on_deleted(self, netpolicy_crd):
        crd_sg = netpolicy_crd['spec'].get('securityGroupId')
        if crd_sg:
            self._drv_policy.delete_np_sg(crd_sg)
