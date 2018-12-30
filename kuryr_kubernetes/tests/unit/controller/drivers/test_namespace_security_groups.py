# Copyright (c) 2018 Red Hat, Inc.
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

import mock

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import namespace_security_groups
from kuryr_kubernetes.tests import base as test_base
from kuryr_kubernetes.tests.unit import kuryr_fixtures as k_fix

from neutronclient.common import exceptions as n_exc


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
            'selfLink': '/api/v1/namespaces/default/pods/busybox-sleep1',
            'uid': '452176db-4a85-11e7-80bd-fa163e29dbbb',
            'annotations': {
                'openstack.org/kuryr-vif': {}
            }
        }}


def get_namespace_obj():
    return {
        'metadata': {
            'annotations': {
                constants.K8S_ANNOTATION_NET_CRD: 'net_crd_url_sample'
            }
        }
    }


def get_no_match_crd_namespace_obj():
    return {
        "kind": "Namespace",
        "metadata": {
            "annotations": {
                "openstack.org/kuryr-namespace-label": '{"name": "dev"}',
                "openstack.org/kuryr-net-crd": "ns-dev"
            },
            "labels": {"name": "prod"},
            "name": "prod",
            "selfLink": "/api/v1/namespaces/dev"}}


def get_match_crd_namespace_obj():
    return {
        "kind": "Namespace",
        "metadata": {
            "annotations": {
                "openstack.org/kuryr-namespace-label": '{"name": "dev"}',
                "openstack.org/kuryr-net-crd": "ns-dev"
            },
            "labels": {
                "name": "dev"
            },
            "name": "dev",
            "selfLink": "/api/v1/namespaces/dev"}}


def get_match_crd_pod_obj():
    return {
        'kind': 'Pod',
        'metadata': {
            'name': mock.sentinel.pod_name,
            'namespace': 'dev',
            'labels': {
                'tier': 'backend'},
            'annotations': {
                'openstack.org/kuryr-pod-label': '{"tier": "backend"}'}},
        'status': {'podIP': mock.sentinel.podIP}}


def get_sg_rule():
    pod_ip = get_match_crd_pod_obj()['status'].get('podIP')
    return {
        "namespace": 'dev',
        "security_group_rule": {
            "description": "Kuryr-Kubernetes NetPolicy SG rule",
            "direction": "ingress",
            "ethertype": "IPv4",
            "id": 'f15ff50a-e8a4-4872-81bf-a04cbb8cb388',
            "port_range_max": 6379,
            "port_range_min": 6379,
            "protocol": "tcp",
            "remote_ip_prefix": pod_ip,
            "security_group_id": '36923e76-026c-422b-8dfd-7292e7c88228'}}


def get_matched_crd_obj():
    return {
        "kind": "KuryrNetPolicy",
        "metadata": {"name": "np-test-network-policy",
                     "namespace": "default"},
        "spec": {
            "egressSgRules": [],
            "ingressSgRules": [get_sg_rule()],
            "networkpolicy_spec": {
                "ingress": [
                    {"from": [
                        {"namespaceSelector": {
                            "matchLabels": {"name": "dev"}}}],
                     "ports": [
                        {"port": 6379,
                         "protocol": "TCP"}]}],
                "podSelector": {"matchLabels": {"app": "demo"}},
                "policyTypes": ["Ingress"]},
            "podSelector": {"matchLabels": {"app": "demo"}},
            "securityGroupId": '36923e76-026c-422b-8dfd-7292e7c88228'}}


def get_crd_obj_no_match():
    return {
        "kind": "KuryrNetPolicy",
        "metadata": {"name": "np-test-network-policy",
                     "namespace": "default"},
        "spec": {
            "egressSgRules": [],
            "ingressSgRules": [],
            "networkpolicy_spec": {
                "ingress": [
                    {"from": [
                        {"namespaceSelector": {
                            "matchLabels": {"name": "dev"}}}],
                     "ports": [
                        {"port": 6379,
                         "protocol": "TCP"}]}],
                "podSelector": {"matchLabels": {"app": "demo"}},
                "policyTypes": ["Ingress"]},
            "podSelector": {"matchLabels": {"app": "demo"}},
            "securityGroupId": '36923e76-026c-422b-8dfd-7292e7c88228'}}


def get_crd_obj_with_all_selectors():
    return {
        "kind": "KuryrNetPolicy",
        "metadata": {"name": "np-test-network-policy",
                     "namespace": "default"},
        "spec": {
            "egressSgRules": [],
            "ingressSgRules": [],
            "networkpolicy_spec": {
                "ingress": [
                    {"from": [
                        {"namespaceSelector": {
                            "matchLabels": {"name": "dev"}},
                         "podSelector": {
                            "matchLabels": {"tier": "backend"}}}],
                     "ports": [
                        {"port": 6379,
                         "protocol": "TCP"}]}],
                "podSelector": {"matchLabels": {"app": "demo"}},
                "policyTypes": ["Ingress"]},
            "podSelector": {"matchLabels": {"app": "demo"}},
            "securityGroupId": '36923e76-026c-422b-8dfd-7292e7c88228'}}


