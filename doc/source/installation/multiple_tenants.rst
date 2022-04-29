========================
Multiple tenants support
========================


Annotation project driver
-------------------------

We introduced an annotation project driver, by the driver you can specify a
openstack project for a k8s namespace, kuryr will take along the project id
when it creates openstack resources (port, subnet, LB, etc.) for the namespace
and the resources (pod, service, etc.) of the namespace.

Configure to enable the driver in kuryr.conf:

    .. code-block:: ini

      [kubernetes]
      pod_project_driver = annotation
      service_project_driver = annotation
      namespace_project_driver = annotation
      network_policy_project_driver = annotation


User workflow
~~~~~~~~~~~~~

#. Retrieve your own openstack project's id:

    .. code-block:: console

      $ openstack project show test-user
      +-------------+----------------------------------+
      | Field       | Value                            |
      +-------------+----------------------------------+
      | description |                                  |
      | domain_id   | default                          |
      | enabled     | True                             |
      | id          | b5e0a1ae99a34aa0b6a6dad59c95dea7 |
      | is_domain   | False                            |
      | name        | test-user                        |
      | options     | {}                               |
      | parent_id   | default                          |
      | tags        | []                               |
      +-------------+----------------------------------+

#. Create a k8s namespace with the project id

    The manifest file of the namespace:

    .. code-block:: yaml

      apiVersion: v1
      kind: Namespace
      metadata:
        name: testns
        annotations:
          openstack.org/kuryr-project: b5e0a1ae99a34aa0b6a6dad59c95dea7

    Modify the annotation ``openstack.org/kuryr-project``'s value to your own
    project id.

#. Create a pod in the created namespaces:

    .. code-block:: console

      $ kubectl create deployment -n testns --image quay.io/kuryr/demo demo
      deployment.apps/demo created

      $ kubectl -n testns get pod -o wide
      NAME                    READY   STATUS    RESTARTS   AGE     IP          NODE            NOMINATED NODE   READINESS GATES
      demo-6cb99dfd4d-mkjh2   1/1     Running   0          3m15s   10.0.1.76   yjf-dev-kuryr   <none>           <none>

#. Retrieve the related openstack resource:

    .. code-block:: console

      $ openstack network list --project b5e0a1ae99a34aa0b6a6dad59c95dea7
      +--------------------------------------+---------------+--------------------------------------+
      | ID                                   | Name          | Subnets                              |
      +--------------------------------------+---------------+--------------------------------------+
      | f7e3f025-6d03-40db-b6a8-6671b0874646 | ns/testns-net | d9995087-1363-4671-86da-51b4d17712d8 |
      +--------------------------------------+---------------+--------------------------------------+

      $ openstack subnet list --project b5e0a1ae99a34aa0b6a6dad59c95dea7
      +--------------------------------------+------------------+--------------------------------------+--------------+
      | ID                                   | Name             | Network                              | Subnet       |
      +--------------------------------------+------------------+--------------------------------------+--------------+
      | d9995087-1363-4671-86da-51b4d17712d8 | ns/testns-subnet | f7e3f025-6d03-40db-b6a8-6671b0874646 | 10.0.1.64/26 |
      +--------------------------------------+------------------+--------------------------------------+--------------+

      $ openstack port list --project b5e0a1ae99a34aa0b6a6dad59c95dea7
      +--------------------------------------+------------------------------+-------------------+--------------------------------------------------------------------------+--------+
      | ID                                   | Name                         | MAC Address       | Fixed IP Addresses                                                       | Status |
      +--------------------------------------+------------------------------+-------------------+--------------------------------------------------------------------------+--------+
      | 1ce9d0b7-de47-40bb-9bc3-2a8e179681b2 |                              | fa:16:3e:90:2a:a7 |                                                                          | DOWN   |
      | abddd00b-383b-4bf2-9b72-0734739e733d | testns/demo-6cb99dfd4d-mkjh2 | fa:16:3e:a4:c0:f7 | ip_address='10.0.1.76', subnet_id='d9995087-1363-4671-86da-51b4d17712d8' | ACTIVE |
      +--------------------------------------+------------------------------+-------------------+--------------------------------------------------------------------------+--------+
