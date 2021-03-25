=====================================================
How to configure Listener timeouts for Load Balancers
=====================================================

By default, Kuryr uses the default Octavia timeout-client-data and
timeout-member-data values when creating or modifying loadbalancers.
To change the timeout values used in creating or modifying a particular
service:

Set the new timeout values for openstack.org/kuryr-timeout-client-data and
openstack.org/kuryr-timeout-member-data in the service annotation as seen in
the service manifest below. This specification sets the timeout-client-data
and the timeout-member-data to '70000' and '75000' respectively.

.. code-block:: yaml

   apiVersion: v1
   kind: Service
   metadata:
     name: kuryr-demo
     annotations:
       openstack.org/kuryr-timeout-client-data: '70000'
       openstack.org/kuryr-timeout-member-data: '75000'
   spec:
     selector:
       app: server
     ports:
       - protocol: TCP
         port: 80
         targetPort: 8080

.. note::

   The listener timeout values can be reset to the defaults by removing the
   sevice annotations for the timeout values.

Setting the timeouts via ConfigMap
----------------------------------

Alternatively, you can change the value of the timeout-client-data and/or the
timeout-member-data on the Kuryr ConfigMap. This option is ideal if the new
timeout values will be used for multiple loadbalancers. On DevStack deployment,
the Kuryr ConfigMap can be edited using:

.. code-block:: console

   $ kubectl -n kube-system edit cm kuryr-config

The listener timeouts then needs to be changed at the ConfigMap:

.. code-block:: bash

   [octavia_defaults]
   timeout_member_data = 0
   timeout_client_data = 0

Another option is to set the listener timeouts at the local.conf file.

.. code-block:: bash

   #KURYR_TIMEOUT_CLIENT_DATA=0
   #KURYR_TIMEOUT_MEMBER_DATA=0

.. note::

   The listener timeouts values set via the ConfigMap or set at the local.conf
   can be overridden by values set in the service annotations for a particular
   service.
