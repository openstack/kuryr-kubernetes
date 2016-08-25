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
from asyncio import streams


class ChunkedStreamReader(streams.StreamReader):

    async def readchunk(self):  # flake8: noqa
        """Modified asyncio.streams.readline for http chunks

        Returns an HTTP1.1 chunk transfer encoding chunk. Returns None if it is
        the trailing chunk.
        """
        if self._exception is not None:
            raise self._exception

        chunk_size = bytearray()
        chunk = bytearray()
        size = None
        sep = b'\r\n'

        while size != 0:
            while self._buffer and size is None:
                ichar = self._buffer.find(sep)
                if ichar < 0:
                    chunk_size.extend(self._buffer)
                    self._buffer.clear()
                else:  # size present
                    chunk_size.extend(self._buffer[:ichar])
                    size = int(bytes(chunk_size), 16)
                    if size == 0:  # Terminal chunk
                        self._buffer.clear()
                        self.feed_eof()
                        return b''
                    else:
                        del self._buffer[:ichar + len(sep)]

            while self._buffer and size > 0:
                buff_size = len(self._buffer)
                if buff_size < size:
                    chunk.extend(self._buffer)
                    self._buffer.clear()
                    size -= buff_size
                else:
                    chunk.extend(self._buffer[:size])
                    del self._buffer[:size + len(sep)]  # delete also trailer
                    size = 0

            if self._eof:
                break

            if size is None or size > 0:
                await self._wait_for_data('readchunk')
            elif size < 0:
                raise ValueError(_('Chunk wrongly encoded'))

        self._maybe_resume_transport()
        return bytes(chunk)
