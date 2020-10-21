==========================
Containerized installation
==========================

It is possible to configure DevStack to install kuryr-controller and kuryr-cni
on Kubernetes as pods. Details can be found on :doc:`../containerized` page,
this page will explain DevStack aspects of running containerized.


Installation
------------

To configure DevStack to install Kuryr services as containerized Kubernetes
resources, you need to switch ``KURYR_K8S_CONTAINERIZED_DEPLOYMENT``. Add this
line to your ``local.conf``:

.. code-block:: ini

   KURYR_K8S_CONTAINERIZED_DEPLOYMENT=True

This will trigger building the kuryr-controller and kuryr-cni containers during
installation, as well as will deploy those on Kubernetes cluster it installed.


Rebuilding container images
---------------------------

Instructions on how to manually rebuild both kuryr-controller and kuryr-cni
container images are presented on :doc:`../containerized` page. In case you
want to test any code changes, you need to rebuild the images first.


Changing configuration
----------------------

To change kuryr.conf files that are put into containers you need to edit the
associated ConfigMap. On DevStack deployment this can be done using:

.. code-block:: console

   $ kubectl -n kube-system edit cm kuryr-config

Then the editor will appear that will let you edit the ConfigMap. Make sure to
keep correct indentation when doing changes.


Restarting services
-------------------

Once any changes are made to docker images or the configuration, it is crucial
to restart pod you've modified.


kuryr-controller
~~~~~~~~~~~~~~~~

To restart kuryr-controller and let it load new image and configuration, simply
kill existing pod:

.. code-block:: console

   $ kubectl -n kube-system get pods
   <find kuryr-controller pod you want to restart>
   $ kubectl -n kube-system delete pod <pod-name>

Deployment controller will make sure to restart the pod with new configuration.


kuryr-cni
~~~~~~~~~

It's important to understand that kuryr-cni is only a storage pod i.e. it is
actually idling with ``sleep infinity`` once all the files are copied into
correct locations on Kubernetes host.

You can force it to redeploy new files by killing it. DaemonSet controller
should make sure to restart it with new image and configuration files.

.. code-block:: console

   $ kubectl -n kube-system get pods
   <find kuryr-cni pods you want to restart>
   $ kubectl -n kube-system delete pod <pod-name1> <pod-name2> <...>
