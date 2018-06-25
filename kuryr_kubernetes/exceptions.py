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


class K8sClientException(Exception):
    pass


class IntegrityError(RuntimeError):
    pass


class ResourceNotReady(Exception):
    def __init__(self, resource):
        super(ResourceNotReady, self).__init__("Resource not ready: %r"
                                               % resource)


class K8sResourceNotFound(K8sClientException):
    def __init__(self, resource):
        super(K8sResourceNotFound, self).__init__("Resource not "
                                                  "found: %r" % resource)


class InvalidKuryrNetCRD(Exception):
    pass


class InvalidKuryrNetworkAnnotation(Exception):
    pass


class CNIError(Exception):
    pass


def format_msg(exception):
    return "%s: %s" % (exception.__class__.__name__, exception)


class K8sNodeTrunkPortFailure(Exception):
    """Exception represents that error is related to K8s node trunk port

    This exception is thrown when Neutron port is not associated to a Neutron
    vlan trunk.
    """


class AllowedAddressAlreadyPresent(Exception):
    """Exception indicates an already present 'allowed address pair' on port

    This exception is raised when an attempt to add an already inserted
    'allowed address pair' on a port is made. Such a condition likely indicates
    a bad program state or a programming bug.
    """


class MultiPodDriverPoolConfigurationNotSupported(Exception):
    """Exception indicates a wrong configuration of the multi pod driver pool

    This exception is raised when the multi pod driver pool is not properly
    configured. This could be due to three different reasons:
    1. One of the pool drivers is not supported
    2. One of the pod drivers is not supported
    3. One of the pod drivers is not supported by its selected pool driver
    """


class IngressControllerFailure(Exception):
    """Exception represents a failure in the Ingress Controller functionality

    This exception is raised when we fail to activate properly the Ingress
    Controller.
    """
