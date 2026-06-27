"""PR7 — agent.meta_invoke handler routes paused MetaResult to text path.

Regression: before PR7, ``_run_one_streaming`` checked ``result.ok``
straight away; a paused MetaResult (``ok=False, paused=True``) fell into
``_format_meta_invoke_failure`` and the user saw a "Meta-skill failed at
step …" message instead of the form prompt.

The fix branches ``paused`` before the failure check and yields:
  - a ``TextDeltaEvent`` with the rendered form text (so IM/CLI/Web
    fallbacks see something user-visible), and
  - a non-error ``ToolResult`` (so the meta_invoke tool call doesn't
    look like an exception in the transcript).
"""

from __future__ import annotations

from typing import Any

import pytest

from opensquilla.engine.agent import Agent
from opensquilla.engine.types import AgentConfig, TextDeltaEvent
from opensquilla.skills.meta.types import (
    ClarifyField,
    ClarifyStepConfig,
    MetaPaused,
    MetaResult,
)
from opensquilla.tool_boundary import ToolCall, ToolResult
from opensquilla.tools.builtin import meta_tools  # noqa: F401 — registers meta_invoke
from opensquilla.tools.registry import get_default_registry
from opensquilla.tools.types import ToolContext


class _NullProvider:
    provider_name = "null"

    async def chat(self, *_args, **_kwargs):
        raise AssertionError("provider.chat must not be called in this test")

    async def list_models(self):
        return []


def _make_paused_result() -> MetaResult:
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="destination", type="string", required=True,
                         prompt="目的地"),
            ClarifyField(name="days", type="int", required=True, min=1, max=14,
                         prompt="天数"),
        ),
        intro="出行前需要确认几件事。",
    )
    paused = MetaPaused(
        run_id="r1",
        step_id="collect",
        schema=cfg,
        intro="出行前需要确认几件事。",
    )
    return MetaResult(ok=False, paused=True, paused_payload=paused)


