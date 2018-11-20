Upgrading kuryr-kubernetes
===========================

Kuryr-Kubernetes supports standard OpenStack utility for checking upgrade
is possible and safe:

.. code-block:: bash

    $ kuryr-k8s-status upgrade check
    +---------------------------------------+
    | Upgrade Check Results                 |
    +---------------------------------------+
    | Check: Pod annotations                |
    | Result: Success                       |
    | Details: All annotations are updated. |
    +---------------------------------------+

If any issue will be found, the utility will give you explanation and possible
remediations. Also note that *Warning* results aren't blocking an upgrade, but
are worth investigating.

Stein (0.6.x) to T (0.7.x) upgrade
----------------------------------

In T we want to drop support for old format of Pod annotations (switch was
motivated by multi-vif support feature implemented in Rocky). To make sure that
you don't have unsupported Pod annotations you need to run ``kuryr-k8s-status
upgrade check`` utility **before upgrading Kuryr-Kubernetes services to T**.

.. note::

    In case of running Kuryr-Kubernetes containerized you can use ``kubectl
    exec`` to run kuryr-k8s-status

    .. code-block:: bash

        $ kubectl -n kube-system exec -it <controller-pod-name> kuryr-k8s-status upgrade check

.. code-block:: bash

    $ kuryr-k8s-status upgrade check
    +---------------------------------------+
    | Upgrade Check Results                 |
    +---------------------------------------+
    | Check: Pod annotations                |
    | Result: Success                       |
    | Details: All annotations are updated. |
    +---------------------------------------+

In case of *Failure* result of *Pod annotations* check you should run
``kuryr-k8s-status upgrade update-annotations`` command and check again:

.. code-block:: bash

    $ kuryr-k8s-status upgrade check
    +----------------------------------------------------------------------+
    | Upgrade Check Results                                                |
    +----------------------------------------------------------------------+
    | Check: Pod annotations                                               |
    | Result: Failure                                                      |
    | Details: You have 3 Kuryr pod annotations in old format. You need to |
    |          run `kuryr-k8s-status upgrade update-annotations`           |
    |          before proceeding with the upgrade.                         |
    +----------------------------------------------------------------------+
    $ kuryr-k8s-status upgrade update-annotations
    +-----------------------+--------+
    | Stat                  | Number |
    +-----------------------+--------+
    | Updated annotations   | 3      |
    +-----------------------+--------+
    | Malformed annotations | 0      |
    +-----------------------+--------+
    | Annotations left      | 0      |
    +-----------------------+--------+
    $ kuryr-k8s-status upgrade check
    +---------------------------------------+
    | Upgrade Check Results                 |
    +---------------------------------------+
    | Check: Pod annotations                |
    | Result: Success                       |
    | Details: All annotations are updated. |
    +---------------------------------------+

It's possible that some annotations were somehow malformed. That will generate
a warning that should be investigated, but isn't blocking upgrading to T
(it won't make things any worse).

If in any case you need to rollback those changes, there is
``kuryr-k8s-status upgrade downgrade-annotations`` command as well.
