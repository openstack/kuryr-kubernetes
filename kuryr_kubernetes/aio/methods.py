# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import asyncio
from collections import deque
import re
import sys
from urllib import parse

from kuryr.lib._i18n import _
from oslo_log import log
from oslo_serialization import jsonutils
import requests

from kuryr_kubernetes.aio import headers
from kuryr_kubernetes.aio import streams


LOG = log.getLogger(__name__)

GET = 'GET'
PATCH = 'PATCH'
POST = 'POST'


class Response(object):
    """HTTP Response class for dealing with HTTP responses in an async way"""
    _full_line = re.compile(b'(.+)(\r\n|\n|\r)')
    _line_remainder = re.compile(b'(\r\n|\n|\r)(.+)\Z')

    def __init__(self, reader, writer, decoder=None):
        self._reader = reader
        self._writer = writer
        self.decoder = decoder
        self.status = None
        self.headers = None
        self.content = None
        self.decoded = None
        self._remainder = b''
        self._matches = None

    async def read_headers(self):  # flake8: noqa
        """Returns HTTP status, reason and headers and updates the object

        One can either get the response doing:

          status, reason, hdrs = await response.read_headers()
          assert status == 200

        or check the object after it has been updated:

          await response.read_headers()
          assert response.status == 200
        """
        hdrs = {}
        # Read status
        line = await self._reader.readline()
        if not line:
            raise IOError(_('No status received'))

        line = line.decode('ascii').rstrip()
        http_version, status, reason = line.split(' ', maxsplit=2)
        self.status = int(status)

        while True:
            line = await self._reader.readline()
            if not line:
                break
            line = line.decode('ascii').rstrip()
            if line:
                try:
                    key, value = line.split(': ')
                    hdrs[key.upper()] = value
                except ValueError:
                    LOG.debug('Failed to read header: %s', line)
            else:
                break
            if self._reader.at_eof():
                break
        self.headers = hdrs
        return self.status, reason, self.headers

    async def read_chunk(self):
        """Returns an HTTP chunked response chunk. None when finsihed"""
        result = await self._reader.readchunk()
        if result == b'' and self._reader.at_eof():
            result = None
            if self._writer.can_write_eof():
                self._writer.write_eof()
            self._writer.close()
        return result

    async def read(self):
        """Returns the whole body of a non-chunked HTTP response"""
        result = await self._reader.readexactly(
            int(self.headers[headers.CONTENT_LENGTH]))
        if self._writer.can_write_eof():
            self._writer.write_eof()
        self._writer.close()
        self.content = result
        if self.decoder is not None:
            result = self.decoder(result)
            self.decoded = result
        return result

    async def read_line(self):
        """Returns a line out of HTTP chunked response chunks.

        If there are no more chunks to complete a line, it returns None
        """
        if self._matches is None:
            self._matches = deque()
        if self._matches:
            result = self._matches.pop().group(0)
        else:
            while True:
                chunk = await self._reader.readchunk()
                if chunk == b'' and self._reader.at_eof():
                    result = None
                    if self._writer.can_write_eof():
                        self._writer.write_eof()
                    self._writer.close()
                    break
                if self._remainder:
                    chunk = self._remainder + chunk
                    self._remainder = b''
                for match in self._full_line.finditer(chunk):
                    self._matches.appendleft(match)
                leftovers = [match.group(2) for match in
                             self._line_remainder.finditer(chunk)]
                if leftovers:
                    self._remainder, = leftovers
                if self._matches:
                    result = self._matches.pop().group(0)
                    break

        if None not in (result, self.decoder):
            result = self.decoder(result)
        return result

    async def read_all(self):
        if self.headers.get(headers.TRANSFER_ENCODING) == 'chunked':
            readings = []
            while True:
                read = await self.read_chunk()
                if read is None:
                    break
                else:
                    readings.append(read)
            content = b''.join(readings)
            if self.decoder is not None:
                result = self.decoder(content)
                self.decoded = result
            else:
                result = content
        else:
            result = await self.read()
        return result


