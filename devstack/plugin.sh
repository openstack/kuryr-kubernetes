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

function container_runtime {
    if [[ ${CONTAINER_ENGINE} == 'crio' ]]; then
        sudo podman "$@"
    else
        docker "$@"
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
    # directory, so we need to modify that.
    iniset "$KURYR_CONFIG" neutron cafile /etc/ssl/certs/kuryr-ca-bundle.crt
    iniset "$KURYR_CONFIG" kubernetes token_file /var/run/secrets/kubernetes.io/serviceaccount/token
    iniset "$KURYR_CONFIG" kubernetes ssl_ca_crt_file /var/run/secrets/kubernetes.io/serviceaccount/ca.crt

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
        "${k8s_data_dir}/service_account.yml" \
        || die $LINENO "Failed to create kuryr-kubernetes ServiceAccount."

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
  python - <<EOF "$1"
import sys
from netaddr import IPAddress, IPNetwork
n = IPNetwork(sys.argv[1])
print("%s\\t%s" % (IPAddress(n.first + 1), IPAddress(n.last - 1)))
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
    service_cidr=$(openstack --os-cloud devstack-admin \
                             --os-region "$REGION_NAME" \
                             subnet show "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET" \
                             -c cidr -f value)

    fixed_ips=$(openstack port show kubelet-"${HOSTNAME}" -c fixed_ips -f value)
    kubelet_iface_ip=$(python -c "print ${fixed_ips}[0]['ip_address']")

    k8s_api_clusterip=$(_cidr_range "$service_cidr" | cut -f1)

    create_load_balancer "$lb_name" "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET"\
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
    local pod_subnet_id
    local sg_ids
    local service_subnet_id
    local subnetpool_id
    local router
    local router_id
    local ext_svc_net_id
    local ext_svc_subnet_id
    local prot

    project_id=$(get_or_create_project \
        "$KURYR_NEUTRON_DEFAULT_PROJECT" default)
    ext_svc_net_id="$(openstack network show -c id -f value \
        "${KURYR_NEUTRON_DEFAULT_EXT_SVC_NET}")"

    # If a subnetpool is not passed, we get the one created in devstack's
    # Neutron module
    subnetpool_id=${KURYR_NEUTRON_DEFAULT_SUBNETPOOL_ID:-${SUBNETPOOL_V4_ID}}
    router=${KURYR_NEUTRON_DEFAULT_ROUTER:-$Q_ROUTER_NAME}
    if [ "$router" != "$Q_ROUTER_NAME" ]; then
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            router create --project "$project_id" "$router"
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            router set --external-gateway "$ext_svc_net_id" "$router"
    fi
    router_id="$(openstack router show -c id -f value \
        "$router")"

    create_k8s_subnet "$project_id" \
                      "$KURYR_NEUTRON_DEFAULT_POD_NET" \
                      "$KURYR_NEUTRON_DEFAULT_POD_SUBNET" \
                      "$subnetpool_id" \
                      "$router"
    pod_subnet_id="$(openstack subnet show -c id -f value \
        "${KURYR_NEUTRON_DEFAULT_POD_SUBNET}")"

    create_k8s_subnet "$project_id" \
                      "$KURYR_NEUTRON_DEFAULT_SERVICE_NET" \
                      "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET" \
                      "$subnetpool_id" \
                      "$router" \
                      "True"
    service_subnet_id="$(openstack subnet show -c id -f value \
        "${KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET}")"

    if [[ "$KURYR_SG_DRIVER" == "default" ]]; then
        sg_ids=$(echo $(openstack security group list \
            --project "$project_id" -c ID -f value) | tr ' ' ',')
    fi

    # In order for the ports to allow service traffic under Octavia L3 mode,
    # it is necessary for the service subnet to be allowed into the port's
    # security groups. If L3 is used, then the pods created will include it.
    # Otherwise it will be just used by the kubelet port used for the K8s API
    # load balancer
    local service_cidr
    local service_pod_access_sg_id
    service_cidr=$(openstack --os-cloud devstack-admin \
        --os-region "$REGION_NAME" subnet show \
        "${KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET}" -f value -c cidr)
    service_pod_access_sg_id=$(openstack --os-cloud devstack-admin \
        --os-region "$REGION_NAME" \
        security group create --project "$project_id" \
        service_pod_access -f value -c id)
    openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
        security group rule create --project "$project_id" \
        --description "k8s service subnet allowed" \
        --remote-ip "$service_cidr" --ethertype IPv4 --protocol tcp \
        "$service_pod_access_sg_id"
    # Since Octavia supports also UDP load balancing, we need to allow
    # also udp traffic
    openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
        security group rule create --project "$project_id" \
        --description "k8s service subnet UDP allowed" \
        --remote-ip "$service_cidr" --ethertype IPv4 --protocol udp \
        "$service_pod_access_sg_id"

    if [[ "$KURYR_K8S_OCTAVIA_MEMBER_MODE" == "L3" ]]; then
        if [ -n "$sg_ids" ]; then
            sg_ids+=",${service_pod_access_sg_id}"
        else
            sg_ids="${service_pod_access_sg_id}"
        fi
    elif [[ "$KURYR_K8S_OCTAVIA_MEMBER_MODE" == "L2" ]]; then
        # In case the member connectivity is L2, Octavia by default uses the
        # admin 'default' sg to create a port for the amphora load balancer
        # at the member ports subnet. Thus we need to allow L2 communication
        # between the member ports and the octavia ports by allowing all
        # access from the pod subnet range to the ports in that subnet, and
        # include it into $sg_ids
        local pod_cidr
        local pod_pod_access_sg_id
        pod_cidr=$(openstack --os-cloud devstack-admin \
            --os-region "$REGION_NAME" subnet show \
            "${KURYR_NEUTRON_DEFAULT_POD_SUBNET}" -f value -c cidr)
        octavia_pod_access_sg_id=$(openstack --os-cloud devstack-admin \
            --os-region "$REGION_NAME" \
            security group create --project "$project_id" \
            octavia_pod_access -f value -c id)
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            security group rule create --project "$project_id" \
            --description "k8s pod subnet allowed from k8s-pod-subnet" \
            --remote-ip "$pod_cidr" --ethertype IPv4 --protocol tcp \
            "$octavia_pod_access_sg_id"
        # Since Octavia supports also UDP load balancing, we need to allow
        # also udp traffic
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            security group rule create --project "$project_id" \
            --description "k8s pod subnet allowed from k8s-pod-subnet" \
            --remote-ip "$pod_cidr" --ethertype IPv4 --protocol udp \
            "$octavia_pod_access_sg_id"
        if [ -n "$sg_ids" ]; then
            sg_ids+=",${octavia_pod_access_sg_id}"
        else
            sg_ids="${octavia_pod_access_sg_id}"
        fi
    fi

    iniset "$KURYR_CONFIG" neutron_defaults project "$project_id"
    iniset "$KURYR_CONFIG" neutron_defaults pod_subnet "$pod_subnet_id"
    iniset "$KURYR_CONFIG" neutron_defaults service_subnet "$service_subnet_id"
    if [ "$KURYR_SUBNET_DRIVER" == "namespace" ]; then
        iniset "$KURYR_CONFIG" namespace_subnet pod_subnet_pool "$subnetpool_id"
        iniset "$KURYR_CONFIG" namespace_subnet pod_router "$router_id"
    fi
    if [ "$KURYR_SG_DRIVER" == "namespace" ]; then
        local allow_namespace_sg_id
        local allow_default_sg_id
        allow_namespace_sg_id=$(openstack --os-cloud devstack-admin \
            --os-region "$REGION_NAME" \
            security group create --project "$project_id" \
            allow_from_namespace -f value -c id)
        allow_default_sg_id=$(openstack --os-cloud devstack-admin \
            --os-region "$REGION_NAME" \
            security group create --project "$project_id" \
            allow_from_default -f value -c id)

        for prot in icmp tcp udp ;
          do
            openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
              security group rule create --project "$project_id" \
              --description "allow traffic from default namespace" \
              --remote-group "$allow_namespace_sg_id" --ethertype IPv4 --protocol "$prot" \
              "$allow_default_sg_id"

            if [ "$prot" != "icmp" ] ; then
              openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
              security group rule create --project "$project_id" \
              --description "allow traffic from namespaces at default namespace" \
              --remote-group "$allow_default_sg_id" --ethertype IPv4 --protocol "$prot" \
              "$allow_namespace_sg_id"
            fi
          done

        # NOTE(ltomasbo): Some tempest test are using FIP and depends on icmp
        # traffic being allowed to the pods. To enable these tests we permit
        # icmp traffic from everywhere on the default namespace. Note tcp
        # traffic will be dropped, just icmp is permitted.
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
            security group rule create --project "$project_id" \
            --description "allow imcp traffic from everywhere to default namespace" \
            --ethertype IPv4 --protocol icmp "$allow_namespace_sg_id"

        iniset "$KURYR_CONFIG" namespace_sg sg_allow_from_namespaces "$allow_namespace_sg_id"
        iniset "$KURYR_CONFIG" namespace_sg sg_allow_from_default "$allow_default_sg_id"
    elif [[ "$KURYR_SG_DRIVER" == "policy" ]]; then
        # NOTE(dulek): Using the default DevStack's SG is not enough to match
        # the NP specification. We need to open ingress to everywhere, so we
        # create allow-all group.
        allow_all_sg_id=$(openstack --os-cloud devstack-admin \
            --os-region "$REGION_NAME" \
            security group create --project "$project_id" \
            allow-all -f value -c id)
        openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
          security group rule create --project "$project_id" \
          --description "allow all ingress traffic" \
          --ethertype IPv4 --ingress --protocol any \
          "$allow_all_sg_id"
        if [ -n "$sg_ids" ]; then
            sg_ids+=",${allow_all_sg_id}"
        else
            sg_ids="${allow_all_sg_id}"
        fi
    fi
    iniset "$KURYR_CONFIG" neutron_defaults pod_security_groups "$sg_ids"

    if [[ "$KURYR_SG_DRIVER" == "namespace" || "$KURYR_SG_DRIVER" == "policy" ]]; then
        # NOTE(ltomasbo): As more security groups and rules are created, there
        # is a need to increase the quota for it
         openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
             quota set --secgroups 100 --secgroup-rules 100 "$project_id"
    fi

    # NOTE(dulek): DevStack's admin default for SG's and instances is 10, this
    #              is too little for our tests with Octavia configured to use
    #              amphora.
    openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
        quota set --secgroups 100 --secgroup-rules 100 --instances 100 admin

    if [ -n "$OVS_BRIDGE" ]; then
        iniset "$KURYR_CONFIG" neutron_defaults ovs_bridge "$OVS_BRIDGE"
    fi
    iniset "$KURYR_CONFIG" neutron_defaults external_svc_net "$ext_svc_net_id"
    iniset "$KURYR_CONFIG" octavia_defaults member_mode "$KURYR_K8S_OCTAVIA_MEMBER_MODE"
    iniset "$KURYR_CONFIG" octavia_defaults sg_mode "$KURYR_K8S_OCTAVIA_SG_MODE"
    iniset "$KURYR_CONFIG" octavia_defaults enforce_sg_rules "$KURYR_ENFORCE_SG_RULES"
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
                             subnet show "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET"\
                             -c cidr -f value)
    k8s_api_clusterip=$(_cidr_range "$service_cidr" | cut -f1)

    # It's not prettiest, but the file haven't changed since 1.6, so it's safe to download it like that.
    curl -o /tmp/make-ca-cert.sh https://raw.githubusercontent.com/kubernetes/kubernetes/release-1.8/cluster/saltbase/salt/generate-cert/make-ca-cert.sh
    chmod +x /tmp/make-ca-cert.sh

    # Create HTTPS certificates
    sudo groupadd -f -r kube-cert

    # hostname -I gets the ip of the node
    sudo CERT_DIR=${KURYR_HYPERKUBE_DATA_DIR} /tmp/make-ca-cert.sh $(hostname -I | awk '{print $1}') "IP:${HOST_IP},IP:${k8s_api_clusterip},DNS:kubernetes,DNS:kubernetes.default,DNS:kubernetes.default.svc,DNS:kubernetes.default.svc.cluster.local"

    # Create basic token authorization
    sudo bash -c "echo 'admin,admin,admin' > $KURYR_HYPERKUBE_DATA_DIR/basic_auth.csv"

    # Create known tokens for service accounts
    sudo bash -c "echo '$(create_token),admin,admin' >> ${KURYR_HYPERKUBE_DATA_DIR}/known_tokens.csv"
    sudo bash -c "echo '$(create_token),kubelet,kubelet' >> ${KURYR_HYPERKUBE_DATA_DIR}/known_tokens.csv"
    sudo bash -c "echo '$(create_token),kube_proxy,kube_proxy' >> ${KURYR_HYPERKUBE_DATA_DIR}/known_tokens.csv"

    # Copy certs for Kuryr services to use
    sudo install -m 644 "${KURYR_HYPERKUBE_DATA_DIR}/kubecfg.crt" "${KURYR_HYPERKUBE_DATA_DIR}/kuryr.crt"
    sudo install -m 644 "${KURYR_HYPERKUBE_DATA_DIR}/kubecfg.key" "${KURYR_HYPERKUBE_DATA_DIR}/kuryr.key"
    sudo install -m 644 "${KURYR_HYPERKUBE_DATA_DIR}/ca.crt" "${KURYR_HYPERKUBE_DATA_DIR}/kuryr-ca.crt"

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

