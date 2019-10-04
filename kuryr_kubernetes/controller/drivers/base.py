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

import abc
import six

from kuryr.lib._i18n import _
from stevedore import driver as stv_driver

from kuryr_kubernetes import config

_DRIVER_NAMESPACE_BASE = 'kuryr_kubernetes.controller.drivers'
_DRIVER_MANAGERS = {}
_MULTI_VIF_DRIVERS = []


class DriverBase(object):
    """Base class for controller drivers.

    Subclasses must define an *ALIAS* attribute that is used to find a driver
    implementation by `get_instance` class method which utilises
    `stevedore.driver.DriverManager` with the namespace set to
    'kuryr_kubernetes.controller.drivers.*ALIAS*' and the name of
    the driver determined from the '[kubernetes]/*ALIAS*_driver' configuration
    parameter.

    Usage example:

        @six.add_metaclass(abc.ABCMeta)
        class SomeDriverInterface(DriverBase):
            ALIAS = 'driver_alias'

            @abc.abstractmethod
            def some_method(self):
                pass

        driver = SomeDriverInterface.get_instance()
        driver.some_method()
    """

    @classmethod
    def get_instance(cls, specific_driver=None, scope='default'):
        """Get an implementing driver instance.

        :param specific_driver: Loads a specific driver instead of using conf.
                                Uses separate manager entry so that loading of
                                default/other drivers is not affected.
        :param scope: Loads the driver in the given scope (if independent
                      instances of a driver are required)
        """

        alias = cls.ALIAS

        if specific_driver:
            driver_key = '{}:{}:{}'.format(alias, specific_driver, scope)
        else:
            driver_key = '{}:_from_cfg:{}'.format(alias, scope)

        try:
            manager = _DRIVER_MANAGERS[driver_key]
        except KeyError:
            driver_name = (specific_driver or
                           config.CONF.kubernetes[alias + '_driver'])

            manager = stv_driver.DriverManager(
                namespace="%s.%s" % (_DRIVER_NAMESPACE_BASE, alias),
                name=driver_name,
                invoke_on_load=True)
            _DRIVER_MANAGERS[driver_key] = manager

        driver = manager.driver
        if not isinstance(driver, cls):
            raise TypeError(_("Invalid %(alias)r driver type: %(driver)s, "
                              "must be a subclass of %(type)s") % {
                            'alias': alias,
                            'driver': driver.__class__.__name__,
                            'type': cls})
        return driver

    def __str__(self):
        return self.__class__.__name__


