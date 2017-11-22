# Copyright (c) 2017 NEC Technologies India Pvt Ltd.
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
    def __init__(self, env, cfg=None):
        for k, v in env.items():
            if k.startswith('CNI_'):
                setattr(self, k, v)
        if cfg is None:
            self.config = CNIConfig(env['config_kuryr'])
        else:
            self.config = cfg
        self.args = CNIArgs(self.CNI_ARGS)

    def __repr__(self):
        return repr({key: value for key, value in self.__dict__.items() if
                     key.startswith('CNI_')})
