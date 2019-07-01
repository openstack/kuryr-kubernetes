================================
Kuryr Kubernetes OVN Integration
================================

OVN provides virtual networking for Open vSwitch and is a component of the Open
vSwitch project.

OpenStack can use OVN as its network management provider through the Modular
Layer 2 (ML2) north-bound plug-in.

Integrating of OVN allows Kuryr to be used to bridge (both baremetal and
nested) containers and VM networking in a OVN-based OpenStack deployment.


Testing with DevStack
=====================

The next points describe how to test OpenStack with OVN using DevStack.
We will start by describing how to test the baremetal case on a single host,
and then cover a nested environment where containers are created inside VMs.

Single Node Test Environment
----------------------------

1. Create a test system.

It's best to use a throwaway dev system for running DevStack. Your best bet is
to use either CentOS 7 or the latest Ubuntu LTS (16.04, Xenial).

2. Create the ``stack`` user.

::

     $ git clone https://opendev.org/openstack-dev/devstack.git
     $ sudo ./devstack/tools/create-stack-user.sh

3. Switch to the ``stack`` user and clone DevStack and kuryr-kubernetes.

::

     $ sudo su - stack
     $ git clone https://opendev.org/openstack-dev/devstack.git
     $ git clone https://opendev.org/openstack/kuryr-kubernetes.git

4. Configure DevStack to use OVN.

kuryr-kubernetes comes with a sample DevStack configuration file for OVN you
can start with. For example, you may want to set some values for the various
PASSWORD variables in that file, or change the LBaaS service provider to use.
Feel free to edit it if you'd like, but it should work as-is.

::

    $ cd devstack
    $ cp ../kuryr-kubernetes/devstack/local.conf.ovn.sample local.conf


Note that due to OVN compiling OVS from source at
/usr/local/var/run/openvswitch we need to state at the local.conf that the path
is different from the default one (i.e., /var/run/openvswitch).

Optionally, the ports pool functionality can be enabled by following:
:doc:`./ports-pool`

5. Run DevStack.

This is going to take a while. It installs a bunch of packages, clones a bunch
of git repos, and installs everything from these git repos.

::

    $ ./stack.sh

Once DevStack completes successfully, you should see output that looks
something like this::

    This is your host IP address: 192.168.5.10
    This is your host IPv6 address: ::1
    Keystone is serving at http://192.168.5.10/identity/
    The default users are: admin and demo
    The password: pass


6. Extra configurations.

Devstack does not wire up the public network by default so we must do
some extra steps for floating IP usage as well as external connectivity:

::

    $ sudo ip link set br-ex up
    $ sudo ip route add 172.24.4.0/24 dev br-ex
    $ sudo ip addr add 172.24.4.1/24 dev br-ex


Then you can create forwarding and NAT rules that will cause "external"
traffic from your instances to get rewritten to your network controller's
ip address and sent out on the network:

::

    $ sudo iptables -A FORWARD -d 172.24.4.0/24 -j ACCEPT
    $ sudo iptables -A FORWARD -s 172.24.4.0/24 -j ACCEPT
    $ sudo iptables -t nat -I POSTROUTING 1 -s 172.24.4.1/24 -j MASQUERADE


Inspect default Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In order to check the default configuration, in term of networks, subnets,
security groups and loadbalancers created upon a successful devstack stacking,
you can check the :doc:`../default_configuration`

Testing Network Connectivity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once the environment is ready, we can test that network connectivity works
among pods. To do that check out :doc:`../testing_connectivity`


Nested Containers Test Environment (VLAN)
-----------------------------------------

Another deployment option is the nested-vlan where containers are created
inside OpenStack VMs by using the Trunk ports support. Thus, first we need to
deploy an undercloud devstack environment with the needed components to
create VMs (e.g., Glance, Nova, Neutron, Keystone, ...), as well as the needed
OVN configurations such as enabling the trunk support that will be needed for
the VM. And then install the overcloud deployment inside the VM with the kuryr
components.


Undercloud deployment
~~~~~~~~~~~~~~~~~~~~~

The steps to deploy the undercloud environment are the same described above
for the `Single Node Test Environment` with the different of the sample
local.conf to use (step 4), in this case::

    $ cd devstack
    $ cp ../kuryr-kubernetes/devstack/local.conf.pod-in-vm.undercloud.ovn.sample local.conf


The main differences with the default ovn local.conf sample are that:

    - There is no need to enable the kuryr-kubernetes plugin as this will be
      installed inside the VM (overcloud).

    - There is no need to enable the kuryr related services as they will also
      be installed inside the VM: kuryr-kubernetes, kubelet,
      kubernetes-api, kubernetes-controller-manager, kubernetes-scheduler and
      kubelet.

    - Nova and Glance components need to be enabled to be able to create the VM
      where we will install the overcloud.

    - OVN Trunk service plugin need to be enable to ensure Trunk ports support.


Once the undercloud deployment has finished, the next steps are related to
create the overcloud VM by using a parent port of a Trunk so that containers
can be created inside with their own networks. To do that we follow the next
steps detailed at :doc:`../trunk_ports`


Overcloud deployment
~~~~~~~~~~~~~~~~~~~~

Once the VM is up and running, we can start with the overcloud configuration.
The steps to perform are the same as without OVN integration, i.e., the
same steps as for ML2/OVS:

1. Log in into the VM::

    $ ssh -i id_rsa_demo centos@FLOATING_IP

2. Deploy devstack following steps 3 and 4 detailed at :doc:`./nested-vlan`


Testing Nested Network Connectivity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Similarly to the baremetal testing, we can create a demo deployment at the
overcloud VM, scale it to any number of pods and expose the service to check if
the deployment was successful. To do that check out
:doc:`../testing_nested_connectivity`
