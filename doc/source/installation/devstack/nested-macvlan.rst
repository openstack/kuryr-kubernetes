============================================
How to try out nested-pods locally (MACVLAN)
============================================

Following are the instructions for an all-in-one setup, using the
nested MACVLAN driver rather than VLAN and trunk ports.

#. To install OpenStack services run devstack with
   ``devstack/local.conf.pod-in-vm.undercloud.sample``.
#. Launch a Nova VM with MACVLAN support

   .. todo::

      Add a list of neutron commands, required to launch a such a VM

#. Log into the VM and set up Kubernetes along with Kuryr using devstack:
    - Since undercloud Neutron will be used by pods, Neutron services should be
      disabled in localrc.
    - Run devstack with ``devstack/local.conf.pod-in-vm.overcloud.sample``.
      Fill in the needed information, such as the subnet pool id to use or the
      router.

#. Once devstack is done and all services are up inside VM. Next steps are to
   configure the missing information at ``/etc/kuryr/kuryr.conf``:

   - Configure worker VMs subnet:

     .. code-block:: ini

        [pod_vif_nested]
        worker_nodes_subnets = <UNDERCLOUD_SUBNET_WORKER_NODES_UUID>

   - Configure "pod_vif_driver" as "nested-macvlan":

     .. code-block:: ini

        [kubernetes]
        pod_vif_driver = nested-macvlan

   - Configure binding section:

     .. code-block:: ini

        [binding]
        link_iface = <VM interface name eg. eth0>

   - Restart kuryr-k8s-controller:

     .. code-block:: console

        $ sudo systemctl restart devstack@kuryr-kubernetes.service

Now launch pods using kubectl, Undercloud Neutron will serve the networking.
