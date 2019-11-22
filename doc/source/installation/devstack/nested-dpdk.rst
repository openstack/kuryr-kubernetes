=========================================
How to try out nested-pods locally (DPDK)
=========================================

Following are the instructions for an all-in-one setup, using the nested DPDK
driver. We assume that we already have the 'undercloud' configured with at
least one VM as nova instance which is also a kubernetes minion. We assume
that VM has an access to the Internet to install necessary packages.

Configure the VM:

#. Install kernel version supporting uio_pci_generic module:

   .. code-block:: bash

      sudo apt install linux-image-`uname -r` linux-headers-`uname -r`
      sudo update-grub
      sudo reboot

#. Install DPDK. On Ubuntu:

   .. code-block:: bash

      sudo apt update
      sudo apt install dpdk

#. Enable hugepages:

   .. code-block:: bash

      sudo sysctl -w vm.nr_hugepages=768

#. Load DPDK userspace driver:

   .. code-block:: bash

      sudo modprobe uio_pci_generic

#. Clone devstack repository:

   .. code-block:: bash

      cd ~
      git clone https://git.openstack.org/openstack-dev/devstack

#. Edit local.conf:

   .. code-block:: ini

      [[local|localrc]]

      RECLONE="no"

      enable_plugin kuryr-kubernetes \
      https://git.openstack.org/openstack/kuryr-kubernetes

      OFFLINE="no"
      LOGFILE=devstack.log
      LOG_COLOR=False
      ADMIN_PASSWORD=<undercloud_password>
      DATABASE_PASSWORD=<undercloud_password>
      RABBIT_PASSWORD=<undercloud_password>
      SERVICE_PASSWORD=<undercloud_password>
      SERVICE_TOKEN=<undercloud_password>
      IDENTITY_API_VERSION=3
      ENABLED_SERVICES=""

      HOST_IP=<vm-ip-address>

      SERVICE_HOST=<undercloud-host-ip-address>
      MULTI_HOST=1
      KEYSTONE_SERVICE_HOST=$SERVICE_HOST
      MYSQL_HOST=$SERVICE_HOST
      RABBIT_HOST=$SERVICE_HOST

      KURYR_CONFIGURE_NEUTRON_DEFAULTS=False
      KURYR_CONFIGURE_BAREMETAL_KUBELET_IFACE=False

      enable_service docker
      enable_service etcd3
      enable_service kubernetes-api
      enable_service kubernetes-controller-manager
      enable_service kubernetes-scheduler
      enable_service kubelet
      enable_service kuryr-kubernetes
      enable_service kuryr-daemon

      [[post-config|$KURYR_CONF]]
      [nested_dpdk]
      dpdk_driver = uio_pci_generic

#. Stack:

   .. code-block:: bash

      cd ~/devstack
      ./stack.sh

#. Install CNI plugins:

   .. code-block:: bash

      wget https://github.com/containernetworking/plugins/releases/download/v0.6.0/cni-plugins-amd64-v0.6.0.tgz
      tar xf cni-plugins-amd64-v0.6.0.tgz -C ~/cni/bin/

#. Install Multus CNI using this guide: https://github.com/intel/multus-cni#build

   - *Note: Kuryr natively supports multiple VIFs now. In step 13 solution*
     *without Multus is described*

#. Create Multus CNI configuration file ~/cni/conf/multus-cni.conf:

   .. code-block:: json

      {
         "name":"multus-demo-network",
         "type":"multus",
         "delegates":[
            {
               "type":"kuryr-cni",
               "kuryr_conf":"/etc/kuryr/kuryr.conf",
               "debug":true
            },
            {
               "type":"macvlan",
               "master":"ens3",
               "masterplugin":true,
               "ipam":{
                  "type":"host-local",
                  "subnet":"10.0.0.0/24"
               }
            }
         ]
      }

#. Create a directory to store pci devices used by container:

   .. code-block:: bash

      mkdir /var/pci_address

#. If you do not use Multus CNI as a tool to have multiple interfaces in
   container but use some multi vif driver, then change Kuryr configuration file
   /etc/kuryr/kuryr.conf:

   .. code-block:: ini

      [kubernetes]
      pod_vif_driver = nested-vlan
      multi_vif_drivers = npwg_multiple_interfaces
      [vif_pool]
      vif_pool_mapping = nested-vlan:nested,nested-dpdk:noop

#. Also prepare and apply network attachment definition, for example:

   .. code-block:: yaml

      apiVersion: "k8s.cni.cncf.io/v1"
      kind: NetworkAttachmentDefinition
      metadata:
        name: "net-nested-dpdk"
        annotations:
          openstack.org/kuryr-config: '{
          "subnetId": "<NEUTRON SUBNET ID>",
          "driverType": "nested-dpdk"
          }'

#. Reload systemd services:

   .. code-block:: bash

      sudo systemctl daemon-reload

#. Restart systemd services:

   .. code-block:: bash

      sudo systemctl restart devstack@kubelet.service devstack@kuryr-kubernetes.service devstack@kuryr-daemon.service

#. Create pod specifying additional interface in annotations:

   .. code-block:: yaml

      apiVersion: extensions/v1beta1
      kind: Deployment
      metadata:
        name: nginx-nested-dpdk
      spec:
        replicas: 1
        template:
          metadata:
            name: nginx-nested-dpdk
            labels:
              app: nginx-nested-dpdk
            annotations:
              k8s.v1.cni.cncf.io/networks: net-nested-dpdk
          spec:
            containers:
            - name: nginx-nested-dpdk
              image: nginx
              resources:
                requests:
                  cpu: "1"
                  memory: "512Mi"
                limits:
                  cpu: "1"
                  memory: "512Mi"
            volumeMounts:
            - name: dev
              mountPath: /dev
            - name: pci_address
              mountPath: /var/pci_address
          volumes:
          - name: dev
            hostPath:
              path: /dev
              type: Directory
          - name: pci_address
            hostPath:
              path: /var/pci_address
              type: Directory

