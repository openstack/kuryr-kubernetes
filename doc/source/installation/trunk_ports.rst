Boot VM with a Trunk Port
=========================

To create a VM that makes use of the Neutron Trunk port support, the next
steps can be followed:

1. Use the demo tenant and create a key to be used to log in into the overcloud
   VM::

    $ source ~/devstack/openrc demo
    $ openstack keypair create demo > id_rsa_demo
    $ chmod 600 id_rsa_demo


2. Ensure the demo default security group allows ping and ssh access::

    $ openstack security group rule create --protocol icmp default
    $ openstack security group rule create --protocol tcp --dst-port 22 default


3. Download and import an image that allows vlans, as cirros does not support
   it::

    $ wget http://cloud.centos.org/centos/7/images/CentOS-7-x86_64-GenericCloud.qcow2
    $ openstack image create --container-format bare --disk-format qcow2 --file CentOS-7-x86_64-GenericCloud.qcow2 centos7


4. Create a port for the overcloud VM and create the trunk with that port as
   the parent port (untagged traffic)::

    $ openstack port create --network private --security-group default port0
    $ openstack network trunk create --parent-port port0 trunk0


5. Create the overcloud VM and assign a floating ip to it to be able to log in
   into it::

    $ openstack server create --image centos7 --flavor ds4G --nic port-id=port0 --key-name demo overcloud_vm
    $ openstack floating ip create --port port0 public


Note subports can be added to the trunk port, and be used inside the VM with the
specific vlan, 102 in the example, by doing::

    $ openstack network trunk set --subport port=subport0,segmentation-type=vlan,segmentation-id=102 trunk0
