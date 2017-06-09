How to try out nested-pods locally (VLAN + trunk)
=================================================

Following are the instructions for an all-in-one setup where K8s will also be
running inside the same Nova VM in which Kuryr-controller and Kuryr-cni will be
running. 4GB memory and 2 vCPUs, is the minimum resource requirement for the VM:

1. To install OpenStack services run devstack with ``devstack/local.conf.pod-in-vm.undercloud.sample``.
   Ensure that "trunk" service plugin is enabled in ``/etc/neutron/neutron.conf``::

    [DEFAULT]
    service_plugins = neutron.services.l3_router.l3_router_plugin.L3RouterPlugin,neutron.services.trunk.plugin.TrunkPlugin

2. Launch a VM with `Neutron trunk port. <https://wiki.openstack.org/wiki/Neutron/TrunkPort>`_

.. todo::
    Add a list of neutron commands, required to launch a trunk port

3. Inside VM, install and setup Kubernetes along with Kuryr using devstack:
    - Since undercloud Neutron will be used by pods, Neutron services should be
      disabled in localrc.
    - Run devstack with ``devstack/local.conf.pod-in-vm.overcloud.sample``.
      With this config devstack will not configure Neutron resources for the
      local cloud. These variables have to be added manually
      to ``/etc/kuryr/kuryr.conf``.

4. Once devstack is done and all services are up inside VM:
    - Configure ``/etc/kuryr/kuryr.conf`` to set UUID of Neutron resources from undercloud Neutron::

       [neutron_defaults]
       ovs_bridge = br-int
       pod_security_groups = <UNDERCLOUD_DEFAULT_SG_UUID>
       pod_subnet = <UNDERCLOUD_SUBNET_FOR_PODS_UUID>
       project = <UNDERCLOUD_DEFAULT_PROJECT_UUID>
       service_subnet = <UNDERCLOUD_SUBNET_FOR_SERVICES_UUID>

    - Configure worker VMs subnet::

       [pod_vif_nested]
       worker_nodes_subnet = <UNDERCLOUD_SUBNET_WORKER_NODES_UUID>

    - Configure "pod_vif_driver" as "nested-vlan"::

       [kubernetes]
       pod_vif_driver = nested-vlan

    - Configure binding section::

       [binding]
       driver = kuryr.lib.binding.drivers.vlan
       link_iface = <VM interface name eg. eth0>

    - Restart kuryr-k8s-controller::

       sudo systemctl restart devstack@kuryr-kubernetes.service

Now launch pods using kubectl, Undercloud Neutron will serve the networking.





