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
K8S_API_CRD = '/apis/openstack.org/v1'
K8S_API_CRD_NAMESPACES = K8S_API_CRD + '/namespaces'
K8S_API_CRD_KURYRNETS = K8S_API_CRD + '/kuryrnets'
K8S_API_CRD_KURYRNETPOLICIES = K8S_API_CRD + '/kuryrnetpolicies'
K8S_API_POLICIES = '/apis/networking.k8s.io/v1/networkpolicies'

K8S_API_NPWG_CRD = '/apis/k8s.cni.cncf.io/v1'

K8S_OBJ_NAMESPACE = 'Namespace'
K8S_OBJ_POD = 'Pod'
K8S_OBJ_SERVICE = 'Service'
K8S_OBJ_ENDPOINTS = 'Endpoints'
K8S_OBJ_POLICY = 'NetworkPolicy'
K8S_OBJ_KURYRNET = 'KuryrNet'
K8S_OBJ_KURYRNETPOLICY = 'KuryrNetPolicy'

K8S_POD_STATUS_PENDING = 'Pending'

K8S_ANNOTATION_PREFIX = 'openstack.org/kuryr'
K8S_ANNOTATION_VIF = K8S_ANNOTATION_PREFIX + '-vif'
K8S_ANNOTATION_LABEL = K8S_ANNOTATION_PREFIX + '-pod-label'
K8S_ANNOTATION_NAMESPACE_LABEL = K8S_ANNOTATION_PREFIX + '-namespace-label'
K8S_ANNOTATION_LBAAS_SPEC = K8S_ANNOTATION_PREFIX + '-lbaas-spec'
K8S_ANNOTATION_LBAAS_STATE = K8S_ANNOTATION_PREFIX + '-lbaas-state'
K8S_ANNOTATION_NET_CRD = K8S_ANNOTATION_PREFIX + '-net-crd'
K8S_ANNOTATION_NETPOLICY_CRD = K8S_ANNOTATION_PREFIX + '-netpolicy-crd'
K8S_ANNOTATION_LBAAS_RT_STATE = K8S_ANNOTATION_PREFIX + '-lbaas-route-state'
K8S_ANNOTATION_LBAAS_RT_NOTIF = K8S_ANNOTATION_PREFIX + '-lbaas-route-notif'
K8S_ANNOTATION_ROUTE_STATE = K8S_ANNOTATION_PREFIX + '-route-state'
K8S_ANNOTATION_ROUTE_SPEC = K8S_ANNOTATION_PREFIX + '-route-spec'

K8S_ANNOTATION_NPWG_PREFIX = 'k8s.v1.cni.cncf.io'
K8S_ANNOTATION_NPWG_NETWORK = K8S_ANNOTATION_NPWG_PREFIX + '/networks'
K8S_ANNOTATION_NPWG_CRD_SUBNET_ID = 'subnetId'
K8S_ANNOTATION_NPWG_CRD_DRIVER_TYPE = 'driverType'

K8S_ANNOTATION_NODE_PCI_DEVICE_INFO = 'openstack.org/kuryr-pci-info'
K8S_ANNOTATION_PCI_DEVICES = K8S_ANNOTATION_PREFIX + '-pci-devices'
K8S_ANNOTATION_OLD_DRIVER = 'old_driver'
K8S_ANNOTATION_CURRENT_DRIVER = 'current_driver'
K8S_ANNOTATION_NEUTRON_PORT = 'neutron_id'

K8S_OS_VIF_NOOP_PLUGIN = "noop"

CNI_EXCEPTION_CODE = 100
CNI_TIMEOUT_CODE = 200

KURYR_PORT_NAME = 'kuryr-pool-port'
KURYR_L7_ROUTER_HTTP_PORT = '80'
KURYR_VIF_TYPE_SRIOV = 'sriov'

OCTAVIA_L2_MEMBER_MODE = "L2"
OCTAVIA_L3_MEMBER_MODE = "L3"
NEUTRON_LBAAS_HAPROXY_PROVIDER = 'haproxy'

VIF_POOL_POPULATE = '/populatePool'
VIF_POOL_FREE = '/freePool'
VIF_POOL_LIST = '/listPools'
VIF_POOL_SHOW = '/showPool'

DEFAULT_IFNAME = 'eth0'

ADDITIONAL_IFNAME_PREFIX = 'eth'
K8S_SRIOV_PREFIX = 'intel.com'

K8S_OPERATOR_IN = 'in'
K8S_OPERATOR_NOT_IN = 'notin'
K8S_OPERATOR_DOES_NOT_EXIST = 'doesnotexist'
K8S_OPERATOR_EXISTS = 'exists'

USERSPACE_DRIVERS = ['vfio-pci', 'uio', 'uio_pci_generic', 'igb_uio']
