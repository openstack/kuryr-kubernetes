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

============================================
Kuryr Kubernetes Services Integration Design
============================================


Purpose
-------
The purpose of this document is to present how Kubernetes Service is supported
by the kuryr integration and to capture the design decisions currently taken
by the kuryr team.

Overview
--------
A Kubernetes Service is an abstraction which defines a logical set of Pods and
a policy by which to access them. Service is a Kubernetes managed API object.
For Kubernetes-native applications, Kubernetes offers an Endpoints API that is
updated whenever the set of Pods in a Service changes. For detailed information
please refer to `Kubernetes service <http://kubernetes.io/docs/user-guide/services/>`_
Kubernetes supports services with kube-proxy component that runs on each node,
`Kube-Proxy <http://kubernetes.io/docs/admin/kube-proxy/>`_.

Proposed Solution
-----------------
Kubernetes service in its essence is a Load Balancer across Pods that fit the
service selection. Kuryr's choice is to support Kubernetes services by using
Neutron LBaaS service. The initial implementation is based on the OpenStack
LBaaSv2 API, so compatible with any LBaaSv2 API provider.
In order to be compatible with Kubernetes networking, Kuryr-Kubernetes
makes sure that services Load Balancers have access to Pods Neutron ports.
This may be affected once Kubernetes Network Policies will be supported.
Oslo versioned objects are used to keep translation details in Kubernetes entities
annotation. This will allow future changes to be backward compatible.

Data Model Translation
~~~~~~~~~~~~~~~~~~~~~~
Kubernetes service is mapped to the LBaaSv2 Load Balancer with associated
Listeners and Pools. Service endpoints are mapped to Load Balancer Pool members.

Kuryr Controller Impact
~~~~~~~~~~~~~~~~~~~~~~~
Two Kubernetes Event Handlers are added to the Controller pipeline.

- LBaaSSpecHandler manages Kubernetes Service creation and modification events.
  Based on the service spec and metadata details, it annotates the service
  endpoints entity with details to be used for translation to LBaaSv2 model,
  such as tenant-id, subnet-id, ip address and security groups. The rationale
  for setting annotation both on Service and Endpoints resources is to avoid
  concurrency issues, by delegating all Service translation operations to
  Endpoints (LoadBalancer) handler. To avoid conflicting annotations, K8s
  Services's resourceVersion is used for Service and Endpoints while handling
  Services events.

- LoadBalancerHandler manages Kubernetes endpoints events. It manages
  LoadBalancer, LoadBalancerListener, LoadBalancerPool and LoadBalancerPool
  members to reflect and keep in sync with the Kubernetes service. It keeps details of
  Neutron resources by annotating the Kubernetes Endpoints object.

Both Handlers use Project, Subnet and SecurityGroup service drivers to get
details for service mapping.
LBaaS Driver is added to manage service translation to the LBaaSv2-like API.
It abstracts all the details of service translation to Load Balancer.
LBaaSv2Driver supports this interface by mapping to neutron LBaaSv2 constructs.
