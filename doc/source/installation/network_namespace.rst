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


2. Enable the namespace subnet driver by modifying the default
   pod_subnet_driver option at kuryr.conf::

    [kubernetes]
    pod_subnets_driver = namespace


3. Select (and create if needed) the subnet pool from where the new subnets
   will get their CIDR (e.g., the default on devstack deployment is
   shared-default-subnetpool-v4)::

    [namespace_subnet]
    pod_subnet_pool = SUBNET_POOL_ID


4. Select (and create if needed) the router where the new subnet will be
   connected (e.g., the default on devstack deployments is router1)::

    [namespace_subnet]
    pod_router = ROUTER_ID


   Note if a new router is created, it must ensure the connectivity
   requirements between pod, service and public subnets, as in the case for
   the default subnet driver.


Note you need to restart the kuryr controller after applying the above
detailed steps. For devstack non-containerized deployments::

  sudo systemctl restart devstack@kuryr-kubernetes.service


And for containerized deployments::

  kubectl -n kube-system get pod | grep kuryr-controller
  kubectl -n kube-system delete pod KURYR_CONTROLLER_POD_NAME


For directly enabling the driver when deploying with devstack, you just need
to add the namespace handler and state the namespace subnet driver with::

  KURYR_SUBNET_DRIVER=namespace
  KURYR_ENABLED_HANDLERS=vif,lb,lbaasspec,namespace


Testing the network per namespace functionality
-----------------------------------------------

1. Create a namespace::

    $ kubectl create namespace test

2. Check resources has been created::

    $ kubectl get namespaces
    NAME        STATUS        AGE
    test        Active        4s
    ...         ...           ...

    $ kubectl get kuryrnets
    NAME      AGE
    ns-test   1m

    $ openstack network list | grep test
    | 7c7b68c5-d3c4-431c-9f69-fbc777b43ee5 | ns/test-net        | 8640d134-5ea2-437d-9e2a-89236f6c0198                                       |

    $ openstack subnet list | grep test
    | 8640d134-5ea2-437d-9e2a-89236f6c0198 | ns/test-subnet         | 7c7b68c5-d3c4-431c-9f69-fbc777b43ee5 | 10.0.1.128/26       |

3. Create a pod in the created namespace::

    $ kubectl run -n test --image kuryr/demo demo
    deployment "demo" created

    $ kubectl -n test get pod -o wide
    NAME                    READY     STATUS    RESTARTS   AGE       IP           NODE
    demo-5995548848-lmmjc   1/1       Running   0          7s        10.0.1.136   node1


4. Create a service::

    $ kubectl expose -n test deploy/demo --port 80 --target-port 8080
    service "demo" exposed

    $ kubectl -n test get svc
    NAME      TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
    demo      ClusterIP   10.0.0.141   <none>        80/TCP    18s


5. Test service connectivity::

    $ curl 10.0.0.141
    demo-5995548848-lmmjc: HELLO! I AM ALIVE!!!

