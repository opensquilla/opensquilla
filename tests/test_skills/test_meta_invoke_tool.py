"""Tests for meta_invoke tool registration and Agent dispatch interception.

This file accumulates tests across Tasks 1, 3, 5, 6 of the
meta_invoke-soft-activation plan. Task 1 covers registration only.
"""

from __future__ import annotations

import pytest


def test_meta_invoke_registered_in_default_registry() -> None:
    """meta_invoke appears in the registry after importing the builtin
    module."""
    # Importing the builtin package triggers all registrations.
    from opensquilla.tools.builtin import meta_tools  # noqa: F401 — import side-effect
    from opensquilla.tools.registry import get_default_registry

    assert get_default_registry().get("meta_invoke") is not None


def test_meta_invoke_spec_shape() -> None:
    """meta_invoke advertises a single required string parameter 'name',
    and the description mentions meta-skill semantics."""
    from opensquilla.tools.builtin import meta_tools  # noqa: F401
    from opensquilla.tools.registry import get_default_registry

    registered = get_default_registry().get("meta_invoke")
    assert registered is not None
    spec = registered.spec
    assert spec.name == "meta_invoke"
    assert "name" in spec.parameters
    assert spec.required == ["name"]
    # Description must mention meta-skill semantics for the LLM
    desc = spec.description.lower()
    assert "meta-skill" in desc
    assert "playbook" in desc or "multi-step" in desc


def test_meta_invoke_not_exposed_by_default() -> None:
    """meta_invoke must not appear in default tool catalogues. It is
    conditionally surfaced by SkillInjector when meta-skills are present."""
    from opensquilla.tools.builtin import meta_tools  # noqa: F401
    from opensquilla.tools.registry import get_default_registry

    registered = get_default_registry().get("meta_invoke")
    assert registered is not None  # exists in registry
    assert registered.spec.exposed_by_default is False, (
        "meta_invoke should be conditionally surfaced, not always exposed"
    )


@pytest.mark.asyncio
async def test_meta_invoke_handler_raises_routing_error() -> None:
    """If the standard dispatcher ever invokes the meta_invoke handler,
    that's a configuration bug — the Agent's dispatch loop should have
    intercepted it. Raise a clear RuntimeError naming the expected
    interception point."""
    from opensquilla.tools.builtin.meta_tools import meta_invoke

    with pytest.raises(RuntimeError) as exc_info:
        await meta_invoke(name="any")
    msg = str(exc_info.value).lower()
    assert "agent" in msg or "_run_one_streaming" in msg or "intercept" in msg


# ---------------------------------------------------------------------------
# Task 3: ToolResult.terminates_turn field + preservation through
# Agent._compress_tool_result rebuild sites.
# ---------------------------------------------------------------------------


def test_tool_result_has_terminates_turn_field() -> None:
    """ToolResult.terminates_turn defaults to False; can be set True."""
    from opensquilla.tool_boundary import ToolResult

    r = ToolResult(tool_use_id="u1", tool_name="t", content="ok")
    assert r.terminates_turn is False

    r2 = ToolResult(
        tool_use_id="u1", tool_name="t", content="ok", terminates_turn=True,
    )
    assert r2.terminates_turn is True


class _NullProvider:
    """Minimal LLMProvider stand-in: never called by _compress_tool_result."""

    provider_name = "null"

    def chat(self, *args: object, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("provider.chat must not be called by _compress_tool_result")

    async def list_models(self) -> list[object]:  # pragma: no cover
        return []


@pytest.mark.asyncio
async def test_compress_tool_result_preserves_terminates_turn_when_short() -> None:
    """When content is short enough to not need compression, the rebuild
    must still carry terminates_turn through."""
    from opensquilla.engine import Agent, AgentConfig
    from opensquilla.tool_boundary import ToolResult

    agent = Agent(provider=_NullProvider(), config=AgentConfig())

    original = ToolResult(
        tool_use_id="u1",
        tool_name="meta_invoke",
        content="small content",
        is_error=False,
        terminates_turn=True,
    )
    compressed = await agent._compress_tool_result(original)
    assert compressed.terminates_turn is True


@pytest.mark.asyncio
async def test_compress_tool_result_preserves_terminates_turn_when_compressed() -> None:
    """When content IS large enough to trigger compression, the rebuild
    must STILL carry terminates_turn through (the other code path)."""
    from opensquilla.engine import Agent, AgentConfig
    from opensquilla.tool_boundary import ToolResult

    # Shrink context_window_tokens so 50_000 chars (~12500 tokens) exceeds
    # the compression budget (context_window_tokens * max_share = 1000 * 0.25
    # = 250 tokens). truncate mode keeps compression purely local — no
    # provider call needed.
    config = AgentConfig(
        context_window_tokens=1000,
        tool_result_compression_enabled=True,
        tool_result_compression_mode="truncate",
    )
    agent = Agent(provider=_NullProvider(), config=config)

    big_content = "x" * 50_000
    original = ToolResult(
        tool_use_id="u1",
        tool_name="meta_invoke",
        content=big_content,
        is_error=False,
        terminates_turn=True,
    )
    compressed = await agent._compress_tool_result(original)
    # Sanity-check the compression path actually fired (content shrunk).
    assert len(compressed.content) < len(big_content), (
        "test setup error: compression did not trigger; "
        "second rebuild site would not be exercised"
    )
    # The FLAG must survive the rebuild.
    assert compressed.terminates_turn is True, (
        "terminates_turn lost during ToolResult compression rebuild"
    )
