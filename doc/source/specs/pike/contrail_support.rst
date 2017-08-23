=========================================
Kuryr Kubernetes OpenContrail Integration
=========================================

https://blueprints.launchpad.net/kuryr-kubernetes/+spec/kuryr-k8s-contrail-integration

This spec proposes how to integrate OpenContrail with Kuryr-Kubernetes.
OpenContrail is an open source project that provides network virtualization
functionality to OpenStack. Integrating these will allow Kuryr to be used to
bridge container-VM networking in a Contrail-based OpenStack deployment.

Problem Description
===================

OpenContrail is one of the largest SDN platforms, but it currently does not
work with Kuryr-Kubernetes. The goal of this blueprint is to provide Kuryr with
the correct driver so that a Kubernetes-hosted container can use
Kuryr-Kubernetes to correctly interface with an OpenContrail-based network. In
this configuration, OpenContrail will take place of the Open Virtual Switch,
L2/L3 functionality, etc. that normally comes with using Neutron as the default
implementation.

Use Cases
---------

Kuryr will act as the container networking interface for OpenContrail. This
patch set will allow a bare-metal, Kubernetes-hosted container to interact with
VMs in an OpenStack virtual network. This means we have to have a way to plug,
unplug and bridge the container.

Use Case 1: Enable container based work loads to communicate with OpenStack
hosted VM workloads in Contrail SDN environments

Use Case 2: Allow Kubernetes workloads to leverage advanced OpenContrail based
networking

Use Case 3: Enable Kuberentes to create virtual networks via Contrail

Proposed Change
===============
This change will add a driver to Kuryr-Kubernetes that has all of the
functionality of the CNI specifically for OpenContrail. The driver will feature
the plug() and unplug() commands that grant the container network access.

Community Impact
----------------

This spec invites the community to collaborate on a unified solution to support
contrail integration within Kuryr-Kubernetes.

Implementation
==============

Assignee(s)
-----------

Darla Ahlert
Steve Kipp

Work Items
----------

1. Implement an os-vif bare bones plugin similar to [1] only worrying about
plug and unplug. We will implement this within Kuryr-Kubernetes for now and
eventually merge this to openstack/os-vif.
2. Look into serialization for OpenContrail and use [2] as a reference,
if needed.
3. Look into binding for OpenContrail similar to OVS binding [3]
4. Implement unit tests for added code
5. Add gate to install OpenContrail components

Added Paths for New Code:
    kuryr-kubernetes/cni/os-vif/opencontrail.py

References
==========

[1] https://github.com/openstack/os-vif/blob/master/vif_plug_ovs/ovs.py
[2] https://github.com/openstack/kuryr-kubernetes/blob/794ec706c5fbe0da6e49bf20ba2439d8eb39ae7e/kuryr_kubernetes/os_vif_util.py#L258-L281
[3] https://github.com/openstack/kuryr-kubernetes/blob/794ec706c5fbe0da6e49bf20ba2439d8eb39ae7e/kuryr_kubernetes/cni/binding/bridge.py
