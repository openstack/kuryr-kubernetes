.. _sriov:

How to configure SR-IOV ports
=============================

Current approach of SR-IOV relies on sriov-device-plugin [2]_. While
creating pods with SR-IOV, sriov-device-plugin should be turned on
on all nodes. To use a SR-IOV port on a baremetal installation the 3
following steps should be done:

1. Create OpenStack network and subnet for SR-IOV.
Following steps should be done with admin rights.

.. code-block:: bash

  neutron net-create vlan-sriov-net --shared --provider:physical_network physnet10_4 --provider:network_type vlan --provider:segmentation_id 3501
  neutron subnet-create vlan-sriov-net 203.0.114.0/24 --name vlan-sriov-subnet --gateway 203.0.114.1

Subnet id <UUID of vlan-sriov-net> will be used later in NetworkAttachmentDefinition.

2. Add sriov section into kuryr.conf.

.. code-block:: ini

  [sriov]
  physical_device_mappings = physnet1:ens4f0
  default_physnet_subnets = physnet1:<UUID of vlan-sriov-net>

This mapping is required for ability to find appropriate PF/VF functions at binding phase.
physnet1 is just an identifier for subnet <UUID of vlan-sriov-net>.
Such kind of transition is necessary to support many-to-many relation.

3. Prepare NetworkAttachmentDefinition object.
Apply NetworkAttachmentDefinition with "sriov" driverType inside,
as described in [1]_.

.. code-block:: yaml

    apiVersion: "k8s.cni.cncf.io/v1"
    kind: NetworkAttachmentDefinition
    metadata:
        name: "sriov-net1"
        annotations:
            openstack.org/kuryr-config: '{
            "subnetId": "UUID of vlan-sriov-net",
            "driverType": "sriov"
            }'


Then add k8s.v1.cni.cncf.io/networks and request/limits for SR-IOV
into the pod's yaml.

.. code-block:: yaml

    kind: Pod
    metadata:
      name: my-pod
      namespace: my-namespace
      annotations:
        k8s.v1.cni.cncf.io/networks: sriov-net1,sriov-net2
    spec:
      containers:
      - name: containerName
        image: containerImage
        imagePullPolicy: IfNotPresent
        command: ["tail", "-f", "/dev/null"]
        resources:
          requests:
            intel.com/sriov: '2'
          limits:
            intel.com/sriov: '2'


In the above example two SR-IOV devices will be attached to pod. First one is described
in sriov-net1 NetworkAttachmentDefinition, second one in sriov-net2. They may have
different subnetId.

Reference
---------

.. [1] https://docs.openstack.org/kuryr-kubernetes/latest/specs/rocky/npwg_spec_support.html
.. [2] https://docs.google.com/document/d/1D3dJeUUmta3sMzqw8JtWFoG2rvcJiWitVro9bsfUTEw