function run_k8s_api {
    local service_cidr
    local cluster_ip_range
    local command

    # Runs Hyperkube's Kubernetes API Server
    wait_for "etcd" "http://${SERVICE_HOST}:${ETCD_PORT}/v2/machines"

    service_cidr=$(openstack --os-cloud devstack-admin \
                         --os-region "$REGION_NAME" \
                         subnet show "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET" \
                         -c cidr -f value)
    if is_service_enabled octavia; then
        cluster_ip_range=$(split_subnet "$service_cidr" | cut -f1)
    else
        cluster_ip_range="$service_cidr"
    fi

    command=(--net=host
             --volume=${KURYR_HYPERKUBE_DATA_DIR}:/srv/kubernetes:rw)
    if [[ ${CONTAINER_ENGINE} == 'docker' ]]; then
        command+=(--restart=on-failure)
    fi
    command+=(${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}
              /hyperkube apiserver
                --service-cluster-ip-range=${cluster_ip_range}
                --insecure-bind-address=0.0.0.0
                --insecure-port=${KURYR_K8S_API_PORT}
                --etcd-servers=http://${SERVICE_HOST}:${ETCD_PORT}
                --client-ca-file=/srv/kubernetes/ca.crt
                --basic-auth-file=/srv/kubernetes/basic_auth.csv
                --min-request-timeout=300
                --tls-cert-file=/srv/kubernetes/server.cert
                --tls-private-key-file=/srv/kubernetes/server.key
                --token-auth-file=/srv/kubernetes/known_tokens.csv
                --allow-privileged=true
                --v=$(get_k8s_log_level)
                --logtostderr=true)

    run_container kubernetes-api "${command[@]}"
}

