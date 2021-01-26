=================================
Kuryr-Kubernetes nested VLAN mode
=================================

Kuryr-Kubernetes can work in two basic modes - nested and standalone. The main
use case of the project, which is to support Kubernetes running on OpenStack
VMs is implemented with nested mode. The standalone mode is mostly used for
testing.

This document describes nested VLAN mode.


Requirements
============

Nested VLAN mode requires Neutron to have `trunk` extension enabled, which adds
trunk port functionality to Neutron API.


Principle
=========

This mode aims at use case of kuryr-kubernetes providing networking for a
Kubernetes cluster running in VMs on OpenStack.

.. note::

   A natural consideration here is running kuryr-kubernetes in containers on
   that K8s cluster. For more see :ref:`containerized` section.

The principle of nested VLAN is that Kuryr-Kubernetes will require that main
interface of the K8s worker VMs is a trunk port. Then each of the pods will
get a subport of that attached into its network namespace.


How to configure
================

You need to set several options in the kuryr.conf:

.. code-block:: ini

   [binding]
   default_driver = kuryr.lib.binding.drivers.vlan
   # Name of the trunk port interface on VMs. If not provided Kuryr will try
   # to autodetect it.
   link_iface = ens3

   [kubernetes]
   pod_vif_driver = nested-vlan
   vif_pool_driver = nested  # If using port pools.

   [pod_vif_nested]
   # ID of the subnet in which worker node VMs are running (if multiple join
   # with a comma).
   worker_nodes_subnets = <id>

Also if you want to run several Kubernetes cluster in one OpenStack tenant you
need to make sure Kuryr-Kubernetes instances are able to distinguish their own
resources from resources created by other instances. In order to do that you
need to configure Kuryr-Kubernetes to tag resources with unique ID:

.. code-block:: ini

   [neutron_defaults]
   resource_tags = <unique-id-of-the-K8s-cluster>
