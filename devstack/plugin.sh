#!/bin/bash
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

# Save trace setting
XTRACE=$(set +o | grep xtrace)
set -o xtrace

function container_runtime {
    # Ignore error at killing/removing a container doesn't running to avoid
    # unstack is terminated.
    # TODO: Support for CRI-O if it's required.
    local regex_cmds_ignore="(kill|rm)\s+"

    if [[ ${CONTAINER_ENGINE} == 'crio' ]]; then
        sudo podman "$@" || die $LINENO "Error when running podman command"
    else
        if [[ $@ =~ $regex_cmds_ignore ]]; then
            docker "$@"
        else
            docker "$@" || die $LINENO "Error when running docker command"
        fi
    fi
}

function create_kuryr_account {
    if is_service_enabled kuryr-kubernetes; then
        create_service_user "kuryr" "admin"
        get_or_create_service "kuryr-kubernetes" "kuryr-kubernetes" \
        "Kuryr-Kubernetes Service"
    fi
}

function create_kuryr_cache_dir {
    # Create cache directory
    sudo install -d -o "$STACK_USER" "$KURYR_AUTH_CACHE_DIR"
    if [[ ! "$KURYR_AUTH_CACHE_DIR" == "" ]]; then
        rm -f "$KURYR_AUTH_CACHE_DIR"/*
    fi
}

function create_kuryr_lock_dir {
    # Create lock directory
    sudo install -d -o "$STACK_USER" "$KURYR_LOCK_DIR"
}

function configure_kuryr {
    local dir
    sudo install -d -o "$STACK_USER" "$KURYR_CONFIG_DIR"
    "${KURYR_HOME}/tools/generate_config_file_samples.sh"
    sudo install -o "$STACK_USER" -m 640 -D "${KURYR_HOME}/etc/kuryr.conf.sample" \
        "$KURYR_CONFIG"

    if [ "$KURYR_K8S_API_CERT" ]; then
        iniset "$KURYR_CONFIG" kubernetes ssl_client_crt_file "$KURYR_K8S_API_CERT"
    fi
    if [ "$KURYR_K8S_API_KEY" ]; then
        iniset "$KURYR_CONFIG" kubernetes ssl_client_key_file "$KURYR_K8S_API_KEY"
    fi
    if [ "$KURYR_K8S_API_CACERT" ]; then
        iniset "$KURYR_CONFIG" kubernetes ssl_ca_crt_file "$KURYR_K8S_API_CACERT"
        iniset "$KURYR_CONFIG" kubernetes ssl_verify_server_crt True
    fi
    if [ "$KURYR_MULTI_VIF_DRIVER" ]; then
        iniset "$KURYR_CONFIG" kubernetes multi_vif_drivers "$KURYR_MULTI_VIF_DRIVER"
    fi
    # REVISIT(ivc): 'use_stderr' is required for current CNI driver. Once a
    # daemon-based CNI driver is implemented, this could be removed.
    iniset "$KURYR_CONFIG" DEFAULT use_stderr true

    iniset "$KURYR_CONFIG" DEFAULT debug "$ENABLE_DEBUG_LOG_LEVEL"

    iniset "$KURYR_CONFIG" kubernetes port_debug "$KURYR_PORT_DEBUG"

    iniset "$KURYR_CONFIG" kubernetes pod_subnets_driver "$KURYR_SUBNET_DRIVER"
    iniset "$KURYR_CONFIG" kubernetes pod_security_groups_driver "$KURYR_SG_DRIVER"
    iniset "$KURYR_CONFIG" kubernetes service_security_groups_driver "$KURYR_SG_DRIVER"
    iniset "$KURYR_CONFIG" kubernetes enabled_handlers "$KURYR_ENABLED_HANDLERS"

    # Let Kuryr retry connections to K8s API for 20 minutes.
    iniset "$KURYR_CONFIG" kubernetes watch_retry_timeout 1200

    KURYR_K8S_CONTAINERIZED_DEPLOYMENT=$(trueorfalse False KURYR_K8S_CONTAINERIZED_DEPLOYMENT)
    if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]; then
        # This works around the issue of being unable to set oslo.privsep mode
        # to FORK in os-vif. When running in a container we disable `sudo` that
        # was prefixed before `privsep-helper` command. This let's us run in
        # envs without sudo and keep the same python environment as the parent
        # process.
        iniset "$KURYR_CONFIG" vif_plug_ovs_privileged helper_command privsep-helper
        iniset "$KURYR_CONFIG" vif_plug_linux_bridge_privileged helper_command privsep-helper

        # When running kuryr-daemon or CNI in container we need to set up
        # some configs.
        iniset "$KURYR_CONFIG" cni_daemon docker_mode True
        iniset "$KURYR_CONFIG" cni_daemon netns_proc_dir "/host_proc"
    fi

    if is_service_enabled kuryr-daemon; then
        iniset "$KURYR_CONFIG" oslo_concurrency lock_path "$KURYR_LOCK_DIR"
        create_kuryr_lock_dir
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "False" ]; then
            iniset "$KURYR_CONFIG" cni_health_server cg_path \
                "/system.slice/system-devstack.slice/devstack@kuryr-daemon.service"
        fi
    fi

    create_kuryr_cache_dir

    # Neutron API server & Neutron plugin
    if is_service_enabled kuryr-kubernetes; then
        configure_auth_token_middleware "$KURYR_CONFIG" kuryr \
        "$KURYR_AUTH_CACHE_DIR" neutron
        iniset "$KURYR_CONFIG" kubernetes pod_vif_driver "$KURYR_POD_VIF_DRIVER"
        if [ "$KURYR_USE_PORTS_POOLS" ]; then
            iniset "$KURYR_CONFIG" kubernetes vif_pool_driver "$KURYR_VIF_POOL_DRIVER"
            iniset "$KURYR_CONFIG" vif_pool ports_pool_min "$KURYR_VIF_POOL_MIN"
            iniset "$KURYR_CONFIG" vif_pool ports_pool_max "$KURYR_VIF_POOL_MAX"
            iniset "$KURYR_CONFIG" vif_pool ports_pool_batch "$KURYR_VIF_POOL_BATCH"
            iniset "$KURYR_CONFIG" vif_pool ports_pool_update_frequency "$KURYR_VIF_POOL_UPDATE_FREQ"
            if [ "$KURYR_VIF_POOL_MANAGER" ]; then
                iniset "$KURYR_CONFIG" kubernetes enable_manager "$KURYR_VIF_POOL_MANAGER"

                dir=`iniget "$KURYR_CONFIG" vif_pool manager_sock_file`
                if [[ -z $dir ]]; then
                    dir="/run/kuryr/kuryr_manage.sock"
                fi
                dir=`dirname $dir`
                sudo mkdir -p $dir
            fi
        fi
    fi
}

function generate_containerized_kuryr_resources {
    if [[ $KURYR_CONTROLLER_REPLICAS -eq 1 ]]; then
        KURYR_CONTROLLER_HA="False"
    else
        KURYR_CONTROLLER_HA="True"
    fi

    # Containerized deployment will use tokens provided by k8s itself.
    inicomment "$KURYR_CONFIG" kubernetes ssl_client_crt_file
    inicomment "$KURYR_CONFIG" kubernetes ssl_client_key_file

    iniset "$KURYR_CONFIG" kubernetes controller_ha ${KURYR_CONTROLLER_HA}
    iniset "$KURYR_CONFIG" kubernetes controller_ha_port ${KURYR_CONTROLLER_HA_PORT}

    # NOTE(dulek): In the container the CA bundle will be mounted in a standard
    # directory
    iniset "$KURYR_CONFIG" neutron cafile /etc/ssl/certs/kuryr-ca-bundle.crt

    # Generate kuryr resources in k8s formats.
    local output_dir="${DATA_DIR}/kuryr-kubernetes"
    generate_kuryr_configmap $output_dir $KURYR_CONFIG
    generate_kuryr_certificates_secret $output_dir $SSL_BUNDLE_FILE
    generate_kuryr_service_account $output_dir
    generate_controller_deployment $output_dir $KURYR_HEALTH_SERVER_PORT $KURYR_CONTROLLER_HA
    generate_cni_daemon_set $output_dir $KURYR_CNI_HEALTH_SERVER_PORT $cni_daemon $CNI_BIN_DIR $CNI_CONF_DIR
}

function run_containerized_kuryr_resources {
    local k8s_data_dir="${DATA_DIR}/kuryr-kubernetes"
    /usr/local/bin/kubectl create -f \
        "${k8s_data_dir}/config_map.yml" \
        || die $LINENO "Failed to create kuryr-kubernetes ConfigMap."
    /usr/local/bin/kubectl create -f \
        "${k8s_data_dir}/certificates_secret.yml" \
        || die $LINENO "Failed to create kuryr-kubernetes certificates Secret."
    /usr/local/bin/kubectl create -f \
        "${k8s_data_dir}/controller_service_account.yml" \
        || die $LINENO "Failed to create kuryr-controller ServiceAccount."
    /usr/local/bin/kubectl create -f \
        "${k8s_data_dir}/cni_service_account.yml" \
        || die $LINENO "Failed to create kuryr-cni ServiceAccount."

    if is_service_enabled openshift-master; then
        # NOTE(dulek): For OpenShift add privileged SCC to serviceaccount.
        /usr/local/bin/oc adm policy add-scc-to-user privileged -n kube-system -z kuryr-controller
    fi
    /usr/local/bin/kubectl create -f \
        "${k8s_data_dir}/controller_deployment.yml" \
        || die $LINENO "Failed to create kuryr-kubernetes Deployment."
    /usr/local/bin/kubectl create -f \
        "${k8s_data_dir}/cni_ds.yml" \
        || die $LINENO "Failed to create kuryr-kubernetes CNI DaemonSet."
}

function install_kuryr_cni {
    local kuryr_cni_bin=$(which kuryr-cni)
    sudo install -o "$STACK_USER" -m 0555 -D \
        "$kuryr_cni_bin" "${CNI_BIN_DIR}/kuryr-cni"
}

function _cidr_range {
  python3 - <<EOF "$1"
import sys
from netaddr import IPAddress, IPNetwork
n = IPNetwork(sys.argv[1])
print("%s\\t%s\\t%s" % (IPAddress(n.first + 1), IPAddress(n.first + 2), IPAddress(n.last - 1)))
EOF
}

function copy_tempest_kubeconfig {
    local tempest_home

    tempest_home='/home/tempest'
    if is_service_enabled openshift-master; then
        sudo mkdir -p "${HOME}/.kube"
        sudo cp "${OPENSHIFT_DATA_DIR}/master/admin.kubeconfig" "${HOME}/.kube/config"
        sudo chown -R $STACK_USER "${HOME}/.kube"
    fi

    if [ -d "$tempest_home" ]; then
        sudo cp -r "${HOME}/.kube" "$tempest_home"
        sudo chown -R tempest "${tempest_home}/.kube"
    fi
}

function create_k8s_api_service {
    # This allows pods that need access to kubernetes API (like the
    # containerized kuryr controller or kube-dns) to talk to the K8s API
    # service
    local service_cidr
    local kubelet_iface_ip
    local lb_name
    local use_octavia
    local project_id
    local fixed_ips

    project_id=$(get_or_create_project \
        "$KURYR_NEUTRON_DEFAULT_PROJECT" default)
    lb_name='default/kubernetes'
    # TODO(dulek): We only look at the first service subnet because kubernetes
    #              API service is only IPv4 in 1.20. It might be dual stack
    #              in the future.
    service_cidr=$(openstack --os-cloud devstack-admin \
                             --os-region "$REGION_NAME" \
                             subnet show "${KURYR_SERVICE_SUBNETS_IDS[0]}" \
                             -c cidr -f value)

    fixed_ips=$(openstack port show kubelet-"${HOSTNAME}" -c fixed_ips -f value)
    kubelet_iface_ip=$(python3 -c "print(${fixed_ips}[0]['ip_address'])")

    k8s_api_clusterip=$(_cidr_range "$service_cidr" | cut -f1)

    create_load_balancer "$lb_name" "${KURYR_SERVICE_SUBNETS_IDS[0]}" \
            "$project_id" "$k8s_api_clusterip"
    create_load_balancer_listener default/kubernetes:${KURYR_K8S_API_LB_PORT} HTTPS ${KURYR_K8S_API_LB_PORT} "$lb_name" "$project_id" 3600000
    create_load_balancer_pool default/kubernetes:${KURYR_K8S_API_LB_PORT} HTTPS ROUND_ROBIN \
        default/kubernetes:${KURYR_K8S_API_LB_PORT} "$project_id" "$lb_name"

    local api_port
    if is_service_enabled openshift-master; then
        api_port=${OPENSHIFT_API_PORT}
    else
        api_port=6443
    fi

    local address
    KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE=$(trueorfalse True KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE)
    if [[ "$KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE" == "True" ]]; then
        address=${kubelet_iface_ip}
    else
        address="${HOST_IP}"
    fi

    # Regardless of the octavia mode, the k8s API will be behind an L3 mode
    # amphora driver loadbalancer
    create_load_balancer_member "$(hostname)" "$address" "$api_port" \
        default/kubernetes:${KURYR_K8S_API_LB_PORT} ${KURYR_NEUTRON_DEFAULT_EXT_SVC_SUBNET} "$lb_name" "$project_id"
}

function configure_neutron_defaults {
    local project_id
    local sg_ids
    local router
    local router_id
    local ext_svc_net_id
    local addrs_prefix
    local subnetpool_name

    project_id=$(get_or_create_project \
        "$KURYR_NEUTRON_DEFAULT_PROJECT" default)
    ext_svc_net_id="$(openstack network show -c id -f value \
        "${KURYR_NEUTRON_DEFAULT_EXT_SVC_NET}")"

    # If a subnetpool is not passed, we get the one created in devstack's
    # Neutron module
    KURYR_IPV6=$(trueorfalse False KURYR_IPV6)
    KURYR_DUAL_STACK=$(trueorfalse False KURYR_DUAL_STACK)

    export KURYR_SUBNETPOOLS_IDS=()
    export KURYR_ETHERTYPES=()
    if [[ "$KURYR_IPV6" == "False" || "$KURYR_DUAL_STACK" == "True" ]]; then
        export KURYR_ETHERTYPE=IPv4
        KURYR_ETHERTYPES+=("IPv4")
        KURYR_SUBNETPOOLS_IDS+=(${KURYR_NEUTRON_DEFAULT_SUBNETPOOL_ID:-${SUBNETPOOL_V4_ID}})
    fi
    if [[ "$KURYR_IPV6" == "True" || "$KURYR_DUAL_STACK" == "True" ]]; then
        export KURYR_ETHERTYPE=IPv6
        KURYR_ETHERTYPES+=("IPv6")
        # NOTE(gryf): To not clash with subnets created by DevStack for IPv6,
        # we create another subnetpool just for kuryr subnets.
        # SUBNETPOOL_KURYR_V6_ID will be used in function configure_kuryr in
        # case of namespace kuryr subnet driver.
        # This is not required for IPv4, because DevStack is only adding a
        # conflicting route for IPv6. On DevStack this route is opening public
        # IPv6 network to be accessible from host, which doesn't have place in
        # IPv4 net, because floating IPs are used instead.
        IPV6_ID=$(uuidgen | sed s/-//g | cut -c 23- | \
            sed -e "s/\(..\)\(....\)\(....\)/\1:\2:\3/")
        addrs_prefix="fd${IPV6_ID}::/56"
        subnetpool_name=${SUBNETPOOL_KURYR_NAME_V6}
        KURYR_SUBNETPOOLS_IDS+=($(openstack \
            --os-cloud devstack-admin \
            --os-region "${REGION_NAME}" \
            subnet pool create "${subnetpool_name}" \
            --default-prefix-length "${SUBNETPOOL_SIZE_V6}" \
            --pool-prefix "${addrs_prefix}" \
            --share -f value -c id))
    fi

    router=${KURYR_NEUTRON_DEFAULT_ROUTER:-$Q_ROUTER_NAME}
    if [ "$router" != "$Q_ROUTER_NAME" ]; then
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            router create --project "$project_id" "$router"
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            router set --external-gateway "$ext_svc_net_id" "$router"
    fi
    router_id="$(openstack router show -c id -f value "$router")"

    pod_net_id=$(openstack --os-cloud devstack-admin \
                       --os-region "$REGION_NAME" \
                       network create --project "$project_id" \
                       "$KURYR_NEUTRON_DEFAULT_POD_NET" \
                       -c id -f value)
    service_net_id=$(openstack --os-cloud devstack-admin \
                       --os-region "$REGION_NAME" \
                       network create --project "$project_id" \
                       "$KURYR_NEUTRON_DEFAULT_SERVICE_NET" \
                       -c id -f value)

    export KURYR_POD_SUBNETS_IDS=()
    export KURYR_SERVICE_SUBNETS_IDS=()
    for i in "${!KURYR_SUBNETPOOLS_IDS[@]}"; do
        KURYR_POD_SUBNETS_IDS+=($(create_k8s_subnet "$project_id" \
                          "$pod_net_id" \
                          "${KURYR_NEUTRON_DEFAULT_POD_SUBNET}-${KURYR_ETHERTYPES[$i]}" \
                          "${KURYR_SUBNETPOOLS_IDS[$i]}" \
                          "$router" "False" ${KURYR_ETHERTYPES[$i]}))

        KURYR_SERVICE_SUBNETS_IDS+=($(create_k8s_subnet "$project_id" \
                          "$service_net_id" \
                          "${KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET}-${KURYR_ETHERTYPES[$i]}" \
                          "${KURYR_SUBNETPOOLS_IDS[$i]}" \
                          "$router" "True" ${KURYR_ETHERTYPES[$i]}))
    done

    sg_ids=()
    if [[ "$KURYR_SG_DRIVER" == "default" ]]; then
        sg_ids+=($(echo $(openstack security group list \
            --project "$project_id" -c ID -f value) | tr ' ' ','))
    fi

    # In order for the ports to allow service traffic under Octavia L3 mode,
    # it is necessary for the service subnet to be allowed into the port's
    # security groups. If L3 is used, then the pods created will include it.
    # Otherwise it will be just used by the kubelet port used for the K8s API
    # load balancer
    local service_pod_access_sg_id
    service_pod_access_sg_id=$(openstack --os-cloud devstack-admin \
        --os-region "$REGION_NAME" \
        security group create --project "$project_id" \
        service_pod_access -f value -c id)

    for i in "${!KURYR_SERVICE_SUBNETS_IDS[@]}"; do
        local service_cidr
        service_cidr=$(openstack --os-cloud devstack-admin \
            --os-region "$REGION_NAME" subnet show \
            "${KURYR_SERVICE_SUBNETS_IDS[$i]}" -f value -c cidr)
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            security group rule create --project "$project_id" \
            --description "k8s service subnet allowed" \
            --remote-ip "$service_cidr" --ethertype "${KURYR_ETHERTYPES[$i]}" --protocol tcp \
            "$service_pod_access_sg_id"
        # Since Octavia supports also UDP load balancing, we need to allow
        # also udp traffic
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            security group rule create --project "$project_id" \
            --description "k8s service subnet UDP allowed" \
            --remote-ip "$service_cidr" --ethertype "${KURYR_ETHERTYPES[$i]}" --protocol udp \
            "$service_pod_access_sg_id"
        # Octavia supports SCTP load balancing, we need to also allow SCTP traffic
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            security group rule create --project "$project_id" \
            --description "k8s service subnet SCTP allowed" \
            --remote-ip "$service_cidr" --ethertype "${KURYR_ETHERTYPES[$i]}" --protocol sctp \
            "$service_pod_access_sg_id"
    done

    if [[ "$KURYR_K8S_OCTAVIA_MEMBER_MODE" == "L3" ]]; then
        sg_ids+=(${service_pod_access_sg_id})
    elif [[ "$KURYR_K8S_OCTAVIA_MEMBER_MODE" == "L2" ]]; then
        # In case the member connectivity is L2, Octavia by default uses the
        # admin 'default' sg to create a port for the amphora load balancer
        # at the member ports subnet. Thus we need to allow L2 communication
        # between the member ports and the octavia ports by allowing all
        # access from the pod subnet range to the ports in that subnet, and
        # include it into $sg_ids
        local octavia_pod_access_sg_id
        octavia_pod_access_sg_id=$(openstack --os-cloud devstack-admin \
            --os-region "$REGION_NAME" \
            security group create --project "$project_id" \
            octavia_pod_access -f value -c id)
        for i in "${!KURYR_POD_SUBNETS_IDS[@]}"; do
            local pod_cidr
            pod_cidr=$(openstack --os-cloud devstack-admin \
                --os-region "$REGION_NAME" subnet show \
                "${KURYR_POD_SUBNETS_IDS[$i]}" -f value -c cidr)
            openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
                security group rule create --project "$project_id" \
                --description "k8s pod subnet allowed from k8s-pod-subnet" \
                --remote-ip "$pod_cidr" --ethertype "${KURYR_ETHERTYPES[$i]}" --protocol tcp \
                "$octavia_pod_access_sg_id"
            # Since Octavia supports also UDP load balancing, we need to allow
            # also udp traffic
            openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
                security group rule create --project "$project_id" \
                --description "k8s pod subnet allowed from k8s-pod-subnet" \
                --remote-ip "$pod_cidr" --ethertype "${KURYR_ETHERTYPES[$i]}" --protocol udp \
                "$octavia_pod_access_sg_id"
            # Octavia supports SCTP load balancing, we need to also support SCTP traffic
            openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
                security group rule create --project "$project_id" \
                --description "k8s pod subnet allowed from k8s-pod-subnet" \
                --remote-ip "$pod_cidr" --ethertype "${KURYR_ETHERTYPES[$i]}" --protocol sctp \
                "$octavia_pod_access_sg_id"
        done
        sg_ids+=(${octavia_pod_access_sg_id})
    fi

    iniset "$KURYR_CONFIG" neutron_defaults project "$project_id"
    iniset "$KURYR_CONFIG" neutron_defaults pod_subnet "${KURYR_POD_SUBNETS_IDS[0]}"
    iniset "$KURYR_CONFIG" neutron_defaults pod_subnets $(IFS=, ; echo "${KURYR_POD_SUBNETS_IDS[*]}")
    iniset "$KURYR_CONFIG" neutron_defaults service_subnet "${KURYR_SERVICE_SUBNETS_IDS[0]}"
    iniset "$KURYR_CONFIG" neutron_defaults service_subnets $(IFS=, ; echo "${KURYR_SERVICE_SUBNETS_IDS[*]}")
    if [ "$KURYR_SUBNET_DRIVER" == "namespace" ]; then
        iniset "$KURYR_CONFIG" namespace_subnet pod_subnet_pool "${KURYR_SUBNETPOOLS_IDS[0]}"
        iniset "$KURYR_CONFIG" namespace_subnet pod_subnet_pools $(IFS=, ; echo "${KURYR_SUBNETPOOLS_IDS[*]}")
        iniset "$KURYR_CONFIG" namespace_subnet pod_router "$router_id"
    fi
    if [[ "$KURYR_SG_DRIVER" == "policy" ]]; then
        # NOTE(dulek): Using the default DevStack's SG is not enough to match
        # the NP specification. We need to open ingress to everywhere, so we
        # create allow-all group.
        allow_all_sg_id=$(openstack --os-cloud devstack-admin \
            --os-region "$REGION_NAME" \
            security group create --project "$project_id" \
            allow-all -f value -c id)
        for ethertype in ${KURYR_ETHERTYPES[@]}; do
            openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
              security group rule create --project "$project_id" \
              --description "allow all ingress traffic" \
              --ethertype "$ethertype" --ingress --protocol any \
              "$allow_all_sg_id"
        done
        sg_ids+=(${allow_all_sg_id})
    fi
    iniset "$KURYR_CONFIG" neutron_defaults pod_security_groups $(IFS=, ; echo "${sg_ids[*]}")

    if [[ "$KURYR_SG_DRIVER" == "policy" ]]; then
        # NOTE(ltomasbo): As more security groups and rules are created, there
        # is a need to increase the quota for it
         openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
             quota set --secgroups 100 --secgroup-rules 300 "$project_id"
    fi

    # NOTE(dulek): DevStack's admin default for SG's and instances is 10, this
    #              is too little for our tests with Octavia configured to use
    #              amphora.
    openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
        quota set --secgroups 100 --secgroup-rules 300 --instances 100 admin

    if [ -n "$OVS_BRIDGE" ]; then
        iniset "$KURYR_CONFIG" neutron_defaults ovs_bridge "$OVS_BRIDGE"
    fi
    iniset "$KURYR_CONFIG" neutron_defaults external_svc_net "$ext_svc_net_id"
    iniset "$KURYR_CONFIG" octavia_defaults member_mode "$KURYR_K8S_OCTAVIA_MEMBER_MODE"
    iniset "$KURYR_CONFIG" octavia_defaults enforce_sg_rules "$KURYR_ENFORCE_SG_RULES"
    iniset "$KURYR_CONFIG" octavia_defaults lb_algorithm "$KURYR_LB_ALGORITHM"
    # Octavia takes a very long time to start the LB in the gate. We need
    # to tweak the timeout for the LB creation. Let's be generous and give
    # it up to 20 minutes.
    # FIXME(dulek): This might be removed when bug 1753653 is fixed and
    #               Kuryr restarts waiting for LB on timeouts.
    iniset "$KURYR_CONFIG" neutron_defaults lbaas_activation_timeout 1200
    iniset "$KURYR_CONFIG" kubernetes endpoints_driver_octavia_provider "$KURYR_EP_DRIVER_OCTAVIA_PROVIDER"
}

function configure_k8s_pod_sg_rules {
    local project_id
    local sg_id

    project_id=$(get_or_create_project \
        "$KURYR_NEUTRON_DEFAULT_PROJECT" default)
    sg_id=$(openstack --os-cloud devstack-admin \
                      --os-region "$REGION_NAME" \
                      security group list \
                      --project "$project_id" -c ID -c Name -f value | \
                      awk '{if ($2=="default") print $1}')
    create_k8s_icmp_sg_rules "$sg_id" ingress
}

function create_token() {
  echo $(cat /dev/urandom | base64 | tr -d "=+/" | dd bs=32 count=1 2> /dev/null)
}

function prepare_kubernetes_files {
    # Sets up the base configuration for the Kubernetes API Server and the
    # Controller Manager.
    local service_cidr
    local k8s_api_clusterip

    service_cidr=$(openstack --os-cloud devstack-admin \
                             --os-region "$REGION_NAME" \
                             subnet show "${KURYR_SERVICE_SUBNETS_IDS[0]}"\
                             -c cidr -f value)
    k8s_api_clusterip=$(_cidr_range "$service_cidr" | cut -f1)

    # It's not prettiest, but the file haven't changed since 1.6, so it's safe to download it like that.
    curl -o /tmp/make-ca-cert.sh https://raw.githubusercontent.com/kubernetes/kubernetes/release-1.8/cluster/saltbase/salt/generate-cert/make-ca-cert.sh
    chmod +x /tmp/make-ca-cert.sh

    # Create HTTPS certificates
    sudo groupadd -f -r kube-cert

    # hostname -I gets the ip of the node
    sudo CERT_DIR=${KURYR_KUBERNETES_DATA_DIR} /tmp/make-ca-cert.sh $(hostname -I | awk '{print $1}') "IP:${HOST_IP},IP:${k8s_api_clusterip},DNS:kubernetes,DNS:kubernetes.default,DNS:kubernetes.default.svc,DNS:kubernetes.default.svc.cluster.local"

    # Create basic token authorization
    sudo bash -c "echo 'admin,admin,admin' > $KURYR_KUBERNETES_DATA_DIR/token_auth.csv"

    # Create known tokens for service accounts
    sudo bash -c "echo '$(create_token),admin,admin' >> ${KURYR_KUBERNETES_DATA_DIR}/known_tokens.csv"
    sudo bash -c "echo '$(create_token),kubelet,kubelet' >> ${KURYR_KUBERNETES_DATA_DIR}/known_tokens.csv"
    sudo bash -c "echo '$(create_token),kube_proxy,kube_proxy' >> ${KURYR_KUBERNETES_DATA_DIR}/known_tokens.csv"

    # Copy certs for Kuryr services to use
    sudo install -m 644 "${KURYR_KUBERNETES_DATA_DIR}/kubecfg.crt" "${KURYR_KUBERNETES_DATA_DIR}/kuryr.crt"
    sudo install -m 644 "${KURYR_KUBERNETES_DATA_DIR}/kubecfg.key" "${KURYR_KUBERNETES_DATA_DIR}/kuryr.key"
    sudo install -m 644 "${KURYR_KUBERNETES_DATA_DIR}/ca.crt" "${KURYR_KUBERNETES_DATA_DIR}/kuryr-ca.crt"

    # FIXME(ivc): replace 'sleep' with a strict check (e.g. wait_for_files)
    # 'kubernetes-api' fails if started before files are generated.
    # this is a workaround to prevent races.
    sleep 5
}

function wait_for {
    local name
    local url
    local cacert_path
    local flags
    name="$1"
    url="$2"
    cacert_path=${3:-}
    timeout=${4:-$KURYR_WAIT_TIMEOUT}

    echo -n "Waiting for $name to respond"

    extra_flags=${cacert_path:+"--cacert ${cacert_path}"}

    local start_time=$(date +%s)
    until curl -o /dev/null -s $extra_flags "$url"; do
        echo -n "."
        local curr_time=$(date +%s)
        local time_diff=$(($curr_time - $start_time))
        [[ $time_diff -le $timeout ]] || die "Timed out waiting for $name"
        sleep 1
    done
    echo ""
}

function wait_for_ok_health {
    local name
    local url
    local cacert_path
    local start_time
    local key_path
    local cert_path
    local curr_time
    local time_diff
    name="$1"
    url="$2"
    cacert_path=${3:-}
    key_path=${4:-}
    cert_path=${5:-}
    timeout=${6:-$KURYR_WAIT_TIMEOUT}


    extra_flags=('-s' ${cacert_path:+--cacert "$cacert_path"} ${key_path:+--key "$key_path"} ${cert_path:+--cert "$cert_path"})

    start_time=$(date +%s)
    echo -n "Waiting for $name to be healthy"
    until [[ "$(curl "${extra_flags[@]}" "$url")" == "ok" ]]; do
        echo -n "."
        curr_time=$(date +%s)
        time_diff=$((curr_time - start_time))
        [[ $time_diff -le $timeout ]] || die "Timed out waiting for $name"
        sleep 1
    done
    echo ""
}

function get_k8s_log_level {
  if [[ ${ENABLE_DEBUG_LOG_LEVEL} == "True" ]]; then
    echo "4"
  else
    echo "2"
  fi
}

function setup_k8s_binaries() {
    tmp_path=$1
    binary_name=$2
    binary_path=$3

    curl -o "${tmp_path}" "${KURYR_KUBERNETES_BINARIES}/${binary_name}"
    sudo install -o "$STACK_USER" -m 0555 -D "${tmp_path}" "${binary_path}"
}

function run_k8s_api {
    local service_cidr
    local cluster_ip_ranges
    local command
    local tmp_kube_apiserver_path="/tmp/kube-apiserver"
    local binary_name="kube-apiserver"

    setup_k8s_binaries $tmp_kube_apiserver_path $binary_name $KURYR_KUBE_APISERVER_BINARY

    # Runs Hyperkube's Kubernetes API Server
    wait_for "etcd" "http://${SERVICE_HOST}:${ETCD_PORT}/v2/machines"

    cluster_ip_ranges=()
    for service_subnet_id in ${KURYR_SERVICE_SUBNETS_IDS[@]}; do
        service_cidr=$(openstack --os-cloud devstack-admin \
                             --os-region "$REGION_NAME" \
                             subnet show "$service_subnet_id" \
                             -c cidr -f value)
        cluster_ip_ranges+=($(split_subnet "$service_cidr" | cut -f1))
    done

    command="${KURYR_KUBE_APISERVER_BINARY} \
                --service-cluster-ip-range=$(IFS=, ; echo "${cluster_ip_ranges[*]}") \
                --insecure-bind-address=0.0.0.0 \
                --insecure-port=${KURYR_K8S_API_PORT} \
                --etcd-servers=http://${SERVICE_HOST}:${ETCD_PORT} \
                --client-ca-file=${KURYR_KUBERNETES_DATA_DIR}/ca.crt \
                --token-auth-file=${KURYR_KUBERNETES_DATA_DIR}/token_auth.csv \
                --min-request-timeout=300 \
                --tls-cert-file=${KURYR_KUBERNETES_DATA_DIR}/server.cert \
                --tls-private-key-file=${KURYR_KUBERNETES_DATA_DIR}/server.key \
                --token-auth-file=${KURYR_KUBERNETES_DATA_DIR}/known_tokens.csv \
                --allow-privileged=true \
                --feature-gates="SCTPSupport=true,IPv6DualStack=true" \
                --v=$(get_k8s_log_level) \
                --logtostderr=true"

    run_process kubernetes-api "$command" root root
}

function run_k8s_controller_manager {
    local command
    local tmp_kube_controller_manager="/tmp/kube-controller-manager"
    local binary_name="kube-controller-manager"

    setup_k8s_binaries $tmp_kube_controller_manager $binary_name $KURYR_KUBE_CONTROLLER_MANAGER_BINARY

    # Runs Hyperkube's Kubernetes controller manager
    wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"

    command="${KURYR_KUBE_CONTROLLER_MANAGER_BINARY} \
                --master=$KURYR_K8S_API_URL \
                --service-account-private-key-file=${KURYR_KUBERNETES_DATA_DIR}/server.key \
                --root-ca-file=${KURYR_KUBERNETES_DATA_DIR}/ca.crt \
                --min-resync-period=3m \
                --v=$(get_k8s_log_level) \
                --logtostderr=true \
                --feature-gates="SCTPSupport=true,IPv6DualStack=true" \
                --leader-elect=false"

    run_process kubernetes-controller-manager "$command" root root
}

function run_k8s_scheduler {
    local command
    local tmp_kube_scheduler="/tmp/kube-scheduler"
    local binary_name="kube-scheduler"

    setup_k8s_binaries $tmp_kube_scheduler $binary_name $KURYR_KUBE_SCHEDULER_BINARY

    # Runs Kubernetes scheduler
    wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"

    command="${KURYR_KUBE_SCHEDULER_BINARY} \
                --master=${KURYR_K8S_API_URL} \
                --v=$(get_k8s_log_level) \
                --logtostderr=true \
                --feature-gates="SCTPSupport=true" \
                --leader-elect=false"

    run_process kubernetes-scheduler "$command" root root
}

function prepare_kubeconfig {
    $KURYR_KUBECTL_BINARY config set-cluster devstack-cluster \
        --server="${KURYR_K8S_API_URL}"
    $KURYR_KUBECTL_BINARY config set-credentials stack
    $KURYR_KUBECTL_BINARY config set-context devstack \
        --cluster=devstack-cluster --user=stack
    $KURYR_KUBECTL_BINARY config use-context devstack
}

function extract_k8s_binaries {
    local tmp_kubectl_path="/tmp/kubectl"
    local tmp_kubelet_path="/tmp/kubelet"
    local tmp_loopback_cni_path="/tmp/loopback"
    local kubectl_binary_name="kubectl"
    local kubelet_binary_name="kubelet"

    setup_k8s_binaries $tmp_kubectl_path $kubectl_binary_name $KURYR_KUBECTL_BINARY
    setup_k8s_binaries $tmp_kubelet_path $kubelet_binary_name $KURYR_KUBELET_BINARY

    sudo mkdir -p "$CNI_BIN_DIR"
    curl -L "${KURYR_CNI_PLUGINS}" | sudo tar -C "${CNI_BIN_DIR}" -xzvf - ./loopback
}

function prepare_kubelet {
    local kubelet_plugin_dir
    kubelet_plugin_dir="/etc/cni/net.d/"

    sudo install -o "$STACK_USER" -m 0664 -D \
        "${KURYR_HOME}${kubelet_plugin_dir}/10-kuryr.conflist" \
        "${CNI_CONF_DIR}/10-kuryr.conflist"
}

function run_k8s_kubelet {
    # Runs Hyperkube's Kubernetes kubelet from the extracted binary
    #
    # The reason for extracting the binary and running it in from the Host
    # filesystem is so that we can leverage the binding utilities that network
    # vendor devstack plugins may have installed (like ovs-vsctl). Also, it
    # saves us from the arduous task of setting up mounts to the official image
    # adding Python and all our CNI/binding dependencies.
    local command
    local minor_version

    sudo mkdir -p "${KURYR_KUBERNETES_DATA_DIR}/"{kubelet,kubelet.cert}
    command="$KURYR_KUBELET_BINARY \
        --kubeconfig=${HOME}/.kube/config \
        --v=2 \
        --address=0.0.0.0 \
        --enable-server \
        --network-plugin=cni \
        --feature-gates="SCTPSupport=true,IPv6DualStack=true" \
        --cni-bin-dir=$CNI_BIN_DIR \
        --cni-conf-dir=$CNI_CONF_DIR \
        --cert-dir=${KURYR_KUBERNETES_DATA_DIR}/kubelet.cert \
        --root-dir=${KURYR_KUBERNETES_DATA_DIR}/kubelet"

    if [[ ${CONTAINER_ENGINE} == 'docker' ]]; then
        command+=" --cgroup-driver $(docker info -f '{{.CgroupDriver}}')"
    elif [[ ${CONTAINER_ENGINE} == 'crio' ]]; then
        local crio_conf
        crio_conf=/etc/crio/crio.conf

        command+=" --cgroup-driver=$(iniget ${crio_conf} crio.runtime cgroup_manager)"
        command+=" --container-runtime=remote --container-runtime-endpoint=unix:///var/run/crio/crio.sock --runtime-request-timeout=10m"

        # We need to reconfigure CRI-O in this case as well.
        # FIXME(dulek): This should probably go to devstack-plugin-container
        iniset -sudo ${crio_conf} crio.network network_dir \"${CNI_CONF_DIR}\"
        iniset -sudo ${crio_conf} crio.network plugin_dir \"${CNI_BIN_DIR}\"
        sudo systemctl --no-block restart crio.service
    fi

    declare -r min_not_require_kubeconfig_ver="1.10.0"
    if [[ "$KURYR_KUBERNETES_VERSION" == "$(echo -e "${KURYR_KUBERNETES_VERSION}\n${min_not_require_kubeconfig_ver}" | sort -V | head -n 1)" ]]; then
        # Version 1.10 did away with that config option
        command+=" --require-kubeconfig"
    fi

    # Kubernetes 1.8+ requires additional option to work in the gate.
    declare -r min_no_swap_ver="1.8.0"
    if [[ "$min_no_swap_ver" == "$(echo -e "${KURYR_KUBERNETES_VERSION}\n${min_no_swap_ver}" | sort -V | head -n 1)" ]]; then
        command="$command --fail-swap-on=false"
    fi

    if is_service_enabled coredns; then
        service_cidr=$(openstack --os-cloud devstack-admin \
                                 --os-region "$REGION_NAME" \
                                 subnet show "${KURYR_SERVICE_SUBNETS_IDS[0]}" \
                                 -c cidr -f value)
        export KURYR_COREDNS_CLUSTER_IP=$(_cidr_range "$service_cidr" | cut -f2)
        command+=" --cluster-dns=${KURYR_COREDNS_CLUSTER_IP} --cluster-domain=cluster.local"
    fi

    wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"
    run_process kubelet "$command" root root
}

function run_coredns {
    local output_dir=$1
    mkdir -p "$output_dir"
    rm -f ${output_dir}/coredns.yml
    cat >> "${output_dir}/coredns.yml" << EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns
  namespace: kube-system
data:
  Corefile: |
    .:53 {
        errors
        kubernetes cluster.local in-addr.arpa ip6.arpa {
           pods insecure
           upstream
           fallthrough in-addr.arpa ip6.arpa
        }
        forward . 8.8.8.8:53
        cache 30
        loop
        reload
        loadbalance
EOF
    if [[ "$ENABLE_DEBUG_LOG_LEVEL" == "True" ]]; then
        cat >> "${output_dir}/coredns.yml" << EOF
        debug
        log
EOF
    fi
    cat >> "${output_dir}/coredns.yml" << EOF
    }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: coredns
  namespace: kube-system
  labels:
    k8s-app: coredns
    kubernetes.io/cluster-service: "true"
    kubernetes.io/name: "CoreDNS"
spec:
  replicas: 1
  selector:
    matchLabels:
      k8s-app: coredns
  template:
    metadata:
      labels:
        k8s-app: coredns
      annotations:
        scheduler.alpha.kubernetes.io/critical-pod: ''
        scheduler.alpha.kubernetes.io/tolerations: '[{"key":"CriticalAddonsOnly", "operator":"Exists"}]'
    spec:
      containers:
      - name: coredns
        image: quay.io/kuryr/coredns:1.5.0
        imagePullPolicy: Always
        args: [ "-conf", "/etc/coredns/Corefile" ]
        volumeMounts:
        - name: config-volume
          mountPath: /etc/coredns
      dnsPolicy: Default
      volumes:
        - name: config-volume
          configMap:
            name: coredns
            items:
            - key: Corefile
              path: Corefile
EOF

    /usr/local/bin/kubectl apply -f ${output_dir}/coredns.yml
    /usr/local/bin/kubectl expose deploy/coredns --port=53 --target-port=53 --protocol=UDP -n kube-system --cluster-ip=${KURYR_COREDNS_CLUSTER_IP}
}


function run_kuryr_kubernetes {
    local python_bin=$(which python3)

    if is_service_enabled openshift-master; then
        wait_for "OpenShift API Server" "${KURYR_K8S_API_ROOT}" \
            "${OPENSHIFT_DATA_DIR}/master/ca.crt" 1200
    else
        wait_for_ok_health "Kubernetes API Server" "${KURYR_K8S_API_ROOT}/healthz" \
            "${KURYR_KUBERNETES_DATA_DIR}/kuryr-ca.crt" \
            "${KURYR_KUBERNETES_DATA_DIR}/kuryr.key" \
            "${KURYR_KUBERNETES_DATA_DIR}/kuryr.crt" \
            1200
    fi

    local controller_bin=$(which kuryr-k8s-controller)
    run_process kuryr-kubernetes "$controller_bin --config-file $KURYR_CONFIG"
}


function run_kuryr_daemon {
    local daemon_bin=$(which kuryr-daemon)
    run_process kuryr-daemon "$daemon_bin --config-file $KURYR_CONFIG" root root
}


function configure_overcloud_vm_k8s_svc_sg {
    local dst_port
    local project_id
    local security_group

    if is_service_enabled octavia; then
        dst_port=${KURYR_K8S_API_LB_PORT}
    else
        dst_port=${KURYR_K8S_API_PORT}
    fi

    project_id=$(get_or_create_project \
        "$KURYR_NEUTRON_DEFAULT_PROJECT" default)
    security_group=$(openstack security group list \
        --project "$project_id" -c ID -c Name -f value | \
        awk '{if ($2=="default") print $1}')
    for ethertype in ${KURYR_ETHERTYPES[@]}; do
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            security group rule create --project "$project_id" \
            --dst-port "$dst_port" --ethertype "$ethertype" "$security_group"
    done
    openstack port set "$KURYR_OVERCLOUD_VM_PORT" --security-group service_pod_access
}

function update_tempest_conf_file {

    if [[ "$KURYR_USE_PORT_POOLS" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes port_pool_enabled True
    fi
    if [[ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes containerized True
    fi
    if [[ "$KURYR_SUBNET_DRIVER" == "namespace" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes subnet_per_namespace True
        iniset $TEMPEST_CONFIG kuryr_kubernetes kuryrnetworks True
    fi
    if [[ "$KURYR_K8S_SERIAL_TESTS" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes run_tests_serial True
    fi
    if [[ "$KURYR_MULTI_VIF_DRIVER" == "npwg_multiple_interfaces" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes npwg_multi_vif_enabled True
    fi
    if [[ "$KURYR_ENABLED_HANDLERS" =~ .*policy.* ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes network_policy_enabled True
        iniset $TEMPEST_CONFIG kuryr_kubernetes new_kuryrnetworkpolicy_crd True
    fi
    # NOTE(yboaron): Services with protocol UDP are supported in Kuryr
    # starting from Stein release
    iniset $TEMPEST_CONFIG kuryr_kubernetes test_udp_services True
    if [[ "$KURYR_CONTROLLER_HA" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes ap_ha True
    fi
    if [[ "$KURYR_K8S_MULTI_WORKER_TESTS" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes multi_worker_setup True
    fi
    if [[ "$KURYR_K8S_CLOUD_PROVIDER" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes cloud_provider True
    fi
    if [[ "$KURYR_CONFIGMAP_MODIFIABLE" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes configmap_modifiable True
    fi
    if [[ "$KURYR_IPV6" == "True" || "$KURYR_DUAL_STACK" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes ipv6 True
    fi
    iniset $TEMPEST_CONFIG kuryr_kubernetes validate_crd True
    iniset $TEMPEST_CONFIG kuryr_kubernetes kuryrports True
    iniset $TEMPEST_CONFIG kuryr_kubernetes kuryrloadbalancers True
    iniset $TEMPEST_CONFIG kuryr_kubernetes test_services_without_selector True
    iniset $TEMPEST_CONFIG kuryr_kubernetes test_sctp_services True
}

source $DEST/kuryr-kubernetes/devstack/lib/kuryr_kubernetes

# main loop
if [[ "$1" == "stack" && "$2" == "install" ]]; then
    setup_develop "$KURYR_HOME"
    if is_service_enabled kubelet || is_service_enabled openshift-node; then
        KURYR_K8S_CONTAINERIZED_DEPLOYMENT=$(trueorfalse False KURYR_K8S_CONTAINERIZED_DEPLOYMENT)
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "False" ]; then
            install_kuryr_cni
        fi
    fi

elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
    create_kuryr_account
    configure_kuryr
fi

if [[ "$1" == "stack" && "$2" == "extra" ]]; then
    if [ "$KURYR_CONFIGURE_NEUTRON_DEFAULTS" == "True" ]; then
        KURYR_CONFIGURE_NEUTRON_DEFAULTS=$(trueorfalse True KURYR_CONFIGURE_NEUTRON_DEFAULTS)
        if is_service_enabled kuryr-kubernetes; then
            configure_neutron_defaults
        fi

        KURYR_K8S_CONTAINERIZED_DEPLOYMENT=$(trueorfalse False KURYR_K8S_CONTAINERIZED_DEPLOYMENT)
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "False" ]; then
            service_cidr=$(openstack --os-cloud devstack-admin \
                                     --os-region "$REGION_NAME" \
                                     subnet show "${KURYR_SERVICE_SUBNETS_IDS[0]}" \
                                     -c cidr -f value)
            k8s_api_clusterip=$(_cidr_range "$service_cidr" | cut -f1)
            # NOTE(mrostecki): KURYR_K8S_API_ROOT will be a global to be used by next
            #                  deployment phases.
            KURYR_K8S_API_ROOT=${KURYR_K8S_API_URL}
            if is_service_enabled octavia; then
                KURYR_K8S_API_ROOT="https://${k8s_api_clusterip}:${KURYR_K8S_API_LB_PORT}"
            fi
            iniset "$KURYR_CONFIG" kubernetes api_root ${KURYR_K8S_API_ROOT}
            iniset "$KURYR_CONFIG" kubernetes ssl_ca_crt_file '""'
            iniset "$KURYR_CONFIG" kubernetes token_file '""'
        else
            iniset "$KURYR_CONFIG" kubernetes api_root '""'
        fi
    fi

    # FIXME(limao): When Kuryr start up, it need to detect if neutron
    # support tag plugin.
    #
    # Kuryr will call neutron extension API to verify if neutron support
    # tag.  So Kuryr need to start after neutron-server finish load tag
    # plugin.  The process of devstack is:
    #     ...
    #     run_phase "stack" "post-config"
    #     ...
    #     start neutron-server
    #     ...
    #     run_phase "stack" "extra"
    #
    # If Kuryr start up in "post-config" phase, there is no way to make
    # sure Kuryr can start before neutron-server, so Kuryr start in "extra"
    # phase.  Bug: https://bugs.launchpad.net/kuryr/+bug/1587522

    # FIXME(apuimedo): Allow running only openshift node for multinode devstack
    # We are missing generating a node config so that it does not need to
    # bootstrap from the master config.
    if is_service_enabled openshift-master || is_service_enabled openshift-node; then
        install_openshift_binary
    fi
    if is_service_enabled openshift-master; then
        run_openshift_master
        make_admin_cluster_admin
    fi
    if is_service_enabled openshift-node; then
        prepare_kubelet
        run_openshift_node
        if is_service_enabled openshift-dns; then
            FIRST_NAMESERVER=$(grep nameserver /etc/resolv.conf | awk '{print $2; exit}')
            openshift_node_set_dns_config "${OPENSHIFT_DATA_DIR}/node/node-config.yaml" \
                "$FIRST_NAMESERVER"
            run_openshift_dnsmasq "$FIRST_NAMESERVER"
            run_openshift_dns
       fi

        KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE=$(trueorfalse True KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE)
        if [[ "$KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE" == "True" ]]; then
            ovs_bind_for_kubelet "$KURYR_NEUTRON_DEFAULT_PROJECT" ${OPENSHIFT_API_PORT}
        fi
    fi

    if is_service_enabled kubernetes-api kubernetes-controller-manager kubernetes-scheduler kubelet; then
        get_container "$KURYR_KUBERNETES_IMAGE" "$KURYR_KUBERNETES_VERSION"
    fi

    if is_service_enabled kubernetes-api kubernetes-controller-manager kubernetes-scheduler; then
        prepare_kubernetes_files
    fi

    if is_service_enabled kubernetes-api; then
        run_k8s_api
    fi

    if is_service_enabled kubernetes-controller-manager; then
        run_k8s_controller_manager
    fi

    if is_service_enabled kubernetes-scheduler; then
        run_k8s_scheduler
    fi

    if is_service_enabled kubelet; then
        prepare_kubelet
        extract_k8s_binaries
        prepare_kubeconfig
        run_k8s_kubelet
        KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE=$(trueorfalse True KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE)
        if [[ "$KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE" == "True" ]]; then
            ovs_bind_for_kubelet "$KURYR_NEUTRON_DEFAULT_PROJECT" 6443
        else
            configure_overcloud_vm_k8s_svc_sg
        fi
    fi

    if is_service_enabled tempest; then
        copy_tempest_kubeconfig
        configure_k8s_pod_sg_rules
    fi

    KURYR_K8S_CONTAINERIZED_DEPLOYMENT=$(trueorfalse False KURYR_K8S_CONTAINERIZED_DEPLOYMENT)
    KURYR_FORCE_IMAGE_BUILD=$(trueorfalse False KURYR_FORCE_IMAGE_BUILD)
    if is_service_enabled kuryr-kubernetes || [[ ${KURYR_FORCE_IMAGE_BUILD} == "True" ]]; then
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]; then
            build_kuryr_containers
        fi
    fi

    if is_service_enabled kuryr-kubernetes; then
        /usr/local/bin/kubectl apply -f ${KURYR_HOME}/kubernetes_crds/kuryr_crds/
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]; then
            generate_containerized_kuryr_resources
        fi
        if [ "$KURYR_MULTI_VIF_DRIVER" == "npwg_multiple_interfaces" ]; then
            /usr/local/bin/kubectl apply -f ${KURYR_HOME}/kubernetes_crds/network_attachment_definition_crd.yaml
        fi
    fi

elif [[ "$1" == "stack" && "$2" == "test-config" ]]; then
    if is_service_enabled kuryr-kubernetes; then
        if is_service_enabled octavia; then
            create_k8s_api_service
        fi

        # FIXME(dulek): This is a very late phase to start Kuryr services.
        #               We're doing it here because we need K8s API LB to be
        #               created in order to run kuryr services. Thing is
        #               Octavia is unable to create LB until test-config phase.
        #               We can revisit this once Octavia's DevStack plugin will
        #               get improved.
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]; then
            run_containerized_kuryr_resources
        else
            run_kuryr_kubernetes
            run_kuryr_daemon
        fi

        if is_service_enabled coredns; then
            run_coredns "${DATA_DIR}/kuryr-kubernetes"
        fi
        # Needs kuryr to be running
        if is_service_enabled openshift-dns; then
            configure_and_run_registry
        fi
    fi
    if is_service_enabled tempest; then
        update_tempest_conf_file
    fi
fi

if [[ "$1" == "unstack" ]]; then
    KURYR_K8S_CONTAINERIZED_DEPLOYMENT=$(trueorfalse False KURYR_K8S_CONTAINERIZED_DEPLOYMENT)
    if is_service_enabled kuryr-kubernetes; then
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]; then
            kubectl delete deploy/kuryr-controller
        fi
        stop_process kuryr-kubernetes
    elif is_service_enabled kubelet; then
        kubectl delete nodes ${HOSTNAME}
    fi
    if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]; then
        kubectl delete ds/kuryr-cni-ds
    fi
    stop_process kuryr-daemon

    if is_service_enabled kubernetes-controller-manager; then
        stop_container kubernetes-controller-manager
    fi
    if is_service_enabled kubernetes-scheduler; then
        stop_container kubernetes-scheduler
    fi
    if is_service_enabled kubelet; then
        stop_process kubelet
    fi
    if is_service_enabled kubernetes-api; then
        stop_container kubernetes-api
    fi
    if is_service_enabled openshift-master; then
        stop_process openshift-master
    fi
    if is_service_enabled openshift-node; then
        stop_process openshift-node
        if is_service_enabled openshift-dns; then
            reinstate_old_dns_config
            stop_process openshift-dns
            stop_process openshift-dnsmasq
        fi
        # NOTE(dulek): We need to clean up the configuration as well, otherwise
        # when doing stack.sh again, openshift-node will use old certificates.
        sudo rm -rf ${OPENSHIFT_DATA_DIR}
    fi

    cleanup_kuryr_devstack_iptables
fi

# Restore xtrace
$XTRACE
