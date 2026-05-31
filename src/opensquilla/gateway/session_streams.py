"""In-memory session stream replay buffers for gateway events."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BufferedSessionEvent:
    event_name: str
    payload: dict[str, Any]
    stream_seq: int


@dataclass(frozen=True)
class ReplayResult:
    current_stream_seq: int
    replay_complete: bool
    events: list[BufferedSessionEvent]
    gap_reason: str | None = None


class SessionStreamRegistry:
    """Small in-memory replay buffer keyed by session.

    The WebSocket frame ``seq`` is per connection. ``stream_seq`` is per
    session and survives reconnects long enough to replay recent run events.
    """

    def __init__(self, *, max_events_per_session: int = 500) -> None:
        self._max_events_per_session = max_events_per_session
        self._seq_by_session: dict[str, int] = {}
        self._events_by_session: dict[str, deque[BufferedSessionEvent]] = {}

    @staticmethod
    def _is_replay_lossy(event_name: str) -> bool:
        return event_name in {
            "session.event.text_delta",
            "session.event.run_heartbeat",
        }

    def _trim_session_events(self, events: deque[BufferedSessionEvent]) -> None:
        while len(events) > self._max_events_per_session:
            for index, event in enumerate(events):
                if self._is_replay_lossy(event.event_name):
                    del events[index]
                    break
            else:
                events.popleft()

    def current_seq(self, session_key: str) -> int:
        return self._seq_by_session.get(session_key, 0)

    def record(
        self,
        session_key: str,
        event_name: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        stream_seq = self.current_seq(session_key) + 1
        self._seq_by_session[session_key] = stream_seq

        enriched = dict(payload or {})
        enriched["session_key"] = session_key
        enriched["stream_seq"] = stream_seq

        event = BufferedSessionEvent(event_name=event_name, payload=enriched, stream_seq=stream_seq)
        events = self._events_by_session.setdefault(session_key, deque())
        events.append(event)
        self._trim_session_events(events)
        return enriched

    def replay(self, session_key: str, since_stream_seq: int | None) -> ReplayResult:
        current = self.current_seq(session_key)
        if since_stream_seq is None:
            return ReplayResult(current_stream_seq=current, replay_complete=True, events=[])

        events = list(self._events_by_session.get(session_key, ()))
        if current == 0:
            return ReplayResult(
                current_stream_seq=0,
                replay_complete=since_stream_seq == 0,
                events=[],
                gap_reason=None if since_stream_seq == 0 else "stream_buffer_reset",
            )

        if since_stream_seq > current:
            return ReplayResult(
                current_stream_seq=current,
                replay_complete=False,
                events=[],
                gap_reason="cursor_ahead_of_stream",
            )

        if since_stream_seq == current:
            return ReplayResult(current_stream_seq=current, replay_complete=True, events=[])

        if not events:
            return ReplayResult(
                current_stream_seq=current,
                replay_complete=False,
                events=[],
                gap_reason="stream_buffer_empty",
            )

        first_seq = events[0].stream_seq
        replay_complete = since_stream_seq >= first_seq - 1
        replay_events = [event for event in events if event.stream_seq > since_stream_seq]
        return ReplayResult(
            current_stream_seq=current,
            replay_complete=replay_complete,
            events=replay_events,
            gap_reason=None if replay_complete else "buffer_window_missed",
        )


_session_streams = SessionStreamRegistry()


def get_session_streams() -> SessionStreamRegistry:
    return _session_streams
