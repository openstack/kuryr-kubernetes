====================================
Installing kuryr-kubernetes manually
====================================

Configure kuryr-k8s-controller
------------------------------

Install ``kuryr-k8s-controller`` in a virtualenv:

.. code-block:: console

   $ mkdir kuryr-k8s-controller
   $ cd kuryr-k8s-controller
   $ virtualenv env
   $ git clone https://opendev.org/openstack/kuryr-kubernetes
   $ . env/bin/activate
   $ pip install -e kuryr-kubernetes

In neutron or in horizon create subnet for pods, subnet for services and a
security-group for pods. You may use existing if you like. In case that you
decide to create new networks and subnets with the cli, you can follow the
services guide, specifically its :ref:`k8s_default_configuration` section.

Create ``/etc/kuryr/kuryr.conf``:

.. code-block:: console

   $ cd kuryr-kubernetes
   $ ./tools/generate_config_file_samples.sh
   $ cp etc/kuryr.conf.sample /etc/kuryr/kuryr.conf

Edit ``kuryr.conf``:

.. code-block:: ini

   [DEFAULT]
   use_stderr = true
   bindir = {path_to_env}/libexec/kuryr

   [kubernetes]
   api_root = http://{ip_of_kubernetes_apiserver}:8080
   ssl_client_crt_file = {path-to-kuryr-k8s-user-cert-file}
   ssl_client_key_file = {path-to-kuryr-k8s-user-key-file}
   ssl_ca_crt_file = {path-to-k8s-api-ca-cert-file}

   [neutron]
   auth_url = http://127.0.0.1:35357/v3/
   username = admin
   user_domain_name = Default
   password = ADMIN_PASSWORD
   project_name = service
   project_domain_name = Default
   auth_type = password

   [neutron_defaults]
   ovs_bridge = br-int
   pod_security_groups = {id_of_secuirity_group_for_pods}
   pod_subnet = {id_of_subnet_for_pods}
   project = {id_of_project}
   service_subnet = {id_of_subnet_for_k8s_services}

.. note::

   If you want Kuryr to connect to Kubernetes through an unauthenticated
   endpoint make sure to set ``[kubernetes]ssl_ca_crt_file`` and
   ``[kubernetes]token_file`` to ``""`` as they default to the locations where
   Kubernetes puts those files for pods. Also don't set
   ``[kubernetes]ssl_client_crt_file`` and ``[kubernetes]ssl_client_key_file``.

   If you use tokens to authenticate use ``[kubernetes]token_file`` to specify
   a file having it.

.. note::

   If your Kubernetes cluster has RBAC enabled, make sure the Kuryr user has
   access to required resources:

   .. code-block:: yaml

      rules:
      - apiGroups:
        - ""
        verbs: ["*"]
        resources:
          - endpoints
          - pods
          - nodes
          - services
          - services/status
          - namespaces
      - apiGroups:
          - openstack.org
        verbs: ["*"]
        resources:
          - kuryrnetworks
          - kuryrnetworkpolicies
          - kuryrloadbalancers
      - apiGroups: ["networking.k8s.io"]
        resources:
        - networkpolicies
        verbs:
        - get
        - list
        - watch
        - update
        - patch
      - apiGroups: ["k8s.cni.cncf.io"]
        resources:
        - network-attachment-definitions
        verbs:
        - get

   You can generate ``ServiceAccount`` definition with correct ``ClusterRole``
   using instructions on :ref:`containerized-generate` page.

Note that the service_subnet and the pod_subnet *should be routable* and that
the pods should allow service subnet access.

Octavia supports two ways of performing the load balancing between the
Kubernetes load balancers and their members:

* Layer2: Octavia, apart from the VIP port in the services subnet, creates a
  Neutron port to the subnet of each of the members. This way the traffic from
  the Service Haproxy to the members will not go through the router again, only
  will have gone through the router to reach the service.
* Layer3: Octavia only creates the VIP port. The traffic from the service VIP
  to the members will go back to the router to reach the pod subnet. It is
  important to note that it will have some performance impact depending on the
  SDN.

To support the L3 mode (both for Octavia and for the deprecated
Neutron-LBaaSv2):

* There should be a router between the two subnets.
* The pod_security_groups setting should include a security group with a rule
  granting access to all the CIDR of the service subnet, e.g.:

  .. code-block:: console

     $ openstack security group create --project k8s_cluster_project \
          service_pod_access_sg
     $ openstack security group rule create --project k8s_cluster_project \
          --remote-ip cidr_of_service_subnet --ethertype IPv4 --protocol tcp \
          service_pod_access_sg

* The uuid of this security group id should be added to the comma separated
  list of pod security groups. *pod_security_groups* in *[neutron_defaults]*.

Alternatively, to support Octavia L2 mode:

* The pod security_groups setting should include a security group with a rule
  granting access to all the CIDR of the pod subnet, e.g.:

  .. code-block:: console

     $ openstack security group create --project k8s_cluster_project \
           octavia_pod_access_sg
     $ openstack security group rule create --project k8s_cluster_project \
           --remote-ip cidr_of_pod_subnet --ethertype IPv4 --protocol tcp \
           octavia_pod_access_sg

* The uuid of this security group id should be added to the comma separated
  list of pod security groups. *pod_security_groups* in *[neutron_defaults]*.

