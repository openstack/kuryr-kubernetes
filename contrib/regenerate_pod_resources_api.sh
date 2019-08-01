#!/bin/bash

set -o errexit

# Exit early if python3 is not available.
python3 --version > /dev/null

KURYR_DIR=${KURYR_DIR:-./}
KURYR_API_PROTO="kuryr_kubernetes/pod_resources/api.proto"

# If API_VERSION is not specified assuming v1alpha1.
VERSION=${API_VERSION:-v1alpha1}

ACTIVATED="no"
ENV_DIR=$(mktemp -d -t kuryr-tmp-env-XXXXXXXXXX)

function cleanup() {
    if [ "${ACTIVATED}" = "yes" ]; then deactivate; fi
    rm -rf "${ENV_DIR}"
}
trap cleanup EXIT INT

if [ -z "${KUBERNETES_API_PROTO}" ]; then

    echo "KUBERNETES_API_PROTO is not specified." \
         "Trying to download api.proto from the k8s github."

    pushd "${ENV_DIR}"

    BASE_URL="https://raw.githubusercontent.com/kubernetes/kubernetes/master"
    PROTO_FILE="pkg/kubelet/apis/podresources/${VERSION}/api.proto"

    wget "${BASE_URL}/${PROTO_FILE}" -O api.proto

    KUBERNETES_API_PROTO="$PWD/api.proto"
    popd
fi

if [ ! -f "${KUBERNETES_API_PROTO}" ]; then
    echo "Can't find ${KUBERNETES_API_PROTO}"
    exit 1
fi

KUBERNETES_API_PROTO=$(readlink -e "${KUBERNETES_API_PROTO}")

pushd "${KURYR_DIR}"

# Obtaining api version from the proto file.
VERSION=$(grep package "${KUBERNETES_API_PROTO}" \
          | sed 's/^package *\(.*\)\;$/\1/')
echo "\
// Generated from kubernetes/pkg/kubelet/apis/podresources/${VERSION}/api.proto
// To regenerate api.proto, api_pb2.py and api_pb2_grpc.py follow instructions
// from doc/source/devref/updating_pod_resources_api.rst.
" > ${KURYR_API_PROTO}

# Stripping unwanted dependencies.
sed '/gogoproto/d;/api.pb.go/d' "${KUBERNETES_API_PROTO}" >> ${KURYR_API_PROTO}
echo '' >> ${KURYR_API_PROTO}
# Stripping redundant empty lines.
sed -i '/^$/N;/^\n$/D' ${KURYR_API_PROTO}

# Creating new virtual environment.
python3 -m venv "${ENV_DIR}"
source "${ENV_DIR}/bin/activate"
ACTIVATED="yes"

pip install grpcio-tools==1.19

# Checking protobuf version.
protobuf_version=$(grep protobuf lower-constraints.txt \
                   | sed 's/^protobuf==\([0-9\.]*\)\.[0-9]*$/\1/')
protoc_version=$(python -m grpc_tools.protoc --version \
                 | sed 's/^libprotoc \([0-9\.]*\)\.[0-9]*$/\1/')
if [ "${protobuf_version}" != "${protoc_version}" ]; then
    echo "protobuf version in lower-constraints.txt (${protobuf_version})" \
         "!= installed protoc compiler version (${protoc_version})."
    echo "Please, update requirements.txt and lower-constraints.txt or" \
         "change version of grpcio-tools used in this script."
    # Clearing api.proto to highlight the issue.
    echo '' > ${KURYR_API_PROTO}
    exit 1
fi

# Generating python bindings.
python -m grpc_tools.protoc -I./ \
       --python_out=. --grpc_python_out=. ${KURYR_API_PROTO}
popd
