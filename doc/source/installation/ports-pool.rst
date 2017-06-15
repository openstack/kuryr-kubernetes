How to enable ports pool support
================================

To enable the utilization of the ports pool feature, the selected pool driver
needs to be included at the kuryr.conf at the kubernetes section. So, for the
baremetal deployment::

       [kubernetes]
       vif_pool_driver = neutron

And for the nested (VLAN+Trunk) case::

       [kubernetes]
       vif_pool_driver = nested

On the other hand, there are a few extra (optional) configuration options
regarding the maximum and minimun desired sizes of the pools, where the
maximum size can be disabled by setting it to 0::

       [vif_pool]
       ports_pool_max = 10
       ports_pool_min = 5

In addition the size of the bulk operation, e.g., the number
of ports created in a bulk request upon pool population, can be modified::

       [vif_pool]
       ports_pool_batch = 5

Note this value should be smaller than the ports_pool_max (if the
ports_pool_max is enabled).

Finally, the interval between pools updating actions (in seconds) can be
modified, and it should be adjusted based on your specific deployment, e.g., if
the port creation actions are slow, it is desirable to raise it in order not to
have overlapping actions. As a simple rule of thumbs, the frequency should be
at least as large as the time needed to perform the bulk requests (ports
creation, including subports attachment for the nested case)::

       [vif_pool]
       ports_pool_update_frequency = 20

After these configurations, the final step is to restart the
kuryr-k8s-controller. At devstack deployment::

       sudo systemctl restart devstack@kuryr-kubernetes.service

And for RDO packaging based installations::

      sudo systemctl restart kuryr-controller
