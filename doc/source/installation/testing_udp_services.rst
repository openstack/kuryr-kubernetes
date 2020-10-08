====================
Testing UDP Services
====================

In this example, we will use the `kuryr-udp-demo`_ image. This image
implements a simple UDP server that listens on port 9090, and replies towards
client when a packet is received.

We first create a deployment named demo:

.. code-block:: console

   $ kubectl create deployment  --image=yboaron/kuryr-udp-demo demo
   deployment "demo" created

As the next step, we will scale the deployment to 2 pods:

.. code-block:: console

   $ kubectl scale deploy/demo --replicas=2
   deployment "demo" scaled

At this point we should have two pods running the `kuryr-udp-demo`_ image:

.. code-block:: console

   $ kubectl get pods
   NAME                   READY     STATUS    RESTARTS   AGE
   demo-fbb89f54c-92ttl   1/1       Running   0          31s
   demo-fbb89f54c-q9fq7   1/1       Running   0          1m

Next, we expose the deployment as a service, setting UDP port to 90:

.. code-block:: console

   $ kubectl get svc
   NAME         TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   kubernetes   ClusterIP   10.0.0.129   <none>        443/TCP   17m

   $ kubectl expose deploy/demo  --protocol UDP  --port 90 --target-port 9090
   service "demo" exposed

   $ kubectl get svc
   NAME         TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   demo         ClusterIP   10.0.0.150   <none>        90/UDP    16s
   kubernetes   ClusterIP   10.0.0.129   <none>        443/TCP   17m

Now, let's check the OpenStack load balancer created by Kuryr for **demo**
service:

.. code-block:: console

   $ openstack loadbalancer list
   +--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+
   | id                                   | name               | project_id                       | vip_address | provisioning_status | provider |
   +--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+
   | eb5123e8-6bb5-4680-ac64-dcf25c57ced3 | default/kubernetes | fdc9ac3b36474fbf8c7ab77f4f783ec5 | 10.0.0.129  | ACTIVE              | amphora  |
   | 67f19a39-dfb9-4a7a-bafe-7d6789982d91 | default/demo       | fdc9ac3b36474fbf8c7ab77f4f783ec5 | 10.0.0.150  | ACTIVE              | amphora  |
   +--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+

   $ openstack loadbalancer show default/demo
   +---------------------+--------------------------------------+
   | Field               | Value                                |
   +---------------------+--------------------------------------+
   | admin_state_up      | True                                 |
   | created_at          | 2018-10-09T06:06:14                  |
   | description         |                                      |
   | flavor              |                                      |
   | id                  | 67f19a39-dfb9-4a7a-bafe-7d6789982d91 |
   | listeners           | 7b374ecf-80c4-44be-a725-9b0c3fa2d0fa |
   | name                | default/demo                         |
   | operating_status    | ONLINE                               |
   | pools               | d549df5b-e008-49a6-8695-b6578441553e |
   | project_id          | fdc9ac3b36474fbf8c7ab77f4f783ec5     |
   | provider            | amphora                              |
   | provisioning_status | ACTIVE                               |
   | updated_at          | 2018-10-09T06:07:53                  |
   | vip_address         | 10.0.0.150                           |
   | vip_network_id      | eee6af72-9fbb-48b5-8e52-9f8bdf61cbab |
   | vip_port_id         | ccd8be94-c65e-4bb2-afe7-44aa3d0617ea |
   | vip_qos_policy_id   | None                                 |
   | vip_subnet_id       | 3376291d-6c23-48cb-b6c6-37cefd57f914 |
   +---------------------+--------------------------------------+

Checking the load balancer's details, we can see that the load balancer is
listening on UDP port 90:

