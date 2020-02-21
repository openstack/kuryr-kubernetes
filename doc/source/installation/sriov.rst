.. _sriov:

=============================
How to configure SR-IOV ports
=============================

Current approach of SR-IOV relies on `sriov-device-plugin`_. While creating
pods with SR-IOV, sriov-device-plugin should be turned on on all nodes. To use
a SR-IOV port on a baremetal or VM installation following steps should be done:

#. Create OpenStack networks and subnets for SR-IOV. Following steps should be
   done with admin rights.

   .. code-block:: console

      $ openstack network create --share --provider-physical-network physnet22 --provider-network-type vlan --provider-segment 3501 vlan-sriov-net-1
      $ openstack network create --share --provider-physical-network physnet23 --provider-network-type vlan --provider-segment 3502 vlan-sriov-net-2
      $ openstack subnet create --network vlan-sriov-net-1 --subnet-range 192.168.2.0/24  vlan-sriov-subnet-1
      $ openstack subnet create --network vlan-sriov-net-2 --subnet-range 192.168.3.0/24  vlan-sriov-subnet-2

   Subnet ids of ``vlan-sriov-subnet-1`` and ``vlan-sriov-subnet-2`` will be
   used later in NetworkAttachmentDefinition.

#. Add sriov section into kuryr.conf.

   .. code-block:: ini

      [sriov]
      default_physnet_subnets = physnet22:<UUID of vlan-sriov-subnet-1>,physnet23:<UUID of vlan-sriov-subnet-2>
      device_plugin_resource_prefix = intel.com
      physnet_resource_mappings = physnet22:physnet22,physnet23:physnet23
      resource_driver_mappings = physnet22:vfio-pci,physnet23:vfio-pci

#. Prepare NetworkAttachmentDefinition objects. Apply
   NetworkAttachmentDefinition with "sriov" driverType inside, as described in
   `NPWG spec`_.

   .. code-block:: yaml

      apiVersion: "k8s.cni.cncf.io/v1"
      kind: NetworkAttachmentDefinition
      metadata:
          name: "sriov-net1"
          annotations:
              openstack.org/kuryr-config: '{
              "subnetId": "UUID of vlan-sriov-subnet-1",
              "driverType": "sriov"
              }'

   .. code-block:: yaml

      apiVersion: "k8s.cni.cncf.io/v1"
      kind: NetworkAttachmentDefinition
      metadata:
          name: "sriov-net2"
          annotations:
              openstack.org/kuryr-config: '{
              "subnetId": "UUID of vlan-sriov-subnet-2",
              "driverType": "sriov"
              }'

   Use the following yaml to create pod with two additional SR-IOV interfaces:

   .. code-block:: yaml

      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: nginx-sriov
        labels:
          app: nginx-sriov
      spec:
        replicas: 1
        selector:
          matchLabels:
            app: nginx-sriov
        template:
          metadata:
            labels:
              app: nginx-sriov
            annotations:
              k8s.v1.cni.cncf.io/networks: sriov-net1,sriov-net2
          spec:
            containers:
            - securityContext:
              privileged: true
              capabilities:
                add:
                - SYS_ADMIN
                - IPC_LOCK
                - SYS_NICE
                - SYS_RAWIO
              name: nginx-sriov
              image: nginx:1.13.8
              resources:
                requests:
                  intel.com/physnet22: '1'
                  intel.com/physnet23: '1'
                  cpu: "2"
                  memory: "512Mi"
                  hugepages-2Mi: 512Mi
                limits:
                  intel.com/physnet22: '1'
                  intel.com/physnet23: '1'
                  cpu: "2"
                  memory: "512Mi"
                  hugepages-2Mi: 512Mi
              volumeMounts:
              - name: dev
                mountPath: /dev
              - name: hugepage
                mountPath: /hugepages
              - name: sys
                mountPath: /sys
            volumes:
            - name: dev
              hostPath:
                path: /dev
                type: Directory
            - name: hugepage
              emptyDir:
                medium: HugePages
            - name: sys
              hostPath:
                path: /sys

   In the above example two SR-IOV devices will be attached to pod. First one
   is described in sriov-net-2 NetworkAttachmentDefinition, second one is in
   sriov-net-3. They may have different subnetId. It is necessary to mount
   ``/dev`` and ``/hugepages`` host's directories into pod to make pod available
   to use vfio devices. ``privileged: true`` is necessary only in case if node
   is a virtual machine. For baremetal node this option is not necessary.
   ``IPC_LOCK`` capability and other ones are necessary for case when node is
   a virtual machine.

