#!/bin/bash

set -o errexit

KURYR_DIR=${KURYR_DIR:-/opt/stack/kuryr-kubernetes}
KURYR_CONTROLLER_NAME=${KURYR_CONTROLLER_NAME:-kuryr-controller}

function build_tagged_container {
    docker build -t kuryr/controller -f $KURYR_DIR/controller.Dockerfile $KURYR_DIR
}

function recreate_controller {
    kubectl delete pods -n kube-system -l name=$KURYR_CONTROLLER_NAME
}

build_tagged_container
recreate_controller
