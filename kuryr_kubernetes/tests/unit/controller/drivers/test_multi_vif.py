# Copyright 2018 Red Hat, Inc.
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

from unittest import mock

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base as drivers
from kuryr_kubernetes.controller.drivers import multi_vif
from kuryr_kubernetes import exceptions
from kuryr_kubernetes.tests import base as test_base
from oslo_serialization import jsonutils


def get_pod_obj():
    return {
        'status': {
            'qosClass': 'BestEffort',
            'hostIP': '192.168.1.2',
        },
        'kind': 'Pod',
        'spec': {
            'schedulerName': 'default-scheduler',
            'containers': [{
                'name': 'busybox',
                'image': 'busybox',
                'resources': {}
            }],
            'nodeName': 'kuryr-devstack'
        },
        'metadata': {
            'name': 'busybox-sleep1',
            'namespace': 'default',
            'resourceVersion': '53808',
            'uid': '452176db-4a85-11e7-80bd-fa163e29dbbb',
            'annotations': {
                'openstack.org/kuryr-vif': {},
                'k8s.v1.cni.cncf.io/networks':
                    "net-a,net-b,other-ns/net-c"
            }
        }
    }


def get_nets():
    return [
        {"name": "net-a"},
        {"name": "net-b"},
        {
            "name": "net-c",
            "namespace": "other-ns"
        }
    ]


def get_crd_objs():
    return [
        {
            'name': 'net-a',
            'metadata': {
                'annotations': {
                    'openstack.org/kuryr-config':
                        '''{"subnetId": "subnet-a"}'''
                }
            }
        },
        {
            'name': 'net-b',
            'metadata': {
                'annotations': {
                    'openstack.org/kuryr-config':
                        '''{"subnetId": "subnet-b"}'''
                }
            }
        },
        {
            'name': 'net-c',
            'metadata': {
                'annotations': {
                    'openstack.org/kuryr-config':
                        '''{"subnetId": "subnet-c"}'''
                }
            }
        }
    ]


def get_subnet_objs():
    return [
        {'subnet-a': mock.sentinel.subneta},
        {'subnet-b': mock.sentinel.subnetb},
        {'subnet-c': mock.sentinel.subnetc},
    ]


class TestNPWGMultiVIFDriver(test_base.TestCase):

    def setUp(self):
        super(TestNPWGMultiVIFDriver, self).setUp()
        self._project_id = mock.sentinel.project_id
        self._subnet = mock.sentinel.subnet
        self._vif = mock.sentinel.vif
        self._subnets = [self._subnet]
        self._security_groups = mock.sentinel.security_groups
        self._pod = get_pod_obj()
        self._vif_pool_drv = mock.Mock(spec=drivers.VIFPoolDriver)
        self._request_vif = self._vif_pool_drv.request_vif
        self._request_vif.return_value = self._vif

        self._cls = multi_vif.NPWGMultiVIFDriver
        self._drv = mock.Mock(spec=self._cls)
        self._drv._get_networks = mock.Mock()
        self._drv._drv_vif_pool = self._vif_pool_drv

    @mock.patch.object(drivers.VIFPoolDriver, 'set_vif_driver')
    @mock.patch.object(drivers.VIFPoolDriver, 'get_instance')
    def test_init(self, m_get_vif_pool_driver, m_set_vifs_driver):
        m_get_vif_pool_driver.return_value = self._vif_pool_drv
        self._vif_pool_drv.set_vif_driver = m_set_vifs_driver

        m_drv = multi_vif.NPWGMultiVIFDriver()
        self.assertEqual(self._vif_pool_drv, m_drv._drv_vif_pool)
        m_get_vif_pool_driver.assert_called_once_with(
            specific_driver='multi_pool')
        m_set_vifs_driver.assert_called_once()

    @mock.patch('kuryr_kubernetes.utils.get_subnet')
    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_request_additional_vifs(self, m_get_client, m_get_subnet):
        vifs = [mock.sentinel.vif_a, mock.sentinel.vif_b, mock.sentinel.vif_c]
        self._request_vif.side_effect = vifs
        net_crds = get_crd_objs()
        client = mock.Mock()
        m_get_client.return_value = client
        m_get_subnet.side_effect = [mock.sentinel.subneta,
                                    mock.sentinel.subnetb,
                                    mock.sentinel.subnetc]
        client.get = mock.Mock()
        client.get.side_effect = net_crds
        self._drv._get_networks.return_value = get_nets()

        self.assertEqual(vifs, self._cls.request_additional_vifs(
            self._drv, self._pod, self._project_id, self._security_groups))

    def test_get_networks_str(self):
        networks = get_nets()
        self.assertEqual(networks,
                         self._cls._get_networks(self._drv, self._pod))

    def test_get_networks_json(self):
        networks = get_nets()
        self._pod['metadata']['annotations'][
            'kubernetes.v1.cni.cncf.io/networks'] = jsonutils.dumps(networks)
        self.assertEqual(networks,
                         self._cls._get_networks(self._drv, self._pod))

    def test_get_networks_with_invalid_annotation(self):
        self._pod['metadata']['annotations'][
            constants.K8S_ANNOTATION_NPWG_NETWORK] = 'ns/net-a/invalid'
        self.assertRaises(exceptions.InvalidKuryrNetworkAnnotation,
                          self._cls._get_networks, self._drv, self._pod)

    def test_get_networks_without_annotation(self):
        pod = {
            'metadata': {
                'annotations': {
                }
            }
        }

        self.assertEqual([], self._cls._get_networks(self._drv, pod))

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_request_additional_vifs_without_networks(self, m_get_client):
        self._drv._get_networks.return_value = []

        self.assertEqual([],
                         self._cls.request_additional_vifs(
                             self._drv, self._pod, self._project_id,
                             self._security_groups))
        m_get_client.assert_not_called()

    @mock.patch('kuryr_kubernetes.clients.get_kubernetes_client')
    def test_request_additional_vifs_with_invalid_network(self, m_get_client):
        net_crds = get_crd_objs()
        client = mock.Mock()
        m_get_client.return_value = client
        client.get = mock.Mock()
        client.get.side_effects = net_crds
        networks = [{'invalid_key': 'net-x'}]
        self._drv._get_networks.return_value = networks

        self.assertRaises(exceptions.InvalidKuryrNetworkAnnotation,
                          self._cls.request_additional_vifs,
                          self._drv, self._pod, self._project_id,
                          self._security_groups)
