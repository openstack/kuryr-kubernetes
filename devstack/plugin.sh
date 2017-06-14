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

    create_kuryr_cache_dir

    # Neutron API server & Neutron plugin
    if is_service_enabled kuryr-kubernetes; then
        configure_auth_token_middleware "$KURYR_CONFIG" kuryr \
        "$KURYR_AUTH_CACHE_DIR" neutron
    fi
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

function create_k8s_router_fake_service {
    local service_cidr
    local router_ip
    local existing_svc_ip
    local fake_svc_name

    fake_svc_name='kuryr-svc-router'
    service_cidr=$(openstack --os-cloud devstack-admin \
                             --os-region "$REGION_NAME" \
                             subnet show "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET" \
                             -c cidr -f value)
    router_ip=$(_cidr_range "$service_cidr" | cut -f2)
    existing_svc_ip=$(/usr/local/bin/kubectl get svc --namespace kube-system -o jsonpath='{.items[?(@.metadata.name=='"\"${fake_svc_name}\""')].spec.clusterIP}')

    if [[ "$existing_svc_ip" == "" ]]; then
        # Create fake router service so the router clusterIP can't be reassigned
        cat <<EOF | /usr/local/bin/kubectl create -f -
kind: Service
apiVersion: v1
metadata:
  name: "${fake_svc_name}"
  namespace: kube-system
spec:
  type: ClusterIP
  clusterIP: "${router_ip}"
  ports:
    - protocol: TCP
      port: 80
EOF
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
    neutron lbaas-member-create  --subnet public-subnet \
        --address "${HOST_IP}" \
        --protocol-port 6443 \
        default/kubernetes:443
}

function create_k8s_service_subnet {
    # REVISIT(ivc): add support for IPv6
    # REVISIT(apuimedo): Move this into a tool that can be used on deployments
    #                    and make use of it here.
    local project_id=$1
    local subnet_params="--project $project_id "

    if [ -z $SUBNETPOOL_V4_ID ]; then
        local service_cidr=$KURYR_K8S_CLUSTER_IP_RANGE
    fi

    subnet_params+="--ip-version 4 "
    subnet_params+="--no-dhcp --gateway none "
    subnet_params+="${SUBNETPOOL_V4_ID:+--subnet-pool $SUBNETPOOL_V4_ID} "
    subnet_params+="${service_cidr:+--subnet-range $service_cidr} "
    subnet_params+="--network $NET_ID $KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET"

    local subnet_id
    subnet_id=$(openstack --os-cloud devstack-admin \
                          --os-region "$REGION_NAME" \
                          subnet create $subnet_params \
                          -c id -f value)
    die_if_not_set $LINENO subnet_id \
        "Failure creating K8s service IPv4 subnet for $project_id"

    service_cidr=$(openstack --os-cloud devstack-admin \
                             --os-region "$REGION_NAME" \
                             subnet show $subnet_id \
                             -c cidr -f value)
    die_if_not_set $LINENO service_cidr \
        "Failure creating K8s service IPv4 subnet for $project_id"
    # REVISIT(ivc): consider adding a note to 'settings'
    # KURYR_K8S_CLUSTER_IP_RANGE from 'settings' is only used if no
    # SUBNETPOOL_V4_ID is defined and otherwise it is rewritten with a
    # generated CIDR from SUBNETPOOL_V4_ID.
    KURYR_K8S_CLUSTER_IP_RANGE=$service_cidr

    # REVISIT(ivc): look for a better solution to deal with K8s IPAM
    # K8s has its own IPAM for services. It also allocates the first IP from
    # service subnet CIDR to Kubernetes apiserver.
    # To deal with it we set gateway's IP to the the last IP from subnet's
    # IP range and Kuryr's K8s service handler will ignore services with
    # gateway's IP.
    local router_ip=$(_cidr_range "$service_cidr" | cut -f2)
    die_if_not_set $LINENO router_ip \
        "Failed to determine K8s service subnet router IP"
    openstack --os-cloud devstack-admin \
              --os-region "$REGION_NAME" subnet set \
              --gateway "$router_ip" \
              --no-allocation-pool \
              $subnet_id \
              || die $LINENO "Failed to update K8s service subnet"
    openstack --os-cloud devstack-admin \
              --os-region "$REGION_NAME" \
              router add subnet $ROUTER_ID $subnet_id \
              || die $LINENO "Failed to enable routing for K8s service subnet"

    KURYR_K8S_SERVICE_SUBNET_ID=$subnet_id
}