function run_k8s_controller_manager {
    local command

    # Runs Hyperkube's Kubernetes controller manager
    wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"

    command=(--net=host
             --volume=${KURYR_HYPERKUBE_DATA_DIR}:/srv/kubernetes:rw)
    if [[ ${CONTAINER_ENGINE} == 'docker' ]]; then
        command+=(--restart=on-failure)
    fi
    command+=(${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}
              /hyperkube controller-manager
                --master=$KURYR_K8S_API_URL
                --service-account-private-key-file=/srv/kubernetes/server.key
                --root-ca-file=/srv/kubernetes/ca.crt
                --min-resync-period=3m
                --v=$(get_k8s_log_level)
                --logtostderr=true
                --leader-elect=false)

    run_container kubernetes-controller-manager "${command[@]}"
}

function run_k8s_scheduler {
    local command

    # Runs Hyperkube's Kubernetes scheduler
    wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"

    command=(--net=host
             --volume=${KURYR_HYPERKUBE_DATA_DIR}:/srv/kubernetes:rw)
    if [[ ${CONTAINER_ENGINE} == 'docker' ]]; then
        command+=(--restart=on-failure)
    fi
    command+=(${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}
              /hyperkube scheduler
                --master=$KURYR_K8S_API_URL
                --v=$(get_k8s_log_level)
                --logtostderr=true
                --leader-elect=false)

    run_container kubernetes-scheduler "${command[@]}"
}

