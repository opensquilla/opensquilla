"""Tests for pre-flight compaction (Feature D).

Covers:
- Pre-flight triggers when transcript exceeds the configured context-window ratio
- Pre-flight does NOT trigger when under threshold
- cron: and subagent: sessions are skipped
- Missing sessions don't error
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opensquilla.engine.runtime import TurnRunner
from opensquilla.gateway.config import GatewayConfig
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import Message, ModelInfo
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.session.compaction import CompactionConfig
from opensquilla.session.manager import SessionManager
from opensquilla.session.models import TranscriptEntry
from opensquilla.session.storage import SessionStorage
from opensquilla.tools.types import CallerKind, ToolContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(content: str, role: str = "user") -> TranscriptEntry:
    return TranscriptEntry(
        session_id="test-session-id",
        session_key="test:key",
        role=role,
        content=content,
    )


def _flush_receipt(**overrides):
    payload = {
        "mode": "llm",
        "error": None,
        "indexed_chunk_count": 1,
        "integrity_status": "ok",
        "output_coverage_status": "ok",
        "invalid_candidate_count": 0,
        "candidate_missing_ids": [],
        "obligation_status": "ok",
        "obligation_missing_ids": [],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class _FakeCompactionProvider:
    provider_name = "openai"

    def __init__(self, model: str = "provider/model") -> None:
        self._api_key = "preflight-provider-key"
        self._model = model
        self._base_url = "https://openrouter.ai/api/v1"

    @property
    def model(self) -> str:
        return self._model

    def chat(self, messages: list[Message], tools=None, config=None) -> AsyncIterator:
        return self._stream()

    async def _stream(self) -> AsyncIterator:
        yield ProviderText(text="ok")
        yield ProviderDone(stop_reason="end_turn", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[ModelInfo]:
        return []


class _FakeSelectorClone:
    current_config = SimpleNamespace(model="provider/model")

    def __init__(self, provider: _FakeCompactionProvider) -> None:
        self.provider = provider
        self.override_calls: list[str] = []

    def override_model(self, model: str) -> None:
        self.override_calls.append(model)
        self.provider._model = model
        self.current_config = SimpleNamespace(model=model)

    def resolve(self) -> _FakeCompactionProvider:
        return self.provider


class _FakeProviderSelector:
    current_config = SimpleNamespace(model="provider/model")

    def __init__(self, provider: _FakeCompactionProvider | None = None) -> None:
        self.provider = provider or _FakeCompactionProvider()
        self.clone_instance = _FakeSelectorClone(self.provider)
        self.override_calls: list[str] = []

    def clone(self) -> _FakeSelectorClone:
        return self.clone_instance

    def override_model(self, model: str) -> None:
        self.override_calls.append(model)

    def resolve(self) -> _FakeCompactionProvider:
        return self.provider


@pytest.fixture
async def session_mgr():
    storage = SessionStorage(":memory:")
    await storage.connect()
    mgr = SessionManager(storage)
    yield mgr
    await storage.close()


# ---------------------------------------------------------------------------
# Tests: _maybe_preflight_compact
# ---------------------------------------------------------------------------


def test_preflight_compaction_coordinator_module_contract_exists() -> None:
    """Engine preflight orchestration has an importable coordinator boundary."""

    module = importlib.import_module("opensquilla.engine.preflight_compaction")

    assert hasattr(module, "PreflightCompactionCoordinator")
    assert module.T3_HANDLED == "handled"
    assert module.T3_FLUSH_FAILED == "flush_failed"
    assert module.flush_receipt_allows_destructive_compaction(
        _flush_receipt(obligation_status="backfilled")
    )
    assert not module.flush_receipt_allows_destructive_compaction(
        _flush_receipt(obligation_missing_ids=["missing"])
    )


def test_turn_runner_delegates_preflight_helpers_to_coordinator() -> None:
    """TurnRunner should remain the composition owner, not the policy owner."""

    module = importlib.import_module("opensquilla.engine.preflight_compaction")

    assert (
        TurnRunner._flush_receipt_allows_destructive_compaction
        is module.flush_receipt_allows_destructive_compaction
    )
    source = inspect.getsource(TurnRunner._maybe_preflight_compact)
    assert "PreflightCompactionCoordinator" in source
    assert "estimate_tokens" not in source


@pytest.mark.asyncio
async def test_preflight_no_session_manager_is_noop() -> None:
    """When session_manager is None, pre-flight silently returns."""
    runner = TurnRunner(provider_selector=MagicMock(), session_manager=None)
    # Should not raise
    await runner._maybe_preflight_compact("some:session", 200_000)


@pytest.mark.asyncio
async def test_preflight_skips_cron_sessions() -> None:
    """cron: prefixed sessions are skipped regardless of token count."""
    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock()
    mock_sm.get_transcript = AsyncMock()

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)
    await runner._maybe_preflight_compact("cron:daily-job", 200_000)

    mock_sm.get_transcript.assert_not_called()
    mock_sm.compact.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_skips_subagent_sessions() -> None:
    """subagent: prefixed sessions are skipped regardless of token count."""
    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock()
    mock_sm.get_transcript = AsyncMock()

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)
    await runner._maybe_preflight_compact("subagent:worker-1", 200_000)

    mock_sm.get_transcript.assert_not_called()
    mock_sm.compact.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_missing_session_does_not_error() -> None:
    """KeyError from get_transcript (session doesn't exist) is swallowed."""
    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock()
    mock_sm.get_transcript = AsyncMock(side_effect=KeyError("Session not found"))

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)
    # Should not raise
    await runner._maybe_preflight_compact("missing:session", 200_000)

    mock_sm.compact.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_empty_transcript_is_noop() -> None:
    """Empty transcript skips compaction."""
    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock()
    mock_sm.get_transcript = AsyncMock(return_value=[])

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)
    await runner._maybe_preflight_compact("user:session", 200_000)

    mock_sm.compact.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_under_threshold_does_not_compact() -> None:
    """Transcript under the configured context-window ratio → no compaction."""
    # 100 tokens worth of content (estimate_tokens("x" * 400) ≈ 100 with len//4 fallback)
    entries = [_make_entry("x" * 400)]  # ~100 tokens

    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)
    # Threshold = 200_000 * 0.85 = 170_000 — 100 tokens is well under
    await runner._maybe_preflight_compact("user:session", 200_000)

    mock_sm.compact.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_uses_configured_compaction_ratio() -> None:
    """Operators can tune the preflight threshold without code changes."""
    context_window = 1000
    entries = [_make_entry("a")]

    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock(return_value="summary text")
    mock_sm.get_transcript = AsyncMock(return_value=entries)

    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        config=SimpleNamespace(preflight_compact_ratio=0.5),
    )

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=600):
        await runner._maybe_preflight_compact("user:session", context_window)

    mock_sm.compact.assert_called_once_with("user:session", context_window)


