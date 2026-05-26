#!/usr/bin/env python3
"""Live meta-skill soft-activation E2E harness.

The harness verifies the path where the model sees a ``kind: meta`` skill,
chooses ``meta_invoke(name=...)``, and the runtime executes that meta-skill.
It prints only structural evidence and never prints provider API keys.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from opensquilla.engine.agent import Agent
from opensquilla.engine.types import (
    AgentConfig,
    DoneEvent,
    ErrorEvent,
    TextDeltaEvent,
    ToolResultEvent,
)
from opensquilla.provider.selector import build_provider
from opensquilla.skills.injector import SkillInjector
from opensquilla.skills.loader import SkillLoader
from opensquilla.tools.builtin import meta_tools  # noqa: F401 - registers meta_invoke
from opensquilla.tools.registry import get_default_registry
from opensquilla.tools.types import ToolContext

META_SKILL_NAME = "meta-live-soft-activation"
EXPECTED_OUTPUT = "LIVE_OK"
DEFAULT_USER_MESSAGE = (
    "Run the available meta-skill named meta-live-soft-activation and return "
    "its result."
)


def _load_env_file(path: Path | None) -> None:
    if path is None or not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_api_key(provider: str) -> str:
    env_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "minimax": "MINIMAX_API_KEY",
    }
    env_name = env_map.get(provider.lower(), "")
    return os.environ.get(env_name, "").strip() if env_name else ""


def _write_live_meta_skill(home: Path) -> SkillLoader:
    bundled = home / "skills" / "bundled"
    skill_dir = bundled / META_SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {META_SKILL_NAME}
kind: meta
description: Live E2E meta-skill that returns {EXPECTED_OUTPUT} when invoked.
triggers:
  - live soft activation workflow
metadata:
  opensquilla:
    risk: low
    capabilities: []
composition:
  steps:
    - id: classify
      kind: llm_classify
      output_choices: [{EXPECTED_OUTPUT}, OTHER]
      with:
        text: "Return {EXPECTED_OUTPUT} for this live soft activation E2E check."
final_text_mode: "step:classify"
---

# {META_SKILL_NAME}
""",
        encoding="utf-8",
    )
    loader = SkillLoader(bundled_dir=bundled, snapshot_path=home / "skills_snapshot.json")
    loader.invalidate_cache()
    loader.load_all()
    return loader


def _make_agent(
    *,
    home: Path,
    provider_instance: Any,
    model: str,
    classify_override: str | None,
) -> Agent:
    loader = _write_live_meta_skill(home)
    skills = loader.load_all()
    system_prompt = SkillInjector().inject_full(
        "You are validating OpenSquilla meta-skill soft activation.",
        skills,
    )
    registry = get_default_registry()
    ctx = ToolContext(
        workspace_dir=str(home),
        is_owner=True,
        allowed_tools={"meta_invoke"},
        surfaced_tools={"meta_invoke"},
    )
    tools = registry.to_tool_definitions(ctx)
    config = AgentConfig(
        model_id=model,
        max_iterations=4,
        system_prompt=system_prompt,
        metadata={"skill_loader": loader, "bootstrap_workspace_dir": str(home)},
    )
    agent = Agent(
        provider=provider_instance,
        config=config,
        tool_definitions=tools,
        tool_handler=None,
        tool_registry=registry,
        tool_context=ctx,
    )
    if classify_override is not None:
        async def _override(_system: str, _user: str) -> str:
            return classify_override

        agent._test_llm_chat_override = _override  # type: ignore[attr-defined]
    return agent