.. code-block:: console

   $ openstack loadbalancer listener show 7b374ecf-80c4-44be-a725-9b0c3fa2d0fa
   +---------------------------+--------------------------------------+
   | Field                     | Value                                |
   +---------------------------+--------------------------------------+
   | admin_state_up            | True                                 |
   | connection_limit          | -1                                   |
   | created_at                | 2018-10-09T06:07:37                  |
   | default_pool_id           | d549df5b-e008-49a6-8695-b6578441553e |
   | default_tls_container_ref | None                                 |
   | description               |                                      |
   | id                        | 7b374ecf-80c4-44be-a725-9b0c3fa2d0fa |
   | insert_headers            | None                                 |
   | l7policies                |                                      |
   | loadbalancers             | 67f19a39-dfb9-4a7a-bafe-7d6789982d91 |
   | name                      | default/demo:UDP:90                  |
   | operating_status          | ONLINE                               |
   | project_id                | fdc9ac3b36474fbf8c7ab77f4f783ec5     |
   | protocol                  | UDP                                  |
   | protocol_port             | 90                                   |
   | provisioning_status       | ACTIVE                               |
   | sni_container_refs        | []                                   |
   | timeout_client_data       | 50000                                |
   | timeout_member_connect    | 5000                                 |
   | timeout_member_data       | 50000                                |
   | timeout_tcp_inspect       | 0                                    |
   | updated_at                | 2018-10-09T06:07:53                  |
   +---------------------------+--------------------------------------+

And the load balancer has two members listening on UDP port 9090:

.. code-block:: console

   $ openstack loadbalancer member list d549df5b-e008-49a6-8695-b6578441553e
   +--------------------------------------+-----------------------------------+----------------------------------+---------------------+-----------+---------------+------------------+--------+
   | id                                   | name                              | project_id                       | provisioning_status | address   | protocol_port | operating_status | weight |
   +--------------------------------------+-----------------------------------+----------------------------------+---------------------+-----------+---------------+------------------+--------+
   | b2c63e7b-47ed-4a6f-b8bb-acaa6742a0ad | default/demo-fbb89f54c-q9fq7:9090 | fdc9ac3b36474fbf8c7ab77f4f783ec5 | ACTIVE              | 10.0.0.74 |          9090 | ONLINE           |      1 |
   | 7fa773b1-cf76-4a0b-8004-153423e59ef6 | default/demo-fbb89f54c-92ttl:9090 | fdc9ac3b36474fbf8c7ab77f4f783ec5 | ACTIVE              | 10.0.0.88 |          9090 | ONLINE           |      1 |
   +--------------------------------------+-----------------------------------+----------------------------------+---------------------+-----------+---------------+------------------+--------+

At this point, we have both the kubernetes **demo** service and corresponding
openstack load balancer running, and we are ready to run the client
application.

For the client application we will use the `udp-client`_ python script. The UDP
client script sends UDP message towards specific IP and port, and waits for a
response from the server. The way that the client application can communicate
with the server is by leveraging the Kubernetes service functionality.

First we clone the client script:

.. code-block:: console

   $ git clone https://github.com/yboaron/udp-client-script.git
   Cloning into 'udp-client-script'...
   remote: Enumerating objects: 15, done.
   remote: Counting objects: 100% (15/15), done.
   remote: Compressing objects: 100% (13/13), done.
   remote: Total 15 (delta 4), reused 3 (delta 1), pack-reused 0
   Unpacking objects: 100% (15/15), done.
   $

And we need the UDP server service IP and port:

.. code-block:: console

   $ kubectl get svc demo
   NAME      TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   demo      ClusterIP   10.0.0.150   <none>        90/UDP    20m
   $

Last step will be to ping the UDP server service:

.. code-block:: console

   $ python udp-client-script/client.py 10.0.0.150 90
   demo-fbb89f54c-92ttl: HELLO, I AM ALIVE!!!

   $ python udp-client-script/client.py 10.0.0.150 90
   demo-fbb89f54c-q9fq7: HELLO, I AM ALIVE!!!

Since the `kuryr-udp-demo`_ application concatenates the pod's name to the
replyed message, it is plain to see that both service's pods are replying to
the requests from the client.


.. _kuryr-udp-demo: https://hub.docker.com/r/yboaron/kuryr-udp-demo/
.. _udp-client: https://github.com/yboaron/udp-client-script