@pytest.mark.asyncio
async def test_preflight_above_threshold_triggers_compact() -> None:
    """Transcript exceeding the default 85% context-window ratio triggers compaction."""
    # Use patch to control estimate_tokens so threshold math is deterministic
    context_window = 1000

    # Create entries whose total estimated tokens exceed threshold
    entries = [_make_entry("a" * 4000)]  # len//4 = 1000 tokens > 850

    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock(return_value="summary text")
    mock_sm.get_transcript = AsyncMock(return_value=entries)

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact("user:session", context_window)

    mock_sm.compact.assert_called_once_with("user:session", context_window)


@pytest.mark.asyncio
async def test_preflight_flushes_full_transcript_before_compact() -> None:
    """Preflight compaction must give durable memory a full-coverage chance first."""

    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    calls: list[str] = []

    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)

    async def compact(session_key, context_window_tokens):
        calls.append("compact")
        return "summary text"

    mock_sm.compact = AsyncMock(side_effect=compact)

    flush_service = MagicMock()

    async def flush_execute(*args, **kwargs):
        calls.append("flush")
        return _flush_receipt()

    flush_service.execute = AsyncMock(side_effect=flush_execute)

    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        session_flush_service=flush_service,
    )

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact("agent:ops:long-session", context_window)

    assert calls == ["flush", "compact"]
    flush_service.execute.assert_awaited_once_with(
        entries,
        "agent:ops:long-session",
        agent_id="ops",
        message_window=0,
        segment_mode="auto",
        timeout=5.0,
    )
    mock_sm.compact.assert_awaited_once_with("agent:ops:long-session", context_window)


