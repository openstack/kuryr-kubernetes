===============
IPv6 networking
===============

Kuryr Kubernetes can be used with IPv6 networking. In this guide we'll show how
you can create the Neutron resources and configure Kubernetes and
Kuryr-Kubernetes to achieve an IPv6 only Kubernetes cluster.


Setting it up
-------------

#. Create pods network:

   .. code-block:: console

      $ openstack network create pods
      +---------------------------+--------------------------------------+
      | Field                     | Value                                |
      +---------------------------+--------------------------------------+
      | admin_state_up            | UP                                   |
      | availability_zone_hints   |                                      |
      | availability_zones        |                                      |
      | created_at                | 2017-08-11T10:51:25Z                 |
      | description               |                                      |
      | dns_domain                | None                                 |
      | id                        | 4593045c-4233-4b4c-8527-35608ab0eaae |
      | ipv4_address_scope        | None                                 |
      | ipv6_address_scope        | None                                 |
      | is_default                | False                                |
      | is_vlan_transparent       | None                                 |
      | mtu                       | 1450                                 |
      | name                      | pods                                 |
      | port_security_enabled     | True                                 |
      | project_id                | 90baf12877ba49a786419b2cacc2c954     |
      | provider:network_type     | vxlan                                |
      | provider:physical_network | None                                 |
      | provider:segmentation_id  | 21                                   |
      | qos_policy_id             | None                                 |
      | revision_number           | 2                                    |
      | router:external           | Internal                             |
      | segments                  | None                                 |
      | shared                    | False                                |
      | status                    | ACTIVE                               |
      | subnets                   |                                      |
      | tags                      | []                                   |
      | updated_at                | 2017-08-11T10:51:25Z                 |
      +---------------------------+--------------------------------------+

#. Create the pod subnet:

   .. code-block:: console

      $ openstack subnet create --network pods --no-dhcp \
            --subnet-range fd10:0:0:1::/64 \
            --ip-version 6 \
            pod_subnet
      +-------------------------+-------------------------------------------+
      | Field                   | Value                                     |
      +-------------------------+-------------------------------------------+
      | allocation_pools        | fd10:0:0:1::2-fd10::1:ffff:ffff:ffff:ffff |
      | cidr                    | fd10:0:0:1::/64                           |
      | created_at              | 2017-08-11T17:02:20Z                      |
      | description             |                                           |
      | dns_nameservers         |                                           |
      | enable_dhcp             | False                                     |
      | gateway_ip              | fd10:0:0:1::1                             |
      | host_routes             |                                           |
      | id                      | eef12d65-4d02-4344-b255-295f9adfd4e9      |
      | ip_version              | 6                                         |
      | ipv6_address_mode       | None                                      |
      | ipv6_ra_mode            | None                                      |
      | name                    | pod_subnet                                |
      | network_id              | 4593045c-4233-4b4c-8527-35608ab0eaae      |
      | project_id              | 90baf12877ba49a786419b2cacc2c954          |
      | revision_number         | 0                                         |
      | segment_id              | None                                      |
      | service_types           |                                           |
      | subnetpool_id           | None                                      |
      | tags                    | []                                        |
      | updated_at              | 2017-08-11T17:02:20Z                      |
      | use_default_subnet_pool | None                                      |
      +-------------------------+-------------------------------------------+


#. Create services network:

   .. code-block:: console

      $ openstack network create services
      +---------------------------+--------------------------------------+
      | Field                     | Value                                |
      +---------------------------+--------------------------------------+
      | admin_state_up            | UP                                   |
      | availability_zone_hints   |                                      |
      | availability_zones        |                                      |
      | created_at                | 2017-08-11T10:53:36Z                 |
      | description               |                                      |
      | dns_domain                | None                                 |
      | id                        | 560df0c2-537c-41c0-b22c-40ef3d752574 |
      | ipv4_address_scope        | None                                 |
      | ipv6_address_scope        | None                                 |
      | is_default                | False                                |
      | is_vlan_transparent       | None                                 |
      | mtu                       | 1450                                 |
      | name                      | services                             |
      | port_security_enabled     | True                                 |
      | project_id                | 90baf12877ba49a786419b2cacc2c954     |
      | provider:network_type     | vxlan                                |
      | provider:physical_network | None                                 |
      | provider:segmentation_id  | 94                                   |
      | qos_policy_id             | None                                 |
      | revision_number           | 2                                    |
      | router:external           | Internal                             |
      | segments                  | None                                 |
      | shared                    | False                                |
      | status                    | ACTIVE                               |
      | subnets                   |                                      |
      | tags                      | []                                   |
      | updated_at                | 2017-08-11T10:53:37Z                 |
      +---------------------------+--------------------------------------+