@six.add_metaclass(abc.ABCMeta)
class PodProjectDriver(DriverBase):
    """Provides an OpenStack project ID for Kubernetes Pod ports."""

    ALIAS = 'pod_project'

    @abc.abstractmethod
    def get_project(self, pod):
        """Get an OpenStack project ID for Kubernetes Pod ports.

        :param pod: dict containing Kubernetes Pod object
        :return: project ID
        """

        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class ServiceProjectDriver(DriverBase):
    """Provides an OpenStack project ID for Kubernetes Services."""

    ALIAS = 'service_project'

    @abc.abstractmethod
    def get_project(self, service):
        """Get an OpenStack project ID for Kubernetes Service.

        :param service: dict containing Kubernetes Service object
        :return: project ID
        """

        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class NamespaceProjectDriver(DriverBase):
    """Provides an OpenStack project ID for Kubernetes Namespace."""

    ALIAS = 'namespace_project'

    @abc.abstractmethod
    def get_project(self, namespace):
        """Get an OpenStack project ID for Kubernetes Namespace.

        :param service: dict containing Kubernetes Namespace object
        :return: project ID
        """

        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class PodSubnetsDriver(DriverBase):
    """Provides subnets for Kubernetes Pods."""

    ALIAS = 'pod_subnets'

    @abc.abstractmethod
    def get_subnets(self, pod, project_id):
        """Get subnets for Pod.

        :param pod: dict containing Kubernetes Pod object
        :param project_id: OpenStack project ID
        :return: dict containing the mapping 'subnet_id' -> 'network' for all
                 the subnets we want to create ports on, where 'network' is an
                 `os_vif.network.Network` object containing a single
                 `os_vif.subnet.Subnet` object corresponding to the 'subnet_id'
        """
        raise NotImplementedError()

    def create_namespace_network(self, namespace, project_id):
        """Create network resources for a namespace.

        :param namespace: string with the namespace name
        :param project_id: OpenStack project ID
        :return: dict with the keys and values for the CRD spec, such as
                 routerId or subnetId
        """
        raise NotImplementedError()

    def delete_namespace_subnet(self, kuryr_net_crd):
        """Delete network resources associated to a namespace.

        :param kuryr_net_crd: kuryrnet CRD obj dict that contains Neutron's
                              network resources associated to a namespace
        """
        raise NotImplementedError()

    def rollback_network_resources(self, crd_spec, namespace):
        """Rollback created network resources for a namespace.

        :param crd_spec: dict with the keys and values for the CRD spec, such
                         as routerId or subnetId
        :param namespace: name of the Kubernetes namespace object
        """
        raise NotImplementedError()

    def cleanup_namespace_networks(self, namespace):
        """Clean up network leftover on the namespace.

        Due to Kuryr controller restarts it may happen that some network
        resources are leftover. This method ensures they are deleted upon
        retries.

        :param namespace: name of the Kubernetes namespace object
        """
        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class ServiceSubnetsDriver(DriverBase):
    """Provides subnets for Kubernetes Services."""

    ALIAS = 'service_subnets'

    @abc.abstractmethod
    def get_subnets(self, service, project_id):
        """Get subnets for Service.

        :param service: dict containing Kubernetes Pod object
        :param project_id: OpenStack project ID
        :return: dict containing the mapping 'subnet_id' -> 'network' for all
                 the subnets we want to create ports on, where 'network' is an
                 `os_vif.network.Network` object containing a single
                 `os_vif.subnet.Subnet` object corresponding to the 'subnet_id'
        """
        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class PodSecurityGroupsDriver(DriverBase):
    """Provides security groups for Kubernetes Pods."""

    ALIAS = 'pod_security_groups'

    @abc.abstractmethod
    def get_security_groups(self, pod, project_id):
        """Get a list of security groups' IDs for Pod.

        :param pod: dict containing Kubernetes Pod object
        :param project_id: OpenStack project ID
        :return: list containing security groups' IDs
        """
        raise NotImplementedError()

    def create_namespace_sg(self, namespace, project_id, crd_spec):
        """Create security group resources for a namespace.

        :param namespace: string with the namespace name
        :param project_id: OpenStack project ID
        :param crd_spec: dict with the keys and values for the CRD spec, such
                         as subnetId or subnetCIDR
        :return: dict with the keys and values for the CRD spec, such as sgId.
        If no security group need to be created for the namespace, it
        should return an empty dict
        """
        raise NotImplementedError()

    def delete_sg(self, sg_id):
        """Delete security group associated to a namespace.

        :param sg_id: OpenStack security group ID
        """
        raise NotImplementedError()

    def create_sg_rules(self, pod):
        """Create security group rules for a pod.

        :param pod: dict containing Kubernetes Pod object
        :return: a list containing podSelectors of CRDs
        that had security group rules created
        """
        raise NotImplementedError()

    def delete_sg_rules(self, pod):
        """Delete security group rules for a pod

        :param pod: dict containing Kubernetes Pod object
        :return: a list containing podSelectors of CRDs
        that had security group rules deleted
        """
        raise NotImplementedError()

    def update_sg_rules(self, pod):
        """Update security group rules for a pod

        :param pod: dict containing Kubernetes Pod object
        :return: a list containing podSelectors of CRDs
        that had security group rules updated
        """
        raise NotImplementedError()

    def delete_namespace_sg_rules(self, namespace):
        """Delete security group rule associated to a namespace.

        :param namespace: dict containing K8S Namespace object
        """
        raise NotImplementedError()

    def create_namespace_sg_rules(self, namespace):
        """Create security group rule associated to a namespace.

        :param namespace: dict containing K8S Namespace object
        """
        raise NotImplementedError()

    def update_namespace_sg_rules(self, namespace):
        """Update security group rule associated to a namespace.

        :param namespace: dict containing K8S Namespace object
        """
        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class ServiceSecurityGroupsDriver(DriverBase):
    """Provides security groups for Kubernetes Services."""

    ALIAS = 'service_security_groups'

    @abc.abstractmethod
    def get_security_groups(self, service, project_id):
        """Get a list of security groups' IDs for Service.

        :param service: dict containing Kubernetes Service object
        :param project_id: OpenStack project ID
        :return: list containing security groups' IDs
        """
        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class PodVIFDriver(DriverBase):
    """Manages Neutron ports to provide VIFs for Kubernetes Pods."""

    ALIAS = 'pod_vif'

    @abc.abstractmethod
    def request_vif(self, pod, project_id, subnets, security_groups):
        """Links Neutron port to pod and returns it as VIF object.

        Implementing drivers must ensure the Neutron port satisfying the
        requested parameters is present and is valid for specified `pod`. It
        is up to the implementing drivers to either create new ports on each
        request or reuse available ports when possible.

        Implementing drivers may return a VIF object with its `active` field
        set to 'False' to indicate that Neutron port requires additional
        actions to enable network connectivity after VIF is plugged (e.g.
        setting up OpenFlow and/or iptables rules by OpenVSwitch agent). In
        that case the Controller will call driver's `activate_vif` method
        and the CNI plugin will block until it receives activation
        confirmation from the Controller.

        :param pod: dict containing Kubernetes Pod object
        :param project_id: OpenStack project ID
        :param subnets: dict containing subnet mapping as returned by
                        `PodSubnetsDriver.get_subnets`. If multiple entries
                        are present in that mapping, it is guaranteed that
                        all entries have the same value of `Network.id`.
        :param security_groups: list containing security groups' IDs as
                                returned by
                                `PodSecurityGroupsDriver.get_security_groups`
        :return: VIF object
        """
        raise NotImplementedError()

    def request_vifs(self, pod, project_id, subnets, security_groups,
                     num_ports):
        """Creates Neutron ports for pods and returns them as VIF objects list.

        It follows the same pattern as request_vif but creating the specified
        amount of ports and vif objects at num_ports parameter.

        The port creation request is generic as it not going to be used by the
        pod -- at least not all of them. Additionally, in order to save Neutron
        calls, the ports creation is handled in a bulk request.

        :param pod: dict containing Kubernetes Pod object
        :param project_id: OpenStack project ID
        :param subnets: dict containing subnet mapping as returned by
                        `PodSubnetsDriver.get_subnets`. If multiple entries
                        are present in that mapping, it is guaranteed that
                        all entries have the same value of `Network.id`.
        :param security_groups: list containing security groups' IDs as
                                returned by
                                `PodSecurityGroupsDriver.get_security_groups`
        :param num_ports: number of ports to be created
        :return: VIF objects list
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def release_vif(self, pod, vif, project_id=None, security_groups=None):
        """Unlinks Neutron port corresponding to VIF object from pod.

        Implementing drivers must ensure the port is either deleted or made
        available for reuse by `PodVIFDriver.request_vif`.

        :param pod: dict containing Kubernetes Pod object
        :param vif: VIF object as returned by `PodVIFDriver.request_vif`
        :param project_id: OpenStack project ID
        :param security_groups: list containing security groups'
                                IDs as returned by
                                `PodSecurityGroupsDriver.get_security_groups`
        """
        raise NotImplementedError()

    def release_vifs(self, pods, vifs, project_id=None, security_groups=None):
        """Unlinks Neutron ports corresponding to VIF objects.

         It follows the same pattern as release_vif but releasing num_ports
         ports. Ideally it will also make use of bulk request to save Neutron
         calls in the release/recycle process.
        :param pods: list of dict containing Kubernetes Pod objects
        :param vifs: list of VIF objects as returned by
                     `PodVIFDriver.request_vif`
        :param project_id: (optional) OpenStack project ID
        :param security_groups: (optional) list containing security groups'
                                IDs as returned by
                                `PodSecurityGroupsDriver.get_security_groups`
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def activate_vif(self, pod, vif):
        """Updates VIF to become active.

        Implementing drivers should update the specified `vif` object's
        `active` field to 'True' but must ensure that the corresponding
        Neutron port is fully configured (i.e. the container using the `vif`
        can access the requested network resources).

        Implementing drivers may raise `ResourceNotReady` exception to
        indicate that port activation should be retried later which will
        cause `activate_vif` to be called again with the same arguments.

        This method may be called before, after or while the VIF is being
        plugged by the CNI plugin.

        :param pod: dict containing Kubernetes Pod object
        :param vif: VIF object as returned by `PodVIFDriver.request_vif`
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def update_vif_sgs(self, pod, security_groups):
        """Update VIF security groups.

        Implementing drivers should update the port associated to the pod
        with the specified security groups.

        :param pod: dict containing Kubernetes Pod object
        :param security_groups: list containing security groups' IDs as
                                returned by
                                `PodSecurityGroupsDriver.get_security_groups`
        """
        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class MultiVIFDriver(DriverBase):
    """Manages additional ports of Kubernetes Pods."""

    ALIAS = 'multi_vif'

    @abc.abstractmethod
    def request_additional_vifs(
            self, pod, project_id, security_groups):
        """Links Neutron ports to pod and returns them as a list of VIF objects.

        Implementing drivers must be able to parse the additional interface
        definition from pod. The format of the definition is up to the
        implementation of each driver. Then implementing drivers must invoke
        the VIF drivers to either create new Neutron ports on each request or
        reuse available ports when possible.

        :param pod: dict containing Kubernetes Pod object
        :param project_id: OpenStack project ID
        :param security_groups: list containing security groups' IDs as
                                returned by
                                `PodSecurityGroupsDriver.get_security_groups`
        :return: VIF object list
        """
        raise NotImplementedError()

    @classmethod
    def get_enabled_drivers(cls):
        if _MULTI_VIF_DRIVERS:
            pass
        else:
            drivers = config.CONF.kubernetes['multi_vif_drivers']
            for driver in drivers:
                _MULTI_VIF_DRIVERS.append(cls.get_instance(driver))
        return _MULTI_VIF_DRIVERS


class LBaaSDriver(DriverBase):
    """Base class for Openstack loadbalancer services."""

    ALIAS = 'endpoints_lbaas'

    @abc.abstractmethod
    def get_service_loadbalancer_name(self, namespace, svc_name):
        """Generate name of a load balancer that represents K8S service.

        In case a load balancer represents K8S service/ep, the handler
        should call first this API to get the load balancer name and use the
        return value of this function as 'name' parameter for the
        'ensure_loadbalancer' function

        :param namespace: K8S service namespace
        :param svc_name: K8S service name
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def ensure_loadbalancer(self, name, project_id, subnet_id, ip,
                            security_groups_ids, service_type, provider):
        """Get or create load balancer.

        :param name: LoadBlancer name
        :param project_id: OpenStack project ID
        :param subnet_id: Neutron subnet ID to host load balancer
        :param ip: IP of the load balancer
        :param security_groups_ids: security groups that should be allowed
                                    access to the load balancer
        :param service_type: K8s service type (ClusterIP or LoadBalancer)
        :param provider: load balancer backend service
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def release_loadbalancer(self, loadbalancer):
        """Release load balancer.

        Should return without errors if load balancer does not exist (e.g.
        already deleted).

        :param loadbalancer: `LBaaSLoadBalancer` object
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def ensure_listener(self, loadbalancer, protocol, port):
        """Get or create listener.

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param protocol: listener's protocol (only TCP is supported for now)
        :param port: listener's port
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def release_listener(self, loadbalancer, listener):
        """Release listener.

        Should return without errors if listener or load balancer does not
        exist (e.g. already deleted).

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param listener: `LBaaSListener` object
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def ensure_pool(self, loadbalancer, listener):
        """Get or create pool attached to Listener.

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param listener: `LBaaSListener` object
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def ensure_pool_attached_to_lb(self, loadbalancer, namespace,
                                   svc_name, protocol):
        """Get or create pool attached to LoadBalancer.

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param namespace: K8S service's namespace
        :param svc_name: K8S service's name
        :param protocol: pool's protocol
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_loadbalancer_pool_name(self, loadbalancer, namespace, svc_name):
        """Get name of a load balancer's pool attached to LB.

        The pool's name should be unique per K8S service

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param namespace: K8S service's namespace
        :param svc_name: K8S service's name
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def release_pool(self, loadbalancer, pool):
        """Release pool.

        Should return without errors if pool or load balancer does not exist
        (e.g. already deleted).

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param pool: `LBaaSPool` object
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def ensure_member(self, loadbalancer, pool,
                      subnet_id, ip, port, target_ref_namespace,
                      target_ref_name):
        """Get or create member.

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param pool: `LBaaSPool` object
        :param subnet_id: Neutron subnet ID of the target
        :param ip: target's IP (e.g. Pod's IP)
        :param port: target port
        :param target_ref_namespace: Kubernetes EP target_ref namespace
        :param target_ref_name: Kubernetes EP target_ref name
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def release_member(self, loadbalancer, member):
        """Release member.

        Should return without errors if memberor load balancer does not exist
        (e.g. already deleted).

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param member: `LBaaSMember` object
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_lb_by_uuid(self, lb_uuid):
        """Get loadbalancer by loadbalancer uuid.

        :param lb_uuid: Loadbalancer uuid
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_pool_by_name(self, pool_name, project_id):
        """Get pool by pool's name.

        :param pool_name: the pool name
        :param project_id: project id
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def ensure_l7_policy(self, namespace, route_name, loadbalancer,
                         pool, listener_id):
        """Get or create L7 policy.

        :param namespace: ocp-route/k8s-ingress namespace
        :param route_name: ocp-route/k8s-ingress name
        :param loadbalancer: `LBaaSLoadBalancer` object
        :param pool: L7 policy's target pool
        :param listener_id: ID of listener to attach L7policy to

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def release_l7_policy(self, loadbalancer, l7_policy):
        """Release l7policy.

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param l7_policy: `LBaaSL7Policy` object

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def ensure_l7_rule(self, loadbalancer, l7_policy, compare_type,
                       type, value):
        """Get or create L7 rule.

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param l7_policy: `LBaaSL7Policy` object
        :param compare_type: comparison type for the L7 rule.
        :param type: the L7 rule type
        :param value:the value to use for the comparison.

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def release_l7_rule(self, loadbalancer, l7_rule):
        """Release L7 rule.

        :param loadbalancer: `LBaaSLoadBalancer` object
        :param l7_rule: `LBaaSL7Rule` object

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def update_l7_rule(self, l7_rule, new_value):
        """Update L7 rule value.

        :param l7_rule: `LBaaSL7Rule` object
        :param new_value: rule's new value

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def is_pool_used_by_other_l7policies(self, l7policy, pool):
        """Checks if pool used by other L7policy.

        :param l7policy: `LBaaSL7Policy` object
        :param pool: `LBaaSPool` object

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def update_lbaas_sg(self, service, sgs):
        """Update security group rules associated to the loadbalancer

        :param service: k8s service object
        :param sgs: list of security group ids to use for updating the rules
        """
        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class VIFPoolDriver(PodVIFDriver):
    """Manages Pool of Neutron ports to provide VIFs for Kubernetes Pods."""

    ALIAS = 'vif_pool'

    @abc.abstractmethod
    def set_vif_driver(self, driver):
        """Sets the driver the Pool should use to manage resources

        The driver will be used for acquiring, releasing and updating the
        vif resources.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def remove_sg_from_pools(self, sg_id, net_id):
        """Remove the SG from the ports associated to the pools.

        This method ensure that ports on net_id that belongs to pools and have
        the referenced SG are updated to clean up their SGs and put back on
        the default pool for that network.

        :param sg_id: Security Group ID that needs to be removed from pool
                      ports
        :param net_id: Network ID associated to the pools to clean up, and
                       where the ports must belong to.
        """
        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class ServicePubIpDriver(DriverBase):
    """Manages loadbalancerIP/public ip for neutron lbaas."""

    ALIAS = 'service_public_ip'

    @abc.abstractmethod
    def acquire_service_pub_ip_info(self, spec_type, spec_lb_ip, project_id,
                                    port_id_to_be_associated=None):
        """Get k8s service loadbalancer IP info based on service spec

        :param spec_type: service.spec.type field
        :param spec_lb_ip: service spec LoadBlaceIP field
        :param project_id: openstack project id
        :param port_id_to_be_associated: port id to associate

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def release_pub_ip(self, service_pub_ip_info):
        """Release (if needed) based on service_pub_ip_info content

        :param service_pub_ip_info: service loadbalancer IP info
        :returns True/False

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def associate_pub_ip(self, service_pub_ip_info, vip_port_id):
        """Associate loadbalancer IP to lbaas VIP port ID

        :param service_pub_ip_info: service loadbalancer IP info
        :param vip_port_id: Lbaas VIP port id

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def disassociate_pub_ip(self, service_pub_ip_info):
        """Disassociate loadbalancer IP and lbaas VIP port ID

        :param service_pub_ip_info: service loadbalancer IP info

        """


