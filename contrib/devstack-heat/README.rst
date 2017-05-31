Kuryr Heat Templates
====================

This set of scripts and Heat templates are useful for deploying devstack
scenarios. It handles the creation of an allinone devstack nova instance and its
networking needs.

Prerequisites
~~~~~~~~~~~~~

Packages to install on the host you run devstack-heat (not on the cloud server):

* jq
* openstack-cli

If you want to run devstack from the master commit, this application requires a
github token due to the github api rate limiting:

You can generate one without any permissions at:

    https://github.com/settings/tokens/new

Then put it in your ~/.bashrc an ENV variable called DEVSTACK_HEAT_GH_TOKEN like
so:

echo "export DEVSTACK_HEAT_GH_TOKEN=my_token" >> ~/.bashrc

After creating the instance, devstack-heat will immediately start creating a
devstack `stack` user and using devstack to stack kuryr-kubernetes. When it is
finished, there'll be a file names `/opt/stack/ready`.

How to run
~~~~~~~~~~

In order to run it, make sure that you have sourced your OpenStack cloud
provider openrc file and tweaked `hot/parameters.yml` to your liking then launch
with::

    ./devstack-heat stack

This will deploy the latest master. You can also specify specific gerrit change
numbers::

    ./devstack-heat stack 465657

To obtain this number, just look for example at the following change::

    https://review.openstack.org/#/c/465657

In this instance, the number to pass to the *stack* subcommand is 466291.

This will create a stack named *gerrit_465657*. Further devstack-heat
subcommands should be called with the whole name of the stack, i.e.,
*gerrit_465657*.

Getting inside the deployment
-----------------------------

You can then ssh into the deployment in two ways::

    ./devstack-heat show name_of_my_stack

Write down the FIP it tells you and then::

    ./devstack-heat getkey name_of_my_stack > ~/name_of_my_stack.pem

Finally to get in (use the default username for the distro of your chosen
glance image, in the example below centos)::

    ssh -i ~/name_of_my_stack.pem centos@obtained_fip

Alternatively, if you wait a bit, devstack-heat will have set up the devstack
stack user and you can just do::

    ./devstack-heat ssh name_of_my_stack


To delete the deployment::

    ./devstack-heat unstack name_of_my_stack

Supported images
----------------

It should work with the latest centos7 image. It is not tested with the latest
ubuntu 16.04 cloud image but it will probably work.
