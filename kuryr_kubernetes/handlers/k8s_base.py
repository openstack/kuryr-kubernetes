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


def object_kind(event):
    try:
        return event['object']['kind']
    except KeyError:
        return None


def object_link(event):
    try:
        return event['object']['metadata']['selfLink']
    except KeyError:
        return None


class ResourceEventHandler(dispatch.EventConsumer):
    """Base class for K8s event handlers.

    Implementing classes should override the `OBJECT_KIND` attribute with a
    valid Kubernetes object type name (e.g. 'Pod' or 'Namespace'; see [1]
    for more details).

    Implementing classes are expected to override any or all of the
    `on_added`, `on_present`, `on_modified`, `on_deleted` methods that would
    be called depending on the type of the event (with K8s object as a single
    argument).

    [1] https://github.com/kubernetes/kubernetes/blob/release-1.4/docs/devel\
        /api-conventions.md#types-kinds
    """

    OBJECT_KIND = None

    @property
    def consumes(self):
        return {object_kind: self.OBJECT_KIND}

    def __call__(self, event):
        event_type = event.get('type')
        obj = event.get('object')
        if 'MODIFIED' == event_type:
            self.on_modified(obj)
            self.on_present(obj)
        elif 'ADDED' == event_type:
            self.on_added(obj)
            self.on_present(obj)
        elif 'DELETED' == event_type:
            self.on_deleted(obj)

    def on_added(self, obj):
        pass

    def on_present(self, obj):
        pass

    def on_modified(self, obj):
        pass

    def on_deleted(self, obj):
        pass