def _make_skill(tmp_path, name: str = "meta-paused-stub") -> Any:
    """Author a minimal meta-skill so meta_invoke validates ``name``."""
    from opensquilla.skills.loader import SkillLoader

    bundled = tmp_path / "skills" / "bundled"
    bundled.mkdir(parents=True)
    skill_dir = bundled / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "kind: meta\n"
        "description: paused stub\n"
        "triggers: [paused-stub-trigger]\n"
        "composition:\n"
        "  steps:\n"
        "    - id: c\n"
        "      kind: user_input\n"
        "      clarify:\n"
        "        mode: form\n"
        "        fields:\n"
        "          - {name: x, type: string, required: true}\n"
        "---\n"
        "# stub\n",
        encoding="utf-8",
    )
    loader = SkillLoader(bundled_dir=bundled, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    loader.load_all()
    return loader


@pytest.mark.asyncio
async def test_paused_meta_result_yields_text_and_non_error_result(tmp_path) -> None:
    loader = _make_skill(tmp_path)
    spec = loader.get_by_name("meta-paused-stub")
    assert spec is not None

    registry = get_default_registry()
    config = AgentConfig(
        model_id="stub",
        max_iterations=1,
        system_prompt="",
        metadata={"skill_loader": loader, "bootstrap_workspace_dir": str(tmp_path)},
    )
    agent = Agent(
        provider=_NullProvider(),  # type: ignore[arg-type]
        config=config,
        tool_definitions=[],
        tool_handler=None,
        tool_registry=registry,
    )

    # Force the orchestrator to return a paused MetaResult without
    # actually running the DAG.
    paused_result = _make_paused_result()

    class _StubOrch:
        async def iter_events(self, _match):
            yield paused_result

    def _factory(*_a, **_k):
        return _StubOrch()

    # Monkeypatch the orchestrator factory at the module the agent
    # imports it from (local import inside _run_one_streaming).
    import opensquilla.skills.meta.orchestrator as orch_mod
    original = orch_mod.MetaOrchestrator
    orch_mod.MetaOrchestrator = lambda *a, **k: _StubOrch()  # type: ignore[assignment]
    try:
        tc = ToolCall(
            tool_use_id="u-paused",
            tool_name="meta_invoke",
            arguments={"name": "meta-paused-stub"},
        )
        tool_ctx = ToolContext(workspace_dir=str(tmp_path), is_owner=True)

        text_chunks: list[str] = []
        final: ToolResult | None = None
        async for ev in agent._run_one_streaming(tc, tool_ctx):
            if isinstance(ev, ToolResult):
                final = ev
            elif isinstance(ev, TextDeltaEvent):
                text_chunks.append(ev.text)
    finally:
        orch_mod.MetaOrchestrator = original  # type: ignore[assignment]

    assert final is not None, "must yield a final ToolResult"
    assert final.is_error is False, (
        f"paused MetaResult must NOT surface as an error (got: {final.content!r})"
    )
    assert final.terminates_turn is True
    assert "paused" in final.content.lower()
    rendered = "".join(text_chunks)
    assert "destination" in rendered
    assert "days" in rendered
    assert "目的地" in rendered
    assert "出行前需要确认几件事" in rendered
    assert "请回复以下字段" in rendered


@pytest.mark.asyncio
async def test_completed_meta_result_with_empty_final_text_yields_visible_fallback(
    tmp_path,
) -> None:
    loader = _make_skill(tmp_path, name="meta-empty-complete-stub")
    registry = get_default_registry()
    config = AgentConfig(
        model_id="stub",
        max_iterations=1,
        system_prompt="",
        metadata={"skill_loader": loader, "bootstrap_workspace_dir": str(tmp_path)},
    )
    agent = Agent(
        provider=_NullProvider(),  # type: ignore[arg-type]
        config=config,
        tool_definitions=[],
        tool_handler=None,
        tool_registry=registry,
    )

    class _StubOrch:
        async def iter_events(self, _match):
            yield MetaResult(ok=True, final_text="")

    import opensquilla.skills.meta.orchestrator as orch_mod

    original = orch_mod.MetaOrchestrator
    orch_mod.MetaOrchestrator = lambda *a, **k: _StubOrch()  # type: ignore[assignment]
    try:
        tc = ToolCall(
            tool_use_id="u-empty",
            tool_name="meta_invoke",
            arguments={"name": "meta-empty-complete-stub"},
        )
        tool_ctx = ToolContext(workspace_dir=str(tmp_path), is_owner=True)

        text_chunks: list[str] = []
        final: ToolResult | None = None
        async for ev in agent._run_one_streaming(tc, tool_ctx):
            if isinstance(ev, ToolResult):
                final = ev
            elif isinstance(ev, TextDeltaEvent):
                text_chunks.append(ev.text)
    finally:
        orch_mod.MetaOrchestrator = original  # type: ignore[assignment]

    rendered = "".join(text_chunks)
    assert "meta-empty-complete-stub" in rendered
    assert "没有生成可展示的最终回答" in rendered
    assert final is not None
    assert final.is_error is False
    assert final.terminates_turn is True
    assert final.content == "meta-skill 'meta-empty-complete-stub' completed."


@pytest.mark.asyncio
async def test_completed_meta_empty_final_text_fallback_follows_english_input(
    tmp_path,
) -> None:
    loader = _make_skill(tmp_path, name="meta-empty-complete-en-stub")
    registry = get_default_registry()
    config = AgentConfig(
        model_id="stub",
        max_iterations=1,
        system_prompt="",
        metadata={
            "skill_loader": loader,
            "bootstrap_workspace_dir": str(tmp_path),
            "user_message": "Please create a research brief in English.",
        },
    )
    agent = Agent(
        provider=_NullProvider(),  # type: ignore[arg-type]
        config=config,
        tool_definitions=[],
        tool_handler=None,
        tool_registry=registry,
    )

    class _StubOrch:
        async def iter_events(self, _match):
            yield MetaResult(ok=True, final_text="")

    import opensquilla.skills.meta.orchestrator as orch_mod

    original = orch_mod.MetaOrchestrator
    orch_mod.MetaOrchestrator = lambda *a, **k: _StubOrch()  # type: ignore[assignment]
    try:
        tc = ToolCall(
            tool_use_id="u-empty-en",
            tool_name="meta_invoke",
            arguments={"name": "meta-empty-complete-en-stub"},
        )
        tool_ctx = ToolContext(workspace_dir=str(tmp_path), is_owner=True)

        text_chunks: list[str] = []
        final: ToolResult | None = None
        async for ev in agent._run_one_streaming(tc, tool_ctx):
            if isinstance(ev, ToolResult):
                final = ev
            elif isinstance(ev, TextDeltaEvent):
                text_chunks.append(ev.text)
    finally:
        orch_mod.MetaOrchestrator = original  # type: ignore[assignment]

    rendered = "".join(text_chunks)
    assert "meta-empty-complete-en-stub" in rendered
    assert "did not produce a user-visible final answer" in rendered
    assert "没有生成可展示的最终回答" not in rendered
    assert final is not None
    assert final.is_error is False
    assert final.terminates_turn is True