function prepare_kubeconfig {
    $KURYR_HYPERKUBE_BINARY kubectl config set-cluster devstack-cluster \
        --server="${KURYR_K8S_API_URL}"
    $KURYR_HYPERKUBE_BINARY kubectl config set-context devstack \
        --cluster=devstack-cluster
    $KURYR_HYPERKUBE_BINARY kubectl config use-context devstack
}

function extract_hyperkube {
    local hyperkube_container
    local tmp_hyperkube_path

    tmp_hyperkube_path="/tmp/hyperkube"
    tmp_loopback_cni_path="/tmp/loopback"
    tmp_nsenter_path="/tmp/nsenter"

    hyperkube_container=$(container_runtime run -d \
        --net host \
       "${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}" \
       /bin/false)
    if [[ ${CONTAINER_ENGINE} == 'crio' ]]; then
        mnt=`container_runtime mount "${hyperkube_container}"`
        sudo cp "${mnt}/hyperkube" "$tmp_hyperkube_path"
        sudo cp "${mnt}/opt/cni/bin/loopback" "$tmp_loopback_cni_path"
        sudo cp "${mnt}/usr/bin/nsenter" "$tmp_nsenter_path"
        container_runtime umount ${hyperkube_container}
    else
        container_runtime cp "${hyperkube_container}:/hyperkube" "$tmp_hyperkube_path"
        container_runtime cp "${hyperkube_container}:/opt/cni/bin/loopback" \
            "$tmp_loopback_cni_path"
        container_runtime cp "${hyperkube_container}:/usr/bin/nsenter" "$tmp_nsenter_path"
    fi

    container_runtime rm --force "$hyperkube_container"
    sudo install -o "$STACK_USER" -m 0555 -D "$tmp_hyperkube_path" \
        "$KURYR_HYPERKUBE_BINARY"
    sudo install -o "$STACK_USER" -m 0555 -D "$tmp_loopback_cni_path" \
        "${CNI_BIN_DIR}/loopback"
    sudo install -o "root" -m 0555 -D "$tmp_nsenter_path" \
        "/usr/local/bin/nsenter"

    # Convenience kubectl executable for development
    sudo install -o "$STACK_USER" -m 555 -D "${KURYR_HOME}/devstack/kubectl" \
        "$(dirname $KURYR_HYPERKUBE_BINARY)/kubectl"
}

