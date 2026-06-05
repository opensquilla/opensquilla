"""Byte-level ANSI sequence assertions for terminal writer collision detection.

These helpers pin the invariant that the concurrent chat REPL never emits a
malformed pairing of cursor, line-erase, or cursor-up sequences across the
combined stream, slash-handler, approval-suspend, and resume window.

The helpers here operate on raw byte streams (not Rich renderables) so
they catch the actual escape sequences the terminal would see, including
any sequences emitted directly by the frontend renderer or by Rich's Console
under the hood.

Sequence reference:

  ``\\x1b[?25l``  hide cursor (DECRST 25)
  ``\\x1b[?25h``  show cursor (DECSET 25)
  ``\\x1b[2K``    erase entire line in current row
  ``\\x1b[<n>A``  move cursor up N rows
"""

from __future__ import annotations

import re

# Pre-compiled patterns kept module-private so callers reuse the same
# regex object across the test matrix rather than re-compiling per call.
_CURSOR_UP_RE = re.compile(rb"\x1b\[\d*A")


def count_sequence(byte_stream: bytes, seq: bytes) -> int:
    """Return the number of non-overlapping ``seq`` occurrences in ``byte_stream``.

    Uses :func:`bytes.count` which performs non-overlapping byte-level
    matching. ``seq`` is matched as a literal substring (no regex).
    """
    return byte_stream.count(seq)


def find_orphan_pairs(
    byte_stream: bytes, open_seq: bytes, close_seq: bytes
) -> list[int]:
    """Return offsets of orphaned ``open_seq`` / ``close_seq`` markers.

    Walks the byte stream in order, tracking a single-slot ``open`` state
    machine: every ``open_seq`` MUST be followed by a ``close_seq`` before
    the next ``open_seq``, and every ``close_seq`` MUST be preceded by an
    unmatched ``open_seq``. Any deviation is recorded as an orphan offset.

    Returns a list of byte offsets where an orphan was detected. An empty
    list means the open/close pairing is balanced.
    """
    if not open_seq or not close_seq:
        raise ValueError("open_seq and close_seq must be non-empty")

    orphans: list[int] = []
    pos = 0
    open_outstanding = False
    while pos < len(byte_stream):
        next_open = byte_stream.find(open_seq, pos)
        next_close = byte_stream.find(close_seq, pos)
        # Neither token found; balance check below decides whether the
        # last unmatched open is an orphan.
        if next_open == -1 and next_close == -1:
            break
        # Pick the earlier of the two markers; bias toward open when they
        # tie so an "open followed by close at the same offset" (which
        # cannot happen for non-overlapping ANSI sequences anyway) still
        # toggles state in the right order.
        if next_open != -1 and (next_close == -1 or next_open <= next_close):
            if open_outstanding:
                # Two opens with no intervening close — the first is an
                # orphan-hide. Record its offset (the earlier one).
                orphans.append(_last_open_offset(byte_stream, open_seq, next_open))
            open_outstanding = True
            pos = next_open + len(open_seq)
        else:
            if not open_outstanding:
                # Close with no matching open — record its offset.
                orphans.append(next_close)
            open_outstanding = False
            pos = next_close + len(close_seq)

    if open_outstanding:
        # Unmatched open hanging at the end — record the last open offset.
        last = byte_stream.rfind(open_seq)
        if last != -1:
            orphans.append(last)
    return orphans


def _last_open_offset(
    byte_stream: bytes, open_seq: bytes, before: int
) -> int:
    """Return the offset of the open marker preceding ``before``.

    Helper for `find_orphan_pairs` so the recorded offset is the *first*
    unmatched open, not the one that overrode it.
    """
    last = byte_stream.rfind(open_seq, 0, before)
    return last if last != -1 else before


def assert_no_orphans(
    byte_stream: bytes, open_seq: bytes, close_seq: bytes
) -> None:
    """Assert balanced ``open_seq`` / ``close_seq`` pairing in ``byte_stream``.

    Raises ``AssertionError`` with a descriptive message including the
    offsets of any detected orphans plus the open/close counts so test
    failures point at the bytes that violated the invariant.
    """
    orphans = find_orphan_pairs(byte_stream, open_seq, close_seq)
    if not orphans:
        return
    open_count = count_sequence(byte_stream, open_seq)
    close_count = count_sequence(byte_stream, close_seq)
    raise AssertionError(
        f"orphan {open_seq!r}/{close_seq!r} pair(s) detected at byte "
        f"offsets {orphans}; open={open_count} close={close_count}; "
        f"stream length={len(byte_stream)}"
    )


def count_cursor_up(byte_stream: bytes) -> int:
    """Return the number of ``\\x1b[<n>A`` cursor-up sequences in ``byte_stream``.

    Matches ``\\x1b[A`` (default 1), ``\\x1b[1A`` ... ``\\x1b[999A``. Other
    CSI parameter forms (``\\x1b[5;2A``) are intentionally NOT matched here
    because the chat REPL never emits them; if a future change does, the
    test should be tightened explicitly.
    """
    return len(_CURSOR_UP_RE.findall(byte_stream))


def find_cursor_up_offsets(byte_stream: bytes) -> list[int]:
    """Return byte offsets of every ``\\x1b[<n>A`` cursor-up sequence."""
    return [m.start() for m in _CURSOR_UP_RE.finditer(byte_stream)]


# Common literals exposed so tests do not have to spell out the escape
# bytes inline. Keeping them as module constants also lets ast-grep land
# on consistent values across the test matrix.
HIDE_CURSOR = b"\x1b[?25l"
SHOW_CURSOR = b"\x1b[?25h"
ERASE_LINE = b"\x1b[2K"
