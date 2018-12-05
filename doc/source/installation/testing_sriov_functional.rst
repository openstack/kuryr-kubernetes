Testing SRIOV functionality
===========================

Following the steps explained on :ref:`sriov` make sure that you have
already created and applied a ``NetworkAttachmentDefinition``
containing a ``sriov`` driverType. Also make sure that
`sriov-device-plugin <https://docs.google.com/document/d/1Ewe9Of84GkP0b2Q2PC0y9RVZNkN2WeVEagX9m99Nrzc>`_
is enabled on the nodes.

``NetworkAttachmentDefinition`` containing a ``sriov`` driverType might
look like:

.. code-block:: yaml

    apiVersion: "k8s.cni.cncf.io/v1"
    kind: NetworkAttachmentDefinition
    metadata:
      name: "net-sriov"
      annotations:
        openstack.org/kuryr-config: '{
        "subnetId": "88d0b025-2710-4f02-a348-2829853b45da",
        "driverType": "sriov"
        }'

Here ``88d0b025-2710-4f02-a348-2829853b45da`` is an id of precreated
subnet that is expected to be used for SR-IOV ports:

.. code-block:: bash

    $ neutron subnet-show 88d0b025-2710-4f02-a348-2829853b45da
    +-------------------+--------------------------------------------------+
    | Field             | Value                                            |
    +-------------------+--------------------------------------------------+
    | allocation_pools  | {"start": "192.168.2.2", "end": "192.168.2.254"} |
    | cidr              | 192.168.2.0/24                                   |
    | created_at        | 2018-11-21T10:57:34Z                             |
    | description       |                                                  |
    | dns_nameservers   |                                                  |
    | enable_dhcp       | True                                             |
    | gateway_ip        | 192.168.2.1                                      |
    | host_routes       |                                                  |
    | id                | 88d0b025-2710-4f02-a348-2829853b45da             |
    | ip_version        | 4                                                |
    | ipv6_address_mode |                                                  |
    | ipv6_ra_mode      |                                                  |
    | name              | sriov_subnet                                     |
    | network_id        | 2f8b9103-e9ec-47fa-9617-0fb9deacfc00             |
    | project_id        | 92a4d7734b17486ba24e635bc7fad595                 |
    | revision_number   | 2                                                |
    | service_types     |                                                  |
    | subnetpool_id     |                                                  |
    | tags              |                                                  |
    | tenant_id         | 92a4d7734b17486ba24e635bc7fad595                 |
    | updated_at        | 2018-11-21T10:57:34Z                             |
    +-------------------+--------------------------------------------------+

1. Create deployment definition <DEFINITION_FILE_NAME> with one
SR-IOV interface (apart from default one). Deployment definition
file might look like:

.. code-block:: yaml

    apiVersion: extensions/v1beta1
    kind: Deployment
    metadata:
      name: nginx-sriov
    spec:
      replicas: 1
      template:
        metadata:
          name: nginx-sriov
          labels:
            app: nginx-sriov
          annotations:
            k8s.v1.cni.cncf.io/networks: net-sriov
        spec:
          containers:
          - name: nginx-sriov
            image: nginx
            resources:
              requests:
                intel.com/sriov: '1'
                cpu: "1"
                memory: "512Mi"
              limits:
                intel.com/sriov: '1'
                cpu: "1"
                memory: "512Mi"

Here ``net-sriov`` is the name of ``NetworkAttachmentDefinition``
created before.

2. Create deployment with the following command:

.. code-block:: bash

    $ kubectl create -f <DEFINITION_FILE_NAME>

3. Wait for the pod to get to Running phase.

.. code-block:: bash

    $ kubectl get pods
    NAME                                    READY   STATUS      RESTARTS    AGE
    nginx-sriov-558db554d7-rvpxs            1/1     Running     0           1m

4. If your image contains ``iputils`` (for example, busybox image), you can
attach to the pod and check that the correct interface has been attached
to the Pod.

.. code-block:: bash

    $ kubectl get pod
    $ kubectl exec -it nginx-sriov-558db554d7-rvpxs -- /bin/bash
    $ ip a

You should see default and eth1 interfaces. eth1 is the SR-IOV VF interface.

.. code-block:: bash

    1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN qlen 1000
        link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
        inet 127.0.0.1/8 scope host lo
            valid_lft forever preferred_lft forever
        inet6 ::1/128 scope host
            valid_lft forever preferred_lft forever
    3: eth0@if43: <BROADCAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP qlen 1000
        link/ether fa:16:3e:1a:c0:43 brd ff:ff:ff:ff:ff:ff link-netnsid 0
        inet 192.168.0.9/24 scope global eth0
            valid_lft forever preferred_lft forever
        inet6 fe80::f816:3eff:fe1a:c043/64 scope link
            valid_lft forever preferred_lft forever
    13: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP qlen 1000
        link/ether fa:16:3e:b3:2e:70 brd ff:ff:ff:ff:ff:ff
        inet 192.168.2.6/24 scope global eth1
            valid_lft forever preferred_lft forever
        inet6 fe80::f816:3eff:fea8:55af/64 scope link
            valid_lft forever preferred_lft forever

