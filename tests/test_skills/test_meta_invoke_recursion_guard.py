"""Tests for meta_invoke recursion-depth + per-turn invocation guards (Step A.1).

Covers:
* sub-Agent tool list excludes meta_invoke (so a sub-Agent cannot recurse).
* ContextVar depth limit returns structured failure (is_error=True,
  terminates_turn=False) with recovery-friendly content.
* Within-limit calls proceed through the normal flow.
* Per-turn invocation cap returns structured failure.
* run_turn resets the per-turn counter at the start of every turn.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _isolate_meta_invoke_contextvars() -> Iterator[None]:
    """Snapshot the two module-level ContextVars before each test and
    restore them after, so a test that does ``set(99)`` cannot leak that
    value to the event loop's root context and pollute later tests.
    """
    from opensquilla.engine import agent as agent_module

    depth_token = agent_module._meta_invoke_depth.set(
        agent_module._meta_invoke_depth.get()
    )
    turn_token = agent_module._meta_invoke_turn_count.set(
        agent_module._meta_invoke_turn_count.get()
    )
    try:
        yield
    finally:
        agent_module._meta_invoke_depth.reset(depth_token)
        agent_module._meta_invoke_turn_count.reset(turn_token)


# ---------------------------------------------------------------------------
# Change 1: sub-Agent tool list filtering
# ---------------------------------------------------------------------------


def test_sub_agent_tool_list_excludes_meta_invoke() -> None:
    """make_agent_runner_from_parent must strip meta_invoke from the
    tool_definitions passed to the sub-Agent factory, so a sub-Agent cannot
    issue a nested meta_invoke call."""
    from opensquilla.engine.types import AgentConfig
    from opensquilla.skills.meta.orchestrator import make_agent_runner_from_parent

    fake_meta = SimpleNamespace(name="meta_invoke")
    fake_other = SimpleNamespace(name="bash")
    # Dict-form entry — make sure dict-style filtering also works.
    fake_dict_meta = {"name": "meta_invoke"}

    tool_definitions = [fake_meta, fake_other, fake_dict_meta]

    captured: dict[str, Any] = {}

    def agent_factory(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        # Return an object whose run_turn yields nothing — the runner is
        # never awaited in this test, but the factory must return something
        # with run_turn for type sanity.
        class _DummyAgent:
            async def run_turn(self, _msg: str):
                if False:
                    yield None  # pragma: no cover

        return _DummyAgent()

    runner = make_agent_runner_from_parent(
        provider=None,  # type: ignore[arg-type]
        base_config=AgentConfig(model_id="stub"),
        tool_definitions=tool_definitions,
        tool_handler=None,
        agent_factory=agent_factory,
    )

    # The factory only fires when the runner is actually exercised; drive
    # it once to capture the kwargs.
    import asyncio

    async def _drive() -> None:
        async for _ in runner("sys", "user"):
            pass

    asyncio.run(_drive())

    assert "tool_definitions" in captured, (
        "agent_factory must receive tool_definitions kwarg"
    )
    filtered = captured["tool_definitions"]
    names = [
        getattr(td, "name", None) or (td.get("name") if isinstance(td, dict) else None)
        for td in filtered
    ]
    assert "meta_invoke" not in names, (
        f"meta_invoke must be filtered from sub-Agent tool list; got {names!r}"
    )
    # Other tools must be preserved.
    assert "bash" in names, (
        f"non-meta_invoke tools must be preserved; got {names!r}"
    )


def test_sub_agent_metadata_excludes_outer_meta_activation_controls() -> None:
    """Outer-turn meta activation controls must not leak into sub-Agents.

    The parent Agent can force the first LLM call to choose meta_invoke after a
    deterministic trigger match. Meta sub-Agents intentionally have meta_invoke
    removed from their tool surface, so inheriting that tool_choice makes
    providers reject otherwise valid agent steps.
    """
    from opensquilla.engine.types import AgentConfig
    from opensquilla.skills.meta.orchestrator import make_agent_runner_from_parent

    captured: dict[str, Any] = {}

    def agent_factory(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

        class _DummyAgent:
            async def run_turn(self, _msg: str):
                if False:
                    yield None  # pragma: no cover

        return _DummyAgent()

    runner = make_agent_runner_from_parent(
        provider=None,  # type: ignore[arg-type]
        base_config=AgentConfig(
            model_id="stub",
            metadata={
                "skill_loader": object(),
                "bootstrap_workspace_dir": "/tmp/workspace",
                "meta_match": object(),
                "meta_match_tool_choice": {
                    "type": "function",
                    "function": {"name": "meta_invoke"},
                },
                "meta_match_tool_surface_restricted": True,
                "keep": "yes",
            },
        ),
        tool_definitions=[SimpleNamespace(name="bash")],
        tool_handler=None,
        agent_factory=agent_factory,
    )

    import asyncio

    async def _drive() -> None:
        async for _ in runner("sys", "user"):
            pass

    asyncio.run(_drive())

    metadata = captured["config"].metadata
    assert metadata["skill_loader"] is not None
    assert metadata["bootstrap_workspace_dir"] == "/tmp/workspace"
    assert metadata["keep"] == "yes"
    assert "meta_match" not in metadata
    assert "meta_match_tool_choice" not in metadata
    assert "meta_match_tool_surface_restricted" not in metadata


# ---------------------------------------------------------------------------
# Change 2: depth + per-turn cap enforcement in _run_one_streaming
# ---------------------------------------------------------------------------


def _make_agent_with_meta_skill(tmp_path):
    """Helper: build an Agent wired with a tiny meta-skill registered in a
    fresh SkillLoader, mirroring test_meta_invoke_tool fixtures."""
    from opensquilla.engine.agent import Agent
    from opensquilla.engine.types import AgentConfig
    from opensquilla.skills.loader import SkillLoader
    from opensquilla.tools.builtin import meta_tools  # noqa: F401 — side-effect register
    from opensquilla.tools.registry import get_default_registry

    bundled = tmp_path / "skills" / "bundled"
    bundled.mkdir(parents=True)
    skill_dir = bundled / "meta-tiny"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: meta-tiny\n"
        "kind: meta\n"
        "description: tiny meta-skill\n"
        "triggers: [tiny-meta-trigger]\n"
        "composition:\n"
        "  steps:\n"
        "    - id: c\n"
        "      kind: llm_classify\n"
        "      output_choices: [A, B]\n"
        "      with: {text: \"x\"}\n"
        "---\n"
        "# meta-tiny\n",
        encoding="utf-8",
    )
    loader = SkillLoader(bundled_dir=bundled, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    loader.load_all()

    class _NullProvider:
        provider_name = "null"

        async def chat(self, *_args, **_kwargs):
            raise AssertionError("provider.chat must not be called in this test")

        async def list_models(self):
            return []

    registry = get_default_registry()
    config = AgentConfig(
        model_id="stub",
        max_iterations=1,
        system_prompt="",
        metadata={
            "skill_loader": loader,
            "bootstrap_workspace_dir": str(tmp_path),
        },
    )
    agent = Agent(
        provider=_NullProvider(),  # type: ignore[arg-type]
        config=config,
        tool_definitions=[],
        tool_handler=None,
        tool_registry=registry,
    )

    async def fake_llm_chat(_s: str, _u: str) -> str:
        return "A"

    agent._test_llm_chat_override = fake_llm_chat  # type: ignore[attr-defined]
    return agent


@pytest.mark.asyncio
async def test_recursion_depth_limit_exceeded_returns_structured_failure(
    tmp_path,
) -> None:
    """When _meta_invoke_depth is already at MAX_META_INVOKE_DEPTH, a new
    meta_invoke call must return a structured failure (is_error=True,
    terminates_turn=False) and not actually run the orchestrator."""
    from opensquilla.engine import agent as agent_module
    from opensquilla.tool_boundary import ToolCall, ToolResult
    from opensquilla.tools.types import ToolContext

    agent = _make_agent_with_meta_skill(tmp_path)
    tc = ToolCall(
        tool_use_id="u1",
        tool_name="meta_invoke",
        arguments={"name": "meta-tiny"},
    )
    tool_ctx = ToolContext(workspace_dir=str(tmp_path), is_owner=True)

    # Saturate the depth gauge.
    token = agent_module._meta_invoke_depth.set(agent_module.MAX_META_INVOKE_DEPTH)
    try:
        results: list[Any] = []
        async for ev in agent._run_one_streaming(tc, tool_ctx):
            results.append(ev)
    finally:
        agent_module._meta_invoke_depth.reset(token)

    assert len(results) == 1, (
        f"depth-cap should short-circuit to a single ToolResult; got {results!r}"
    )
    final = results[0]
    assert isinstance(final, ToolResult)
    assert final.is_error is True
    assert final.terminates_turn is False
    assert "recursion depth limit reached" in final.content


@pytest.mark.asyncio
async def test_recursion_within_limit_proceeds(tmp_path) -> None:
    """When depth is below the cap, _run_one_streaming proceeds through the
    normal flow (does NOT yield the depth-cap structured failure)."""
    from opensquilla.engine import agent as agent_module
    from opensquilla.tool_boundary import ToolCall, ToolResult
    from opensquilla.tools.types import ToolContext

    agent = _make_agent_with_meta_skill(tmp_path)
    tc = ToolCall(
        tool_use_id="u1",
        tool_name="meta_invoke",
        arguments={"name": "meta-tiny"},
    )
    tool_ctx = ToolContext(workspace_dir=str(tmp_path), is_owner=True)

    # Below the cap — orchestrator should actually run.
    token = agent_module._meta_invoke_depth.set(
        agent_module.MAX_META_INVOKE_DEPTH - 1
    )
    try:
        final: ToolResult | None = None
        async for ev in agent._run_one_streaming(tc, tool_ctx):
            if isinstance(ev, ToolResult):
                final = ev
    finally:
        agent_module._meta_invoke_depth.reset(token)

    assert final is not None
    # The depth-cap message must NOT appear; flow proceeded normally.
    assert "recursion depth limit reached" not in (final.content or "")


@pytest.mark.asyncio
async def test_meta_invoke_depth_reset_valueerror_restores_previous_depth() -> None:
    """Python 3.13 can close async generators in a different Context than
    the one that created the ContextVar token. meta_invoke should still
    restore the previous depth instead of surfacing that ValueError.
    """
    from opensquilla.engine import agent as agent_module
    from opensquilla.engine.agent import Agent
    from opensquilla.engine.types import AgentConfig
    from opensquilla.tool_boundary import ToolCall, ToolResult
    from opensquilla.tools.types import ToolContext

    class _FakeDepthVar:
        def __init__(self, value: int) -> None:
            self.value = value
            self.set_values: list[int] = []
            self.reset_called = False

        def get(self) -> int:
            return self.value

        def set(self, value: int) -> object:
            self.value = value
            self.set_values.append(value)
            return object()

        def reset(self, _token: object) -> None:
            self.reset_called = True
            raise ValueError("Token was created in a different Context")

    class _NullProvider:
        provider_name = "null"

        async def chat(self, *_args, **_kwargs):
            raise AssertionError("provider.chat must not be called")

        async def list_models(self):
            return []

    previous_depth = 2
    fake_depth = _FakeDepthVar(previous_depth)
    original_depth_var = agent_module._meta_invoke_depth
    agent_module._meta_invoke_depth = fake_depth  # type: ignore[assignment]
    try:
        agent = Agent(
            provider=_NullProvider(),  # type: ignore[arg-type]
            config=AgentConfig(model_id="stub"),
            tool_registry=None,
        )
        events: list[object] = []
        async for ev in agent._run_one_streaming(
            ToolCall(
                tool_use_id="u1",
                tool_name="meta_invoke",
                arguments={"name": "meta-tiny"},
            ),
            ToolContext(is_owner=True),
        ):
            events.append(ev)
    finally:
        agent_module._meta_invoke_depth = original_depth_var  # type: ignore[assignment]

    assert len(events) == 1
    assert isinstance(events[0], ToolResult)
    assert "requires Agent to be constructed with tool_registry" in events[0].content
    assert fake_depth.reset_called is True
    assert fake_depth.set_values == [previous_depth + 1, previous_depth]
    assert fake_depth.value == previous_depth


@pytest.mark.asyncio
async def test_per_turn_invocation_cap_exceeded_returns_structured_failure(
    tmp_path,
) -> None:
    """When _meta_invoke_turn_count is at MAX_META_INVOKE_PER_TURN, a new
    meta_invoke must short-circuit to a structured failure."""
    from opensquilla.engine import agent as agent_module
    from opensquilla.tool_boundary import ToolCall, ToolResult
    from opensquilla.tools.types import ToolContext

    agent = _make_agent_with_meta_skill(tmp_path)
    tc = ToolCall(
        tool_use_id="u1",
        tool_name="meta_invoke",
        arguments={"name": "meta-tiny"},
    )
    tool_ctx = ToolContext(workspace_dir=str(tmp_path), is_owner=True)

    token = agent_module._meta_invoke_turn_count.set(
        agent_module.MAX_META_INVOKE_PER_TURN
    )
    try:
        results: list[Any] = []
        async for ev in agent._run_one_streaming(tc, tool_ctx):
            results.append(ev)
    finally:
        agent_module._meta_invoke_turn_count.reset(token)

    assert len(results) == 1
    final = results[0]
    assert isinstance(final, ToolResult)
    assert final.is_error is True
    assert final.terminates_turn is False
    assert "per-turn invocation limit" in final.content


@pytest.mark.asyncio
async def test_run_turn_resets_per_turn_counter(tmp_path) -> None:
    """Agent.run_turn (via _turn_generator) must reset _meta_invoke_turn_count
    to 0 at the start of every new turn so each turn gets a fresh quota.

    Asserted by pre-setting the counter to a non-zero value, driving one
    event out of run_turn, and observing the counter has been reset.
    """
    from opensquilla.engine import agent as agent_module

    agent = _make_agent_with_meta_skill(tmp_path)

    # Force the counter high *before* run_turn starts.
    agent_module._meta_invoke_turn_count.set(99)

    observed: list[int] = []

    # Patch _transition to capture the counter value at the moment the
    # turn generator starts producing events (immediately after the
    # reset assignment in _turn_generator).
    original_transition = agent._transition

    def _spy_transition(state):  # type: ignore[no-untyped-def]
        observed.append(agent_module._meta_invoke_turn_count.get())
        return original_transition(state)

    agent._transition = _spy_transition  # type: ignore[assignment]

    gen = agent.run_turn("hello")
    try:
        # Pulling one event is enough — the reset happens before the
        # first yield in _turn_generator.
        await gen.__anext__()
    except StopAsyncIteration:
        pass
    except Exception:
        # The provider is a stub; we don't care if the turn errors out
        # after the reset point. We only need to confirm reset ran.
        pass
    finally:
        await gen.aclose()

    assert observed, "expected _transition to be invoked at least once"
    assert observed[0] == 0, (
        f"_meta_invoke_turn_count should be reset to 0 at the start of "
        f"run_turn; observed {observed[0]!r}"
    )
