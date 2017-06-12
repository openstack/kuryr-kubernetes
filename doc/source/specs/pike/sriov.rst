..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

      Convention for heading levels in Neutron devref:
      =======  Heading 0 (reserved for the title in a document)
      -------  Heading 1
      ~~~~~~~  Heading 2
      +++++++  Heading 3
      '''''''  Heading 4
      (Avoid deeper levels because they do not render well.)



Kuryr Kubernetes SR-IOV Integration
===================================

https://blueprints.launchpad.net/kuryr-kubernetes/+spec/kuryr-kubernetes-sriov-support

This spec proposes an approach to allow kuryr-kubernetes manage pods that
require SR-IOV interfaces.

Problem Description
-------------------

SR-IOV (Single-root input/output virtualization) is a technique that allows a
single physical PCIe device to be shared across several clients (VMs or
otherwise). Each such network card would have a single PF (physical function)
and multiple VFs (Virtual Functions), essentially appearing as multiple PCIe
devices. These VFs can be then passed-through to VMs bypassing the hypervisor
and virtual switch. This allows performance comparable to non-virtualized
environments. SR-IOV support is present in nova and neutron, see docs [#]_.

It is possible to implement a similar approach within Kubernetes. Since
Kubernetes uses separate network namespaces for Pods, it is possible to
implement pass-through, simply by assigning a VF device to the desired Pod's
namespace.

There are several challenges that this task poses:

* SR-IOV interfaces are limited and not every Pod would require them. This means
  that a Pod should be able to request 0(zero) or more VFs. Since not all Pods
  will require VFs, these interfaces should be optional.
* For SR-IOV support to be practical the Pods should be able to request multiple
  VFs, possibly from multiple PFs. It's important to note
  that Kubernetes only stores information about a single IP
  address per Pod, however it does not restrict configuring additional network
  interfaces and/or IP addresses for it.
* Different PFs may map to different neutron physical networks(physnets).
  Pods need to be able to request VFs specific physnet and physnet information
  (vlan id, specifically) should be passed to the CNI for configuration.
* Kubernetes does not have any knowledge about SR-IOV interfaces on the Node it
  runs. This can be mitigated by utilising Opaque Integer Resources [#2d]_
  feature from 1.5.x and later series.
* This feature would be limited to bare metal installations of Kubernetes,
  since it's currently impossible to manage VFs of a PF inside a VM. (There is
  work to allow this in newer kernels, but latest stable kernels do not support
  it yet)


Proposed Change
---------------
Proposed solution consists of two major parts: add SR-IOV capabilities to VIF
handler of kuryr-kubernetes controller and enhance CNI to allow it
associate VFs to Pods.


Pod scheduling and resource management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since Kubernetes is the one who actually schedules the Pods on a Node we need a
way to tell it that a particular node is capable of handling a SR-IOV-enabled
Pods. There are several techniques in Kubernetes, that allow limiting where a
pod should be scheduled (i.e. Labels and NodeSelectors, Taints and Tolerations),
but only Opaque Integer Resources [#2d]_ (OIR) allows exact bookkeeping of VFs.
This spec proposes to use a predefined OIR pattern to track VFs on a node:::

    pod.alpha.kubernetes.io/opaque-int-resource-sriov-vf-<PHYSNET_NAME>

For example to request VFs for ``physnet2`` it would be:::

    pod.alpha.kubernetes.io/opaque-int-resource-sriov-vf-physnet2

It will be deployer's duty to set these resources, during node setup.
``kubectl`` does not support setting ORI as of yet, so it has to be done as a
PATCH request to Kubernetes API. For example to add 7 VFs from ``physnet2`` to
``k8s-node-1`` one would issue the following request::

    curl --header "Content-Type: application/json-patch+json" \
    --request PATCH \
    --data '[{"op": "add", "path":
    "/status/capacity/pod.alpha.kubernetes.io~1opaque-int-resource-sriov-vf-physnet2",
    "value": "7"}]' \
    http://k8s-master:8080/api/v1/nodes/k8s-node-1/status