@pytest.mark.parametrize(
    "receipt",
    [
        _flush_receipt(mode="raw", raw_reason="no_provider"),
        _flush_receipt(integrity_status="missing_chunks"),
        _flush_receipt(output_coverage_status="coverage_warning"),
        _flush_receipt(invalid_candidate_count=1),
        _flush_receipt(candidate_missing_ids=["candidate-1"]),
        _flush_receipt(obligation_missing_ids=["obligation-1"]),
    ],
)
@pytest.mark.asyncio
async def test_preflight_degraded_flush_receipts_skip_compact(receipt: SimpleNamespace) -> None:
    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)
    mock_sm.compact = AsyncMock(return_value="summary text")

    flush_service = MagicMock()
    flush_service.execute = AsyncMock(return_value=receipt)
    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        session_flush_service=flush_service,
    )

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact("agent:ops:long-session", context_window)

    flush_service.execute.assert_awaited_once()
    mock_sm.compact.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_backfilled_flush_receipt_allows_compact() -> None:
    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)
    mock_sm.compact = AsyncMock(return_value="summary text")

    flush_service = MagicMock()
    flush_service.execute = AsyncMock(return_value=_flush_receipt(obligation_status="backfilled"))
    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        session_flush_service=flush_service,
    )

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact("agent:ops:long-session", context_window)

    flush_service.execute.assert_awaited_once()
    mock_sm.compact.assert_awaited_once_with("agent:ops:long-session", context_window)


@pytest.mark.asyncio
async def test_preflight_uses_configured_memory_flush_timeout() -> None:
    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)
    mock_sm.compact = AsyncMock(return_value="summary text")

    flush_service = MagicMock()
    flush_service.execute = AsyncMock(return_value=_flush_receipt())
    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        session_flush_service=flush_service,
        config=SimpleNamespace(
            memory=SimpleNamespace(flush_enabled=True, flush_timeout_seconds=0.25)
        ),
    )

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact("agent:ops:long-session", context_window)

    assert flush_service.execute.await_args.kwargs["timeout"] == 0.25
    mock_sm.compact.assert_awaited_once_with("agent:ops:long-session", context_window)


@pytest.mark.asyncio
async def test_preflight_memory_flush_disabled_compacts_without_flush() -> None:
    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)
    mock_sm.compact = AsyncMock(return_value="summary text")

    flush_service = MagicMock()
    flush_service.execute = AsyncMock(return_value=_flush_receipt())
    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        session_flush_service=flush_service,
        config=SimpleNamespace(
            memory=SimpleNamespace(flush_enabled=False, flush_timeout_seconds=0.25)
        ),
    )

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact("agent:ops:long-session", context_window)

    flush_service.execute.assert_not_called()
    mock_sm.compact.assert_awaited_once_with("agent:ops:long-session", context_window)


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
@pytest.mark.asyncio
async def test_preflight_env_flush_disabled_compacts_without_flush(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_SESSION_FLUSH", value)
    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)
    mock_sm.compact = AsyncMock(return_value="summary text")

    flush_service = MagicMock()
    flush_service.execute = AsyncMock(return_value=_flush_receipt())
    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        session_flush_service=flush_service,
        config=SimpleNamespace(
            memory=SimpleNamespace(flush_enabled=True, flush_timeout_seconds=0.25)
        ),
    )

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact("agent:ops:long-session", context_window)

    flush_service.execute.assert_not_called()
    mock_sm.compact.assert_awaited_once_with("agent:ops:long-session", context_window)


