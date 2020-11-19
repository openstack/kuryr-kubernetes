Enable network policy support functionality
===========================================

Enable policy, pod_label and namespace handlers to respond to network policy events.
As this is not done by default you'd have to explicitly add that to the list of enabled
handlers at kuryr.conf (further info on how to do this can be found  at
:doc:`./devstack/containerized`)::

    [kubernetes]
    enabled_handlers=vif,lb,lbaasspec,policy,pod_label,namespace,kuryrnetpolicy


Note that if you also want to enable prepopulation of ports pools upon new
namespace creation, you need to add the kuryrnet handler (more details on
:doc:`./ports-pool`)::

    [kubernetes]
    enabled_handlers=vif,lb,lbaasspec,policy,pod_label,namespace,kuryrnetpolicy,kuryrnet


After that, enable also the security group drivers for policies::

    [kubernetes]
    service_security_groups_driver = policy
    pod_security_groups_driver = policy

.. warning::
  The correct behavior for pods that have no network policy applied is to allow
  all ingress and egress traffic. If you want that to be enforced, please make
  sure to create an SG allowing all traffic and add it to
  ``[neutron_defaults]pod_security_groups`` setting in ``kuryr.conf``::

    [neutron_defaults]
    pod_security_groups = ALLOW_ALL_SG_ID

Enable the namespace subnet driver by modifying the default pod_subnet_driver
option::

    [kubernetes]
    pod_subnets_driver = namespace

Select the subnet pool from where the new subnets will get their CIDR::

    [namespace_subnet]
    pod_subnet_pool = SUBNET_POOL_ID

Lastly, select the router where the new subnet will be connected::

    [namespace_subnet]
    pod_router = ROUTER_ID

Note you need to restart the kuryr controller after applying the above step.
For devstack non-containerized deployments::

    $ sudo systemctl restart devstack@kuryr-kubernetes.service

Same for containerized deployments::

    $ kubectl -n kube-system get pod | grep kuryr-controller
    $ kubectl -n kube-system delete pod KURYR_CONTROLLER_POD_NAME

For directly enabling the driver when deploying with devstack, you just need
to add the policy, pod_label and namespace handler and drivers with::

    KURYR_ENABLED_HANDLERS=vif,lb,lbaasspec,policy,pod_label,namespace,kuryrnetpolicy
    KURYR_SG_DRIVER=policy
    KURYR_SUBNET_DRIVER=namespace

.. note::
  If the loadbalancer maintains the source IP (such as ovn-octavia driver),
  there is no need to enforce sg rules at the load balancer level.
  To disable the enforcement, you need to set the following variable:
  KURYR_ENFORCE_SG_RULES=False

Testing the network policy support functionality
------------------------------------------------

1. Given a yaml file with a network policy, such as::

    apiVersion: networking.k8s.io/v1
    kind: NetworkPolicy
    metadata:
      name: test-network-policy
      namespace: default
    spec:
      podSelector:
        matchLabels:
          project: default
      policyTypes:
      - Ingress
      - Egress
      ingress:
      - from:
        - namespaceSelector:
            matchLabels:
              project: default
        ports:
        - protocol: TCP
          port: 6379
      egress:
      - to:
        - namespaceSelector:
            matchLabels:
              project: default
        ports:
        - protocol: TCP
          port: 5978

2. Apply the network policy::

    $ kubectl apply -f network_policy.yml

3. Check that the resources has been created::

    $ kubectl get kuryrnetpolicies
    NAME                     AGE
    np-test-network-policy   2s

    $ kubectl get networkpolicies
    NAME                  POD-SELECTOR   AGE
    test-network-policy   role=db        2s

    $ openstack security group list | grep sg-test-network-policy
    | dabdf308-7eed-43ef-a058-af84d1954acb | sg-test-network-policy

4. Check that the rules are in place for the security group::

    $ kubectl get kuryrnetpolicy np-test-network-policy -o yaml

    apiVersion: openstack.org/v1
    kind: KuryrNetPolicy
    metadata:
      annotations:
        networkpolicy_name: test-network-policy
        networkpolicy_namespace: default
        networkpolicy_uid: aee1c59f-c634-11e8-b63d-002564fdd760
      clusterName: ""
      creationTimestamp: 2018-10-02T11:17:02Z
      generation: 0
      name: np-test-network-policy
      namespace: default
      resourceVersion: "2117"
      selfLink: /apis/openstack.org/v1/namespaces/default/kuryrnetpolicies/np-test-network-policy
      uid: afb99326-c634-11e8-b63d-002564fdd760
    spec:
      egressSgRules:
      - security_group_rule:
          description: Kuryr-Kubernetes NetPolicy SG rule
          direction: egress
          ethertype: IPv4
          id: 6297c198-b385-44f3-8b43-29951f933a8f
          port_range_max: 5978
          port_range_min: 5978
          protocol: tcp
          security_group_id: cdee7815-3b49-4a3e-abc8-31e384ab75c5
      ingressSgRules:
      - security_group_rule:
          description: Kuryr-Kubernetes NetPolicy SG rule
          direction: ingress
          ethertype: IPv4
          id: f4e11e73-81c6-4c1b-9760-714eedff417b
          port_range_max: 6379
          port_range_min: 6379
          protocol: tcp
          security_group_id: cdee7815-3b49-4a3e-abc8-31e384ab75c5
      securityGroupId: cdee7815-3b49-4a3e-abc8-31e384ab75c5
      securityGroupName: sg-test-network-policy
      networkpolicy_spec:
        egress:
        - to:
          - namespaceSelector:
              matchLabels:
                project: default
          ports:
          - port: 5978
            protocol: TCP
        ingress:
        - from:
          - namespaceSelector:
              matchLabels:
                project: default
          ports:
          - port: 6379
            protocol: TCP
        podSelector:
          matchLabels:
            project: default
        policyTypes:
        - Ingress
        - Egress

    $ openstack security group rule list sg-test-network-policy --protocol tcp -c "IP Protocol" -c "Port Range" -c "Direction" --long
    +-------------+------------+-----------+
    | IP Protocol | Port Range | Direction |
    +-------------+------------+-----------+
    | tcp         | 6379:6379  | ingress   |
    | tcp         | 5978:5978  | egress    |
    +-------------+------------+-----------+

