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

function get_distutils_data_path {
    cat << EOF | python -
from __future__ import print_function
import distutils.dist
import distutils.command.install

inst = distutils.command.install.install(distutils.dist.Distribution())
inst.finalize_options()

print(inst.install_data)
EOF
}

function configure_kuryr {
    local dir
    sudo install -d -o "$STACK_USER" "$KURYR_CONFIG_DIR"
    "${KURYR_HOME}/tools/generate_config_file_samples.sh"
    sudo install -o "$STACK_USER" -m 640 -D "${KURYR_HOME}/etc/kuryr.conf.sample" \
        "$KURYR_CONFIG"

    iniset "$KURYR_CONFIG" kubernetes api_root "$KURYR_K8S_API_URL"
    if [ "$KURYR_K8S_API_CERT" ]; then
        iniset "$KURYR_CONFIG" kubernetes ssl_client_crt_file "$KURYR_K8S_API_CERT"
    fi
    if [ "$KURYR_K8S_API_KEY" ]; then
        iniset "$KURYR_CONFIG" kubernetes ssl_client_key_file "$KURYR_K8S_API_KEY"
    fi
    if [ "$KURYR_K8S_API_CACERT" ]; then
        iniset "$KURYR_CONFIG" kubernetes ssl_ca_crt_file "$KURYR_K8S_API_CACERT"
    fi
    # REVISIT(ivc): 'use_stderr' is required for current CNI driver. Once a
    # daemon-based CNI driver is implemented, this could be removed.
    iniset "$KURYR_CONFIG" DEFAULT use_stderr true

    iniset "$KURYR_CONFIG" DEFAULT debug "$ENABLE_DEBUG_LOG_LEVEL"

    iniset "$KURYR_CONFIG" kubernetes port_debug "$KURYR_PORT_DEBUG"

    KURYR_K8S_CONTAINERIZED_DEPLOYMENT=$(trueorfalse False KURYR_K8S_CONTAINERIZED_DEPLOYMENT)
    if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]; then
        # This works around the issue of being unable to set oslo.privsep mode
        # to FORK in os-vif. When running in a container we disable `sudo` that
        # was prefixed before `privsep-helper` command. This let's us run in
        # envs without sudo and keep the same python environment as the parent
        # process.
        iniset "$KURYR_CONFIG" vif_plug_ovs_privileged helper_command privsep-helper
        iniset "$KURYR_CONFIG" vif_plug_linux_bridge_privileged helper_command privsep-helper
    fi

    if is_service_enabled kuryr-daemon; then
        iniset "$KURYR_CONFIG" cni_daemon daemon_enabled True
        iniset "$KURYR_CONFIG" oslo_concurrency lock_path "$KURYR_LOCK_DIR"
        create_kuryr_lock_dir
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "True" ]; then
            # When running kuryr-daemon in container we need to set up some
            # configs.
            iniset "$KURYR_CONFIG" cni_daemon docker_mode True
            iniset "$KURYR_CONFIG" cni_daemon netns_proc_dir "/host_proc"
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
    # Containerized deployment will use tokens provided by k8s itself.
    inicomment "$KURYR_CONFIG" kubernetes ssl_client_crt_file
    inicomment "$KURYR_CONFIG" kubernetes ssl_client_key_file

    # kuryr-controller and kuryr-cni will have tokens in different dirs.
    KURYR_CNI_CONFIG=${KURYR_CONFIG}-cni
    cp $KURYR_CONFIG $KURYR_CNI_CONFIG
    iniset "$KURYR_CONFIG" kubernetes token_file /var/run/secrets/kubernetes.io/serviceaccount/token
    iniset "$KURYR_CONFIG" kubernetes ssl_ca_crt_file /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    iniset "$KURYR_CNI_CONFIG" kubernetes token_file /etc/kuryr/token
    iniset "$KURYR_CNI_CONFIG" kubernetes ssl_ca_crt_file /etc/kuryr/ca.crt

    # Generate kuryr resources in k8s formats.
    local output_dir="${DATA_DIR}/kuryr-kubernetes"
    generate_kuryr_configmap $output_dir $KURYR_CONFIG $KURYR_CNI_CONFIG
    generate_kuryr_service_account $output_dir
    generate_controller_deployment $output_dir $KURYR_HEALTH_SERVER_PORT
    generate_cni_daemon_set $output_dir $CNI_BIN_DIR $CNI_CONF_DIR
}

