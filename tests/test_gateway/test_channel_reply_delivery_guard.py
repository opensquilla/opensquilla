"""A user-visible reply must survive — or explain — a provider send failure.

Before the guard, ``_deliver_runtime_channel_reply`` did a bare
``await channel.send(...)``: one raised exception killed the reply task and
the user waited forever for an answer that was fully computed and paid for.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from opensquilla.channels.types import OutgoingMessage
from opensquilla.gateway.channel_dispatch import (
    _REPLY_SEND_ATTEMPTS,
    _deliver_reply_or_notify,
    _send_channel_reply_guarded,
)


def _route() -> SimpleNamespace:
    return SimpleNamespace(channel_id="chat-1", thread_id=None, channel_name="slack-main")


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://p.example/send")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("x", request=request, response=response)


class _Channel:
    """Records every send; fails the first ``fail_times`` with ``error``."""

    def __init__(self, *, fail_times: int = 0, error: BaseException | None = None) -> None:
        self.sent: list[OutgoingMessage] = []
        self._fail_times = fail_times
        self._error = error or _http_error(503)

    async def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)
        if len(self.sent) <= self._fail_times:
            raise self._error


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_delay: float) -> None:
        return None

    monkeypatch.setattr("opensquilla.gateway.channel_dispatch.asyncio.sleep", _instant)


async def test_delivered_first_try_returns_none() -> None:
    channel = _Channel()
    result = await _send_channel_reply_guarded(
        channel, OutgoingMessage(content="hi", reply_to="chat-1"), session_key="s"
    )
    assert result is None
    assert len(channel.sent) == 1


async def test_transient_failure_is_retried_then_succeeds() -> None:
    channel = _Channel(fail_times=2, error=_http_error(503))
    result = await _send_channel_reply_guarded(
        channel, OutgoingMessage(content="hi", reply_to="chat-1"), session_key="s"
    )
    assert result is None
    assert len(channel.sent) == 3


async def test_all_attempts_share_one_delivery_id() -> None:
    # The outbox keys a row on delivery_id; retrying without a stable id would
    # spray one row per attempt. Stamp it once and every attempt reuses it.
    channel = _Channel(fail_times=_REPLY_SEND_ATTEMPTS, error=_http_error(503))
    await _send_channel_reply_guarded(
        channel, OutgoingMessage(content="hi", reply_to="chat-1"), session_key="s"
    )
    ids = {m.metadata.get("delivery_id") for m in channel.sent}
    assert len(channel.sent) == _REPLY_SEND_ATTEMPTS
    assert len(ids) == 1 and next(iter(ids))


async def test_fatal_failure_is_not_retried() -> None:
    # A 401 will fail identically on every attempt; retrying just stalls the
    # turn. Surface it after one try.
    channel = _Channel(fail_times=99, error=_http_error(401))
    result = await _send_channel_reply_guarded(
        channel, OutgoingMessage(content="hi", reply_to="chat-1"), session_key="s"
    )
    assert result == "auth_invalid"
    assert len(channel.sent) == 1


async def test_exhausted_retries_return_the_failure_class() -> None:
    channel = _Channel(fail_times=99, error=_http_error(503))
    result = await _send_channel_reply_guarded(
        channel, OutgoingMessage(content="hi", reply_to="chat-1"), session_key="s"
    )
    assert result == "transport_transient"
    assert len(channel.sent) == _REPLY_SEND_ATTEMPTS


async def test_on_final_loss_the_user_gets_a_delivery_notice() -> None:
    # A recoverable-looking class that never recovers: the reply is lost, but
    # the user is told it exists rather than left in silence.
    channel = _Channel(fail_times=99, error=_http_error(503))
    delivered = await _deliver_reply_or_notify(
        channel,
        OutgoingMessage(content="the answer", reply_to="chat-1"),
        route_envelope=_route(),
        session_key="s",
    )
    assert delivered is False
    # attempts for the reply, plus exactly one notice send.
    notices = [m for m in channel.sent if m.metadata.get("delivery_failure_notice")]
    assert len(notices) == 1


async def test_no_notice_when_every_send_to_the_target_is_hopeless() -> None:
    # target_missing: a notice would fail identically, so don't burn the call.
    channel = _Channel(fail_times=99, error=_http_error(404))
    delivered = await _deliver_reply_or_notify(
        channel,
        OutgoingMessage(content="the answer", reply_to="chat-1"),
        route_envelope=_route(),
        session_key="s",
    )
    assert delivered is False
    assert not any(m.metadata.get("delivery_failure_notice") for m in channel.sent)


async def test_a_failing_notice_never_masks_the_original_failure() -> None:
    class _AlwaysFails:
        def __init__(self) -> None:
            self.sent: list[Any] = []

        async def send(self, message: OutgoingMessage) -> None:
            self.sent.append(message)
            raise _http_error(503)

    channel = _AlwaysFails()
    # Must not raise even though the notice send also fails.
    delivered = await _deliver_reply_or_notify(
        channel,
        OutgoingMessage(content="x", reply_to="chat-1"),
        route_envelope=_route(),
        session_key="s",
    )
    assert delivered is False


async def test_success_after_notice_path_is_never_reached_on_delivery() -> None:
    channel = _Channel()
    delivered = await _deliver_reply_or_notify(
        channel,
        OutgoingMessage(content="hi", reply_to="chat-1"),
        route_envelope=_route(),
        session_key="s",
    )
    assert delivered is True
    assert not any(m.metadata.get("delivery_failure_notice") for m in channel.sent)
