#!/bin/bash
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

set -e

DIR=$( cd "$( dirname "$0" )" && pwd )
source "$DIR/../devstack/lib/kuryr_kubernetes"

OUTPUT_DIR=${1:-.}
CONTROLLER_CONF_PATH=${2:-""}
CNI_CONF_PATH=${3:-$CONTROLLER_CONF_PATH}

if [ -z $CONTROLLER_CONF_PATH ]; then
    api_root=${KURYR_K8S_API_ROOT:-https://127.0.0.1:6443}
    auth_url=${KURYR_K8S_AUTH_URL:-http://127.0.0.1/identity}
    username=${KURYR_K8S_USERNAME:-admin}
    password=${KURYR_K8S_PASSWORD:-password}
    user_domain_name=${KURYR_K8S_USER_DOMAIN_NAME:-Default}
    kuryr_project_id=${KURYR_K8S_KURYR_PROJECT_ID}
    project_domain_name=${KURYR_K8S_PROJECT_DOMAIN_NAME:-Default}
    k8s_project_id=${KURYR_K8S_PROJECT_ID}
    pod_subnet_id=${KURYR_K8S_POD_SUBNET_ID}
    pod_sg=${KURYR_K8S_POD_SG}
    service_subnet_id=${KURYR_K8S_SERVICE_SUBNET_ID}
    worker_nodes_subnet=${KURYR_K8S_WORKER_NODES_SUBNET}
    binding_driver=${KURYR_K8S_BINDING_DRIVER:-kuryr.lib.binding.drivers.vlan}
    binding_iface=${KURYR_K8S_BINDING_IFACE:-eth0}

    CONTROLLER_CONF_PATH="${OUTPUT_DIR}/kuryr.conf"
    rm -f $CONTROLLER_CONF_PATH
    cat >> $CONTROLLER_CONF_PATH << EOF
[DEFAULT]
debug = true
[kubernetes]
api_root = $api_root
token_file = /var/run/secrets/kubernetes.io/serviceaccount/token
ssl_ca_crt_file = /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
[neutron]
signing_dir = /var/cache/kuryr
project_domain_name = $project_domain_name
project_id = $kuryr_project_id
user_domain_name = $user_domain_name
username = $username
password = $password
auth_url = $auth_url
auth_type = password
[neutron_defaults]
ovs_bridge = br-int
service_subnet = $service_subnet_id
pod_security_groups = $pod_sg
pod_subnet = $pod_subnet_id
project = $k8s_project_id
EOF

    if [ ! -z $binding_driver ]; then
        cat >> $CONTROLLER_CONF_PATH << EOF
[pod_vif_nested]
worker_nodes_subnet = $worker_nodes_subnet
[binding]
driver = $binding_driver
link_iface = $binding_iface
EOF
    fi
fi

if [ -z $CNI_CONF_PATH ]; then
    CNI_CONF_PATH="${OUTPUT_DIR}/kuryr-cni.conf"
    rm -f $CNI_CONF_PATH
    cat >> $CNI_CONF_PATH << EOF
[DEFAULT]
debug = true
use_stderr = true
[kubernetes]
api_root = $api_root
token_file = /etc/kuryr/token
ssl_ca_crt_file = /etc/kuryr/ca.crt
ssl_verify_server_crt = true
[vif_plug_ovs_privileged]
helper_command=privsep-helper
[vif_plug_linux_bridge_privileged]
helper_command=privsep-helper
EOF

    if [ ! -z $binding_driver ]; then
        cat >> $CNI_CONF_PATH << EOF
[pod_vif_nested]
worker_nodes_subnet = $worker_nodes_subnet
[binding]
driver = $binding_driver
link_iface = $binding_iface
EOF
    fi
fi

generate_kuryr_configmap $OUTPUT_DIR $CONTROLLER_CONF_PATH $CNI_CONF_PATH
generate_kuryr_service_account $OUTPUT_DIR
health_server_port=${KURYR_HEALTH_SERVER_PORT:-8082}
generate_controller_deployment $OUTPUT_DIR $health_server_port
generate_cni_daemon_set $OUTPUT_DIR
