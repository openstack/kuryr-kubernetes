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
import itertools
import os

from oslo_log import log as logging
from oslo_serialization import jsonutils
import requests

from kuryr.lib._i18n import _
from kuryr_kubernetes import config
from kuryr_kubernetes import exceptions as exc

LOG = logging.getLogger(__name__)


class K8sClient(object):
    # REVISIT(ivc): replace with python-k8sclient if it could be extended
    # with 'WATCH' support

    def __init__(self, base_url):
        self._base_url = base_url
        cert_file = config.CONF.kubernetes.ssl_client_crt_file
        key_file = config.CONF.kubernetes.ssl_client_key_file
        ca_crt_file = config.CONF.kubernetes.ssl_ca_crt_file
        self.verify_server = config.CONF.kubernetes.ssl_verify_server_crt
        token_file = config.CONF.kubernetes.token_file
        self.token = None
        self.cert = (None, None)
        if token_file:
            if os.path.exists(token_file):
                with open(token_file, 'r') as f:
                    self.token = f.readline().rstrip('\n')
            else:
                raise RuntimeError(
                    _("Unable to find token_file  : %s") % token_file)
        else:
            if cert_file and not os.path.exists(cert_file):
                raise RuntimeError(
                    _("Unable to find ssl cert_file  : %s") % cert_file)
            if key_file and not os.path.exists(key_file):
                raise RuntimeError(
                    _("Unable to find ssl key_file : %s") % key_file)
            self.cert = (cert_file, key_file)
        if self.verify_server:
            if not ca_crt_file:
                raise RuntimeError(
                    _("ssl_ca_crt_file cannot be None"))
            elif not os.path.exists(ca_crt_file):
                raise RuntimeError(
                    _("Unable to find ca cert_file  : %s") % ca_crt_file)
            else:
                self.verify_server = ca_crt_file

    def get(self, path):
        LOG.debug("Get %(path)s", {'path': path})
        url = self._base_url + path
        header = {}
        if self.token:
            header.update({'Authorization': 'Bearer %s' % self.token})
        response = requests.get(url, cert=self.cert,
                                verify=self.verify_server,
                                headers=header)
        if not response.ok:
            raise exc.K8sClientException(response.text)
        return response.json()

    def annotate(self, path, annotations, resource_version=None):
        """Pushes a resource annotation to the K8s API resource

        The annotate operation is made with a PATCH HTTP request of kind:
        application/merge-patch+json as described in:

        https://github.com/kubernetes/community/blob/master/contributors/devel/api-conventions.md#patch-operations  # noqa
        """
        LOG.debug("Annotate %(path)s: %(names)s", {
            'path': path, 'names': list(annotations)})
        url = self._base_url + path
        header = {'Content-Type': 'application/merge-patch+json',
                  'Accept': 'application/json'}
        if self.token:
            header.update({'Authorization': 'Bearer %s' % self.token})
        while itertools.count(1):
            if resource_version:
                data = jsonutils.dumps({
                    "metadata": {
                        "annotations": annotations,
                        "resourceVersion": resource_version,
                    }
                }, sort_keys=True)
            else:
                data = jsonutils.dumps({
                    "metadata": {
                        "annotations": annotations
                    }
                }, sort_keys=True)

            response = requests.patch(url, data=data,
                                      headers=header, cert=self.cert,
                                      verify=self.verify_server)
            if response.ok:
                return response.json()['metadata']['annotations']
            if response.status_code == requests.codes.conflict:
                resource = self.get(path)
                new_version = resource['metadata']['resourceVersion']
                retrieved_annotations = resource['metadata'].get(
                    'annotations', {})

                for k, v in annotations.items():
                    if v != retrieved_annotations.get(k, v):
                        break
                else:
                    # No conflicting annotations found. Retry patching
                    resource_version = new_version
                    continue
                LOG.debug("Annotations for %(path)s already present: "
                          "%(names)s", {'path': path,
                                        'names': retrieved_annotations})

            LOG.debug("Exception response, headers: %(headers)s, "
                      "content: %(content)s, text: %(text)s"
                      % {'headers': response.headers,
                         'content': response.content, 'text': response.text})
            raise exc.K8sClientException(response.text)

    def watch(self, path):
        params = {'watch': 'true'}
        url = self._base_url + path
        header = {}
        if self.token:
            header.update({'Authorization': 'Bearer %s' % self.token})

        # TODO(ivc): handle connection errors and retry on failure
        while True:
            with contextlib.closing(
                    requests.get(url, params=params, stream=True,
                                 cert=self.cert, verify=self.verify_server,
                                 headers=header)) as response:
                if not response.ok:
                    raise exc.K8sClientException(response.text)
                for line in response.iter_lines(delimiter='\n'):
                    line = line.strip()
                    if line:
                        yield jsonutils.loads(line)
