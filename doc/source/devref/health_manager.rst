..
      This work is licensed under a Creative Commons Attribution 3.0 Unported
      License.

      http://creativecommons.org/licenses/by/3.0/legalcode

      Convention for heading levels in Neutron devref:
      =======  Heading 0 (reserved for the title in a document)
      -------  Heading 1
      ~~~~~~~  Heading 2
      +++++++  Heading 3
      '''''''  Heading 4
      (Avoid deeper levels because they do not render well.)

======================================
Kuryr Kubernetes Health Manager Design
======================================


Purpose
-------
The purpose of this document is to present the design decision behind
Kuryr Kubernetes Health Managers.

The main purpose of the Health Managers is to perform Health verifications that
assures readiness and liveness to Kuryr Controller and CNI pod, and so improve
the management that Kubernetes does on Kuryr-Kubernetes pods.

Overview
--------

Kuryr Controller might get to a broken state due to problems like:
unable to connect with services it depends on and they being not healthy.

It is important to check health of these services so that Kubernetes and
its users know when Kuryr Controller is ready to perform its networking
tasks. Also, it is necessary to check the health state of Kuryr components in
order to assure Kuryr Controller service is alive. To provide these
functionalities, Controller's Health Manager will verify and serve the health
state of these services and components to the probes.

Besides these problems on the Controller, Kuryr CNI daemon also might get to a
broken state as a result of its components being not healthy and necessary
configurations not present. It is essential that CNI components health and
configurations are properly verified to assure CNI daemon is in a good shape.
On this way, the CNI Health Manager will check and serve the health state to
Kubernetes readiness and liveness probes.

Proposed Solution
-----------------
One of the endpoints provided by the Controller Health Manager will check
whether it is able to watch the Kubernetes API, authenticate with Keystone
and talk to Neutron, since these are services needed by Kuryr Controller.
These checks will assure the Controller readiness. The other endpoint, will
verify the health state of Kuryr components and guarantee Controller liveness.

The CNI Health Manager also provides two endpoints to Kubernetes probes.
The endpoint that provides readiness state to the probe checks connection
to Kubernetes API and presence of NET_ADMIN capabilities. The other endpoint,
which provides liveness, validates whether IPDB is in working order, maximum
CNI ADD failure is reached, health of CNI components and existence of memory
leak.

.. note::
  The CNI Health Manager will be started with the check for memory leak
  disabled. In order to enable, set the following option in kuryr.conf to a
  limit value of memory in MiBs.

    [cni_health_server]
    max_memory_usage = -1

The CNI Health Manager is added as a process to CNI daemon and communicates
to the other two processes i.e. Watcher and Server with a shared boolean
object, which indicates the current health state of each component.

The idea behind these two Managers is to combine all the necessary checks in
servers running inside Kuryr Controller and CNI pods to provide the result of
these checks to the probes.