#. Specify resource names

   The resource names *intel.com/physnet22* and *intel.com/physnet23*, which
   are used in the above example are the resource names (see `SRIOV network
   device plugin for Kubernetes`_). This name should match "^\[a-zA-Z0-9\_\]+$"
   regular expression. To be able to work with arbitrary resource names
   physnet_resource_mappings and device_plugin_resource_prefix in [sriov]
   section of kuryr-controller configuration file should be filled. The
   default value for device_plugin_resource_prefix is ``intel.com``, the same
   as in SR-IOV network device plugin, in case of SR-IOV network device plugin
   was started with value of -resource-prefix option different from
   ``intel.com``, than value should be set to device_plugin_resource_prefix,
   otherwise kuryr-kubernetes will not work with resource.

   Assume we have following SR-IOV network device plugin (defined by
   -config-file option)

   .. code-block:: json

      {
          "resourceList":
              [
                 {
                    "resourceName": "physnet22",
                    "rootDevices": ["0000:02:00.0"],
                    "sriovMode": true,
                    "deviceType": "vfio"
                 },
                 {
                    "resourceName": "physnet23",
                    "rootDevices": ["0000:02:00.1"],
                    "sriovMode": true,
                    "deviceType": "vfio"
                 }
              ]
      }

   The config file above describes two physical devices mapped on two
   resources. Virtual functions from these devices will be used for pods.
   We defined ``physnet22`` and ``physnet23`` as resource names, also assume
   we started sriovdp with -resource-prefix intel.com value. The PCI address
   of ens6 interface is "0000:02:00.0" and the PCI address of ens8 interface
   is "0000:02:00.1". If we assigned 8 VF to ens6 and 8 VF to ens8 and launch
   SR-IOV network device plugin, we can see following state of kubernetes:

   .. code-block:: console

      $ kubectl get node node1 -o json | jq '.status.allocatable'
      {
        "cpu": "4",
        "ephemeral-storage": "269986638772",
        "hugepages-1Gi": "8Gi",
        "hugepages-2Mi": "0Gi",
        "intel.com/physnet22": "8",
        "intel.com/physnet23": "8",
        "memory": "7880620Ki",
        "pods": "1k"
      }

   If you use a virtual machine as your worker node, then it is necessary to
   use sriov-device-plugin of version 3.1 because it provides selectors which
   are important to separate particular VFs which are passed into VM.

   Config file for sriov-device-plugin may look like:

   .. code-block:: json

      {
          "resourceList": [{
                   "resourceName": "physnet22",
                   "selectors": {
                       "vendors": ["8086"],
                       "devices": ["1520"],
                       "pfNames": ["ens6"]
                   }
              },
              {
                   "resourceName": "physnet23",
                   "selectors": {
                       "vendors": ["8086"],
                       "devices": ["1520"],
                       "pfNames": ["ens8"]
                   }
              }
          ]
      }

   We defined ``physnet22`` resource name that maps to ``ens6`` interface,
   which is the first passed into VM virtual function. The same situation is
   with ``physnet23``, it maps to ``ens8`` interface. It is important to note
   that in case of virtual machine usage we should specify the names of passed
   virtual functions as physical devices. Thus we expect sriov-dp to annotate
   different pci addresses for each resource:

   .. code-block:: console

      $ kubectl get node node1 -o json | jq '.status.allocatable'
      {
        "cpu": "4",
        "ephemeral-storage": "269986638772",
        "hugepages-2Mi": "2Gi",
        "intel.com/physnet22": "1",
        "intel.com/physnet23": "1",
        "memory": "7880620Ki",
      }

#. Enable Kubelet Pod Resources feature

   To use SR-IOV functionality properly it is necessary to enable Kubelet Pod
   Resources feature. Pod Resources is a service provided by Kubelet via gRPC
   server that allows to request list of resources allocated for each pod and
   container on the node. These resources are devices allocated by k8s device
   plugins. Service was implemented mainly for monitoring purposes, but it also
   suitable for SR-IOV binding driver allowing it to know which VF was
   allocated for particular container.

   To enable Pod Resources service it is needed to add ``--feature-gates
   KubeletPodResources=true`` into ``/etc/sysconfig/kubelet``. This file could
   look like:

   .. code-block:: bash

      KUBELET_EXTRA_ARGS="--feature-gates KubeletPodResources=true"

   Note that it is important to set right value for parameter
   ``kubelet_root_dir`` in ``kuryr.conf``. By default it is
   ``/var/lib/kubelet``.  In case of using containerized CNI it is necessary to
   mount ``'kubelet_root_dir'/pod-resources`` directory into CNI container.

   To use this feature add ``enable_pod_resource_service`` into kuryr.conf.

   .. code-block:: ini

      [sriov]
      enable_pod_resource_service = True

#. Use privileged user

   To make neutron ports active kuryr-k8s makes requests to neutron API to
   update ports with binding:profile information. Due to this it is necessary
   to make actions with privileged user with admin rights.

#. Use vfio devices in containers

   To use vfio devices inside containers it is necessary to load vfio-pci
   module. Remember that if our worker node is a virtual machine then it
   should be loaded without iommu support:

   .. code-block:: bash

      rmmod vfio_pci
      rmmod vfio_iommu_type1
      rmmod vfio
      modprobe vfio enable_unsafe_noiommu_mode=1
      modprobe vfio-pci

.. _NPWG spec: https://docs.openstack.org/kuryr-kubernetes/latest/specs/rocky/npwg_spec_support.html
.. _sriov-device-plugin: https://docs.google.com/document/d/1D3dJeUUmta3sMzqw8JtWFoG2rvcJiWitVro9bsfUTEw
.. _SRIOV network device plugin for Kubernetes: https://github.com/intel/sriov-network-device-plugin
