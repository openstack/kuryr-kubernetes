Enable OCP-Router functionality
===============================

To enable OCP-Router functionality we should set the following:

- Setting L7 Router.
- Configure Kuryr to support L7 Router and OCP-Route resources.

Setting L7 Router
------------------

The L7 Router is the ingress point for the external traffic destined
for services in the K8S/OCP cluster.
The next steps are needed for setting the L7 Router:

1. Create LoadBalancer that will run the L7 loadbalancing::

    $ openstack loadbalancer create --name  kuryr-l7-router  --vip-subnet-id  k8s-service-subnet
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | admin_state_up      | True                                 |
    | created_at          | 2018-06-28T06:34:15                  |
    | description         |                                      |
    | flavor              |                                      |
    | id                  | 99f580e6-d894-442a-bc5f-4d14b41e10d2 |
    | listeners           |                                      |
    | name                | kuryr-l7-router                      |
    | operating_status    | OFFLINE                              |
    | pools               |                                      |
    | project_id          | 24042703aba141b89217e098e495cea1     |
    | provider            | amphora                              |
    | provisioning_status | PENDING_CREATE                       |
    | updated_at          | None                                 |
    | vip_address         | 10.0.0.171                           |
    | vip_network_id      | 65875d24-5a54-43fb-91a7-087e956deb1a |
    | vip_port_id         | 42c6062a-644a-4004-a4a6-5a88bf596196 |
    | vip_qos_policy_id   | None                                 |
    | vip_subnet_id       | 01f21201-65a3-4bc5-a7a8-868ccf4f0edd |
    +---------------------+--------------------------------------+
    $



2. Create floating IP address that should be accessible from external network::

        $ openstack floating ip create --subnet public-subnet  public
        +---------------------+--------------------------------------+
        | Field               | Value                                |
        +---------------------+--------------------------------------+
        | created_at          | 2018-06-28T06:31:36Z                 |
        | description         |                                      |
        | dns_domain          | None                                 |
        | dns_name            | None                                 |
        | fixed_ip_address    | None                                 |
        | floating_ip_address | 172.24.4.3                           |
        | floating_network_id | 3371c2ba-edb5-45f2-a589-d35080177311 |
        | id                  | c971f6d3-ba63-4318-a9e7-43cbf85437c2 |
        | name                | 172.24.4.3                           |
        | port_details        | None                                 |
        | port_id             | None                                 |
        | project_id          | 24042703aba141b89217e098e495cea1     |
        | qos_policy_id       | None                                 |
        | revision_number     | 0                                    |
        | router_id           | None                                 |
        | status              | DOWN                                 |
        | subnet_id           | 939eeb1f-20b8-4185-a6b1-6477fbe73409 |
        | tags                | []                                   |
        | updated_at          | 2018-06-28T06:31:36Z                 |
        +---------------------+--------------------------------------+
        $


3. Bind the floating IP to LB vip::

        [stack@gddggd devstack]$ openstack floating ip set --port 42c6062a-644a-4004-a4a6-5a88bf596196  172.24.4.3


Configure Kuryr to support L7 Router and OCP-Route resources
------------------------------------------------------------

1. Configure the L7 Router by adding the LB UUID at kuryr.conf::

        [ingress]
        l7_router_uuid = 99f580e6-d894-442a-bc5f-4d14b41e10d2


2. Enable the ocp-route and k8s-endpoint handlers. For that you need to add
   this handlers to the enabled handlers list at kuryr.conf (details on how
   to edit this for containerized deployment can be found
   at :doc:`./devstack/containerized`)::

        [kubernetes]
        enabled_handlers=vif,lb,lbaasspec,ocproute,ingresslb

Note: you need to restart the kuryr controller after applying the above
detailed steps. For devstack non-containerized deployments::

  sudo systemctl restart devstack@kuryr-kubernetes.service


And for containerized deployments::

  kubectl -n kube-system get pod | grep kuryr-controller
  kubectl -n kube-system delete pod KURYR_CONTROLLER_POD_NAME


For directly enabling both L7 router and OCP-Route handlers when deploying
with devstack, you just need to add the following at local.conf file::

  KURYR_ENABLE_INGRESS=True
  KURYR_ENABLED_HANDLERS=vif,lb,lbaasspec,ocproute,ingresslb


Testing OCP-Route functionality
-------------------------------

1. Create a service::

    $ oc run --image=celebdor/kuryr-demo  kuryr-demo
    $ oc scale dc/kuryr-demo  --replicas=2
    $ oc expose dc/kuryr-demo --port 80 --target-port 8080


2. Create a Route object pointing to above service (kuryr-demo)::

    $  cat >> route.yaml << EOF
    > apiVersion: v1
    > kind: Route
    > metadata:
    >  name: testroute
    > spec:
    >  host: www.firstroute.com
    >  to:
    >    kind: Service
    >    name: kuryr-demo
    > EOF
    $ oc create -f route.yaml


3. Curl L7 router's FIP using specified hostname::

    $  curl  --header 'Host: www.firstroute.com'  172.24.4.3
       kuryr-demo-1-gzgj2: HELLO, I AM ALIVE!!!
    $
