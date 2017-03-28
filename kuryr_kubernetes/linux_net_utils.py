# Derived from nova/network/linux_net.py
#
# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

""" Implements linux net utils"""

from oslo_concurrency import processutils
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


def _ovs_vsctl(args, timeout=None):
    full_args = ['ovs-vsctl']
    if timeout is not None:
        full_args += ['--timeout=%s' % timeout]
    full_args += args
    try:
        return processutils.execute(*full_args, run_as_root=True)
    except Exception as e:
        LOG.error("Unable to execute %(cmd)s. Exception: %(exception)s",
                  {'cmd': full_args, 'exception': e})
        raise


def _create_ovs_vif_cmd(bridge, dev, iface_id, mac, instance_id):
    cmd = ['--', '--if-exists', 'del-port', dev, '--',
           'add-port', bridge, dev,
           '--', 'set', 'Interface', dev,
           'external-ids:iface-id=%s' % iface_id,
           'external-ids:iface-status=active',
           'external-ids:attached-mac=%s' % mac,
           'external-ids:vm-uuid=%s' % instance_id]
    return cmd


def create_ovs_vif_port(bridge, dev, iface_id, mac, instance_id):
    _ovs_vsctl(_create_ovs_vif_cmd(bridge, dev, iface_id, mac, instance_id))


def delete_ovs_vif_port(bridge, dev):
    _ovs_vsctl(['--', '--if-exists', 'del-port', bridge, dev])
