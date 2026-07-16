from __future__ import annotations

import importlib
import json
from typing import Any

import pytest

from opensquilla.engine.tool_result_store import ToolResultStore
from opensquilla.engine.types import ToolCall
from opensquilla.result_budget import ToolResultBudgetPolicy
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolContext, ToolSpec, current_tool_context


def _projection_spec(
    name: str,
    *,
    model_projector=None,
    sources_projector=None,
    result_budget_class: str | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"{name} projection probe",
        parameters={},
        result_budget_class=result_budget_class,
        model_result_projector=model_projector,
        result_sources_projector=sources_projector,
    )


def _handler_for(
    spec: ToolSpec,
    handler,
    ctx: ToolContext | None = None,
):
    registry = ToolRegistry()
    registry.register(spec, handler)
    return build_tool_handler(registry, ctx)


@pytest.mark.asyncio
async def test_success_projects_redacted_full_result_in_sources_then_model_order() -> None:
    secret = "sk-or-v1-abcdefghijklmnopqrstuvwxyz"
    raw = f"api_key={secret}\nfull redacted payload"
    calls: list[tuple[str, str]] = []

    def project_sources(content: str) -> list[dict[str, Any]]:
        calls.append(("sources", content))
        return [{"kind": "probe", "snippet": content}]

    def project_model(content: str) -> str:
        calls.append(("model", content))
        return "model-only"

    async def projected() -> str:
        return raw

    handler = _handler_for(
        _projection_spec(
            "projected",
            model_projector=project_model,
            sources_projector=project_sources,
        ),
        projected,
    )

    result = await handler(
        ToolCall(tool_use_id="tc-projected", tool_name="projected", arguments={})
    )

    assert result.content == "model-only"
    assert result.sources == [
        {
            "kind": "probe",
            "snippet": "api_key=[REDACTED]\nfull redacted payload",
        }
    ]
    assert calls == [
        ("sources", "api_key=[REDACTED]\nfull redacted payload"),
        ("model", "api_key=[REDACTED]\nfull redacted payload"),
    ]
    assert secret not in repr(calls)


@pytest.mark.asyncio
async def test_projectors_are_independently_optional() -> None:
    async def raw_result() -> str:
        return "full result"

    sources_handler = _handler_for(
        _projection_spec(
            "sources_only",
            sources_projector=lambda content: [{"snippet": content}],
        ),
        raw_result,
    )
    model_handler = _handler_for(
        _projection_spec(
            "model_only",
            model_projector=lambda content: f"projected:{content}",
        ),
        raw_result,
    )

    sources_only = await sources_handler(
        ToolCall(tool_use_id="tc-sources", tool_name="sources_only", arguments={})
    )
    model_only = await model_handler(
        ToolCall(tool_use_id="tc-model", tool_name="model_only", arguments={})
    )

    assert sources_only.content == "full result"
    assert sources_only.sources == [{"snippet": "full result"}]
    assert model_only.content == "projected:full result"
    assert model_only.sources == []


@pytest.mark.asyncio
async def test_model_projection_is_budgeted_by_configured_class_without_sources() -> None:
    raw = "RAW-" + ("r" * 1000)
    projected = "MODEL-" + ("m" * 200)
    sources = [{"kind": "probe", "snippet": "s" * 1000}]

    async def external_result() -> str:
        return raw

    handler = _handler_for(
        _projection_spec(
            "projected_external",
            result_budget_class="external",
            model_projector=lambda _content: projected,
            sources_projector=lambda _content: sources,
        ),
        external_result,
        ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=1000,
                max_single_external_result_chars=40,
            )
        ),
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-budgeted-projection",
            tool_name="projected_external",
            arguments={},
        )
    )

    payload = json.loads(result.content)
    assert payload["result_truncated"] is True
    assert payload["result_original_chars"] == len(projected)
    assert len(payload["preview"]) + len(payload["tail"]) <= 40
    assert "RAW-" not in result.content
    assert "s" * 10 not in result.content
    assert result.sources == sources


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "raw"),
    [
        ("ordinary_error", json.dumps({"status": "error", "message": "failed"})),
        ("ordinary_denial", json.dumps({"status": "denied", "message": "blocked"})),
        (
            "ordinary_approval",
            json.dumps({"status": "approval_pending", "approval_id": "approval-1"}),
        ),
        ("ordinary_control", json.dumps({"status": "control", "reason": "wait"})),
        ("exec_command", "exit_code=1\ncommand failed"),
    ],
)
async def test_non_success_results_bypass_projectors(tool_name: str, raw: str) -> None:
    calls: list[str] = []

    def project_sources(content: str) -> list[dict[str, Any]]:
        calls.append(f"sources:{content}")
        return [{"unexpected": True}]

    def project_model(content: str) -> str:
        calls.append(f"model:{content}")
        return "unexpected"

    async def non_success() -> str:
        return raw

    handler = _handler_for(
        _projection_spec(
            tool_name,
            model_projector=project_model,
            sources_projector=project_sources,
        ),
        non_success,
    )

    result = await handler(
        ToolCall(tool_use_id=f"tc-{tool_name}", tool_name=tool_name, arguments={})
    )

    assert result.content == raw
    assert result.sources == []
    assert calls == []


