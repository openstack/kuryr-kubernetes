=============================================================
Enable network per namespace functionality (handler + driver)
=============================================================

To enable the subnet driver that creates a new network for each new namespace
the next steps are needed:

#. Enable the namespace handler to reach to namespace events, in this case,
   creation and deletion. To do that you need to add it to the list of the
   enabled handlers at kuryr.conf (details on how to edit this for
   containerized deployment can be found at :doc:`./devstack/containerized`):

   .. code-block:: ini

      [kubernetes]
      enabled_handlers=vif,endpoints,service,kuryrloadbalancer,namespace,
                       kuryrnetwork,kuryrport

   Note that if you also want to enable prepopulation of ports pools upon
   creation of first pod on pods network in a namespace, you need to also
   add the kuryrnetwork_population handler (more details on :doc:`./ports-pool`):

   .. code-block:: ini

      [kubernetes]
      enabled_handlers=vif,endpoints,service,kuryrloadbalancer,namespace,
                       kuryrnetwork,kuryrport,kuryrnetwork_population

#. Enable the namespace subnet driver by modifying the default
   pod_subnet_driver option at kuryr.conf:

   .. code-block:: ini

      [kubernetes]
      pod_subnets_driver = namespace

#. Select (and create if needed) the subnet pool from where the new subnets
   will get their CIDR (e.g., the default on devstack deployment is
   shared-default-subnetpool-v4):

   .. code-block:: ini

      [namespace_subnet]
      pod_subnet_pool = SUBNET_POOL_ID

#. Select (and create if needed) the router where the new subnet will be
   connected (e.g., the default on devstack deployments is router1):

   .. code-block:: ini

      [namespace_subnet]
      pod_router = ROUTER_ID

   Note that if a new router is created, it must ensure the connectivity
   requirements between pod, service and public subnets, as in the case for
   the default subnet driver.

Note you need to restart the kuryr controller after applying the above
detailed steps. For devstack non-containerized deployments:

.. code-block:: console

   $ sudo systemctl restart devstack@kuryr-kubernetes.service

And for containerized deployments:

.. code-block:: console

   $ kubectl -n kube-system get pod | grep kuryr-controller
   $ kubectl -n kube-system delete pod KURYR_CONTROLLER_POD_NAME

For directly enabling the driver when deploying with devstack, you just need
to add the namespace handler and state the namespace subnet driver with:

.. code-block:: console

   KURYR_SUBNET_DRIVER=namespace
   KURYR_ENABLED_HANDLERS=vif,endpoints,service,kuryrloadbalancer,namespace,
                          kuryrnetwork,kuryrport

.. note::

   If the loadbalancer maintains the source IP (such as ovn-octavia driver),
   there is no need to enforce sg rules at the load balancer level.
   To disable the enforcement, you need to set the following variable:
   KURYR_ENFORCE_SG_RULES=False


Testing the network per namespace functionality
-----------------------------------------------

#. Create two namespaces:

   .. code-block:: console

      $ kubectl create namespace test1
      $ kubectl create namespace test2

#. Check resources has been created:

   .. code-block:: console

      $ kubectl get namespaces
      NAME        STATUS        AGE
      test1       Active        14s
      test2       Active        5s
      ...         ...           ...

      $ kubectl get kuryrnetworks -A
      NAME      AGE
      ns-test1  1m
      ns-test2  1m

      $ openstack network list | grep test1
      | 7c7b68c5-d3c4-431c-9f69-fbc777b43ee5 | ns/test1-net        | 8640d134-5ea2-437d-9e2a-89236f6c0198                                       |

      $ openstack subnet list | grep test1
      | 8640d134-5ea2-437d-9e2a-89236f6c0198 | ns/test1-subnet         | 7c7b68c5-d3c4-431c-9f69-fbc777b43ee5 | 10.0.1.128/26       |

#. Create a pod in the created namespaces:

   .. code-block:: console

      $ kubectl create deployment -n test1 --image quay.io/kuryr/demo demo
      deployment "demo" created

      $ kubectl create deployment -n test2 --image quay.io/kuryr/demo demo
      deployment "demo" created

      $ kubectl -n test1 get pod -o wide
      NAME                    READY     STATUS    RESTARTS   AGE       IP           NODE
      demo-5995548848-lmmjc   1/1       Running   0          7s        10.0.1.136   node1

      $ kubectl -n test2 get pod -o wide
      NAME                    READY     STATUS    RESTARTS   AGE       IP           NODE
      demo-5135352253-dfghd   1/1       Running   0          7s        10.0.1.134   node1

#. Create a service:

   .. code-block:: console

      $ kubectl expose -n test1 deploy/demo --port 80 --target-port 8080
      service "demo" exposed

      $ kubectl -n test1 get svc
      NAME      TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
      demo      ClusterIP   10.0.0.141   <none>        80/TCP    18s

#. Test service connectivity from both namespaces:

   .. code-block:: console

      $ kubectl exec -n test1 -it demo-5995548848-lmmjc /bin/sh
      test-1-pod$ curl 10.0.0.141
      demo-5995548848-lmmjc: HELLO! I AM ALIVE!!!

#. And finally, to remove the namespace and all its resources, including
   openstack networks, kuryrnetwork CRD, svc, pods, you just need to
   do:

   .. code-block:: console

      $ kubectl delete namespace test1
      $ kubectl delete namespace test2
