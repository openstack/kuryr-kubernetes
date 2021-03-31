============================
Testing Network Connectivity
============================

Once the environment is ready, we can test that network connectivity works
among pods. First we check the status of the kubernetes cluster:

.. code-block:: console

   $ kubectl get nodes
   NAME           STATUS    AGE       VERSION
   masterodl-vm   Ready     1h        v1.6.2

   $ kubectl get pods
   No resources found.

   $ kubectl get svc
   NAME         CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   kubernetes   10.0.0.129   <none>        443/TCP   1h

As we can see, this is a one node cluster with currently no pods running, and
with the kubernetes API service listening on port 443 at 10.0.0.129 (which
matches the ip assigned to the load balancer created for it).

To test proper configuration and connectivity we firstly create a sample
deployment with:

.. code-block:: console

   $ kubectl create deployment demo --image=quay.io/kuryr/demo
   deployment "demo" created

After a few seconds, the container is up an running, and a neutron port was
created with the same IP that got assigned to the pod:

.. code-block:: console

   $ kubectl get pods
   NAME                    READY     STATUS    RESTARTS   AGE
   demo-7dd477695c-25s99   1/1       Running   0          1m

   $ kubectl describe pod demo-2293951457-j29nb | grep IP:
   IP:             10.0.1.122

   $ openstack port list | grep demo
   | 468d3d7e-4dd1-4e42-9200-e3eb97d603e6 | default/demo-7dd477695c-25s99  | fa:16:3e:24:ba:40 | ip_address='10.0.1.122', subnet_id='15cfabf7-c7e0-4964-a3c0-0545e9e4ea2f' | ACTIVE |

We can then scale the deployment to 2 pods, and check connectivity between
them:

.. code-block:: console

   $ kubectl scale deploy/demo --replicas=2
   deployment "demo" scaled

   $ kubectl get pods
   NAME                    READY     STATUS    RESTARTS   AGE
   demo-7dd477695c-25s99   1/1       Running   0          36m
   demo-7dd477695c-fbq4r   1/1       Running   0          30m


   $ openstack port list | grep demo
   | 468d3d7e-4dd1-4e42-9200-e3eb97d603e6 | default/demo-7dd477695c-25s99  | fa:16:3e:24:ba:40 | ip_address='10.0.1.122', subnet_id='15cfabf7-c7e0-4964-a3c0-0545e9e4ea2f' | ACTIVE |
   | b54da942-2241-4f07-8e2e-e45a7367fa69 | default/demo-7dd477695c-fbq4r  | fa:16:3e:41:57:a4 | ip_address='10.0.1.116', subnet_id='15cfabf7-c7e0-4964-a3c0-0545e9e4ea2f' | ACTIVE |

   $ kubectl exec -it demo-7dd477695c-25s99  -- /bin/sh

   sh-4.2$ curl 10.0.1.122:8080
   demo-7dd477695c-25s99: HELLO, I AM ALIVE!!!


   sh-4.2$ curl 10.0.1.116:8080
   demo-7dd477695c-fbq4r: HELLO, I AM ALIVE!!!


   sh-4.2$ ping 10.0.1.116
   PING 10.0.1.116 (10.0.1.116) 56(84) bytes of data.
   64 bytes from 10.0.1.116: icmp_seq=1 ttl=64 time=1.14 ms
   64 bytes from 10.0.1.116: icmp_seq=2 ttl=64 time=0.250 ms

Next, we expose the service so that a neutron load balancer is created and
the service is exposed and load balanced among the available pods:

