===================================
Testing Nested Network Connectivity
===================================

Similarly to the baremetal testing, we can create a demo deployment, scale it
to any number of pods and expose the service to check if the deployment was
successful:

.. code-block:: console

   $ kubectl create deployment demo --image=quay.io/kuryr/demo
   $ kubectl scale deploy/demo --replicas=2
   $ kubectl expose deploy/demo --port=80 --target-port=8080

After a few seconds you can check that the pods are up and running and the
neutron subports have been created (and in ACTIVE status) at the undercloud:

.. code-block:: console

   (OVERCLOUD) $ kubectl get pods
   NAME                    READY     STATUS    RESTARTS   AGE
   demo-1575152709-4k19q   1/1       Running   0          2m
   demo-1575152709-vmjwx   1/1       Running   0          12s

   (UNDERCLOUD) $ openstack port list | grep demo
   | 1019bc07-fcdd-4c78-adbd-72a04dffd6ba | demo-1575152709-4k19q | fa:16:3e:b5:de:1f | ip_address='10.0.0.65', subnet_id='b98d40d1-57ac-4909-8db5-0bf0226719d8' | ACTIVE |
   | 33c4d79f-4fde-4817-b672-a5ec026fa833 | demo-1575152709-vmjwx | fa:16:3e:32:58:38 | ip_address='10.0.0.70', subnet_id='b98d40d1-57ac-4909-8db5-0bf0226719d8' | ACTIVE |

Then, we can check that the service has been created, as well as the
respective loadbalancer at the undercloud:

.. code-block:: console

   (OVERCLOUD) $ kubectl get svc
   NAME             CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
   svc/demo         10.0.0.171   <none>        80/TCP    1m
   svc/kubernetes   10.0.0.129   <none>        443/TCP   45m

   (UNDERCLOUD) $ openstack loadbalancer list
   +--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+
   | id                                   | name               | tenant_id                        | vip_address | provisioning_status | provider |
   +--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+
   | a3b85089-1fbd-47e1-a697-bbdfd0fa19e3 | default/kubernetes | 672bc45aedfe4ec7b0e90959b1029e30 | 10.0.0.129  | ACTIVE              | haproxy  |
   | e55b3f75-15dc-4bc5-b4f4-bce65fc15aa4 | default/demo       | e4757688696641218fba0bac86ff7117 | 10.0.0.171  | ACTIVE              | haproxy  |
   +--------------------------------------+--------------------+----------------------------------+-------------+---------------------+----------+


Finally, you can log in into one of the containers and curl the service IP to
check that each time a different pod answer the request:

.. code-block:: console

   $ kubectl exec -it demo-1575152709-4k19q -- /bin/sh
   sh-4.2$ curl 10.0.0.171
   demo-1575152709-4k19q: HELLO, I AM ALIVE!!!
   sh-4.2$ curl 10.0.0.771
   demo-1575152709-vmjwx: HELLO, I AM ALIVE!!!
