.. _containerized:

================================================
Kuryr installation as a Kubernetes network addon
================================================

Building images
~~~~~~~~~~~~~~~

First you should build kuryr-controller and kuryr-cni docker images and place
them on cluster-wide accessible registry.

For creating controller image on local machine:

.. code-block:: console

   $ docker build -t kuryr/controller -f controller.Dockerfile .

For creating cni daemonset image on local machine:

.. code-block:: console

   $ docker build -t kuryr/cni -f cni.Dockerfile .

Kuryr-kubernetes also includes a tool to automatically build the controller
image and deletes the existing container to apply the newly built
image. The tool is avaliable at:

.. code-block:: console

   $ contrib/regenerate_controller_pod.sh

If you want to run kuryr CNI without the daemon, build the image with:

.. code-block:: console

   $ docker build -t kuryr/cni -f cni.Dockerfile --build-arg CNI_DAEMON=False .

Alternatively, you can remove ``imagePullPolicy: Never`` from kuryr-controller
Deployment and kuryr-cni DaemonSet definitions to use pre-built `controller`_
and `cni`_ images from the Docker Hub. Those definitions will be generated in
next step.

.. _containerized-generate:

Generating Kuryr resource definitions for Kubernetes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

kuryr-kubernetes includes a tool that lets you generate resource definitions
that can be used to Deploy Kuryr on Kubernetes. The script is placed in
``tools/generate_k8s_resource_definitions.sh`` and takes up to 3 arguments:

.. code-block:: console

   $ ./tools/generate_k8s_resource_definitions.sh <output_dir> [<controller_conf_path>] [<cni_conf_path>] [<ca_certificate_path>]

* ``output_dir`` - directory where to put yaml files with definitions.
* ``controller_conf_path`` - path to custom kuryr-controller configuration
  file.
* ``cni_conf_path`` - path to custom kuryr-cni configuration file (defaults to
  ``controller_conf_path``).
* ``ca_certificate_path`` - path to custom CA certificate for OpenStack API. It
  will be added into Kubernetes as a ``Secret`` and mounted into
  kuryr-controller container. Defaults to no certificate.

.. note::

   Providing no or incorrect ``ca_certificate_path`` will still create the file
   with ``Secret`` definition with empty CA certificate file. This file will
   still be mounted in kuryr-controller ``Deployment`` definition.

If no path to config files is provided, script automatically generates minimal
configuration. However some of the options should be filled by the user. You
can do that either by editing the file after the ConfigMap definition is
generated or provide your options as environment variables before running the
script. Below is the list of available variables:

* ``$KURYR_K8S_API_ROOT`` - ``[kubernetes]api_root`` (default:
  https://127.0.0.1:6443)
* ``$KURYR_K8S_AUTH_URL`` - ``[neutron]auth_url`` (default:
  http://127.0.0.1/identity)
* ``$KURYR_K8S_USERNAME`` - ``[neutron]username`` (default: admin)
* ``$KURYR_K8S_PASSWORD`` - ``[neutron]password`` (default: password)
* ``$KURYR_K8S_USER_DOMAIN_NAME`` - ``[neutron]user_domain_name`` (default:
  Default)
* ``$KURYR_K8S_KURYR_PROJECT_ID`` - ``[neutron]kuryr_project_id``
* ``$KURYR_K8S_PROJECT_DOMAIN_NAME`` - ``[neutron]project_domain_name``
  (default: Default)
* ``$KURYR_K8S_PROJECT_ID`` - ``[neutron]k8s_project_id``
* ``$KURYR_K8S_POD_SUBNET_ID`` - ``[neutron_defaults]pod_subnet_id``
* ``$KURYR_K8S_POD_SG`` - ``[neutron_defaults]pod_sg``
* ``$KURYR_K8S_SERVICE_SUBNET_ID`` - ``[neutron_defaults]service_subnet_id``
* ``$KURYR_K8S_WORKER_NODES_SUBNETS`` - ``[pod_vif_nested]worker_nodes_subnets``
* ``$KURYR_K8S_BINDING_DRIVER`` - ``[binding]driver`` (default:
  ``kuryr.lib.binding.drivers.vlan``)
* ``$KURYR_K8S_BINDING_IFACE`` - ``[binding]link_iface`` (default: eth0)

.. note::

   kuryr-daemon will be started in the CNI container. It is using ``os-vif``
   and ``oslo.privsep`` to do pod wiring tasks. By default it'll call ``sudo``
   to raise privileges, even though container is priviledged by itself or
   ``sudo`` is missing from container OS (e.g. default CentOS 8). To prevent
   that make sure to set following options in kuryr.conf used for kuryr-daemon:

   .. code-block:: ini

     [vif_plug_ovs_privileged]
     helper_command=privsep-helper
     [vif_plug_linux_bridge_privileged]
     helper_command=privsep-helper

   Those options will prevent oslo.privsep from doing that. If rely on
   aformentioned script to generate config files, those options will be added
   automatically.

In case of using ports pool functionality, we may want to make the
kuryr-controller not ready until the pools are populated with the existing
ports. To achieve this a readiness probe must be added to the kuryr-controller
deployment. To add the readiness probe, in addition to the above environment
variables or the kuryr-controller configuration file, and extra environmental
variable must be set:

* ``$KURYR_USE_PORTS_POOLS`` - ``True`` (default: False)

Example run:

.. code-block:: console

   $ KURYR_K8S_API_ROOT="192.168.0.1:6443" ./tools/generate_k8s_resource_definitions.sh /tmp

This should generate 6 files in your ``<output_dir>``:

* config_map.yml
* certificates_secret.yml
* controller_service_account.yml
* cni_service_account.yml
* controller_deployment.yml
* cni_ds.yml

.. note::

   kuryr-cni daemonset mounts /var/run, due to necessity of accessing to
   several sub directories like openvswitch and auxiliary directory for
   vhostuser configuration and socket files. Also when
   neutron-openvswitch-agent works with datapath_type = netdev configuration
   option, kuryr-kubernetes has to move vhostuser socket to auxiliary
   directory, that auxiliary directory should be on the same mount point,
   otherwise connection of this socket will be refused. In case when Open
   vSwitch keeps vhostuser socket files not in /var/run/openvswitch,
   openvswitch mount point in cni_ds.yaml and [vhostuser] section in
   config_map.yml should be changed properly.


Deploying Kuryr resources on Kubernetes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To deploy the files on your Kubernetes cluster run:

.. code-block:: console

   $ kubectl apply -f config_map.yml -n kube-system
   $ kubectl apply -f certificates_secret.yml -n kube-system
   $ kubectl apply -f controller_service_account.yml -n kube-system
   $ kubectl apply -f cni_service_account.yml -n kube-system
   $ kubectl apply -f controller_deployment.yml -n kube-system
   $ kubectl apply -f cni_ds.yml -n kube-system

After successful completion:

* kuryr-controller Deployment object, with single replica count, will get
  created in kube-system namespace.
* kuryr-cni gets installed as a daemonset object on all the nodes in
  kube-system namespace

To see kuryr-controller logs:

.. code-block:: console

   $ kubectl logs <pod-name>

NOTE: kuryr-cni has no logs and to debug failures you need to check out kubelet
logs.


.. _controller: https://hub.docker.com/r/kuryr/controller/
.. _cni: https://hub.docker.com/r/kuryr/cni/
