# Copyright 2020 Red Hat, Inc.
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

from oslo_config import cfg

from kuryr_kubernetes.controller.drivers import node_subnets
from kuryr_kubernetes.tests import base as test_base


class TestConfigNodesSubnetsDriver(test_base.TestCase):

    def test_get_nodes_subnets(self):
        subnets = ['subnet1', 'subnet2']
        cfg.CONF.set_override('worker_nodes_subnets', subnets,
                              group='pod_vif_nested')
        driver = node_subnets.ConfigNodesSubnets()

        self.assertEqual(subnets, driver.get_nodes_subnets())

    def test_get_nodes_subnets_alias(self):
        subnet = 'subnet1'
        cfg.CONF.set_override('worker_nodes_subnet', subnet,
                              group='pod_vif_nested')
        driver = node_subnets.ConfigNodesSubnets()

        self.assertEqual([subnet], driver.get_nodes_subnets())

    def test_get_project_not_set_raise(self):
        cfg.CONF.set_override('worker_nodes_subnets', None,
                              group='pod_vif_nested')
        driver = node_subnets.ConfigNodesSubnets()

        self.assertRaises(cfg.RequiredOptError, driver.get_nodes_subnets,
                          raise_on_empty=True)

    def test_get_project_not_set(self):
        cfg.CONF.set_override('worker_nodes_subnets', None,
                              group='pod_vif_nested')
        driver = node_subnets.ConfigNodesSubnets()

        self.assertEqual([], driver.get_nodes_subnets())

    def test_add_node(self):
        driver = node_subnets.ConfigNodesSubnets()
        self.assertFalse(driver.add_node('node'))

    def test_delete_node(self):
        driver = node_subnets.ConfigNodesSubnets()
        self.assertFalse(driver.delete_node('node'))
