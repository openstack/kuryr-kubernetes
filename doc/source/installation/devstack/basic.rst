Basic DevStack installation
===========================

Most basic DevStack installation of kuryr-kubernetes is pretty simple. This
document aims to be a tutorial through installation steps.

Document assumes using Centos 7 OS, but same steps should apply for other
operating systems. It is also assumed that ``git`` is already installed on the
system. DevStack will make sure to install and configure OpenStack, Kubernetes
and dependencies of both systems.

Cloning required repositories
-----------------------------

First of all you need to clone DevStack: ::

    $ git clone https://opendev.org/openstack-dev/devstack

Create user *stack*, give it required permissions and log in as that user: ::

    $ ./devstack/tools/create-stack-user.sh
    $ sudo su stack

*stack* user has ``/opt/stack`` set as its home directory. It will need its own
repository with DevStack. Also clone kuryr-kubernetes: ::

    $ git clone https://opendev.org/openstack-dev/devstack
    $ git clone https://opendev.org/openstack/kuryr-kubernetes

Copy sample ``local.conf`` (DevStack configuration file) to devstack
directory: ::

    $ cp kuryr-kubernetes/devstack/local.conf.sample devstack/local.conf

.. note::

  ``local.conf.sample`` file is configuring Neutron and Kuryr with standard
  Open vSwitch ML2 networking. In the ``devstack`` directory there are other
  sample configuration files that enable OpenDaylight or Drangonflow networking.
  See other pages in this documentation section to learn more.

Now edit ``devstack/local.conf`` to set up some initial options:

* If you have multiple network interfaces, you need to set ``HOST_IP`` variable
  to the IP on the interface you want to use as DevStack's primary.
* ``KURYR_K8S_LBAAS_USE_OCTAVIA`` can be set to False if you want more
  lightweight installation. In that case installation of Glance and Nova will be
  omitted.
* If you already have Docker installed on the machine, you can comment out line
  starting with ``enable_plugin devstack-plugin-container``.

Once ``local.conf`` is configured, you can start the installation: ::

    $ ./devstack/stack.sh

Installation takes from 15 to 30 minutes. Once that's done you should see
similar output: ::

    =========================
    DevStack Component Timing
     (times are in seconds)
    =========================
    run_process            5
    test_with_retry        2
    pip_install           48
    osc                  121
    wait_for_service       1
    yum_install           31
    dbsync                27
    -------------------------
    Unaccounted time     125
    =========================
    Total runtime        360



    This is your host IP address: 192.168.101.249
    This is your host IPv6 address: fec0::5054:ff:feb0:213a
    Keystone is serving at http://192.168.101.249/identity/
    The default users are: admin and demo
    The password: password

    WARNING:
    Using lib/neutron-legacy is deprecated, and it will be removed in the future


    Services are running under systemd unit files.
    For more information see:
    https://docs.openstack.org/devstack/latest/systemd.html

    DevStack Version: queens
    Change: 301d4d1678c3c1342abc03e51a74574f7792a58b Merge "Use "pip list" in check_libs_from_git" 2017-10-04 07:22:59 +0000
    OS Version: CentOS 7.4.1708 Core

You can test DevStack by sourcing credentials and trying some commands: ::

    $ source /devstack/openrc admin admin
    $ openstack service list
    +----------------------------------+------------------+------------------+
    | ID                               | Name             | Type             |
    +----------------------------------+------------------+------------------+
    | 091e3e2813cc4904b74b60c41e8a98b3 | kuryr-kubernetes | kuryr-kubernetes |
    | 2b6076dd5fc04bf180e935f78c12d431 | neutron          | network          |
    | b598216086944714aed2c233123fc22d | keystone         | identity         |
    +----------------------------------+------------------+------------------+

To verify if Kubernetes is running properly, list its nodes and check status of
the only node you should have. The correct value is "Ready": ::

    $ kubectl get nodes
    NAME        STATUS    AGE       VERSION
    localhost   Ready     2m        v1.6.2

To test kuryr-kubernetes itself try creating a Kubernetes pod: ::

    $ kubectl run --image busybox test -- sleep 3600
    $ kubectl get pods -o wide
    NAME                    READY     STATUS              RESTARTS   AGE       IP        NODE
    test-3202410914-1dp7g   0/1       ContainerCreating   0          7s        <none>    localhost

After a moment (even up to few minutes as Docker image needs to be downloaded)
you should see that pod got the IP from OpenStack network: ::

    $ kubectl get pods -o wide
    NAME                    READY     STATUS    RESTARTS   AGE       IP          NODE
    test-3202410914-1dp7g   1/1       Running   0          35s       10.0.0.73   localhost

You can verify that this IP is really assigned to Neutron port: ::

    [stack@localhost kuryr-kubernetes]$ openstack port list | grep 10.0.0.73
    | 3ce7fd13-ad0a-4e92-9b6f-0d38d50b1699 |     | fa:16:3e:8e:f4:30 | ip_address='10.0.0.73', subnet_id='ddfbc8e9-68da-48f9-8a05-238ea0607e0d' | ACTIVE |

If those steps were successful, then it looks like your DevStack with
kuryr-kubernetes is working correctly. In case of errors, copy last ~50 lines of
the logs, paste them into `paste.openstack.org <http://paste.openstack.org>`_
and ask other developers for help on `Kuryr's IRC channel
<chat.freenode.net:6667/openstack-kuryr>`_. More info on how to use DevStack can
be found in `DevStack Documentation
<https://docs.openstack.org/devstack/latest/>`_, especially in section
`Using Systemd in DevStack
<https://docs.openstack.org/devstack/latest/systemd.html>`_, which explains how
to use ``systemctl`` to control services and ``journalctl`` to read its logs.