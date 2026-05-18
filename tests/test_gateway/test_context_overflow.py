"""Tests for the context-overflow policy branches."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from opensquilla.gateway.config import ContextOverflowPolicy, GatewayConfig
from opensquilla.gateway.context_overflow import (
    OverflowOutcome,
    apply_context_overflow_policy,
)
from opensquilla.gateway.rpc_chat import _enforce_context_overflow
from opensquilla.session.compaction import CompactionConfig


@dataclass
class _FakeEntry:
    content: str


class _FakeSessionManager:
    """Minimal session-manager stub: tracks compact() calls + transcript."""

    def __init__(self, transcript: list[_FakeEntry]) -> None:
        self._transcript = list(transcript)
        self.compact_calls: list[tuple[str, int, object | None]] = []

    async def get_transcript(self, session_key: str) -> list[_FakeEntry]:
        return list(self._transcript)

    async def compact(self, session_key: str, budget: int, config=None) -> str:
        # Simulate a successful compaction: collapse history into a single
        # short summary entry so the next estimate fits easily.
        self.compact_calls.append((session_key, budget, config))
        self._transcript = [_FakeEntry(content="[summary]")]
        return "[summary]"


class _LegacyCompactSessionManager(_FakeSessionManager):
    async def compact(self, session_key: str, budget: int) -> str:
        self.compact_calls.append((session_key, budget, None))
        self._transcript = [_FakeEntry(content="[summary]")]
        return "[summary]"


class _FakeCompactionProvider:
    provider_name = "openai"

    def __init__(self) -> None:
        self._api_key = "overflow-provider-key"
        self._model = "provider/model"
        self._base_url = "https://openrouter.ai/api/v1"

    @property
    def model(self) -> str:
        return self._model


class _FakeSelectorClone:
    def __init__(self, provider: _FakeCompactionProvider) -> None:
        self.provider = provider
        self.override_calls: list[str] = []

    def override_model(self, model: str) -> None:
        self.override_calls.append(model)
        self.provider._model = model

    def resolve(self) -> _FakeCompactionProvider:
        return self.provider


class _FakeProviderSelector:
    def __init__(self) -> None:
        self.provider = _FakeCompactionProvider()
        self.clone_instance = _FakeSelectorClone(self.provider)
        self.override_calls: list[str] = []

    def clone(self) -> _FakeSelectorClone:
        return self.clone_instance

    def override_model(self, model: str) -> None:
        self.override_calls.append(model)

    def resolve(self) -> _FakeCompactionProvider:
        return self.provider


def _cfg(policy: ContextOverflowPolicy, budget: int = 20) -> GatewayConfig:
    return GatewayConfig(
        context_overflow_policy=policy,
        context_budget_tokens=budget,
    )


def _history(n_entries: int, chars_per_entry: int) -> list[_FakeEntry]:
    # estimate_tokens rounds chars/4, so ~4 chars ≈ 1 token.
    return [_FakeEntry(content="x" * chars_per_entry) for _ in range(n_entries)]


@pytest.mark.asyncio
async def test_default_policy_is_auto_summarize() -> None:
    """GatewayConfig default policy must be AUTO_SUMMARIZE per S4 AC."""

    cfg = GatewayConfig()
    assert cfg.context_overflow_policy == ContextOverflowPolicy.AUTO_SUMMARIZE
    assert cfg.context_budget_tokens == 100_000


@pytest.mark.asyncio
async def test_policy_enum_has_exactly_three_members() -> None:
    """Locks S4 AC: exactly three policy options, stable string values."""

    values = {m.value for m in ContextOverflowPolicy}
    assert values == {"auto_summarize", "hard_truncate", "refuse"}


@pytest.mark.asyncio
async def test_under_budget_is_noop() -> None:
    cfg = _cfg(ContextOverflowPolicy.REFUSE, budget=10_000)
    outcome = await apply_context_overflow_policy(
        config=cfg,
        message="hi",
        transcript=_history(1, 4),
        session_key="s1",
    )
    assert outcome.over_budget is False
    assert outcome.refusal is None


@pytest.mark.asyncio
async def test_refuse_returns_stable_error_envelope() -> None:
    """REFUSE short-circuits with the documented error envelope."""

    cfg = _cfg(ContextOverflowPolicy.REFUSE, budget=5)
    outcome = await apply_context_overflow_policy(
        config=cfg,
        message="hello",
        transcript=_history(4, 40),
        session_key="s-refuse",
    )
    assert outcome.over_budget is True
    assert outcome.refusal is not None
    env = outcome.refusal
    assert env["status"] == "error"
    assert env["error_class"] == "context_overflow"
    assert env["retry_allowed"] is False
    assert isinstance(env["user_message"], str) and env["user_message"]


@pytest.mark.asyncio
async def test_hard_truncate_drops_oldest_history_until_fits() -> None:
    """HARD_TRUNCATE removes oldest entries one at a time to fit the budget."""

    cfg = _cfg(ContextOverflowPolicy.HARD_TRUNCATE, budget=10)
    transcript = _history(5, 40)  # 5 * 40 chars ≈ 50 tokens per estimate_tokens
    outcome = await apply_context_overflow_policy(
        config=cfg,
        message="m",
        transcript=transcript,
        session_key="s-trunc",
    )
    assert outcome.over_budget is True
    assert outcome.truncated_entries > 0
    # Some entries were dropped; remaining history is shorter than input.
    assert len(outcome.trimmed_history) == len(transcript) - outcome.truncated_entries


@pytest.mark.asyncio
async def test_auto_summarize_invokes_compaction_and_retries_once() -> None:
    """AUTO_SUMMARIZE triggers session_manager.compact() exactly once."""

    cfg = _cfg(ContextOverflowPolicy.AUTO_SUMMARIZE, budget=10)
    sm = _FakeSessionManager(_history(6, 40))
    outcome = await apply_context_overflow_policy(
        config=cfg,
        message="m",
        transcript=sm._transcript,
        session_key="s-auto",
        session_manager=sm,
    )
    assert outcome.over_budget is True
    assert outcome.summarized is True
    assert outcome.retried is True
    assert len(sm.compact_calls) == 1
    assert sm.compact_calls[0][0] == "s-auto"


@pytest.mark.asyncio
async def test_auto_summarize_forwards_compaction_config() -> None:
    cfg = _cfg(ContextOverflowPolicy.AUTO_SUMMARIZE, budget=10)
    sm = _FakeSessionManager(_history(6, 40))
    compaction_config = CompactionConfig(api_key="key", model="model")

    outcome = await apply_context_overflow_policy(
        config=cfg,
        message="m",
        transcript=sm._transcript,
        session_key="s-auto",
        session_manager=sm,
        compaction_config=compaction_config,
    )

    assert outcome.summarized is True
    assert sm.compact_calls == [("s-auto", 10, compaction_config)]


@pytest.mark.asyncio
async def test_auto_summarize_keeps_legacy_compact_manager_compatible() -> None:
    cfg = _cfg(ContextOverflowPolicy.AUTO_SUMMARIZE, budget=10)
    sm = _LegacyCompactSessionManager(_history(6, 40))
    compaction_config = CompactionConfig(api_key="key", model="model")

    outcome = await apply_context_overflow_policy(
        config=cfg,
        message="m",
        transcript=sm._transcript,
        session_key="s-auto",
        session_manager=sm,
        compaction_config=compaction_config,
    )

    assert outcome.summarized is True
    assert sm.compact_calls == [("s-auto", 10, None)]


@pytest.mark.asyncio
async def test_rpc_chat_auto_summarize_builds_provider_compaction_config() -> None:
    cfg = _cfg(ContextOverflowPolicy.AUTO_SUMMARIZE, budget=10)
    sm = _FakeSessionManager(_history(6, 40))
    sm._storage = SimpleNamespace(
        get_session=AsyncMock(
            return_value=SimpleNamespace(model="session/model", model_override="routed/model")
        )
    )
    selector = _FakeProviderSelector()
    ctx = SimpleNamespace(config=cfg, session_manager=sm, provider_selector=selector)

    refusal = await _enforce_context_overflow(ctx, "s-auto", "m")

    assert refusal is None
    config = sm.compact_calls[0][2]
    assert isinstance(config, CompactionConfig)
    assert config.api_key == "overflow-provider-key"
    assert config.model == "routed/model"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert selector.override_calls == []
    assert selector.clone_instance.override_calls == ["routed/model"]


def test_rpc_chat_auto_summarize_delegates_compaction_inputs_to_gateway_boundary() -> None:
    from opensquilla.gateway import rpc_chat

    source = Path(rpc_chat.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    boundary_path = Path(rpc_chat.__file__).with_name("rpc_compaction_inputs.py")

    assert boundary_path.exists()

    boundary_tree = ast.parse(boundary_path.read_text(encoding="utf-8"))
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    top_level_functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    boundary_defs = {
        node.name
        for node in ast.walk(boundary_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    builder = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_build_context_overflow_compaction_config"
    )

    assert (
        "opensquilla.gateway.rpc_compaction_inputs",
        "build_gateway_compaction_config",
    ) in imports
    assert "build_gateway_compaction_config" in boundary_defs
    assert "_effective_compaction_model" not in top_level_functions
    assert "_resolve_compaction_provider" not in top_level_functions
    assert any(
        isinstance(node, ast.Name) and node.id == "build_gateway_compaction_config"
        for node in ast.walk(builder)
    )
    assert not any(
        isinstance(node, ast.Name) and node.id == "build_compaction_config_from_provider"
        for node in ast.walk(builder)
    )


@pytest.mark.asyncio
async def test_auto_summarize_without_session_manager_uses_proxy() -> None:
    """Without a session manager, AUTO degrades to drop-oldest proxy."""

    cfg = _cfg(ContextOverflowPolicy.AUTO_SUMMARIZE, budget=10)
    outcome = await apply_context_overflow_policy(
        config=cfg,
        message="m",
        transcript=_history(6, 40),
        session_key="s-proxy",
        session_manager=None,
    )
    assert outcome.over_budget is True
    assert outcome.retried is True
    assert outcome.summarized is False
    assert outcome.truncated_entries > 0


@pytest.mark.asyncio
async def test_outcome_carries_diagnostic_counters() -> None:
    """The returned OverflowOutcome exposes estimated + budget for observability."""

    cfg = _cfg(ContextOverflowPolicy.REFUSE, budget=3)
    outcome = await apply_context_overflow_policy(
        config=cfg,
        message="hello",
        transcript=_history(2, 40),
        session_key="s-x",
    )
    assert isinstance(outcome, OverflowOutcome)
    assert outcome.estimated_tokens > outcome.budget_tokens
    assert outcome.budget_tokens == 3
