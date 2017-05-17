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
import traceback

from kuryr.lib._i18n import _
from oslo_log import log as logging
from oslo_serialization import jsonutils

from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes import exceptions as k_exc

LOG = logging.getLogger(__name__)
_CNI_TIMEOUT = 60


class CNIConfig(dict):
    def __init__(self, cfg):
        super(CNIConfig, self).__init__(cfg)

        for k, v in self.items():
            if not k.startswith('_'):
                setattr(self, k, v)


class CNIArgs(object):
    def __init__(self, value):
        for item in value.split(';'):
            k, v = item.split('=', 1)
            if not k.startswith('_'):
                setattr(self, k, v)


class CNIParameters(object):
    def __init__(self, env, cfg):
        for k, v in env.items():
            if k.startswith('CNI_'):
                setattr(self, k, v)
        self.config = CNIConfig(cfg)
        self.args = CNIArgs(self.CNI_ARGS)

    def __repr__(self):
        return repr({key: value for key, value in self.__dict__.items() if
                     key.startswith('CNI_')})


@six.add_metaclass(abc.ABCMeta)
class CNIPlugin(object):

    @abc.abstractmethod
    def add(self, params):
        raise NotImplementedError()

    @abc.abstractmethod
    def delete(self, params):
        raise NotImplementedError()


class CNIRunner(object):

    # TODO(ivc): extend SUPPORTED_VERSIONS and format output based on
    # requested params.CNI_VERSION and/or params.config.cniVersion
    VERSION = '0.3.0'
    SUPPORTED_VERSIONS = ['0.3.0']

    def __init__(self, plugin):
        self._plugin = plugin

    def run(self, env, fin, fout):
        try:
            params = CNIParameters(env, jsonutils.load(fin))

            if params.CNI_COMMAND == 'ADD':
                vif = self._plugin.add(params)
                self._write_vif(fout, vif)
            elif params.CNI_COMMAND == 'DEL':
                self._plugin.delete(params)
            elif params.CNI_COMMAND == 'VERSION':
                self._write_version(fout)
            else:
                raise k_exc.CNIError(_("unknown CNI_COMMAND: %s")
                                     % params.CNI_COMMAND)
            return 0
        except Exception as ex:
            # LOG.exception
            self._write_exception(fout, str(ex))
            return 1

    def _write_dict(self, fout, dct):
        output = {'cniVersion': self.VERSION}
        output.update(dct)
        LOG.debug("CNI output: %s", output)
        jsonutils.dump(output, fout, sort_keys=True)

    def _write_exception(self, fout, msg):
        self._write_dict(fout, {
            'msg': msg,
            'code': k_const.CNI_EXCEPTION_CODE,
            'details': traceback.format_exc(),
        })

    def _write_version(self, fout):
        self._write_dict(fout, {'supportedVersions': self.SUPPORTED_VERSIONS})

    def _write_vif(self, fout, vif):
        result = {}
        nameservers = []

        for subnet in vif.network.subnets.objects:
            nameservers.extend(subnet.dns)

            ip = subnet.ips.objects[0].address
            cni_ip = result.setdefault("ip%s" % ip.version, {})
            cni_ip['ip'] = "%s/%s" % (ip, subnet.cidr.prefixlen)

            if subnet.gateway:
                cni_ip['gateway'] = str(subnet.gateway)

            if subnet.routes.objects:
                cni_ip['routes'] = [
                    {'dst': str(route.cidr), 'gw': str(route.gateway)}
                    for route in subnet.routes.objects]

        if nameservers:
            result['dns'] = {'nameservers': nameservers}

        self._write_dict(fout, result)
