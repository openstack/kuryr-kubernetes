Enable network policy support functionality
===========================================

Enable the policy handler to respond to network policy events. As this is not
done by default you'd have to explicitly add that to the list of enabled
handlers at kuryr.conf (further info on how to do this can be found  at
:doc:`./devstack/containerized`)::

    [kubernetes]
    enabled_handlers=vif,lb,lbaasspec,policy

Note you need to restart the kuryr controller after applying the above step.
For devstack non-containerized deployments::

    $ sudo systemctl restart devstack@kuryr-kubernetes.service


Same for containerized deployments::

    $ kubectl -n kube-system get pod | grep kuryr-controller
    $ kubectl -n kube-system delete pod KURYR_CONTROLLER_POD_NAME


For directly enabling the driver when deploying with devstack, you just need
to add the policy handler with::

    KURYR_ENABLED_HANDLERS=vif,lb,lbaasspec,policy


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
        role: db
    policyTypes:
    - Ingress
    - Egress
    ingress:
    - from:
        ports:
        - protocol: TCP
        port: 6379
    egress:
    - to:
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
        - ports:
          - port: 5978
            protocol: TCP
          to:
        ingress:
        - from:
          ports:
          - port: 6379
            protocol: TCP
        podSelector:
          matchLabels:
            role: db
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

5. Network policies can also be updated in the following way::

    $ kubectl patch networkpolicy test-network-policy -p '{"spec":{"ingress":[{"ports":[{"port": 8081,"protocol": "UDP"}]}]}}'
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
          port_range_max: 8081
          port_range_min: 8081
          protocol: udp
          security_group_id: cdee7815-3b49-4a3e-abc8-31e384ab75c5
      securityGroupId: cdee7815-3b49-4a3e-abc8-31e384ab75c5
      networkpolicy_spec:
        egress:
        - ports:
          - port: 5978
            protocol: TCP
          to:
        ingress:
        - ports:
          - port: 8081
            protocol: UDP
        policyTypes:
        - Ingress
        - Egress

    $ openstack security group rule list sg-test-network-policy -c "IP Protocol" -c "Port Range" -c "Direction" --long
    +-------------+------------+-----------+
    | IP Protocol | Port Range | Direction |
    +-------------+------------+-----------+
    | tcp         | 6379:6379  | ingress   |
    | udp         | 8081:8081  | egress    |
    +-------------+------------+-----------+

6. Confirm the teardown of the resources once the network policy is removed::

    $ kubectl delete -f network_policy.yml

    $ kubectl get kuryrnetpolicies

    $ kubectl get networkpolicies

    $ openstack security group list | grep sg-test-network-policy
