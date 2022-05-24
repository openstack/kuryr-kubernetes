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

from kuryr_kubernetes.handlers import dispatch
from kuryr_kubernetes.handlers import health


def object_kind(event):
    try:
        return event['object']['kind']
    except KeyError:
        return None


def object_uid(event):
    try:
        return event['object']['metadata']['uid']
    except KeyError:
        return None


def object_info(event):
    try:
        resource = event['object']
        try:
            return "%(kind)s %(namespace)s/%(name)s" % resource['metadata']
        except KeyError:
            return "%(kind)s: %(name)s" % resource['metadata']
    except KeyError:
        return None


class ResourceEventHandler(dispatch.EventConsumer, health.HealthHandler):
    """Base class for K8s event handlers.

    Implementing classes should override both `OBJECT_KIND` and
    'OBJECT_WATCH_PATH' attributes.
    The `OBJECT_KIND` should be set to a valid Kubernetes object type
    name (e.g. 'Pod' or 'Namespace'; see [1] for more details).

    The `OBJECT_WATCH_PATH` should point to object's watched path,
    (e.g. for the 'Pod' case the OBJECT_WATCH_PATH should be '/api/v1/pods').

    Implementing classes are expected to override any or all of the
    `on_added`, `on_present`, `on_modified`, `on_deleted` methods that would
    be called depending on the type of the event (with K8s object as a single
    argument).

    [1] https://github.com/kubernetes/kubernetes/blob/release-1.4/docs/devel\
        /api-conventions.md#types-kinds
    """

    OBJECT_KIND = None
    OBJECT_WATCH_PATH = None

    def __init__(self):
        super(ResourceEventHandler, self).__init__()

    def get_watch_path(self):
        return self.OBJECT_WATCH_PATH

    @property
    def consumes(self):
        return {object_kind: self.OBJECT_KIND}

    def _check_finalize(self, obj):
        deletion_timestamp = None
        try:
            deletion_timestamp = obj['metadata']['deletionTimestamp']
        except (KeyError, TypeError):
            pass

        return deletion_timestamp

    def __call__(self, event, *args, **kwargs):
        event_type = event.get('type')
        obj = event.get('object')
        if 'MODIFIED' == event_type:
            if self._check_finalize(obj):
                self.on_finalize(obj, *args, **kwargs)
                return
            self.on_modified(obj, *args, **kwargs)
            self.on_present(obj, *args, **kwargs)
        elif 'ADDED' == event_type:
            if self._check_finalize(obj):
                self.on_finalize(obj, *args, **kwargs)
                return
            self.on_added(obj, *args, **kwargs)
            self.on_present(obj, *args, **kwargs)
        elif 'DELETED' == event_type:
            self.on_deleted(obj, *args, **kwargs)

    def on_added(self, obj, *args, **kwargs):
        pass

    def on_present(self, obj, *args, **kwargs):
        pass

    def on_modified(self, obj, *args, **kwargs):
        pass

    def on_deleted(self, obj, *args, **kwargs):
        pass

    def on_finalize(self, obj, *args, **kwargs):
        pass

    def reconcile(self):
        pass
