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


======================================
Kuryr Support Multiple Projects Design
======================================


Purpose
-------

Now, ``kuryr-kubernetes`` just implement a default project driver, the project
id of openstack resource which used to support k8s resource was specified by
configuration option ``neutron_defaults.project``. This means all of these
openstack resources have the same project id. This will result in some puzzling
issues in multiple tenant environment. Such as, the metering and billing system
can not classify these resources and the resources will exceed the tenant's
quota. In order to resolve these issues, we need to ensure these resources have
different project id (For the sake of simplicity, we can treat a project as a
tenant).


Overview
--------

Implement an annotation project driver for ``namespace``, ``pod`. ``service``
and ``network policy``. The driver can read project id from the annotations of
this resources' namespace.


Proposed Solution
-----------------

Now, the openstack resources that are created by ``kuryr-kubernetes`` only
involves ``neutron`` and ``octavia``. ``Neutron`` and ``octavia`` use openstack
project id to isolate their resources, so we can treat a openstack project as a
metering or billing tenant. Generally, ``kuryr-kubernetes`` use ``kuryr`` user
to create/delete/update/read ``neutron`` or ``octavia`` resources. The
``kuryr`` user has admin role, so ``kuryr-kubernetes`` can manage any project's
resources.

So, I propose that we introduce an annotation ``openstack.org/kuryr-project``,
the annotation should be set when a k8s namespace was created. The annotation's
value is a openstack project's id. One k8s namespace can only specify one
openstack project, but one openstack project can be associated with one or
multiple k8s namespace.

.. note::

   ``kuryr-kubernetes`` can not verify the project id that speficied by
   ``openstack.org/kuryr-project``. So, the validity of project id should be
   ensured by third-party process. In addition to, we suggest that the
   privilege of k8s namespace creation and updation only grant the user who has
   admin role (avoid the common user to create k8s namespace arbitrarily).

When user create a ``pod``, ``service`` or ``network policy``, the new project
driver will retrieve these resources's namespace and get the namespace's
information, then the driver will try to get project id from annotaion
``openstack.org/kuryr-project``. If the driver succeed get project id, the
project id will return to these resource's handlers, then these handlers will
create related openstack resource with the project id.

.. note::

    This is only solving the resource ownership issues. No isolation in terms
    of networking will be achieved this way.

For namespace, then namespace handler can get namespace information from the
``on_present`` function's parameter. So, the namespace annotaion project driver
can try get project id from the information directly.

If user don't add ``openstack.org/kuryr-project`` annotation to namespace, the
default project need to be selected, the default project specified by
configuration option ``neutron_defaults.project``. If the default project not
specified still, the driver will raise ``cfg.RequiredOptError`` error.


Testing
-------

Need to add a new CI gate with these drivers

Tempest Tests
~~~~~~~~~~~~~

Need to add tempest tests
