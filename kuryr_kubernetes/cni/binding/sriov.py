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

import collections
import os

from kuryr.lib._i18n import _
from oslo_concurrency import lockutils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes.cni.binding import base as b_base
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class VIFSriovDriver(object):
    def __init__(self):
        self._lock = None
        self._device_pf_mapping = self._get_device_pf_mapping()

    def release_lock_object(func):
        def wrapped(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            finally:
                if self._lock and self._lock.acquired:
                    self._lock.release()
        return wrapped

    @release_lock_object
    def connect(self, vif, ifname, netns, container_id):
        pci_info = self._process_vif(vif, ifname, netns)
        self._save_pci_info(vif.id, pci_info)

    def disconnect(self, vif, ifname, netns, container_id):
        # NOTE(k.zaitsev): when netns is deleted the interface is
        # returned automatically to host netns. We may reset
        # it to all-zero state
        self._return_device_driver(vif)
        self._remove_pci_info(vif.id)

    def _process_vif(self, vif, ifname, netns):
        pr_client = clients.get_pod_resources_client()
        pod_resources_list = pr_client.list()
        resources = pod_resources_list.pod_resources
        pod_name = vif.pod_name
        pod_link = vif.pod_link
        physnet = vif.physnet
        resource_name = self._get_resource_by_physnet(physnet)
        driver = self._get_driver_by_res(resource_name)
        resource = self._make_resource(resource_name)
        LOG.debug("Vif %s will correspond to pci device belonging to "
                  "resource %s", vif, resource)
        pod_devices = self._get_pod_devices(pod_link)
        pod_resource = None
        container_devices = None
        for res in resources:
            if res.name == pod_name:
                pod_resource = res
                break
        if not pod_resource:
            raise exceptions.CNIError(
                "No resources are discovered for pod {}".format(pod_name))
        LOG.debug("Looking for PCI device used by kubelet service and not "
                  "used by pod %s yet ...", pod_name)
        for container in pod_resource.containers:
            try:
                container_devices = container.devices
            except Exception:
                LOG.warning("No devices in container %s",
                            container.name)
                continue

            for dev in container_devices:
                if dev.resource_name != resource:
                    continue

                for pci in dev.device_ids:
                    if pci in pod_devices:
                        continue
                    LOG.debug("Appropriate PCI device %s is found", pci)
                    pci_info = self._compute_pci(pci, driver,
                                                 pod_link, vif,
                                                 ifname, netns)
                    return pci_info

    def _get_resource_by_physnet(self, physnet):
        mapping = config.CONF.sriov.physnet_resource_mappings
        try:
            resource_name = mapping[physnet]
        except KeyError:
            LOG.exception("No resource name for physnet %s", physnet)
            raise
        return resource_name

    def _make_resource(self, res_name):
        res_prefix = config.CONF.sriov.device_plugin_resource_prefix
        return res_prefix + '/' + res_name

    def _get_driver_by_res(self, resource_name):
        mapping = config.CONF.sriov.resource_driver_mappings
        try:
            driver = mapping[resource_name]
        except KeyError:
            LOG.exception("No driver for resource_name %s", resource_name)
            raise
        return driver

    def _compute_pci(self, pci, driver, pod_link, vif, ifname, netns):
        port_id = vif.id
        vf_name, vf_index, pf, pci_info = self._get_vf_info(pci, driver)
        if driver in constants.USERSPACE_DRIVERS:
            LOG.info("PCI device %s will be rebinded to userspace network "
                     "driver %s", pci, driver)
            self._set_vf_mac(pf, vf_index, vif.address)
            if vif.network.should_provide_vlan:
                vlan_id = vif.network.vlan
                self._set_vf_vlan(pf, vf_index, vlan_id)
            old_driver = self._bind_device(pci, driver)
            self._annotate_device(pod_link, pci, old_driver, driver, port_id)
        else:
            LOG.info("PCI device %s will be moved to container's net ns %s",
                     pci, netns)
            pci_info = self._move_to_netns(pci, ifname, netns, vif, vf_name,
                                           vf_index, pf, pci_info)
            self._annotate_device(pod_link, pci, driver, driver, port_id)
        return pci_info

    def _move_to_netns(self, pci, ifname, netns, vif, vf_name, vf_index, pf,
                       pci_info):
        if vif.network.should_provide_vlan:
            vlan_id = vif.network.vlan
            self._set_vf_vlan(pf, vf_index, vlan_id)

        self._set_vf_mac(pf, vf_index, vif.address)

        with b_base.get_ipdb() as h_ipdb, b_base.get_ipdb(netns) as c_ipdb:
            with h_ipdb.interfaces[vf_name] as host_iface:
                host_iface.net_ns_fd = utils.convert_netns(netns)

            with c_ipdb.interfaces[vf_name] as iface:
                iface.ifname = ifname
                iface.mtu = vif.network.mtu
                iface.up()

        return pci_info

    def _get_vf_info(self, pci, driver):
        vf_sys_path = '/sys/bus/pci/devices/{}/net/'.format(pci)
        if not os.path.exists(vf_sys_path):
            if driver not in constants.USERSPACE_DRIVERS:
                raise OSError(_("No vf name for device {}").format(pci))
            vf_name = None
        else:
            vf_names = os.listdir(vf_sys_path)
            vf_name = vf_names[0]

        pfysfn_path = '/sys/bus/pci/devices/{}/physfn/net/'.format(pci)
        pf_names = os.listdir(pfysfn_path)
        pf_name = pf_names[0]

        nvfs = self._get_total_vfs(pf_name)
        pf_sys_path = '/sys/class/net/{}/device'.format(pf_name)
        for vf_index in range(nvfs):
            virtfn_path = os.path.join(pf_sys_path,
                                       'virtfn{}'.format(vf_index))
            vf_pci = os.path.basename(os.readlink(virtfn_path))
            if vf_pci == pci:
                pci_info = self._get_pci_info(pf_name, vf_index)
                return vf_name, vf_index, pf_name, pci_info
        return None, None, None, None

    def _bind_device(self, pci, driver, old_driver=None):
        if not old_driver:
            old_driver_path = '/sys/bus/pci/devices/{}/driver'.format(pci)
            old_driver_link = os.readlink(old_driver_path)
            old_driver = os.path.basename(old_driver_link)
        unbind_path = '/sys/bus/pci/drivers/{}/unbind'.format(old_driver)
        bind_path = '/sys/bus/pci/drivers/{}/bind'.format(driver)

        with open(unbind_path, 'w') as unbind_fd:
            unbind_fd.write(pci)

        owerride = "/sys/bus/pci/devices/{}/driver_override".format(pci)
        with open(owerride, 'w') as owerride_fd:
            owerride_fd.write("\00")

        with open(owerride, 'w') as owerride_fd:
            owerride_fd.write(driver)

        with open(bind_path, 'w') as bind_fd:
            bind_fd.write(pci)

        LOG.info("Device %s was binded on driver %s. Old driver is %s", pci,
                 driver, old_driver)
        return old_driver

    def _annotate_device(self, pod_link, pci, old_driver, new_driver, port_id):
        old_driver_title = constants.K8S_ANNOTATION_OLD_DRIVER
        current_driver_title = constants.K8S_ANNOTATION_CURRENT_DRIVER
        neutron_port_title = constants.K8S_ANNOTATION_NEUTRON_PORT
        k8s = clients.get_kubernetes_client()
        pod_devices = self._get_pod_devices(pod_link)
        pod_devices[pci] = {old_driver_title: old_driver,
                            current_driver_title: new_driver,
                            neutron_port_title: port_id}
        pod_devices = jsonutils.dumps(pod_devices)

        LOG.debug("Trying to annotate pod %s with pci %s, old driver %s "
                  "and new driver %s", pod_link, pci, old_driver, new_driver)
        k8s.annotate(pod_link,
                     {constants.K8S_ANNOTATION_PCI_DEVICES: pod_devices})

    def _get_pod_devices(self, pod_link):
        k8s = clients.get_kubernetes_client()
        pod = k8s.get(pod_link)
        annotations = pod['metadata']['annotations']
        try:
            json_devices = annotations[constants.K8S_ANNOTATION_PCI_DEVICES]
            devices = jsonutils.loads(json_devices)
        except KeyError:
            devices = {}
        except Exception as ex:
            LOG.exception("Exception while getting annotations: %s", ex)
        LOG.debug("Pod %s has devies %s", pod_link, devices)
        return devices

    def _return_device_driver(self, vif):
        neutron_port_title = constants.K8S_ANNOTATION_NEUTRON_PORT
        old_driver_title = constants.K8S_ANNOTATION_OLD_DRIVER
        current_driver_title = constants.K8S_ANNOTATION_CURRENT_DRIVER
        if not hasattr(vif, 'pod_link'):
            return
        pod_link = vif.pod_link
        pod_devices = self._get_pod_devices(pod_link)
        for pci, info in pod_devices.items():
            if info[neutron_port_title] == vif.id:
                if info[old_driver_title] != info[current_driver_title]:
                    LOG.debug("Driver of device %s should be changed back",
                              pci)
                    self._bind_device(pci,
                                      info[old_driver_title],
                                      info[current_driver_title])

    def _get_pci_info(self, pf, vf_index):
        pci_slot = ''
        physnet = ''
        pci_vendor_info = ''

        vendor_path = '/sys/class/net/{}/device/virtfn{}/vendor'.format(
            pf, vf_index)
        with open(vendor_path) as vendor_file:
            vendor_full = vendor_file.read()
            vendor = vendor_full.split('x')[1].strip()
        device_path = '/sys/class/net/{}/device/virtfn{}/device'.format(
            pf, vf_index)
        with open(device_path) as device_file:
            device_full = device_file.read()
            device = device_full.split('x')[1].strip()
        pci_vendor_info = '{}:{}'.format(vendor, device)

        vf_path = '/sys/class/net/{}/device/virtfn{}'.format(
            pf, vf_index)
        pci_slot_path = os.readlink(vf_path)
        pci_slot = pci_slot_path.split('/')[1]

        physnet = self._get_physnet_by_pf(pf)

        return {'pci_slot': pci_slot,
                'physical_network': physnet,
                'pci_vendor_info': pci_vendor_info}

    def _get_physnet_by_pf(self, desired_pf):
        for physnet, pf_list in self._device_pf_mapping.items():
            for pf in pf_list:
                if pf == desired_pf:
                    return physnet
        LOG.exception("Unable to find physnet for pf %s", desired_pf)
        raise

    def _save_pci_info(self, neutron_port, port_pci_info):
        k8s = clients.get_kubernetes_client()
        annot_name = constants.K8S_ANNOTATION_NODE_PCI_DEVICE_INFO
        annot_name = annot_name.replace('/', '~1')
        annot_name = annot_name + '-' + neutron_port
        LOG.info('annot_name = %s', annot_name)
        nodename = utils.get_node_name()

        LOG.info("Trying to annotate node %s with pci info %s",
                 nodename, port_pci_info)
        k8s.patch_node_annotations(nodename, annot_name, port_pci_info)

    def _remove_pci_info(self, neutron_port):
        k8s = clients.get_kubernetes_client()
        annot_name = constants.K8S_ANNOTATION_NODE_PCI_DEVICE_INFO
        annot_name = annot_name.replace('/', '~1')
        annot_name = annot_name + '-' + neutron_port
        LOG.info('annot_name = %s', annot_name)
        nodename = utils.get_node_name()

        LOG.info("Trying to delete pci info for port %s on node %s",
                 neutron_port, nodename)
        k8s.remove_node_annotations(nodename, annot_name)

    def _acquire(self, path):
        if self._lock and self._lock.acquired:
            raise RuntimeError(_("Attempting to lock {} when {} "
                               "is already locked.").format(path, self._lock))
        self._lock = lockutils.InterProcessLock(path=path)
        return self._lock.acquire()

    def _release(self):
        if not self._lock:
            raise RuntimeError(_("Attempting release an empty lock"))
        return self._lock.release()

    def _get_total_vfs(self, pf):
        """Read /sys information for configured number of VFs of a PF"""

        pf_sys_path = '/sys/class/net/{}/device'.format(pf)
        total_fname = os.path.join(pf_sys_path, 'sriov_numvfs')
        try:
            with open(total_fname) as total_f:
                data = total_f.read()
        except IOError:
            LOG.warning("Could not open %s. No VFs for %s", total_fname, pf)
            return 0
        nvfs = 0
        try:
            nvfs = int(data.strip())
        except ValueError:
            LOG.warning("Could not parse %s from %s. No VFs for %s", data,
                        total_fname, pf)
            return 0
        LOG.debug("PF %s has %s VFs", pf, nvfs)
        return nvfs

    def _set_vf_mac(self, pf, vf_index, mac):
        """Call `ip link set enp2s0f1 vf 3 mac fa:16:3e:87:b2:ac`"""

        LOG.debug("Seting VF MAC: pf = %s, vf_index = %s, mac = %s",
                  pf, vf_index, mac)
        cmd = [
            'ip', 'link',
            'set', pf, 'vf', vf_index, 'mac', mac
        ]
        try:
            return processutils.execute(*cmd, run_as_root=True)
        except Exception:
            LOG.exception("Unable to execute %s", cmd)
            raise

    def _set_vf_vlan(self, pf, vf_index, vlan_id):
        """Call `ip link set enp1s0f0 vf 5 vlan 10`"""
        cmd = [
            'ip', 'link',
            'set', pf, 'vf', vf_index, 'vlan', vlan_id
        ]
        try:
            return processutils.execute(*cmd, run_as_root=True)
        except Exception:
            LOG.exception("Unable to execute %s", cmd)
            raise

    def is_alive(self):
        bridge_name = CONF.neutron_defaults.ovs_bridge
        try:
            with b_base.get_ipdb() as h_ipdb:
                h_ipdb.interfaces[bridge_name]
            return True
        except Exception:
            LOG.warning("Default OVS bridge %s does not exist on "
                        "the host.", bridge_name)
            return False

    def _get_device_pf_mapping(self):
        """Return a mapping in format {<physnet_name>:[<pf_name>, ...]}"""

        phys_mappings = config.CONF.sriov.physical_device_mappings
        physnets = collections.defaultdict(list)
        for phys_map in phys_mappings:
            try:
                netname, ifname = phys_map.split(':', 1)
            except ValueError:
                raise cfg.Error(
                    "Invalid mapping {}".format(phys_map))
            physnets[netname].append(ifname)
        return physnets
