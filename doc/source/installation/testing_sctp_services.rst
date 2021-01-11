=====================
Testing SCTP Services
=====================

In this example, we will use the `kuryr-sctp-demo`_ image. This image
implements a SCTP server that listens on port 9090, and responds to client
when a packet is received.

We first create a deployment named sctp-demo using the deployment manifest
(deploy.yml) below:

.. code-block:: yaml

   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: sctp-demo
     labels:
       app: server
   spec:
     replicas: 2
     selector:
       matchLabels:
         app: server
     template:
       metadata:
         labels:
           app: server
       spec:
         containers:
         - name: sctp-demo
           image: tabbie/kuryr-sctp-demo:v2.1
           ports:
           - containerPort: 9090

.. code-block:: console

   $ kubectl apply -f deploy.yml
   deployment.apps/sctp-demo created

At this point we should have two pods running the `kuryr-sctp-demo`_ image:

.. code-block:: console

   $ kubectl get pods
   NAME                         READY   STATUS     RESTARTS   AGE
   sctp-demo-65fcf85ddb-8vnrq   1/1     Running    0          40s
   sctp-demo-65fcf85ddb-zg7nq   1/1     Running    0          109s

Next, we expose the deployment as a service, setting SCTP port to 90:

.. note::

   In order to successfully expose the deployment as a service, ensure that
   the Octavia provider in use by Kuryr has SCTP support.

.. code-block:: console

   $ kubectl get svc
   NAME         TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   kubernetes   ClusterIP   10.0.0.129   <none>        443/TCP   36h

   $ kubectl expose deploy/sctp-demo --protocol=SCTP --port=90 --target-port=9090
   service/sctp-demo exposed

   $ kubectl get svc
   NAME         TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   kubernetes   ClusterIP   10.0.0.129   <none>        443/TCP   36h
   sctp-demo    ClusterIP   10.0.0.158   <none>        90/SCTP   42s

Now, let's check the OpenStack load balancer created by Kuryr for **sctp-demo**
service.

.. code-block:: console

   $ openstack loadbalancer list
   +--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+
   | id                                   | name               | project_id                       | vip_address | provisioning_status | provider |
   +--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+
   | 4d219ac7-2592-4d33-8afa-12994c5d82ec | default/kubernetes | 2e89a9e0a50d42d1be8054a80530b836 | 10.0.0.129  | ACTIVE              | amphora  |
   | 96b38be3-1183-41c5-a0db-d246ef1d07cb | default/sctp-demo  | 2e89a9e0a50d42d1be8054a80530b836 | 10.0.0.158  | ACTIVE              | amphora  |
   +--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+

   $ openstack loadbalancer show default/sctp-demo
   +---------------------+--------------------------------------+
   | Field               | Value                                |
   +---------------------+--------------------------------------+
   | admin_state_up      | True                                 |
   | availability_zone   | None                                 |
   | created_at          | 2021-01-11T10:01:15                  |
   | description         |                                      |
   | flavor_id           | None                                 |
   | id                  | 96b38be3-1183-41c5-a0db-d246ef1d07cb |
   | listeners           | eda5caa0-083a-4c45-a2e5-38c243b2c970 |
   | name                | default/sctp-demo                    |
   | operating_status    | ONLINE                               |
   | pools               | 0935f099-d901-4f39-8090-392a527cbc35 |
   | project_id          | 2e89a9e0a50d42d1be8054a80530b836     |
   | provider            | amphora                              |
   | provisioning_status | ACTIVE                               |
   | updated_at          | 2021-01-11T10:05:30                  |
   | vip_address         | 10.0.0.158                           |
   | vip_network_id      | 13190422-869c-4259-ba3b-6a41be79a671 |
   | vip_port_id         | 64da8e72-8469-4ac6-a0e6-ec60ca02b96a |
   | vip_qos_policy_id   | None                                 |
   | vip_subnet_id       | 0041469e-371c-417f-83df-94ca8f202eab |
   +---------------------+--------------------------------------+

Checking the load balancer's details, we can see that the load balancer is
listening on SCTP port 90:

