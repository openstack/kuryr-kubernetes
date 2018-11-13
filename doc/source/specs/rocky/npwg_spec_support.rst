==========================================================================
Kubernetes Network Custom Resource Definition De-facto Standard v1 Support
==========================================================================

https://blueprints.launchpad.net/kuryr-kubernetes/+spec/kuryr-npwg-spec-support

This spec proposes an approach to support the mechanism defined in Kubernetes
Network Custom Resource Definition De-facto Standard Version 1 [#]_, which is
used to attach multiple VIFs to Pods.

Problem Description
-------------------

There is always a desire for Pods to be able to be attached to multiple
interfaces in NFV use cases. However CNI plugins which have implemented this
functionality are using different way of defining the additional interfaces in
Pods. There is no standard approach among those CNI plugins.

Therefore, the Networking Plumbing Working Group [#]_ drafted a spec (the NPWG
spec) trying to standardize the way of attaching Pods to multiple networks.

Proposed Change
---------------

The NPWG spec defines a "Network" Custom Resource object which describes how to
attach a Pod to the logical or physical network referenced by the object.

The proposed change is based on VIF-Handler And Vif Drivers Design [#]_. A new
VIF driver 'npwg_multiple_interfaces' will be created to parse the annotation
of Pods and Network CRDs. The new VIF driver will be invoked by the multi-vif
driver as another sub-drivers. It should return a list of VIF objects. The
'npwg_multiple_interfaces' should invoke other VIF driver to create the vif
objects if it is necessary.

The VIFHandler then updates the Pod annotation of 'openstack.org/kuryr-vif'
with the VIF objects. So that the Kuryr CNI can read these VIFs, and attaches
each of them to Pods namespace. If any of the additional interfaces failed to
be attached to the Pod, or any error happens during attachment, the CNI shall
return with error.

Option in config file might look like this:

.. code-block:: ini

    [kubernetes]

    enabled_vif_drivers = npwg_multiple_interfaces

To define additional network in Pods, NPWG spec defines format of annotation.
Here's how a Pod Spec with additional networks requests might look like:

.. code-block:: yaml

    kind: Pod
    metadata:
      name: my-pod
      namespace: my-namespace
      annotations:
        k8s.v1.cni.cncf.io/networks: net-a,net-b,other-ns/net-c

Or in JSON format like:

.. code-block:: yaml

    kind: Pod
      metadata:
        name: my-pod
        namespace: my-namespace
        annotations:
          k8s.v1.cni.cncf.io/networks: |
            [
              {"name":"net-a"},
              {"name":"net-b"},
              {
                "name":"net-c",
                "namespace":"other-ns"
              }
            ]

Then the VIF driver can parse the network information defined in 'Network'
objects. In NPWG spec, the 'NetworkAttachmentDefinition' object definition is
very flexible. Implementations that are not CNI delegating plugins can add
annotations to the Network object and use those to store non-CNI configuration.
And it is up to the implementation to define the content it requires.

Here is how 'CustomResourceDefinition' CRD specified in the NPWG spec.

.. code-block:: yaml

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

For Kuryr-kubernetes, users should define the 'Network' object with a Neutron
subnet created previously like:

.. code-block:: yaml

    apiVersion: "kubernetes.cni.cncf.io/v1"
    kind: Network
    metadata:
      name: a-bridge-network
      annotations:
        openstack.org/kuryr-config: '{
          "subnetId": "id_of_neutron_subnet_created_previously"
        }'

With information read from Pod annotation k8s.v1.cni.cncf.io/networks
and 'Network' objects, the Neutron ports could either be created or retrieved.
Then the Pod annotation openstack.org/kuryr-vif will be updated accordingly.

Here's how openstack.org/kuryr-vif annotation with additional networks might
look like:

.. code-block:: yaml

    kind: Pod
    metadata:
      name: my-pod
      namespace: my-namespace
      annotations:
        openstack.org/kuryr-vif: {
          # default interface remains intact
          "eth0": {
            ... Neutron vif object from default subnet ...
          }
          # additional interfaces appended by driver 'npwg_multiple_interfaces'
          "eth1": {
            ... Neutron vif object ...
          }
          "eth2": {
            ... Neutron vif object ...
          }
        }

Alternatives
~~~~~~~~~~~~

Currently, Kuryr-Kubernetes has already designed a way of defining additional
VIF. This spec will not change that part. Users can choose using which
format they want by configuring 'enabled_vif_drivers'.

Other end user impact
~~~~~~~~~~~~~~~~~~~~~
Pods always attach the default Kubernetes network as how Kuryr-Kubernetes works
today, and all networks specified in the Pod annotation are sidecars.

Assignee(s)
~~~~~~~~~~~

Primary assignee:
Peng Liu

Work Items
~~~~~~~~~~

* Implement a new NPWG spec compatible VIF driver.
* Document the procedure of using this new VIF driver.

Possible Further Work
~~~~~~~~~~~~~~~~~~~~~

* To keep on track of the subsequent releases of NPWG spec.
* To allow defining new neutron network/subnet in 'Network' objects, so that
  kuryr can create them in Neutron first, then attach Pod to it.

References
----------

.. [#] https://docs.google.com/document/d/1Ny03h6IDVy_e_vmElOqR7UdTPAG_RNydhVE1Kx54kFQ/edit?usp=sharing
.. [#] https://groups.google.com/forum/?_escaped_fragment_=topic/kubernetes-sig-network/ANAjTyqVosw
.. [#] https://docs.openstack.org/kuryr-kubernetes/latest/devref/vif_handler_drivers_design.html