For more information please refer to OIR docs. [#2d]_
This process may be automated, using Node Feature Discovery [#]_
or a similar service, however these details are out of the scope of this spec.

Here's how A Pod Spec might look like this:

.. code-block:: yaml

    spec:
      containers:
      - name: vf-container
        image: vf-image
        resources:
          requests:
            pod.alpha.kubernetes.io/opaque-int-resource-sriov-vf-physnet2: 1
      - name: vf-other-container
        image: vf-other-image
        resources:
          requests:
            pod.alpha.kubernetes.io/opaque-int-resource-sriov-vf-physnet2: 1
            pod.alpha.kubernetes.io/opaque-int-resource-sriov-vf-physnet3: 1


These requests are per-container, and the total amount of VFs should be
totalled for the Pod, the same way Kubernetes does it.
The example above would require 2 VFs from ``physnet2``
and 1 from ``physnet3``.

An important note should be made about kubernetes Init Containers [#]_. If we
decide that it is important to support requests from Init Containers, they
would have to be treated differently. Init Containers are designed to run
sequentially, so we would need to scan them and get maximum request value
across all of them.

Requesting SR-IOV ports
~~~~~~~~~~~~~~~~~~~~~~~

To implement SR-IOV capabilities current VIF handler will be modified to handle
multiple VIFs.
As a prerequisite of this the following changes have to be implemented:

Multi-VIF capabilities of generic handler
+++++++++++++++++++++++++++++++++++++++++

Instead of storing a single VIF in the annotation VIFHandler would store
a dict, that maps desired interface name to a VIF object. As an alternative we
can store VIFs in a list, but dict would give finer control over interface
naming. Both handler and the CNI would have to be modified to understand
this new format of the annotation. The CNI may also be kept
backward-compatible, i.e. understand the old single-VIF format.

Even though this functionality is not a part of SR-IOV handling it acts as a
prerequisite and would be implemented as part of this spec.

SR-IOV capabilities of generic handler
++++++++++++++++++++++++++++++++++++++

The handler would read OIR requests of a
scheduled Pod and would see if the Pod has requested any SR-IOV VFs. (NOTE: at
this point the Pod should already be scheduled to a node, meaning there are
enough available VFs on that node). The handler would ask SR-IOV driver for
sufficient number of ``direct`` ports from neutron and pass them on
to the CNI via annotations. Network information should also include network's
VLAN info, to setup VF VLAN.

SR-IOV functionality requires additional knowledge of neutron subnets. The
controller needs to know a subnet where it would allocate direct ports for
certain physnet. This can be solved by adding a config setting that will map
physnets to a default neutron subnet
It might look like this:

.. code-block:: ini

    default_physnet_subnets =  "physnet2:e603a1cc-57e5-40fe-9af1-9fbb30905b10,physnet3:0919e15a-b619-440c-a07e-bb5a28c11a75"

Alternatively we can request this information from neutron. However since there
can be multiple networks within a single physnet and multiple subnets within a
single network there is a lot of space for ambiguity.
Finally we can combine the approaches: request info from neutron only if it's
not set in the config.

Kuryr-cni
~~~~~~~~~

On the CNI side we will implement a CNI binding driver for SR-IOV ports.
Since this work will be based on top of multi-vif support for both CNI and
controller, no additional format changes would be implemented.
The driver would configure the VF and pass it to the Pod's namespace.
It would scan ``/sys/class/net/<PF>/device`` directory for available
virtual functions and pass the acquired device to Pods namespace.

The driver would need to know which
devices map to which physnets. Therefore we would introduce a config
setting ``physical_device_mappings``. It will be identical to
neutron-sriov-nic-agent's setting. It might look like:

.. code-block:: ini

    physical_device_mappings = "physnet2:enp1s0f0,physnet3:enp1s0f1"

As an alternative to storing this setting in ``kuryr.conf`` we may store it in
``/etc/cni/net.d/kuryr.conf`` file or in a kubernetes node annotation.


Caveats
~~~~~~~

* Current implementation does not concern itself with setting active status of
  the Port on the neutron side. It is not required for the feature to function
  properly, but may be undesired from operators standpoint. Doing so may
  require some additional integration with neutron-sriov-nic-agent and
  verification. There is a concern, that neutron-sriov-nic-agent does not
  detect port status correctly all the times.

Optional 2-Phase Approach
~~~~~~~~~~~~~~~~~~~~~~~~~

Initial implementation followed an alternative path, where SR-IOV functionality
has been implemented as a separate handler/cni. This sparked several design
discussions, where community agreed, that multi-VIF handler is preferred over
multi-handler approach. However if implementing multi-vif handler would prove
to be lengthy and difficult we may go with a 2-phase approach. First phase:
polish and merge initial implementation. Second phase: Implement multi-vif
approach and convert sriov-handler to use it.

Alternatives
~~~~~~~~~~~~

* It is possible to implement SR-IOV functionality as a separate handler.
  In this scenario both handlers would listen to Pod events and would handle
  them separately. They would have to use different annotation keys inside the
  Pod object. The CNI would have to be able to handle both annotation keys.
* Since this feature is only practical for bare metal we can implement it
  entirely on the CNI side. (i.e. CNI would request ports from neutron).
  However this would introduce an alternative control flow.
* It is also possible to implement a separate CNI, that would use static
  configuration, compatible with neutrons, much like [#]_. This would eliminate
  the need to talk to neutron at all, but would put the burden of configuring
  multiple nodes network information on the deployer. This may be however
  desirable for some installations and may be considered as an option. At the
  same time in this scenario there would be little to no code shared
  between this CNI and regular kuryr-kubernetes. In this case it feels like the
  code will be more suited to a separate project, than kuryr-kubernetes.
* As an alternative we may implement a separate kuryr-sriov-cni, that would
  only handle SR-IOV requests. This will allow a more granular approach and
  would decouple SR-IOV functionality from the main code.
  Implementing a kuryr-sriov-cni would mean,  however, that operators would
  need to pick one of the implementations (kuryr-cni vs kuryr-sriov-cni) or
  use something like multus-cni [#]_ or CNI-Genie [#]_ to allow them
  work together.


Assignee(s)
~~~~~~~~~~~

Primary assignee:
Zaitsev Kirill


Work Items
~~~~~~~~~~

* Implement Multi-VIF handler/CNI
* Implement SR-IOV capabilities
* Implement CNI SR-IOV handler
* Active state monitoring for kuryr-sriov direct ports
* Document deployment procedure for kuryr-sriov support

Possible Further Work
~~~~~~~~~~~~~~~~~~~~~

* It may be desirable to be able to request specific ports from
  neutron subnet in the Pod Spec. This functionality may be extended to
  normal VIFs, beyond SR-IOV handler.
* It may be desirable to add an option to assign network info to VFs
  statically

References
----------

.. [#] https://docs.openstack.org/ocata/networking-guide/config-sriov.html
.. [#2d] https://kubernetes.io/docs/concepts/configuration/manage-compute-resources-container/#opaque-integer-resources-alpha-feature
.. [#] https://github.com/kubernetes-incubator/node-feature-discovery
.. [#] https://kubernetes.io/docs/concepts/workloads/pods/init-containers/
.. [#] https://github.com/hustcat/sriov-cni
.. [#] https://github.com/Intel-Corp/multus-cni
.. [#] https://github.com/Huawei-PaaS/CNI-Genie