function run_containerized_kuryr_resources {
    local k8s_data_dir="${DATA_DIR}/kuryr-kubernetes"
    /usr/local/bin/kubectl create -f \
        "${k8s_data_dir}/config_map.yml" \
        || die $LINENO "Failed to create kuryr-kubernetes ConfigMap."
    /usr/local/bin/kubectl create -f \
        "${k8s_data_dir}/service_account.yml" \
        || die $LINENO "Failed to create kuryr-kubernetes ServiceAccount."
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
        sudo cp "${OPENSHIFT_DATA_DIR}/admin.kubeconfig" "${HOME}/.kube/config"
        sudo chown -R $STACK_USER "${HOME}/.kube"
    fi

    if [ -d "$tempest_home" ]; then
        sudo cp -r "${HOME}/.kube" "$tempest_home"
        sudo chown -R tempest "${tempest_home}/.kube"
    fi
}

function _lb_state {
    # Checks Neutron lbaas for the Load balancer state
    neutron lbaas-loadbalancer-show "$1" | awk '/provisioning_status/ {print $4}'
}

function create_k8s_api_service {
    # This allows pods that need access to kubernetes API (like the
    # containerized kuryr controller or kube-dns) to talk to the K8s API
    # service
    local service_cidr
    local router_ip
    local lb_name

    lb_name='default/kubernetes'
    service_cidr=$(openstack --os-cloud devstack-admin \
                             --os-region "$REGION_NAME" \
                             subnet show "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET" \
                             -c cidr -f value)

    k8s_api_clusterip=$(_cidr_range "$service_cidr" | cut -f1)

    neutron lbaas-loadbalancer-create --name "$lb_name" \
        --vip-address "$k8s_api_clusterip" \
        "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET"

    # Octavia needs the LB to be active for the listener
    while [[ "$(_lb_state $lb_name)" != "ACTIVE" ]]; do
        sleep 1
    done

    neutron lbaas-listener-create --loadbalancer "$lb_name" \
        --name default/kubernetes:443 \
        --protocol HTTPS \
        --protocol-port 443

    # We must wait for the LB to be active before we can put a Pool for it
    while [[ "$(_lb_state $lb_name)" != "ACTIVE" ]]; do
        sleep 1
    done

    neutron lbaas-pool-create --loadbalancer "$lb_name" \
        --name default/kubernetes:443 \
        --listener default/kubernetes:443 \
        --protocol HTTPS \
        --lb-algorithm ROUND_ROBIN
    # We must wait for the pending pool creation update
    while [[ "$(_lb_state $lb_name)" != "ACTIVE" ]]; do
        sleep 1
    done
    if is_service_enabled openshift-master; then
        neutron lbaas-member-create  --subnet public-subnet \
            --address "${HOST_IP}" \
            --protocol-port 8443 \
            default/kubernetes:443
    else
        neutron lbaas-member-create  --subnet public-subnet \
            --address "${HOST_IP}" \
            --protocol-port 6443 \
            default/kubernetes:443
    fi
}

function configure_neutron_defaults {
    local project_id
    local pod_subnet_id
    local sg_ids
    local service_subnet_id
    local subnetpool_id
    local router

    # If a subnetpool is not passed, we get the one created in devstack's
    # Neutron module
    subnetpool_id=${KURYR_NEUTRON_DEFAULT_SUBNETPOOL_ID:-${SUBNETPOOL_V4_ID}}
    router=${KURYR_NEUTRON_DEFAULT_ROUTER:-$Q_ROUTER_NAME}

    project_id=$(get_or_create_project \
        "$KURYR_NEUTRON_DEFAULT_PROJECT" default)
    create_k8s_subnet "$project_id" \
                      "$KURYR_NEUTRON_DEFAULT_POD_NET" \
                      "$KURYR_NEUTRON_DEFAULT_POD_SUBNET" \
                      "$subnetpool_id" \
                      "$router"
    pod_subnet_id="$(neutron subnet-show -c id -f value \
        "${KURYR_NEUTRON_DEFAULT_POD_SUBNET}")"

    create_k8s_subnet "$project_id" \
                      "$KURYR_NEUTRON_DEFAULT_SERVICE_NET" \
                      "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET" \
                      "$subnetpool_id" \
                      "$router"
    service_subnet_id="$(neutron subnet-show -c id -f value \
        "${KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET}")"

    sg_ids=$(echo $(neutron security-group-list \
        --project-id "$project_id" -c id -f value) | tr ' ' ',')

    ext_svc_subnet_id="$(neutron subnet-show -c id -f value \
        "${KURYR_NEUTRON_DEFAULT_EXT_SVC_SUBNET}")"

    local use_octavia
    use_octavia=$(trueorfalse True KURYR_K8S_LBAAS_USE_OCTAVIA)
    if [[ "$use_octavia" == "True" && \
          "$KURYR_K8S_OCTAVIA_MEMBER_MODE" == "L3" ]]; then
        # In order for the pods to allow service traffic under Octavia L3 mode,
        #it is necessary for the service subnet to be allowed into the $sg_ids
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
        sg_ids+=",${service_pod_access_sg_id}"
    elif [[ "$use_octavia" == "True" && \
            "$KURYR_K8S_OCTAVIA_MEMBER_MODE" == "L2" ]]; then
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
        sg_ids+=",${octavia_pod_access_sg_id}"
    fi

    iniset "$KURYR_CONFIG" neutron_defaults project "$project_id"
    iniset "$KURYR_CONFIG" neutron_defaults pod_subnet "$pod_subnet_id"
    iniset "$KURYR_CONFIG" neutron_defaults pod_security_groups "$sg_ids"
    iniset "$KURYR_CONFIG" neutron_defaults service_subnet "$service_subnet_id"
    if [ -n "$OVS_BRIDGE" ]; then
        iniset "$KURYR_CONFIG" neutron_defaults ovs_bridge "$OVS_BRIDGE"
    fi
    iniset "$KURYR_CONFIG" neutron_defaults external_svc_subnet "$ext_svc_subnet_id"
    iniset "$KURYR_CONFIG" octavia_defaults member_mode "$KURYR_K8S_OCTAVIA_MEMBER_MODE"
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
                      awk '/default/ {print $1}')
    create_k8s_icmp_sg_rules "$sg_id" ingress
}

