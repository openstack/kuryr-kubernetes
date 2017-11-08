Kuryr installation as a Kubernetes network addon
================================================

Building images
~~~~~~~~~~~~~~~

First you should build kuryr-controller and kuryr-cni docker images and place
them on cluster-wide accessible registry.

For creating controller image on local machine: ::

    $ docker build -t kuryr/controller -f controller.Dockerfile .

For creating cni daemonset image on local machine: ::

    $ ./tools/build_cni_daemonset_image

Alternatively, you can remove ``imagePullPolicy: Never`` from kuryr-controller
Deployment and kuryr-cni DaemonSet definitions to use pre-built
`controller <https://hub.docker.com/r/kuryr/controller/>`_ and `cni <https://hub.docker.com/r/kuryr/cni/>`_
images from the Docker Hub. Those definitions will be generated in next step.

Generating Kuryr resource definitions for Kubernetes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

kuryr-kubernetes includes a tool that lets you generate resource definitions
that can be used to Deploy Kuryr on Kubernetes. The script is placed in
``tools/generate_k8s_resource_definitions.sh`` and takes up to 3 arguments: ::

    $ ./tools/generate_k8s_resource_definitions <output_dir> [<controller_conf_path>] [<cni_conf_path>]

* ``output_dir`` - directory where to put yaml files with definitions.
* ``controller_conf_path`` - path to custom kuryr-controller configuration file.
* ``cni_conf_path`` - path to custom kuryr-cni configuration file (defaults to
  ``controller_conf_path``).

If no path to config files is provided, script automatically generates minimal
configuration. However some of the options should be filled by the user. You can
do that either by editing the file after the ConfigMap definition is generated
or provide your options as environment variables before running the script.
Below is the list of available variables:

* ``$KURYR_K8S_API_ROOT`` - ``[kubernetes]api_root`` (default: https://127.0.0.1:6443)
* ``$KURYR_K8S_AUTH_URL`` - ``[neutron]auth_url`` (default: http://127.0.0.1/identity)
* ``$KURYR_K8S_USERNAME`` - ``[neutron]username`` (default: admin)
* ``$KURYR_K8S_PASSWORD`` - ``[neutron]password`` (default: password)
* ``$KURYR_K8S_USER_DOMAIN_NAME`` - ``[neutron]user_domain_name`` (default: Default)
* ``$KURYR_K8S_KURYR_PROJECT_ID`` - ``[neutron]kuryr_project_id``
* ``$KURYR_K8S_PROJECT_DOMAIN_NAME`` - ``[neutron]project_domain_name`` (default: Default)
* ``$KURYR_K8S_PROJECT_ID`` - ``[neutron]k8s_project_id``
* ``$KURYR_K8S_POD_SUBNET_ID`` - ``[neutron_defaults]pod_subnet_id``
* ``$KURYR_K8S_POD_SG`` - ``[neutron_defaults]pod_sg``
* ``$KURYR_K8S_SERVICE_SUBNET_ID`` - ``[neutron_defaults]service_subnet_id``
* ``$KURYR_K8S_WORKER_NODES_SUBNET`` - ``[pod_vif_nested]worker_nodes_subnet``
* ``$KURYR_K8S_BINDING_DRIVER`` - ``[binding]driver`` (default: ``kuryr.lib.binding.drivers.vlan``)
* ``$KURYR_K8S_BINDING_IFACE`` - ``[binding]link_iface`` (default: eth0)

In case of using ports pool functionality, we may want to make the
kuryr-controller not ready until the pools are populated with the existing
ports. To achive this a readiness probe must be added to the kuryr-controller
deployment. To add the readiness probe, in addition to the above environment
variables or the kuryr-controller configuration file, and extra environmental
variable must be set:

* ``$KURYR_USE_PORTS_POOLS`` - ``True`` (default: False)

Example run: ::

    $ KURYR_K8S_API_ROOT="192.168.0.1:6443" ./tools/generate_k8s_resource_definitions /tmp

This should generate 4 files in your ``<output_dir>``:

* config_map.yml
* service_account.yml
* controller_deployment.yml
* cni_ds.yml

Deploying Kuryr resources on Kubernetes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To deploy the files on your Kubernetes cluster run: ::

    $ kubectl apply -f config_map.yml -n kube-system
    $ kubectl apply -f service_account.yml -n kube-system
    $ kubectl apply -f controller_deployment.yml -n kube-system
    $ kubectl apply -f cni_ds.yml -n kube-system

After successful completion:

* kuryr-controller Deployment object, with single replica count, will get
  created in kube-system namespace.
* kuryr-cni gets installed as a daemonset object on all the nodes in kube-system
  namespace

To see kuryr-controller logs ::
    $ kubectl logs <pod-name>

NOTE: kuryr-cni has no logs and to debug failures you need to check out kubelet
logs.