async def _run_one_case(
    *,
    home: Path,
    provider_instance: Any,
    model: str,
    user_message: str,
    expected_meta_skill: str | None,
    classify_override: str | None,
) -> dict[str, Any]:
    agent = _make_agent(
        home=home,
        provider_instance=provider_instance,
        model=model,
        classify_override=classify_override,
    )
    events = []
    async for event in agent.run_turn(user_message):
        events.append(event)

    tool_results = [
        event for event in events
        if isinstance(event, ToolResultEvent)
    ]
    final_text = "".join(
        event.text for event in events
        if isinstance(event, TextDeltaEvent)
    )
    meta_results = [
        event for event in tool_results
        if event.tool_name == "meta_invoke"
    ]
    errors = [
        event.message for event in events
        if isinstance(event, ErrorEvent)
    ]
    done = next((event for event in events if isinstance(event, DoneEvent)), None)
    selected = None
    if meta_results:
        args = meta_results[-1].arguments or {}
        selected = args.get("name") if isinstance(args.get("name"), str) else None
        if selected is None:
            selected = expected_meta_skill
    meta_invoke_result = meta_results[-1].result if meta_results else ""
    passed = (
        selected == expected_meta_skill
        if expected_meta_skill is not None
        else not meta_results
    )
    if expected_meta_skill is not None:
        passed = passed and (
            EXPECTED_OUTPUT in meta_invoke_result
            or EXPECTED_OUTPUT in final_text
            or bool(done and EXPECTED_OUTPUT in (done.text or ""))
        )

    return {
        "user_message": user_message,
        "expected_meta_skill": expected_meta_skill,
        "passed": passed,
        "model_decision": {
            "meta_invoke_called": bool(meta_results),
            "selected_meta_skill": selected,
        },
        "observed_tool_results": [event.tool_name for event in tool_results],
        "meta_invoke_result": meta_invoke_result,
        "final_text": final_text or (done.text if done else ""),
        "done": done is not None,
        "errors": errors,
    }


def run_live_meta_activation_cases(
    *,
    home: Path | None = None,
    provider_instance: Any | None = None,
    provider: str = "openrouter",
    model: str = "anthropic/claude-3.5-haiku",
    cases: list[dict[str, Any]] | None = None,
    classify_override: str | None = None,
) -> dict[str, Any]:
    home_path = home or Path(tempfile.mkdtemp(prefix="opensquilla-live-meta-soft-"))
    home_path.mkdir(parents=True, exist_ok=True)
    llm = provider_instance or build_provider(
        provider=provider,
        model=model,
        api_key=_resolve_api_key(provider),
    )
    case_rows = cases or [
        {
            "name": "positive",
            "user_message": DEFAULT_USER_MESSAGE,
            "expected_meta_skill": META_SKILL_NAME,
        }
    ]

    async def _drive() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for row in case_rows:
            result = await _run_one_case(
                home=home_path,
                provider_instance=llm,
                model=model,
                user_message=str(row["user_message"]),
                expected_meta_skill=row.get("expected_meta_skill"),
                classify_override=classify_override,
            )
            result["name"] = row.get("name", "")
            results.append(result)
        return results

    results = asyncio.run(_drive())
    passed = sum(1 for row in results if row["passed"])
    failed = len(results) - passed
    return {
        "ok": failed == 0,
        "home": str(home_path),
        "provider": provider_instance.provider_name
        if provider_instance is not None and hasattr(provider_instance, "provider_name")
        else provider,
        "model": model,
        "meta_skill": META_SKILL_NAME,
        "expected_output": EXPECTED_OUTPUT,
        "summary": {"passed": passed, "failed": failed, "total": len(results)},
        "cases": results,
    }


def run_live_meta_soft_activation_e2e(
    *,
    home: Path | None = None,
    provider_instance: Any | None = None,
    provider: str = "openrouter",
    model: str = "anthropic/claude-3.5-haiku",
    user_message: str = DEFAULT_USER_MESSAGE,
    classify_override: str | None = None,
) -> dict[str, Any]:
    result = run_live_meta_activation_cases(
        home=home,
        provider_instance=provider_instance,
        provider=provider,
        model=model,
        cases=[
            {
                "name": "positive",
                "user_message": user_message,
                "expected_meta_skill": META_SKILL_NAME,
            }
        ],
        classify_override=classify_override,
    )
    case = result["cases"][0]
    return {
        **result,
        "model_decision": case["model_decision"],
        "observed_tool_results": case["observed_tool_results"],
        "meta_invoke_result": case["meta_invoke_result"],
        "final_text": case.get("final_text", ""),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--provider", default="openrouter")
    parser.add_argument("--model", default="anthropic/claude-3.5-haiku")
    parser.add_argument("--user-message", default=DEFAULT_USER_MESSAGE)
    parser.add_argument("--case-file", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _load_env_file(args.env_file)
    cases = None
    if args.case_file is not None:
        cases = json.loads(args.case_file.read_text(encoding="utf-8"))
    if cases is None:
        result = run_live_meta_soft_activation_e2e(
            home=args.home,
            provider=args.provider,
            model=args.model,
            user_message=args.user_message,
        )
    else:
        result = run_live_meta_activation_cases(
            home=args.home,
            provider=args.provider,
            model=args.model,
            cases=cases,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
