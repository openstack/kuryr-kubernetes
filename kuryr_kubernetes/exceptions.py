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

from kuryr.lib._i18n import _LE


class K8sClientException(Exception):
    pass


class IntegrityError(RuntimeError):
    pass


class ResourceNotReady(Exception):
    def __init__(self, resource):
        super(ResourceNotReady, self).__init__(_LE("Resource not ready: %r")
                                               % resource)


class CNIError(Exception):
    pass


def format_msg(exception):
    return "%s: %s" % (exception.__class__.__name__, exception)