@pytest.mark.asyncio
async def test_handler_exception_bypasses_projectors() -> None:
    calls: list[str] = []

    async def boom() -> str:
        raise ValueError("handler failed")

    handler = _handler_for(
        _projection_spec(
            "boom",
            model_projector=lambda content: calls.append(f"model:{content}") or content,
            sources_projector=lambda content: calls.append(f"sources:{content}") or [],
        ),
        boom,
    )

    result = await handler(ToolCall(tool_use_id="tc-boom", tool_name="boom", arguments={}))

    assert result.is_error is True
    assert json.loads(result.content)["error_class"] == "ValueError"
    assert result.sources == []
    assert calls == []


class _RecordingLog:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **kwargs: Any) -> None:
        self.records.append((event, kwargs))

    def debug(self, event: str, **kwargs: Any) -> None:
        self.records.append((event, kwargs))


@pytest.mark.asyncio
async def test_sources_projector_failure_fails_closed_without_running_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finalize_module = importlib.import_module("opensquilla.tools.policy.finalize")
    recording_log = _RecordingLog()
    monkeypatch.setattr(finalize_module, "log", recording_log)
    secret = "sk-or-v1-abcdefghijklmnopqrstuvwxyz"
    raw = f"private-result-body api_key={secret}"
    calls: list[str] = []

    def fail_sources(content: str) -> list[dict[str, Any]]:
        calls.append("sources")
        raise RuntimeError(f"source failure included {content}")

    def project_model(content: str) -> str:
        calls.append("model")
        return content

    async def projected() -> str:
        return raw

    handler = _handler_for(
        _projection_spec(
            "sources_failure",
            model_projector=project_model,
            sources_projector=fail_sources,
        ),
        projected,
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-sources-failure",
            tool_name="sources_failure",
            arguments={},
        )
    )

    payload = json.loads(result.content)
    assert result.is_error is True
    assert payload["error_class"] == "tool_result_projection_failed"
    assert result.execution_status is not None
    assert result.execution_status["reason"] == "tool_result_projection_failed"
    assert result.sources == []
    assert calls == ["sources"]
    assert "private-result-body" not in result.content
    assert secret not in result.content
    logged = repr(recording_log.records)
    assert "RuntimeError" in logged
    assert "private-result-body" not in logged
    assert secret not in logged


@pytest.mark.asyncio
async def test_model_projector_failure_discards_projected_sources_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finalize_module = importlib.import_module("opensquilla.tools.policy.finalize")
    recording_log = _RecordingLog()
    monkeypatch.setattr(finalize_module, "log", recording_log)
    raw = "private-model-result-body"
    calls: list[str] = []

    def project_sources(content: str) -> list[dict[str, Any]]:
        calls.append("sources")
        return [{"snippet": content}]

    def fail_model(content: str) -> str:
        calls.append("model")
        raise KeyError(f"model failure included {content}")

    async def projected() -> str:
        return raw

    handler = _handler_for(
        _projection_spec(
            "model_failure",
            model_projector=fail_model,
            sources_projector=project_sources,
        ),
        projected,
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-model-failure",
            tool_name="model_failure",
            arguments={},
        )
    )

    payload = json.loads(result.content)
    assert result.is_error is True
    assert payload["error_class"] == "tool_result_projection_failed"
    assert result.execution_status is not None
    assert result.execution_status["reason"] == "tool_result_projection_failed"
    assert result.sources == []
    assert calls == ["sources", "model"]
    assert raw not in result.content
    logged = repr(recording_log.records)
    assert "KeyError" in logged
    assert raw not in logged


