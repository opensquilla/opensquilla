from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path


def test_live_soft_activation_harness_observes_model_meta_invoke(tmp_path: Path) -> None:
    from opensquilla.provider.types import DoneEvent as ProviderDoneEvent
    from opensquilla.provider.types import ToolUseDeltaEvent as ProviderToolUseDelta
    from opensquilla.provider.types import ToolUseEndEvent as ProviderToolUseEnd
    from opensquilla.provider.types import ToolUseStartEvent as ProviderToolUseStart
    from scripts.live_meta_soft_activation_e2e import (
        run_live_meta_soft_activation_e2e,
    )

    class _StubProvider:
        provider_name = "stub"

        async def chat(
            self,
            messages,
            tools=None,
            config=None,
        ) -> AsyncIterator:
            assert tools is not None
            assert any(tool.name == "meta_invoke" for tool in tools)
            yield ProviderToolUseStart(tool_use_id="tu_1", tool_name="meta_invoke")
            yield ProviderToolUseDelta(
                tool_use_id="tu_1",
                json_fragment='{"name": "meta-live-soft-activation"}',
            )
            yield ProviderToolUseEnd(
                tool_use_id="tu_1",
                tool_name="meta_invoke",
                arguments={"name": "meta-live-soft-activation"},
            )
            yield ProviderDoneEvent(stop_reason="tool_use")

        async def list_models(self):
            return []

    result = run_live_meta_soft_activation_e2e(
        home=tmp_path,
        provider_instance=_StubProvider(),
        model="stub",
        classify_override="LIVE_OK",
    )

    assert result["ok"] is True
    assert result["model_decision"]["meta_invoke_called"] is True
    assert result["model_decision"]["selected_meta_skill"] == "meta-live-soft-activation"
    assert "meta-step:classify" in result["observed_tool_results"]
    assert result["expected_output"] in result["final_text"]


def test_live_soft_activation_harness_runs_multiple_model_decision_cases(
    tmp_path: Path,
) -> None:
    from opensquilla.provider.types import DoneEvent as ProviderDoneEvent
    from opensquilla.provider.types import ToolUseEndEvent as ProviderToolUseEnd
    from opensquilla.provider.types import ToolUseStartEvent as ProviderToolUseStart
    from scripts.live_meta_soft_activation_e2e import run_live_meta_activation_cases

    class _CaseProvider:
        provider_name = "stub"

        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, tools=None, config=None) -> AsyncIterator:
            self.calls += 1
            if self.calls == 1:
                yield ProviderToolUseStart(tool_use_id="tu_1", tool_name="meta_invoke")
                yield ProviderToolUseEnd(
                    tool_use_id="tu_1",
                    tool_name="meta_invoke",
                    arguments={"name": "meta-live-soft-activation"},
                )
                yield ProviderDoneEvent(stop_reason="tool_use")
            else:
                yield ProviderDoneEvent(stop_reason="end_turn")

        async def list_models(self):
            return []

    result = run_live_meta_activation_cases(
        home=tmp_path,
        provider_instance=_CaseProvider(),
        cases=[
            {
                "name": "positive",
                "user_message": "Run the live soft activation workflow.",
                "expected_meta_skill": "meta-live-soft-activation",
            },
            {
                "name": "negative",
                "user_message": "Answer normally without a meta-skill.",
                "expected_meta_skill": None,
            },
        ],
        model="stub",
        classify_override="LIVE_OK",
    )

    assert result["ok"] is True
    assert [case["passed"] for case in result["cases"]] == [True, True]
    assert result["summary"] == {"passed": 2, "failed": 0, "total": 2}
