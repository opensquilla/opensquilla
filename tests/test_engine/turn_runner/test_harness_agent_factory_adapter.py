"""Tests for TurnRunner harness adapters."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from opensquilla.engine.turn_runner.harness import _TurnRunnerAgentFactoryAdapter


def test_agent_factory_adapter_passes_runner_tool_registry(monkeypatch) -> None:
    """Meta-skill execution needs the per-runner registry on constructed Agents."""

    captured: dict[str, Any] = {}

    class RecordingAgent:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    import opensquilla.engine.agent as agent_module

    monkeypatch.setattr(agent_module, "Agent", RecordingAgent)

    registry = object()
    runner = SimpleNamespace(
        _tool_registry=registry,
        _usage_tracker=None,
        _session_flush_service=None,
    )
    adapter = _TurnRunnerAgentFactoryAdapter(runner)

    adapter.build(
        provider=object(),
        config=object(),
        tool_definitions=[],
        tool_handler=None,
        session_key="agent:main:test",
        turn_call_logger=None,
        memory_sync_manager=None,
        tool_context=None,
    )

    assert captured["tool_registry"] is registry
