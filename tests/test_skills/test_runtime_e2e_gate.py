from __future__ import annotations

import pytest

from opensquilla.engine.types import AgentConfig, DoneEvent
from opensquilla.skills.creator.runtime_e2e import (
    make_runtime_e2e_context,
    run_runtime_e2e_gate,
)
from opensquilla.tool_boundary import ToolCall

SKILL_MD = """---
name: synth-test-pipeline
description: "Sample synthetic pipeline for runtime E2E tests"
kind: meta
meta_priority: 50
triggers:
  - "synth test trigger"
provenance:
  origin: opensquilla-user
composition:
  steps:
    - id: a
      skill: summarize
      with:
        task: "{{ inputs.user_message | xml_escape | truncate(512) }}"
---
"""


@pytest.mark.asyncio
async def test_runtime_e2e_gate_runs_meta_and_no_meta_baseline() -> None:
    calls: list[tuple[str, str, str]] = []

    async def runner(*, route: str, prompt: str, skill_md: str, baseline_model: str) -> dict:
        calls.append((route, prompt, baseline_model))
        return {
            "text": (
                "meta answer with concrete summary"
                if route == "meta"
                else "baseline generic answer"
            ),
            "model": baseline_model if route == "baseline" else "meta-route",
        }

    async def judge(*, prompt: str, meta: dict, baseline: dict) -> dict:
        assert "synth test trigger" in prompt
        assert meta["text"].startswith("meta answer")
        assert baseline["text"].startswith("baseline")
        return {"winner": "meta", "regression": "", "reason": "meta follows the trigger"}

    result = await run_runtime_e2e_gate(
        skill_md=SKILL_MD,
        eval_prompts=["please use synth test trigger"],
        baseline_model="frontier/highest",
        runner=runner,
        judge=judge,
    )

    assert result["status"] == "ok"
    assert result["passed"] is True
    assert result["winner"] == "meta"
    assert calls == [
        ("meta", "please use synth test trigger", "frontier/highest"),
        ("baseline", "please use synth test trigger", "frontier/highest"),
    ]


@pytest.mark.asyncio
async def test_runtime_e2e_gate_blocks_baseline_winner() -> None:
    async def runner(*, route: str, prompt: str, skill_md: str, baseline_model: str) -> dict:
        return {"text": f"{route} output", "model": baseline_model}

    async def judge(*, prompt: str, meta: dict, baseline: dict) -> dict:
        return {
            "winner": "baseline",
            "regression": "meta omits the requested evidence",
            "reason": "baseline is more complete",
        }

    result = await run_runtime_e2e_gate(
        skill_md=SKILL_MD,
        eval_prompts=["please use synth test trigger"],
        baseline_model="frontier/highest",
        runner=runner,
        judge=judge,
    )

    assert result["passed"] is False
    assert result["winner"] == "baseline"
    assert result["cases"][0]["regression"] == "meta omits the requested evidence"


@pytest.mark.asyncio
async def test_runtime_e2e_gate_blocks_invalid_baseline_refusal() -> None:
    async def runner(*, route: str, prompt: str, skill_md: str, baseline_model: str) -> dict:
        if route == "baseline":
            return {
                "text": (
                    "Runtime E2E baseline mode: meta-skill creator tools are "
                    "disabled, so I cannot complete this request."
                ),
                "model": baseline_model,
            }
        return {"text": "meta output", "model": "meta"}

    async def judge(*, prompt: str, meta: dict, baseline: dict) -> dict:
        raise AssertionError("blocked/refusal baseline should not be sent to judge")

    result = await run_runtime_e2e_gate(
        skill_md=SKILL_MD,
        eval_prompts=["create a useful meta-skill from this workflow"],
        baseline_model="frontier/highest",
        runner=runner,
        judge=judge,
    )

    assert result["passed"] is False
    assert result["winner"] == "invalid"
    assert result["cases"][0]["regression"] == "baseline_invalid_or_blocked"


