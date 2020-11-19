Enable network per namespace functionality (handler + driver)
=============================================================

To enable the subnet driver that creates a new network for each new namespace
the next steps are needed:

1. Enable the namespace handler to reach to namespace events, in this case,
   creation and deletion. To do that you need to add it to the list of the
   enabled handlers at kuryr.conf (details on how to edit this for
   containerized deployment can be found at :doc:`./devstack/containerized`)::

    [kubernetes]
    enabled_handlers=vif,lb,lbaasspec,namespace


   Note that if you also want to enable prepopulation of ports pools upon new
   namespace creation, you need to add the kuryrnet handler (more details on
   :doc:`./ports-pool`)::

    [kubernetes]
    enabled_handlers=vif,lb,lbaasspec,namespace,kuryrnet


2. Enable the namespace subnet driver by modifying the default
   pod_subnet_driver option at kuryr.conf::

    [kubernetes]
    pod_subnets_driver = namespace


   In addition, to ensure that pods and services at one given namespace
   cannot reach (or be reached by) the ones at another namespace, except the
   pods at the default namespace that can reach (and be reached by) any pod at
   a different namespace, the next security group driver needs to be set too::

    [kubernetes]
    pod_security_groups_driver = namespace
    service_security_groups_driver = namespace


3. Select (and create if needed) the subnet pool from where the new subnets
   will get their CIDR (e.g., the default on devstack deployment is
   shared-default-subnetpool-v4)::

    [namespace_subnet]
    pod_subnet_pool = SUBNET_POOL_ID


4. Select (and create if needed) the router where the new subnet will be
   connected (e.g., the default on devstack deployments is router1)::

    [namespace_subnet]
    pod_router = ROUTER_ID


   Note that if a new router is created, it must ensure the connectivity
   requirements between pod, service and public subnets, as in the case for
   the default subnet driver.


5. Select (and create if needed) the security groups to be attached to the
   pods at the default namespace and to the others, enabling the cross access
   between them::

    [namespace_sg]
    sg_allow_from_namespaces = SG_ID_1 # Makes SG_ID_1 allow traffic from the sg sg_allow_from_default
    sg_allow_from_default = SG_ID_2 # Makes SG_ID_2 allow traffic from the sg sg_allow_from_namespaces


Note you need to restart the kuryr controller after applying the above
detailed steps. For devstack non-containerized deployments::

  sudo systemctl restart devstack@kuryr-kubernetes.service


And for containerized deployments::

  kubectl -n kube-system get pod | grep kuryr-controller
  kubectl -n kube-system delete pod KURYR_CONTROLLER_POD_NAME


For directly enabling the driver when deploying with devstack, you just need
to add the namespace handler and state the namespace subnet driver with::

  KURYR_SUBNET_DRIVER=namespace
  KURYR_SG_DRIVER=namespace
  KURYR_ENABLED_HANDLERS=vif,lb,lbaasspec,namespace

.. note::
  If the loadbalancer maintains the source IP (such as ovn-octavia driver),
  there is no need to enforce sg rules at the load balancer level.
  To disable the enforcement, you need to set the following variable:
  KURYR_ENFORCE_SG_RULES=False

Testing the network per namespace functionality
-----------------------------------------------

1. Create two namespaces::

    $ kubectl create namespace test1
    $ kubectl create namespace test2

2. Check resources has been created::

    $ kubectl get namespaces
    NAME        STATUS        AGE
    test1       Active        14s
    test2       Active        5s
    ...         ...           ...

    $ kubectl get kuryrnets
    NAME      AGE
    ns-test1  1m
    ns-test2  1m

    $ openstack network list | grep test1
    | 7c7b68c5-d3c4-431c-9f69-fbc777b43ee5 | ns/test1-net        | 8640d134-5ea2-437d-9e2a-89236f6c0198                                       |

    $ openstack subnet list | grep test1
    | 8640d134-5ea2-437d-9e2a-89236f6c0198 | ns/test1-subnet         | 7c7b68c5-d3c4-431c-9f69-fbc777b43ee5 | 10.0.1.128/26       |

3. Create a pod in the created namespaces::

    $ kubectl run -n test1 --image quay.io/kuryr/demo demo
    deployment "demo" created

    $ kubectl run -n test2 --image quay.io/kuryr/demo demo
    deployment "demo" created

    $ kubectl -n test1 get pod -o wide
    NAME                    READY     STATUS    RESTARTS   AGE       IP           NODE
    demo-5995548848-lmmjc   1/1       Running   0          7s        10.0.1.136   node1

    $ kubectl -n test2 get pod -o wide
    NAME                    READY     STATUS    RESTARTS   AGE       IP           NODE
    demo-5135352253-dfghd   1/1       Running   0          7s        10.0.1.134   node1


4. Create a service::

    $ kubectl expose -n test1 deploy/demo --port 80 --target-port 8080
    service "demo" exposed

    $ kubectl -n test1 get svc
    NAME      TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
    demo      ClusterIP   10.0.0.141   <none>        80/TCP    18s


5. Test service connectivity from both namespaces::

    $ kubectl exec -n test1 -it demo-5995548848-lmmjc /bin/sh
    test-1-pod$ curl 10.0.0.141
    demo-5995548848-lmmjc: HELLO! I AM ALIVE!!!

    $ kubectl exec -n test2 -it demo-5135352253-dfghd /bin/sh
    test-2-pod$ curl 10.0.0.141
    ## No response


6. And finally, to remove the namespace and all its resources, including
   openstack networks, kuryrnet CRD, svc, pods, you just need to do::

    $ kubectl delete namespace test1
    $ kubectl delete namespace test2