function prepare_kubelet {
    local kubelet_plugin_dir
    kubelet_plugin_dir="/etc/cni/net.d/"

    sudo install -o "$STACK_USER" -m 0664 -D \
        "${KURYR_HOME}${kubelet_plugin_dir}/10-kuryr.conf" \
        "${CNI_CONF_DIR}/10-kuryr.conf"
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

    sudo mkdir -p "${KURYR_HYPERKUBE_DATA_DIR}/"{kubelet,kubelet.cert}
    command="$KURYR_HYPERKUBE_BINARY kubelet\
        --kubeconfig=${HOME}/.kube/config \
        --allow-privileged=true \
        --v=2 \
        --address=0.0.0.0 \
        --enable-server \
        --network-plugin=cni \
        --cni-bin-dir=$CNI_BIN_DIR \
        --cni-conf-dir=$CNI_CONF_DIR \
        --cert-dir=${KURYR_HYPERKUBE_DATA_DIR}/kubelet.cert \
        --root-dir=${KURYR_HYPERKUBE_DATA_DIR}/kubelet"

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
    if [[ "$KURYR_HYPERKUBE_VERSION" == "$(echo -e "${KURYR_HYPERKUBE_VERSION}\n${min_not_require_kubeconfig_ver}" | sort -V | head -n 1)" ]]; then
        # Version 1.10 did away with that config option
        command+=" --require-kubeconfig"
    fi

    # Kubernetes 1.8+ requires additional option to work in the gate.
    declare -r min_no_swap_ver="1.8.0"
    if [[ "$min_no_swap_ver" == "$(echo -e "${KURYR_HYPERKUBE_VERSION}\n${min_no_swap_ver}" | sort -V | head -n 1)" ]]; then
        command="$command --fail-swap-on=false"
    fi

    if is_service_enabled coredns; then
        local k8s_resolv_conf
        command+=" --cluster-dns=${HOST_IP} --cluster-domain=cluster.local"
    fi

    wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"
    if [[ "$USE_SYSTEMD" = "True" ]]; then
        # If systemd is being used, proceed as normal
        run_process kubelet "$command" root root
    else
        # If screen is being used, there is a possibility that the devstack
        # environment is on a stable branch. Older versions of run_process have
        # a different signature. Sudo is used as a workaround that works in
        # both older and newer versions of devstack.
        run_process kubelet "sudo $command"
    fi
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
        bind ${HOST_IP}
        errors
        kubernetes cluster.local in-addr.arpa ip6.arpa {
           pods insecure
           upstream
           fallthrough in-addr.arpa ip6.arpa
        }
        proxy . /etc/resolv.conf
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
apiVersion: extensions/v1beta1
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
      hostNetwork: true
      containers:
      - name: coredns
        image: quay.io/kuryr/coredns:1.4.0
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
}