function configure_neutron_defaults {
    local project_id=$(get_or_create_project \
        "$KURYR_NEUTRON_DEFAULT_PROJECT" default)
    local pod_subnet_id=$(neutron subnet-show -c id -f value \
        "$KURYR_NEUTRON_DEFAULT_POD_SUBNET")
    local sg_ids=$(echo $(neutron security-group-list \
        --project-id "$project_id" -c id -f value) | tr ' ' ',')

    create_k8s_service_subnet $project_id
    local service_subnet_id=$KURYR_K8S_SERVICE_SUBNET_ID

    iniset "$KURYR_CONFIG" neutron_defaults project "$project_id"
    iniset "$KURYR_CONFIG" neutron_defaults pod_subnet "$pod_subnet_id"
    iniset "$KURYR_CONFIG" neutron_defaults pod_security_groups "$sg_ids"
    iniset "$KURYR_CONFIG" neutron_defaults service_subnet "$service_subnet_id"
    if [ -n "$OVS_BRIDGE" ]; then
        iniset "$KURYR_CONFIG" neutron_defaults ovs_bridge "$OVS_BRIDGE"
    fi
}

function check_docker {
    if is_ubuntu; then
       dpkg -s docker-engine > /dev/null 2>&1
    else
       rpm -q docker-engine > /dev/null 2>&1 || rpm -q docker > /dev/null 2>&1
    fi
}

function prepare_docker {
    curl -L http://get.docker.com | sudo bash
}

function run_docker {
    local dockerd_bin=$(which dockerd)

    if [[ "$USE_SYSTEMD" = "True" ]]; then
        # If systemd is being used, proceed as normal
        run_process docker \
            "$dockerd_bin --debug=true \
                -H unix://$KURYR_DOCKER_ENGINE_SOCKET_FILE" "root" "root"
    else
        # If screen is being used, there is a possibility that the devstack
        # environment is on a stable branch. Older versions of run_process have
        # a different signature. Sudo is used as a workaround that works in
        # both older and newer versions of devstack.
        run_process docker \
           "sudo $dockerd_bin --debug=true \
               -H unix://$KURYR_DOCKER_ENGINE_SOCKET_FILE"
    fi

    # We put the stack user as owner of the socket so we do not need to
    # run the Docker commands with sudo when developing.
    echo -n "Waiting for Docker to create its socket file"
    while [ ! -e "$KURYR_DOCKER_ENGINE_SOCKET_FILE" ]; do
        echo -n "."
        sleep 1
    done
    echo ""
    sudo chown "$STACK_USER":docker "$KURYR_DOCKER_ENGINE_SOCKET_FILE"
}

function stop_docker {
    stop_process docker

    # Stop process does not handle well Docker 1.12+ new multi process
    # split and doesn't kill them all. Let's leverage Docker's own pidfile
    local DOCKER_PIDFILE="/var/run/docker.pid"
    if [ -f "$DOCKER_PIDFILE" ]; then
        echo "Killing docker"
        sudo kill -s SIGTERM "$(cat "$DOCKER_PIDFILE")"
    fi
    while [ -e "$DOCKER_PIDFILE" ]; do
        echo -n "."
        sleep 1
    done
    if [ -e "$KURYR_DOCKER_ENGINE_SOCKET_FILE" ]; then
        sudo rm "$KURYR_DOCKER_ENGINE_SOCKET_FILE"
    fi
}

function get_hyperkube_container_cacert_setup_dir {
    case "$1" in
        1.[0-3].*) echo "/data";;
        *) echo "/srv/kubernetes"
    esac
}

function prepare_kubernetes_files {
    # Sets up the base configuration for the Kubernetes API Server and the
    # Controller Manager.
    local mountpoint
    local service_cidr
    local k8s_api_clusterip

    service_cidr=$(openstack --os-cloud devstack-admin \
                             --os-region "$REGION_NAME" \
                             subnet show "$KURYR_NEUTRON_DEFAULT_SERVICE_SUBNET"\
                             -c cidr -f value)
    k8s_api_clusterip=$(_cidr_range "$service_cidr" | cut -f1)
    mountpoint=$(get_hyperkube_container_cacert_setup_dir "$KURYR_HYPERKUBE_VERSION")

    docker run \
        --name devstack-k8s-setup-files \
        --detach \
        --volume "${KURYR_HYPERKUBE_DATA_DIR}:${mountpoint}:rw" \
        "${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}" \
            /setup-files.sh \
            "IP:${HOST_IP},IP:${k8s_api_clusterip},DNS:kubernetes,DNS:kubernetes.default,DNS:kubernetes.default.svc,DNS:kubernetes.default.svc.cluster.local"

    # FIXME(ivc): replace 'sleep' with a strict check (e.g. wait_for_files)
    # 'kubernetes-api' fails if started before files are generated.
    # this is a workaround to prevent races.
    sleep 5
}

