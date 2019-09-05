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
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get pods -o yaml --all-namespaces >> ${K8S_LOG_DIR}/pods.txt
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get svc -o yaml --all-namespaces >> ${K8S_LOG_DIR}/services.txt
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get cm -o yaml --all-namespaces >> ${K8S_LOG_DIR}/configmaps.txt
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get deploy -o yaml --all-namespaces >> ${K8S_LOG_DIR}/deployments.txt
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get ds -o yaml --all-namespaces >> ${K8S_LOG_DIR}/daemonsets.txt
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get nodes -o yaml --all-namespaces >> ${K8S_LOG_DIR}/nodes.txt
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get ingress -o yaml --all-namespaces >> ${K8S_LOG_DIR}/ingress.txt
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get namespaces -o yaml >> ${K8S_LOG_DIR}/namespaces.txt
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get kuryrnets -o yaml --all-namespaces >> ${K8S_LOG_DIR}/kuryrnets_crds.txt
/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config get endpoints -o yaml --all-namespaces >> ${K8S_LOG_DIR}/endpoints.txt
# Kubernetes pods logs
mkdir -p ${K8S_LOG_DIR}/pod_logs
while read -r line
do
    name=$(echo ${line} | cut -f1 -d " ")
    namespace=$(echo ${line} | cut -f2 -d " ")
    containers=`/usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config -n ${namespace} get pods ${name} -o jsonpath="{.spec.containers[*].name}"`
    for container in ${containers}
    do
        /usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config logs -n ${namespace} -c ${container} ${name} >> ${K8S_LOG_DIR}/pod_logs/${namespace}-${name}-${container}.txt
        /usr/local/bin/kubectl --kubeconfig=${HOME}/.kube/config logs -n ${namespace} -p -c ${container} ${name} >> ${K8S_LOG_DIR}/pod_logs/${namespace}-${name}-${container}-prev.txt
    done
done < <(/usr/local/bin/kubectl get pods -o=custom-columns=NAME:.metadata.name,NAMESPACE:.metadata.namespace --all-namespaces | tail -n +2)

sudo chown -R zuul:zuul ${K8S_LOG_DIR}
