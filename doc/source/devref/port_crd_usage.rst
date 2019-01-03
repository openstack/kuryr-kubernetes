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

===============================
Kuryr Kubernetes Port CRD Usage
===============================

Purpose
-------
The purpose of this document is to present Kuryr Kubernetes Port and PortPool
CRD [1]_ usage, capturing the design decisions currently taken by the Kuryr
team.

The main purpose of the Port CRD is to keep Neutron resources tracking as part
of K8s data model. The main idea behind is to try to minimize the amount of
calls to Neutron by ensuring port and port pools consistent usage. Port and
PortPool CRD will allow faster synchronization between Kuryr Controller and
Kuryr CNI Daemon. Maintaining Neutron resources via K8s CRD objects will allow
proper handling of Kuryr Controller restart flow.
Having the details in K8s data model should also serve the case where Kuryr is
used as generic SDN K8s integration framework. This means that Port CRD can be
not neutron specific.

Overview
--------
Interactions between Kuryr and Neutron may take more time than desired from
the container management perspective.

To optimize this interaction and speed up both container creation and deletion,
the Kuryr-Kubernetes Ports Pools were added: Neutron ports are created before
container creation, and Neutron ports are deleted after container deletion.

But there is still a need to keep the Ports and Port pools details and have
them available in case of Kuryr Controller restart. Since Kuryr is stateless
service, the details should be kept either as part of Neutron or Kubernetes
data. Due to the perfromance costs, K8s option is more performant.

Proposed Solution
-----------------
The proposal is to start relying on K8s CRD objects more and more.
The first action is to create a KuryrPort CRD where the needed information
about the Neutron Ports will be stored (or any other SDN).

