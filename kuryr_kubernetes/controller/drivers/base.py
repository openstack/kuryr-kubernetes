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
import six

from kuryr.lib._i18n import _LE
from oslo_log import log as logging
from stevedore import driver as stv_driver

from kuryr_kubernetes import config

LOG = logging.getLogger(__name__)

_DRIVER_NAMESPACE_BASE = 'kuryr_kubernetes.controller.drivers'
_DRIVER_MANAGERS = {}


class DriverBase(object):
    """Base class for controller drivers.

    Subclasses must define an *ALIAS* attribute that is used to find a driver
    implementation by `get_instance` class method which utilises
    `stevedore.driver.DriverManager` with the namespace set to
    'kuryr_kubernetes.controller.drivers.*ALIAS*' and the name of
    the driver determined from the '[kubernetes]/*ALIAS*_driver' configuration
    parameter.

    Usage example:

        @six.add_metaclass(abc.ABCMeta)
        class SomeDriverInterface(DriverBase):
            ALIAS = 'driver_alias'

            @abc.abstractmethod
            def some_method(self):
                pass

        driver = SomeDriverInterface.get_instance()
        driver.some_method()
    """

    @classmethod
    def get_instance(cls):
        """Get an implementing driver instance."""

        alias = cls.ALIAS

        try:
            manager = _DRIVER_MANAGERS[alias]
        except KeyError:
            name = config.CONF.kubernetes[alias + '_driver']
            manager = stv_driver.DriverManager(
                namespace="%s.%s" % (_DRIVER_NAMESPACE_BASE, alias),
                name=name,
                invoke_on_load=True)
            _DRIVER_MANAGERS[alias] = manager

        driver = manager.driver
        if not isinstance(driver, cls):
            raise TypeError(_LE("Invalid %(alias)r driver type: %(driver)s, "
                                "must be a subclass of %(type)s") % {
                'alias': alias,
                'driver': driver.__class__.__name__,
                'type': cls})
        return driver


@six.add_metaclass(abc.ABCMeta)
class PodProjectDriver(DriverBase):
    """Provides an OpenStack project ID for Kubernetes Pod ports."""

    ALIAS = 'pod_project'

    @abc.abstractmethod
    def get_project(self, pod):
        """Get an OpenStack project ID for Kubernetes Pod ports.

        :param pod: dict containing Kubernetes Pod object
        :return: project ID
        """

        raise NotImplementedError()