function get_hyperkube_container_cacert_setup_dir {
    case "$1" in
        1.[0-3].*) echo "/data";;
        *) echo "/srv/kubernetes"
    esac
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

    echo -n "Waiting for $name to respond"

    if [ $# == 3 ]; then
        extra_flags="--cacert ${cacert_path}"
    else
        extra_flags=""
    fi

    until curl -o /dev/null -sIf $extra_flags "$url"; do
        echo -n "."
        sleep 1
    done
    echo ""
}

function run_k8s_api {
    local cluster_ip_range

    # Runs Hyperkube's Kubernetes API Server
    wait_for "etcd" "${KURYR_ETCD_ADVERTISE_CLIENT_URL}/v2/machines"

    cluster_ip_range=$(openstack --os-cloud devstack-admin \
                         --os-region "$REGION_NAME" \
                         subnet show "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET" \
                         -c cidr -f value)

    run_container kubernetes-api \
        --net host \
        --volume="${KURYR_HYPERKUBE_DATA_DIR}:/srv/kubernetes:rw" \
        "${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}" \
            /hyperkube apiserver \
                --service-cluster-ip-range="${cluster_ip_range}" \
                --insecure-bind-address=0.0.0.0 \
                --insecure-port="${KURYR_K8S_API_PORT}" \
                --etcd-servers="${KURYR_ETCD_ADVERTISE_CLIENT_URL}" \
                --admission-control=NamespaceLifecycle,LimitRanger,ServiceAccount,ResourceQuota \
                --client-ca-file=/srv/kubernetes/ca.crt \
                --basic-auth-file=/srv/kubernetes/basic_auth.csv \
                --min-request-timeout=300 \
                --tls-cert-file=/srv/kubernetes/server.cert \
                --tls-private-key-file=/srv/kubernetes/server.key \
                --token-auth-file=/srv/kubernetes/known_tokens.csv \
                --allow-privileged=true \
                --v=2 \
                --logtostderr=true
}

function run_k8s_controller_manager {
    # Runs Hyperkube's Kubernetes controller manager
    wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"

    run_container kubernetes-controller-manager \
        --net host \
        --volume="${KURYR_HYPERKUBE_DATA_DIR}:/srv/kubernetes:rw" \
        "${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}" \
            /hyperkube controller-manager \
                --master="$KURYR_K8S_API_URL" \
                --service-account-private-key-file=/srv/kubernetes/server.key \
                --root-ca-file=/srv/kubernetes/ca.crt \
                --min-resync-period=3m \
                --v=2 \
                --logtostderr=true
}

