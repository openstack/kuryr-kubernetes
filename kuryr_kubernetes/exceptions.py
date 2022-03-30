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

from kuryr_kubernetes import utils


class K8sClientException(Exception):
    pass


class IntegrityError(RuntimeError):
    pass


class InvalidKuryrConfiguration(RuntimeError):
    pass


class ResourceNotReady(Exception):
    def __init__(self, resource):
        msg = resource
        if type(resource) == dict:
            if resource.get('metadata', {}).get('name', None):
                res_name = utils.get_res_unique_name(resource)
                kind = resource.get('kind')
                if kind:
                    msg = f'{kind} {res_name}'
                else:
                    msg = res_name
        self.message = "Resource not ready: %r" % msg
        super(ResourceNotReady, self).__init__(self.message)


class KuryrLoadBalancerNotCreated(Exception):
    def __init__(self, res):
        name = utils.get_res_unique_name(res)
        super().__init__(
            'KuryrLoadBalancer not created yet for the Service %s' % name)


class LoadBalancerNotReady(ResourceNotReady):
    def __init__(self, loadbalancer_id, status):
        super().__init__(
            'Loadbalancer %s is stuck in %s status for several minutes. This '
            'is unexpected and indicates problem with OpenStack Octavia. '
            'Please contact your OpenStack administrator.' % (
                loadbalancer_id, status))


class PortNotReady(ResourceNotReady):
    def __init__(self, port_id, status):
        super().__init__(
            'Port %s is stuck in %s status for several minutes. This '
            'is unexpected and indicates problem with OpenStack Neutron. '
            'Please contact your OpenStack administrator.' % (port_id, status))


class K8sResourceNotFound(K8sClientException):
    def __init__(self, resource):
        super(K8sResourceNotFound, self).__init__("Resource not "
                                                  "found: %r" % resource)


class K8sConflict(K8sClientException):
    def __init__(self, message):
        super(K8sConflict, self).__init__("Conflict: %r" % message)


class K8sForbidden(K8sClientException):
    def __init__(self, message):
        super(K8sForbidden, self).__init__("Forbidden: %r" % message)


class K8sNamespaceTerminating(K8sForbidden):
    # This is raised when K8s complains about operation failing because
    # namespace is being terminated.
    def __init__(self, message):
        super(K8sNamespaceTerminating, self).__init__(
            "Namespace already terminated: %r" % message)


class K8sUnprocessableEntity(K8sClientException):
    def __init__(self, message):
        super(K8sUnprocessableEntity, self).__init__(
            "Unprocessable: %r" % message)


class K8sFieldValueForbidden(K8sUnprocessableEntity):
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


class CNITimeout(Exception):
    """Exception groups various timeouts happening in the CNI """


class CNIKuryrPortTimeout(CNITimeout):
    """Excepton raised on timeout waiting for KuryrPort to be created"""
    def __init__(self, name):
        super().__init__(
            f'Timed out waiting for KuryrPort to be created for pod {name}. '
            f'kuryr-controller is responsible for that, check logs there.')


class CNINeutronPortActivationTimeout(CNITimeout):
    """Excepton raised on time out waiting for Neutron ports to be ACITVE"""
    def __init__(self, name, vifs):
        inactive = ', '.join(vif.id for vif in vifs.values() if not vif.active)
        super().__init__(
            f'Timed out waiting for Neutron port(s) {inactive} to be marked '
            f'as ACTIVE after being bound to a Pod {name}. Most likely this '
            f'indicates an issue with OpenStack Neutron. You can also check '
            f'logs of kuryr-controller to confirm.')


class CNIBindingFailure(Exception):
    """Exception indicates a binding/unbinding VIF failure in CNI"""
    def __init__(self, message):
        super(CNIBindingFailure, self).__init__(message)


class CNIPodUidMismatch(Exception):
    """Excepton raised on a mismatch of CNI request's pod UID and KuryrPort"""
    def __init__(self, name, expected, observed):
        super().__init__(
            f'uid {observed} of the pod {name} does not match the uid '
            f'{expected} requested by the CNI. Dropping CNI request to prevent'
            f' race conditions.')


class CNIPodGone(Exception):
    """Excepton raised when Pod got deleted while processing a CNI request"""
    def __init__(self, name):
        super().__init__(
            f'Pod {name} got deleted while processing the CNI ADD request.')


class UnreachableOctavia(Exception):
    """Exception indicates Octavia API failure and can not be reached

    This exception is raised when Kuryr can not reach Octavia. The Octavia
    API call returns 'None' on the version field and we need to properly log
    a message informing the user
    """
    def __init__(self, message):
        super(UnreachableOctavia, self).__init__(message)
