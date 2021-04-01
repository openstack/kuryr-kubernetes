=============================
Subport pools management tool
=============================

This tool makes it easier to deal with subports pools. It allows to populate
a given amount of subports at the specified pools (i.e., at the VM trunks), as
well as to free the unused ones.

The first step to perform is to enable the pool manager by adding this to
``/etc/kuryr/kuryr.conf``::

    [kubernetes]
    enable_manager = True


If the environment has been deployed with devstack, the socket file directory
will have been created automatically. However, if that is not the case, you
need to create the directory for the socket file with the right permissions.
If no other path is specified, the default location for the socket file is:
``/run/kuryr/kuryr_manage.sock``

Hence, you need to create that directory and give it read/write access to the
user who is running the kuryr-kubernetes.service, for instance::

    $ sudo mkdir -p /run/kuryr
    $ sudo chown stack:stack /run/kuryr


Finally, restart kuryr-k8s-controller::

    $ sudo systemctl restart devstack@kuryr-kubernetes.service


Populate subport pools for nested environment
---------------------------------------------

Once the nested environment is up and running, and the pool manager has been
started, we can populate the pools, i.e., the trunk ports in used by the
overcloud VMs, with subports. From the *undercloud* we just need to make use
of the subports.py tool.

To obtain information about the tool options::

    $ python contrib/pools-management/subports.py -h
    usage: subports.py [-h] {create,free} ...

    Tool to create/free subports from the subport pools

    positional arguments:
    {create,free}  commands
        create       Populate the pool(s) with subports
        free         Remove unused subports from the pools

    optional arguments:
    -h, --help     show this help message and exit


And to obtain information about the create subcommand::

    $ python contrib/pools-management/subports.py create -h
    usage: subports.py create [-h] --trunks SUBPORTS [SUBPORTS ...] [-n NUM] [-t TIMEOUT]

    optional arguments:
    -h, --help            show this help message and exit
    --trunks SUBPORTS [SUBPORTS ...]
                                                list of trunk IPs where subports will be added
    -n NUM, --num-ports NUM
                                                number of subports to be created per pool
    -t TIMEOUT, --timeout TIMEOUT
                          set timeout for operation. Default is 180 sec


Then, we can check the existing (overcloud) VMs to use their (trunk) IPs to
later populate their respective pool::

    $ openstack server list -f value -c Networks
    net0-10.0.4.5
    net0=10.0.4.6, 172.24.4.5


As it can be seen, the second VM has also a floating ip associated, but we
only need to use the one belonging to `net0`. If we want to create and attach
a subport to the 10.0.4.5 trunk, and the respective pool, we just need to do::

    $ python contrib/pools-management/subports.py create --trunks 10.0.4.5


As the number of ports to create is not specified, it only creates 1 subport
as this is the default value. We can check the result of this command with::

    # Checking the subport named `available-port` has been created
    $ openstack port list | grep available-port
    | 1de77073-7127-4c39-a47b-cef15f98849c | available-port| fa:16:3e:64:7d:90 | ip_address='10.0.0.70', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |

    # Checking the subport is attached to the VM trunk
    $ openstack network trunk show trunk1
    +-----------------+--------------------------------------------------------------------------------------------------+
    | Field           | Value                                                                                            |
    +-----------------+--------------------------------------------------------------------------------------------------+
    | admin_state_up  | UP                                                                                               |
    | created_at      | 2017-08-28T15:06:54Z                                                                             |
    | description     |                                                                                                  |
    | id              | 9048c109-c1aa-4a41-9508-71b2ba98f3b0                                                             |
    | name            | trunk1                                                                                           |
    | port_id         | 4180a2e5-e184-424a-93d4-54b48490f50d                                                             |
    | project_id      | a05f6ec0abd04cba80cd160f8baaac99                                                                 |
    | revision_number | 43                                                                                               |
    | status          | ACTIVE                                                                                           |
    | sub_ports       | port_id='1de77073-7127-4c39-a47b-cef15f98849c', segmentation_id='3934', segmentation_type='vlan' |
    | tags            | []                                                                                               |
    | tenant_id       | a05f6ec0abd04cba80cd160f8baaac99                                                                 |
    | updated_at      | 2017-08-29T06:12:39Z                                                                             |
    +-----------------+--------------------------------------------------------------------------------------------------+


