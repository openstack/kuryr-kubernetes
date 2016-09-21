===============================
kuryr-kubernetes
===============================

Kubernetes integration with OpenStack networking

Please fill here a long description which must be at least 3 lines wrapped on
80 cols, so that distribution package maintainers can use it in their packages.
Note that this is a hard requirement.

* Free software: Apache license
* Documentation: http://docs.openstack.org/developer/kuryr-kubernetes
* Source: http://git.openstack.org/cgit/openstack/kuryr-kubernetes
* Bugs: http://bugs.launchpad.net/kuryr-kubernetes


Configuring Kuryr
~~~~~~~~~~~~~~~~~

Generate sample config, `etc/kuryr.conf.sample`, running the following::

    $ ./tools/generate_config_file_samples.sh


Rename and copy config file at required path::

    $ cp etc/kuryr.conf.sample /etc/kuryr/kuryr.conf


Edit Neutron section in `/etc/kuryr/kuryr.conf`, replace ADMIN_PASSWORD::

    [neutron]
    auth_url = http://127.0.0.1:35357/v3/
    username = admin
    user_domain_name = Default
    password = ADMIN_PASSWORD
    project_name = service
    project_domain_name = Default
    auth_type = password


In the same file uncomment the `bindir` parameter with the path to the Kuryr
vif binding executables. For example, if you installed it on Debian or Ubuntu::

    [DEFAULT]
    bindir = /usr/local/libexec/kuryr


Features
--------

* TODO
