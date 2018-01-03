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
regarding the maximum and minimum desired sizes of the pools, where the
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

Note that for the containerized deployment, you need to edit the associated
ConfigMap to change the kuryr.conf files with::

      kubectl -n kube-system edit cm kuryr-config

Then modify the kuryr.conf (not the kuryr-cni.conf) to modify the controller
configuration regarding the pools. After that, to have the new configuration
applied you need to restart the kuryr-controller just by killing the existing
pod::

      kubectl -n kube-system get pod | grep kuryr-controller
      kubectl -n kube-system delete pod KURYR_CONTROLLER_POD_NAME


Ports loading into pools
------------------------

Pre-created ports for the pools will be loaded and put back into their
respective pools upon controller restart. This allows the pre-creation of
neutron ports (or subports for the nested case) with a script or any other
preferred tool (e.g., heat templates) and load them into their respective
pools just by restarting the kuryr-controller (or even before installing it).
To do that you just need to ensure the ports are created with the right
device_owner:

    - For neutron pod driver: compute:kuryr (of the value at
      kuryr.lib.constants.py)

    - For nested-vlan pod driver: trunk:subport or compute:kuryr (or the value
      at kuryr.lib.constants.py). But in this case they also need to be
      attached to an active neutron trunk port, i.e., they need to be subports
      of an existing trunk


Subports pools management tool
------------------------------

Note there is a developers tool available at `contrib/pools-management` to
create/delete ports in the desired pool(s) as well as to control the amount of
existing ports loaded into each pool. For more details on this read the readme
file on that folder.