It can be seen that the port with id `1de77073-7127-4c39-a47b-cef15f98849c`
has been attached to `trunk1`.

Similarly, we can add subport to different pools by including several IPs at
the `--trunks` option, and we can also modify the amount of subports created
per pool with the `--num` option::

    $ python contrib/pools-management/subports.py create --trunks 10.0.4.6 10.0.4.5 --num 3


This command will create 6 subports in total, 3 at trunk 10.0.4.5 and another
3 at trunk 10.0.4.6. So, to check the result of this command, as before::

    $ openstack port list | grep available-port
    | 1de77073-7127-4c39-a47b-cef15f98849c | available-port | fa:16:3e:64:7d:90 | ip_address='10.0.0.70', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |
    | 52e52281-4692-45e9-935e-db77de44049a | available-port | fa:16:3e:0b:45:f6 | ip_address='10.0.0.73', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |
    | 71245983-e15e-4ae8-9425-af255b54921b | available-port | fa:16:3e:e5:2f:90 | ip_address='10.0.0.68', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |
    | b6a8aa34-feef-42d7-b7ce-f9c33ac499ca | available-port | fa:16:3e:0c:8c:b0 | ip_address='10.0.0.65', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |
    | bee0cb3e-8d83-4942-8cdd-fc091b6e6058 | available-port | fa:16:3e:c2:0a:c6 | ip_address='10.0.0.74', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |
    | c2d7b5c9-606d-4499-9981-0f94ec94f7e1 | available-port | fa:16:3e:73:89:d2 | ip_address='10.0.0.67', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |
    | cb42940f-40c0-4e01-aa40-f3e9c5f6743f | available-port | fa:16:3e:49:73:ca | ip_address='10.0.0.66', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |

    $ openstack network trunk show trunk0
    +-----------------+--------------------------------------------------------------------------------------------------+
    | Field           | Value                                                                                            |
    +-----------------+--------------------------------------------------------------------------------------------------+
    | admin_state_up  | UP                                                                                               |
    | created_at      | 2017-08-25T07:28:11Z                                                                             |
    | description     |                                                                                                  |
    | id              | c730ff56-69c2-4540-b3d4-d2978007236d                                                             |
    | name            | trunk0                                                                                           |
    | port_id         | ad1b8e91-0698-473d-a2f2-d123e8a0af45                                                             |
    | project_id      | a05f6ec0abd04cba80cd160f8baaac99                                                                 |
    | revision_number | 381                                                                                              |
    | status          | ACTIVE                                                                                           |
    | sub_port        | port_id='bee0cb3e-8d83-4942-8cdd-fc091b6e6058', segmentation_id='875', segmentation_type='vlan'  |
    |                 | port_id='71245983-e15e-4ae8-9425-af255b54921b', segmentation_id='1446', segmentation_type='vlan' |
    |                 | port_id='b6a8aa34-feef-42d7-b7ce-f9c33ac499ca', segmentation_id='1652', segmentation_type='vlan' |
    | tags            | []                                                                                               |
    | tenant_id       | a05f6ec0abd04cba80cd160f8baaac99                                                                 |
    | updated_at      | 2017-08-29T06:19:24Z                                                                             |
    +-----------------+--------------------------------------------------------------------------------------------------+

    $ openstack network trunk show trunk1
    +-----------------+--------------------------------------------------------------------------------------------------+
    | Field           | Value                                                                                            |
    +-----------------+--------------------------------------------------------------------------------------------------+
    | admin_state_up  | UP                                                                                               |
    | created_at      | 2017-08-28T15:06:54Z                                                                             |
    | description     |                                                                                                  |
    | id              | 9048c109-c1aa-4a41-9508-71b2ba98f3b0                                                             |
    | name            | trunk1                                                                                           |
    | port_id         | 4180a2e5-e184-424a-93d4-54b48490f50d                                                             |
    | project_id      | a05f6ec0abd04cba80cd160f8baaac99                                                                 |
    | revision_number | 46                                                                                               |
    | status          | ACTIVE                                                                                           |
    | sub_ports       | port_id='c2d7b5c9-606d-4499-9981-0f94ec94f7e1', segmentation_id='289', segmentation_type='vlan'  |
    |                 | port_id='cb42940f-40c0-4e01-aa40-f3e9c5f6743f', segmentation_id='1924', segmentation_type='vlan' |
    |                 | port_id='52e52281-4692-45e9-935e-db77de44049a', segmentation_id='3866', segmentation_type='vlan' |
    |                 | port_id='1de77073-7127-4c39-a47b-cef15f98849c', segmentation_id='3934', segmentation_type='vlan' |
    | tags            | []                                                                                               |
    | tenant_id       | a05f6ec0abd04cba80cd160f8baaac99                                                                 |
    | updated_at      | 2017-08-29T06:19:28Z                                                                             |
    +-----------------+--------------------------------------------------------------------------------------------------+