@six.add_metaclass(abc.ABCMeta)
class NetworkPolicyDriver(DriverBase):
    """Provide network-policy for pods"""

    ALIAS = 'network_policy'

    @abc.abstractmethod
    def ensure_network_policy(self, policy, project_id):
        """Policy created or updated

        :param policy: dict containing Kubernetes NP object
        :param project_id: openstack project_id
        :returns: list of Pod objects affected by the network policy
        creation or its podSelector modification
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def release_network_policy(self, kuryrnetpolicy):
        """Delete a network policy

        :param kuryrnetpolicy: dict containing Kuryrnetpolicy CRD object
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def affected_pods(self, policy, selector=None):
        """Return affected pods by the policy

        This method returns the list of pod objects affected by the policy, or
        by the selector if it is specified.

        :param policy: dict containing Kubernetes NP object
        :param selector: (optional) specifc pod selector
        :returns: list of Pods objects affected by the policy or the selector
                  if it is passed
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def knps_on_namespace(self, namespace):
        """Check if there si kuryr network policy CRDs on the namespace

        This method returns true if there are knps on the specified namespace
        or false otherwise

        :param namespace: namespace name where the knps CRDs should be
        :returns: true if knps CRDs on the namespace, false otherwise
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def namespaced_pods(self, policy):
        """Return pods on the policy namespace

        This method returns the pods on the network policy namespace

        :param policy: dict containing Kubernetes NP object
        :returns: list of Pods objects on the policy namespace
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_kuryrnetpolicy_crd(self, policy):
        """Return kuryrnetpolicy CRD object associated to the policy

        :param policy: dict containing Kubernetes NP object
        :returns: kuryrnetpolicy CRD object associated to the policy
        """
        raise NotImplementedError()


@six.add_metaclass(abc.ABCMeta)
class NetworkPolicyProjectDriver(DriverBase):
    """Get an OpenStack project id for K8s network policies"""

    ALIAS = 'network_policy_project'

    @abc.abstractmethod
    def get_project(self, policy):
        """Get an OpenStack project id for K8s pod ports.

        :param policy: dict containing Kubernetes NP object
        :returns: OpenStack project_id
        """
        raise NotImplementedError()
