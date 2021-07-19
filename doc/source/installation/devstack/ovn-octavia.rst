=======================================================
How to enable OVN Octavia provider driver with devstack
=======================================================

To enable the utilization of OVN as the provider driver for Octavia through
devstack:

#. You can start with the sample DevStack configuration file for OVN
   that kuryr-kubernetes comes with.

   .. code-block:: console

      $ curl https://opendev.org/openstack/kuryr-kubernetes/raw/branch/master/devstack/local.conf.sample \
        -o devstack/local.conf

#. In case you want more Kuryr specific features than provided by the default
   handlers and more handlers are enabled, for example, the following enables
   NetworkPolicies in addition to the default features:

   .. code-block:: bash

      KURYR_ENABLED_HANDLERS=vif,kuryrport,service,endpoints,kuryrloadbalancer,
      namespace,pod_label,policy,kuryrnetworkpolicy,kuryrnetwork

   Then, the proper subnet drivers need to be set:

   .. code-block:: bash

      KURYR_SG_DRIVER=policy
      KURYR_SUBNET_DRIVER=namespace

#. Run DevStack.

   .. code-block:: console

      $ ./stack.sh


Enabling Kuryr support for OVN Octavia driver via ConfigMap
-----------------------------------------------------------

Alternatively, you can enable Kuryr support for the OVN Octavia driver on the
Kuryr ConfigMap, in case the options are not set at the local.conf file. On
DevStack deployment, the Kuryr ConfigMap can be edited using:

.. code-block:: console

   $ kubectl -n kube-system edit cm kuryr-config

The following options need to be set at the ConfigMap:

.. code-block:: bash

   [kubernetes]
   endpoints_driver_octavia_provider = ovn

   [octavia_defaults]
   lb_algorithm = SOURCE_IP_PORT
   enforce_sg_rules = False
   member_mode = L2

Make sure to keep correct indentation when doing changes. To enforce the new
settings, you need to restart kuryr-controller by simply killing existing pod.
Deployment controller will make sure to restart the pod with new configuration.

Kuryr automatically handles the recreation of already created services/load
balancers, so that all of them have the same Octavia provider.


Testing ovn-octavia driver support
----------------------------------

Once the environment is ready, you can test that network connectivity works
and verify that Kuryr creates the load balancer for the service with the OVN
provider specified in the ConfigMap.
To do that check out :doc:`../testing_connectivity`.

You can also manually create a load balancer in Openstack:

.. code-block:: console

   $ openstack loadbalancer create --vip-network-id public --provider ovn
   +---------------------+--------------------------------------+
   | Field               | Value                                |
   +---------------------+--------------------------------------+
   | admin_state_up      | True                                 |
   | availability_zone   | None                                 |
   | created_at          | 2020-12-09T14:45:08                  |
   | description         |                                      |
   | flavor_id           | None                                 |
   | id                  | 94e7c431-912b-496c-a247-d52875d44ac7 |
   | listeners           |                                      |
   | name                |                                      |
   | operating_status    | OFFLINE                              |
   | pools               |                                      |
   | project_id          | af820b57868c4864957d523fb32ccfba     |
   | provider            | ovn                                  |
   | provisioning_status | PENDING_CREATE                       |
   | updated_at          | None                                 |
   | vip_address         | 172.24.4.9                           |
   | vip_network_id      | ee97665d-69d0-4995-a275-27855359956a |
   | vip_port_id         | c98e52d0-5965-4b22-8a17-a374f4399193 |
   | vip_qos_policy_id   | None                                 |
   | vip_subnet_id       | 3eed0c05-6527-400e-bb80-df6e59d248f1 |
   +---------------------+--------------------------------------+
