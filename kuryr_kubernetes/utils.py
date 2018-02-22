# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import random
import time

from oslo_config import cfg
from oslo_serialization import jsonutils

CONF = cfg.CONF

DEFAULT_TIMEOUT = 180
DEFAULT_INTERVAL = 3


def utf8_json_decoder(byte_data):
    """Deserializes the bytes into UTF-8 encoded JSON.

    :param byte_data: The bytes to be converted into the UTF-8 encoded JSON.
    :returns: The UTF-8 encoded JSON represented by Python dictionary format.
    """
    return jsonutils.loads(byte_data.decode('utf8'))


def convert_netns(netns):
    """Convert /proc based netns path to Docker-friendly path.

    When CONF.docker_mode is set this method will change /proc to
    /CONF.netns_proc_dir. This allows netns manipulations to work when running
    in Docker container on Kubernetes host.

    :param netns: netns path to convert.
    :return: Converted netns path.
    """
    if CONF.cni_daemon.docker_mode:
        return netns.replace('/proc', CONF.cni_daemon.netns_proc_dir)
    else:
        return netns


def exponential_sleep(deadline, attempt, interval=DEFAULT_INTERVAL):
    """Sleep for exponential duration.

    This implements a variation of exponential backoff algorithm [1] and
    ensures that there is a minimal time `interval` to sleep.
    (expected backoff E(c) = interval * 2 ** c / 2).

    [1] https://en.wikipedia.org/wiki/Exponential_backoff

    :param deadline: sleep timeout duration in seconds.
    :param attempt: attempt count of sleep function.
    :param interval: minimal time interval to sleep
    :return: the actual time that we've slept
    """
    now = time.time()
    seconds_left = deadline - now

    if seconds_left <= 0:
        return 0

    interval = random.randint(1, 2 ** attempt - 1) * DEFAULT_INTERVAL

    if interval > seconds_left:
        interval = seconds_left

    if interval < DEFAULT_INTERVAL:
        interval = DEFAULT_INTERVAL

    time.sleep(interval)
    return interval
