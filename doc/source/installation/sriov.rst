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

4. Specify resource names

The resource name *intel.com/sriov*, which used in the above example is the default
resource name. This name was used in SR-IOV network device plugin in
version 1 (release-v1 branch). But since latest version the device plugin can use any
arbitrary name of the resources [3]_. This name should match "^\[a-zA-Z0-9\_\]+$"
regular expression. To be able to work with arbitrary resource names
physnet_resource_mappings and device_plugin_resource_prefix in [sriov] section
of kuryr-controller configuration file should be filled. The default value for
device_plugin_resource_prefix is intel.com, the same as in SR-IOV network device plugin,
in case of SR-IOV network device plugin was started with value of -resource-prefix option
different from intel.com, than value should be set to
device_plugin_resource_prefix, otherwise kuryr-kubernetes will not work with resource.

Assume we have following SR-IOV network device plugin (defined by -config-file option)

.. code-block:: json

    {
        "resourceList":
            [
               {
                  "resourceName": "numa0",
                  "rootDevices": ["0000:02:00.0"],
                  "sriovMode": true,
                  "deviceType": "netdevice"
               }
            ]
    }

We defined numa0 resource name, also assume we started sriovdp with
-resource-prefix samsung.com value. The PCI address of ens4f0 interface
is "0000:02:00.0". If we assigned 8 VF to ens4f0 and launch SR-IOV network
device plugin, we can see following state of kubernetes

.. code-block:: bash

    $ kubectl get node node1 -o json | jq '.status.allocatable'
    {
      "cpu": "4",
      "ephemeral-storage": "269986638772",
      "hugepages-1Gi": "8Gi",
      "hugepages-2Mi": "0Gi",
      "samsung.com/numa0": "8",
      "memory": "7880620Ki",
      "pods": "1k"
    }

We have to add to the sriov section following mapping:

.. code-block:: ini

  [sriov]
  device_plugin_resource_prefix = samsung.com
  physnet_resource_mappings = physnet1:numa0

5. Enable Kubelet Pod Resources feature

To use SR-IOV functionality properly it is necessary to enable Kubelet Pod
Resources feature. Pod Resources is a service provided by Kubelet via gRPC
server that allows to request list of resources allocated for each pod and
container on the node. These resources are devices allocated by k8s device
plugins. Service was implemented mainly for monitoring purposes, but it also
suitable for SR-IOV binding driver allowing it to know which VF was allocated
for particular container.

To enable Pod Resources service it is needed to add
``--feature-gates KubeletPodResources=true`` into ``/etc/sysconfig/kubelet``.
This file could look like::

  KUBELET_EXTRA_ARGS="--feature-gates KubeletPodResources=true"

Note that it is important to set right value for parameter ``kubelet_root_dir``
in ``kuryr.conf``. By default it is ``/var/lib/kubelet``.
In case of using containerized CNI it is necessary to mount
``'kubelet_root_dir'/pod-resources`` directory into CNI container.

To use this feature add ``enable_pod_resource_service`` into kuryr.conf.

.. code-block:: ini

  [sriov]
  enable_pod_resource_service = True

6. Use privileged user

To make neutron ports active kuryr-k8s makes requests to neutron API to update
ports with binding:profile information. Due to this it is necessary to make
actions with privileged user with admin rights.

Reference
---------

.. [1] https://docs.openstack.org/kuryr-kubernetes/latest/specs/rocky/npwg_spec_support.html
.. [2] https://docs.google.com/document/d/1D3dJeUUmta3sMzqw8JtWFoG2rvcJiWitVro9bsfUTEw
.. [3] https://github.com/intel/sriov-network-device-plugin
