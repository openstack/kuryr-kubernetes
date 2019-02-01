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
from kuryr_kubernetes import config
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes.controller.drivers import public_ip
from kuryr_kubernetes.objects import lbaas as obj_lbaas
from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class FloatingIpServicePubIPDriver(base.ServicePubIpDriver):
    """Manages floating ip for neutron lbaas.

    Service loadbalancerIP support the following :
    1. No loadbalancer IP  - k8s service.spec.type != 'LoadBalancer'
    2. Floating IP allocated from pool  -
    k8s service.spec.type = 'LoadBalancer' and
    service.spec.loadBalancerIP NOT defined
    3. Floating IP specified by the user -
     k8s service.spec.type = 'LoadBalancer' and
      service.spec.loadBalancerIP is defined.
    """

    def __init__(self):
        super(FloatingIpServicePubIPDriver, self).__init__()
        self._drv_pub_ip = public_ip.FipPubIpDriver()

    def acquire_service_pub_ip_info(self, spec_type, spec_lb_ip, project_id,
                                    port_id_to_be_associated=None):

        if spec_type != 'LoadBalancer':
            return None

        if spec_lb_ip:
            user_specified_ip = spec_lb_ip.format()
            res_id = self._drv_pub_ip.is_ip_available(user_specified_ip,
                                                      port_id_to_be_associated)
            if res_id:
                service_pub_ip_info = (obj_lbaas.LBaaSPubIp(
                                       ip_id=res_id,
                                       ip_addr=str(user_specified_ip),
                                       alloc_method='user'))

                return service_pub_ip_info
            else:
                # user specified IP is not valid
                LOG.error("IP=%s is not available", user_specified_ip)
                return None
        else:
            LOG.debug("Trying to allocate public ip from pool")

        # get public network/subnet ids from kuryr.conf
        public_network_id = config.CONF.neutron_defaults.external_svc_net
        public_subnet_id = config.CONF.neutron_defaults.external_svc_subnet
        if not public_network_id:
            raise cfg.RequiredOptError('external_svc_net',
                                       cfg.OptGroup('neutron_defaults'))
        try:
            res_id, alloc_ip_addr = (self._drv_pub_ip.allocate_ip(
                public_network_id, project_id, pub_subnet_id=public_subnet_id,
                description='kuryr_lb',
                port_id_to_be_associated=port_id_to_be_associated))
        except Exception:
            LOG.exception("Failed to allocate public IP - net_id:%s",
                          public_network_id)
            return None
        service_pub_ip_info = obj_lbaas.LBaaSPubIp(ip_id=res_id,
                                                   ip_addr=alloc_ip_addr,
                                                   alloc_method='pool')

        return service_pub_ip_info

    def release_pub_ip(self, service_pub_ip_info):
        if not service_pub_ip_info:
            return True
        if service_pub_ip_info.alloc_method == 'pool':
            retcode = self._drv_pub_ip.free_ip(service_pub_ip_info.ip_id)
            if not retcode:
                LOG.error("Failed to delete public_ip_id =%s !",
                          service_pub_ip_info.ip_id)
                return False
        return True

    def associate_pub_ip(self, service_pub_ip_info, vip_port_id):
        if (not service_pub_ip_info or
                not vip_port_id or
                not service_pub_ip_info.ip_id):
            return
        self._drv_pub_ip.associate(
            service_pub_ip_info.ip_id, vip_port_id)

    def disassociate_pub_ip(self, service_pub_ip_info):
        if not service_pub_ip_info or not service_pub_ip_info.ip_id:
            return
        self._drv_pub_ip.disassociate(service_pub_ip_info.ip_id)
