===============================================
Kubernetes and OpenShift version support matrix
===============================================

This document maintains updated documentation about what Kubernetes and
OpenShift versions are supported at each Kuryr-Kubernetes release.


.. note::

   In general Kuryr should work fine with older versions of Kubernetes and
   OpenShift as well as it only depends from the APIs that are quite stable
   in Kubernetes itself. However we try to limit the number of supported
   versions, as Kubernetes policy is to only support last 3 minor releases.

.. note::

   Kuryr-Kubernetes follows *cycle-with-intermediary* release model and that's
   why there are multiple minor releases per single OpenStack release. Going
   forward it is possible that Kuryr-Kubernetes will switch to *independent*
   release model, that would completely untie it from OpenStack releases. This
   is because it seems to be easier to follow Kubernetes releases than
   OpenStack releases.

.. warning::

   In most cases only the latest supported version is tested in the CI/CD
   system.

========================  ======================================    ========================
Kuryr-Kubernetes version  Kubernetes version                        OpenShift Origin version
========================  ======================================    ========================
master (Victoria)         v1.16.x, v1.17.x, v1.18.x                 4.3, 4.4, 4.5
2.0.0 (Ussuri)            v1.14.x, v1.15.x, v1.16.x                 3.11, 4.2
1.1.0 (Train)             v1.13.x, v1.14.x, v1.15.x                 3.9, 3.10, 3.11, 4.2
0.6.x, 1.0.0 (Stein)      v1.11.x, v1.12.x, v1.13.x                 3.9, 3.10, 3.11, 4.2
0.5.2-3 (Rocky)           v1.9.x, v1.10.x, v1.11.x, v1.12.x         3.9, 3.10
0.5.0-1 (Rocky)           v1.9.x, v1.10.x                           3.9, 3.10
0.4.x (Queens)            v1.8.x                                    3.7
0.3.0 (Queens)            v1.6.x, v1.8.x                            No support
0.2.x (Pike)              v1.4.x, v1.6.x                            No support
0.1.0 (Pike)              v1.3.x, v1.4.x                            No support
========================  ======================================    ========================
