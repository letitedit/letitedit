"""Reading the Windows pipe a program was given on stdin without ever leaving a read waiting on it.

A thread blocked in a read of such a pipe holds the handle, and Windows then holds every other question asked about it
until the read returns. Some libraries ask what kind of handle stdin is as their DLL loads (numpy's and scipy's
start-up do), and a Python started without a stdin of its own asks as it starts. With one thread listening to the pipe,
such an import or child in another thread waits for the listener's next bytes: for good, when the other end writes
nothing more until that work is done.

reader(stream) reads the pipe only when it already holds bytes (PeekNamedPipe never waits), so nothing is ever held.
A program that does all its work in the thread that reads, between reads, has no waiting read at that time and doesn't
need this.

    lines = pipe_input.reader(sys.stdin.buffer)    # read nothing from the stream before this
    lines.readline(); lines.read(size); for line in lines: ...
"""
from __future__ import annotations

import os
import time

POLL_S = 0.25          # the longest wait between two looks at an empty pipe
FIRST_POLL_S = 0.001   # the wait after the first empty look; it doubles up to the longest


class PipeReader:
    """Bytes from a Windows pipe, read only when the pipe already holds them. read(size) and readline() give bytes, and
    b'' once the other end has closed and everything sent has been read."""

    def __init__(self, fd, handle, poll_s=POLL_S):
        self.fd, self.handle, self.poll_s, self.pending = fd, handle, poll_s, b''

    def _chunk(self, size=None):
        """Bytes the pipe holds (at most size), waiting for some; None once the pipe is closed."""
        import _winapi
        wait = min(FIRST_POLL_S, self.poll_s)
        while True:
            try:
                ready = _winapi.PeekNamedPipe(self.handle, 0)[0]
            except OSError:
                return None                    # the other end is closed
            if ready:                          # never more than is there: this read returns at once
                return os.read(self.fd, ready if size is None else min(ready, size)) or None
            time.sleep(wait)
            wait = min(wait * 2, self.poll_s)

    def read(self, size):
        """Up to size bytes, as soon as there are any."""
        if size <= 0:
            return b''
        if self.pending:
            out, self.pending = self.pending[:size], self.pending[size:]
            return out
        return self._chunk(size) or b''

    def readline(self):
        """The next line with its newline; the last one may have none."""
        searched = 0
        while True:
            end = self.pending.find(b'\n', searched)
            if end >= 0:
                break
            searched = len(self.pending)
            chunk = self._chunk()
            if chunk is None:
                end = len(self.pending) - 1
                break
            self.pending += chunk
        line, self.pending = self.pending[:end + 1], self.pending[end + 1:]
        return line

    def __iter__(self):
        return iter(self.readline, b'')


def reader(stream, poll_s=POLL_S):
    """A PipeReader on the stream's Windows pipe, else the stream itself (another system, a file, a console, a StringIO).
    Read nothing from the stream before this: what the stream has already buffered would be lost. poll_s: the longest
    wait between two looks at an empty pipe, the most an arriving byte can wait to be seen."""
    if os.name != 'nt':
        return stream
    try:
        import _winapi
        import msvcrt
        fd = stream.fileno()
        handle = msvcrt.get_osfhandle(fd)
        _winapi.PeekNamedPipe(handle, 0)
    except (AttributeError, OSError, ValueError):
        return stream
    return PipeReader(fd, handle, poll_s)