We can see that now we have 7 subports, 3 of them attached to `trunk0` and 4
(1 + 3) attached to `trunk1`.

After that, if we create a new pod, we can see that the pre-created subports
are being used::

    $ kubectl create deployment demo --image=quay.io/kuryr/demo
    $ kubectl scale deploy/demo --replicas=2
    $ kubectl get pods
    NAME                    READY     STATUS    RESTARTS   AGE
    demo-2293951457-0l35q   1/1       Running   0          8s
    demo-2293951457-nlghf   1/1       Running   0          17s

    $ openstack port list | grep demo
    | 71245983-e15e-4ae8-9425-af255b54921b | demo-2293951457-0l35q | fa:16:3e:e5:2f:90 | ip_address='10.0.0.68', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |
    | b6a8aa34-feef-42d7-b7ce-f9c33ac499ca | demo-2293951457-nlghf | fa:16:3e:0c:8c:b0 | ip_address='10.0.0.65', subnet_id='c3a8feb0-62b5-4b53-9235-af1ca93c2571' | ACTIVE |


Free pools for nested environment
---------------------------------

In addition to the create subcommand, there is a `free` command available that
allows to either remove the available ports at a given pool (i.e., VM trunk),
or in all of them::

    $ python contrib/pools-management/subports.py free -h
    usage: subports.py free [-h] [--trunks SUBPORTS [SUBPORTS ...]] [-t TIMEOUT]

    optional arguments:
      -h, --help            show this help message and exit
      --trunks SUBPORTS [SUBPORTS ...]
                            list of trunk IPs where subports will be freed
      -t TIMEOUT, --timeout TIMEOUT
                            set timeout for operation. Default is 180 sec


Following from the previous example, we can remove the available-ports
attached to a give pool, e.g.::

    $ python contrib/pools-management/subports.py free --trunks 10.0.4.5
    $ openstack network trunk show trunk1
    +-----------------+--------------------------------------+
    | Field           | Value                                |
    +-----------------+--------------------------------------+
    | admin_state_up  | UP                                   |
    | created_at      | 2017-08-28T15:06:54Z                 |
    | description     |                                      |
    | id              | 9048c109-c1aa-4a41-9508-71b2ba98f3b0 |
    | name            | trunk1                               |
    | port_id         | 4180a2e5-e184-424a-93d4-54b48490f50d |
    | project_id      | a05f6ec0abd04cba80cd160f8baaac99     |
    | revision_number | 94                                   |
    | status          | ACTIVE                               |
    | sub_ports       |                                      |
    | tags            | []                                   |
    | tenant_id       | a05f6ec0abd04cba80cd160f8baaac99     |
    | updated_at      | 2017-08-29T06:40:18Z                 |
    +-----------------+--------------------------------------+


