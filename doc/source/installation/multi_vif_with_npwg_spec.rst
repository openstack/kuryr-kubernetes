Configure Pod with Additional Interfaces
========================================

To create pods with additional Interfaces follow the Kubernetes Network Custom
Resource Definition De-facto Standard Version 1 [#]_, the next steps can be
followed:

1. Create Neutron net/subnets which you want the additional interfaces attach
   to.

.. code-block:: bash

    $ openstack network create net-a
    $ openstack subnet create subnet-a --subnet-range 192.0.2.0/24 --network net-a

2. Create CRD of 'NetworkAttachmentDefinition' as defined in NPWG spec.

.. code-block:: bash

    $ cat << EOF > nad.yaml
    apiVersion: apiextensions.k8s.io/v1beta1
    kind: CustomResourceDefinition
    metadata:
      name: network-attachment-definitions.k8s.cni.cncf.io
    spec:
      group: k8s.cni.cncf.io
      version: v1
      scope: Namespaced
      names:
        plural: network-attachment-definitions
        singular: network-attachment-definition
        kind: NetworkAttachmentDefinition
        shortNames:
        - net-attach-def
    validation:
      openAPIV3Schema:
        properties:
          spec:
            properties:
              config:
                type: string
    EOF
    $ kubectl apply -f nad.yaml

3. Create NetworkAttachmentDefinition object with the UUID of Neutron subnet
defined in step 1.

.. code-block:: bash

    $ cat << EOF > net-a.yaml
    apiVersion: "k8s.cni.cncf.io/v1"
    kind: NetworkAttachmentDefinition
    metadata:
      name: "net-a"
      annotations:
        openstack.org/kuryr-config: '{
        "subnetId": "uuid-of-neutron-subnet-a"
        }'
    EOF
    $ kubectl apply -f net-a.yaml

4. Enable the multi-vif driver by setting 'multi_vif_drivers' in kuryr.conf.
   Then restart kuryr-controller.

.. code-block:: ini

    [kubernetes]
    multi_vif_drivers = npwg_multiple_interfaces

5. Add additional interfaces to pods definition. e.g.

.. code-block:: bash

    $ cat << EOF > pod.yaml
    apiVersion: v1
    kind: Pod
    metadata:
      name: nginx4
      annotations:
        k8s.v1.cni.cncf.io/networks: net-a
    spec:
      containers:
      - name: nginx
          image: nginx:1.7.9
          ports:
          - containerPort: 80
    EOF
    $ kubectl apply -f pod.yaml

You may put a list of network separated with comma to attach Pods to more networks.

Reference
---------

.. [#] https://docs.google.com/document/d/1Ny03h6IDVy_e_vmElOqR7UdTPAG_RNydhVE1Kx54kFQ/edit?usp=sharing