function run_k8s_scheduler {
    # Runs Hyperkube's Kubernetes scheduler
    wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"

    run_container kubernetes-scheduler \
        --net host \
        --volume="${KURYR_HYPERKUBE_DATA_DIR}:/srv/kubernetes:rw" \
        "${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}" \
            /hyperkube scheduler \
                --master="$KURYR_K8S_API_URL" \
                --v=2 \
                --logtostderr=true
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

    hyperkube_container=$(docker run -d \
        --net host \
       "${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}" \
       /bin/false)
    docker cp "${hyperkube_container}:/hyperkube" "$tmp_hyperkube_path"
    docker cp "${hyperkube_container}:/opt/cni/bin/loopback" \
        "$tmp_loopback_cni_path"
    docker cp "${hyperkube_container}:/usr/bin/nsenter" "$tmp_nsenter_path"

    docker rm "$hyperkube_container"
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

    sudo mkdir -p "${KURYR_HYPERKUBE_DATA_DIR}/"{kubelet,kubelet.cert}
    command="$KURYR_HYPERKUBE_BINARY kubelet\
        --kubeconfig=${HOME}/.kube/config --require-kubeconfig \
        --allow-privileged=true \
        --v=2 \
        --address=0.0.0.0 \
        --enable-server \
        --network-plugin=cni \
        --cni-bin-dir=$CNI_BIN_DIR \
        --cni-conf-dir=$CNI_CONF_DIR \
        --cert-dir=${KURYR_HYPERKUBE_DATA_DIR}/kubelet.cert \
        --root-dir=${KURYR_HYPERKUBE_DATA_DIR}/kubelet"

    # Kubernetes 1.8 requires additional option to work in the gate.
    if [[ ${KURYR_HYPERKUBE_VERSION} == v1.8* ]]; then
        command="$command --fail-swap-on=false"
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

function run_kuryr_kubernetes {
    local python_bin=$(which python)

    if is_service_enabled openshift-master; then
        wait_for "OpenShift API Server" "$OPENSHIFT_API_URL" \
            "${OPENSHIFT_DATA_DIR}/ca.crt"
    else
        wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"
    fi
    run_process kuryr-kubernetes \
        "$python_bin ${KURYR_HOME}/scripts/run_server.py  \
            --config-file $KURYR_CONFIG"
}


function run_kuryr_daemon {
    local daemon_bin=$(which kuryr-daemon)
    run_process kuryr-daemon "$daemon_bin --config-file $KURYR_CONFIG" root root
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
    if is_service_enabled kuryr-kubernetes; then
        create_kuryr_account
    fi
    configure_kuryr
fi

if [[ "$1" == "stack" && "$2" == "extra" ]]; then
    if is_service_enabled kuryr-kubernetes; then
        KURYR_CONFIGURE_NEUTRON_DEFAULTS=$(trueorfalse True KURYR_CONFIGURE_NEUTRON_DEFAULTS)
        if [ "$KURYR_CONFIGURE_NEUTRON_DEFAULTS" == "True" ]; then
            configure_neutron_defaults
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

    if is_service_enabled legacy_etcd; then
        prepare_etcd_legacy
        run_etcd_legacy
    fi

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

    KURYR_K8S_CONTAINERIZED_DEPLOYMENT=$(trueorfalse False KURYR_K8S_CONTAINERIZED_DEPLOYMENT)
    if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "False" ]; then
        # If running in containerized mode, we'll run the daemon as DaemonSet.
        run_kuryr_daemon
    fi

    if is_service_enabled kubelet; then
        prepare_kubelet
        extract_hyperkube
        prepare_kubeconfig
        run_k8s_kubelet
        KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE=$(trueorfalse True KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE)
        if [[ "$KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE" == "True" ]]; then
            ovs_bind_for_kubelet "$KURYR_NEUTRON_DEFAULT_PROJECT"
        fi
    fi

    if is_service_enabled tempest; then
        copy_tempest_kubeconfig
        configure_k8s_pod_sg_rules
    fi

    if is_service_enabled kuryr-kubernetes; then
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "False" ]; then
            run_kuryr_kubernetes
        else
            if is_service_enabled kuryr-daemon; then
                build_kuryr_containers $CNI_BIN_DIR $CNI_CONF_DIR True
            else
                build_kuryr_containers $CNI_BIN_DIR $CNI_CONF_DIR False
            fi
            generate_containerized_kuryr_resources
            run_containerized_kuryr_resources
        fi
    fi

elif [[ "$1" == "stack" && "$2" == "test-config" ]]; then
    if is_service_enabled kuryr-kubernetes; then
        create_k8s_router_fake_service
        create_k8s_api_service
    fi
fi

if [[ "$1" == "unstack" ]]; then
    KURYR_K8S_CONTAINERIZED_DEPLOYMENT=$(trueorfalse False KURYR_K8S_CONTAINERIZED_DEPLOYMENT)
    if is_service_enabled kuryr-kubernetes; then
        if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "False" ]; then
            stop_process kuryr-kubernetes
        else
            $KURYR_HYPERKUBE_BINARY kubectl delete deploy/kuryr-controller
        fi
    elif is_service_enabled kubelet; then
         $KURYR_HYPERKUBE_BINARY kubectl delete nodes ${HOSTNAME}
    fi
    if [ "$KURYR_K8S_CONTAINERIZED_DEPLOYMENT" == "False" ]; then
        stop_process kuryr-daemon
    else
        $KURYR_HYPERKUBE_BINARY kubectl delete ds/kuryr-cni-ds
    fi

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
    fi
    if is_service_enabled legacy_etcd; then
        stop_container etcd
    fi
fi

if [[ "$1" == "clean" ]]; then
    if is_service_enabled legacy_etcd; then
        # Cleanup Etcd for the next stacking
        sudo rm -rf "$KURYR_ETCD_DATA_DIR"
    fi
fi
