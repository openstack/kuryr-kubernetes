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

================================
Active/Passive High Availability
================================


Overview
--------
Initially it was assumed that there will only be a single kuryr-controller
instance in the Kuryr-Kubernetes deployment. While it simplified a lot of
controller code, it is obviously not a perfect situation. Having redundant
controllers can help with achieving higher availability and scalability of the
deployment.

Now with introduction of possibility to run Kuryr in Pods on Kubernetes cluster
HA is much easier to be implemented. The purpose of this document is to explain
how will it work in practice.

Proposed Solution
-----------------
There are two types of HA - Active/Passive and Active/Active. In this document
we'll focus on the former. A/P basically works as one of the instances being
the leader (doing all the exclusive tasks) and other instances waiting in
*standby* mode in case the leader *dies* to take over the leader role. As you
can see a *leader election* mechanism is required to make this work.

Leader election
+++++++++++++++
The idea here is to use leader election mechanism based on Kubernetes
endpoints. The idea is neatly `explained on Kubernetes blog
<https://kubernetes.io/blog/2016/01/simple-leader-election-with-kubernetes/>`_.
Election is based on Endpoint resources, that hold annotation about current
leader and its leadership lease time. If leader dies, other instances of the
service are free to take over the record. Kubernetes API mechanisms will
provide update exclusion mechanisms to prevent race conditions.

This can be implemented by adding another *leader-elector* container to each
of kuryr-controller pods:

.. code:: yaml

 - image: gcr.io/google_containers/leader-elector:0.5
   name: leader-elector
   args:
   - "--election=kuryr-controller"
   - "--http=0.0.0.0:${KURYR_CONTROLLER_HA_PORT:-16401}"
   - "--election-namespace=kube-system"
   - "--ttl=5s"
   ports:
   - containerPort: ${KURYR_CONTROLLER_HA_PORT:-16401}
     protocol: TCP

This adds a new container to the pod. This container will do the
leader-election and expose the simple JSON API on port 16401 by default. This
API will be available to kuryr-controller container.

Kuryr Controller Implementation
+++++++++++++++++++++++++++++++
The main issue with having multiple controllers is task division. All of the
controllers are watching the same endpoints and getting the same notifications,
but those notifications cannot be processed by multiple controllers at once,
because we end up with a huge race condition, where each controller creates
Neutron resources but only one succeeds to put the annotation on the Kubernetes
resource it is processing.

This is obviously unacceptable so as a first step we're implementing A/P HA,
where only the leader is working on the resources and the other instances wait
as standby. This will be implemented by periodically calling the leader-elector
API to check the current leader. On leader change:

* Pod losing the leadership will stop its Watcher. Please note that it will be
  stopped gracefully, so all the ongoing operations will be completed.
* Pod gaining the leadership will start its Watcher. Please note that it will
  get notified about all the previously created Kubernetes resources, but will
  ignore them as they already have the annotations.
* Pods not affected by leadership change will continue to be in standby mode
  with their Watchers stopped.

Please note that this means that in HA mode Watcher will not get started on
controller startup, but only when periodic task will notice that it is the
leader.

Issues
++++++
There are certain issues related to orphaned OpenStack resources that we may
hit. Those can happen in two cases:

* Controller instance dies instantly during request processing. Some of
  OpenStack resources were already created, but information about them was not
  yet annotated onto Kubernetes resource. Therefore information is lost and we
  end up with orphaned OpenStack resources. New leader will process the
  Kubernetes resource by creating resources again.
* During leader transition (short period after a leader died, but before its
  lease expired and periodic task on other controllers noticed that; this
  shouldn't exceed 10s) some K8s resources are deleted. New leader will not
  get the notification about the deletion and those will go unnoticed.

Both of this issues can be tackled by garbage-collector mechanism that will
periodically look over Kubernetes resources and delete OpenStack resources that
have no representation in annotations.

The latter of the issues can also be tackled by saving last seen
``resourceVersion`` of watched resources list when stopping the Watcher and
restarting watching from that point.

Future enhancements
+++++++++++++++++++
It would be useful to implement the garbage collector and
``resourceVersion``-based protection mechanism described in section above.

Besides that to further improve the scalability, we should work on
Active/Active HA model, where work is divided evenly between all of the
kuryr-controller instances. This can be achieved e.g. by using
consistent hash ring to decide which instance will process which resource.

Potentially this can be extended with support for non-containerized deployments
by using Tooz and some other tool providing leader-election - like Consul or
Zookeeper.
