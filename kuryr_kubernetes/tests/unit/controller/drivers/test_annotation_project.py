# Copyright (c) 2022 Troila
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

from unittest import mock

from oslo_config import cfg

from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import annotation_project
from kuryr_kubernetes.tests import base as test_base


class TestAnnotationProjectDriverBase(test_base.TestCase):

    project_id = 'fake_project_id'

    def _get_project_from_namespace(self, resource, driver):
        m_get_k8s_res = mock.patch('kuryr_kubernetes.controller.drivers.'
                                   'utils.get_k8s_resource').start()
        m_get_k8s_res.return_value = {
            'metadata': {
                'name': 'fake_namespace',
                'annotations': {
                    constants.K8s_ANNOTATION_PROJECT: self.project_id}}}
        project_id = driver.get_project(resource)
        self.assertEqual(self.project_id, project_id)

    def _get_project_from_configure_option(self, resource, driver):
        m_cfg = mock.patch('kuryr_kubernetes.config.CONF').start()
        m_cfg.neutron_defaults.project = self.project_id
        m_get_k8s_res = mock.patch('kuryr_kubernetes.controller.drivers.'
                                   'utils.get_k8s_resource').start()
        m_get_k8s_res.return_value = {
            'metadata': {
                'name': 'fake_namespace',
                'annotations': {}}}
        project_id = driver.get_project(resource)
        self.assertEqual(self.project_id, project_id)

    def _project_id_not_set(self, resource, driver):
        m_cfg = mock.patch('kuryr_kubernetes.config.CONF').start()
        m_cfg.neutron_defaults.project = ""
        m_get_k8s_res = mock.patch('kuryr_kubernetes.controller.drivers.'
                                   'utils.get_k8s_resource').start()
        m_get_k8s_res.return_value = {
            'metadata': {
                'name': 'fake_namespace',
                'annotations': {}}}
        self.assertRaises(cfg.RequiredOptError, driver.get_project, resource)


class TestAnnotationPodProjectDriver(TestAnnotationProjectDriverBase):

    pod = {'metadata': {'namespace': 'fake_namespace'}}

    def test_get_project(self):
        driver = annotation_project.AnnotationPodProjectDriver()
        self._get_project_from_namespace(self.pod, driver)
        self._get_project_from_configure_option(self.pod, driver)
        self._project_id_not_set(self.pod, driver)


class TestAnnotationServiceProjectDriver(TestAnnotationProjectDriverBase):

    service = {'metadata': {'namespace': 'fake_namespace'}}

    def test_get_project(self):
        driver = annotation_project.AnnotationPodProjectDriver()
        self._get_project_from_namespace(self.service, driver)
        self._get_project_from_configure_option(self.service, driver)
        self._project_id_not_set(self.service, driver)


class TestAnnotationNetworkPolicyProjectDriver(
        TestAnnotationProjectDriverBase):

    network_policy = {'metadata': {'namespace': 'fake_namespace'}}

    def test_get_project(self):
        driver = annotation_project.AnnotationPodProjectDriver()
        self._get_project_from_namespace(self.network_policy, driver)
        self._get_project_from_configure_option(self.network_policy, driver)
        self._project_id_not_set(self.network_policy, driver)


class TestAnnotationNamespaceProjectDriver(test_base.TestCase):

    project_id = 'fake_project_id'
    driver = annotation_project.AnnotationNamespaceProjectDriver()

    def test_get_project_from_annotation(self):
        namespace = {'metadata': {
            'annotations': {
                constants.K8s_ANNOTATION_PROJECT: self.project_id}}}
        project_id = self.driver.get_project(namespace)
        self.assertEqual(self.project_id, project_id)

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_project_from_configure_option(self, m_cfg):
        m_cfg.neutron_defaults.project = self.project_id
        namespace = {'metadata': {'name': 'fake_namespace'}}
        project_id = self.driver.get_project(namespace)
        self.assertEqual(self.project_id, project_id)

    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_project_not_set(self, m_cfg):
        m_cfg.neutron_defaults.project = ""
        namespace = {'metadata': {'name': 'fake_namespace'}}
        self.assertRaises(
            cfg.RequiredOptError, self.driver.get_project, namespace)