.. code-block:: console

   $ openstack loadbalancer listener show eda5caa0-083a-4c45-a2e5-38c243b2c970
   +-----------------------------+--------------------------------------+
   | Field                       | Value                                |
   +-----------------------------+--------------------------------------+
   | admin_state_up              | True                                 |
   | connection_limit            | -1                                   |
   | created_at                  | 2021-01-11T10:04:31                  |
   | default_pool_id             | 0935f099-d901-4f39-8090-392a527cbc35 |
   | default_tls_container_ref   | None                                 |
   | description                 |                                      |
   | id                          | eda5caa0-083a-4c45-a2e5-38c243b2c970 |
   | insert_headers              | None                                 |
   | l7policies                  |                                      |
   | loadbalancers               | 96b38be3-1183-41c5-a0db-d246ef1d07cb |
   | name                        | default/sctp-demo:SCTP:90            |
   | operating_status            | ONLINE                               |
   | project_id                  | 2e89a9e0a50d42d1be8054a80530b836     |
   | protocol                    | SCTP                                 |
   | protocol_port               | 90                                   |
   | provisioning_status         | ACTIVE                               |
   | sni_container_refs          | []                                   |
   | timeout_client_data         | 50000                                |
   | timeout_member_connect      | 5000                                 |
   | timeout_member_data         | 50000                                |
   | timeout_tcp_inspect         | 0                                    |
   | updated_at                  | 2021-01-11T10:05:30                  |
   | client_ca_tls_container_ref | None                                 |
   | client_authentication       | NONE                                 |
   | client_crl_container_ref    | None                                 |
   | allowed_cidrs               | None                                 |
   | tls_ciphers                 | None                                 |
   | tls_versions                | None                                 |
   | alpn_protocols              | None                                 |
   +-----------------------------+--------------------------------------+

And the load balancer has a pool with two members listening on SCTP port 9090:

.. code-block:: console

   $ openstack loadbalancer pool list
   +--------------------------------------+---------------------------+----------------------------------+---------------------+----------+--------------+----------------+
   | id                                   | name                      | project_id                       | provisioning_status | protocol | lb_algorithm | admin_state_up |
   +--------------------------------------+---------------------------+----------------------------------+---------------------+----------+--------------+----------------+
   | c69a87a5-078e-4c2b-84d4-0a2691c58f07 | default/kubernetes:443    | 2e89a9e0a50d42d1be8054a80530b836 | ACTIVE              | HTTPS    | ROUND_ROBIN  | True           |
   | 0935f099-d901-4f39-8090-392a527cbc35 | default/sctp-demo:SCTP:90 | 2e89a9e0a50d42d1be8054a80530b836 | ACTIVE              | SCTP     | ROUND_ROBIN  | True           |
   +--------------------------------------+---------------------------+----------------------------------+---------------------+----------+--------------+----------------+

   $ openstack loadbalancer member list default/sctp-demo:SCTP:90
   +--------------------------------------+-----------------------------------------+----------------------------------+---------------------+-----------+---------------+------------------+--------+
   | id                                   | name                                    | project_id                       | provisioning_status | address   | protocol_port | operating_status | weight |
   +--------------------------------------+-----------------------------------------+----------------------------------+---------------------+-----------+---------------+------------------+--------+
   | abeec334-56b1-4535-a238-71424d78590e | default/sctp-demo-65fcf85ddb-zg7nq:9090 | 2e89a9e0a50d42d1be8054a80530b836 | ACTIVE              | 10.0.0.75 |          9090 | NO_MONITOR       |      1 |
   | 826345b0-1264-421d-b9e0-8756f7bc0d21 | default/sctp-demo-65fcf85ddb-8vnrq:9090 | 2e89a9e0a50d42d1be8054a80530b836 | ACTIVE              | 10.0.0.88 |          9090 | NO_MONITOR       |      1 |
   +--------------------------------------+-----------------------------------------+----------------------------------+---------------------+-----------+---------------+------------------+--------+

At this point, we have both the kubernetes service and corresponding OpenStack
load balancer running, and we are ready to run the client application.

For the client application we will use the `sctp_client`_ python script. The
SCTP client script sends SCTP message towards specific IP and port, and waits
for a response from the server. The client application communicates with the
server by leveraging OpenStack load balancer functionality.

For the client application to work, python SCTP module needs to be installed
in our environment. We need a SCTP-aware kernel (most are). First we install
the following packages: libsctp-dev, libsctp1, lksctp-tools and then install
the module.

.. code-block:: console

   $ sudo apt-get install libsctp-dev libsctp1 lksctp-tools
   $ pip3 install pysctp


And we need the SCTP server service IP and port:

.. code-block:: console

   $ kubectl get svc sctp-demo
   NAME        TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   sctp-demo   ClusterIP   10.0.0.158   <none>        90/SCTP   67m

Last step will be to connect to the SCTP server service:

.. code-block:: console

   $ python3 sctp_client.py 10.0.0.158 90
   Sending Message
   sctp-demo-65fcf85ddb-zg7nq: HELLO, I AM ALIVE!!!

   $ python3 sctp_client.py 10.0.0.158 90
   Sending Message
   sctp-demo-65fcf85ddb-8vnrq: HELLO, I AM ALIVE!!!

.. _kuryr-sctp-demo: https://hub.docker.com/repository/docker/tabbie/kuryr-sctp-demo
.. _sctp_client: https://github.com/openstack/kuryr-kubernetes/blob/master/contrib/sctp_client.py
