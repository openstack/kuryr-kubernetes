

Kuryr Kubernetes vhost-user port integration
============================================

Open vSwitch or any other virtual switch can be built with DPDK datapath [3]_,
for this datapath virtual switch provisions vhost-user port. DPDK application
can use it just by accessing UNIX domain socket of vhost-user port. DPDK
applications which use vhost-user port have more network performance compared to
applications which use veth pair with tap interfaces.
DPDK application which uses vhost-user socket it is typical use case for
bare-metal installation in NFV world.
Also there is another use case, where vhost-user ports are passed to VM. In this
case DPDK application inside VM works with vhost-user port through VirtIO
device. This is Nested DPDK Support [1]_ use case.

Problem statement
-----------------

Now kuryr-kubernetes doesn't support vhostuser port creation on bare-metal
installation, but OpenStack can be configured to work with vhost-user ports.
In case of vhost-user port in bare-metal installation there is no device, DPDK
applications use unix domain socket created by Open vSwitch daemon, it's control
plain socket. Kuryr-kubernetes has to move this vhost-user socket file to path
available for pod.

Proposed solution
-----------------

Kuryr-kubernetes should create Neutron port as usual, NeutronPodVIFDriver will
be used. Then kuryr-kubernetes should handle vif_type vhost-user [2]_, it
already handles port with vif_type ovs for non-DPDK datapath with veth pair as
well as ports with ovs_hybrid_plug where linux bridge is used. No new pod vif
driver will be introduced.

From user point of view there is no difference in pod definition. It's the same
as with tap based. To request vhost-user port as a main port no need to do
something special.

When vhost-user port is additional interface it can be defined with Network
Attachment Definition [6]_.

The type of port will be determined by neutron-openvswitch-agent configuration
file by datapath_type option [2]_, whether the veth is plugged to the OVS bridge
or vhostuser. That's why datapath is not featured in pod's definition,
kuryr-kubernetes will rely on pod's vif type.

Open vSwitch supports DPDK ports only in special bridges with type netdev,
therefore integration bridge should have netdev type, otherwise OVS dpdk port
will not work. Kuryr-kubernetes uses os-vif, this library does all necessary
work for vif of VIFVhostuser type to set up bridge and create port.

To be able to use that kind of port in container, socket of that port has to be
placed on the container's file system. It will be done by mountVolumes in pod
yaml file like that:

.. _configuration:
.. code-block:: yaml

     volumeMounts:
       - name: vhostuser
         mountPath: /var/run/vhostuser
        ...
     volumes:
       - name: openvswitch
         hostPath:
           path: /var/run/vhostuser
           type: Directory


mountPath is defined in kuryr.conf on the minion host

.. code-block:: ini

  [vhostuser]
  mount_point = /var/run/vhostuser
  ovs_vhu_path = /var/run/openvswitch

Single mount point will be provided for several pods
(CONF.vhostuser.mount_point). It's the place where vhost-user socket file will
be moved from ovs_vhu_path. ovs_vhu_path it's a path where Open vSwitch stores
vhost-user socket by default in case when Open vSwitch creates socket.
mount_point and ovs_vhu_path should be on the same point of mount,
otherwise EXDEV (Cross-device link) will be raised and
connection by this socket will be refused. Unfortunately Open vSwitch daemon
can't remove moved socket by ovs-vsctl del-port command, in this case socket
file will be removed by VIFVHostUserDriver.

Configuration file will be created there for DPDK application. It will contain
auxiliary information: socket name, mac address, ovs port mode.
It might look like:

.. code-block:: json

  {
    "vhostname": "vhu9c9cc8f5-88",
    "vhostmac": "fa:16:3e:ef:b0:ed",
    "mode": "server"
  }

Name of configuration file will contain container id concatenated by dash with
ifname for this interface. DPDK application will use vhostname to determine
vhost-user socket name.

To get vhost user socket name inside container user has to read configuration
file. Container identifier will be required for it. Following bash
command will help to get it inside container.

.. code-block:: bash

  CONTAINER_ID=`sed -ne '/hostname/p' /proc/1/task/1/mountinfo |\
                awk -F '/' '{print $4}'`

Kuryr-kubernetes can produce multiple ports per one pod, following command can
be used to list all available ports.

.. code-block:: bash

  ls $MOUNT_POINT/$CONTAINER_ID-eth*

$MOUNT_POINT here is volumeMounts with name vhostuser defined in pod
configuration_ yaml file.
Value from vhostname field should be used for launching DPDK application.

.. code-block:: bash

  testpmd -d librte_pmd_virtio.so.17.11 -m 1024 -c 0xC --file-prefix=testpmd_ \
          --vdev=net_virtio_user0,path=/$MOUNT_POINT/$VHU_PORT \
          --no-pci -- --no-lsc-interrupt --auto-start --tx-first \
          --stats-period 1 --disable-hw-vlan;

vhost-user port has two different modes: client and server.
The type of vhost-user port to create is defined in vif_details by
vhostuser_mode field [4]_. vhost-user port's mode affects socket life cycle.
The client mode from kuryr-kubernetes point of view, it is mode when
ovs-vswitchd creates and listens the vhost-user socket, which is created by the
command below:

.. code-block:: console

        ovs-vsctl add-port ovsbr0 vhost-user0 -- set Interface vhost-user0 \
                 type=dpdkvhostuser

In this case vhost_user_mode's value will be 'client'. This mode is not robust
because after restarting ovs-vswitchd will recreate sockets by initial path, all
clients have to reestablish connection and kuryr-kubernetes has to move sockets
again. It leads to more complicated solution, that's why another mode in
Open vSwitch was invented, in this mode ovs-vswitchd acts as a client, it tries
to connect by predefined path to vhost-user server (DPDK application in
container). From kuryr-kubernetes point of view it's server mode,
vhost_user_mode's value is 'server'.

It imposes a restrictions:

- Kuryr-kubernetes can specify socket path in 'server' mode, but can't in
  'client' mode, at socket creation time
- In case of 'client' mode it's better to recreate whole pod at restart of Open
  vSwitch daemon

This feature doesn't depend on HA behavior. But this feature affects
containeraized cni plugin, due to it requeres the same mount point for source
and destination of vhostuser socket file.

vhost-user port is not a limited resource it can be scheduled in any nodes
without restrictions. Limited resource here is memory, in most cases number of
huge pages. To configure it see [5]_.

Initial implementation doesn't cover security issues, DAC and MAC should be
defined by user properly.


Implementation
==============

Work Items
----------

* check for vhostuser_mode in neutron_to_osvif_vif_ovs and create appropriate
  VIF
* introduce new binding driver VIFVHostUserDriver
* add unit tests for new code
* add tempest test for vhostuser ports

Assignee
--------

Alexey Perevalov


References
----------
.. [1] https://blueprints.launchpad.net/kuryr-kubernetes/+spec/nested-dpdk-support
.. [2] https://docs.openstack.org/neutron/pike/contributor/internals/ovs_vhostuser.html
.. [3] http://docs.openvswitch.org/en/latest/topics/dpdk/vhost-user/
.. [4] https://specs.openstack.org/openstack/nova-specs/specs/kilo/implemented/libvirt_vif_vhostuser.html
.. [5] https://kubernetes.io/docs/tasks/manage-hugepages/scheduling-hugepages/
.. [6] https://docs.openstack.org/kuryr-kubernetes/latest/specs/rocky/npwg_spec_support.html
