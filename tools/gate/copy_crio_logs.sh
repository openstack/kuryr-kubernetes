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

# copy crio config and logs, if crio is installed - there should be
# configuration, since we modifying it through devstack.
if [ -d /etc/crio ]; then
    CRIO_LOG_DIR=${DEVSTACK_BASE_DIR}/logs/crio
    mkdir -p "${CRIO_LOG_DIR}/conf"
    sudo journalctl -o short-precise --unit crio | \
        sudo tee "${CRIO_LOG_DIR}/crio_log.txt" > /dev/null
    sudo cp -a /etc/crio "${CRIO_LOG_DIR}/conf"
    sudo chown -R zuul:zuul "${CRIO_LOG_DIR}"
fi
