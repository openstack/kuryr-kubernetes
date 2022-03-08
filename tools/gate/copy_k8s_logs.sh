#!/bin/bash -x
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
#
# See the License for the specific language governing permissions and
# limitations under the License.
# This script takes bits from devstack-gate/functions/cleanup_host in a
# more generic approach, so we don't need to actually run devstack on the node
# to cleanup an host.

# Kubernetes resources
# TODO(dulek): It might be good to split that into Ansible tasks once it's
#              stable. Until then script is easier to debug and test.
K8S_LOG_DIR=${DEVSTACK_BASE_DIR}/logs/kubernetes
mkdir -p ${K8S_LOG_DIR}
mkdir ${HOME}/.kube
sudo cp /opt/stack/.kube/config  ${HOME}/.kube/
sudo chown ${USER}:${USER} ${HOME}/.kube/config

KCTL="/usr/bin/kubectl --kubeconfig=${HOME}/.kube/config"
$KCTL get pods -o yaml --all-namespaces >> ${K8S_LOG_DIR}/pods.txt
$KCTL get svc -o yaml --all-namespaces >> ${K8S_LOG_DIR}/services.txt
$KCTL get endpoints -o yaml --all-namespaces >> ${K8S_LOG_DIR}/endpoints.txt
$KCTL get networkpolicies -o yaml --all-namespaces >> ${K8S_LOG_DIR}/networkpolicies.txt
$KCTL get cm -o yaml --all-namespaces >> ${K8S_LOG_DIR}/configmaps.txt
$KCTL get deploy -o yaml --all-namespaces >> ${K8S_LOG_DIR}/deployments.txt
$KCTL get ds -o yaml --all-namespaces >> ${K8S_LOG_DIR}/daemonsets.txt
$KCTL get nodes -o yaml --all-namespaces >> ${K8S_LOG_DIR}/nodes.txt
$KCTL get namespaces -o yaml >> ${K8S_LOG_DIR}/namespaces.txt
$KCTL get events -o yaml --all-namespaces >> ${K8S_LOG_DIR}/events.txt
$KCTL get kuryrnetworks -o yaml --all-namespaces >> ${K8S_LOG_DIR}/kuryrnetworks_crds.txt
$KCTL get kuryrport -o yaml --all-namespaces >> ${K8S_LOG_DIR}/kuryrport_crds.txt
$KCTL get kuryrloadbalancers -o yaml --all-namespaces >> ${K8S_LOG_DIR}/kuryrloadbalancer_crds.txt
$KCTL get kuryrnetworkpolicy -o yaml --all-namespaces >> ${K8S_LOG_DIR}/kuryrnetworkpolicy_crds.txt
sudo journalctl -o short-precise --unit kubelet | sudo tee ${K8S_LOG_DIR}/kubelet_log.txt > /dev/null
# Kubernetes pods logs
mkdir -p ${K8S_LOG_DIR}/pod_logs
while read -r line
do
    name=$(echo ${line} | cut -f1 -d " ")
    namespace=$(echo ${line} | cut -f2 -d " ")
    containers=`/usr/bin/kubectl --kubeconfig=${HOME}/.kube/config -n ${namespace} get pods ${name} -o jsonpath="{.spec.containers[*].name} {.spec.initContainers[*].name}"`
    for container in ${containers}
    do
        $KCTL logs -n ${namespace} -c ${container} ${name} >> ${K8S_LOG_DIR}/pod_logs/${namespace}-${name}-${container}.txt
        $KCTL logs -n ${namespace} -p -c ${container} ${name} >> ${K8S_LOG_DIR}/pod_logs/${namespace}-${name}-${container}-prev.txt
    done
done < <(/usr/bin/kubectl get pods -o=custom-columns=NAME:.metadata.name,NAMESPACE:.metadata.namespace --all-namespaces | tail -n +2)

mkdir -p "${K8S_LOG_DIR}/kubernetes_conf"
sudo cp -a /etc/kubernetes/* "${K8S_LOG_DIR}/kubernetes_conf"
sudo chown -R zuul:zuul ${K8S_LOG_DIR}