@pytest.mark.asyncio
async def test_runtime_e2e_context_baseline_runs_without_meta_loader() -> None:
    seen_configs: list[AgentConfig] = []

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            seen_configs.append(kwargs["config"])

        async def run_turn(self, prompt: str):
            yield DoneEvent(text=f"baseline handled {prompt}")

    ctx = make_runtime_e2e_context(
        provider=object(),
        base_config=AgentConfig(
            model_id="frontier/highest",
            metadata={"skill_loader": object(), "meta_match": object(), "keep": "yes"},
        ),
        skill_loader=object(),
        tool_definitions=[],
        tool_handler=None,
        agent_factory=FakeAgent,
        llm_chat=None,
        tool_invoker=None,
        session_key="test",
        baseline_model="frontier/highest",
    )

    result = await ctx["runner"](
        route="baseline",
        prompt="compare this",
        skill_md=SKILL_MD,
        baseline_model="frontier/highest",
    )

    assert result["text"] == "baseline handled compare this"
    assert seen_configs[0].metadata == {"keep": "yes"}
    assert seen_configs[0].model_id == "frontier/highest"


@pytest.mark.asyncio
async def test_runtime_e2e_context_baseline_blocks_creator_side_effect_tools() -> None:
    observed: list[tuple[str, bool, str]] = []

    async def unsafe_tool_handler(tc: ToolCall):
        raise AssertionError(f"baseline leaked creator tool call: {tc.tool_name}")

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            self.tool_handler = kwargs["tool_handler"]

        async def run_turn(self, prompt: str):
            result = await self.tool_handler(ToolCall(
                tool_use_id="tool-1",
                tool_name="meta_skill_persist_proposal",
                arguments={},
            ))
            observed.append((result.tool_name, result.is_error, result.content))
            yield DoneEvent(text="baseline done")

    ctx = make_runtime_e2e_context(
        provider=object(),
        base_config=AgentConfig(model_id="frontier/highest"),
        skill_loader=object(),
        tool_definitions=[],
        tool_handler=unsafe_tool_handler,
        agent_factory=FakeAgent,
        llm_chat=None,
        tool_invoker=None,
        session_key="test",
        baseline_model="frontier/highest",
    )

    result = await ctx["runner"](
        route="baseline",
        prompt="compare this",
        skill_md=SKILL_MD,
        baseline_model="frontier/highest",
    )

    assert result["text"] == "baseline done"
    assert observed == [(
        "meta_skill_persist_proposal",
        False,
        "Continue without this tool and write the strongest standalone answer "
        "directly in the final response.",
    )]


@pytest.mark.asyncio
async def test_runtime_e2e_context_baseline_hides_meta_tools_and_instructs_direct_answer() -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            captured["config"] = kwargs["config"]
            captured["tool_definitions"] = kwargs["tool_definitions"]

        async def run_turn(self, prompt: str):
            yield DoneEvent(text="baseline direct answer")

    ctx = make_runtime_e2e_context(
        provider=object(),
        base_config=AgentConfig(model_id="frontier/highest"),
        skill_loader=object(),
        tool_definitions=[
            {"type": "function", "function": {"name": "meta_invoke"}},
            {"type": "function", "function": {"name": "meta_skill_persist_proposal"}},
            {"type": "function", "function": {"name": "memory_search"}},
        ],
        tool_handler=None,
        agent_factory=FakeAgent,
        llm_chat=None,
        tool_invoker=None,
        session_key="test",
        baseline_model="frontier/highest",
    )

    result = await ctx["runner"](
        route="baseline",
        prompt="create a meta-skill from my history",
        skill_md=SKILL_MD,
        baseline_model="frontier/highest",
    )

    assert result["text"] == "baseline direct answer"
    assert captured["tool_definitions"] == [
        {"type": "function", "function": {"name": "memory_search"}},
    ]
    config = captured["config"]
    assert isinstance(config, AgentConfig)
    assert "highest-tier single model" in (config.request_context_prompt or "")
    assert "standalone proposal" in (config.request_context_prompt or "")
    assert "disabled" not in (config.request_context_prompt or "").lower()
