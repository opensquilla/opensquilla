"""meta_resolution: auto-trigger suppressed when auto_trigger off; resume preserved."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.engine.pipeline import TurnContext
from opensquilla.engine.runtime import TurnRunner
from opensquilla.provider import ToolDefinition, ToolInputSchema
from tests.test_engine.test_runtime_meta_invoke_surfacing import _make_loader_with_meta


def _meta_cfg(auto_trigger: bool) -> SimpleNamespace:
    return SimpleNamespace(meta_skill=SimpleNamespace(enabled=True, auto_trigger=auto_trigger))


@pytest.mark.asyncio
async def test_no_meta_match_when_auto_trigger_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def noop_router(ctx: TurnContext) -> TurnContext:
        return ctx

    noop_router.__name__ = "apply_squilla_router"
    monkeypatch.setattr("opensquilla.engine.steps.apply_squilla_router", noop_router)

    loader = _make_loader_with_meta(tmp_path)
    runner = TurnRunner(provider_selector=None, config=_meta_cfg(auto_trigger=False))
    runner._skill_loader = loader

    turn, _provider = await runner._run_pipeline(
        "please run tiny-meta-trigger for this request",
        "agent:main:test-no-auto",
        None,
        None,
        [ToolDefinition(name="web_search", description="search", input_schema=ToolInputSchema())],
        "base prompt",
        [],
    )

    assert turn.metadata.get("meta_match") is None
    assert turn.metadata.get("meta_match_tool_choice") is None


@pytest.mark.asyncio
async def test_meta_match_fires_when_auto_trigger_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def noop_router(ctx: TurnContext) -> TurnContext:
        return ctx

    noop_router.__name__ = "apply_squilla_router"
    monkeypatch.setattr("opensquilla.engine.steps.apply_squilla_router", noop_router)

    loader = _make_loader_with_meta(tmp_path)
    runner = TurnRunner(provider_selector=None, config=_meta_cfg(auto_trigger=True))
    runner._skill_loader = loader

    turn, _provider = await runner._run_pipeline(
        "please run tiny-meta-trigger for this request",
        "agent:main:test-auto-on",
        None,
        None,
        [
            ToolDefinition(
                name="meta_invoke",
                description="invoke",
                input_schema=ToolInputSchema(),
            ),
            ToolDefinition(name="web_search", description="search", input_schema=ToolInputSchema()),
        ],
        "base prompt",
        [],
    )

    assert turn.metadata["meta_match"].plan.name == "meta-tiny"
