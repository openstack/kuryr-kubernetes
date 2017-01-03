#!/usr/bin/env bash

set -ex

source $BASE/new/kuryr-kubernetes/devstack/devstackgaterc $1
$BASE/new/devstack-gate/devstack-vm-gate.sh
