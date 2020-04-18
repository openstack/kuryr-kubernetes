# Copyright (c) 2016 Mirantis, Inc.
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
from unittest import mock


from kuryr_kubernetes.controller.drivers import base as d_base
from kuryr_kubernetes.tests import base as test_base


class _TestDriver(d_base.DriverBase, metaclass=abc.ABCMeta):
    ALIAS = 'test_alias'

    @abc.abstractmethod
    def test(self):
        raise NotImplementedError()


class TestDriverBase(test_base.TestCase):

    @mock.patch.object(d_base, '_DRIVER_MANAGERS')
    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch('stevedore.driver.DriverManager')
    def test_get_instance(self, m_stv_mgr, m_cfg, m_mgrs):
        m_drv = mock.MagicMock(spec=_TestDriver)
        m_mgr = mock.MagicMock()
        m_mgr.driver = m_drv
        m_mgrs.__getitem__.return_value = m_mgr

        self.assertEqual(m_drv, _TestDriver.get_instance())
        m_cfg.assert_not_called()
        m_stv_mgr.assert_not_called()

    @mock.patch.object(d_base, '_DRIVER_MANAGERS')
    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch('stevedore.driver.DriverManager')
    def test_get_instance_not_loaded(self, m_stv_mgr, m_cfg, m_mgrs):
        alias = _TestDriver.ALIAS
        cfg_name = '%s_driver' % (alias)
        mgr_key = '%s:_from_cfg:default' % (alias)
        drv_name = 'driver_impl'
        namespace = '%s.%s' % (d_base._DRIVER_NAMESPACE_BASE, alias)
        m_cfg.kubernetes.__getitem__.return_value = drv_name
        m_drv = mock.MagicMock(spec=_TestDriver)
        m_mgr = mock.MagicMock()
        m_mgr.driver = m_drv
        m_stv_mgr.return_value = m_mgr
        m_mgrs.__getitem__.side_effect = KeyError

        self.assertEqual(m_drv, _TestDriver.get_instance())
        m_cfg.kubernetes.__getitem__.assert_called_with(cfg_name)
        m_stv_mgr.assert_called_with(namespace=namespace, name=drv_name,
                                     invoke_on_load=True)
        m_mgrs.__setitem__.assert_called_once_with(mgr_key, m_mgr)

    @mock.patch.object(d_base, '_DRIVER_MANAGERS')
    @mock.patch('kuryr_kubernetes.config.CONF')
    @mock.patch('stevedore.driver.DriverManager')
    def test_get_instance_invalid_type(self, m_stv_mgr, m_cfg, m_mgrs):
        class _InvalidDriver(object):
            pass

        m_drv = mock.MagicMock(spec=_InvalidDriver)
        m_mgr = mock.MagicMock()
        m_mgr.driver = m_drv
        m_mgrs.__getitem__.return_value = m_mgr

        self.assertRaises(TypeError, _TestDriver.get_instance)
        m_cfg.assert_not_called()
        m_stv_mgr.assert_not_called()


class TestMultiVIFDriver(test_base.TestCase):

    @mock.patch.object(d_base, '_MULTI_VIF_DRIVERS', [])
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_enabled_drivers(self, m_cfg):
        cfg_name = 'multi_vif_drivers'
        drv_name = 'driver_impl'
        m_cfg.kubernetes.__getitem__.return_value = [drv_name]
        m_drv = mock.MagicMock()
        d_base.MultiVIFDriver.get_instance = mock.MagicMock(return_value=m_drv)

        self.assertIn(m_drv, d_base.MultiVIFDriver.get_enabled_drivers())
        m_cfg.kubernetes.__getitem__.assert_called_once_with(cfg_name)

    @mock.patch.object(d_base, '_MULTI_VIF_DRIVERS', [])
    @mock.patch('kuryr_kubernetes.config.CONF')
    def test_get_enabled_drivers_multiple(self, m_cfg):
        cfg_name = 'multi_vif_drivers'
        drv1_name = 'driver_impl_1'
        drv2_name = 'driver_impl_2'
        m_cfg.kubernetes.__getitem__.return_value = [drv1_name, drv2_name]
        m_drv1 = mock.MagicMock()
        m_drv2 = mock.MagicMock()
        d_base.MultiVIFDriver.get_instance = mock.MagicMock()
        d_base.MultiVIFDriver.get_instance.side_effect = [m_drv1, m_drv2]

        self.assertIn(m_drv1, d_base.MultiVIFDriver.get_enabled_drivers())
        self.assertIn(m_drv2, d_base.MultiVIFDriver.get_enabled_drivers())
        m_cfg.kubernetes.__getitem__.assert_called_once_with(cfg_name)