async def get(endpoint, decoder=None, loop=None):
    """Returns a Response object

    This coroutine is intended to be used as a convenience method to perform
    HTTP GET requests in an asyncronous way. With the response object it
    returns you can obtain the GET data. Example:

      response = await get('http://httpbin.org/ip')
      status, reason, hdrs = await response.read_headers()
      if status == 200:  # check that the request is OK
          content = await response.read()   # Read a non chunked response
    """
    parsed_url = parse.urlsplit(endpoint)
    host = parsed_url.hostname.encode('idna').decode('utf8')
    # requests does proper path encoding for non ascii chars
    req = requests.Request(GET, endpoint).prepare()

    if parsed_url.scheme == 'https':
        port = 443 if parsed_url.port is None else parsed_url.port
        ssl = True
    else:
        port = 80 if parsed_url.port is None else parsed_url.port
        ssl = False

    if loop is None:
        loop = asyncio.events.get_event_loop()
    reader = streams.ChunkedStreamReader(limit=asyncio.streams._DEFAULT_LIMIT,
                                         loop=loop)
    protocol = asyncio.streams.StreamReaderProtocol(reader, loop=loop)
    transport, _ = await loop.create_connection(
        lambda: protocol, host, port, ssl=ssl)
    writer = asyncio.streams.StreamWriter(transport, protocol, reader, loop)

    _write_headers(writer, _auto_headers(parsed_url),
                   _request_line('GET', req.path_url))

    return Response(reader, writer, decoder)


def _auto_headers(parsed_url):
    return {
        headers.USER_AGENT:
        'Python/{0[0]}.{0[1]} raven/1.0'.format(sys.version_info),
        headers.HOST: parsed_url.netloc}


def _request_line(method, req_uri, http_version='1.1'):
    req_line = '{method} {path} HTTP/{version}\r\n'.format(
        method=method, path=req_uri, version=http_version)
    return req_line


def _write_headers(writer, headers, request_line):
    content = request_line + ''.join(
        key + ': ' + val + '\r\n' for key, val in headers.items()) + '\r\n'
    encoded_content = content.encode('utf8')
    writer.write(encoded_content)

if __name__ == '__main__':
    def term_handler():
        for task in asyncio.Task.all_tasks():
            task.cancel()
        print('Cancelling all threads...')
        print('Exitting')

    async def print_response(http_func, url, loop, print_headers=False,
                       line_based=True):
        response = await http_func(url, loop=loop)
        status, reason, hdrs = await response.read_headers()
        if hdrs.get(headers.CONTENT_TYPE) == 'application/json':
            response.decoder = lambda x: jsonutils.loads(x.decode())
        if status != 200:
            print('HTTP Status {}: {}. Exiting...'.format(status, reason))
            sys.exit(1)

        try:
            if hdrs.get(headers.TRANSFER_ENCODING) == 'chunked':
                while True:
                    if line_based:
                        content = await response.read_line()
                    else:
                        content = await response.read_chunk()
                    if content is None:
                        break
                    print(content)
            else:
                content = await response.read()
                print(content)
        except asyncio.CancelledError:
            pass

    async def print_raw(http_func, url, loop):
        response = await http_func(url, loop=loop)
        content = await asyncio.shield(response._reader.read(-1))
        print(content)

    import argparse
    import signal

    parser = argparse.ArgumentParser()
    parser.add_argument('method', help='The HTTP Method, i.e. "get"')
    parser.add_argument('url', help="The URL to do an HTTP Request to")
    parser.add_argument('-l', '--line-based', help='Process the chunk lines',
                        action='store_true')
    parser.add_argument('-i', '--header-info', help='print headers',
                        action='store_true')
    parser.add_argument('-r', '--raw', help='print raw response',
                        action='store_true')
    args = parser.parse_args()

    if args.method not in ('get',):
        raise NotImplementedError
    else:
        http_func = get

    loop = asyncio.get_event_loop()
    if args.raw:
        task = asyncio.async(print_raw(http_func, args.url, loop=loop))
    else:
        task = asyncio.async(print_response(http_func, args.url, loop=loop,
                                            print_headers=args.header_info,
                                            line_based=args.line_based))
    loop.run_until_complete(task)

    loop.add_signal_handler(signal.SIGINT, term_handler)
    loop.add_signal_handler(signal.SIGTERM, term_handler)
    loop.close()
