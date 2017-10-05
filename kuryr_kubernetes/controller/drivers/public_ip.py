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
from kuryr_kubernetes import clients
from neutronclient.common import exceptions as n_exc
from oslo_log import log as logging
import six

LOG = logging.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class BasePubIpDriver(object):
    """Base class for public IP functionality."""

    @abc.abstractmethod
    def is_ip_available(self, ip_addr):
        """check availability of ip address

        :param ip_address:
        :returns res_id in case ip is available returns resources id else None

        """
        raise NotImplementedError()

    @abc.abstractmethod
    def allocate_ip(self, pub_net_id, pub_subnet_id, project_id, description):
        """allocate ip address from public network id

        :param pub_net_id: public network id
        :param pub_subnet_id: public subnet id
        :param project_id:
        :param description: string describing request
        :returns res_id , ip_addr
                :res_id - resource id
                :ip_addr - ip aaddress


        """
        raise NotImplementedError()

    @abc.abstractmethod
    def free_ip(self, res_id):
        """free ip by resource ID

        :param res_id: resource_id

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

    def is_ip_available(self, ip_addr):
        if ip_addr:
            neutron = clients.get_neutron_client()
            floating_ips_list = neutron.list_floatingips(
                floating_ip_address=ip_addr)
            for entry in floating_ips_list['floatingips']:
                if not entry:
                    continue
                if (entry['floating_ip_address'] == ip_addr and
                        not entry['port_id']):
                    return entry['id']
            # floating IP not available
            LOG.error("Floating IP=%s not available", ip_addr)
        else:
            LOG.error("Invalid parameter ip_addr=%s", ip_addr)
        return None

    def allocate_ip(self, pub_net_id, pub_subnet_id, project_id, description):

        neutron = clients.get_neutron_client()
        try:
            response = neutron.create_floatingip({'floatingip': {
                'tenant_id': project_id,
                'project_id': project_id,
                'floating_network_id': pub_net_id,
                'subnet_id': pub_subnet_id,
                'description': description}})
        except n_exc.NeutronClientException as ex:
            LOG.error("Failed to create floating IP - subnetid=%s ",
                      pub_subnet_id)
            raise ex
        return response['floatingip']['id'], response[
            'floatingip']['floating_ip_address']

    def free_ip(self, res_id):
        neutron = clients.get_neutron_client()
        try:
            neutron.delete_floatingip(res_id)
        except n_exc.NeutronClientException as ex:
            LOG.error("Failed to delete floating_ip_id =%s !",
                      res_id)
            raise ex

    def _update(self, res_id, vip_port_id):
        response = None
        neutron = clients.get_neutron_client()
        try:
            response = neutron.update_floatingip(
                res_id, {'floatingip': {'port_id': vip_port_id, }})
        except n_exc.NeutronClientException as ex:
            LOG.error("Failed to update_floatingip ,floating_ip_id=%s,"
                      "response=%s!", res_id, response)
            raise ex

    def associate(self, res_id, vip_port_id):
        self._update(res_id, vip_port_id)

    def disassociate(self, res_id):
        self._update(res_id, None)
