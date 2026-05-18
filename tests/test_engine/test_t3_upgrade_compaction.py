"""Tests for TurnRunner._maybe_compact_on_t3_upgrade()."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine.pipeline import TurnContext
from opensquilla.engine.runtime import TurnRunner
from opensquilla.session.models import TranscriptEntry

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeSessionManager:
    def __init__(self, transcript: list[TranscriptEntry] | None = None) -> None:
        self._transcript = transcript or []
        self.compact_calls: list[tuple[str, int]] = []

    async def get_transcript(self, session_key: str, **kwargs: Any) -> list[TranscriptEntry]:
        return list(self._transcript)

    async def compact(self, session_key: str, context_window_tokens: int, **kwargs: Any) -> str:
        self.compact_calls.append((session_key, context_window_tokens))
        return "summary"


@dataclass(frozen=True)
class _FakeFlushReceipt:
    mode: str = "llm"
    flushed_paths: list[str] = field(default_factory=list)
    slug: str | None = None
    message_count: int = 1
    duration_ms: int = 10
    raw_reason: str | None = None
    error: str | None = None
    integrity_status: str = "ok"
    indexed_chunk_count: int = 1
    output_coverage_status: str = "ok"
    invalid_candidate_count: int = 0
    candidate_missing_ids: list[str] = field(default_factory=list)
    obligation_status: str = "ok"
    obligation_missing_ids: list[str] = field(default_factory=list)


class _FakeFlushService:
    def __init__(
        self,
        receipt: _FakeFlushReceipt | None = None,
        raise_exc: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._receipt = receipt or _FakeFlushReceipt()
        self._raise_exc = raise_exc
        self._delay_seconds = delay_seconds
        self.execute_calls: list[dict[str, Any]] = []

    async def execute(self, transcript: Any, session_key: str, **kwargs: Any) -> _FakeFlushReceipt:
        self.execute_calls.append({"session_key": session_key, **kwargs})
        if self._delay_seconds:
            import asyncio

            await asyncio.sleep(self._delay_seconds)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._receipt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_transcript() -> list[TranscriptEntry]:
    return [
        TranscriptEntry(
            session_id="s1",
            session_key="agent:main:webchat:default",
            role="user",
            content="hello",
        ),
        TranscriptEntry(
            session_id="s1",
            session_key="agent:main:webchat:default",
            role="assistant",
            content="hi there",
        ),
    ]


def _make_turn(
    routed_tier: str = "t3",
    previous_tier: str | None = "t2",
    base_tier: str | None = None,
    final_tier: str | None = None,
    routing_applied: bool = True,
) -> TurnContext:
    routing_extra: dict[str, Any] = {}
    if previous_tier is not None:
        routing_extra["previous_tier"] = previous_tier
    if base_tier is not None:
        routing_extra["base_tier"] = base_tier
    if final_tier is not None:
        routing_extra["final_tier"] = final_tier

    return TurnContext(
        message="test",
        session_key="agent:main:webchat:default",
        config=None,
        provider=None,
        model="anthropic/claude-opus-4.7",
        tool_defs=[],
        system_prompt="you are helpful",
        metadata={
            "routed_tier": routed_tier,
            "routing_applied": routing_applied,
            "routing_extra": routing_extra,
        },
    )


def _make_runner(
    session_manager: Any = None,
    flush_service: Any = None,
    enabled: bool = True,
    *,
    flush_enabled: bool = True,
    flush_timeout_seconds: float = 5.0,
    flush_background_timeout_seconds: float = 60.0,
) -> TurnRunner:
    config = SimpleNamespace(
        squilla_router=SimpleNamespace(upgrade_to_t3_compaction_enabled=enabled),
        memory=SimpleNamespace(
            flush_enabled=flush_enabled,
            flush_timeout_seconds=flush_timeout_seconds,
            flush_background_timeout_seconds=flush_background_timeout_seconds,
        ),
    )
    return TurnRunner(
        provider_selector=SimpleNamespace(clone=lambda: SimpleNamespace()),
        session_manager=session_manager,
        config=config,
        session_flush_service=flush_service,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t2_to_t3_triggers_flush_then_compact() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService()
    runner = _make_runner(session_manager=sm, flush_service=fs)

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "handled"
    assert len(fs.execute_calls) == 1
    assert len(sm.compact_calls) == 1
    assert sm.compact_calls[0] == ("agent:main:webchat:default", 100_000)


@pytest.mark.asyncio
async def test_t0_t1_to_t3_triggers() -> None:
    for prev in ("t0", "t1"):
        sm = _FakeSessionManager(_sample_transcript())
        fs = _FakeFlushService()
        runner = _make_runner(session_manager=sm, flush_service=fs)

        turn = _make_turn(routed_tier="t3", previous_tier=prev)
        result = await runner._maybe_compact_on_t3_upgrade(
            "agent:main:webchat:default", turn, 100_000
        )

        assert result == "handled", f"failed for previous_tier={prev}"
        assert len(fs.execute_calls) == 1
        assert len(sm.compact_calls) == 1


@pytest.mark.asyncio
async def test_t3_to_t3_skips() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService()
    runner = _make_runner(session_manager=sm, flush_service=fs)

    turn = _make_turn(routed_tier="t3", previous_tier="t3")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "not_applicable"
    assert len(fs.execute_calls) == 0
    assert len(sm.compact_calls) == 0


@pytest.mark.asyncio
async def test_non_t3_route_skips() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService()
    runner = _make_runner(session_manager=sm, flush_service=fs)

    turn = _make_turn(routed_tier="t1", previous_tier="t0")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "not_applicable"
    assert len(fs.execute_calls) == 0
    assert len(sm.compact_calls) == 0


@pytest.mark.asyncio
async def test_config_disabled_skips() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService()
    runner = _make_runner(session_manager=sm, flush_service=fs, enabled=False)

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "not_applicable"
    assert len(fs.execute_calls) == 0
    assert len(sm.compact_calls) == 0


@pytest.mark.asyncio
async def test_observe_mode_skips() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService()
    runner = _make_runner(session_manager=sm, flush_service=fs)

    turn = _make_turn(routed_tier="t3", previous_tier="t2", routing_applied=False)
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "not_applicable"
    assert len(fs.execute_calls) == 0
    assert len(sm.compact_calls) == 0


@pytest.mark.asyncio
async def test_flush_raises_does_not_block_compaction() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService(raise_exc=RuntimeError("flush boom"))
    runner = _make_runner(session_manager=sm, flush_service=fs)

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "handled"
    assert len(fs.execute_calls) == 1
    assert len(sm.compact_calls) == 1


@pytest.mark.asyncio
async def test_flush_error_receipt_does_not_block_compaction() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService(receipt=_FakeFlushReceipt(mode="error", error="provider down"))
    runner = _make_runner(session_manager=sm, flush_service=fs)

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "handled"
    assert len(fs.execute_calls) == 1
    assert len(sm.compact_calls) == 1


@pytest.mark.parametrize(
    "receipt",
    [
        _FakeFlushReceipt(mode="raw", raw_reason="no_provider"),
        _FakeFlushReceipt(integrity_status="missing_chunks"),
        _FakeFlushReceipt(output_coverage_status="coverage_warning"),
        _FakeFlushReceipt(invalid_candidate_count=1),
        _FakeFlushReceipt(candidate_missing_ids=["candidate-1"]),
        _FakeFlushReceipt(obligation_missing_ids=["obligation-1"]),
    ],
)
@pytest.mark.asyncio
async def test_degraded_flush_receipts_do_not_block_compaction(
    receipt: _FakeFlushReceipt,
) -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService(receipt=receipt)
    runner = _make_runner(session_manager=sm, flush_service=fs)

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "handled"
    assert len(fs.execute_calls) == 1
    assert len(sm.compact_calls) == 1


@pytest.mark.asyncio
async def test_backfilled_flush_receipt_allows_compact() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService(receipt=_FakeFlushReceipt(obligation_status="backfilled"))
    runner = _make_runner(session_manager=sm, flush_service=fs)

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "handled"
    assert len(fs.execute_calls) == 1
    assert len(sm.compact_calls) == 1


@pytest.mark.asyncio
async def test_t3_flush_uses_background_timeout_for_service_call() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService()
    runner = _make_runner(
        session_manager=sm,
        flush_service=fs,
        flush_timeout_seconds=0.25,
        flush_background_timeout_seconds=42.0,
    )

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "handled"
    assert fs.execute_calls[0]["timeout"] == 42.0


@pytest.mark.asyncio
async def test_t3_flush_grace_timeout_does_not_block_compaction() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    fs = _FakeFlushService(delay_seconds=0.05)
    runner = _make_runner(
        session_manager=sm,
        flush_service=fs,
        flush_timeout_seconds=0.001,
        flush_background_timeout_seconds=42.0,
    )

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "handled"
    assert fs.execute_calls[0]["timeout"] == 42.0
    assert len(sm.compact_calls) == 1


@pytest.mark.asyncio
async def test_memory_flush_disabled_compacts_without_flush_service() -> None:
    sm = _FakeSessionManager(_sample_transcript())
    runner = _make_runner(
        session_manager=sm,
        flush_service=None,
        flush_enabled=False,
    )

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "handled"
    assert len(sm.compact_calls) == 1


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
@pytest.mark.asyncio
async def test_env_flush_disabled_compacts_without_flush_service(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_SESSION_FLUSH", value)
    sm = _FakeSessionManager(_sample_transcript())
    runner = _make_runner(session_manager=sm, flush_service=None)

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "handled"
    assert len(sm.compact_calls) == 1


@pytest.mark.asyncio
async def test_compact_raises_continues() -> None:
    sm = _FakeSessionManager(_sample_transcript())

    async def _boom(session_key: str, context_window_tokens: int, **kw: Any) -> str:
        raise RuntimeError("compact boom")

    sm.compact = _boom  # type: ignore[assignment]
    fs = _FakeFlushService()
    runner = _make_runner(session_manager=sm, flush_service=fs)

    turn = _make_turn(routed_tier="t3", previous_tier="t2")
    result = await runner._maybe_compact_on_t3_upgrade(
        "agent:main:webchat:default", turn, 100_000
    )

    assert result == "compact_failed"
    assert len(fs.execute_calls) == 1
