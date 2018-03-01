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

====================================
Kuryr Kubernetes Port Manager Design
====================================


Purpose
-------
The purpose of this document is to present Kuryr Kubernetes Port Manager,
capturing the design decision currently taken by the kuryr team.

The main purpose of the Port Manager is to perform Neutron resources handling,
i.e., ports creation and deletion. The main idea behind is to try to minimize
the amount of calls to Neutron by ensuring port reusal as well as performing
bulk actions, e.g., creating/deleting several ports within the same Neutron
call.

Overview
--------
Interactions between Kuryr and Neutron may take more time than desired from
the container management perspective.

Some of these interactions between Kuryr and Neutron can be optimized. For
instance, by maintaining pre-created pools of Neutron port resources instead
of asking for their creation during pod lifecycle pipeline.

As an example, every time a container is created or deleted, there is a call
from Kuryr to Neutron to create/remove the port used by the container. To
optimize this interaction and speed up both container creation and deletion,
the Kuryr-Kubernetes Port Manager will take care of both: Neutron ports
creation beforehand, and Neutron ports deletion afterwards. This will
consequently remove the waiting time for:

- Creating ports and waiting for them to become active when booting containers
- Deleting ports when removing containers

Proposed Solution
-----------------
The Port Manager will be in charge of handling Neutron ports. The main
difference with the current implementation resides on when and how these
ports are managed. The idea behind is to minimize the amount of calls to the
Neutron server by reusing already created ports as well as by creating/deleting
them in bulk requests.

This design focuses on Neutron ports management, but similar optimization can
be done for other Neutron resources, and consequently new resource managers
can be added.

Ports Manager
~~~~~~~~~~~~~
The Port Manager will handle different pool of Neutron ports:

- Available pools: There will be a pool of ports for each tenant, host (or
  trunk port for the nested case) and security group, ready to be used by the
  pods. Note at the beginning there are no pools. Once a pod is created at
  a given host/VM by a tenant, with a specific security group, a corresponding
  pool gets created and populated with the desired minimum amount of ports.
  Note the Neutron port quota needs to be considered when configuring the
  parameters of the pool, i.e., the minimum and/or maximum size of the pools as
  well as the size of the bulk creation requests.
- Recyclable pool: Instead of deleting the port during pods removal it will
  just be included into this pool. The ports in this pool will be later
  recycled by the Port Manager and put back into the corresponding
  available pool.

The Port Manager will handle the available pools ensuring that at least X ports
are ready to be used at each existing pool, i.e., for each security group
and tenant which already has a pod on it. The port creation at each
available_pool will be handled in batches, i.e., instead of creating one port
at a time, a configurable amount of them will be created altogether.
The Port Manager will check for each pod creation that the remaining number of
ports in the specific pool is above X. Otherwise it creates Y extra ports for
that pool (with the specific tenant and security group). Note both X and Y are
configurable.

Thanks to having the available ports pool, during the container creation
process, instead of calling Neutron port_create and then waiting for the port
to become active, a port will be taken from the right available_pool (hence,
no need to call Neutron) and then the port info will be updated with the
proper container name (i.e., call to Neutron port_update). Thus, thanks to the
Port Manager, at least two calls to Neutron are skipped (port create and
pooling waiting for port to become ACTIVE), while doing an extra one (update)
which is faster than the other ones. Similarly, for the port deletion we save
the call to remove the port as it is just included in the recyclable pool.

The port cleanup actions return ports to the corresponding available_pool after
re-applying security groups and changing the device name to 'available-port'.
A maximum limit for the pool can be specified to ensure that once the
corresponding available_pool reach a certain size, the ports gets deleted
instead of recycled. Note this upper limit can be disabled by setting it to 0.
In addition, a Time-To-Live (TTL) could be set to the ports at the pool, so
that if they are not used during a certain period of time, they are removed --
if and only if the available_pool size is still larger than the target minimum.

Recovery of pool ports upon Kuryr-Controller restart
++++++++++++++++++++++++++++++++++++++++++++++++++++
If the Kuryr-Controller is restarted, the pre-created ports will still exist
on the Neutron side but the Kuryr-controller will be unaware of them, thus
pre-creating more upon pod allocation requests. To avoid having these existing
but unused ports a mechanisms is needed to either delete them after
controller's reboot, or obtain their information and re-include them into
their corresponding pool.

For the baremetal (NeutronVIF) case, as the ports are not attached to any
hosts (at least not until CNI support is included) there is not enough
information to decide which pool should be selected for adding the port.
For simplicity, and as a temporal solution until CNI support is developed,
the implemented mechanism will find the previously created ports by looking
at the existing neutron ports and filtering them by device_owner and name,
which should be compute:kuryr and available-port, respectively.
Once these ports are obtained, they are deleted to release unused Neutron
resources and avoid problems related to ports quota limits.

By contrast, it is possible to obtain all the needed information for the
subports previously created for the nested (VLAN+Trunk) case as they are still
attached to their respective trunk ports. Therefore, these ports instead of
being deleted will be re-added to their corresponding pools.
To do this, the Neutron ports are filtered by device_owner (trunk:subport in
this case) and name (available-port), and then we iterate over the subports
attached to each existing trunk port to find where the filtered ports are
attached and then obtain all the needed information to re-add them into the
corresponding pools.

Kuryr Controller Impact
+++++++++++++++++++++++
A new VIF Pool driver is created to manage the ports pools upon pods creation
and deletion events. It will ensure that a pool with at least X ports is
available for each tenant, host or trunk port, and security group, when the
first request to create a pod with these attributes happens. Similarly, it will
ensure that ports are recycled from the recyclable pool after pods deletion and
are put back in the corresponding available_pool to be reused. Thanks to this
Neutron calls are skipped and the ports of the pools are used instead. If the
corresponding pool is empty, a ResourceNotReady exception will be triggered and
the pool will be repopulated.

In addition to the handler modification and the new pool drivers there are
changes related to the VIF drivers. The VIF drivers (neutron-vif and nested)
will be extended to support bulk ports creation of Neutron ports and similarly
for the VIF objects requests.

Future enhancement
''''''''''''''''''
The VIFHandler needs to be aware of the new Pool driver, which will load the
respective VIF driver to be used. In a sense, the Pool Driver will be a proxy
to the VIF Driver, but also managing the pools. When a mechanism to load and
set the VIFHandler drivers is in place, this will be reverted so that the
VIFHandlers becomes unaware of the pool drivers.

Kuryr CNI Impact
++++++++++++++++
For the nested vlan case, the subports at the different pools are already
attached to the VMs trunk ports, therefore they are already in ACTIVE status.
However, for the generic case the ports are not really bond to anything (yet),
therefore their status will be DOWN. In order to keep these ports returned to
the pool in ACTIVE status, we will implement another pool at the CNI side for
the generic case. This solution could be different for different SDN
controllers. The main idea is that they should keep the port in ACTIVE
state without allowing network traffic through them. For instance, for the
Neutron reference implementation, this pool will maintain a pool of veth
devices at each host, by connecting them to a recyclable namespace so that the
OVS agent sees them as 'still connected' and maintains their ACTIVE status.
This modification must ensure the OVS (br-int) ports where these veth devices
are connected are not deleted after container deletion by the CNI.

Future enhancement
''''''''''''''''''
The CNI modifications will be implemented in a second phase.
