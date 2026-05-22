from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import opensquilla.engine.agent as agent_mod
import opensquilla.engine.tokenjuice_adapter as tokenjuice_adapter_mod
from opensquilla.engine import Agent, AgentConfig, ToolCall, ToolResult
from opensquilla.engine.runtime import TurnRunner
from opensquilla.engine.types import ToolResultEvent
from opensquilla.gateway.config import AgentTokenSavingConfig
from opensquilla.plugins.tokenjuice import reduce_tool_result as plugin_reduce_tool_result
from opensquilla.provider import DoneEvent, TextDeltaEvent, ToolDefinition, ToolInputSchema
from opensquilla.provider import DoneEvent as ProviderDoneEvent
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
            raise AssertionError("summary provider should not be used")
        return self._stream()

    async def _stream(self):
        yield TextDeltaEvent(text=self.return_text or "")
        yield DoneEvent(stop_reason="stop", model="summary-model")

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


def test_agent_resolves_tokenjuice_compression_mode() -> None:
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(tool_result_compression_mode="tokenjuice"),
    )

    assert agent._tool_result_compression_mode() == "tokenjuice"


def test_runtime_resolves_tokenjuice_compression_mode() -> None:
    cfg = SimpleNamespace(
        tool_result_compression_mode="tokenjuice",
        tool_result_compression_enabled=True,
    )

    assert TurnRunner._resolve_tool_result_compression_mode(cfg) == "tokenjuice"


def test_gateway_config_accepts_tokenjuice_compression_mode() -> None:
    cfg = AgentTokenSavingConfig(tool_result_compression_mode="tokenjuice")

    assert cfg.effective_tool_result_compression_mode == "tokenjuice"


@pytest.mark.asyncio
async def test_truncate_mode_does_not_call_tokenjuice(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_reduce(**kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("truncate mode must not call tokenjuice")

    monkeypatch.setattr(agent_mod, "reduce_tool_result_with_tokenjuice", fail_reduce, raising=False)
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(
            context_window_tokens=100,
            tool_result_compression_mode="truncate",
            tool_result_compression_max_share=0.25,
        ),
    )
    result = ToolResult(
        tool_use_id="tool-1",
        tool_name="exec_command",
        content="pytest output\n" + ("x" * 1000),
    )

    compressed = await agent._compress_tool_result(
        result,
        tool_call=ToolCall(
            tool_use_id="tool-1",
            tool_name="exec_command",
            arguments={"command": "pytest -q", "workdir": "/repo"},
        ),
    )

    assert compressed.content != result.content
    assert "pytest output" in compressed.content
    assert "[...truncated" in compressed.content
    assert agent.config.metadata.get("tool_compression_backend") is None


@pytest.mark.asyncio
async def test_summarize_mode_does_not_call_tokenjuice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _Provider(return_text="summary result")

    def fail_reduce(**kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("summarize mode must not call tokenjuice")

    monkeypatch.setattr(agent_mod, "reduce_tool_result_with_tokenjuice", fail_reduce, raising=False)
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(
            context_window_tokens=100,
            tool_result_compression_mode="summarize",
            tool_result_compression_max_share=0.25,
        ),
        tool_result_summarizer_provider=provider,
    )
    result = ToolResult(
        tool_use_id="tool-1",
        tool_name="exec_command",
        content="long output\n" + ("x" * 1000),
    )

    compressed = await agent._compress_tool_result(result)

    assert "summary result" in compressed.content
    assert provider.chat_calls == 1
    assert agent.config.metadata.get("tool_compression_backend") is None


@pytest.mark.asyncio
async def test_tokenjuice_mode_uses_tokenjuice_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
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
        config=AgentConfig(
            context_window_tokens=100,
            tool_result_compression_mode="tokenjuice",
            tool_result_compression_max_share=0.25,
        ),
    )
    result = ToolResult(
        tool_use_id="tool-1",
        tool_name="exec_command",
        content="pytest output\n" + ("x" * 1000),
    )

    compressed = await agent._compress_tool_result(
        result,
        tool_call=ToolCall(
            tool_use_id="tool-1",
            tool_name="exec_command",
            arguments={"command": "pytest -q", "workdir": "/repo"},
        ),
    )

    assert compressed.content == "[tokenjuice]\n1 failed, 2 passed"
    assert calls[0]["tool_name"] == "exec_command"
    assert calls[0]["command"] == "pytest -q"
    assert calls[0]["cwd"] == "/repo"
    assert agent.config.metadata["tool_compression_backend"] == "tokenjuice"


@pytest.mark.asyncio
async def test_tokenjuice_mode_keeps_raw_result_when_tokenjuice_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_mod,
        "reduce_tool_result_with_tokenjuice",
        lambda **kwargs: None,
        raising=False,
    )
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(
            context_window_tokens=100,
            tool_result_compression_mode="tokenjuice",
            tool_result_compression_max_share=0.25,
        ),
    )
    result = ToolResult(
        tool_use_id="tool-1",
        tool_name="exec_command",
        content="long output\n" + ("x" * 1000),
    )

    compressed = await agent._compress_tool_result(result)

    assert compressed is result
    assert agent.config.metadata.get("tool_compression_backend") is None


@pytest.mark.asyncio
async def test_summarize_mode_falls_back_to_summary_provider_when_tokenjuice_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_mod,
        "reduce_tool_result_with_tokenjuice",
        lambda **kwargs: None,
        raising=False,
    )
    provider = _Provider(return_text="summary result")
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(
            context_window_tokens=100,
            tool_result_compression_mode="summarize",
            tool_result_compression_max_share=0.25,
        ),
        tool_result_summarizer_provider=provider,
    )
    result = ToolResult(
        tool_use_id="tool-1",
        tool_name="exec_command",
        content="long output\n" + ("x" * 1000),
    )

    compressed = await agent._compress_tool_result(result)

    assert "summary result" in compressed.content
    assert provider.chat_calls == 1


def test_tokenjuice_adapter_calls_python_plugin(
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
        "_reduce_tool_result_plugin",
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


def test_tokenjuice_adapter_returns_none_when_plugin_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tokenjuice_adapter_mod,
        "_reduce_tool_result_plugin",
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
        "_reduce_tool_result_plugin",
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


def test_python_plugin_reduces_pytest_output() -> None:
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

    result = plugin_reduce_tool_result(
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
        config=AgentConfig(
            context_window_tokens=500,
            max_iterations=2,
            tool_result_compression_mode="tokenjuice",
            tool_result_compression_max_share=0.25,
        ),
        tool_definitions=[_tool_def("exec_command")],
        tool_handler=handler,
    )

    events = [event async for event in agent.run_turn("run tests")]

    assert len(provider.calls) == 2
    second_call_tool_result = provider.calls[1][-1].content[0].content
    assert "FAILED tests/test_api.py::test_bad" in second_call_tool_result
    assert "AssertionError" in second_call_tool_result
    assert "rootdir:" not in second_call_tool_result
    assert agent.config.metadata["tool_compression_backend"] == "tokenjuice"
    raw_event = next(event for event in events if isinstance(event, ToolResultEvent))
    assert raw_event.result == output


def test_python_plugin_reduces_docker_build_output() -> None:
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

    result = plugin_reduce_tool_result(
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


def test_python_plugin_generic_fallback_head_tail() -> None:
    output = "\n".join(f"line {index}" for index in range(60))

    result = plugin_reduce_tool_result(
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
