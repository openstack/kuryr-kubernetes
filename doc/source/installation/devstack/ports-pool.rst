======================================
How to enable ports pool with devstack
======================================

To enable the utilization of the ports pool feature through devstack, the next
options needs to be set at the local.conf file:

#. First, you need to enable the pools by setting:

   .. code-block:: bash

      KURYR_USE_PORT_POOLS=True

#. Then, the proper pool driver needs to be set. This means that for the
   baremetal case you need to ensure the pod vif driver and the vif pool driver
   are set to the right baremetal drivers, for instance:

   .. code-block:: bash

      KURYR_POD_VIF_DRIVER=neutron-vif
      KURYR_VIF_POOL_DRIVER=neutron

   And if the use case is the nested one, then they should be set to:

   .. code-block:: bash

      KURYR_POD_VIF_DRIVER=nested-vlan
      KURYR_VIF_POOL_DRIVER=nested

#. Then, in case you want to set a limit to the maximum number of ports, or
   increase/reduce the default one for the minimum number, as well as to modify
   the way the pools are repopulated, both in time as well as regarding bulk
   operation sizes, the next option can be included and modified accordingly:

   .. code-block:: bash

      KURYR_PORT_POOL_MIN=5
      KURYR_PORT_POOL_MAX=0
      KURYR_PORT_POOL_BATCH=10
      KURYR_PORT_POOL_UPDATE_FREQ=20
