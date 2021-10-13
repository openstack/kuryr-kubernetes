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

KURYR_CONT=$(trueorfalse False KURYR_K8S_CONTAINERIZED_DEPLOYMENT)
KURYR_OVS_BM=$(trueorfalse True KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE)


source $DEST/kuryr-kubernetes/devstack/lib/kuryr_kubernetes
source $DEST/kuryr-kubernetes/devstack/lib/kubernetes


if is_service_enabled kuryr-kubernetes kuryr-daemon \
    kuryr-kubernetes-worker; then
    # There are four services provided by this plugin.
    #
    # Those two are needed for non-containerized deployment, otherwise,
    # run_process will not create systemd units thus run the service. For
    # containerized one, kuryr-daemon can be omitted, but you'll still need
    # kuryr-kubernetes to be able to install and run kuryr/k8s bits.
    #
    # * kuryr-kubernetes (no change from former version)
    # * kuryr-daemon (no change from former version)
    #
    # Those are new one, and differentiate between kubernetes master node and
    # worker node:
    #
    # * kubernetes-master (former: kubernetes-api, kubernetes-scheduler,
    #   kubernetes-controller-manager, kubelet)
    # * kubernetes-worker (former: kubelet)
    #
    # There were openshift-* services removed, since they are not working
    # anymore.

    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        echo_summary "Installing dependecies for Kuryr-Kubernetes"
        if is_service_enabled kubernetes-master kubernetes-worker; then
            kubeadm_install
        fi

    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing kuryr CNI and Controller"
        setup_develop "$KURYR_HOME"
        if [[ "${KURYR_CONT}" == "False" ]]; then
            # Build CNI only for non-containerized deployment. For
            # containerized CNI will be built within the images build.
            build_install_kuryr_cni
        fi

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Configure kuryr bits"
        if is_service_enabled kuryr-daemon; then
            create_kuryr_account
            configure_kuryr
        fi

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Installing kubernetes and kuryr"
        # Initialize and start the template service
        if is_service_enabled kuryr-kubernetes; then
            configure_neutron_defaults
        fi

        if is_service_enabled kubernetes-master kubernetes-worker; then
            prepare_kubelet
        fi

        if is_service_enabled kubernetes-master; then
            wait_for "etcd" "http://${SERVICE_HOST}:${ETCD_PORT}/v2/machines"
            kubeadm_init
            copy_kuryr_certs
        elif is_service_enabled kubernetes-worker; then
            kubeadm_join
        fi

        if [ "${KURYR_CONT}" == "True" ]; then
            if is_service_enabled kubernetes-master; then
                build_kuryr_container_image "controller"
                build_kuryr_container_image "cni"
            else
                build_kuryr_container_image "cni"
            fi
        fi

        if is_service_enabled kubernetes-master; then
            # don't alter kubernetes config
            # prepare_kubeconfig
            prepare_kubernetes_files
        fi

        if is_service_enabled kubernetes-master kubernetes-worker; then
            if [[ "${KURYR_OVS_BM}" == "True" ]]; then
                ovs_bind_for_kubelet "$KURYR_NEUTRON_DEFAULT_PROJECT" 6443
            else
                configure_overcloud_vm_k8s_svc_sg
            fi
        fi

        if is_service_enabled tempest; then
            copy_tempest_kubeconfig
            configure_k8s_pod_sg_rules
        fi

        if is_service_enabled kuryr-kubernetes; then
            kubectl apply -f ${KURYR_HOME}/kubernetes_crds/kuryr_crds/
            if [[ "${KURYR_CONT}" == "True" ]]; then
                _generate_containerized_kuryr_resources
            fi
            if [ "$KURYR_MULTI_VIF_DRIVER" == "npwg_multiple_interfaces" ]; then
                kubectl apply -f ${KURYR_HOME}/kubernetes_crds/network_attachment_definition_crd.yaml
            fi
        fi

    elif [[ "$1" == "stack" && "$2" == "test-config" ]]; then
        echo_summary "Run kuryr-kubernetes"
        if is_service_enabled kuryr-kubernetes; then
            if is_service_enabled octavia; then
                create_lb_for_services
            fi

            # FIXME(dulek): This is a very late phase to start Kuryr services.
            # We're doing it here because we need K8s API LB to be created in
            # order to run kuryr services. Thing is Octavia is unable to
            # create LB until test-config phase. We can revisit this once
            # Octavia's DevStack plugin will get improved.

            if [ "${KURYR_CONT}" == "True" ]; then
                run_containerized_kuryr_resources
            else
                run_kuryr_kubernetes
                run_kuryr_daemon
            fi
        fi

        if is_service_enabled tempest; then
            update_tempest_conf_file
        fi
    fi

    if [[ "$1" == "unstack" ]]; then
        # Shut down kuryr and kubernetes services
        if is_service_enabled kuryr-kubernetes; then
            if [ "${KURYR_CONT}" == "False" ]; then
                stop_process kuryr-kubernetes
                stop_process kuryr-daemon
            fi
            kubeadm_reset
        fi
        cleanup_kuryr_devstack_iptables
    fi

    if [[ "$1" == "clean" ]]; then
        # Uninstall kubernetes pkgs, remove config files and kuryr cni
        kubeadm_uninstall
        uninstall_kuryr_cni
        rm_kuryr_conf
    fi
fi

# Restore xtrace
$XTRACE
