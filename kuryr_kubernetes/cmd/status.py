# Copyright 2018 Red Hat
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

"""
CLI interface for kuryr status commands.
"""

import sys
import textwrap
import traceback

import prettytable

import os_vif
from os_vif.objects import base
from oslo_config import cfg
from oslo_serialization import jsonutils

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes import objects
from kuryr_kubernetes import version

CONF = config.CONF

UPGRADE_CHECK_SUCCESS = 0
UPGRADE_CHECK_WARNING = 1
UPGRADE_CHECK_FAILURE = 2

UPGRADE_CHECK_MSG_MAP = {
    UPGRADE_CHECK_SUCCESS: 'Success',
    UPGRADE_CHECK_WARNING: 'Warning',
    UPGRADE_CHECK_FAILURE: 'Failure',
}


class UpgradeCheckResult(object):
    """Class used for 'kuryr-k8s-status upgrade check' results.

    The 'code' attribute is an UpgradeCheckCode enum.
    The 'details' attribute is a message generally only used for
    checks that result in a warning or failure code. The details should provide
    information on what issue was discovered along with any remediation.
    """

    def __init__(self, code, details=None):
        super(UpgradeCheckResult, self).__init__()
        self.code = code
        self.details = details

    def get_details(self):
        if self.details is not None:
            # wrap the text on the details to 60 characters
            return '\n'.join(textwrap.wrap(self.details, 60,
                                           subsequent_indent=' ' * 9))


class UpgradeCommands(object):
    def __init__(self):
        self.check_methods = {
            'Pod annotations': self._check_annotations,  # Stein
        }
        clients.setup_kubernetes_client()
        self.k8s = clients.get_kubernetes_client()

    def _get_annotation(self, pod):
        annotations = pod['metadata']['annotations']
        if constants.K8S_ANNOTATION_VIF not in annotations:
            # NOTE(dulek): We ignore pods without annotation, those
            # probably are hostNetworking.
            return None
        k_ann = annotations[constants.K8S_ANNOTATION_VIF]
        k_ann = jsonutils.loads(k_ann)
        obj = base.VersionedObject.obj_from_primitive(k_ann)
        return obj

    def _check_annotations(self):
        old_count = 0
        malformed_count = 0
        pods = self.k8s.get('/api/v1/pods')['items']
        for pod in pods:
            try:
                obj = self._get_annotation(pod)
                if not obj:
                    # NOTE(dulek): We ignore pods without annotation, those
                    # probably are hostNetworking.
                    continue
            except Exception:
                # TODO(dulek): We might want to print this exception.
                malformed_count += 1
                continue

            if obj.obj_name() != objects.vif.PodState.obj_name():
                old_count += 1

        if malformed_count == 0 and old_count == 0:
            return UpgradeCheckResult(0, 'All annotations are updated.')
        elif malformed_count > 0 and old_count == 0:
            msg = ('You have %d malformed Kuryr pod annotations in your '
                   'deployment. This is not blocking the upgrade, but '
                   'consider investigating it.' % malformed_count)
            return UpgradeCheckResult(1, msg)
        elif old_count > 0:
            msg = ('You have %d Kuryr pod annotations in old format. You need '
                   'to run `kuryr-k8s-status upgrade update-annotations` '
                   'before proceeding with the upgrade.' % old_count)
            return UpgradeCheckResult(2, msg)

    def upgrade_check(self):
        check_results = []

        t = prettytable.PrettyTable(['Upgrade Check Results'],
                                    hrules=prettytable.ALL)
        t.align = 'l'

        for name, method in self.check_methods.items():
            result = method()
            check_results.append(result)
            cell = (
                'Check: %(name)s\n'
                'Result: %(result)s\n'
                'Details: %(details)s' %
                {
                    'name': name,
                    'result': UPGRADE_CHECK_MSG_MAP[result.code],
                    'details': result.get_details(),
                }
            )
            t.add_row([cell])
        print(t)

        return max(res.code for res in check_results)

    def update_annotations(self):
        pass

    def downgrade_annotations(self):
        pass


def print_version():
    print(version.version_info.version_string())


def add_parsers(subparsers):
    upgrade_cmds = UpgradeCommands()

    upgrade = subparsers.add_parser(
        'upgrade', help='Actions related to upgrades between releases.')
    sub = upgrade.add_subparsers()

    check = sub.add_parser('check', help='Check if upgrading is possible.')
    check.set_defaults(action_fn=upgrade_cmds.upgrade_check)

    ann_update = sub.add_parser(
        'update-annotations',
        help='Update annotations in K8s API to newest version.')
    ann_update.set_defaults(action_fn=upgrade_cmds.update_annotations)

    ann_downgrade = sub.add_parser(
        'downgrade-annotations',
        help='Downgrade annotations in K8s API to previous version (useful '
             'when reverting a failed upgrade).')
    ann_downgrade.set_defaults(action_fn=upgrade_cmds.downgrade_annotations)

    version_action = subparsers.add_parser('version')
    version_action.set_defaults(action_fn=print_version)


def main():
    opt = cfg.SubCommandOpt(
        'category', title='command',
        description='kuryr-k8s-status command or category to execute',
        handler=add_parsers)

    conf = cfg.ConfigOpts()
    conf.register_cli_opt(opt)
    conf(sys.argv[1:])

    os_vif.initialize()
    objects.register_locally_defined_vifs()

    try:
        return conf.category.action_fn()
    except Exception:
        print('Error:\n%s' % traceback.format_exc())
        # This is 255 so it's not confused with the upgrade check exit codes.
        return 255


if __name__ == '__main__':
    main()
