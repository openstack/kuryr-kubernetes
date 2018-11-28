# Copyright 2018 Maysa de Macedo Souza.
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


class HealthRegister(object):
    instance = None

    def __init__(self):
        self.registry = []

    def register(self, elem):
        self.registry.append(elem)

    @classmethod
    def get_instance(cls):
        if not HealthRegister.instance:
            HealthRegister.instance = cls()
        return HealthRegister.instance


class HealthHandler(object):
    """Base class for health handlers."""
    def __init__(self):
        super(HealthHandler, self).__init__()
        self._alive = True
        self._ready = True
        self._manager = HealthRegister.get_instance()
        self._manager.register(self)

    def set_liveness(self, alive):
        self._alive = alive

    def set_readiness(self, ready):
        self._ready = ready

    def is_alive(self):
        return self._alive

    def is_ready(self, *args):
        return self._ready
