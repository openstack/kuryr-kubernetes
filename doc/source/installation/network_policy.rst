Enable network policy support functionality
===========================================

Please follow the next steps in order to enable the network policy support
feature:

1. Enable the policy handler to response to network policy events. As this is
   not enabled by default you'd have to explicitly add that to the list of
   enabled handlers at kuryr.conf (further info on how to do this can be found
   at :doc:`./devstack/containerized`)::

    [kubernetes]
    enabled_handlers=vif,lb,lbaasspec,policy

Note that you need to restart the kuryr controller after applying the above
detailed steps. For devstack non-containerized deployments::

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
        - ipBlock:
            cidr: 172.17.0.0/16
            except:
            - 172.17.1.0/24
        - namespaceSelector:
            matchLabels:
            project: myproject
        - podSelector:
            matchLabels:
            role: frontend
        ports:
        - protocol: TCP
        port: 6379
    egress:
    - to:
        - ipBlock:
            cidr: 10.0.0.0/24
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

    $ openstack security group list | grep test-network-policy
    | dabdf308-7eed-43ef-a058-af84d1954acb | test-network-policy

4. Check that the teardown of the resources once the network policy is removed::

    $ kubectl delete -f network_policy.yml

    $ kubectl get kuryrnetpolicies

    $ kubectl get networkpolicies

    $ openstack security group list | grep test-network-policy
