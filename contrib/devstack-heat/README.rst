Kuryr Heat Templates
====================

This set of scripts and Heat templates are useful for deploying DevStack
scenarios. It handles the creation of an all-in-one DevStack nova instance and
its networking needs.

Prerequisites
~~~~~~~~~~~~~

Packages to install on the host you run devstack-heat (not on the cloud
server):

* python-openstackclient

After creating the instance, devstack-heat will immediately start creating a
devstack `stack` user and using devstack to stack kuryr-kubernetes. When it is
finished, there'll be a file names `/opt/stack/ready`.

How to run
~~~~~~~~~~

In order to run it, make sure you reviewed values in `hot/parameters.yml`
(especially the `image`, `flavor` and `public_net` properties, the last one
telling in which network to create the floating IPs). The cloud credentials
should be in `~/.config/openstack/clouds.yaml`. Then the most basic run
requires executing::

    ./devstack_heat.py -c <cloud-name> stack -e hot/parameters.yml <stack-name>

This will deploy the latest master on cloud <cloud-name> in a stack
<stack-name>. You can also specify other sources than master::

  --gerrit GERRIT                     ID of Kuryr Gerrit change
  --commit COMMIT                     Kuryr commit ID
  --branch BRANCH                     Kuryr branch
  --devstack-branch DEVSTACK_BRANCH   DevStack branch to use

Note that some options are excluding other ones.

Besides that you can customize deployments using those options::

  -p KEY=VALUE, --parameter KEY=VALUE  Heat stack parameters
  --local-conf LOCAL_CONF              URL to DevStack local.conf file
  --bashrc BASHRC                      URL to bashrc file to put on VM
  --additional-key ADDITIONAL_KEY      URL to additional SSH key to add for
                                       stack user

`stack` will save you a private key for the deployment in `<stack-name>.pem`
file in current directory.

Getting inside the deployment
-----------------------------

You can then ssh into the deployment in two ways::

    ./devstack_heat.py show <stack-name>

Write down the FIP it tells you and then (might be skipped, key should be
there)::

    ./devstack_heat.py key <stack-name> > ./<stack-name>.pem

Finally to get in (use the default username for the distro of your chosen
glance image, in the example below centos)::

    ssh -i ./<stack-name>.pem ubuntu@<floating-ip>

Alternatively, if you wait a bit, devstack-heat will have set up the devstack
stack user and you can just do::

    ./devstack_heat.py ssh <stack-name>

If you want to observe the progress of the installation you can use `join` to
make it stream `stack.sh` logs::

    ./devstack_heat.py join <stack-name>

Note that you can make `stack` join automatically using its `--join` option.

To delete the deployment::

    ./devstack_heat.py unstack <stack-name>

Supported images
----------------

Scripts were tested with latest Ubuntu 20.04 cloud images.
