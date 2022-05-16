#!/usr/bin/env python3

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

import argparse
import os
import subprocess
import sys
import time

import openstack
from openstack import exceptions as o_exc


class ParseDict(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        d = getattr(namespace, self.dest, {})
        if not d:
            d = {}

        if values:
            split_items = values.split("=", 1)
            key = split_items[0].strip()
            value = split_items[1]

            d[key] = value

        setattr(namespace, self.dest, d)


class DevStackHeat(object):
    HOT_FILE = 'hot/devstack_heat_template.yml'

    def __init__(self):
        parser = self._get_arg_parser()
        args = parser.parse_args()
        if hasattr(args, 'func'):
            self._setup_openstack(args.cloud)
            args.func(args)
            return

        parser.print_help()
        parser.exit()

    def _get_arg_parser(self):
        parser = argparse.ArgumentParser(
            description="Deploy a DevStack VM with Kuryr-Kubernetes")
        parser.add_argument('-c', '--cloud', help='name in clouds.yaml to use')

        subparsers = parser.add_subparsers(help='supported commands')

        stack = subparsers.add_parser('stack', help='run the VM')
        stack.add_argument('name', help='name of the stack')
        stack.add_argument('-e', '--environment', help='Heat stack env file',
                           default='hot/parameters.yml')
        stack.add_argument('-p', '--parameter', help='Heat stack parameters',
                           metavar='KEY=VALUE',
                           action=ParseDict)
        stack.add_argument('-j', '--join', help='SSH the stack and watch log',
                           action='store_true')
        stack.add_argument('--local-conf',
                           help='URL to DevStack local.conf file')
        stack.add_argument('--bashrc',
                           help='URL to bashrc file to put on VM')
        source = stack.add_mutually_exclusive_group()
        source.add_argument('--gerrit', help='ID of Kuryr Gerrit change')
        source.add_argument('--commit', help='Kuryr commit ID')
        source.add_argument('--branch', help='Kuryr branch')
        stack.add_argument('--devstack-branch', help='DevStack branch to use',
                           default='master')
        stack.add_argument('--additional-key', help='Additional SSH key to '
                                                    'add for stack user')
        stack.set_defaults(func=self.stack)

        unstack = subparsers.add_parser('unstack', help='delete the VM')
        unstack.add_argument('name', help='name of the stack')
        unstack.set_defaults(func=self.unstack)

        key = subparsers.add_parser('key', help='get SSH key')
        key.add_argument('name', help='name of the stack')
        key.set_defaults(func=self.key)

        show = subparsers.add_parser('show', help='show basic stack info')
        show.add_argument('name', help='name of the stack')
        show.set_defaults(func=self.show)

        ssh = subparsers.add_parser('ssh', help='SSH to the stack')
        ssh.add_argument('name', help='name of the stack')
        ssh.set_defaults(func=self.ssh)

        join = subparsers.add_parser('join', help='join watching logs of'
                                                  'DevStack installation')
        join.add_argument('name', help='name of the stack')
        join.set_defaults(func=self.join)

        return parser

    def _setup_openstack(self, cloud_name):
        self.heat = openstack.connection.from_config(
            cloud=cloud_name).orchestration

    def _find_output(self, stack, name):
        for output in stack.outputs:
            if output['output_key'] == name:
                return output['output_value']
        return None

    def _get_private_key(self, name):
        stack = self.heat.find_stack(name)
        if stack:
            return self._find_output(stack, 'master_key_priv')
        return None

    def stack(self, args):
        stack_attrs = self.heat.read_env_and_templates(
            template_file=self.HOT_FILE, environment_files=[args.environment])

        stack_attrs['name'] = args.name
        stack_attrs['parameters'] = args.parameter or {}
        if args.local_conf:
            stack_attrs['parameters']['local_conf'] = args.local_conf
        if args.bashrc:
            stack_attrs['parameters']['bashrc'] = args.bashrc
        if args.additional_key:
            stack_attrs['parameters']['ssh_key'] = args.additional_key
        if args.gerrit:
            stack_attrs['parameters']['gerrit_change'] = args.gerrit
        if args.commit:
            stack_attrs['parameters']['git_hash'] = args.commit
        if args.branch:
            stack_attrs['parameters']['branch'] = args.branch
        if args.devstack_branch:
            stack_attrs['parameters']['devstack_branch'] = args.devstack_branch

        print(f'Creating stack {args.name}')
        stack = self.heat.create_stack(**stack_attrs)
        print(f'Wating for stack {args.name} to create')
        self.heat.wait_for_status(stack, status='CREATE_COMPLETE',
                                  failures=['CREATE_FAILED'], wait=600)
        print(f'Stack {args.name} created')

        print(f'Saving SSH key to {args.name}.pem')
        key = self._get_private_key(args.name)
        if not key:
            print(f'Private key or stack {args.name} not found')
        with open(f'{args.name}.pem', "w") as pemfile:
            print(key, file=pemfile)

        os.chmod(f'{args.name}.pem', 0o600)

        if args.join:
            time.sleep(120)  # FIXME(dulek): This isn't pretty.
            self.join(args)

    def unstack(self, args):
        stack = self.heat.find_stack(args.name)
        if stack:
            self.heat.delete_stack(stack)
            try:
                self.heat.wait_for_status(stack, status='DELETE_COMPLETE',
                                          failures=['DELETE_FAILED'])
            except o_exc.ResourceNotFound:
                print(f'Stack {args.name} deleted')
            print(f'Deleting SSH key {args.name}.pem')
            os.unlink(f'{args.name}.pem')
        else:
            print(f'Stack {args.name} not found')

    def key(self, args):
        key = self._get_private_key(args.name)
        if not key:
            print(f'Private key or stack {args.name} not found')
        print(key)

    def show(self, args):
        stack = self.heat.find_stack(args.name)
        if not stack:
            print(f'Stack {args.name} not found')
        ips = self._find_output(stack, 'node_fips')
        print(f'IPs: {", ".join(ips)}')

    def _ssh(self, keyname, ip, command=None):
        if not command:
            command = []
        subprocess.run(['ssh', '-i', keyname, f'stack@{ip}'] + command,
                       stdin=sys.stdin, stdout=sys.stdout)

    def ssh(self, args, command=None):
        stack = self.heat.find_stack(args.name)
        if not stack:
            print(f'Stack {args.name} not found')
        ips = self._find_output(stack, 'node_fips')
        if not ips:
            print(f'Stack {args.name} has no IPs')
        self._ssh(f'{args.name}.pem', ips[0], command)

    def join(self, args):
        stack = self.heat.find_stack(args.name)
        if not stack:
            print(f'Stack {args.name} not found')
        ips = self._find_output(stack, 'node_fips')
        if not ips:
            print(f'Stack {args.name} has no IPs')
        self.ssh(args, ['tail', '-f', '/opt/stack/devstack.log'])


if __name__ == '__main__':
    DevStackHeat()
