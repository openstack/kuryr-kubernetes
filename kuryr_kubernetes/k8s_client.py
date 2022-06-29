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
import datetime
import functools
import itertools
import os
import ssl
import time
from urllib import parse
import urllib3

from oslo_log import log as logging
from oslo_serialization import jsonutils
import pytz
import requests
from requests import adapters

from kuryr.lib._i18n import _
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes import exceptions as exc
from kuryr_kubernetes import utils

CONF = config.CONF
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
        self.are_events_enabled = config.CONF.kubernetes.use_events

        # Setting higher numbers regarding connection pools as we're running
        # with max of 1000 green threads.
        self.session = requests.Session()
        prefix = '%s://' % parse.urlparse(base_url).scheme
        self.session.mount(prefix, adapters.HTTPAdapter(pool_maxsize=1000))
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

        # Let's setup defaults for our Session.
        self.session.cert = self.cert
        self.session.verify = self.verify_server
        if self.token:
            self.session.headers['Authorization'] = f'Bearer {self.token}'
        # NOTE(dulek): Seems like this is the only way to set is globally.
        self.session.request = functools.partial(
            self.session.request, timeout=(
                CONF.kubernetes.watch_connection_timeout,
                CONF.kubernetes.watch_read_timeout))

    def _raise_from_response(self, response):
        if response.status_code == requests.codes.not_found:
            raise exc.K8sResourceNotFound(response.text)
        if response.status_code == requests.codes.conflict:
            raise exc.K8sConflict(response.text)
        if response.status_code == requests.codes.forbidden:
            if 'because it is being terminated' in response.json()['message']:
                raise exc.K8sNamespaceTerminating(response.text)
            raise exc.K8sForbidden(response.text)
        if response.status_code == requests.codes.unprocessable_entity:
            # NOTE(gryf): on k8s API code 422 is also Forbidden, but specified
            # to FieldValueForbidden. Perhaps there are other usages for
            # throwing unprocessable entity errors in different cases.
            if ('FieldValueForbidden' in response.text and
                    'Forbidden' in response.json()['message']):
                raise exc.K8sFieldValueForbidden(response.text)
            raise exc.K8sUnprocessableEntity(response.text)
        if not response.ok:
            raise exc.K8sClientException(response.text)

    def get(self, path, json=True, headers=None):
        LOG.debug("Get %(path)s", {'path': path})
        url = self._base_url + path
        response = self.session.get(url, headers=headers)
        self._raise_from_response(response)

        if json:
            result = response.json()
            kind = result['kind']

            api_version = result.get('apiVersion')
            if not api_version:
                api_version = utils.get_api_ver(path)

            # Strip List from e.g. PodList. For some reason `.items` of a list
            # returned from API doesn't have `kind` set.
            # NOTE(gryf): Also, for the sake of calculating selfLink
            # equivalent, we need to have both: kind and apiVersion, while the
            # latter is not present on items list for core resources, while
            # for custom resources there are both kind and apiVersion..
            if kind.endswith('List'):
                kind = kind[:-4]

                # NOTE(gryf): In case we get null/None for items from the API,
                # we need to convert it to the empty list, otherwise it might
                # be propagated to the consumers of this method and sent back
                # to the Kubernetes as is, and fail as a result.
                if result['items'] is None:
                    result['items'] = []

                for item in result['items']:
                    if not item.get('kind'):
                        item['kind'] = kind
                    if not item.get('apiVersion'):
                        item['apiVersion'] = api_version

                if not result.get('apiVersion'):
                    result['apiVersion'] = api_version
        else:
            result = response.text

        return result

    def _get_url_and_header(self, path, content_type):
        url = self._base_url + path
        header = {'Content-Type': content_type,
                  'Accept': 'application/json'}

        return url, header

    def patch(self, field, path, data):
        LOG.debug("Patch %(path)s: %(data)s", {'path': path, 'data': data})
        content_type = 'application/merge-patch+json'
        url, header = self._get_url_and_header(path, content_type)
        response = self.session.patch(url, json={field: data}, headers=header)
        self._raise_from_response(response)
        return response.json().get('status')

    def patch_crd(self, field, path, data, action='replace'):
        content_type = 'application/json-patch+json'
        url, header = self._get_url_and_header(path, content_type)

        if action == 'remove':
            data = [{'op': action,
                     'path': f'/{field}/{data}'}]
        else:
            if data:
                data = [{'op': action,
                         'path': f'/{field}/{crd_field}',
                         'value': value}
                        for crd_field, value in data.items()]
            else:
                data = [{'op': action,
                         'path': f'/{field}',
                         'value': data}]

        LOG.debug("Patch %(path)s: %(data)s", {
            'path': path, 'data': data})

        response = self.session.patch(url, data=jsonutils.dumps(data),
                                      headers=header)
        self._raise_from_response(response)
        return response.json().get('status')

    def post(self, path, body):
        LOG.debug("Post %(path)s: %(body)s", {'path': path, 'body': body})
        url = self._base_url + path
        header = {'Content-Type': 'application/json'}

        response = self.session.post(url, json=body, headers=header)
        self._raise_from_response(response)
        return response.json()

    def delete(self, path):
        LOG.debug("Delete %(path)s", {'path': path})
        url = self._base_url + path
        header = {'Content-Type': 'application/json'}

        response = self.session.delete(url, headers=header)
        self._raise_from_response(response)
        return response.json()

    # TODO(dulek): add_finalizer() and remove_finalizer() have some code
    #              duplication, but I don't see a nice way to avoid it.
    def add_finalizer(self, obj, finalizer):
        if finalizer in obj['metadata'].get('finalizers', []):
            return True

        path = utils.get_res_link(obj)
        LOG.debug(f"Add finalizer {finalizer} to {path}")
        url, headers = self._get_url_and_header(
            path, 'application/merge-patch+json')

        for i in range(3):  # Let's make sure it's not infinite loop
            finalizers = obj['metadata'].get('finalizers', []).copy()
            finalizers.append(finalizer)

            data = {
                'metadata': {
                    'finalizers': finalizers,
                    'resourceVersion': obj['metadata']['resourceVersion'],
                },
            }

            response = self.session.patch(url, json=data, headers=headers)

            if response.ok:
                return True

            try:
                self._raise_from_response(response)
            except (exc.K8sFieldValueForbidden, exc.K8sResourceNotFound):
                # Object is being deleting or gone. Return.
                return False
            except exc.K8sConflict:
                try:
                    obj = self.get(path)
                except exc.K8sResourceNotFound:
                    # Object got removed before finalizer was set
                    return False
                if finalizer in obj['metadata'].get('finalizers', []):
                    # Finalizer is there, return.
                    return True

        # If after 3 iterations there's still conflict, just raise.
        self._raise_from_response(response)

    def remove_finalizer(self, obj, finalizer):
        path = utils.get_res_link(obj)
        LOG.debug(f"Remove finalizer {finalizer} from {path}")
        url, headers = self._get_url_and_header(
            path, 'application/merge-patch+json')

        for i in range(3):  # Let's make sure it's not infinite loop
            finalizers = obj['metadata'].get('finalizers', []).copy()
            try:
                finalizers.remove(finalizer)
            except ValueError:
                # Finalizer is not there, return.
                return True

            data = {
                'metadata': {
                    'finalizers': finalizers,
                    'resourceVersion': obj['metadata']['resourceVersion'],
                },
            }

            response = self.session.patch(url, json=data, headers=headers)

            if response.ok:
                return True

            try:
                try:
                    self._raise_from_response(response)
                except exc.K8sConflict:
                    obj = self.get(path)
            except (exc.K8sFieldValueForbidden, exc.K8sResourceNotFound):
                # Object is being deleted or gone already, stop.
                return False

        # If after 3 iterations there's still conflict, just raise.
        self._raise_from_response(response)

    def get_loadbalancer_crd(self, obj):
        name = obj['metadata']['name']
        namespace = obj['metadata']['namespace']

        try:
            crd = self.get('{}/{}/kuryrloadbalancers/{}'.format(
                constants.K8S_API_CRD_NAMESPACES, namespace,
                name))
        except exc.K8sResourceNotFound:
            return None
        except exc.K8sClientException:
            LOG.exception("Kubernetes Client Exception.")
            raise
        return crd

    def annotate(self, path, annotations, resource_version=None):
        """Pushes a resource annotation to the K8s API resource

        The annotate operation is made with a PATCH HTTP request of kind:
        application/merge-patch+json as described in:

        https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md#patch-operations  # noqa
        """
        LOG.debug("Annotate %(path)s: %(names)s", {
            'path': path, 'names': list(annotations)})

        content_type = 'application/merge-patch+json'
        url, header = self._get_url_and_header(path, content_type)

        while itertools.count(1):
            metadata = {"annotations": annotations}
            if resource_version:
                metadata['resourceVersion'] = resource_version
            data = jsonutils.dumps({"metadata": metadata}, sort_keys=True)
            response = self.session.patch(url, data=data, headers=header)
            if response.ok:
                return response.json()['metadata'].get('annotations', {})
            if response.status_code == requests.codes.conflict:
                resource = self.get(path)
                new_version = resource['metadata']['resourceVersion']
                retrieved_annotations = resource['metadata'].get(
                    'annotations', {})

                for k, v in annotations.items():
                    if v != retrieved_annotations.get(k):
                        break
                else:
                    LOG.debug("Annotations for %(path)s already present: "
                              "%(names)s", {'path': path,
                                            'names': retrieved_annotations})
                    return retrieved_annotations
                # Retry patching with updated resourceVersion
                resource_version = new_version
                continue

            LOG.error("Exception response, headers: %(headers)s, "
                      "content: %(content)s, text: %(text)s"
                      % {'headers': response.headers,
                         'content': response.content, 'text': response.text})

            self._raise_from_response(response)

    def watch(self, path):
        url = self._base_url + path
        resource_version = None

        attempt = 0
        while True:
            try:
                params = {'watch': 'true'}
                if resource_version:
                    params['resourceVersion'] = resource_version
                with contextlib.closing(
                        self.session.get(
                            url, params=params, stream=True)) as response:
                    if not response.ok:
                        raise exc.K8sClientException(response.text)
                    attempt = 0
                    for line in response.iter_lines():
                        line = line.decode('utf-8').strip()
                        if line:
                            line_dict = jsonutils.loads(line)
                            yield line_dict
                            # Saving the resourceVersion in case of a restart.
                            # At this point it's safely passed to handler.
                            m = line_dict.get('object', {}).get('metadata', {})
                            resource_version = m.get('resourceVersion', None)
            except (requests.ReadTimeout, requests.ConnectionError,
                    ssl.SSLError, requests.exceptions.ChunkedEncodingError,
                    urllib3.exceptions.SSLError):
                t = utils.exponential_backoff(attempt)
                log = LOG.debug
                if attempt > 0:
                    # Only make it a warning if it's happening again, no need
                    # to inform about all the read timeouts.
                    log = LOG.warning
                log('Connection error when watching %s. Retrying in %ds with '
                    'resourceVersion=%s', path, t,
                    params.get('resourceVersion'))
                time.sleep(t)
                attempt += 1

    def add_event(self, resource, reason, message, type_='Normal',
                  component='kuryr-controller'):
        """Create an Event object for the provided resource."""
        if not self.are_events_enabled:
            return {}

        if not resource:
            return {}

        involved_object = {'apiVersion': resource['apiVersion'],
                           'kind': resource['kind'],
                           'name': resource['metadata']['name'],
                           'namespace': resource['metadata']['namespace'],
                           'uid': resource['metadata']['uid']}

        # This is needed for Event date, otherwise LAST SEEN/Age will be empty
        # and misleading.
        now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
        date_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        name = ".".join((resource['metadata']['name'],
                         self._get_hex_timestamp(now)))

        event = {'kind': 'Event',
                 'apiVersion': 'v1',
                 'firstTimestamp': date_time,
                 'metadata': {'name': name},
                 'reason': reason,
                 'message': message,
                 'type': type_,
                 'involvedObject': involved_object,
                 'source': {'component': component,
                            'host': utils.get_nodename()}}

        try:
            return self.post(f'{constants.K8S_API_BASE}/namespaces/'
                             f'{resource["metadata"]["namespace"]}/events',
                             event)
        except exc.K8sNamespaceTerminating:
            # We can't create events in a Namespace that is being terminated,
            # there's no workaround, no need to log it, just ignore it.
            return {}
        except exc.K8sClientException:
            LOG.warning(f'There was non critical error during creating an '
                        'Event for resource: "{resource}", with reason: '
                        f'"{reason}", message: "{message}" and type: '
                        f'"{type_}"')
            return {}

    def _get_hex_timestamp(self, datetimeobj):
        """Get hex representation for timestamp.

        In Kuberenets, Event name is constructed name of the bounded object
        and timestamp in hexadecimal representation.
        Note, that Python timestamp is represented as floating figure:
          1631622163.8534190654754638671875
        while those which origin from K8s, after change to int:
          1631622163915909162
        so, to get similar integer, we need to multiply the float by
        100000000 to get the same precision and cast to integer, to get rid
        of the fractures, and finally convert it to hex representation.
        """
        timestamp = datetime.datetime.timestamp(datetimeobj)
        return format(int(timestamp * 100000000), 'x')
