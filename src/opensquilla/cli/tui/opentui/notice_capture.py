"""Capture stray console output as OpenTUI host notices.

In the OpenTUI backend the host owns the terminal (alternate screen) and is
driven entirely over the fd IPC bridge. Slash-command handlers, however, still
emit their notices with Rich ``console.print``, which writes to ``sys.stdout``.
With nothing intercepting it that output bleeds raw onto the host's screen —
overlapping the composer and clipping (``compact:`` rendered as ``act:``).

This module installs a ``sys.stdout``/``sys.stderr`` replacement (OpenTUI mode
only) that forwards each complete console line to a sink, which the runtime ships
to the host as a ``notice.write`` message. ``isatty()`` returns ``True`` so Rich
keeps emitting its ANSI styling, which the host parses back into theme colors.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable, Iterator


class NoticeForwardingStream:
    """A text stream that forwards complete lines to ``forward`` (not a terminal).

    Partial writes are buffered until a newline (or an explicit ``flush``). The
    sink is wrapped so a failing forward can never break the program that is just
    trying to print.
    """

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, forward: Callable[[str], None]) -> None:
        self._forward = forward
        self._buffer = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        text = data if isinstance(data, str) else str(data)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)
        return len(text)

    def _emit(self, line: str) -> None:
        with contextlib.suppress(Exception):
            self._forward(line)

    def flush(self) -> None:
        if self._buffer:
            line, self._buffer = self._buffer, ""
            self._emit(line)

    def isatty(self) -> bool:
        # Make Rich emit ANSI styling so the host can recolor by severity.
        return True

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def fileno(self) -> int:
        # Not backed by a real descriptor; callers (e.g. Rich size probing) must
        # fall back to a default width rather than touching a terminal.
        raise OSError("NoticeForwardingStream has no fileno")


@contextlib.contextmanager
def capture_stdout_as_notices(forward: Callable[[str], None]) -> Iterator[None]:
    """Redirect ``sys.stdout``/``sys.stderr`` to a notice-forwarding stream.

    Restores the originals on exit (always), flushing any buffered partial line
    first so a trailing prompt fragment is not silently dropped.
    """
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    stream = NoticeForwardingStream(forward)
    sys.stdout = stream
    sys.stderr = stream
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            stream.flush()
        sys.stdout = original_stdout
        sys.stderr = original_stderr
