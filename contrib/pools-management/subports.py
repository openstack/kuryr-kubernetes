# Copyright 2017 Red Hat, Inc.
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

import argparse
from http import client as httplib
import socket

from oslo_serialization import jsonutils

from kuryr_kubernetes import constants


class UnixDomainHttpConnection(httplib.HTTPConnection):

    def __init__(self, path, timeout):
        httplib.HTTPConnection.__init__(
            self, "localhost", timeout=timeout)
        self.__unix_socket_path = path
        self.timeout = timeout

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.__unix_socket_path)
        self.sock = sock


def create_subports(num_ports, trunk_ips, timeout=180):
    method = 'POST'
    body = jsonutils.dumps({"trunks": trunk_ips, "num_ports": num_ports})
    headers = {'Content-Type': 'application/json', 'Connection': 'close'}
    headers['Content-Length'] = len(body)
    path = 'http://localhost{0}'.format(constants.VIF_POOL_POPULATE)
    socket_path = constants.MANAGER_SOCKET_FILE
    conn = UnixDomainHttpConnection(socket_path, timeout)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    print(resp.read())


def delete_subports(trunk_ips, timeout=180):
    method = 'POST'
    body = jsonutils.dumps({"trunks": trunk_ips})
    headers = {'Content-Type': 'application/json', 'Connection': 'close'}
    headers['Content-Length'] = len(body)
    path = 'http://localhost{0}'.format(constants.VIF_POOL_FREE)
    socket_path = constants.MANAGER_SOCKET_FILE
    conn = UnixDomainHttpConnection(socket_path, timeout)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    print(resp.read())


def list_pools(timeout=180):
    method = 'GET'
    body = jsonutils.dumps({})
    headers = {'Context-Type': 'application/json', 'Connection': 'close'}
    headers['Context-Length'] = len(body)
    path = 'http://localhost{0}'.format(constants.VIF_POOL_LIST)
    socket_path = constants.MANAGER_SOCKET_FILE
    conn = UnixDomainHttpConnection(socket_path, timeout)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    print(resp.read())


def show_pool(trunk_ip, project_id, sg, timeout=180):
    method = 'GET'
    body = jsonutils.dumps({"pool_key": [trunk_ip, project_id, sg]})
    headers = {'Context-Type': 'application/json', 'Connection': 'close'}
    headers['Context-Length'] = len(body)
    path = 'http://localhost{0}'.format(constants.VIF_POOL_SHOW)
    socket_path = constants.MANAGER_SOCKET_FILE
    conn = UnixDomainHttpConnection(socket_path, timeout)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    print(resp.read())


def _get_parser():
    parser = argparse.ArgumentParser(
        description='Tool to create/free subports from the subports pool')
    subparser = parser.add_subparsers(help='commands', dest='command')

    create_ports_parser = subparser.add_parser(
        'create',
        help='Populate the pool(s) with subports')
    create_ports_parser.add_argument(
        '--trunks',
        help='list of trunk IPs where subports will be added',
        nargs='+',
        dest='subports',
        required=True)
    create_ports_parser.add_argument(
        '-n', '--num-ports',
        help='number of subports to be created per pool.',
        dest='num',
        default=1,
        type=int)
    create_ports_parser.add_argument(
        '-t', '--timeout',
        help='set timeout for operation. Default is 180 sec',
        dest='timeout',
        default=180,
        type=int)

    delete_ports_parser = subparser.add_parser(
        'free',
        help='Remove unused subports from the pools')
    delete_ports_parser.add_argument(
        '--trunks',
        help='list of trunk IPs where subports will be freed',
        nargs='+',
        dest='subports')
    delete_ports_parser.add_argument(
        '-t', '--timeout',
        help='set timeout for operation. Default is 180 sec',
        dest='timeout',
        default=180,
        type=int)

    list_pools_parser = subparser.add_parser(
        'list',
        help='List available pools and the number of ports they have')
    list_pools_parser.add_argument(
        '-t', '--timeout',
        help='set timeout for operation. Default is 180 sec',
        dest='timeout',
        default=180,
        type=int)

    show_pool_parser = subparser.add_parser(
        'show',
        help='Show the ports associated to a given pool')
    show_pool_parser.add_argument(
        '--trunk',
        help='Trunk IP of the desired pool',
        dest='trunk_ip',
        required=True)
    show_pool_parser.add_argument(
        '-p', '--project-id',
        help='project id of the pool',
        dest='project_id',
        required=True)
    show_pool_parser.add_argument(
        '--sg',
        help='Security group ids of the pool',
        dest='sg',
        nargs='+',
        required=True)
    show_pool_parser.add_argument(
        '-t', '--timeout',
        help='set timeout for operation. Default is 180 sec',
        dest='timeout',
        default=180,
        type=int)

    return parser


def main():
    """Parse options and call the appropriate class/method."""
    parser = _get_parser()
    args = parser.parse_args()
    if args.command == 'create':
        create_subports(args.num, args.subports, args.timeout)
    elif args.command == 'free':
        delete_subports(args.subports, args.timeout)
    elif args.command == 'list':
        list_pools(args.timeout)
    elif args.command == 'show':
        show_pool(args.trunk_ip, args.project_id, args.sg, args.timeout)


if __name__ == '__main__':
    main()
