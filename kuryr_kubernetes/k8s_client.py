# Copyright (c) 2016 Mirantis, Inc.
# All Rights Reserved.
#
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

import contextlib

from oslo_serialization import jsonutils
import requests

from kuryr_kubernetes import exceptions as exc


class K8sClient(object):
    # REVISIT(ivc): replace with python-k8sclient if it could be extended
    # with 'WATCH' support

    def __init__(self, base_url):
        self._base_url = base_url

    def get(self, path):
        url = self._base_url + path
        response = requests.get(url)
        if not response.ok:
            raise exc.K8sClientException(response.text)
        return response.json()

    def annotate(self, path, annotations):
        url = self._base_url + path
        data = jsonutils.dumps({
            "metadata": {
                "annotations": annotations
            }
        })
        response = requests.patch(url, data=data, headers={
            'Content-Type': 'application/merge-patch+json',
            'Accept': 'application/json',
        })
        if not response.ok:
            raise exc.K8sClientException(response.text)
        return response.json()['metadata']['annotations']

    def watch(self, path):
        params = {'watch': 'true'}
        url = self._base_url + path

        # TODO(ivc): handle connection errors and retry on failure
        while True:
            with contextlib.closing(requests.get(url, params=params,
                                                 stream=True)) as response:
                if not response.ok:
                    raise exc.K8sClientException(response.text)
                for line in response.iter_lines(delimiter='\n'):
                    line = line.strip()
                    if line:
                        yield jsonutils.loads(line)
