# Copyright (c) 2019 Samsung Electronics Co.,Ltd
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

from oslo_log import log

import grpc

from kuryr_kubernetes.pod_resources import api_pb2
from kuryr_kubernetes.pod_resources import api_pb2_grpc

LOG = log.getLogger(__name__)

POD_RESOURCES_SOCKET = '/pod-resources/kubelet.sock'


class PodResourcesClient(object):

    def __init__(self, kubelet_root_dir):
        socket = 'unix:' + kubelet_root_dir + POD_RESOURCES_SOCKET
        LOG.debug("Creating PodResourcesClient on socket: %s", socket)
        self._channel = grpc.insecure_channel(socket)
        self._stub = api_pb2_grpc.PodResourcesListerStub(self._channel)

    def list(self):
        try:
            response = self._stub.List(api_pb2.ListPodResourcesRequest())
            LOG.debug("PodResourceResponse: %s", response)
            return response
        except grpc.RpcError as e:
            LOG.error("ListPodResourcesRequest failed: %s", e)
            raise