Run kuryr-k8s-controller:

.. code-block:: console

   $ kuryr-k8s-controller --config-file /etc/kuryr/kuryr.conf -d

Alternatively you may run it in screen:

.. code-block:: console

   $ screen -dm kuryr-k8s-controller --config-file /etc/kuryr/kuryr.conf -d


Configure kuryr-cni
-------------------

On every kubernetes minion node (and on master if you intend to run containers
there) you need to configure kuryr-cni.

Install ``kuryr-cni`` in a virtualenv:

.. code-block:: console

   $ mkdir kuryr-k8s-cni
   $ cd kuryr-k8s-cni
   $ virtualenv env
   $ . env/bin/activate
   $ git clone https://opendev.org/openstack/kuryr-kubernetes
   $ pip install -e kuryr-kubernetes

Create ``/etc/kuryr/kuryr.conf``:

.. code-block:: console

   $ cd kuryr-kubernetes
   $ ./tools/generate_config_file_samples.sh
   $ cp etc/kuryr.conf.sample /etc/kuryr/kuryr.conf

Edit ``kuryr.conf``:

.. code-block:: ini

   [DEFAULT]
   use_stderr = true
   bindir = {path_to_env}/libexec/kuryr
   [kubernetes]
   api_root = http://{ip_of_kubernetes_apiserver}:8080

Link the CNI binary to CNI directory, where kubelet would find it:

.. code-block:: console

   $ mkdir -p /opt/cni/bin
   $ ln -s $(which kuryr-cni) /opt/cni/bin/

Create the CNI config file for kuryr-cni: ``/etc/cni/net.d/10-kuryr.conflist``.
Kubelet would only use the lexicographically first file in that directory, so
make sure that it is kuryr's config file:

.. code-block:: json

   {
     "name": "kuryr",
     "cniVersion": "0.3.1",
     "plugins": [
       {
         "type": "kuryr-cni",
         "kuryr_conf": "/etc/kuryr/kuryr.conf",
         "debug": true
       }
     ]
   }

Install ``os-vif`` and ``oslo.privsep`` libraries globally. These modules
are used to plug interfaces and would be run with raised privileges. ``os-vif``
uses ``sudo`` to raise privileges, and they would need to be installed globally
to work correctly:

.. code-block:: console

   $ deactivate
   $ sudo pip install 'oslo.privsep>=1.20.0' 'os-vif>=1.5.0'


Configure Kuryr CNI Daemon
--------------------------

Kuryr CNI Daemon is a service designed to increased scalability of the Kuryr
operations done on Kubernetes nodes. More information can be found on
:ref:`cni-daemon` page.

Kuryr CNI Daemon, should be installed on every Kubernetes node, so following
steps need to be repeated.

.. note::

   You can tweak configuration of some timeouts to match your environment. It's
   crucial for scalability of the whole deployment. In general the timeout to
   serve CNI request from kubelet to Kuryr is 180 seconds. After that time
   kubelet will retry the request. Additionally there are two configuration
   options:

   .. code-block:: ini

      [cni_daemon]
      vif_annotation_timeout=60
      pyroute2_timeout=10

   ``vif_annotation_timeout`` is time the Kuryr CNI Daemon will wait for Kuryr
   Controller to create a port in Neutron and add information about it to Pod's
   metadata. If either Neutron or Kuryr Controller doesn't keep up with high
   number of requests, it's advised to increase this timeout. Please note that
   increasing it over 180 seconds will not have any effect as the request will
   time out anyway and will be retried (which is safe).

   ``pyroute2_timeout`` is internal timeout of pyroute2 library, that is
   responsible for doing modifications to Linux Kernel networking stack (e.g.
   moving interfaces to Pod's namespaces, adding routes and ports or assigning
   addresses to interfaces). When serving a lot of ADD/DEL CNI requests on a
   regular basis it's advised to increase that timeout. Please note that the
   value denotes *maximum* time to wait for kernel to complete the operations.
   If operation succeeds earlier, request isn't delayed.

Run kuryr-daemon:

.. code-block:: console

   $ kuryr-daemon --config-file /etc/kuryr/kuryr.conf -d

Alternatively you may run it in screen:

.. code-block:: console

   $ screen -dm kuryr-daemon --config-file /etc/kuryr/kuryr.conf -d


Kuryr CNI Daemon health checks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The CNI daemon health checks allow the deployer or the orchestration layer
(like for example Kubernetes or OpenShift) to probe the CNI daemon for liveness
and readiness.

If you want to make use of all of its facilities, you should run the
kuryr-daemon in its own cgroup. It will get its own cgroup if you:

* Run it as a systemd service,
* run it containerized,
* create a memory cgroup for it.

In order to make the daemon run in its own cgroup, you can do the following:

.. code-block:: console

   systemd-run --unit=kuryr-daemon --scope --slice=kuryr-cni \
       kuryr-daemon --config-file /etc/kuryr/kuryr.conf -d

After this, with the CNI daemon running inside its own cgroup, we can enable
the CNI daemon memory health check. This health check allows us to limit the
memory consumption of the CNI Daemon. The health checks will fail if CNI starts
taking more memory that it is set and the orchestration layer should restart.
The setting is:

.. code-block:: ini

   [cni_health_server]
   max_memory_usage = 4096  # Set the memory limit to 4GiB