#. Create services subnet. We reserve the first half of the subnet range for the
   VIPs and the second half for the loadbalancer vrrp ports.

   .. code-block:: console

      $ openstack subnet create --network services --no-dhcp \
            --gateway fd10:0:0:2:0:0:0:fffe \
            --ip-version 6 \
            --allocation-pool start=fd10:0:0:2:0:0:0:8000,end=fd10:0:0:2:0:0:0:fffd \
            --subnet-range fd10:0:0:2::/112 \
            service_subnet
      +-------------------------+--------------------------------------+
      | Field                   | Value                                |
      +-------------------------+--------------------------------------+
      | allocation_pools        | fd10:0:0:2::8000-fd10:0:0:2::fffd    |
      | cidr                    | fd10:0:0:2::/112                     |
      | created_at              | 2017-08-14T19:08:34Z                 |
      | description             |                                      |
      | dns_nameservers         |                                      |
      | enable_dhcp             | False                                |
      | gateway_ip              | fd10:0:0:2::fffe                     |
      | host_routes             |                                      |
      | id                      | 3c53ff94-40e2-4399-bc45-6e210f1e8064 |
      | ip_version              | 6                                    |
      | ipv6_address_mode       | None                                 |
      | ipv6_ra_mode            | None                                 |
      | name                    | service_subnet                       |
      | network_id              | 560df0c2-537c-41c0-b22c-40ef3d752574 |
      | project_id              | 90baf12877ba49a786419b2cacc2c954     |
      | revision_number         | 0                                    |
      | segment_id              | None                                 |
      | service_types           |                                      |
      | subnetpool_id           | None                                 |
      | tags                    | []                                   |
      | updated_at              | 2017-08-14T19:08:34Z                 |
      | use_default_subnet_pool | None                                 |
      +-------------------------+--------------------------------------+

#. Create a router:

   .. code-block:: console

      $ openstack router create k8s-ipv6
      +-------------------------+--------------------------------------+
      | Field                   | Value                                |
      +-------------------------+--------------------------------------+
      | admin_state_up          | UP                                   |
      | availability_zone_hints |                                      |
      | availability_zones      |                                      |
      | created_at              | 2017-08-11T13:17:10Z                 |
      | description             |                                      |
      | distributed             | False                                |
      | external_gateway_info   | None                                 |
      | flavor_id               | None                                 |
      | ha                      | False                                |
      | id                      | f802a968-2f83-4006-80cb-5070415f69bf |
      | name                    | k8s-ipv6                             |
      | project_id              | 90baf12877ba49a786419b2cacc2c954     |
      | revision_number         | None                                 |
      | routes                  |                                      |
      | status                  | ACTIVE                               |
      | tags                    | []                                   |
      | updated_at              | 2017-08-11T13:17:10Z                 |
      +-------------------------+--------------------------------------+

#. Add the router to the pod subnet:

   .. code-block:: console

      $ openstack router add subnet k8s-ipv6 pod_subnet

#. Add the router to the service subnet:

   .. code-block:: console

      $ openstack router add subnet k8s-ipv6 service_subnet

#. Modify Kubernetes API server command line so that it points to the right
   CIDR:

   .. code-block:: console

      --service-cluster-ip-range=fd10:0:0:2::/113

   Note that it is /113 because the other half of the /112 will be used by the
   Octavia LB vrrp ports.

#. Follow the :ref:`k8s_lb_reachable` guide but using IPv6 addresses instead
   for the host Kubernetes API. You should also make sure that the Kubernetes
   API server binds on the IPv6 address of the host.


Troubleshooting
---------------

* **Pods can talk to each other with IPv6 but they can't talk to services.**

  This means that most likely you forgot to create a security group or rule
  for the pods to be accessible by the service CIDR. You can find an example
  here:

  .. code-block:: console

     $ openstack security group create service_pod_access_v6
     +-----------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+
     | Field           | Value                                                                                                                                                 |
     +-----------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+
     | created_at      | 2017-08-16T10:01:45Z                                                                                                                                  |
     | description     | service_pod_access_v6                                                                                                                                 |
     | id              | f0b6f0bd-40f7-4ab6-a77b-3cf9f7cc28ac                                                                                                                  |
     | name            | service_pod_access_v6                                                                                                                                 |
     | project_id      | 90baf12877ba49a786419b2cacc2c954                                                                                                                      |
     | revision_number | 2                                                                                                                                                     |
     | rules           | created_at='2017-08-16T10:01:45Z', direction='egress', ethertype='IPv4', id='bd759b4f-c0f5-4cff-a30a-3cd8544d2822', updated_at='2017-08-16T10:01:45Z' |
     |                 | created_at='2017-08-16T10:01:45Z', direction='egress', ethertype='IPv6', id='c89c3f3e-a326-4902-ba26-5315e2d95320', updated_at='2017-08-16T10:01:45Z' |
     | updated_at      | 2017-08-16T10:01:45Z                                                                                                                                  |
     +-----------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+

     $ openstack security group rule create --remote-ip fd10:0:0:2::/112 \
          --ethertype IPv6 f0b6f0bd-40f7-4ab6-a77b-3cf9f7cc28ac
     +-------------------+--------------------------------------+
     | Field             | Value                                |
     +-------------------+--------------------------------------+
     | created_at        | 2017-08-16T10:04:57Z                 |
     | description       |                                      |
     | direction         | ingress                              |
     | ether_type        | IPv6                                 |
     | id                | cface77f-666f-4a4c-8a15-a9c6953acf08 |
     | name              | None                                 |
     | port_range_max    | None                                 |
     | port_range_min    | None                                 |
     | project_id        | 90baf12877ba49a786419b2cacc2c954     |
     | protocol          | tcp                                  |
     | remote_group_id   | None                                 |
     | remote_ip_prefix  | fd10:0:0:2::/112                     |
     | revision_number   | 0                                    |
     | security_group_id | f0b6f0bd-40f7-4ab6-a77b-3cf9f7cc28ac |
     | updated_at        | 2017-08-16T10:04:57Z                 |
     +-------------------+--------------------------------------+

  Then remember to add the new security groups to the comma-separated
  *pod_security_groups* setting in the section *[neutron_defaults]* of
  /etc/kuryr/kuryr.conf
