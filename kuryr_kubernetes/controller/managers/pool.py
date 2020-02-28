# Copyright 2017 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from http import server
import os
import socketserver
import threading


from openstack import exceptions as os_exc
from oslo_config import cfg as oslo_cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr.lib._i18n import _

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers

LOG = logging.getLogger(__name__)

pool_manager_opts = [
    oslo_cfg.StrOpt('sock_file',
                    help=_("Absolute path to socket file that "
                           "will be used for communication with "
                           "the Pool Manager daemon"),
                    default='/run/kuryr/kuryr_manage.sock'),
]

oslo_cfg.CONF.register_opts(pool_manager_opts, "pool_manager")


class UnixDomainHttpServer(socketserver.ThreadingUnixStreamServer):
    pass


class RequestHandler(server.BaseHTTPRequestHandler):
    protocol = "HTTP/1.0"

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))

        body = self.rfile.read(content_length)
        params = dict(jsonutils.loads(body))

        if self.path.endswith(constants.VIF_POOL_POPULATE):
            trunk_ips = params.get('trunks', None)
            num_ports = params.get('num_ports', 1)
            if trunk_ips:
                try:
                    self._create_subports(num_ports, trunk_ips)
                except Exception:
                    response = ('Error while populating pool {0} with {1} '
                                'ports.'.format(trunk_ips, num_ports))
                else:
                    response = ('Ports pool at {0} was populated with {1} '
                                'ports.'.format(trunk_ips, num_ports))

                self.send_header('Content-Length', len(response))
                self.end_headers()
                self.wfile.write(response.encode())
            else:
                response = 'Trunk port IP(s) missing.'
                self.send_header('Content-Length', len(response))
                self.end_headers()
                self.wfile.write(response.encode())

        elif self.path.endswith(constants.VIF_POOL_FREE):
            trunk_ips = params.get('trunks', None)
            if not trunk_ips:
                pool = "all"
            else:
                pool = trunk_ips

            try:
                self._delete_subports(trunk_ips)
            except Exception:
                response = 'Error freeing ports pool: {0}.'.format(pool)
            else:
                response = 'Ports pool belonging to {0} was freed.'.format(
                    pool)

            self.send_header('Content-Length', len(response))
            self.end_headers()
            self.wfile.write(response.encode())

        else:
            response = 'Method not allowed.'
            self.send_header('Content-Length', len(response))
            self.end_headers()
            self.wfile.write(response.encode())

    def do_GET(self):
        content_length = int(self.headers.get('Content-Length', 0))

        body = self.rfile.read(content_length)
        params = dict(jsonutils.loads(body))

        if self.path.endswith(constants.VIF_POOL_LIST):
            try:
                pools_info = self._list_pools()
            except Exception:
                response = 'Error listing the pools.'
            else:
                response = 'Pools:\n{0}'.format(pools_info)

            self.send_header('Content-Length', len(response))
            self.end_headers()
            self.wfile.write(response.encode())

        elif self.path.endswith(constants.VIF_POOL_SHOW):
            raw_key = params.get('pool_key', None)
            if len(raw_key) != 3:
                response = ('Invalid pool key. Proper format is:\n'
                            '[trunk_ip, project_id, [security_groups]]\n')
            else:
                pool_key = (raw_key[0], raw_key[1], tuple(sorted(raw_key[2])))

                try:
                    pool_info = self._show_pool(pool_key)
                except Exception:
                    response = 'Error showing pool: {0}.'.format(pool_key)
                else:
                    response = 'Pool {0} ports are:\n{1}'.format(pool_key,
                                                                 pool_info)

            self.send_header('Content-Length', len(response))
            self.end_headers()
            self.wfile.write(response.encode())

        else:
            response = 'Method not allowed.'
            self.send_header('Content-Length', len(response))
            self.end_headers()
            self.wfile.write(response.encode())

    def _create_subports(self, num_ports, trunk_ips):
        try:
            drv_project = drivers.PodProjectDriver.get_instance()
            drv_subnets = drivers.PodSubnetsDriver.get_instance()
            drv_sg = drivers.PodSecurityGroupsDriver.get_instance()
            drv_vif = drivers.PodVIFDriver.get_instance()
            drv_vif_pool = drivers.VIFPoolDriver.get_instance()
            drv_vif_pool.set_vif_driver(drv_vif)
            project_id = drv_project.get_project({})
            security_groups = drv_sg.get_security_groups({}, project_id)
            subnets = drv_subnets.get_subnets([], project_id)
        except TypeError:
            LOG.error("Invalid driver type")
            raise

        for trunk_ip in trunk_ips:
            try:
                drv_vif_pool.force_populate_pool(
                    trunk_ip, project_id, subnets, security_groups, num_ports)
            except os_exc.ConflictException:
                LOG.error("VLAN Id conflict (already in use) at trunk %s",
                          trunk_ip)
                raise
            except os_exc.SDKException:
                LOG.exception("Error happened during subports addition at "
                              "trunk: %s", trunk_ip)
                raise

    def _delete_subports(self, trunk_ips):
        try:
            drv_vif = drivers.PodVIFDriver.get_instance()
            drv_vif_pool = drivers.VIFPoolDriver.get_instance()
            drv_vif_pool.set_vif_driver(drv_vif)

            drv_vif_pool.free_pool(trunk_ips)
        except TypeError:
            LOG.error("Invalid driver type")
            raise

    def _list_pools(self):
        try:
            drv_vif = drivers.PodVIFDriver.get_instance()
            drv_vif_pool = drivers.VIFPoolDriver.get_instance()
            drv_vif_pool.set_vif_driver(drv_vif)

            available_pools = drv_vif_pool.list_pools()
        except TypeError:
            LOG.error("Invalid driver type")
            raise

        pools_info = ""
        for pool_key, pool_items in available_pools.items():
            pools_info += (jsonutils.dumps(pool_key) + " has "
                           + str(len(pool_items)) + " ports\n")
        if pools_info:
            return pools_info
        return "There are no pools"

    def _show_pool(self, pool_key):
        try:
            drv_vif = drivers.PodVIFDriver.get_instance()
            drv_vif_pool = drivers.VIFPoolDriver.get_instance()
            drv_vif_pool.set_vif_driver(drv_vif)

            pool = drv_vif_pool.show_pool(pool_key)
        except TypeError:
            LOG.error("Invalid driver type")
            raise

        if pool:
            pool_info = ""
            for pool_id in pool:
                pool_info += str(pool_id) + "\n"
            return pool_info
        else:
            return "Empty pool"


class PoolManager(object):
    """Manages the ports pool enabling population and free actions.

    `PoolManager` runs on the Kuryr-kubernetes controller and allows  to
    populate specific pools with a given amount of ports. In addition, it also
    allows to remove all the (unused) ports in the given pool(s), or from all
    of the pool if none of them is specified.
    """

    def __init__(self):
        pool_manager = threading.Thread(target=self._start_kuryr_manage_daemon)
        pool_manager.setDaemon(True)
        pool_manager.start()

    def _start_kuryr_manage_daemon(self):
        LOG.info("Pool manager started")
        server_address = oslo_cfg.CONF.pool_manager.sock_file
        try:
            os.unlink(server_address)
        except OSError:
            if os.path.exists(server_address):
                raise
        try:
            httpd = UnixDomainHttpServer(server_address, RequestHandler)
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        except Exception:
            LOG.exception('Failed to start Pool Manager.')
        httpd.socket.close()