.. code-block:: console

   $ kubectl get svc
   NAME         CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   kubernetes   10.0.0.129   <none>        443/TCP   1h

   $ kubectl expose deploy/demo --port=80 --target-port=8080
   service "demo" exposed

   $ kubectl get svc
   NAME         CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   demo         10.0.0.140   <none>        80/TCP    6s
   kubernetes   10.0.0.129   <none>        443/TCP   1h

   $ openstack loadbalancer list
   +--------------------------------------+---------------------+----------------------------------+-------------+---------------------+------------------+----------+
   | id                                   | name                | project_id                       | vip_address | provisioning_status | operating_status | provider |
   +--------------------------------------+---------------------+----------------------------------+-------------+---------------------+------------------+----------+
   | e4949ba4-7f73-43ad-8091-d123dea12dae | default/kubernetes  | 1ea4a08913d74aff8ed3e3bf31851236 | 10.0.0.129  | ACTIVE              | ONLINE           | amphora  |
   | 994893a7-d67f-4af2-b2fe-5a03f03102b1 | default/demo        | 1ea4a08913d74aff8ed3e3bf31851236 | 10.0.0.140  | ACTIVE              | ONLINE           | amphora  |
   +--------------------------------------+---------------------+----------------------------------+-------------+---------------------+------------------+----------+


   $ openstack loadbalancer listener list
   +--------------------------------------+--------------------------------------+----------------------------+----------------------------------+----------+---------------+----------------+
   | id                                   | default_pool_id                      | name                       | project_id                       | protocol | protocol_port | admin_state_up |
   +--------------------------------------+--------------------------------------+----------------------------+----------------------------------+----------+---------------+----------------+
   | 3223bf4a-4cdd-4d0f-9922-a3d3eb6f5e4f | 6212ecc2-c118-434a-8564-b4e763e9fa74 | default/kubernetes:443     | 1ea4a08913d74aff8ed3e3bf31851236 | HTTPS    |           443 | True           |
   | 8aebeb5e-bccc-4519-8b68-07847c1b5b73 | f5a61ce7-3e2f-4a33-bd1f-8f12b8d6a6aa | default/demo:TCP:80        | 1ea4a08913d74aff8ed3e3bf31851236 | TCP      |            80 | True           |
   +--------------------------------------+--------------------------------------+----------------------------+----------------------------------+----------+---------------+----------------+

   $ openstack loadbalancer pool list
   +--------------------------------------+----------------------------+----------------------------------+---------------------+----------+--------------+----------------+
   | id                                   | name                       | project_id                       | provisioning_status | protocol | lb_algorithm | admin_state_up |
   +--------------------------------------+----------------------------+----------------------------------+---------------------+----------+--------------+----------------+
   | 6212ecc2-c118-434a-8564-b4e763e9fa74 | default/kubernetes:443     | 1ea4a08913d74aff8ed3e3bf31851236 | ACTIVE              | HTTPS    | ROUND_ROBIN  | True           |
   | f5a61ce7-3e2f-4a33-bd1f-8f12b8d6a6aa | default/demo:TCP:80        | 1ea4a08913d74aff8ed3e3bf31851236 | ACTIVE              | TCP      | ROUND_ROBIN  | True           |
   +--------------------------------------+----------------------------+----------------------------------+---------------------+----------+--------------+----------------+


   $ openstack loadbalancer member list default/demo:TCP:80
   +--------------------------------------+------------------------------------+----------------------------------+---------------------+------------+---------------+------------------+--------+
   | id                                   | name                               | project_id                       | provisioning_status | address    | protocol_port | operating_status | weight |
   +--------------------------------------+------------------------------------+----------------------------------+---------------------+------------+---------------+------------------+--------+
   | 8aff18b1-1e5b-45df-ade1-44ed0e75ca5e | default/demo-7dd477695c-fbq4r:8080 | 1ea4a08913d74aff8ed3e3bf31851236 | ACTIVE              | 10.0.1.116 |          8080 | NO_MONITOR       |      1 |
   | 2c2c7a54-ad38-4182-b34f-daec03ee0a9a | default/demo-7dd477695c-25s99:8080 | 1ea4a08913d74aff8ed3e3bf31851236 | ACTIVE              | 10.0.1.122 |          8080 | NO_MONITOR       |      1 |
   +--------------------------------------+------------------------------------+----------------------------------+---------------------+------------+---------------+------------------+--------+

   $ kubectl get klb demo -o yaml
   apiVersion: openstack.org/v1
   kind: KuryrLoadBalancer
   metadata:
     creationTimestamp: "2020-12-21T15:31:48Z"
     finalizers:
     - kuryr.openstack.org/kuryrloadbalancer-finalizers
     generation: 7
     name: demo
     namespace: default
     resourceVersion: "714"
     selfLink: /apis/openstack.org/v1/namespaces/default/kuryrloadbalancers/demo
     uid: 3a97dfad-ad19-45da-8544-72d837ca704a
   spec:
     endpointSlices:
     - endpoints:
       - addresses:
         - 10.0.1.116
         conditions:
           ready: true
         targetRef:
           kind: Pod
           name: demo-7dd477695c-fbq4r
           namespace: default
           resourceVersion: "592"
           uid: 35d2b8ef-1f0b-4859-b6a2-f62e35418d22
       - addresses:
         - 10.0.1.122
         conditions:
           ready: true
         targetRef:
           kind: Pod
           name: demo-7dd477695c-25s99
           namespace: default
           resourceVersion: "524"
           uid: 27437c01-488b-43cd-bba3-9a70c1778598
       ports:
       - port: 8080
         protocol: TCP
     ip: 10.0.0.140
     ports:
     - port: 80
       protocol: TCP
       targetPort: "8080"
     project_id: 1ea4a08913d74aff8ed3e3bf31851236
     provider: amphora
     security_groups_ids:
     - 30cd7a25-3628-449c-992f-d23bdc4d1086
     - aaffa1a5-4b7e-4257-a444-1d39fb61ea22
     subnet_id: 3e043d77-c1b1-4374-acd5-a87a5f7a8c25
     type: ClusterIP
   status:
     listeners:
     - id: 8aebeb5e-bccc-4519-8b68-07847c1b5b73
       loadbalancer_id: 994893a7-d67f-4af2-b2fe-5a03f03102b1
       name: default/demo:TCP:80
       port: 80
       project_id: 1ea4a08913d74aff8ed3e3bf31851236
       protocol: TCP
     loadbalancer:
       id: 994893a7-d67f-4af2-b2fe-5a03f03102b1
       ip: 10.0.0.140
       name: default/demo
       port_id: 967688f5-55a7-4f84-a021-0fdf64152a8b
       project_id: 1ea4a08913d74aff8ed3e3bf31851236
       provider: amphora
       security_groups:
       - 30cd7a25-3628-449c-992f-d23bdc4d1086
       - aaffa1a5-4b7e-4257-a444-1d39fb61ea22
       subnet_id: 3e043d77-c1b1-4374-acd5-a87a5f7a8c25
     members:
     - id: 8aff18b1-1e5b-45df-ade1-44ed0e75ca5e
       ip: 10.0.1.116
       name: default/demo-7dd477695c-fbq4r:8080
       pool_id: f5a61ce7-3e2f-4a33-bd1f-8f12b8d6a6aa
       port: 8080
       project_id: 1ea4a08913d74aff8ed3e3bf31851236
       subnet_id: 3e043d77-c1b1-4374-acd5-a87a5f7a8c25
     - id: 2c2c7a54-ad38-4182-b34f-daec03ee0a9a
       ip: 10.0.1.122
       name: default/demo-7dd477695c-25s99:8080
       pool_id: f5a61ce7-3e2f-4a33-bd1f-8f12b8d6a6aa
       port: 8080
       project_id: 1ea4a08913d74aff8ed3e3bf31851236
       subnet_id: 3e043d77-c1b1-4374-acd5-a87a5f7a8c25
     pools:
     - id: f5a61ce7-3e2f-4a33-bd1f-8f12b8d6a6aa
       listener_id: 8aebeb5e-bccc-4519-8b68-07847c1b5b73
       loadbalancer_id: 994893a7-d67f-4af2-b2fe-5a03f03102b1
       name: default/demo:TCP:80
       project_id: 1ea4a08913d74aff8ed3e3bf31851236
       protocol: TCP

We can see that both pods are included as members and that the demo cluster-ip
matches with the loadbalancer vip_address. Also we can see the loadbalancer CRD
after the load balancer was created. In order to check loadbalancing among them,
we are going to curl the cluster-ip from one of the pods and see that each of
the pods is replying at a time:

.. code-block:: console

   $ kubectl exec -it demo-7dd477695c-25s99 -- /bin/sh

   sh-4.2$ curl 10.0.0.140     
   demo-7dd477695c-fbq4r: HELLO, I AM ALIVE!!!


   sh-4.2$ curl 10.0.0.140
   demo-7dd477695c-25s99: HELLO, I AM ALIVE!!!
