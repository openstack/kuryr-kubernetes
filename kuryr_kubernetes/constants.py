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

KURYR_FQDN = 'kuryr.openstack.org'

K8S_API_BASE = '/api/v1'
K8S_API_PODS = K8S_API_BASE + '/pods'
K8S_API_NAMESPACES = K8S_API_BASE + '/namespaces'
K8S_API_CRD_VERSION = 'openstack.org/v1'
K8S_API_CRD = '/apis/' + K8S_API_CRD_VERSION
K8S_API_CRD_NAMESPACES = K8S_API_CRD + '/namespaces'
K8S_API_CRD_KURYRNETWORKS = K8S_API_CRD + '/kuryrnetworks'
K8S_API_CRD_KURYRNETWORKPOLICIES = K8S_API_CRD + '/kuryrnetworkpolicies'
K8S_API_CRD_KURYRLOADBALANCERS = K8S_API_CRD + '/kuryrloadbalancers'
K8S_API_CRD_KURYRPORTS = K8S_API_CRD + '/kuryrports'
K8S_API_POLICIES = '/apis/networking.k8s.io/v1/networkpolicies'
K8S_API_NETWORKING = '/apis/networking.k8s.io/v1'
K8S_API_NETWORKING_NAMESPACES = K8S_API_NETWORKING + '/namespaces'

K8S_API_NPWG_CRD = '/apis/k8s.cni.cncf.io/v1'

K8S_OBJ_NAMESPACE = 'Namespace'
K8S_OBJ_POD = 'Pod'
K8S_OBJ_SERVICE = 'Service'
K8S_OBJ_ENDPOINTS = 'Endpoints'
K8S_OBJ_POLICY = 'NetworkPolicy'
K8S_OBJ_KURYRNETWORK = 'KuryrNetwork'
K8S_OBJ_KURYRNETWORKPOLICY = 'KuryrNetworkPolicy'
K8S_OBJ_KURYRLOADBALANCER = 'KuryrLoadBalancer'
K8S_OBJ_KURYRPORT = 'KuryrPort'

OPENSHIFT_OBJ_MACHINE = 'Machine'
OPENSHIFT_API_CRD_MACHINES = '/apis/machine.openshift.io/v1beta1/machines'

K8S_POD_STATUS_PENDING = 'Pending'
K8S_POD_STATUS_SUCCEEDED = 'Succeeded'
K8S_POD_STATUS_FAILED = 'Failed'

K8S_ANNOTATION_PREFIX = 'openstack.org/kuryr'
K8S_ANNOTATION_VIF = K8S_ANNOTATION_PREFIX + '-vif'
K8S_ANNOTATION_LABEL = K8S_ANNOTATION_PREFIX + '-pod-label'
K8S_ANNOTATION_IP = K8S_ANNOTATION_PREFIX + '-pod-ip'
K8S_ANNOTATION_NAMESPACE_LABEL = K8S_ANNOTATION_PREFIX + '-namespace-label'
K8S_ANNOTATION_LBAAS_SPEC = K8S_ANNOTATION_PREFIX + '-lbaas-spec'
K8S_ANNOTATION_LBAAS_STATE = K8S_ANNOTATION_PREFIX + '-lbaas-state'
K8S_ANNOTATION_NET_CRD = K8S_ANNOTATION_PREFIX + '-net-crd'
K8S_ANNOTATION_NETPOLICY_CRD = K8S_ANNOTATION_PREFIX + '-netpolicy-crd'
K8S_ANNOTATION_POLICY = K8S_ANNOTATION_PREFIX + '-counter'
K8s_ANNOTATION_PROJECT = K8S_ANNOTATION_PREFIX + '-project'

K8S_ANNOTATION_CLIENT_TIMEOUT = K8S_ANNOTATION_PREFIX + '-timeout-client-data'
K8S_ANNOTATION_MEMBER_TIMEOUT = K8S_ANNOTATION_PREFIX + '-timeout-member-data'

K8S_ANNOTATION_NPWG_PREFIX = 'k8s.v1.cni.cncf.io'
K8S_ANNOTATION_NPWG_NETWORK = K8S_ANNOTATION_NPWG_PREFIX + '/networks'
K8S_ANNOTATION_NPWG_CRD_SUBNET_ID = 'subnetId'
K8S_ANNOTATION_NPWG_CRD_DRIVER_TYPE = 'driverType'

K8S_ANNOTATION_HEADLESS_SERVICE = 'service.kubernetes.io/headless'
K8S_ANNOTATION_CONFIG_SOURCE = 'kubernetes.io/config.source'

POD_FINALIZER = KURYR_FQDN + '/pod-finalizer'
KURYRNETWORK_FINALIZER = 'kuryrnetwork.finalizers.kuryr.openstack.org'
KURYRLB_FINALIZER = 'kuryr.openstack.org/kuryrloadbalancer-finalizers'
SERVICE_FINALIZER = 'kuryr.openstack.org/service-finalizer'
NETWORKPOLICY_FINALIZER = 'kuryr.openstack.org/networkpolicy-finalizer'

KURYRPORT_FINALIZER = KURYR_FQDN + '/kuryrport-finalizer'
KURYRPORT_LABEL = KURYR_FQDN + '/nodeName'

K8S_OS_VIF_NOOP_PLUGIN = "noop"

CNI_EXCEPTION_CODE = 100
CNI_TIMEOUT_CODE = 200
CNI_DELETED_POD_SENTINEL = None

KURYR_PORT_NAME = 'kuryr-pool-port'

OCTAVIA_L2_MEMBER_MODE = "L2"
OCTAVIA_L3_MEMBER_MODE = "L3"
NEUTRON_LBAAS_HAPROXY_PROVIDER = 'haproxy'
IPv4 = 'IPv4'
IPv6 = 'IPv6'
IP_VERSION_4 = 4
IP_VERSION_6 = 6

VIF_POOL_POPULATE = '/populatePool'
VIF_POOL_FREE = '/freePool'
VIF_POOL_LIST = '/listPools'
VIF_POOL_SHOW = '/showPool'

DEFAULT_IFNAME = 'eth0'

K8S_OPERATOR_IN = 'in'
K8S_OPERATOR_NOT_IN = 'notin'
K8S_OPERATOR_DOES_NOT_EXIST = 'doesnotexist'
K8S_OPERATOR_EXISTS = 'exists'

LEFTOVER_RM_POOL_SIZE = 5
