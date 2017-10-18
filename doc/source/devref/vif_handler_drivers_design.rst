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

==================================
VIF-Handler And Vif Drivers Design
==================================

Purpose
-------
The purpose of this document is to present an approach for implementing
design of interaction between VIF-handler and the drivers it uses in
Kuryr-Kubernetes Controller.

VIF-Handler
-----------
VIF-handler is intended to handle VIFs. The main aim of VIF-handler is to get
the pod object, send it to Multi-vif driver and get vif objects from it. After
that VIF-handler is able to activate, release or update vifs. Also VIF-Handler
is always authorized to get main vif for pod from generic driver.
VIF-handler should stay clean whereas parsing of specific pod information
should be moved to Multi-vif driver.

Multi-vif driver
~~~~~~~~~~~~~~~~~
The main driver that is authorized to call other drivers. The main aim of
this driver is to get list of enabled drivers, parse pod annotations, pass
pod object to enabled drivers and get vif objects from them to pass these
objects to VIF-handler finally. The list of parsed annotations by Multi-vif
driver includes sriov requests, additional subnets requests and specific ports.
If the pod object doesn't have annotation which is required by some of the
drivers then this driver is not called or driver can just return.
Diagram describing VifHandler - Drivers flow is giver below:

.. image:: ../../images/vif_handler_drivers_design.png
    :alt: vif handler drivers design
    :align: center
    :width: 100%

Config Options
~~~~~~~~~~~~~~
Add new config option "enabled_vif_drivers" (list) to config file that shows
what drivers should be used in Multi-vif driver to collect vif objects. This
means that Multi-vif driver will pass pod object only to specified drivers
(generic driver is always used by default and it's not necessary to specify
it) and get vifs from them.
Option in config file might look like this:

.. code-block:: ini

    [kubernetes]

    enabled_vif_drivers =  sriov, additional_subnets


Additional Subnets Driver
~~~~~~~~~~~~~~~~~~~~~~~~~
Since it is possible to request additional subnets for the pod through the pod
annotations it is necessary to have new driver. According to parsed information
(requested subnets) by Multi-vif driver it has to return dictionary containing
the mapping 'subnet_id' -> 'network' for all requested subnets in unified format
specified in PodSubnetsDriver class.
Here's how a Pod Spec with additional subnets requests might look like:

.. code-block:: yaml

    spec:
      replicas: 1
      template:
        metadata:
          name: some-name
          labels:
            app: some-name
          annotations:
            openstack.org/kuryr-additional-subnets: '[
                "id_of_neutron_subnet_created_previously"
            ]'


SRIOV Driver
~~~~~~~~~~~~
SRIOV driver gets pod object from Multi-vif driver, according to parsed
information (sriov requests) by Multi-vif driver. It should return a list of
created vif objects. Method request_vif() has unified interface with
PodVIFDriver as a base class.
Here's how a Pod Spec with sriov requests might look like:

.. code-block:: yaml

    spec:
      containers:
      - name: vf-container
        image: vf-image
        resources:
          requests:
            pod.alpha.kubernetes.io/opaque-int-resource-sriov-vf-physnet2: 1


Specific ports support
----------------------
Specific ports support is enabled by default and will be a part of the drivers
to implement it. It is possile to have manually precreated specific ports in
neutron and specify them in pod annotations as preferably used. This means that
drivers will use specific ports if it is specified in pod annotations, otherwise
it will create new ports by default. It is important that specific ports can have
vnic_type both direct and normal, so it is necessary to provide processing
support for specific ports in both SRIOV and generic driver.
Pod annotation with requested specific ports might look like this:

.. code-block:: yaml

    spec:
      replicas: 1
      template:
        metadata:
          name: some-name
          labels:
            app: some-name
          annotations:
            spec-ports: '[
                "id_of_direct_precreated_port".
                "id_of_normal_precreated_port"
            ]'

Pod spec above should be interpreted the following way:
Multi-vif driver parses pod annotations and gets ids of specific ports.
If vnic_type is "normal" and such ports exist, it calls generic driver to create vif
objects for these ports. Else if vnic_type is "direct" and such ports exist, it calls
sriov driver to create vif objects for these ports. If certain ports are not
requested in annotations then driver doesn't return additional vifs to Multi-vif
driver.