@pytest.mark.asyncio
async def test_preflight_flush_service_unavailable_skips_compact_when_enabled() -> None:
    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)
    mock_sm.compact = AsyncMock(return_value="summary text")

    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        session_flush_service=None,
        config=SimpleNamespace(
            memory=SimpleNamespace(flush_enabled=True, flush_timeout_seconds=0.25)
        ),
    )

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact("agent:ops:long-session", context_window)

    mock_sm.compact.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_passes_provider_backed_compaction_config_after_flush() -> None:
    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    captured_configs: list[CompactionConfig | None] = []

    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)

    async def compact(session_key, context_window_tokens, config=None):
        captured_configs.append(config)
        return "summary text"

    mock_sm.compact = AsyncMock(side_effect=compact)

    flush_service = MagicMock()
    flush_service.execute = AsyncMock(return_value=_flush_receipt())

    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        session_flush_service=flush_service,
        config=SimpleNamespace(
            compaction=SimpleNamespace(enabled=True, model=None, timeout_seconds=17.5)
        ),
    )
    provider = _FakeCompactionProvider(model="provider/model")

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact(
            "agent:ops:long-session",
            context_window,
            compaction_provider=provider,
            compaction_model="routed/model",
        )

    assert len(captured_configs) == 1
    config = captured_configs[0]
    assert isinstance(config, CompactionConfig)
    assert config.api_key == "preflight-provider-key"
    assert config.model == "routed/model"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.timeout_seconds == 17.5


@pytest.mark.asyncio
async def test_preflight_keeps_legacy_compact_manager_compatible() -> None:
    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    calls: list[tuple[str, int]] = []

    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)

    async def compact(session_key, context_window_tokens):
        calls.append((session_key, context_window_tokens))
        return "summary text"

    mock_sm.compact = AsyncMock(side_effect=compact)

    runner = TurnRunner(
        provider_selector=MagicMock(),
        session_manager=mock_sm,
        config=SimpleNamespace(
            compaction=SimpleNamespace(enabled=True, model=None, timeout_seconds=17.5)
        ),
    )

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact(
            "agent:ops:long-session",
            context_window,
            compaction_provider=_FakeCompactionProvider(model="provider/model"),
            compaction_model="routed/model",
        )

    assert calls == [("agent:ops:long-session", context_window)]


@pytest.mark.asyncio
async def test_run_falls_back_to_generic_preflight_after_t3_flush_failed() -> None:
    selector = _FakeProviderSelector()
    runner = TurnRunner(provider_selector=selector, config=GatewayConfig())
    seen: dict[str, object] = {}

    async def fake_t3(session_key, turn, context_window_tokens, **kwargs):
        seen["t3_session_key"] = session_key
        return "flush_failed"

    async def spy_preflight(session_key, context_window_tokens, **kwargs):
        seen["preflight_session_key"] = session_key
        seen.update(kwargs)

    runner._maybe_compact_on_t3_upgrade = fake_t3  # type: ignore[method-assign]
    runner._maybe_preflight_compact = spy_preflight  # type: ignore[method-assign]
    tool_ctx = ToolContext(is_owner=True, caller_kind=CallerKind.CLI)

    async for _ in runner.run(
        "hello",
        "agent:main:abc123",
        tool_context=tool_ctx,
        model="routed/model",
    ):
        pass

    assert seen["t3_session_key"] == "agent:main:abc123"
    assert seen["preflight_session_key"] == "agent:main:abc123"
    assert seen["compaction_model"] == "routed/model"


@pytest.mark.parametrize("t3_result", ["handled", "compact_failed"])
@pytest.mark.asyncio
async def test_run_skips_generic_preflight_after_terminal_t3_result(t3_result: str) -> None:
    selector = _FakeProviderSelector()
    runner = TurnRunner(provider_selector=selector, config=GatewayConfig())
    seen: dict[str, object] = {}

    async def fake_t3(session_key, turn, context_window_tokens, **kwargs):
        seen["t3_session_key"] = session_key
        return t3_result

    async def fail_preflight(session_key, context_window_tokens, **kwargs):
        raise AssertionError("generic preflight should not run after terminal T3 result")

    runner._maybe_compact_on_t3_upgrade = fake_t3  # type: ignore[method-assign]
    runner._maybe_preflight_compact = fail_preflight  # type: ignore[method-assign]
    tool_ctx = ToolContext(is_owner=True, caller_kind=CallerKind.CLI)

    async for _ in runner.run(
        "hello",
        "agent:main:abc123",
        tool_context=tool_ctx,
        model="routed/model",
    ):
        pass

    assert seen["t3_session_key"] == "agent:main:abc123"