class TestNamespacePodSecurityGroupsDriver(test_base.TestCase):

    @mock.patch('kuryr_kubernetes.controller.drivers.'
                'namespace_security_groups._get_net_crd')
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_security_groups(self, m_cfg, m_get_crd):
        cls = namespace_security_groups.NamespacePodSecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)

        pod = get_pod_obj()
        project_id = mock.sentinel.project_id
        sg_list = [mock.sentinel.sg_id]
        m_cfg.neutron_defaults.pod_security_groups = sg_list
        sg_id = mock.sentinel.sg_id
        extra_sg = mock.sentinel.extra_sg
        net_crd = {
            'spec': {
                'sgId': sg_id
            }
        }
        m_get_crd.return_value = net_crd
        m_driver._get_extra_sg.return_value = [extra_sg]

        ret = cls.get_security_groups(m_driver, pod, project_id)
        expected_sg = [str(sg_id), str(extra_sg), sg_list[0]]

        self.assertEqual(ret, expected_sg)
        m_get_crd.assert_called_once_with(pod['metadata']['namespace'])

    def test_create_namespace_sg(self):
        cls = namespace_security_groups.NamespacePodSecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)

        namespace = 'test'
        project_id = mock.sentinel.project_id
        sg = {'id': mock.sentinel.sg}
        subnet_cidr = mock.sentinel.subnet_cidr
        crd_spec = {
            'subnetCIDR': subnet_cidr
        }
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.create_security_group.return_value = {'security_group': sg}

        create_sg_resp = cls.create_namespace_sg(m_driver, namespace,
                                                 project_id, crd_spec)

        self.assertEqual(create_sg_resp, {'sgId': sg['id']})
        neutron.create_security_group.assert_called_once()
        neutron.create_security_group_rule.assert_called_once()

    def test_create_namespace_sg_exception(self):
        cls = namespace_security_groups.NamespacePodSecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)

        namespace = 'test'
        project_id = mock.sentinel.project_id
        subnet_cidr = mock.sentinel.subnet_cidr
        crd_spec = {
            'subnetCIDR': subnet_cidr
        }
        neutron = self.useFixture(k_fix.MockNeutronClient()).client
        neutron.create_security_group.side_effect = (
            n_exc.NeutronClientException)

        self.assertRaises(n_exc.NeutronClientException,
                          cls.create_namespace_sg, m_driver,
                          namespace, project_id, crd_spec)

        neutron.create_security_group.assert_called_once()
        neutron.create_security_group_rule.assert_not_called()

    def test_delete_sg(self):
        cls = namespace_security_groups.NamespacePodSecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        sg_id = mock.sentinel.sg_id

        cls.delete_sg(m_driver, sg_id)
        neutron.delete_security_group.assert_called_once_with(sg_id)

    def test_delete_sg_exception(self):
        cls = namespace_security_groups.NamespacePodSecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        sg_id = mock.sentinel.sg_id
        neutron.delete_security_group.side_effect = (
            n_exc.NeutronClientException)

        self.assertRaises(n_exc.NeutronClientException, cls.delete_sg,
                          m_driver, sg_id)
        neutron.delete_security_group.assert_called_once_with(sg_id)

    def test_delete_sg_not_found(self):
        cls = namespace_security_groups.NamespacePodSecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)
        neutron = self.useFixture(k_fix.MockNeutronClient()).client

        sg_id = mock.sentinel.sg_id
        neutron.delete_security_group.side_effect = n_exc.NotFound

        cls.delete_sg(m_driver, sg_id)
        neutron.delete_security_group.assert_called_once_with(sg_id)

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'patch_kuryr_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'delete_security_group_rule')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetpolicy_crds')
    def test_delete_namespace_sg_rule(self, m_get_knp_crd, m_delete_sg_rule,
                                      m_patch_kuryr_crd):
        cls = namespace_security_groups.NamespacePodSecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)
        i_rule = get_matched_crd_obj()['spec']['ingressSgRules'][0]
        sg_rule_id = i_rule.get('security_group_rule')['id']

        m_get_knp_crd.return_value = {"items": [get_matched_crd_obj()]}

        cls.delete_namespace_sg_rules(m_driver, get_match_crd_namespace_obj())

        m_get_knp_crd.assert_called_once()
        m_delete_sg_rule.assert_called_once_with(sg_rule_id)
        m_patch_kuryr_crd.assert_called_once()

    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'patch_kuryr_crd')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'delete_security_group_rule')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_kuryrnetpolicy_crds')
    def test_delete_namespace_sg_rule_no_match(self, m_get_knp_crd,
                                               m_delete_sg_rule,
                                               m_patch_kuryr_crd):
        cls = namespace_security_groups.NamespacePodSecurityGroupsDriver
        m_driver = mock.MagicMock(spec=cls)

        m_get_knp_crd.return_value = {"items": [get_matched_crd_obj()]}

        cls.delete_namespace_sg_rules(m_driver,
                                      get_no_match_crd_namespace_obj())

        m_get_knp_crd.assert_called_once()
        m_delete_sg_rule.assert_not_called()
        m_patch_kuryr_crd.assert_not_called()

    @mock.patch('kuryr_kubernetes.controller.drivers.'
                'namespace_security_groups._create_sg_rule')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_selector')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_namespace_subnet_cidr')
    def test__parse_rules(self, m_get_ns_subnet_cidr, m_match_selector,
                          m_create_sg_rule):
        crd = get_crd_obj_no_match()
        policy = crd['spec']['networkpolicy_spec']
        i_rule = policy.get('ingress')[0]
        ns_selector = i_rule['from'][0].get('namespaceSelector')
        ns = get_match_crd_namespace_obj()

        m_get_ns_subnet_cidr.return_value = '10.0.2.0/26'
        m_match_selector.return_value = True
        m_create_sg_rule.return_value = get_sg_rule()

        matched, rules = namespace_security_groups._parse_rules('ingress',
                                                                crd, ns)

        m_get_ns_subnet_cidr.assert_called_once_with(ns)
        m_match_selector.assert_called_once_with(ns_selector,
                                                 ns['metadata']['labels'])
        m_create_sg_rule.assert_called_once()

        self.assertEqual(matched, True)
        self.assertEqual(rules, [get_sg_rule()])

    @mock.patch('kuryr_kubernetes.controller.drivers.'
                'namespace_security_groups._create_sg_rule')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_selector')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_namespace_subnet_cidr')
    def test__parse_rules_no_match(self, m_get_ns_subnet_cidr,
                                   m_match_selector, m_create_sg_rule):
        crd = get_crd_obj_no_match()
        policy = crd['spec']['networkpolicy_spec']
        i_rule = policy.get('ingress')[0]
        ns_selector = i_rule['from'][0].get('namespaceSelector')
        ns = get_no_match_crd_namespace_obj()

        m_get_ns_subnet_cidr.return_value = '10.0.2.0/26'
        m_match_selector.return_value = False

        matched, rules = namespace_security_groups._parse_rules('ingress',
                                                                crd, ns)

        m_get_ns_subnet_cidr.assert_called_once_with(ns)
        m_match_selector.assert_called_once_with(ns_selector,
                                                 ns['metadata']['labels'])
        m_create_sg_rule.assert_not_called()

        self.assertEqual(matched, False)
        self.assertEqual(rules, [])

    @mock.patch('kuryr_kubernetes.controller.drivers.'
                'namespace_security_groups._create_sg_rule')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_pod_ip')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_pods')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'match_selector')
    @mock.patch('kuryr_kubernetes.controller.drivers.utils.'
                'get_namespace_subnet_cidr')
    def test__parse_rules_all_selectors(self, m_get_ns_subnet_cidr,
                                        m_match_selector, m_get_pods,
                                        m_get_pod_ip, m_create_sg_rule):
        crd = get_crd_obj_with_all_selectors()
        policy = crd['spec']['networkpolicy_spec']
        i_rule = policy.get('ingress')[0]
        ns_selector = i_rule['from'][0].get('namespaceSelector')
        pod_selector = i_rule['from'][0].get('podSelector')
        ns = get_match_crd_namespace_obj()
        pod = get_match_crd_pod_obj()

        m_get_ns_subnet_cidr.return_value = '10.0.2.0/26'
        m_match_selector.return_value = True
        m_get_pods.return_value = {"items": [pod]}
        m_get_pod_ip.return_value = pod['status']['podIP']
        m_create_sg_rule.return_value = get_sg_rule()

        matched, rules = namespace_security_groups._parse_rules('ingress',
                                                                crd, ns)

        m_get_ns_subnet_cidr.assert_called_once_with(ns)
        m_match_selector.assert_called_once_with(ns_selector,
                                                 ns['metadata']['labels'])
        m_get_pods.assert_called_once_with(pod_selector,
                                           ns['metadata']['name'])
        m_get_pod_ip.assert_called_once_with(pod)
        m_create_sg_rule.assert_called_once()

        self.assertEqual(matched, True)
        self.assertEqual(rules, [get_sg_rule()])