function wait_for {
    local name
    local url
    name="$1"
    url="$2"

    echo -n "Waiting for $name to respond"

    until curl -o /dev/null -sIf "$url"; do
        echo -n "."
        sleep 1
    done
    echo ""
}

function run_k8s_api {
    # Runs Hyperkube's Kubernetes API Server
    wait_for "etcd" "${KURYR_ETCD_ADVERTISE_CLIENT_URL}/v2/machines"

    run_container kubernetes-api \
        --net host \
        --volume="${KURYR_HYPERKUBE_DATA_DIR}:/srv/kubernetes:rw" \
        "${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}" \
            /hyperkube apiserver \
                --service-cluster-ip-range="${KURYR_K8S_CLUSTER_IP_RANGE}" \
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
        --server=http://localhost:8080
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

    hyperkube_container="$(docker ps -aq \
        -f ancestor="${KURYR_HYPERKUBE_IMAGE}:${KURYR_HYPERKUBE_VERSION}" | \
        head -1)"
    docker cp "${hyperkube_container}:/hyperkube" "$tmp_hyperkube_path"
    docker cp "${hyperkube_container}:/opt/cni/bin/loopback" \
        "$tmp_loopback_cni_path"
    docker cp "${hyperkube_container}:/usr/bin/nsenter" "$tmp_nsenter_path"
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
    sudo install -o "$STACK_USER" -m 0664 -D \
        "${KURYR_HOME}${kubelet_plugin_dir}/99-loopback.conf" \
        "${CNI_CONF_DIR}/99-loopback.conf"
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
        --allow-privileged=true \
        --api-servers=$KURYR_K8S_API_URL \
        --v=2 \
        --address=0.0.0.0 \
        --enable-server \
        --network-plugin=cni \
        --cni-bin-dir=$CNI_BIN_DIR \
        --cni-conf-dir=$CNI_CONF_DIR \
        --cert-dir=${KURYR_HYPERKUBE_DATA_DIR}/kubelet.cert \
        --root-dir=${KURYR_HYPERKUBE_DATA_DIR}/kubelet"
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
    wait_for "Kubernetes API Server" "$KURYR_K8S_API_URL"
    run_process kuryr-kubernetes \
        "$python_bin ${KURYR_HOME}/scripts/run_server.py  \
            --config-file $KURYR_CONFIG"
}


source $DEST/kuryr-kubernetes/devstack/lib/kuryr_kubernetes

# main loop
if is_service_enabled kuryr-kubernetes; then
    if [[ "$1" == "stack" && "$2" == "install" ]]; then
        setup_develop "$KURYR_HOME"
        if is_service_enabled kubelet; then
            install_kuryr_cni
        fi

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        create_kuryr_account
        configure_kuryr
    fi

    if [[ "$1" == "stack" && "$2" == "extra" ]]; then
        KURYR_CONFIGURE_NEUTRON_DEFAULTS=$(trueorfalse True KURYR_CONFIGURE_NEUTRON_DEFAULTS)
        if [ "$KURYR_CONFIGURE_NEUTRON_DEFAULTS" == "True" ]; then
            configure_neutron_defaults
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

        if is_service_enabled docker; then
            check_docker || prepare_docker
            stop_docker
            run_docker
        fi

        if is_service_enabled legacy_etcd; then
            prepare_etcd_legacy
            run_etcd_legacy
        fi

        get_container "$KURYR_HYPERKUBE_IMAGE" "$KURYR_HYPERKUBE_VERSION"
        prepare_kubernetes_files
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
                ovs_bind_for_kubelet "$KURYR_NEUTRON_DEFAULT_PROJECT"
            fi
        fi

        run_kuryr_kubernetes

    elif [[ "$1" == "stack" && "$2" == "test-config" ]]; then
        create_k8s_router_fake_service
        create_k8s_api_service
    fi

    if [[ "$1" == "unstack" ]]; then
        stop_process kuryr-kubernetes
        docker kill devstack-k8s-setup-files
        docker rm devstack-k8s-setup-files

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
        if is_service_enabled legacy_etcd; then
            stop_container etcd
        fi

        stop_docker
    fi

    if [[ "$1" == "clean" ]]; then
        if is_service_enabled legacy_etcd; then
            # Cleanup Etcd for the next stacking
            sudo rm -rf "$KURYR_ETCD_DATA_DIR"
        fi
    fi
fi
