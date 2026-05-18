from __future__ import annotations

import inspect
import re
from pathlib import Path

from opensquilla.channels.types import OutgoingMessage


def test_channel_replies_exports_reply_helpers_and_sanitizers() -> None:
    from opensquilla.gateway import channel_replies

    assert callable(channel_replies.terminal_payload_from_exception)
    assert callable(channel_replies.terminal_payload_from_error_event)
    assert callable(channel_replies.terminal_reply_suffix)
    assert callable(channel_replies.sanitize_outgoing_message)
    assert inspect.isclass(channel_replies.DirectiveTagStreamSanitizer)


def test_channel_streaming_exports_runtime_stream_relay() -> None:
    from opensquilla.gateway import channel_streaming

    assert inspect.isclass(channel_streaming.RuntimeChannelStreamRelay)


def test_channel_dispatch_preserves_compatibility_aliases() -> None:
    from opensquilla.gateway import channel_dispatch, channel_replies, channel_streaming

    assert (
        channel_dispatch._terminal_payload_from_exception
        is channel_replies.terminal_payload_from_exception
    )
    assert (
        channel_dispatch._terminal_payload_from_error_event
        is channel_replies.terminal_payload_from_error_event
    )
    assert channel_dispatch._terminal_reply_suffix is channel_replies.terminal_reply_suffix
    assert (
        channel_dispatch._sanitize_outgoing_message
        is channel_replies.sanitize_outgoing_message
    )
    assert (
        channel_dispatch._DirectiveTagStreamSanitizer
        is channel_replies.DirectiveTagStreamSanitizer
    )
    assert (
        channel_dispatch._RuntimeChannelStreamRelay
        is channel_streaming.RuntimeChannelStreamRelay
    )


def test_channel_dispatch_no_longer_defines_moved_reply_or_streaming_symbols() -> None:
    source = Path("src/opensquilla/gateway/channel_dispatch.py").read_text()

    moved_definitions = [
        r"def _terminal_payload_from_exception\b",
        r"def _terminal_payload_from_error_event\b",
        r"def _terminal_reply_suffix\b",
        r"def _sanitize_outgoing_message\b",
        r"class _DirectiveTagStreamSanitizer\b",
        r"class _RuntimeChannelStreamRelay\b",
    ]

    for pattern in moved_definitions:
        assert re.search(pattern, source) is None


def test_sanitize_outgoing_message_strips_inline_reply_directives() -> None:
    from opensquilla.gateway.channel_replies import sanitize_outgoing_message

    original = OutgoingMessage(
        content="answer [[reply_to_current]]still here [[reply_to: thread-1]]done"
    )

    cleaned = sanitize_outgoing_message(original)

    assert cleaned.content == "answer still here done"
    assert original.content == (
        "answer [[reply_to_current]]still here [[reply_to: thread-1]]done"
    )


def test_stream_sanitizer_strips_reply_directives_split_across_chunks() -> None:
    from opensquilla.gateway.channel_replies import DirectiveTagStreamSanitizer

    sanitizer = DirectiveTagStreamSanitizer()

    assert sanitizer.clean("hello [[reply_to") == "hello "
    assert sanitizer.clean("_current]]world [[reply_to: th") == "world "
    assert sanitizer.clean("read-1]]tail") == "tail"
    assert sanitizer.flush() == ""
