====================================================
Vagrant based Kuryr-Kubernetes devstack installation
====================================================

Deploy kuryr-kubernetes on devstack in VM using `Vagrant`_. Vagrant simplifies
life cycle of the local virtual machine and provides automation for repetitive
tasks.

Requirements
------------

For comfortable work, here are minimal host requirements:

#. ``vagrant`` installed
#. 4 CPU cores
#. At least 8GB of RAM
#. Around 20GB of free disk space

Vagrant will create VM with 2 cores, 6GB of RAM and dynamically expanded disk
image.


Getting started
---------------

You'll need vagrant itself, i.e.:

.. code:: console

   $ apt install vagrant virtualbox

As an option, you can install libvirt instead of VirtualBox, although
VirtualBox is as an easiest drop-in.

Next, clone the kuryr-kubernetes repository:

.. code:: console

   $ git clone https://opendev.org/openstack/kuryr-kubernetes

And run provided vagrant file, by executing:

.. code:: console

   $ cd kuryr-kubernetes/contrib/vagrant
   $ vagrant up

This can take some time, depending on your host performance, and may take
20 minutes and up.

After deploying is complete, you can access VM by ssh:

.. code:: console

   $ vagrant ssh

At this point you should have experimental kubernetes (etcdv3, k8s-apiserver,
k8s-controller-manager, k8s-scheduler, kubelet and kuryr-controller), docker,
OpenStack services (neutron, keystone, placement, nova, octavia), kuryr-cni and
kuryr-controller all up, running and pointing to each other. Pods and services
orchestrated by kubernetes will be backed by kuryr+neutron and Octavia. The
architecture of the setup `can be seen here`_.


Vagrant Options available
-------------------------

You can set the following environment variables before running `vagrant up` to
modify the definition of the Virtual Machine spawned:

* ``VAGRANT_KURYR_VM_BOX`` - to change the Vagrant Box used. Should be
  available in `atlas <https://app.vagrantup.com/>`_. For example of a
  rpm-based option:

  .. code:: console

     $ export VAGRANT_KURYR_VM_BOX=centos/8

* ``VAGRANT_KURYR_VM_MEMORY`` - to modify the RAM of the VM. Defaulted to:
  **6144**. If you plan to create multiple Kubernetes services on the setup and
  the Octavia driver used is Amphora, you should increase this setting.
* ``VAGRANT_KURYR_VM_CPU``: to modify number of CPU cores for the VM. Defaulted
  to: **2**.
* ``VAGRANT_KURYR_RUN_DEVSTACK`` - whether ``vagrant up`` should run devstack
  to have an environment ready to use. Set it to 'false' if you want to edit
  ``local.conf`` before stacking devstack in the VM. Defaulted to: **true**.
  See below for additional options for editing local.conf.


Additional devstack configuration
---------------------------------

To add additional configuration to local.conf before the VM is provisioned, you
can create a file called ``user_local.conf`` in the contrib/vagrant directory
of networking-kuryr. This file will be appended to the "local.conf" created
during the Vagrant provisioning.

.. _Vagrant: https://www.vagrantup.com/
.. _can be seen here: https://docs.openstack.org/developer/kuryr-kubernetes/devref/kuryr_kubernetes_design.html
