# Copyright (C) 2020 Intel Corporation
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

import os

from os_vif import objects
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes import constants
from kuryr_kubernetes.handlers import health

from kuryr.lib._i18n import _


LOG = logging.getLogger(__name__)
CONF = cfg.CONF

NET_DEV_PATH = "/sys/class/net/{}/device"
VIRTIO_DEVS_PATH = "/sys/bus/virtio/devices"
PCI_PATH = "/sys/bus/pci/devices"
PCI_DRVS_PATH = "/sys/bus/pci/drivers"


# TODO(garyloug) These should probably eventually move to config.py
# TODO(garyloug) Would be nice if dpdk_driver is set as CNI arg
nested_dpdk_opts = [
    cfg.StrOpt('dpdk_driver',
               help=_('The DPDK driver that the device will be bound to after '
                      'it is unbound from the kernel driver'),
               default='uio_pci_generic'),
    cfg.StrOpt('pci_mount_point',
               help=_('Absolute path to directory containing pci address of '
                      'devices to be used by DPDK application'),
               default='/var/pci_address'),
]

CONF.register_opts(nested_dpdk_opts, "nested_dpdk")


class DpdkDriver(health.HealthHandler, b_base.BaseBindingDriver):

    def __init__(self):
        super(DpdkDriver, self).__init__()

    def connect(self, vif, ifname, netns, container_id):
        name = self._get_iface_name_by_mac(vif.address)
        driver, pci_addr = self._get_device_info(name)

        vif.dev_driver = driver
        vif.pci_address = pci_addr
        dpdk_driver = CONF.nested_dpdk.dpdk_driver
        self._change_driver_binding(pci_addr, dpdk_driver)
        self._create_pci_file(pci_addr, container_id, ifname)
        self._set_vif(vif)

    def disconnect(self, vif, ifname, netns, container_id):
        self._remove_pci_file(container_id, ifname)

    def _get_iface_name_by_mac(self, mac_address):
        with b_base.get_ipdb() as h_ipdb:
            for name, data in h_ipdb.interfaces.items():
                if data['address'] == mac_address:
                    return data['ifname']

    def _get_device_info(self, ifname):
        """Get driver and PCI addr by using sysfs"""

        # TODO(garyloug): check the type (virtio)
        dev = os.path.basename(os.readlink(NET_DEV_PATH.format(ifname)))
        pci_link = os.readlink(os.path.join(VIRTIO_DEVS_PATH, dev))
        pci_addr = os.path.basename(os.path.dirname(pci_link))
        pci_driver_link = os.readlink(os.path.join(PCI_PATH, pci_addr,
                                                   'driver'))
        pci_driver = os.path.basename(pci_driver_link)

        return pci_driver, pci_addr

    def _change_driver_binding(self, pci, driver):
        old_driver_path = os.path.join(PCI_PATH, pci, 'driver')
        old_driver_link = os.readlink(old_driver_path)
        old_driver = os.path.basename(old_driver_link)

        unbind_path = os.path.join(PCI_DRVS_PATH, old_driver, 'unbind')
        bind_path = os.path.join(PCI_DRVS_PATH, driver, 'bind')

        with open(unbind_path, 'w') as unbind_fd:
            unbind_fd.write(pci)

        override = os.path.join(PCI_PATH, pci, 'driver_override')
        # NOTE(danil): to change driver for device it is necessary to
        # write the name of this driver into override_fd. Before that
        # Null should be written there. This process is described properly
        # in dpdk-devbind.py script by DPDK
        with open(override, 'w') as override_fd:
            override_fd.write("\00")

        with open(override, 'w') as override_fd:
            override_fd.write(driver)

        with open(bind_path, 'w') as bind_fd:
            bind_fd.write(pci)

        LOG.info("Device %s was binded on driver %s. Old driver is %s", pci,
                 driver, old_driver)

    def _create_pci_file(self, pci_addr, container_id, ifname):
        # NOTE(danil): writing used pci addresses is necessary to know what
        # device to use by dpdk applications inside containers
        try:
            os.makedirs(CONF.nested_dpdk.pci_mount_point, exists_ok=True)
            file_path = os.path.join(CONF.nested_dpdk.pci_mount_point,
                                     container_id + '-' + ifname)
            with open(file_path, 'w') as fd:
                fd.write(pci_addr)
        except OSError as err:
            LOG.exception('Cannot create file %s. Error message: (%d) %s',
                          file_path, err.errno, err.strerror)

    def _remove_pci_file(self, container_id, ifname):
        file_path = os.path.join(CONF.nested_dpdk.pci_mount_point,
                                 container_id + '-' + ifname)
        try:
            os.remove(file_path)
        except OSError as err:
            LOG.warning('Cannot remove file %s. Error message: (%d) %s',
                        file_path, err.errno, err.strerror)

    def _set_vif(self, vif):
        # TODO(ivc): extract annotation interactions
        vifs, labels, resource_version, kp_link = self._get_pod_details(
            vif.port_profile.selflink)
        for ifname, data in vifs.items():
            if vif.id == data['vif'].id:
                vifs[ifname] = data
                break
        self._set_pod_details(vifs, vif.port_profile.selflink, labels,
                              resource_version, kp_link)

    def _get_pod_details(self, selflink):
        k8s = clients.get_kubernetes_client()
        pod = k8s.get(selflink)
        kp = k8s.get(f'{constants.K8S_API_CRD_NAMESPACES}/'
                     f'{pod["metadata"]["namespace"]}/kuryrports/'
                     f'{pod["metadata"]["name"]}')

        try:
            vifs = {k: {'default': v['default'],
                        'vif': objects.base.VersionedObject
                        .obj_from_primitive(v['vif'])}
                    for k, v in kp['status']['vifs'].items()}
        except (KeyError, AttributeError):
            LOG.exception(f"No vifs found on KuryrPort: {kp}")
            raise
        LOG.info(f"Got VIFs from Kuryrport: {vifs}")

        resource_version = pod['metadata']['resourceVersion']
        labels = pod['metadata'].get('labels')
        return vifs, labels, resource_version, kp['metadata']['selflink']

    def _set_pod_details(self, vifs, selflink, labels, resource_version,
                         kp_link):
        k8s = clients.get_kubernetes_client()
        if vifs:
            vif_dict = {k: {'default': v['default'],
                            'vif': v['vif'].obj_to_primitive()}
                        for k, v in vifs.items()}

            LOG.info("Setting VIFs in KuryrPort %r", vif_dict)
            k8s.patch_crd('status', kp_link, {'vifs': vif_dict})

        if not labels:
            LOG.info("Removing Label annotation: %r", labels)
            labels_annotation = None
        else:
            labels_annotation = jsonutils.dumps(labels, sort_keys=True)
            LOG.info("Setting Labels annotation: %r", labels_annotation)

        k8s.annotate(selflink,
                     {constants.K8S_ANNOTATION_LABEL: labels_annotation},
                     resource_version=resource_version)
