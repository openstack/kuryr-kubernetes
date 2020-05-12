# Copyright (c) 2020 Samsung Electronics Co., Ltd.
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


import os.path
import stat

from os_vif.objects import fields as osv_fields
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from vif_plug_ovs import constants
from vif_plug_ovs import ovs

from kuryr_kubernetes.cni.binding import base
from kuryr_kubernetes import config
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import health

LOG = log.getLogger(__name__)


def _get_vhostuser_port_name(vif):
    return ovs.OvsPlugin.gen_port_name(constants.OVS_VHOSTUSER_PREFIX, vif.id)


def _get_vhu_sock(config_file_path):
    with open(config_file_path, 'r') as f:
        conf = jsonutils.load(f)
    return conf['vhostname']


def _check_sock_file(vhostuser_socket):
    mode = os.stat(vhostuser_socket).st_mode
    return stat.S_ISSOCK(mode)


class VIFVHostUserDriver(health.HealthHandler, base.BaseBindingDriver):

    def __init__(self):
        super(VIFVHostUserDriver, self).__init__()
        self.mount_path = config.CONF.vhostuser.mount_point
        self.ovs_vu_path = config.CONF.vhostuser.ovs_vhu_path
        if not self.mount_path:
            raise cfg.RequiredOptError('mount_point', 'vhostuser')

    def _write_config(self, container_id, ifname, port_name, vif):
        """Write vhostuser configuration file

        This function writes configuration file, this file will be used by
        application inside container and for cleanup (def disconnect)
        procedure.
        """
        vhost_conf = {}
        vhost_conf["vhostname"] = port_name
        vhost_conf["vhostmac"] = vif.address
        vhost_conf["mode"] = vif.mode
        with open(self._config_file_path(container_id, ifname), "w") as f:
            jsonutils.dump(vhost_conf, f)

    def _config_file_path(self, container_id, ifname):
        return os.path.join(self.mount_path, f'{container_id}-{ifname}')

    def connect(self, vif, ifname, netns, container_id):
        port_name = _get_vhostuser_port_name(vif)
        self._write_config(container_id, ifname, port_name, vif)
        # no need to copy in case of SERVER mode
        if vif.mode == osv_fields.VIFVHostUserMode.SERVER:
            return

        src_vhu_sock = os.path.join(self.ovs_vu_path, port_name)

        if _check_sock_file(src_vhu_sock):
            dst_vhu_sock = os.path.join(vif.path, port_name)
            LOG.debug("Moving %s to %s while processing VIF %s", src_vhu_sock,
                      dst_vhu_sock, vif.id)
            os.rename(src_vhu_sock, dst_vhu_sock)
        else:
            error_msg = ("Socket %s required for VIF %s doesn't exist" %
                         (src_vhu_sock, vif.id))
            LOG.error(error_msg)
            raise k_exc.CNIError(error_msg)

    def disconnect(self, vif, ifname, netns, container_id):
        # This function removes configuration file and appropriate
        # socket file. Unfortunatelly Open vSwitch daemon can't remove
        # moved socket, so we have to do it
        config_file_path = self._config_file_path(container_id, ifname)

        if not os.path.exists(config_file_path):
            LOG.warning("Configuration file: %s for VIF %s doesn't exist!",
                        config_file_path, vif.id)
            return
        vhu_sock_path = os.path.join(self.mount_path,
                                     _get_vhu_sock(config_file_path))
        LOG.debug("remove: %s, %s", config_file_path, vhu_sock_path)
        try:
            os.remove(vhu_sock_path)
        except Exception:
            LOG.exception("Failed to delete socket %s when processing VIF %s.",
                          vhu_sock_path, vif.id)
        os.remove(config_file_path)

    def is_alive(self):
        healthy = False
        try:
            healthy = (os.path.exists(self.ovs_vu_path)
                       and os.path.exists(self.mount_path))
        except Exception:
            LOG.exception('Error when determining health status of vhostuser '
                          'CNI driver.')

        if not healthy:
            LOG.error('Directory %s or %s does not exist or Kuryr has no '
                      'permissions to access it. Marking vhostuser binding '
                      'driver as unhealthy.', self.ovs_vu_path,
                      self.mount_path)

        return healthy