5. Create a pod::

    $ kubectl create deployment --image kuryr/demo demo
    deployment "demo" created

    $ kubectl get pod -o wide
    NAME                    READY     STATUS    RESTARTS   AGE       IP
    demo-5558c7865d-fdkdv   1/1       Running   0          44s       10.0.0.68

6. Get the pod port and check its security group rules::

    $ openstack port list --fixed-ip ip-address=10.0.0.68 -f value -c ID
    5d29b83c-714c-4579-8987-d0c0558420b3

    $ openstack port show 5d29b83c-714c-4579-8987-d0c0558420b3 | grep security_group_ids
    | security_group_ids    | bb2ac605-56ff-4688-b4f1-1d045ad251d0

    $ openstack security group rule list bb2ac605-56ff-4688-b4f1-1d045ad251d0
    --protocol tcp -c "IP Protocol" -c "Port Range"
    +-------------+------------+-----------+
    | IP Protocol | Port Range | Direction |
    +-------------+------------+-----------+
    | tcp         | 6379:6379  | ingress   |
    | tcp         | 5978:5978  | egress    |
    +-------------+------------+-----------+

7. Try to curl the pod on port 8080 (hint: it won't work!)::

    $ curl 10.0.0.68:8080

8. Update network policy to allow ingress 8080 port::

    $ kubectl patch networkpolicy test-network-policy -p '{"spec":{"ingress":[{"ports":[{"port": 8080,"protocol": "TCP"}]}]}}'
    networkpolicy "test-network-policy" patched

    $ kubectl get knp np-test-network-policy -o yaml
    apiVersion: openstack.org/v1
    kind: KuryrNetPolicy
    metadata:
      annotations:
        networkpolicy_name: test-network-policy
        networkpolicy_namespace: default
        networkpolicy_uid: aee1c59f-c634-11e8-b63d-002564fdd760
      clusterName: ""
      creationTimestamp: 2018-10-02T11:17:02Z
      generation: 0
      name: np-test-network-policy
      namespace: default
      resourceVersion: "1546"
      selfLink: /apis/openstack.org/v1/namespaces/default/kuryrnetpolicies/np-test-network-policy
      uid: afb99326-c634-11e8-b63d-002564fdd760
    spec:
      egressSgRules:
      - security_group_rule:
          description: Kuryr-Kubernetes NetPolicy SG rule
          direction: egress
          ethertype: IPv4
          id: 1969a0b3-55e1-43d7-ba16-005b4ed4cbb7
          port_range_max: 5978
          port_range_min: 5978
          protocol: tcp
          security_group_id: cdee7815-3b49-4a3e-abc8-31e384ab75c5
      ingressSgRules:
      - security_group_rule:
          description: Kuryr-Kubernetes NetPolicy SG rule
          direction: ingress
          ethertype: IPv4
          id: 6598aa1f-4f94-4fb2-81ce-d3649ba28f33
          port_range_max: 8080
          port_range_min: 8080
          protocol: tcp
          security_group_id: cdee7815-3b49-4a3e-abc8-31e384ab75c5
      securityGroupId: cdee7815-3b49-4a3e-abc8-31e384ab75c5
      networkpolicy_spec:
        egress:
        - ports:
          - port: 5978
            protocol: TCP
          to:
          - namespaceSelector:
              matchLabels:
                project: default
        ingress:
        - ports:
          - port: 8080
            protocol: TCP
          from:
          - namespaceSelector:
              matchLabels:
                project: default
        podSelector:
          matchLabels:
            project: default
        policyTypes:
        - Ingress
        - Egress

    $ openstack security group rule list sg-test-network-policy -c "IP Protocol" -c "Port Range" -c "Direction" --long
    +-------------+------------+-----------+
    | IP Protocol | Port Range | Direction |
    +-------------+------------+-----------+
    | tcp         | 8080:8080  | ingress   |
    | tcp         | 5978:5978  | egress    |
    +-------------+------------+-----------+

9. Try to curl the pod ip after patching the network policy::

    $ curl 10.0.0.68:8080
    demo-5558c7865d-fdkdv: HELLO! I AM ALIVE!!!


Note the curl only works from pods (neutron ports) on a namespace that has
the label `project: default` as stated on the policy namespaceSelector.


10. We can also create a single pod, without a label and check that there is
    no connectivity to it, as it does not match the network policy
    podSelector::

      $ cat sample-pod.yml
      apiVersion: v1
      kind: Pod
      metadata:
        name: demo-pod
      spec:
        containers:
        - image: quay.io/kuryr/demo
          imagePullPolicy: Always
          name: demo-pod

      $ kubectl apply -f sample-pod.yml
      $ curl demo-pod-IP:8080
      NO REPLY


11. If we add to the pod a label that match a network policy podSelector, in
    this case 'project: default', the network policy will get applied on the
    pod, and the traffic will be allowed::

      $ kubectl label pod demo-pod project=default
      $ curl demo-pod-IP:8080
      demo-pod-XXX: HELLO! I AM ALIVE!!!


12. Confirm the teardown of the resources once the network policy is removed::

    $ kubectl delete -f network_policy.yml
    $ kubectl get kuryrnetpolicies
    $ kubectl get networkpolicies
    $ openstack security group list | grep sg-test-network-policy
