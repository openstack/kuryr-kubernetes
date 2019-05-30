Testing Network Connectivity
============================

Once the environment is ready, we can test that network connectivity works
among pods. First we check the status of the kubernetes cluster::

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
deployment with::

	$ kubectl run demo --image=celebdor/kuryr-demo
	deployment "demo" created


After a few seconds, the container is up an running, and a neutron port was
created with the same IP that got assigned to the pod::

	$ kubectl get pods
	NAME                    READY     STATUS    RESTARTS   AGE
	demo-2293951457-j29nb   1/1       Running   0          1m

	$ kubectl describe pod demo-2293951457-j29nb | grep IP:
	IP:             10.0.0.69

	$ openstack port list | grep demo
	| 73100cdb-84d6-4f33-93b2-e212966c65ac | demo-2293951457-j29nb | fa:16:3e:99:ac:ce | ip_address='10.0.0.69', subnet_id='3c3e18f9-d1d0-4674-b3be-9fc8561980d3' | ACTIVE |


We can then scale the deployment to 2 pods, and check connectivity between
them::

	$ kubectl scale deploy/demo --replicas=2
	deployment "demo" scaled

	$ kubectl get pods
	NAME                    READY     STATUS    RESTARTS   AGE
	demo-2293951457-gdrv2   1/1       Running   0          9s
	demo-2293951457-j29nb   1/1       Running   0          14m

	$ openstack port list | grep demo
	| 73100cdb-84d6-4f33-93b2-e212966c65ac | demo-2293951457-j29nb | fa:16:3e:99:ac:ce | ip_address='10.0.0.69', subnet_id='3c3e18f9-d1d0-4674-b3be-9fc8561980d3' | ACTIVE |
	| 95e89edd-f513-4ec8-80d0-36839725e62d | demo-2293951457-gdrv2 | fa:16:3e:e6:b4:b9 | ip_address='10.0.0.75', subnet_id='3c3e18f9-d1d0-4674-b3be-9fc8561980d3' | ACTIVE |

	$ kubectl exec -it demo-2293951457-j29nb -- /bin/sh

	sh-4.2$ curl 10.0.0.69:8080
	demo-2293951457-j29nb: HELLO, I AM ALIVE!!!

	sh-4.2$ curl 10.0.0.75:8080
	demo-2293951457-gdrv2: HELLO, I AM ALIVE!!!

	sh-4.2$ ping 10.0.0.75
	PING 10.0.0.75 (10.0.0.75) 56(84) bytes of data.
	64 bytes from 10.0.0.75: icmp_seq=1 ttl=64 time=1.14 ms
	64 bytes from 10.0.0.75: icmp_seq=2 ttl=64 time=0.250 ms


Next, we expose the service so that a neutron load balancer is created and
the service is exposed and load balanced among the available pods::

	$ kubectl get svc
	NAME         CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
	kubernetes   10.0.0.129   <none>        443/TCP   1h

	$ kubectl expose deploy/demo --port=80 --target-port=8080
	service "demo" exposed

	$ kubectl get svc
	NAME         CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
	demo         10.0.0.161   <none>        80/TCP    6s
	kubernetes   10.0.0.129   <none>        443/TCP   1h

	$ openstack loadbalancer list
	+--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+
	| id                                   | name               | tenant_id                        | vip_address | provisioning_status | provider |
	+--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+
	| 7d0cf5b5-b164-4b32-87d3-ae6c82513927 | default/kubernetes | 47c28e562795468ea52e92226e3bc7b1 | 10.0.0.129  | ACTIVE              | haproxy  |
	| c34c8d0c-a683-497f-9530-a49021e4b502 | default/demo       | 49e2683370f245e38ac2d6a8c16697b3 | 10.0.0.161  | ACTIVE              | haproxy  |
	+--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+

	$ openstack loadbalancer listener list
	+--------------------------------------+--------------------------------------+------------------------+----------------------------------+----------+---------------+----------------+
	| id                                   | default_pool_id                      | name                   | tenant_id                        | protocol | protocol_port | admin_state_up |
	+--------------------------------------+--------------------------------------+------------------------+----------------------------------+----------+---------------+----------------+
	| fc485508-c37a-48bd-9be3-898bbb7700fa | b12f00b9-44c0-430e-b1a1-e92b57247ad2 | default/demo:TCP:80    | 49e2683370f245e38ac2d6a8c16697b3 | TCP      |            80 | True           |
	| abfbafd8-7609-4b7d-9def-4edddf2b887b | 70bed821-9a9f-4e1d-8c7e-7df89a923982 | default/kubernetes:443 | 47c28e562795468ea52e92226e3bc7b1 | HTTPS    |           443 | True           |
	+--------------------------------------+--------------------------------------+------------------------+----------------------------------+----------+---------------+----------------+

	$ openstack loadbalancer pool list
	+--------------------------------------+------------------------+----------------------------------+--------------+----------+----------------+
	| id                                   | name                   | tenant_id                        | lb_algorithm | protocol | admin_state_up |
	+--------------------------------------+------------------------+----------------------------------+--------------+----------+----------------+
	| 70bed821-9a9f-4e1d-8c7e-7df89a923982 | default/kubernetes:443 | 47c28e562795468ea52e92226e3bc7b1 | ROUND_ROBIN  | HTTPS    | True           |
	| b12f00b9-44c0-430e-b1a1-e92b57247ad2 | default/demo:TCP:80    | 49e2683370f245e38ac2d6a8c16697b3 | ROUND_ROBIN  | TCP      | True           |
	+--------------------------------------+------------------------+----------------------------------+--------------+----------+----------------+

	$ openstack loadbalancer member list default/demo:TCP:80
	+--------------------------------------+------------------------------------+----------------------------------+-----------+---------------+--------+--------------------------------------+----------------+
	| id                                   | name                               | tenant_id                        | address   | protocol_port | weight | subnet_id                            | admin_state_up |
	+--------------------------------------+------------------------------------+----------------------------------+-----------+---------------+--------+--------------------------------------+----------------+
	| c0057ce6-64da-4613-b284-faf5477533ab | default/demo-2293951457-j29nb:8080 | 49e2683370f245e38ac2d6a8c16697b3 | 10.0.0.69 |          8080 |      1 | 55405e9d-4e25-4a55-bac2-e25ee88584e1 | True           |
	| 7a0c0ef9-35ce-4134-b92a-2e73f0f8fe98 | default/demo-2293951457-gdrv2:8080 | 49e2683370f245e38ac2d6a8c16697b3 | 10.0.0.75 |          8080 |      1 | 55405e9d-4e25-4a55-bac2-e25ee88584e1 | True           |
	+--------------------------------------+------------------------------------+----------------------------------+-----------+---------------+--------+--------------------------------------+----------------+


We can see that both pods are included as members and that the demo cluster-ip
matches with the loadbalancer vip_address. In order to check loadbalancing
among them, we are going to curl the cluster-ip from one of the pods and see
that each of the pods is replying at a time::

	$ kubectl exec -it demo-2293951457-j29nb -- /bin/sh

	sh-4.2$ curl 10.0.0.161
	demo-2293951457-j29nb: HELLO, I AM ALIVE!!!

	sh-4.2$ curl 10.0.0.161
	demo-2293951457-gdrv2: HELLO, I AM ALIVE!!!
