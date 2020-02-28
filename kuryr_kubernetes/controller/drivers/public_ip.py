# Copyright (c) 2017 RedHat, Inc.
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
import abc

from openstack import exceptions as os_exc
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes.controller.drivers import utils

LOG = logging.getLogger(__name__)


class BasePubIpDriver(object, metaclass=abc.ABCMeta):
    """Base class for public IP functionality."""

    @abc.abstractmethod
    def is_ip_available(self, ip_addr, port_id_to_be_associated):
        """check availability of ip address

        :param ip_address:
        :param port_id_to_be_associated
        :returns res_id in case ip is available returns resources id else None

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def allocate_ip(self, pub_net_id, project_id, pub_subnet_id=None,
                    description=None, port_id_to_be_associated=None):
        """allocate ip address from public network id

        :param pub_net_id: public network id
        :param project_id:
        :param pub_subnet_id: public subnet id (Optional)
        :param description: string describing request (Optional)
        :param port_id_to_be_associated: (optional)
        :returns res_id , ip_addr
                :res_id - resource id
                :ip_addr - ip aaddress


        """
        raise NotImplementedError()

    @abc.abstractmethod
    def free_ip(self, res_id):
        """free ip by resource ID

        :param res_id: resource_id
        :returns True/False

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def associate(self, res_id, vip_port_id):
        """Associate VIP port id with resource_id

        :param res_id: id represents pub ip resource
        :param vip_port_id: VIP port id

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def disassociate(self, res_id):
        """Clear association between res_id to any vip port

        :param res_id: id represents pub ip resource

        """


class FipPubIpDriver(BasePubIpDriver):
    """Floating IP implementation for public IP capability ."""

    def is_ip_available(self, ip_addr, port_id_to_be_associated=None):
        if ip_addr:
            os_net = clients.get_network_client()
            floating_ips_list = os_net.ips(floating_ip_address=ip_addr)
            for entry in floating_ips_list:
                if not entry:
                    continue
                if (entry.floating_ip_address == ip_addr):
                    if not entry.port_id or (
                            port_id_to_be_associated is not None
                            and entry.port_id == port_id_to_be_associated):
                        return entry.id
            # floating IP not available
            LOG.error("Floating IP=%s not available", ip_addr)
        else:
            LOG.error("Invalid parameter ip_addr=%s", ip_addr)
        return None

    def allocate_ip(self, pub_net_id, project_id, pub_subnet_id=None,
                    description=None, port_id_to_be_associated=None):
        os_net = clients.get_network_client()

        if port_id_to_be_associated is not None:
            floating_ips_list = os_net.ips(
                port_id=port_id_to_be_associated)
            for entry in floating_ips_list:
                if not entry:
                    continue
                if (entry['floating_ip_address']):
                    LOG.debug('FIP %s already allocated to port %s',
                              entry['floating_ip_address'],
                              port_id_to_be_associated)
                    return entry['id'], entry['floating_ip_address']

        try:
            fip = os_net.create_ip(floating_network_id=pub_net_id,
                                   project_id=project_id,
                                   subnet_id=pub_subnet_id,
                                   description=description)
        except os_exc.SDKException:
            LOG.exception("Failed to create floating IP - netid=%s ",
                          pub_net_id)
            raise
        utils.tag_neutron_resources([fip])
        return fip.id, fip.floating_ip_address

    def free_ip(self, res_id):
        os_net = clients.get_network_client()
        try:
            os_net.delete_ip(res_id)
        except os_exc.SDKException:
            LOG.error("Failed to delete floating_ip_id =%s !", res_id)
            return False
        return True

    def _update(self, res_id, vip_port_id):
        response = None
        os_net = clients.get_network_client()
        try:
            response = os_net.update_ip(res_id, port_id=vip_port_id)
        except os_exc.ConflictException:
            LOG.warning("Conflict when assigning floating IP with id %s. "
                        "Checking if it's already assigned correctly.", res_id)
            try:
                fip = os_net.get_ip(res_id)
            except os_exc.NotFoundException:
                LOG.exception("Failed to get FIP %s - it doesn't exist.",
                              res_id)
                raise

            if fip.port_id == vip_port_id:
                LOG.debug('FIP %s already assigned to %s', res_id,
                          vip_port_id)
            else:
                LOG.exception('Failed to assign FIP %s to VIP port %s. It is '
                              'probably already bound', res_id, vip_port_id)
                raise
        except os_exc.SDKException:
            # NOTE(gryf): the response will be None, since in case of
            # exception, there will be no value assigned to response variable.
            LOG.error("Failed to update_ip, floating_ip_id=%s,"
                      "response=%s!", res_id, response)
            raise

    def associate(self, res_id, vip_port_id):
        self._update(res_id, vip_port_id)

    def disassociate(self, res_id):
        self._update(res_id, None)
