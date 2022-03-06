===========================
Basic DevStack installation
===========================

Most basic DevStack installation of kuryr-kubernetes is pretty simple. This
document aims to be a tutorial through installation steps.

Document assumes using Ubuntu LTS 20.04 (using server or cloud installation is
recommended, but desktop will also work), but same steps should apply for other
operating systems. It is also assumed that ``git`` and ``curl`` are already
installed on the system. DevStack will make sure to install and configure
OpenStack, Kubernetes and dependencies of both systems.

Please note, that DevStack installation should be done inside isolated
environment such as virtual machine, since it will make substantial changes to
the host.


Cloning required repositories
-----------------------------

First of all, you'll need a user account, which can execute passwordless
``sudo`` command.  Consult `DevStack Documentation`_ for details, how to create
one, or simply add line:

.. code-block:: ini

   "USERNAME ALL=(ALL) NOPASSWD:ALL"

to ``/etc/sudoers`` using ``visudo`` command. Remember to change ``USERNAME``
to the real name of the user account.

Clone DevStack:

.. code-block:: console

   $ git clone https://opendev.org/openstack-dev/devstack

Copy sample ``local.conf`` (DevStack configuration file) to devstack
directory:

.. code-block:: console

   $ curl https://opendev.org/openstack/kuryr-kubernetes/raw/branch/master/devstack/local.conf.sample \
     -o devstack/local.conf

.. note::

   ``local.conf.sample`` file is configuring Neutron and Kuryr with OVN
   ML2 networking. In the ``kuryr-kubernetes/devstack`` directory there are
   other sample configuration files that enable Open vSwitch instead OVN.
   networking. See other pages in this documentation section to learn more.

Now edit ``devstack/local.conf`` to set up some initial options:

* If you have multiple network interfaces, you need to set ``HOST_IP`` variable
  to the IP on the interface you want to use as DevStack's primary. DevStack
  sometimes complain about lacking of ``HOST_IP`` even if there is single
  network interface.
* If you already have Docker installed on the machine, you can comment out line
  starting with ``enable_plugin devstack-plugin-container``.
* If you can't pull images from k8s.gcr.io, you can add the variable
  ``KURYR_KUBEADMIN_IMAGE_REPOSITORY`` to ``devstack/local.conf`` and set it's
  value to the repository that you can access.

Once ``local.conf`` is configured, you can start the installation:

.. code-block:: console

   $ devstack/stack.sh

Installation takes from 20 to 40 minutes. Once that's done you should see
similar output:

.. code-block:: console

   =========================
   DevStack Component Timing
    (times are in seconds)
   =========================
   wait_for_service       8
   pip_install          137
   apt-get              295
   run_process           14
   dbsync                22
   git_timed            168
   apt-get-update         4
   test_with_retry        3
   async_wait            71
   osc                  200
   -------------------------
   Unaccounted time     505
   =========================
   Total runtime        1427

   =================
    Async summary
   =================
    Time spent in the background minus waits: 140 sec
    Elapsed time: 1427 sec
    Time if we did everything serially: 1567 sec
    Speedup:  1.09811



   This is your host IP address: 10.0.2.15
   This is your host IPv6 address: ::1
   Keystone is serving at http://10.0.2.15/identity/
   The default users are: admin and demo
   The password: pass

   Services are running under systemd unit files.
   For more information see:
   https://docs.openstack.org/devstack/latest/systemd.html

   DevStack Version: xena
   Change:
   OS Version: Ubuntu 20.04 focal


You can test DevStack by sourcing credentials and trying some commands:

.. code-block:: console

   $ source devstack/openrc admin admin
   $ openstack service list
   +----------------------------------+------------------+------------------+
   | ID                               | Name             | Type             |
   +----------------------------------+------------------+------------------+
   | 07e985b425fc4f8a9da20970a26f754a | octavia          | load-balancer    |
   | 1dc08cb4401243848a562c0042d3f40a | neutron          | network          |
   | 35627730938d4a4295f3add6fc826261 | nova             | compute          |
   | 636b43b739e548e0bb369bc41fe1df08 | glance           | image            |
   | 90ef7129985e4e10874d5e4ddb36ea01 | keystone         | identity         |
   | ce177a3f05dc454fb3d43f705ae24dde | kuryr-kubernetes | kuryr-kubernetes |
   | d3d6a461a78e4601a14a5e484ec6cdd1 | nova_legacy      | compute_legacy   |
   | d97e5c31b1054a308c5409ee813c0310 | placement        | placement        |
   +----------------------------------+------------------+------------------+

To verify if Kubernetes is running properly, list its nodes and check status of
the only node you should have. The correct value is "Ready":

.. code-block:: console

   $ kubectl get nodes
   NAME        STATUS    AGE       VERSION
   localhost   Ready     2m        v1.6.2

To test kuryr-kubernetes itself try creating a Kubernetes pod:

.. code-block:: console

   $ kubectl create deployment --image busybox test -- sleep 3600
   $ kubectl get pods -o wide
   NAME                    READY     STATUS              RESTARTS   AGE       IP        NODE
   test-3202410914-1dp7g   0/1       ContainerCreating   0          7s        <none>    localhost

After a moment (even up to few minutes as Docker image needs to be downloaded)
you should see that pod got the IP from OpenStack network:

.. code-block:: console

   $ kubectl get pods -o wide
   NAME                    READY     STATUS    RESTARTS   AGE       IP          NODE
   test-3202410914-1dp7g   1/1       Running   0          35s       10.0.0.73   localhost

You can verify that this IP is really assigned to Neutron port:

.. code-block:: console

   [stack@localhost kuryr-kubernetes]$ openstack port list | grep 10.0.0.73
   | 3ce7fd13-ad0a-4e92-9b6f-0d38d50b1699 |     | fa:16:3e:8e:f4:30 | ip_address='10.0.0.73', subnet_id='ddfbc8e9-68da-48f9-8a05-238ea0607e0d' | ACTIVE |

If those steps were successful, then it looks like your DevStack with
kuryr-kubernetes is working correctly. In case of errors, copy last ~50 lines
of the logs, paste them into `paste.openstack.org`_ and ask other developers
for help on `Kuryr's IRC channel`_. More info on how to use DevStack can be
found in `DevStack Documentation`_, especially in section `Using Systemd in
DevStack`_, which explains how to use ``systemctl`` to control services and
``journalctl`` to read its logs.


.. _paste.openstack.org: http://paste.openstack.org
.. _Kuryr's IRC channel: ircs://irc.oftc.net:6697/openstack-kuryr
.. _DevStack Documentation: https://docs.openstack.org/devstack/latest/
.. _Using Systemd in DevStack: https://docs.openstack.org/devstack/latest/systemd.html
