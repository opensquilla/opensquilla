from __future__ import annotations

import pytest

from opensquilla.engine.types import AgentConfig, DoneEvent
from opensquilla.skills.creator.runtime_e2e import (
    make_runtime_e2e_context,
    run_runtime_e2e_gate,
)

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