@pytest.mark.asyncio
async def test_truncated_snapshot_contains_full_projected_model_string_not_raw_result(
    tmp_path,
) -> None:
    raw = "RAW-REMOVED-" + ("r" * 1000)
    projected = "MODEL-KEPT-" + ("m" * 200)

    async def large_result() -> str:
        return raw

    store_dir = tmp_path / "tool-results"
    handler = _handler_for(
        _projection_spec(
            "projected_snapshot",
            model_projector=lambda _content: projected,
            sources_projector=lambda _content: [{"kind": "probe"}],
        ),
        large_result,
        ToolContext(
            agent_id="main",
            session_key="agent:main:projection",
            tool_result_store_dir=str(store_dir),
            tool_result_store_session_id="session-projection",
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=48,
            ),
        ),
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-projected-snapshot",
            tool_name="projected_snapshot",
            arguments={},
        )
    )

    payload = json.loads(result.content)
    stored = ToolResultStore(store_dir).read(
        payload["tool_result_handle"],
        session_id="session-projection",
    )
    assert payload["result_original_chars"] == len(projected)
    assert stored.content == projected
    assert "RAW-REMOVED" not in stored.content
    assert result.sources == [{"kind": "probe"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["web_search", "web_fetch", "ordinary_probe"])
async def test_unconfigured_tools_preserve_byte_identical_content_and_empty_sources(
    tool_name: str,
) -> None:
    raw = "unchanged bytes:\x00ÿ\n\tend"

    async def unconfigured(**_kwargs: Any) -> str:
        return raw

    handler = _handler_for(
        _projection_spec(
            tool_name,
            result_budget_class=(
                "external" if tool_name in {"web_search", "web_fetch"} else None
            ),
        ),
        unconfigured,
    )

    result = await handler(
        ToolCall(tool_use_id=f"tc-{tool_name}", tool_name=tool_name, arguments={})
    )

    assert result.content == raw
    assert result.sources == []


@pytest.mark.asyncio
async def test_projection_preserves_artifacts_and_pre_projection_execution_status() -> None:
    artifact = {"id": "artifact-projection", "kind": "artifact_ref"}

    async def exec_command() -> str:
        ctx = current_tool_context.get()
        assert ctx is not None
        ctx.published_artifacts.append(artifact)
        return "exit_code=0\nfull successful output"

    handler = _handler_for(
        _projection_spec(
            "exec_command",
            model_projector=lambda _content: "projected successful output",
            sources_projector=lambda _content: [{"kind": "probe"}],
        ),
        exec_command,
        ToolContext(
            session_key="agent:main:artifact-projection",
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=1,
            ),
        ),
    )

    result = await handler(
        ToolCall(tool_use_id="tc-exec-projection", tool_name="exec_command", arguments={})
    )

    assert result.content == "projected successful output"
    assert result.artifacts == [artifact]
    assert result.sources == [{"kind": "probe"}]
    assert result.is_error is False
    assert result.execution_status is not None
    assert result.execution_status["status"] == "success"
    assert result.execution_status["exit_code"] == 0
    assert result.execution_status["truncated"] is False


@pytest.mark.asyncio
async def test_model_projection_does_not_change_router_control_turn_termination() -> None:
    raw = json.dumps(
        {
            "status": "router_control",
            "accepted": True,
            "action": "set_hold",
            "replay_required": True,
        }
    )

    async def router_control() -> str:
        return raw

    handler = _handler_for(
        _projection_spec(
            "router_control",
            model_projector=lambda _content: "projected router result",
        ),
        router_control,
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-router-projection",
            tool_name="router_control",
            arguments={},
        )
    )

    assert result.content == "projected router result"
    assert result.terminates_turn is True