@pytest.mark.asyncio
async def test_run_forwards_routed_provider_and_model_to_preflight() -> None:
    selector = _FakeProviderSelector()
    runner = TurnRunner(provider_selector=selector, config=GatewayConfig())
    seen: dict[str, object] = {}

    async def spy_preflight(session_key, context_window_tokens, **kwargs):
        seen["session_key"] = session_key
        seen["context_window_tokens"] = context_window_tokens
        seen.update(kwargs)

    runner._maybe_preflight_compact = spy_preflight  # type: ignore[method-assign]
    tool_ctx = ToolContext(is_owner=True, caller_kind=CallerKind.CLI)

    async for _ in runner.run(
        "hello",
        "agent:main:abc123",
        tool_context=tool_ctx,
        model="routed/model",
    ):
        pass

    assert seen["session_key"] == "agent:main:abc123"
    assert seen["compaction_model"] == "routed/model"
    assert getattr(seen["compaction_provider"], "model") == "routed/model"
    assert selector.override_calls == []
    assert selector.clone_instance.override_calls[-1] == "routed/model"


@pytest.mark.asyncio
async def test_preflight_compact_called_with_correct_args() -> None:
    """compact() is called with (session_key, context_window_tokens)."""
    entries = [_make_entry("content")]

    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock(return_value="")
    mock_sm.get_transcript = AsyncMock(return_value=entries)

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=90_000):
        await runner._maybe_preflight_compact("user:long-session", 100_000)

    mock_sm.compact.assert_called_once_with("user:long-session", 100_000)


@pytest.mark.asyncio
async def test_preflight_exactly_at_threshold_does_not_compact() -> None:
    """Transcript at exactly the threshold (not exceeding) → no compaction."""
    context_window = 1000
    threshold = int(context_window * 0.85)  # default threshold: 850

    entries = [_make_entry("a")]

    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=threshold):
        await runner._maybe_preflight_compact("user:session", context_window)

    mock_sm.compact.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_integration_with_real_session_manager(session_mgr) -> None:
    """Integration: pre-flight with real SessionManager calls compact() when over threshold."""
    mgr = session_mgr
    key = "user:preflight-test"
    await mgr.create(key)

    # Seed transcript entries
    await mgr.append_message(key, role="user", content="message one")
    await mgr.append_message(key, role="assistant", content="reply one")
    await mgr.append_message(key, role="user", content="message two")

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mgr)

    # Patch compact() on the real manager to verify it gets called
    original_compact = mgr.compact
    compact_calls: list[tuple] = []

    async def _spy_compact(session_key, context_window_tokens, config=None):
        compact_calls.append((session_key, context_window_tokens))
        return await original_compact(session_key, context_window_tokens, config)

    mgr.compact = _spy_compact  # type: ignore[method-assign]

    # Force all tokens to exceed the default threshold (100 * 0.85 = 85)
    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact(key, 100)

    # compact() was invoked with the correct args
    assert len(compact_calls) == 1
    assert compact_calls[0] == (key, 100)


@pytest.mark.asyncio
async def test_preflight_compaction_circuit_breaker_retries_after_cooldown() -> None:
    context_window = 1000
    entries = [_make_entry("a" * 4000)]

    mock_sm = MagicMock()
    mock_sm.compact = AsyncMock(side_effect=RuntimeError("compact failed"))
    mock_sm.get_transcript = AsyncMock(return_value=entries)

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        for _ in range(4):
            await runner._maybe_preflight_compact("user:session", context_window)

    assert mock_sm.compact.await_count == 3

    runner._compaction_failures["user:session"].opened_at = 0.0
    with (
        patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000),
        patch("opensquilla.engine.runtime.time.monotonic", return_value=999.0),
    ):
        await runner._maybe_preflight_compact("user:session", context_window)

    assert mock_sm.compact.await_count == 4
