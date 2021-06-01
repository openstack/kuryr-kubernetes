============================
So You Want to Contribute...
============================

For general information on contributing to OpenStack, please check out the
`contributor guide <https://docs.openstack.org/contributors/>`_ to get started.
It covers all the basics that are common to all OpenStack projects: the
accounts you need, the basics of interacting with our Gerrit review system, how
we communicate as a community, etc.

Below will cover the more project specific information you need to get started
with kuryr-kubernetes.


Communication
-------------

The primary communication channel of kuryr-kubernetes team is `#openstack-kuryr
channel on IRC <ircs://irc.oftc.net:6697/openstack-kuryr>`_. For more
formal inquiries you can use [kuryr] tag on `openstack-discuss mailing list
<http://lists.openstack.org/cgi-bin/mailman/listinfo/openstack-discuss>`_.
kuryr-kubernetes team is not holding weekly meetings, but we have office hours
every Monday at 15:00 UTC on our IRC channel.


Contacting the Core Team
------------------------

Outside of office hours, kuryr-kubernetes team is available mostly in the CET
working hours (7:00-17:00 UTC), as most of the team is located in Europe. Feel
free to try pinging dulek, ltomasbo, maysams or gryf on IRC, we have bouncers
set up so we'll answer once online.


New Feature Planning
--------------------

We don't really follow a very detailed way of feature planning. If you want to
implement a feature, come talk to us on IRC, create a `blueprint on Launchpad
<https://blueprints.launchpad.net/kuryr-kubernetes>`_ and start coding!
kuryr-kubernetes follows OpenStack release schedule pretty loosely as we're
more bound to Kubernetes release schedule. This means that we do not observe as
hard deadlines as other projects.


Task Tracking
-------------

We track our `tasks in Launchpad
<https://bugs.launchpad.net/kuryr-kubernetes>`_.

If you're looking for some smaller, easier work item to pick up and get started
on, search for the 'low-hanging-fruit' tag in either blueprints or bugs.


Reporting a Bug
---------------

You found an issue and want to make sure we are aware of it? You can do so on
`Launchpad <https://bugs.launchpad.net/kuryr-kubernetes>`_. It won't hurt to
ping us about it on IRC too.


Getting Your Patch Merged
-------------------------

We follow the normal procedures, requiring two +2's before approving the patch.
Due to limited number of contributors we do not require that those +2's are
from reviewers working for separate businesses.

If your patch is stuck in review, please ping us on IRC as listed in sections
above.


Project Team Lead Duties
------------------------

All common PTL duties are enumerated in the `PTL guide
<https://docs.openstack.org/project-team-guide/ptl.html>`_.

And additional PTL duty is to maintain `kuryr images on Docker Hub
<https://hub.docker.com/orgs/kuryr/repositories>`_.
