from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import opensquilla.engine.agent as agent_mod
import opensquilla.engine.tokenjuice_adapter as tokenjuice_adapter_mod
from opensquilla.engine import Agent, AgentConfig, ToolCall, ToolResult
from opensquilla.engine.types import ToolResultEvent, ToolUseDeltaEvent
from opensquilla.plugins.tokenjuice import reduce_tool_result as backend_reduce_tool_result
from opensquilla.provider import DoneEvent as ProviderDoneEvent
from opensquilla.provider import TextDeltaEvent, ToolDefinition, ToolInputSchema
from opensquilla.provider import ToolUseDeltaEvent as ProviderToolUseDeltaEvent
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEndEvent
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStartEvent


class _Provider:
    provider_name = "fake"

    def __init__(self, return_text: str | None = None) -> None:
        self.return_text = return_text
        self.chat_calls = 0

    def chat(self, messages, tools=None, config=None):
        self.chat_calls += 1
        if self.return_text is None:  # pragma: no cover - must not run
            raise AssertionError("provider should not be used")
        return self._stream()

    async def _stream(self):
        yield TextDeltaEvent(text=self.return_text or "")
        yield ProviderDoneEvent(stop_reason="stop", model="fake-model")

    async def list_models(self) -> list[Any]:
        return []


class _ToolCallingProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def chat(self, messages, tools=None, config=None):
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int):
        if call_number == 1:
            yield ProviderToolUseStartEvent(tool_use_id="tool-1", tool_name="exec_command")
            yield ProviderToolUseDeltaEvent(
                tool_use_id="tool-1",
                json_fragment='{"command": "pytest -q"',
            )
            yield ProviderToolUseDeltaEvent(
                tool_use_id="tool-1",
                json_fragment=', "workdir": "/repo"}',
            )
            yield ProviderToolUseEndEvent(
                tool_use_id="tool-1",
                tool_name="exec_command",
                arguments={"command": "pytest -q", "workdir": "/repo"},
            )
            yield ProviderDoneEvent(stop_reason="tool_use", input_tokens=1, output_tokens=1)
            return
        yield TextDeltaEvent(text="done")
        yield ProviderDoneEvent(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


def _tool_def(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Mock tool {name}",
        input_schema=ToolInputSchema(properties={}, required=[]),
    )


@pytest.mark.asyncio
async def test_agent_projects_tokenjuice_without_context_window_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_reduce(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(
            inline_text="[tokenjuice]\n1 failed, 2 passed",
            raw_chars=len(kwargs["content"]),
            reduced_chars=30,
            ratio=0.1,
            reducer="tests/pytest",
        )

    monkeypatch.setattr(agent_mod, "reduce_tool_result_with_tokenjuice", fake_reduce, raising=False)
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(context_window_tokens=1_000_000),
    )
    result = ToolResult(
        tool_use_id="tool-1",
        tool_name="exec_command",
        content="pytest output\n" + ("x" * 1000),
    )

    projected = await agent._canonicalize_tool_result(
        result,
        tool_call=ToolCall(
            tool_use_id="tool-1",
            tool_name="exec_command",
            arguments={"command": "pytest -q", "workdir": "/repo"},
        ),
    )

    assert calls
    assert projected.content == "[tokenjuice]\n1 failed, 2 passed"
    assert calls[0]["tool_name"] == "exec_command"
    assert calls[0]["command"] == "pytest -q"
    assert calls[0]["cwd"] == "/repo"
    assert agent.config.metadata["tool_projection_backend"] == "tokenjuice"
    assert agent.config.metadata["tool_projection_attempts"] == 1
    assert agent.config.metadata["tool_projection_calls"] == 1


@pytest.mark.asyncio
async def test_tokenjuice_noop_preserves_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_mod,
        "reduce_tool_result_with_tokenjuice",
        lambda **kwargs: None,
        raising=False,
    )
    agent = Agent(provider=_Provider(), config=AgentConfig(context_window_tokens=100))
    result = ToolResult(
        tool_use_id="tool-1",
        tool_name="exec_command",
        content="short output",
    )

    projected = await agent._canonicalize_tool_result(result)

    assert projected is result
    assert projected.content == "short output"
    assert agent.config.metadata["tool_projection_attempts"] == 1
    assert agent.config.metadata["tool_projection_noops"] == 1
    assert "tool_projection_backend" not in agent.config.metadata