Currently, the pods are annotated with the vif information of the port
assigned to it::

  "kind": "Pod",
  "metadata": {
      "annotations": {
          "openstack.org/kuryr-vif": "{\"eth0\": {\"versioned_object.data\": {\"active\": true, \"address\": \"fa:16:3e:bf:84:ff\", \"has_traffic_filtering\
          ": false, \"id\": \"18f968a5-c420-4318-92d7-941eb5f9e60e\", \"network\": {\"versioned_object.data\": {\"id\": \"144164d9-8c21-4274-acec-43245de0aed0\", \"labe
          l\": \"ns/luis-net\", \"mtu\": 1350, \"multi_host\": false, \"should_provide_bridge\": false, \"should_provide_vlan\": false, \"subnets\": {\"versioned_object
          .data\": {\"objects\": [{\"versioned_object.data\": {\"cidr\": \"10.11.9.0/24\", \"dns\": [], \"gateway\": \"10.11.9.1\", \"ips\": {\"versioned_object.data\":
          {\"objects\": [{\"versioned_object.data\": {\"address\": \"10.11.9.5\"}, \"versioned_object.name\": \"FixedIP\", \"versioned_object.namespace\": \"os_vif\",
          \"versioned_object.version\": \"1.0\"}]}, \"versioned_object.name\": \"FixedIPList\", \"versioned_object.namespace\": \"os_vif\", \"versioned_object.version\"
          : \"1.0\"}, \"routes\": {\"versioned_object.data\": {\"objects\": []}, \"versioned_object.name\": \"RouteList\", \"versioned_object.namespace\": \"os_vif\", \
          "versioned_object.version\": \"1.0\"}}, \"versioned_object.name\": \"Subnet\", \"versioned_object.namespace\": \"os_vif\", \"versioned_object.version\": \"1.0
          \"}]}, \"versioned_object.name\": \"SubnetList\", \"versioned_object.namespace\": \"os_vif\", \"versioned_object.version\": \"1.0\"}}, \"versioned_object.name
          \": \"Network\", \"versioned_object.namespace\": \"os_vif\", \"versioned_object.version\": \"1.1\"}, \"plugin\": \"noop\", \"preserve_on_delete\": false, \"vi
          f_name\": \"tap18f968a5-c4\", \"vlan_id\": 1346}, \"versioned_object.name\": \"VIFVlanNested\", \"versioned_object.namespace\": \"os_vif\", \"versioned_object
          .version\": \"1.0\"}}"
      },


The proposal is to store the information of the VIF in the new defined
KuryrPort CRD as a new KuryrPort object, including similar information to the
one we currently have on os_vif objects. Then we annotate the KuryrPort
object selfLink at the pod by using oslo.versionedobject to easy identify
the changes into the annotation format. Note the selfLink should contain the
Neutron Port UUID if that is used as the name for the KuryrPort CRD object.
In case of other SDN a unique value that represents the port should be used
as the name for the KuryrPort CRD object::

  $ kubectl get POD_NAME -o json
  "kind": "Pod",
  "metadata": {
      "annotations": {
          "openstack.org/kuryr-vif": "{"eth0": {\"versioned_object.data\": {\"selfLink\": \"/apis/openstack.org/v1/kuryrports/18f968a5-c420-4318-92d7-941eb5f9e60e\"}},
          \"versioned_object.name\": \"KuryrPortCRD\", \"versioned_object.version\": \"1.0\"}"
      },
  ...

  $ openstack port show 18f968a5-c420-4318-92d7-941eb5f9e60e
  +-----------------------+---------------------------------------------------------------------------+
  | Field                 | Value                                                                     |
  +-----------------------+---------------------------------------------------------------------------+
  | admin_state_up        | UP                                                                        |
  | allowed_address_pairs |                                                                           |
  | binding_host_id       | None                                                                      |
  | binding_profile       | None                                                                      |
  | binding_vif_details   | None                                                                      |
  | binding_vif_type      | None                                                                      |
  | binding_vnic_type     | normal                                                                    |
  | created_at            | 2018-06-18T15:58:23Z                                                      |
  | data_plane_status     | None                                                                      |
  | description           |                                                                           |
  | device_id             |                                                                           |
  | device_owner          | trunk:subport                                                             |
  | dns_assignment        | None                                                                      |
  | dns_domain            | None                                                                      |
  | dns_name              | None                                                                      |
  | extra_dhcp_opts       |                                                                           |
  | fixed_ips             | ip_address='10.11.9.5', subnet_id='fa660385-65f1-4677-8dc7-3f4f9cd15d7f'  |
  | id                    | 18f968a5-c420-4318-92d7-941eb5f9e60e                                      |
  | ip_address            | None                                                                      |
  | mac_address           | fa:16:3e:bf:84:ff                                                         |
  | name                  |                                                                           |
  | network_id            | 144164d9-8c21-4274-acec-43245de0aed0                                      |
  | option_name           | None                                                                      |
  | option_value          | None                                                                      |
  | port_security_enabled | True                                                                      |
  | project_id            | d85bdba083204fe2845349a86cb87d82                                          |
  | qos_policy_id         | None                                                                      |
  | revision_number       | 4                                                                         |
  | security_group_ids    | 32704585-8cbe-43f3-a4d5-56ffe2d3ab24                                      |
  | status                | ACTIVE                                                                    |
  | subnet_id             | None                                                                      |
  | tags                  |                                                                           |
  | trunk_details         | None                                                                      |
  | updated_at            | 2018-06-18T15:58:30Z                                                      |
  +-----------------------+---------------------------------------------------------------------------+

  $ kubectl get kuryrports 18f968a5-c420-4318-92d7-941eb5f9e60e -o json
  {
    "apiVersion": "openstack.org/v1",
    "kind": "KuryrPort",
    "metadata": {
        "resourceVersion": "164682",
        "selfLink": "/apis/openstack.org/v1/kuryrports/18f968a5-c420-4318-92d7-941eb5f9e60e",
        "uid": "d2834c13-6e6e-11e8-8acd-fa163ed12aae"
        "name": "18f968a5-c420-4318-92d7-941eb5f9e60e"
        "portStatus": "created"
    },
    "spec": {
        "active": true",
        "address": "fa:16:3e:bf:84:ff",
        "id": "18f968a5-c420-4318-92d7-941eb5f9e60e",
        "network": {
          "id": "144164d9-8c21-4274-acec-43245de0aed0",
          "mtu": 1350,
          ...
        }
        ...
    }
  }


This allows a more standard way of annotating the pods, ensuring all needed
information is there regardless of the SDN backend.

In addition, in case of failures it is easier to find orphaned resources that
were created but not in use anymore. As an example we could check the
KuryrPorts objects that were annotated with `deleting` label at the
`portStatus` field at metatdata, and remove the associated Neutron resources
(e.g. ports) in case the controller crashed while deleting the Neutron
(or any other SDN) associated resources.

As for the Ports Pools, right now they reside on memory on the
Kuryr-controller and need to be recovered every time the controller gets
restarted. To perform this recovery we are relying on Neutron Port
device-owner information which may not be completely waterproof in all
situations (e.g., if there is another entity using the same device
owner name). Consequently, by storing the information into K8s CRD objests we
have the benefit of:

  * Calling K8s API instead of Neutron API
  * Being sure the recovered ports into the pools were created by
    kuryr-controller

In addition to these advantages, moving to CRDs will easier the transition for
kuryr-cni handling the ports pools as kuryr-cni has access to the K8S API but
not to the Neutron API. This leads also to the idea of also having
KuryrPortPool CRDs that will keep track of what ports belong to what pool.
This would remove the need for recovering them upon kuryr-controller reboot
completely. An example of the PortPool CRD spec is the next::

  TBD


Note this is similar to the approach already followed by the network per
namespace subnet driver and it could be similarly applied to other SDN
resources, such as LoadBalancers.

References
==========
.. [1] https://kubernetes.io/docs/concepts/api-extension/custom-resources/#custom-resources