4.1. Alternatively you can login to k8s worker and do the same from the
host system.
Use the following command to find out ID of running SR-IOV container:

.. code-block:: bash

    $ docker ps

Suppose that ID of created container is ``eb4e10f38763``.
Use the following command to get PID of that container:

.. code-block:: bash

    $ docker inspect --format {{.State.Pid}} eb4e10f38763

Suppose that output of previous command is bellow:

.. code-block:: bash

    $ 32609

Use the following command to get interfaces of container:

.. code-block:: bash

    $ nsenter -n -t 32609 ip a

You should see default and eth1 interfaces. eth1 is the SR-IOV VF interface.

.. code-block:: bash

    1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN qlen 1000
        link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
        inet 127.0.0.1/8 scope host lo
            valid_lft forever preferred_lft forever
        inet6 ::1/128 scope host
            valid_lft forever preferred_lft forever
    3: eth0@if43: <BROADCAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP qlen 1000
        link/ether fa:16:3e:1a:c0:43 brd ff:ff:ff:ff:ff:ff link-netnsid 0
        inet 192.168.0.9/24 scope global eth0
            valid_lft forever preferred_lft forever
        inet6 fe80::f816:3eff:fe1a:c043/64 scope link
            valid_lft forever preferred_lft forever
    13: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP qlen 1000
        link/ether fa:16:3e:b3:2e:70 brd ff:ff:ff:ff:ff:ff
        inet 192.168.2.6/24 scope global eth1
            valid_lft forever preferred_lft forever
        inet6 fe80::f816:3eff:fea8:55af/64 scope link
            valid_lft forever preferred_lft forever

In our example sriov interface has address 192.168.2.6

5. Use neutron CLI to check the port with exact address has been created on neutron:

.. code-block:: bash

    $ openstack port list | grep 192.168.2.6

Suppose that previous command returns a list with one openstack port that
has ID ``545ec21d-6bfc-4179-88c6-9dacaf435ea7``. You can see its information
with the following command:

.. code-block:: bash

    $ openstack port show 545ec21d-6bfc-4179-88c6-9dacaf435ea7
    +-----------------------+----------------------------------------------------------------------------+
    | Field                 | Value                                                                      |
    +-----------------------+----------------------------------------------------------------------------+
    | admin_state_up        | UP                                                                         |
    | allowed_address_pairs |                                                                            |
    | binding_host_id       | novactl                                                                    |
    | binding_profile       |                                                                            |
    | binding_vif_details   | port_filter='True'                                                         |
    | binding_vif_type      | hw_veb                                                                     |
    | binding_vnic_type     | direct                                                                     |
    | created_at            | 2018-11-26T09:13:07Z                                                       |
    | description           |                                                                            |
    | device_id             | 7ab02cf9-f15b-11e8-bdf4-525400152cf3                                       |
    | device_owner          | compute:kuryr:sriov                                                        |
    | dns_assignment        | None                                                                       |
    | dns_name              | None                                                                       |
    | extra_dhcp_opts       |                                                                            |
    | fixed_ips             | ip_address='192.168.2.6', subnet_id='88d0b025-2710-4f02-a348-2829853b45da' |
    | id                    | 545ec21d-6bfc-4179-88c6-9dacaf435ea7                                       |
    | ip_address            | None                                                                       |
    | mac_address           | fa:16:3e:b3:2e:70                                                          |
    | name                  | default/nginx-sriov-558db554d7-rvpxs                                       |
    | network_id            | 2f8b9103-e9ec-47fa-9617-0fb9deacfc00                                       |
    | option_name           | None                                                                       |
    | option_value          | None                                                                       |
    | port_security_enabled | False                                                                      |
    | project_id            | 92a4d7734b17486ba24e635bc7fad595                                           |
    | qos_policy_id         | None                                                                       |
    | revision_number       | 5                                                                          |
    | security_groups       | 1e7bb965-2ad5-4a09-a5ac-41aa466af25b                                       |
    | status                | DOWN                                                                       |
    | subnet_id             | None                                                                       |
    | updated_at            | 2018-11-26T09:13:07Z                                                       |
    +-----------------------+----------------------------------------------------------------------------+

The port would have the name of the pod, ``compute::kuryr::sriov`` for device owner and 'direct' vnic_type.
Verify that IP and MAC addresses of the port match the ones on the container.
Currently the neutron-sriov-nic-agent does not properly detect SR-IOV ports assigned to containers. This
means that direct ports in neutron would always remain in *DOWN* state. This doesn't affect the feature
in any way other than cosmetically.