@pytest.mark.asyncio
async def test_tokenjuice_projection_does_not_store_raw_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    def fake_reduce(**kwargs: Any) -> Any:
        return SimpleNamespace(
            inline_text="[tokenjuice]\nimportant failure",
            raw_chars=len(kwargs["content"]),
            reduced_chars=28,
            ratio=0.1,
            reducer="tests/pytest",
        )

    monkeypatch.setattr(agent_mod, "reduce_tool_result_with_tokenjuice", fake_reduce, raising=False)
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(),
    )
    raw_output = "raw output\n" + ("x" * 8000)

    projected = await agent._canonicalize_tool_result(
        ToolResult(
            tool_use_id="tool-1",
            tool_name="exec_command",
            content=raw_output,
            is_error=True,
        )
    )

    assert projected.content == "[tokenjuice]\nimportant failure"
    assert "tool_result_handle:" not in projected.content
    assert raw_output not in projected.content
    assert not (tmp_path / "tool-results").exists()


def test_tokenjuice_adapter_calls_python_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_reduce(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(
            inline_text="reduced output",
            raw_chars=23,
            reduced_chars=14,
            ratio=14 / 23,
            reducer="tests/pytest",
        )

    monkeypatch.setattr(
        tokenjuice_adapter_mod,
        "_reduce_tool_result_backend",
        fake_reduce,
    )

    result = tokenjuice_adapter_mod.reduce_tool_result_with_tokenjuice(
        tool_name="exec_command",
        content="raw output with details",
        is_error=False,
        tool_use_id="tool-1",
        arguments={"command": "pytest -q", "workdir": "/repo"},
        max_inline_chars=600,
    )

    assert result is not None
    assert result.inline_text == "reduced output"
    assert result.reducer == "tests/pytest"
    assert captured["tool_name"] == "exec_command"
    assert captured["content"] == "raw output with details"
    assert captured["is_error"] is False
    assert captured["tool_use_id"] == "tool-1"
    assert captured["arguments"] == {"command": "pytest -q", "workdir": "/repo"}
    assert captured["command"] == "pytest -q"
    assert captured["cwd"] == "/repo"
    assert captured["max_inline_chars"] == 600


def test_tokenjuice_adapter_returns_none_when_backend_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tokenjuice_adapter_mod,
        "_reduce_tool_result_backend",
        lambda **kwargs: None,
    )

    assert (
        tokenjuice_adapter_mod.reduce_tool_result_with_tokenjuice(
            tool_name="exec_command",
            content="raw output",
            is_error=False,
            tool_use_id="tool-1",
        )
        is None
    )


def test_tokenjuice_adapter_ignores_non_shrinking_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_reduce(**kwargs: Any) -> Any:
        return SimpleNamespace(
            inline_text="this output is longer than raw output",
            raw_chars=10,
            reduced_chars=35,
            ratio=3.5,
            reducer="generic/fallback",
        )

    monkeypatch.setattr(
        tokenjuice_adapter_mod,
        "_reduce_tool_result_backend",
        fake_reduce,
    )

    assert (
        tokenjuice_adapter_mod.reduce_tool_result_with_tokenjuice(
            tool_name="exec_command",
            content="raw output",
            is_error=False,
            tool_use_id="tool-1",
        )
        is None
    )


def test_tokenjuice_adapter_ignores_trailing_newline_only_reduction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_reduce(**kwargs: Any) -> Any:
        return SimpleNamespace(
            inline_text="exit_code=0\ninstalled",
            raw_chars=22,
            reduced_chars=21,
            ratio=21 / 22,
            reducer="generic/fallback",
        )

    monkeypatch.setattr(
        tokenjuice_adapter_mod,
        "_reduce_tool_result_backend",
        fake_reduce,
    )

    assert (
        tokenjuice_adapter_mod.reduce_tool_result_with_tokenjuice(
            tool_name="exec_command",
            content="exit_code=0\ninstalled\n",
            is_error=False,
            tool_use_id="tool-1",
        )
        is None
    )


def test_python_backend_reduces_pytest_output() -> None:
    output = "\n".join(
        [
            "platform darwin -- Python 3.13",
            "rootdir: /repo",
            "collected 3 items",
            "tests/test_api.py::test_ok PASSED",
            "tests/test_api.py::test_bad FAILED",
            "E   AssertionError: expected 1 == 2",
            "FAILED tests/test_api.py::test_bad - AssertionError",
            "=========================== 1 failed, 1 passed in 0.12s ===========================",
        ]
    )

    result = backend_reduce_tool_result(
        tool_name="exec_command",
        tool_use_id="tool-1",
        command="pytest -q",
        content=output,
        is_error=True,
        max_inline_chars=600,
    )

    assert result is not None
    assert result.reducer == "tests/pytest"
    assert "FAILED tests/test_api.py::test_bad" in result.inline_text
    assert "AssertionError" in result.inline_text
    assert "rootdir:" not in result.inline_text


