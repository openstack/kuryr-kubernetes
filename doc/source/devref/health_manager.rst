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

========================================
Kuryr Kubernetes Health Manager Design
========================================


Purpose
-------
The purpose of this document is to present the design decision behind
Kuryr Kubernetes Health Manager.

The main purpose of the Health Manager is to perform Health verifications
that assures Kuryr Controller readiness and liveness, and so improve the
management that Kubernetes does on Kuryr Controller pod.

Overview
--------

Kuryr Controller might get to a broken state due to problems like:
unable to connect with services it depends on and they being not healthy.

It is important to check health of these services so that Kubernetes and
its users know when Kuryr Controller it is ready to perform its networking
tasks. Also, it is necessary to check the health state of Kuryr components in
order to assure Kuryr Controller service is alive. To provide these
functionalities, Health Manager will verify and serve the health state of
these services and components to the probe.

Proposed Solution
-----------------
One of the endpoints provided by The Health Manager will check whether it is
able to watch the Kubernetes API, authenticate with Keystone and talk to
Neutron, since these are services needed by Kuryr Controller. These checks
will assure the Controller readiness. The other endpoint, will verify
the health state of Kuryr components and guarantee Controller liveness.

The idea behind the Manager is to combine all the necessary checks in a
server running inside Kuryr Controller pod and provide the checks result
to the probe.
