#!/bin/sh
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

set -e

GEN_CMD=oslo-config-generator
SCRIPT_PATH=$(dirname "$(readlink -f "$0")")
DIST_PATH=$(dirname "$SCRIPT_PATH")

prerequisites() (
    if ! command -v "$GEN_CMD" > /dev/null; then
        echo "ERROR: $GEN_CMD not installed on the system."
        return 1
    fi

    if ! [ -f "${DIST_PATH}/kuryr_kubernetes.egg-info/entry_points.txt" ]; then
        curr_dir=$(pwd)
        cd "${DIST_PATH}"
        python setup.py egg_info  # Generate entrypoints for config generation
        cd "${curr_dir}"
    fi

    return 0
)

generate() (
    curr_dir=$(pwd)
    cd "${DIST_PATH}"
    # Set PYTHONPATH so that it will use the generated egg-info
    PYTHONPATH=. find "etc/oslo-config-generator" -type f -exec "$GEN_CMD" --config-file="{}" \;
    cd "${curr_dir}"
)


prerequisites
rc=$?
if [ $rc -ne 0 ]; then
    exit $rc
fi

generate

set -x
