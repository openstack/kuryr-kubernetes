=========================
Boot VM with a Trunk Port
=========================

To create a VM that makes use of the Neutron Trunk port support, the next
steps can be followed:

#. Use the demo tenant and create a key to be used to log in into the overcloud
   VM:

   .. code-block:: console

      $ source ~/devstack/openrc demo
      $ openstack keypair create demo > id_rsa_demo
      $ chmod 600 id_rsa_demo

#. Ensure the demo default security group allows ping and ssh access:

   .. code-block:: console

      $ openstack security group rule create --protocol icmp default
      $ openstack security group rule create --protocol tcp --dst-port 22 default

#. Download and import an image that allows vlans, as cirros does not support
   it:

   .. code-block:: console

      $ wget http://cloud.centos.org/centos/7/images/CentOS-7-x86_64-GenericCloud.qcow2
      $ openstack image create --container-format bare --disk-format qcow2 --file CentOS-7-x86_64-GenericCloud.qcow2 centos7

#. Create a port for the overcloud VM and create the trunk with that port as
   the parent port (untagged traffic):

   .. code-block:: console

      $ openstack port create --network private --security-group default port0
      $ openstack network trunk create --parent-port port0 trunk0

#. Create the overcloud VM and assign a floating ip to it to be able to log in
   into it:

   .. code-block:: console

      $ openstack server create --image centos7 --flavor ds4G --nic port-id=port0 --key-name demo overcloud_vm
      $ openstack floating ip create --port port0 public

   Note subports can be added to the trunk port, and be used inside the VM with
   the specific vlan, 102 in the example, by doing:

   .. code-block:: console

      $ openstack network trunk set --subport port=subport0,segmentation-type=vlan,segmentation-id=102 trunk0
