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

import sctp
import socket
import sys

sk = sctp.sctpsocket_tcp(socket.AF_INET)


def connect_plus_message(OUT_IP, OUT_PORT):
    sk.connect((OUT_IP, OUT_PORT))
    print("Sending Message")
    sk.sctp_send(msg='HELLO, I AM ALIVE!!!')
    msgFromServer = sk.recvfrom(1024)
    print(msgFromServer[0].decode('utf-8'))
    sk.shutdown(0)
    sk.close()


if __name__ == '__main__':
    connect_plus_message(sys.argv[1], int(sys.argv[2]))
