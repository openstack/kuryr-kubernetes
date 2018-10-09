How to try out nested-pods locally (VLAN + trunk)
=================================================

Following are the instructions for an all-in-one setup where Kubernetes will also be
running inside the same Nova VM in which Kuryr-controller and Kuryr-cni will be
running. 4GB memory and 2 vCPUs, is the minimum resource requirement for the VM:

1. To install OpenStack services run devstack with ``devstack/local.conf.pod-in-vm.undercloud.sample``.
   Ensure that "trunk" service plugin is enabled in ``/etc/neutron/neutron.conf``::

    [DEFAULT]
    service_plugins = neutron.services.l3_router.l3_router_plugin.L3RouterPlugin,neutron.services.trunk.plugin.TrunkPlugin

2. Launch a VM with `Neutron trunk port. <https://wiki.openstack.org/wiki/Neutron/TrunkPort>`_.
   The next steps can be followed: `Boot VM with a Trunk Port`_.

.. _Boot VM with a Trunk Port: https://docs.openstack.org/kuryr-kubernetes/latest/installation/trunk_ports.html

3. Inside VM, install and setup Kubernetes along with Kuryr using devstack:
    - Since undercloud Neutron will be used by pods, Neutron services should be
      disabled in localrc.
    - Run devstack with ``devstack/local.conf.pod-in-vm.overcloud.sample``.
      but first fill in the needed information:

        - Point to the undercloud deployment by setting::

            SERVICE_HOST=UNDERCLOUD_CONTROLLER_IP


        - Fill in the subnetpool id of the undercloud deployment, as well as
          the router where the new pod and service networks need to be
          connected::

            KURYR_NEUTRON_DEFAULT_SUBNETPOOL_ID=UNDERCLOUD_SUBNETPOOL_V4_ID
            KURYR_NEUTRON_DEFAULT_ROUTER=router1

        - Ensure the nested-vlan driver is going to be set by setting::

            KURYR_POD_VIF_DRIVER=nested-vlan

        - Optionally, the ports pool funcionality can be enabled by following:
          `How to enable ports pool with devstack`_.

        .. _How to enable ports pool with devstack: https://docs.openstack.org/kuryr-kubernetes/latest/installation/devstack/ports-pool.html

        - [OPTIONAL] If you want to enable the subport pools driver and the
          VIF Pool Manager you need to include::

            KURYR_VIF_POOL_MANAGER=True


4. Once devstack is done and all services are up inside VM. Next steps are to
   configure the missing information at ``/etc/kuryr/kuryr.conf``:

    - Configure worker VMs subnet::

       [pod_vif_nested]
       worker_nodes_subnet = <UNDERCLOUD_SUBNET_WORKER_NODES_UUID>

    - Configure binding section::

       [binding]
       driver = kuryr.lib.binding.drivers.vlan
       link_iface = <VM interface name eg. eth0>

    - Restart kuryr-k8s-controller::

       sudo systemctl restart devstack@kuryr-kubernetes.service

    - Restart kuryr-daemon::

       sudo systemctl restart devstack@kuryr-daemon.service

Now launch pods using kubectl, Undercloud Neutron will serve the networking.