@pytest.mark.asyncio
async def test_run_turn_feeds_tokenjuice_reduced_tool_result_to_next_provider_call() -> None:
    output = "\n".join(
        [
            "platform darwin -- Python 3.13",
            "rootdir: /repo",
            "collected 3 items",
            *(f"tests/test_api.py::test_extra_{index} PASSED" for index in range(40)),
            "tests/test_api.py::test_ok PASSED",
            "tests/test_api.py::test_bad FAILED",
            "E   AssertionError: expected 1 == 2",
            "FAILED tests/test_api.py::test_bad - AssertionError",
            "=========================== 1 failed, 1 passed in 0.12s ===========================",
        ]
    )

    async def handler(tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=tool_call.tool_use_id,
            tool_name=tool_call.tool_name,
            content=output,
            is_error=True,
        )

    provider = _ToolCallingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(context_window_tokens=1_000_000, max_iterations=2),
        tool_definitions=[_tool_def("exec_command")],
        tool_handler=handler,
    )

    events = [event async for event in agent.run_turn("run tests")]

    assert len(provider.calls) == 2
    second_call_tool_result = provider.calls[1][-1].content[0].content
    assert "FAILED tests/test_api.py::test_bad" in second_call_tool_result
    assert "AssertionError" in second_call_tool_result
    assert "rootdir:" not in second_call_tool_result
    assert agent.config.metadata["tool_projection_backend"] == "tokenjuice"
    projected_event = next(event for event in events if isinstance(event, ToolResultEvent))
    delta_fragments = [
        event.json_fragment for event in events if isinstance(event, ToolUseDeltaEvent)
    ]
    assert delta_fragments == ['{"command": "pytest -q"', ', "workdir": "/repo"}']
    assert projected_event.result == second_call_tool_result
    assert projected_event.result != output
    assert "rootdir:" not in projected_event.result


@pytest.mark.asyncio
async def test_approval_retry_clears_stale_tool_result_projection() -> None:
    approval_payload = json.dumps(
        {
            "status": "approval_required",
            "approval_id": "approval-1",
            "message": "Approve this command.",
            "lines": [str(index) for index in range(80)],
        },
        indent=2,
    )
    calls = 0

    async def handler(tool_call: ToolCall) -> ToolResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ToolResult(
                tool_use_id=tool_call.tool_use_id,
                tool_name=tool_call.tool_name,
                content=approval_payload,
            )
        assert tool_call.arguments["approval_id"] == "approval-1"
        return ToolResult(
            tool_use_id=tool_call.tool_use_id,
            tool_name=tool_call.tool_name,
            content="FINAL_OK",
        )

    provider = _ToolCallingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(context_window_tokens=1_000_000, max_iterations=2),
        tool_definitions=[_tool_def("exec_command")],
        tool_handler=handler,
    )

    events = [event async for event in agent.run_turn("run risky command")]

    assert calls == 2
    assert len(provider.calls) == 2
    second_call_tool_result = provider.calls[1][-1].content[0].content
    assert second_call_tool_result == "FINAL_OK"
    tool_result_events = [event for event in events if isinstance(event, ToolResultEvent)]
    approval_event_payload = json.loads(tool_result_events[0].result)
    assert approval_event_payload["status"] == "approval_required"
    assert approval_event_payload["approval_id"] == "approval-1"
    assert tool_result_events[-1].result == "FINAL_OK"


def test_python_backend_reduces_docker_build_output() -> None:
    output = "\n".join(
        [
            "#1 [internal] load build definition from Dockerfile",
            "#1 sha256:1234",
            "#1 DONE 0.1s",
            "#2 [2/3] RUN pnpm install",
            "#2 1.234 lots of progress",
            "#2 ERROR: process exited with code 1",
            "ERROR: failed to solve: process exited with code 1",
        ]
    )

    result = backend_reduce_tool_result(
        tool_name="exec_command",
        tool_use_id="tool-1",
        command="docker build .",
        content=output,
        is_error=True,
        max_inline_chars=600,
    )

    assert result is not None
    assert result.reducer == "devops/docker-build"
    assert "ERROR: failed to solve" in result.inline_text
    assert "sha256:1234" not in result.inline_text


def test_python_backend_generic_fallback_head_tail() -> None:
    output = "\n".join(f"line {index}" for index in range(60))

    result = backend_reduce_tool_result(
        tool_name="exec_command",
        tool_use_id="tool-1",
        command="custom-tool --verbose",
        content=output,
        is_error=False,
        max_inline_chars=400,
    )

    assert result is not None
    assert result.reducer == "generic/fallback"
    assert "line 0" in result.inline_text
    assert "line 59" in result.inline_text
    assert "omitted" in result.inline_text


def test_typescript_runtime_directory_is_not_present() -> None:
    from pathlib import Path

    assert not (Path(__file__).resolve().parents[2] / "src/opensquilla/tokenjuice_runtime").exists()