function run_kuryr_kubernetes {
    local python_bin=$(which python)

    if is_service_enabled openshift-master; then
        wait_for "OpenShift API Server" "${KURYR_K8S_API_ROOT}" \
            "${OPENSHIFT_DATA_DIR}/master/ca.crt" 1200
    else
        wait_for_ok_health "Kubernetes API Server" "${KURYR_K8S_API_ROOT}/healthz" \
            "${KURYR_HYPERKUBE_DATA_DIR}/kuryr-ca.crt" \
            "${KURYR_HYPERKUBE_DATA_DIR}/kuryr.key" \
            "${KURYR_HYPERKUBE_DATA_DIR}/kuryr.crt" \
            1200
    fi

    local controller_bin=$(which kuryr-k8s-controller)
    run_process kuryr-kubernetes "$controller_bin --config-file $KURYR_CONFIG"
}


function run_kuryr_daemon {
    local daemon_bin=$(which kuryr-daemon)
    run_process kuryr-daemon "$daemon_bin --config-file $KURYR_CONFIG" root root
}

function create_ingress_l7_router {

    local lb_port_id
    local lb_name
    local project_id
    local max_timeout
    local lb_vip
    local fake_svc_name
    local l7_router_fip
    local project_id
    local lb_uuid

    lb_name=${KURYR_L7_ROUTER_NAME}
    max_timeout=1000
    project_id=$(get_or_create_project \
        "$KURYR_NEUTRON_DEFAULT_PROJECT" default)

    create_load_balancer "$lb_name" "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET" "$project_id"

    wait_for_lb $lb_name $max_timeout

    lb_port_id="$(get_loadbalancer_attribute "$lb_name" "vip_port_id")"

    #allocate FIP and bind it to lb vip
    l7_router_fip=$(openstack --os-cloud devstack-admin \
           --os-region "$REGION_NAME" \
           floating ip create --project "$project_id" \
            --subnet "$KURYR_NEUTRON_DEFAULT_EXT_SVC_SUBNET" \
             "$KURYR_NEUTRON_DEFAULT_EXT_SVC_NET" \
            -f value -c floating_ip_address)

    openstack  --os-cloud devstack-admin \
            --os-region "$REGION_NAME" \
            floating ip set --port "$lb_port_id" "$l7_router_fip"

    lb_uuid="$(get_loadbalancer_attribute "$lb_name" "id")"
    iniset "$KURYR_CONFIG" ingress l7_router_uuid "$lb_uuid"

    #in case tempest enabled, update router's FIP in tempest.conf
    if is_service_enabled tempest; then
       iniset $TEMPEST_CONFIG kuryr_kubernetes ocp_router_fip "$l7_router_fip"
    fi

    if is_service_enabled octavia; then
        echo -n "Octavia: no need to create fake k8s service for Ingress."
    else
        # keep fake an endpoint less k8s service to keep Kubernetes API server
        # from allocating ingress LB vip
        fake_svc_name='kuryr-svc-ingress'
        echo -n "LBaaS: create fake k8s service: $fake_svc_name for Ingress."
        lb_vip="$(get_loadbalancer_attribute "$lb_name" "vip_address")"
        create_k8s_fake_service $fake_svc_name $lb_vip
    fi
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
    openstack --os-cloud devstack-admin --os-region "$REGION_NAME" \
        security group rule create --project "$project_id" \
        --dst-port "$dst_port" "$security_group"
    openstack port set "$KURYR_OVERCLOUD_VM_PORT" --security-group service_pod_access
}