Or from all the pools at once::

    $ python contrib/pools-management/subports.py free
    $ openstack port list | grep available-port
    $ # returns nothing


List pools for nested environment
---------------------------------

There is a `list` command available to show information about the existing
pools, i.e., it prints out the pool keys (trunk_ip, project_id,
[security_groups]) and the amount of available ports in each one of them::

    $ python contrib/pools-management/subports.py list -h
    usage: subports.py list [-h] [-t TIMEOUT]

    optional arguments:
      -h, --help            show this help message and exit
      -t TIMEOUT, --timeout TIMEOUT
                            set timeout for operation. Default is 180 sec


As an example::

    $ python contrib/pools-management/subports.py list
    Content-length: 150

    Pools:
    ["10.0.0.6", "9d2b45c4efaa478481c30340b49fd4d2", ["00efc78c-f11c-414a-bfcd-a82e16dc07d1", "fd6b13dc-7230-4cbe-9237-36b4614bc6b5"]] has 4 ports


Show pool for nested environment
--------------------------------

There is a `show` command available to print out information about a given
pool. It prints the ids of the ports associated to that pool:::

    $ python contrib/pools-management/subports.py show -h
    usage: subports.py show [-h] --trunk TRUNK_IP -p PROJECT_ID --sg SG [SG ...]
                            [-t TIMEOUT]

    optional arguments:
      -h, --help            show this help message and exit
      --trunk TRUNK_IP      Trunk IP of the desired pool
      -p PROJECT_ID, --project-id PROJECT_ID
                            project id of the pool
      --sg SG [SG ...]      Security group ids of the pool
      -t TIMEOUT, --timeout TIMEOUT
                            set timeout for operation. Default is 180 sec

As an example::

    $ python contrib/pools-management/subports.py show --trunk 10.0.0.6 -p 9d2b45c4efaa478481c30340b49fd4d2 --sg 00efc78c-f11c-414a-bfcd-a82e16dc07d1 fd6b13dc-7230-4cbe-9237-36b4614bc6b5
    Content-length: 299

    Pool (u'10.0.0.6', u'9d2b45c4efaa478481c30340b49fd4d2', (u'00efc78c-f11c-414a-bfcd-a82e16dc07d1', u'fd6b13dc-7230-4cbe-9237-36b4614bc6b5')) ports are:
    4913fbde-5939-4aef-80c0-7fcca0348871
    864c8237-6ab4-4713-bec8-3d8bb6aa2144
    8138134b-44df-489c-a693-3defeb2adb58
    f5e107c6-f998-4416-8f17-a055269f2829


Without the script
------------------

Note the same can be done without using this script, by directly calling the
REST API with curl::

    # To populate the pool
    $ curl --unix-socket /run/kuryr/kuryr_manage.sock http://localhost/populatePool -H "Content-Type: application/json" -X POST -d '{"trunks": ["10.0.4.6"], "num_ports": 3}'

    # To free the pool
    $ curl --unix-socket /run/kuryr/kuryr_manage.sock http://localhost/freePool -H "Content-Type: application/json" -X POST -d '{"trunks": ["10.0.4.6"]}'

    # To list the existing pools
    $ curl --unix-socket /run/kuryr/kuryr_manage.sock http://localhost/listPools -H "Content-Type: application/json" -X GET -d '{}'

    # To show a specific pool
    $ curl --unix-socket /run/kuryr/kuryr_manage.sock http://localhost/showPool -H "Content-Type: application/json" -X GET -d '{"pool_key": ["10.0.0.6", "9d2b45c4efaa478481c30340b49fd4d2", ["00efc78c-f11c-414a-bfcd-a82e16dc07d1", "fd6b13dc-7230-4cbe-9237-36b4614bc6b5"]]}'
