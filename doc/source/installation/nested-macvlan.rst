How to try out nested-pods locally (MACVLAN)
============================================

Following are the instructions for an all-in-one setup, using the
nested MACVLAN driver rather than VLAN and trunk ports.

1. To install OpenStack services run devstack with ``devstack/local.conf.pod-in-vm.undercloud.sample``.
2. Launch a Nova VM with MACVLAN support

.. todo::
    Add a list of neutron commands, required to launch a such a VM

3. Log into the VM and set up Kubernetes along with Kuryr using devstack:
    - Since undercloud Neutron will be used by pods, Neutron services should be
      disabled in localrc.
    - Run devstack with ``devstack/local.conf.pod-in-vm.overcloud.sample``.
      With this config devstack will not configure Neutron resources for the
      local cloud. These variables have to be added manually
      to ``/etc/kuryr/kuryr.conf``.

4. Once devstack is done and all services are up inside VM:
    - Configure ``/etc/kuryr/kuryr.conf`` with the following content, replacing
      the values with correct UUIDs of Neutron resources from the undercloud::

       [neutron_defaults]
       pod_security_groups = <UNDERCLOUD_DEFAULT_SG_UUID>
       pod_subnet = <UNDERCLOUD_SUBNET_FOR_PODS_UUID>
       project = <UNDERCLOUD_DEFAULT_PROJECT_UUID>
       service_subnet = <UNDERCLOUD_SUBNET_FOR_SERVICES_UUID>

    - Configure worker VMs subnet::

       [pod_vif_nested]
       worker_nodes_subnet = <UNDERCLOUD_SUBNET_WORKER_NODES_UUID>

    - Configure "pod_vif_driver" as "nested-macvlan"::

       [kubernetes]
       pod_vif_driver = nested-macvlan

    - Configure binding section::

       [binding]
       link_iface = <VM interface name eg. eth0>

    - Restart kuryr-k8s-controller::

       sudo systemctl restart devstack@kuryr-kubernetes.service

Now launch pods using kubectl, Undercloud Neutron will serve the networking.