function update_tempest_conf_file {

    if [[ "$KURYR_USE_PORT_POOLS" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes port_pool_enabled True
    fi
    if [[ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes containerized True
    fi
    if [[ "$KURYR_SG_DRIVER" == "namespace" ]] && [[ "$KURYR_SUBNET_DRIVER" == "namespace" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes namespace_enabled True
    fi
    if [[ "$KURYR_K8S_SERIAL_TESTS" == "True" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes run_tests_serial True
    fi
    if [[ "$KURYR_MULTI_VIF_DRIVER" == "npwg_multiple_interfaces" ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes npwg_multi_vif_enabled True
    fi
    if [[ "$KURYR_ENABLED_HANDLERS" =~ .*policy.* ]]; then
        iniset $TEMPEST_CONFIG kuryr_kubernetes network_policy_enabled True
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
    iniset $TEMPEST_CONFIG kuryr_kubernetes validate_crd True
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
                                     subnet show "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET" \
                                     -c cidr -f value)
            k8s_api_clusterip=$(_cidr_range "$service_cidr" | cut -f1)
            # NOTE(mrostecki): KURYR_K8S_API_ROOT will be a global to be used by next
            #                  deployment phases.
            KURYR_K8S_API_ROOT=${KURYR_K8S_API_URL}
            if is_service_enabled octavia; then
                KURYR_K8S_API_ROOT="https://${k8s_api_clusterip}:${KURYR_K8S_API_LB_PORT}"
            fi
            iniset "$KURYR_CONFIG" kubernetes api_root ${KURYR_K8S_API_ROOT}
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

    if is_service_enabled kubernetes-api \
       || is_service_enabled kubernetes-controller-manager \
       || is_service_enabled kubernetes-scheduler \
       || is_service_enabled kubelet; then
        get_container "$KURYR_HYPERKUBE_IMAGE" "$KURYR_HYPERKUBE_VERSION"
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
        extract_hyperkube
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
        /usr/local/bin/kubectl apply -f ${KURYR_HOME}/kubernetes_crds/kuryrnet.yaml
        /usr/local/bin/kubectl apply -f ${KURYR_HOME}/kubernetes_crds/kuryrnetpolicy.yaml
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
            #create Ingress L7 router if required
            enable_ingress=$(trueorfalse False KURYR_ENABLE_INGRESS)

            if [ "$enable_ingress" == "True" ]; then
                create_ingress_l7_router
            fi
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
            #Open port 53 so pods can reach the DNS server
            sudo iptables -I INPUT 1 -p udp -m udp --dport 53 -j ACCEPT

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
            $KURYR_HYPERKUBE_BINARY kubectl delete deploy/kuryr-controller
        fi
        stop_process kuryr-kubernetes
    elif is_service_enabled kubelet; then
         $KURYR_HYPERKUBE_BINARY kubectl delete nodes ${HOSTNAME}
    fi
    if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]; then
        $KURYR_HYPERKUBE_BINARY kubectl delete ds/kuryr-cni-ds
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
