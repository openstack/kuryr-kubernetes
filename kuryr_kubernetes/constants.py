# Copyright (c) 2016 Mirantis, Inc.
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

K8S_API_BASE = '/api/v1'
K8S_API_NAMESPACES = K8S_API_BASE + '/namespaces'

K8S_OBJ_NAMESPACE = 'Namespace'
K8S_OBJ_POD = 'Pod'
K8S_OBJ_SERVICE = 'Service'
K8S_OBJ_ENDPOINTS = 'Endpoints'

K8S_POD_STATUS_PENDING = 'Pending'

K8S_ANNOTATION_PREFIX = 'openstack.org/kuryr'
K8S_ANNOTATION_VIF = K8S_ANNOTATION_PREFIX + '-vif'
K8S_ANNOTATION_LBAAS_SPEC = K8S_ANNOTATION_PREFIX + '-lbaas-spec'
K8S_ANNOTATION_LBAAS_STATE = K8S_ANNOTATION_PREFIX + '-lbaas-state'

K8S_OS_VIF_NOOP_PLUGIN = "noop"

CNI_EXCEPTION_CODE = 100
CNI_TIMEOUT_CODE = 200

KURYR_PORT_NAME = 'kuryr-pool-port'

OCTAVIA_L2_MEMBER_MODE = "L2"
OCTAVIA_L3_MEMBER_MODE = "L3"
