"""Tests for chat command — verify CLI interface and routing."""

from __future__ import annotations

import ast
import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from opensquilla.cli import (
    chat_cmd,
    chat_presenters,
    chat_session_workflows,
    chat_slash_workflows,
    chat_standalone_repl,
    chat_transcript_exports,
)
from opensquilla.cli.main import app
from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.repl.stream import TurnResult, UsageSummary
from opensquilla.engine.types import ArtifactEvent, DoneEvent, TextDeltaEvent
from opensquilla.session.compaction import CompactionConfig
from opensquilla.tools.types import CallerKind, ToolContext

runner = CliRunner()


class TestChatCommand:
    def test_chat_help(self) -> None:
        result = runner.invoke(
            app,
            ["chat", "--help"],
            env={"COLUMNS": "120", "NO_COLOR": "1", "TERM": "dumb"},
        )
        assert result.exit_code == 0
        assert "--model" in result.output
        assert "--session" in result.output

    def test_chat_invokes_run_chat(self) -> None:
        """Default chat calls run_chat with correct defaults."""
        mock_run = MagicMock()
        with patch("opensquilla.cli.chat_cmd.run_chat", mock_run):
            result = runner.invoke(app, ["chat"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            model="",
            session_id="",
            standalone=False,
            workspace="",
            workspace_strict=None,
            timeout=None,
        )

    def test_chat_model_option_forwarded(self) -> None:
        """--model option is forwarded to run_chat."""
        mock_run = MagicMock()
        with patch("opensquilla.cli.chat_cmd.run_chat", mock_run):
            result = runner.invoke(app, ["chat", "--model", "ollama/llama3"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            model="ollama/llama3",
            session_id="",
            standalone=False,
            workspace="",
            workspace_strict=None,
            timeout=None,
        )

    def test_chat_session_option_forwarded(self) -> None:
        """--session option is forwarded to run_chat."""
        mock_run = MagicMock()
        with patch("opensquilla.cli.chat_cmd.run_chat", mock_run):
            result = runner.invoke(app, ["chat", "--session", "abc123"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            model="",
            session_id="abc123",
            standalone=False,
            workspace="",
            workspace_strict=None,
            timeout=None,
        )

    def test_chat_timeout_option_forwarded(self) -> None:
        """--timeout option is forwarded to run_chat."""
        mock_run = MagicMock()
        with patch("opensquilla.cli.chat_cmd.run_chat", mock_run):
            result = runner.invoke(app, ["chat", "--timeout", "12.5"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            model="",
            session_id="",
            standalone=False,
            workspace="",
            workspace_strict=None,
            timeout=12.5,
        )

    def test_chat_workspace_options_forwarded(self) -> None:
        mock_run = MagicMock()
        with patch("opensquilla.cli.chat_cmd.run_chat", mock_run):
            result = runner.invoke(
                app,
                ["chat", "--workspace", "repo", "--workspace-strict"],
            )
        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            model="",
            session_id="",
            standalone=False,
            workspace="repo",
            workspace_strict=True,
            timeout=None,
        )

    def test_gateway_chat_workspace_options_warn_without_forwarding(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        buffer = io.StringIO()
        called: dict[str, object] = {}

        async def fake_gateway_chat(model: str | None, session_id: str | None) -> None:
            called["model"] = model
            called["session_id"] = session_id

        monkeypatch.setattr(chat_cmd.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(
            chat_cmd,
            "console",
            Console(file=buffer, force_terminal=True, color_system=None, no_color=True),
        )
        monkeypatch.setattr(chat_cmd, "_gateway_chat", fake_gateway_chat)

        chat_cmd.run_chat(
            model="",
            session_id="",
            standalone=False,
            workspace="repo",
            workspace_strict=True,
            timeout=None,
        )

        assert called == {"model": None, "session_id": None}
        output = buffer.getvalue()
        assert "--workspace only affects --standalone chat" in output
        assert "requires the path to be visible to the gateway runtime" in output

    def test_chat_rejects_extra_args(self) -> None:
        """Extra positional args (like 'send Hello') are rejected."""
        result = runner.invoke(app, ["chat", "send", "Hello"])
        assert result.exit_code != 0


class _FakeSessionManager:
    def __init__(self) -> None:
        self.get_or_create_calls: list[dict[str, str]] = []
        self.compact_calls: list[tuple[str, int, object | None]] = []
        self.truncate_calls: list[tuple[str, int]] = []
        self.transcripts: dict[str, list[object]] = {}

    async def get_or_create(self, session_key: str, agent_id: str = "main") -> object:
        self.get_or_create_calls.append({"session_key": session_key, "agent_id": agent_id})
        return SimpleNamespace(session_key=session_key, agent_id=agent_id)

    async def append_message(self, session_key: str, role: str, content: str) -> object:
        entry = SimpleNamespace(role=role, content=content)
        self.transcripts.setdefault(session_key, []).append(entry)
        return entry

    async def get_transcript(self, session_key: str) -> list[object]:
        return list(self.transcripts.get(session_key, []))

    async def truncate(self, session_key: str, max_messages: int = 0) -> None:
        self.truncate_calls.append((session_key, max_messages))
        if max_messages <= 0:
            self.transcripts[session_key] = []
        else:
            self.transcripts[session_key] = self.transcripts.get(session_key, [])[-max_messages:]

    async def compact(self, session_key: str, context_window_tokens: int, config=None) -> str:
        self.compact_calls.append((session_key, context_window_tokens, config))
        return "summary"


class _LegacyCompactSessionManager(_FakeSessionManager):
    async def compact(self, session_key: str, context_window_tokens: int) -> str:
        self.compact_calls.append((session_key, context_window_tokens, None))
        return "summary"


class _FakeCompactionProvider:
    provider_name = "openai"

    def __init__(self) -> None:
        self._api_key = "cli-provider-key"
        self._model = "provider/model"
        self._base_url = "https://openrouter.ai/api/v1"

    @property
    def model(self) -> str:
        return self._model


class _FakeProviderSelector:
    def __init__(self, provider: _FakeCompactionProvider | None = None) -> None:
        self.provider = provider or _FakeCompactionProvider()

    def clone(self) -> _FakeProviderSelector:
        return self

    def resolve(self) -> _FakeCompactionProvider:
        return self.provider


class _FakeServices:
    def __init__(self) -> None:
        self.memory_sync_managers = {"main": object()}
        self.memory_retrievers = {"main": object()}
        self.turn_capture_services = {"main": object()}
        self.flush_service = None
        self.model_catalog = object()
        self.provider_selector = MagicMock()
        self.tool_registry = None
        self.session_manager = _FakeSessionManager()
        self.skill_loader = None
        self.usage_tracker = None
        self.config = None

    async def close(self) -> None:
        return None


class _DummyLive:
    def __init__(self, *args, **kwargs) -> None:
        return None

    def __enter__(self) -> _DummyLive:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, *args, **kwargs) -> None:
        return None


class _RecordingRenderer:
    instances: list[_RecordingRenderer] = []

    def __init__(self, *args, **kwargs) -> None:
        self.buffer = ""
        self.pulses = 0
        self.errors: list[str] = []
        self.finalized = False
        _RecordingRenderer.instances.append(self)

    def __enter__(self) -> _RecordingRenderer:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def append_text(self, delta: str) -> None:
        self.buffer += delta

    def pulse(self) -> None:
        self.pulses += 1

    def tool_call(self, name: str, args=None) -> None:
        return None

    def error(self, message: str) -> None:
        self.errors.append(message)

    def finalize(self, usage=None, *, cancelled: bool = False) -> None:
        self.finalized = True


@pytest.mark.asyncio
async def test_standalone_repl_forwards_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}
    inputs = iter(["hello", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            captured["message"] = message
            captured["session_key"] = session_key
            captured["timeout"] = kwargs.get("timeout")
            captured["tool_context"] = kwargs["tool_context"]
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return _FakeServices()

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/test",
        session_id="standalone:test",
        timeout=7.25,
    )

    assert captured["message"] == "hello"
    assert captured["session_key"] == "standalone:test"
    assert captured["timeout"] == 7.25
    assert captured["tool_context"].channel_kind == "cli"
    assert captured["tool_context"].channel_id == "cli:chat"
    assert captured["tool_context"].sender_id


@pytest.mark.asyncio
async def test_standalone_chat_uses_workspace_in_tool_context(
    monkeypatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}
    inputs = iter(["hello", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            captured["tool_context"] = kwargs["tool_context"]
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return _FakeServices()

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/test",
        session_id="standalone:test",
        workspace=str(tmp_path),
        workspace_strict=True,
    )

    tool_context = captured["tool_context"]
    assert tool_context.workspace_dir == str(tmp_path)
    assert tool_context.workspace_strict is True


@pytest.mark.asyncio
async def test_standalone_path_command_runs_as_plain_message(
    monkeypatch,
    tmp_path,
) -> None:
    target = tmp_path / "large.log"
    target.write_text("hello\n", encoding="utf-8")
    captured: dict[str, object] = {}
    inputs = iter([f"/path {target} inspect", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            captured["message"] = message
            captured["kwargs"] = kwargs
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return _FakeServices()

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/test",
        session_id="standalone:test",
    )

    assert "inspect" in captured["message"]
    assert str(target.resolve(strict=False)) in captured["message"]
    assert "attachments" not in captured["kwargs"]


@pytest.mark.asyncio
async def test_standalone_path_workflow_streams_prompt_without_attachments(
    tmp_path,
) -> None:
    from opensquilla.cli import chat_standalone_path_workflows

    target = tmp_path / "large.log"
    target.write_text("hello\n", encoding="utf-8")
    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    turn_runner = object()
    tool_context = object()
    services = object()
    calls: list[dict[str, object]] = []

    async def stream_response(
        runner: object,
        session_key: str,
        context: object,
        prompt: str,
        **kwargs: object,
    ) -> TurnResult:
        calls.append(
            {
                "runner": runner,
                "session_key": session_key,
                "context": context,
                "prompt": prompt,
                "kwargs": kwargs,
            }
        )
        return TurnResult(
            text="path reply",
            usage=UsageSummary(
                input_tokens=4,
                output_tokens=6,
                cached_tokens=2,
                cost_usd=0.0123,
            ),
        )

    handled = await chat_standalone_path_workflows.handle_standalone_path_command(
        f"/path {target} inspect",
        ["/path", f"{target} inspect"],
        state,
        turn_runner=turn_runner,
        tool_context=tool_context,
        services=services,
        model="openrouter/test",
        timeout=12.5,
        stream_response=stream_response,
    )

    assert handled is True
    assert len(calls) == 1
    call = calls[0]
    assert call["runner"] is turn_runner
    assert call["session_key"] == "standalone:test"
    assert call["context"] is tool_context
    assert "inspect" in call["prompt"]
    assert str(target.resolve(strict=False)) in call["prompt"]
    assert call["kwargs"] == {
        "model": "openrouter/test",
        "svc": services,
        "timeout": 12.5,
    }
    assert "attachments" not in call["kwargs"]
    assert state.transcript.to_markdown().count("path reply") == 1
    assert state.usage.render() == "10 tok (4 in / 6 out) · cache 2 · $0.012300"


@pytest.mark.asyncio
async def test_standalone_path_workflow_prints_usage_without_path(monkeypatch) -> None:
    from opensquilla.cli import chat_standalone_path_workflows

    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    buffer = io.StringIO()

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response must not run without a path")

    monkeypatch.setattr(
        chat_standalone_path_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_standalone_path_workflows.handle_standalone_path_command(
        "/path",
        ["/path"],
        state,
        turn_runner=object(),
        tool_context=object(),
        services=object(),
        model="openrouter/test",
        timeout=None,
        stream_response=stream_response,
    )

    assert handled is True
    assert "Usage: /path <path> [prompt]" in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_standalone_path_workflow_rejects_unexpected_attachments(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_standalone_path_workflows

    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    buffer = io.StringIO()

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response must not run when /path returns attachments")

    def prompt_and_attachments(command: str) -> tuple[str, list[dict[str, object]]]:
        assert command == "/path /tmp/example.txt inspect"
        return "prompt", [{"kind": "unexpected"}]

    monkeypatch.setattr(
        chat_standalone_path_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_standalone_path_workflows.handle_standalone_path_command(
        "/path /tmp/example.txt inspect",
        ["/path", "/tmp/example.txt inspect"],
        state,
        turn_runner=object(),
        tool_context=object(),
        services=object(),
        model="openrouter/test",
        timeout=None,
        stream_response=stream_response,
        path_prompt_and_attachments=prompt_and_attachments,
    )

    assert handled is True
    assert "/path must not create attachments." in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_standalone_image_workflow_runs_image_command_and_updates_state() -> None:
    from opensquilla.cli import chat_standalone_image_workflows

    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    turn_runner = object()
    tool_context = object()
    services = object()
    calls: list[dict[str, object]] = []

    async def run_image_command(
        runner: object,
        session_key: str,
        context: object,
        command: str,
        **kwargs: object,
    ) -> TurnResult:
        calls.append(
            {
                "runner": runner,
                "session_key": session_key,
                "context": context,
                "command": command,
                "kwargs": kwargs,
            }
        )
        return TurnResult(
            text="image reply",
            usage=UsageSummary(input_tokens=7, output_tokens=11, cost_usd=0.021),
        )

    def prompt_from_command(command: str) -> str:
        assert command == "/image /tmp/chart.png describe chart"
        return "describe chart"

    handled = await chat_standalone_image_workflows.handle_standalone_image_command(
        "/image /tmp/chart.png describe chart",
        ["/image", "/tmp/chart.png describe chart"],
        state,
        turn_runner=turn_runner,
        tool_context=tool_context,
        services=services,
        model="openrouter/test",
        timeout=3.5,
        run_image_command=run_image_command,
        image_prompt_from_command=prompt_from_command,
    )

    assert handled is True
    assert calls == [
        {
            "runner": turn_runner,
            "session_key": "standalone:test",
            "context": tool_context,
            "command": "/image /tmp/chart.png describe chart",
            "kwargs": {
                "model": "openrouter/test",
                "svc": services,
                "timeout": 3.5,
            },
        }
    ]
    transcript = state.transcript.to_markdown()
    assert "describe chart" in transcript
    assert "image reply" in transcript
    assert state.usage.render() == "18 tok (7 in / 11 out) · cache 0 · $0.021000"


@pytest.mark.asyncio
async def test_standalone_image_workflow_prints_usage_without_path(monkeypatch) -> None:
    from opensquilla.cli import chat_standalone_image_workflows

    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    buffer = io.StringIO()

    async def run_image_command(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("run_image_command must not run without a path")

    monkeypatch.setattr(
        chat_standalone_image_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_standalone_image_workflows.handle_standalone_image_command(
        "/image",
        ["/image"],
        state,
        turn_runner=object(),
        tool_context=object(),
        services=object(),
        model="openrouter/test",
        timeout=None,
        run_image_command=run_image_command,
    )

    assert handled is True
    assert "Usage: /image <path> [prompt]" in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_standalone_model_command_updates_next_turn_model(monkeypatch) -> None:
    captured: dict[str, object] = {}
    inputs = iter(["/model anthropic/claude-sonnet-4", "hello", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            captured["message"] = message
            captured["session_key"] = session_key
            captured["model"] = kwargs.get("model")
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return _FakeServices()

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/old",
        session_id="standalone:test",
    )

    assert captured["message"] == "hello"
    assert captured["session_key"] == "standalone:test"
    assert captured["model"] == "anthropic/claude-sonnet-4"


@pytest.mark.asyncio
async def test_standalone_status_commands_emit_without_turnrunner_calls(monkeypatch) -> None:
    run_messages: list[str] = []
    inputs = iter(["/status", "/session", "/models", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            run_messages.append(message)
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return _FakeServices()

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/test",
        session_id="standalone:test",
    )

    assert run_messages == []


@pytest.mark.asyncio
async def test_standalone_new_command_updates_next_turn_session(monkeypatch) -> None:
    services = _FakeServices()
    inputs = iter(["/new Research Notes", "hello", "/quit"])
    run_calls: list[dict[str, object]] = []

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            run_calls.append(
                {
                    "message": message,
                    "session_key": session_key,
                    "tool_context": kwargs.get("tool_context"),
                    "model": kwargs.get("model"),
                }
            )
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return services

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/test",
        session_id="standalone:test",
    )

    assert len(services.session_manager.get_or_create_calls) == 2
    assert services.session_manager.get_or_create_calls[0] == {
        "session_key": "standalone:test",
        "agent_id": "main",
    }
    new_session_key = services.session_manager.get_or_create_calls[1]["session_key"]
    assert new_session_key.startswith("agent:main:standalone:")
    assert run_calls[0]["message"] == "hello"
    assert run_calls[0]["session_key"] == new_session_key
    assert run_calls[0]["model"] == "openrouter/test"
    assert getattr(run_calls[0]["tool_context"], "session_key") == new_session_key


def test_chat_workspace_strict_resolution_matches_agent_precedence(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.cli.agent_cmd import _resolve_workspace_strict

    monkeypatch.setenv("OPENSQUILLA_WORKSPACE_STRICT", "false")
    assert (
        _resolve_workspace_strict(
            cli_value=True,
            config_value=False,
            entrypoint_default=bool(tmp_path),
        )
        is True
    )
    assert (
        _resolve_workspace_strict(
            cli_value=None,
            config_value=True,
            entrypoint_default=bool(tmp_path),
        )
        is False
    )
    monkeypatch.delenv("OPENSQUILLA_WORKSPACE_STRICT")
    assert (
        _resolve_workspace_strict(
            cli_value=None,
            config_value=True,
            entrypoint_default=False,
        )
        is True
    )
    assert (
        _resolve_workspace_strict(
            cli_value=None,
            config_value=None,
            entrypoint_default=True,
        )
        is True
    )


@pytest.mark.asyncio
async def test_standalone_repl_wires_memory_services_into_turnrunner(monkeypatch) -> None:
    services = _FakeServices()
    captured: dict[str, object] = {}
    inputs = iter(["/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        async def run(self, message: str, session_key: str, **kwargs):
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return services

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/test",
        session_id="standalone:test",
        timeout=7.25,
    )

    assert captured["memory_sync_managers"] is services.memory_sync_managers
    assert captured["memory_retrievers"] is services.memory_retrievers
    assert captured["turn_capture_services"] is services.turn_capture_services
    assert captured["session_flush_service"] is services.flush_service
    assert captured["model_catalog"] is services.model_catalog


@pytest.mark.asyncio
async def test_standalone_turnrunner_stream_uses_heartbeat_wrapper(monkeypatch) -> None:
    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            await asyncio.sleep(0.03)
            yield TextDeltaEvent(text="ok")
            yield DoneEvent()

    _RecordingRenderer.instances.clear()
    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr(chat_cmd, "StreamingRenderer", _RecordingRenderer)
    svc = SimpleNamespace(
        config=SimpleNamespace(
            agent_stream_heartbeat_interval_seconds=0.01,
            agent_stream_idle_timeout_seconds=1.0,
        ),
        session_manager=_FakeSessionManager(),
    )
    tool_ctx = ToolContext(caller_kind=CallerKind.CLI, channel_kind="cli", channel_id="cli:chat")

    result = await chat_cmd._stream_response_turnrunner(
        FakeTurnRunner(),
        "agent:main:standalone:test",
        tool_ctx,
        "hello",
        svc=svc,
    )

    renderer = _RecordingRenderer.instances[-1]
    assert result.text == "ok"
    assert renderer.pulses >= 1
    assert renderer.finalized is True


@pytest.mark.asyncio
async def test_standalone_turnrunner_stream_collects_artifacts(monkeypatch) -> None:
    artifact = {
        "id": "art-chat",
        "kind": "artifact_ref",
        "name": "report.txt",
        "mime": "text/plain",
        "size": 4,
        "sha256": "e" * 64,
        "session_id": "session-1",
        "session_key": "agent:main:standalone:test",
        "source": "publish_artifact",
        "created_at": "2026-05-06T12:00:00Z",
        "download_url": "/api/v1/artifacts/art-chat?sessionKey=agent%3Amain%3Astandalone%3Atest",
        "store": "artifacts",
    }

    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            yield ArtifactEvent(**artifact)
            yield TextDeltaEvent(text="ok")
            yield DoneEvent()

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr(chat_cmd, "StreamingRenderer", _RecordingRenderer)
    svc = SimpleNamespace(
        config=SimpleNamespace(
            agent_stream_heartbeat_interval_seconds=0.0,
            agent_stream_idle_timeout_seconds=1.0,
        ),
        session_manager=_FakeSessionManager(),
    )
    tool_ctx = ToolContext(caller_kind=CallerKind.CLI, channel_kind="cli", channel_id="cli:chat")

    result = await chat_cmd._stream_response_turnrunner(
        FakeTurnRunner(),
        "agent:main:standalone:test",
        tool_ctx,
        "hello",
        svc=svc,
    )

    assert result.text == "ok"
    assert result.artifacts[0]["download_url"] == "/api/v1/artifacts/art-chat"
    assert "session_key" not in result.artifacts[0]
    assert "sessionKey" not in json.dumps(result.artifacts[0])


@pytest.mark.asyncio
async def test_standalone_repl_uses_exact_slash_tokens(monkeypatch) -> None:
    services = _FakeServices()
    inputs = iter(["/newer", "/models", "/quit"])
    run_calls: list[str] = []

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            run_calls.append(message)
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return services

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/test",
        session_id="standalone:test",
        timeout=7.25,
    )

    assert services.session_manager.get_or_create_calls == [
        {"session_key": "standalone:test", "agent_id": "main"}
    ]
    assert run_calls == []


def test_standalone_slash_routes_preserve_current_command_surface() -> None:
    from opensquilla.cli.chat_standalone_slash_routes import (
        STANDALONE_SLASH_ROUTE_NAMES,
        match_standalone_slash_route,
    )

    expected_names = frozenset(
        {
            "help",
            "new",
            "status",
            "models",
            "model",
            "cost",
            "tool_compress",
            "clear",
            "compact",
            "save",
            "image",
            "path",
        }
    )
    assert STANDALONE_SLASH_ROUTE_NAMES == expected_names

    cases = [
        ("/help", "help", ["/help"]),
        ("/new project", "new", ["/new", "project"]),
        ("/status", "status", ["/status"]),
        ("/session", "status", ["/session"]),
        ("/models", "models", ["/models"]),
        ("/model openai/gpt-test", "model", ["/model", "openai/gpt-test"]),
        ("/cost", "cost", ["/cost"]),
        ("/tool-compress status", "tool_compress", ["/tool-compress", "status"]),
        ("/clear", "clear", ["/clear"]),
        ("/reset", "clear", ["/reset"]),
        ("/compact", "compact", ["/compact"]),
        ("/save out.md", "save", ["/save", "out.md"]),
        ("/image cat.png describe", "image", ["/image", "cat.png describe"]),
        ("/path repo/file.py summarize", "path", ["/path", "repo/file.py summarize"]),
    ]
    for command, route_name, parts in cases:
        match = match_standalone_slash_route(command)
        assert match is not None
        assert match.name == route_name
        assert match.parts == parts

    for unsupported in ["/newer", "/models extra", "/file doc.pdf", "/usage", "/sessions"]:
        assert match_standalone_slash_route(unsupported) is None


@pytest.mark.asyncio
async def test_standalone_slash_compact_passes_provider_config(monkeypatch) -> None:
    services = _FakeServices()
    services.provider_selector = _FakeProviderSelector()
    services.config = SimpleNamespace(
        context_budget_tokens=1234,
        compaction=SimpleNamespace(enabled=True, model=None, timeout_seconds=12.5),
    )
    inputs = iter(["/compact", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return services

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/test",
        session_id="standalone:test",
        timeout=7.25,
    )

    assert len(services.session_manager.compact_calls) == 1
    session_key, context_window, config = services.session_manager.compact_calls[0]
    assert session_key == "standalone:test"
    assert context_window == 1234
    assert isinstance(config, CompactionConfig)
    assert config.api_key == "cli-provider-key"
    assert config.model == "openrouter/test"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.timeout_seconds == 12.5


@pytest.mark.asyncio
async def test_standalone_reset_refuses_non_empty_transcript_without_flush_service(
    monkeypatch,
) -> None:
    services = _FakeServices()
    services.flush_service = None
    session_key = "standalone:test"
    services.session_manager.transcripts[session_key] = [
        SimpleNamespace(role="user", content="persisted")
    ]
    inputs = iter(["/reset", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return services

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(model="openrouter/test", session_id=session_key)

    assert services.session_manager.truncate_calls == []
    assert await services.session_manager.get_transcript(session_key)


@pytest.mark.asyncio
async def test_standalone_compact_refuses_non_empty_transcript_without_flush_service(
    monkeypatch,
) -> None:
    services = _FakeServices()
    services.flush_service = None
    session_key = "standalone:test"
    services.session_manager.transcripts[session_key] = [
        SimpleNamespace(role="user", content="persisted")
    ]
    services.provider_selector = _FakeProviderSelector()
    services.config = SimpleNamespace(
        context_budget_tokens=1234,
        compaction=SimpleNamespace(enabled=True, model=None, timeout_seconds=12.5),
    )
    inputs = iter(["/compact", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return services

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(model="openrouter/test", session_id=session_key)

    assert services.session_manager.compact_calls == []
    assert await services.session_manager.get_transcript(session_key)


class _FakeFlushService:
    def __init__(self, receipt: object | None = None, error: Exception | None = None) -> None:
        self.receipt = receipt or SimpleNamespace(mode="llm", error=None)
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def execute(self, transcript: object, session_key: str, **kwargs) -> object:
        self.calls.append(
            {"transcript": transcript, "session_key": session_key, "kwargs": kwargs}
        )
        if self.error is not None:
            raise self.error
        return self.receipt


@pytest.mark.asyncio
async def test_standalone_compact_flushes_before_compacting(monkeypatch) -> None:
    services = _FakeServices()
    session_key = "standalone:test"
    services.session_manager.transcripts[session_key] = [
        SimpleNamespace(role="user", content="persisted")
    ]
    services.flush_service = _FakeFlushService()
    services.provider_selector = _FakeProviderSelector()
    services.config = SimpleNamespace(
        context_budget_tokens=1234,
        compaction=SimpleNamespace(enabled=True, model=None, timeout_seconds=12.5),
    )
    inputs = iter(["/compact", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return services

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(model="openrouter/test", session_id=session_key)

    assert len(services.flush_service.calls) == 1
    assert services.flush_service.calls[0]["session_key"] == session_key
    assert services.flush_service.calls[0]["kwargs"]["message_window"] == 0
    assert services.flush_service.calls[0]["kwargs"]["segment_mode"] == "auto"
    assert len(services.session_manager.compact_calls) == 1


@pytest.mark.asyncio
async def test_standalone_compact_aborts_when_flush_fails(monkeypatch) -> None:
    services = _FakeServices()
    session_key = "standalone:test"
    services.session_manager.transcripts[session_key] = [
        SimpleNamespace(role="user", content="persisted")
    ]
    services.flush_service = _FakeFlushService(
        receipt=SimpleNamespace(mode="error", error="provider down")
    )
    services.provider_selector = _FakeProviderSelector()
    services.config = SimpleNamespace(
        context_budget_tokens=1234,
        compaction=SimpleNamespace(enabled=True, model=None, timeout_seconds=12.5),
    )
    inputs = iter(["/compact", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return services

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(model="openrouter/test", session_id=session_key)

    assert len(services.flush_service.calls) == 1
    assert services.session_manager.compact_calls == []
    assert await services.session_manager.get_transcript(session_key)


@pytest.mark.asyncio
async def test_standalone_slash_compact_keeps_legacy_compact_manager_compatible(
    monkeypatch,
) -> None:
    services = _FakeServices()
    services.session_manager = _LegacyCompactSessionManager()
    services.provider_selector = _FakeProviderSelector()
    services.config = SimpleNamespace(
        context_budget_tokens=1234,
        compaction=SimpleNamespace(enabled=True, model=None, timeout_seconds=12.5),
    )
    inputs = iter(["/compact", "/quit"])

    class FakeTurnRunner:
        def __init__(self, **kwargs) -> None:
            return None

        async def run(self, message: str, session_key: str, **kwargs):
            yield DoneEvent()

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    async def fake_build_services() -> _FakeServices:
        return services

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.build_services", fake_build_services)
    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._standalone_repl(
        model="openrouter/test",
        session_id="standalone:test",
        timeout=7.25,
    )

    assert services.session_manager.compact_calls == [("standalone:test", 1234, None)]


# ---------------------------------------------------------------------------
# Gateway-mode flag forwarding
# ---------------------------------------------------------------------------


class _FakeGatewayClient:
    """Fake GatewayClient that records create/send calls and feeds the REPL exit.

    Patched in place of the real `GatewayClient` class so `_stream_response_gateway`'s
    ``isinstance(client, GatewayClient)`` assertion passes. Each instance registers
    itself in a class-level ``instances`` list so tests can grab the one created
    by the function-under-test.
    """

    instances: list[_FakeGatewayClient]

    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.send_calls: list[dict[str, object]] = []
        self.resolve_calls: list[str] = []
        self.delete_calls: list[list[str]] = []
        self.history_calls: list[dict[str, object]] = []
        self.abort_calls: list[str] = []
        self.reset_calls: list[str] = []
        self.compact_calls: list[dict[str, object]] = []
        self.patch_session_calls: list[dict[str, object]] = []
        self.usage_status_calls = 0
        self.usage_status_payload: dict[str, object] = {
            "totalTokens": 12345,
            "totalCostUsd": 0.0456789,
        }
        self.config_get_calls: list[str | None] = []
        self.config_patch_safe_calls: list[dict[str, object]] = []
        self.config_values: dict[str, object] = {
            "agent_token_saving.tool_result_compression_enabled": True,
            "agent_token_saving.tool_result_compression_mode": None,
            "agent_token_saving.tool_result_compression_summary_model": "cheap/model",
        }
        self.approvals_snapshot_calls = 0
        self.approvals_snapshot_payload: dict[str, object] = {
            "mode": "prompt",
            "intent_cache_entries": [],
        }
        self.approval_mode_calls: list[str] = []
        self.forget_approvals_calls: list[str | None] = []
        self.list_models_calls = 0
        self.list_sessions_calls: list[int] = []
        self.delete_result: dict[str, object] = {"deleted": [], "errors": []}
        self.resolved_payload: dict[str, object] = {
            "session_key": "agent:main:resolved",
            "model": "openai/test",
        }
        self.connected = False
        self.closed = False
        type(self).instances.append(self)

    async def connect(self) -> None:
        self.connected = True

    async def create_session(
        self,
        agent_id: str = "main",
        model: str | None = None,
        display_name: str | None = None,
    ) -> str:
        self.create_calls.append(
            {"agent_id": agent_id, "model": model, "display_name": display_name}
        )
        return "agent:main:fake12345"

    async def resolve_session(self, key: str) -> dict[str, object]:
        self.resolve_calls.append(key)
        return self.resolved_payload

    async def delete_sessions(self, keys: list[str]) -> dict[str, object]:
        self.delete_calls.append(keys)
        return self.delete_result

    async def session_history(self, session_key: str, limit: int = 1000) -> dict[str, object]:
        self.history_calls.append({"session_key": session_key, "limit": limit})
        return {
            "messages": [
                {"role": "user", "text": "persisted hello"},
                {"role": "assistant", "text": "persisted reply"},
            ]
        }

    async def list_models(self) -> list[dict[str, object]]:
        self.list_models_calls += 1
        return [{"id": "openai/test", "provider": "openai"}]

    async def list_sessions(self, limit: int = 50) -> dict[str, object]:
        self.list_sessions_calls.append(limit)
        return {
            "sessions": [
                {
                    "session_key": "agent:main:abc123",
                    "status": "running",
                    "model": "openai/test",
                    "entry_count": 2,
                }
            ]
        }

    async def abort_session(self, session_key: str) -> dict[str, object]:
        self.abort_calls.append(session_key)
        return {"aborted": True, "key": session_key}

    async def reset_session(self, session_key: str) -> dict[str, object]:
        self.reset_calls.append(session_key)
        return {"reset": True, "key": session_key}

    async def compact_session(self, session_key: str) -> dict[str, object]:
        self.compact_calls.append({"session_key": session_key})
        return {
            "key": session_key,
            "compacted": True,
            "mode": "summary",
            "summary_len": 37,
        }

    async def patch_session(self, key: str, **fields: object) -> dict[str, object]:
        self.patch_session_calls.append({"key": key, "fields": dict(fields)})
        return {"patched": dict(fields)}

    async def usage_status(self) -> dict[str, object]:
        self.usage_status_calls += 1
        return dict(self.usage_status_payload)

    async def get_config(self, path: str | None = None) -> object:
        self.config_get_calls.append(path)
        if path is None:
            return dict(self.config_values)
        return self.config_values.get(path)

    async def patch_config_safe(self, patches: dict[str, object]) -> dict[str, object]:
        self.config_patch_safe_calls.append(dict(patches))
        self.config_values.update(patches)
        return {"patched": list(patches)}

    async def approvals_snapshot(self) -> dict[str, object]:
        self.approvals_snapshot_calls += 1
        return dict(self.approvals_snapshot_payload)

    async def set_approval_mode(self, mode: str) -> dict[str, object]:
        self.approval_mode_calls.append(mode)
        return {"mode": mode}

    async def forget_approvals(self, target: str | None = None) -> dict[str, object]:
        self.forget_approvals_calls.append(target)
        return {"target": target}

    async def send_message(self, session_key, message, attachments=None, elevated=None):
        self.send_calls.append(
            {
                "session_key": session_key,
                "message": message,
                "attachments": attachments,
                "elevated": elevated,
            }
        )
        # Drain immediately — REPL loop sees no events and proceeds to next prompt.
        if False:
            yield {}

    async def close(self) -> None:
        self.closed = True


_FakeGatewayClient.instances = []


@pytest.mark.asyncio
async def test_gateway_chat_forwards_model_to_create_session(monkeypatch) -> None:
    """`opensquilla chat --model X` (gateway mode) must reach create_session(model='X')."""
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    inputs = iter(["/quit"])

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._gateway_chat(model="anthropic/claude-sonnet-4", session_id=None)

    assert len(_FakeGatewayClient.instances) == 1
    fake = _FakeGatewayClient.instances[-1]
    assert fake.connected is True
    assert fake.closed is True
    assert fake.create_calls == [
        {
            "agent_id": "main",
            "model": "anthropic/claude-sonnet-4",
            "display_name": None,
        }
    ]
    assert fake.send_calls == []  # /quit on first prompt — no message sent


@pytest.mark.asyncio
async def test_gateway_chat_session_id_skips_create_session(monkeypatch) -> None:
    """`opensquilla chat --session abc` (gateway mode) must reuse the key without create."""
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    inputs = iter(["hi", "/quit"])

    async def fake_prompt_user(prefix: str = "[you] ", **kwargs):
        return next(inputs)

    monkeypatch.setattr(chat_cmd, "prompt_user", fake_prompt_user)

    await chat_cmd._gateway_chat(model=None, session_id="agent:main:resumed-key")

    fake = _FakeGatewayClient.instances[-1]
    assert fake.create_calls == []  # MUST NOT create
    assert len(fake.send_calls) == 1
    assert fake.send_calls[0]["session_key"] == "agent:main:resumed-key"
    assert fake.send_calls[0]["message"] == "hi"


@pytest.mark.asyncio
async def test_gateway_slash_new_passes_title_as_display_name(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:old", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command(
        "/new Research Notes", state, fake, {"mode": None}
    )

    assert handled is True
    assert fake.create_calls == [
        {
            "agent_id": "main",
            "model": "openai/test",
            "display_name": "Research Notes",
        }
    ]
    assert state.session_key == "agent:main:fake12345"


@pytest.mark.asyncio
async def test_gateway_path_command_sends_prompt_without_attachments_or_upload(
    monkeypatch,
    tmp_path,
) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    fake.is_local_gateway = True

    async def fail_upload_file(*args, **kwargs):
        raise AssertionError("upload_file must not be called for /path")

    fake.upload_file = fail_upload_file
    target = tmp_path / "large.log"
    target.write_text("hello\n", encoding="utf-8")
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command(
        f"/path {target} summarize", state, fake, {"mode": None}
    )

    assert handled is True
    assert len(fake.send_calls) == 1
    assert fake.send_calls[0]["attachments"] == []
    assert "summarize" in fake.send_calls[0]["message"]
    assert str(target.resolve(strict=False)) in fake.send_calls[0]["message"]


@pytest.mark.asyncio
async def test_gateway_path_command_remote_rejects_before_send(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.cli import chat_gateway_path_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    fake.is_local_gateway = False
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()
    monkeypatch.setattr(
        chat_gateway_path_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )
    nonexistent = tmp_path / "does-not-exist.log"

    handled = await chat_cmd._handle_gateway_slash_command(
        f"/path {nonexistent} inspect", state, fake, {"mode": None}
    )

    assert handled is True
    assert fake.send_calls == []
    assert "Use /file to upload from this CLI machine" in buffer.getvalue()
    assert "File not found" not in buffer.getvalue()


@pytest.mark.asyncio
async def test_gateway_file_command_uploads_and_sends_attachment(
    monkeypatch,
    tmp_path,
) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    uploads: list[dict[str, object]] = []

    async def upload_file(path: Path, mime: str, name: str) -> str:
        uploads.append({"path": path, "mime": mime, "name": name})
        return "u-large-pdf"

    fake.upload_file = upload_file  # type: ignore[attr-defined]
    target = tmp_path / "large.pdf"
    target.write_bytes(b"%PDF-1.4\n" + b"a" * (3 * 1024 * 1024))
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command(
        f"/file {target} summarize", state, fake, {"mode": "always"}
    )

    assert handled is True
    assert uploads == [{"path": target, "mime": "application/pdf", "name": "large.pdf"}]
    assert len(fake.send_calls) == 1
    assert fake.send_calls[0]["message"] == "summarize"
    assert fake.send_calls[0]["attachments"] == [
        {
            "type": "application/pdf",
            "file_uuid": "u-large-pdf",
            "name": "large.pdf",
            "mime": "application/pdf",
        }
    ]
    assert fake.send_calls[0]["elevated"] == "always"


@pytest.mark.asyncio
async def test_gateway_path_workflow_streams_prompt_without_upload_and_updates_state() -> None:
    from opensquilla.cli import chat_gateway_path_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    client = object()
    elevated_state = {"mode": "always"}
    calls: list[dict[str, object]] = []

    def path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, object]]]:
        assert command == "/path /tmp/large.log inspect"
        return "inspect path", []

    def gateway_client_is_local(gateway_client: object) -> bool:
        assert gateway_client is client
        return True

    async def stream_response(
        gateway_client: object,
        session_key: str,
        prompt: str,
        elevated: dict[str, str | None],
        **kwargs: object,
    ) -> TurnResult:
        calls.append(
            {
                "client": gateway_client,
                "session_key": session_key,
                "prompt": prompt,
                "elevated": elevated,
                "kwargs": kwargs,
            }
        )
        return TurnResult(
            text="path gateway reply",
            usage=UsageSummary(input_tokens=8, output_tokens=12, cost_usd=0.025),
        )

    handled = await chat_gateway_path_workflows.handle_gateway_path_command(
        "/path /tmp/large.log inspect",
        ["/path", "/tmp/large.log inspect"],
        state,
        client=client,
        elevated_state=elevated_state,
        stream_response=stream_response,
        path_prompt_and_attachments=path_prompt_and_attachments,
        gateway_client_is_local=gateway_client_is_local,
        remote_gateway_message="remote /path blocked",
    )

    assert handled is True
    assert calls == [
        {
            "client": client,
            "session_key": "agent:main:abc123",
            "prompt": "inspect path",
            "elevated": elevated_state,
            "kwargs": {"attachments": []},
        }
    ]
    transcript = state.transcript.to_markdown()
    assert "inspect path" in transcript
    assert "path gateway reply" in transcript
    assert state.usage.render() == "20 tok (8 in / 12 out) · cache 0 · $0.025000"


@pytest.mark.asyncio
async def test_gateway_path_workflow_prints_usage_without_path(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_path_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response must not run without a path")

    def path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, object]]]:
        raise AssertionError("path_prompt_and_attachments must not run without a path")

    def gateway_client_is_local(gateway_client: object) -> bool:
        raise AssertionError("gateway_client_is_local must not run without a path")

    monkeypatch.setattr(
        chat_gateway_path_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_path_workflows.handle_gateway_path_command(
        "/path",
        ["/path"],
        state,
        client=object(),
        elevated_state={"mode": None},
        stream_response=stream_response,
        path_prompt_and_attachments=path_prompt_and_attachments,
        gateway_client_is_local=gateway_client_is_local,
        remote_gateway_message="remote /path blocked",
    )

    assert handled is True
    assert "Usage: /path <path> [prompt]" in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_gateway_path_workflow_remote_rejects_before_prompt(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_path_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response must not run for remote /path")

    def path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, object]]]:
        raise AssertionError("path_prompt_and_attachments must not run for remote /path")

    def gateway_client_is_local(gateway_client: object) -> bool:
        return False

    monkeypatch.setattr(
        chat_gateway_path_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_path_workflows.handle_gateway_path_command(
        "/path missing.txt inspect",
        ["/path", "missing.txt inspect"],
        state,
        client=object(),
        elevated_state={"mode": None},
        stream_response=stream_response,
        path_prompt_and_attachments=path_prompt_and_attachments,
        gateway_client_is_local=gateway_client_is_local,
        remote_gateway_message="remote /path blocked",
    )

    assert handled is True
    assert "remote /path blocked" in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_gateway_path_workflow_renders_prompt_errors(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_path_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()

    def path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, object]]]:
        assert command == "/path missing.txt"
        raise ValueError("File not found: missing.txt")

    def gateway_client_is_local(gateway_client: object) -> bool:
        return True

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response must not run after a prompt error")

    monkeypatch.setattr(
        chat_gateway_path_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_path_workflows.handle_gateway_path_command(
        "/path missing.txt",
        ["/path", "missing.txt"],
        state,
        client=object(),
        elevated_state={"mode": None},
        stream_response=stream_response,
        path_prompt_and_attachments=path_prompt_and_attachments,
        gateway_client_is_local=gateway_client_is_local,
        remote_gateway_message="remote /path blocked",
    )

    assert handled is True
    assert "File not found: missing.txt" in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_gateway_image_workflow_streams_with_attachments_and_updates_state() -> None:
    from opensquilla.cli import chat_gateway_image_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    client = object()
    elevated_state = {"mode": "always"}
    attachments = [{"type": "image/png", "data": "ZmFrZQ==", "name": "chart.png"}]
    calls: list[dict[str, object]] = []

    def prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
        assert command == "/image /tmp/chart.png describe chart"
        return "describe chart", attachments

    async def stream_response(
        gateway_client: object,
        session_key: str,
        prompt: str,
        elevated: dict[str, str | None],
        **kwargs: object,
    ) -> TurnResult:
        calls.append(
            {
                "client": gateway_client,
                "session_key": session_key,
                "prompt": prompt,
                "elevated": elevated,
                "kwargs": kwargs,
            }
        )
        return TurnResult(
            text="image gateway reply",
            usage=UsageSummary(input_tokens=9, output_tokens=13, cost_usd=0.034),
        )

    handled = await chat_gateway_image_workflows.handle_gateway_image_command(
        "/image /tmp/chart.png describe chart",
        ["/image", "/tmp/chart.png describe chart"],
        state,
        client=client,
        elevated_state=elevated_state,
        stream_response=stream_response,
        image_prompt_and_attachments=prompt_and_attachments,
    )

    assert handled is True
    assert calls == [
        {
            "client": client,
            "session_key": "agent:main:abc123",
            "prompt": "describe chart",
            "elevated": elevated_state,
            "kwargs": {"attachments": attachments},
        }
    ]
    transcript = state.transcript.to_markdown()
    assert "describe chart" in transcript
    assert "image gateway reply" in transcript
    assert state.usage.render() == "22 tok (9 in / 13 out) · cache 0 · $0.034000"


@pytest.mark.asyncio
async def test_gateway_image_workflow_prints_usage_without_path(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_image_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response must not run without a path")

    def prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
        raise AssertionError("image_prompt_and_attachments must not run without a path")

    monkeypatch.setattr(
        chat_gateway_image_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_image_workflows.handle_gateway_image_command(
        "/image",
        ["/image"],
        state,
        client=object(),
        elevated_state={"mode": None},
        stream_response=stream_response,
        image_prompt_and_attachments=prompt_and_attachments,
    )

    assert handled is True
    assert "Usage: /image <path> [prompt]" in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_gateway_image_workflow_renders_prompt_errors(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_image_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()

    def prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
        assert command == "/image missing.bmp"
        raise ValueError("Unsupported format: bmp. Use png/jpg/gif/webp")

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response must not run after a prompt error")

    monkeypatch.setattr(
        chat_gateway_image_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_image_workflows.handle_gateway_image_command(
        "/image missing.bmp",
        ["/image", "missing.bmp"],
        state,
        client=object(),
        elevated_state={"mode": None},
        stream_response=stream_response,
        image_prompt_and_attachments=prompt_and_attachments,
    )

    assert handled is True
    assert "Unsupported format: bmp" in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_gateway_file_workflow_streams_with_attachments_and_updates_state() -> None:
    from opensquilla.cli import chat_gateway_file_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    client = object()
    elevated_state = {"mode": "always"}
    attachments = [
        {
            "type": "application/pdf",
            "file_uuid": "u-large-pdf",
            "name": "large.pdf",
            "mime": "application/pdf",
        }
    ]
    calls: list[dict[str, object]] = []

    async def file_prompt_and_attachments(
        command: str,
        *,
        upload_callable: object | None = None,
    ) -> tuple[str, list[dict[str, object]]]:
        assert command == "/file /tmp/large.pdf summarize"
        assert upload_callable is not None
        return "summarize", attachments

    async def stream_response(
        gateway_client: object,
        session_key: str,
        prompt: str,
        elevated: dict[str, str | None],
        **kwargs: object,
    ) -> TurnResult:
        calls.append(
            {
                "client": gateway_client,
                "session_key": session_key,
                "prompt": prompt,
                "elevated": elevated,
                "kwargs": kwargs,
            }
        )
        return TurnResult(
            text="file gateway reply",
            usage=UsageSummary(input_tokens=5, output_tokens=9, cost_usd=0.017),
        )

    handled = await chat_gateway_file_workflows.handle_gateway_file_command(
        "/file /tmp/large.pdf summarize",
        ["/file", "/tmp/large.pdf summarize"],
        state,
        client=client,
        elevated_state=elevated_state,
        stream_response=stream_response,
        async_file_prompt_and_attachments=file_prompt_and_attachments,
    )

    assert handled is True
    assert calls == [
        {
            "client": client,
            "session_key": "agent:main:abc123",
            "prompt": "summarize",
            "elevated": elevated_state,
            "kwargs": {"attachments": attachments},
        }
    ]
    transcript = state.transcript.to_markdown()
    assert "summarize" in transcript
    assert "file gateway reply" in transcript
    assert state.usage.render() == "14 tok (5 in / 9 out) · cache 0 · $0.017000"


@pytest.mark.asyncio
async def test_gateway_file_workflow_prints_usage_without_path(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_file_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response must not run without a path")

    async def file_prompt_and_attachments(
        command: str,
        *,
        upload_callable: object | None = None,
    ) -> tuple[str, list[dict[str, object]]]:
        raise AssertionError("async_file_prompt_and_attachments must not run without a path")

    monkeypatch.setattr(
        chat_gateway_file_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_file_workflows.handle_gateway_file_command(
        "/file",
        ["/file"],
        state,
        client=object(),
        elevated_state={"mode": None},
        stream_response=stream_response,
        async_file_prompt_and_attachments=file_prompt_and_attachments,
    )

    assert handled is True
    assert "Usage: /file <path> [prompt]" in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_gateway_file_workflow_forwards_upload_bridge() -> None:
    from opensquilla.cli import chat_gateway_file_workflows

    class Client:
        def __init__(self) -> None:
            self.uploads: list[dict[str, object]] = []

        async def upload_file(self, path: Path, mime: str, name: str) -> str:
            self.uploads.append({"path": path, "mime": mime, "name": name})
            return "u-bridge"

    client = Client()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    upload_path = Path("/tmp/big.pdf")

    async def file_prompt_and_attachments(
        command: str,
        *,
        upload_callable: object | None = None,
    ) -> tuple[str, list[dict[str, object]]]:
        assert command == "/file /tmp/big.pdf"
        assert callable(upload_callable)
        file_uuid = await upload_callable(upload_path, "application/pdf", "big.pdf")
        return "Read this file", [{"type": "application/pdf", "file_uuid": file_uuid}]

    async def stream_response(
        gateway_client: object,
        session_key: str,
        prompt: str,
        elevated: dict[str, str | None],
        **kwargs: object,
    ) -> TurnResult:
        return TurnResult(text="ok")

    handled = await chat_gateway_file_workflows.handle_gateway_file_command(
        "/file /tmp/big.pdf",
        ["/file", "/tmp/big.pdf"],
        state,
        client=client,
        elevated_state={"mode": None},
        stream_response=stream_response,
        async_file_prompt_and_attachments=file_prompt_and_attachments,
    )

    assert handled is True
    assert client.uploads == [
        {"path": upload_path, "mime": "application/pdf", "name": "big.pdf"}
    ]


@pytest.mark.asyncio
async def test_gateway_file_workflow_renders_prompt_errors(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_file_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()

    async def file_prompt_and_attachments(
        command: str,
        *,
        upload_callable: object | None = None,
    ) -> tuple[str, list[dict[str, object]]]:
        assert command == "/file too-large.pdf"
        raise ValueError("PDF limit exceeded: too-large.pdf")

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response must not run after a prompt error")

    monkeypatch.setattr(
        chat_gateway_file_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_file_workflows.handle_gateway_file_command(
        "/file too-large.pdf",
        ["/file", "too-large.pdf"],
        state,
        client=object(),
        elevated_state={"mode": None},
        stream_response=stream_response,
        async_file_prompt_and_attachments=file_prompt_and_attachments,
    )

    assert handled is True
    assert "PDF limit exceeded: too-large.pdf" in buffer.getvalue()
    assert state.transcript.to_markdown() == ""


@pytest.mark.asyncio
async def test_gateway_permissions_workflow_delegates_and_syncs_chat_state() -> None:
    from opensquilla.cli import chat_gateway_permissions_workflows

    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    elevated_state = {"mode": None}
    client = object()
    calls: list[dict[str, object]] = []

    async def permissions_command(
        command: str,
        mode_state: dict[str, str | None],
        *,
        client: object | None = None,
        forget_server_approvals: object | None = None,
    ) -> None:
        calls.append(
            {
                "command": command,
                "mode_state": mode_state,
                "client": client,
                "forget_server_approvals": forget_server_approvals,
            }
        )
        mode_state["mode"] = "bypass"

    async def forget_server_approvals(
        client: object | None,
        target: str | None = None,
    ) -> bool:
        raise AssertionError("delegated permissions_command owns approval clearing")

    handled = await chat_gateway_permissions_workflows.handle_gateway_permissions_command(
        "/permissions bypass",
        state,
        elevated_state,
        client=client,
        permissions_command=permissions_command,
        forget_server_approvals=forget_server_approvals,
    )

    assert handled is True
    assert state.elevated == "bypass"
    assert elevated_state["mode"] == "bypass"
    assert calls == [
        {
            "command": "/permissions bypass",
            "mode_state": elevated_state,
            "client": client,
            "forget_server_approvals": forget_server_approvals,
        }
    ]


@pytest.mark.asyncio
async def test_permissions_workflow_status_prints_current_without_revoking(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_permissions_workflows

    mode_state = {"mode": "full"}
    buffer = io.StringIO()

    async def forget_server_approvals(
        client: object | None,
        target: str | None = None,
    ) -> bool:
        raise AssertionError("status must not clear cached approvals")

    monkeypatch.setattr(
        chat_gateway_permissions_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    await chat_gateway_permissions_workflows.handle_permissions_command(
        "/permissions status",
        mode_state,
        client=object(),
        forget_server_approvals=forget_server_approvals,
    )

    assert mode_state == {"mode": "full"}
    assert "permissions:" in buffer.getvalue()
    assert "full" in buffer.getvalue()


@pytest.mark.asyncio
async def test_permissions_workflow_unknown_mode_prints_usage_without_mutating(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_permissions_workflows

    mode_state = {"mode": "on"}
    buffer = io.StringIO()

    async def forget_server_approvals(
        client: object | None,
        target: str | None = None,
    ) -> bool:
        raise AssertionError("unknown mode must not clear cached approvals")

    monkeypatch.setattr(
        chat_gateway_permissions_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    await chat_gateway_permissions_workflows.handle_permissions_command(
        "/permissions maybe",
        mode_state,
        client=object(),
        forget_server_approvals=forget_server_approvals,
    )

    output = buffer.getvalue()
    assert mode_state == {"mode": "on"}
    assert "Unknown permissions mode:" in output
    assert "Usage: /permissions on | off | bypass | full | status" in output


@pytest.mark.asyncio
async def test_permissions_workflow_on_sets_mode_and_revokes_cache(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_permissions_workflows

    mode_state = {"mode": None}
    client = object()
    forget_calls: list[tuple[object | None, str | None]] = []
    buffer = io.StringIO()

    async def forget_server_approvals(
        client_arg: object | None,
        target: str | None = None,
    ) -> bool:
        forget_calls.append((client_arg, target))
        return True

    monkeypatch.setattr(
        chat_gateway_permissions_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    await chat_gateway_permissions_workflows.handle_permissions_command(
        "/elevated on",
        mode_state,
        client=client,
        forget_server_approvals=forget_server_approvals,
    )

    assert mode_state == {"mode": "on"}
    assert forget_calls == [(client, None)]
    output = buffer.getvalue()
    assert "permissions: on" in output
    assert "Cached approvals revoked." in output


@pytest.mark.asyncio
async def test_permissions_workflow_off_resets_gateway_queue_and_revokes_cache(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_permissions_workflows

    class Client:
        def __init__(self) -> None:
            self.set_calls: list[str] = []

        async def set_approval_mode(self, mode: str) -> dict[str, object]:
            self.set_calls.append(mode)
            return {"mode": mode}

    mode_state = {"mode": "full"}
    client = Client()
    forget_calls: list[tuple[object | None, str | None]] = []
    buffer = io.StringIO()

    async def forget_server_approvals(
        client_arg: object | None,
        target: str | None = None,
    ) -> bool:
        forget_calls.append((client_arg, target))
        return True

    monkeypatch.setattr(
        chat_gateway_permissions_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    await chat_gateway_permissions_workflows.handle_permissions_command(
        "/permissions off",
        mode_state,
        client=client,
        forget_server_approvals=forget_server_approvals,
    )

    assert mode_state == {"mode": None}
    assert forget_calls == [(client, None)]
    assert client.set_calls == ["prompt"]
    output = buffer.getvalue()
    assert "permissions: off" in output
    assert "Queue mode reset to prompt." in output
    assert "Cached approvals" in output
    assert "revoked." in output


@pytest.mark.asyncio
async def test_gateway_permissions_command_updates_chat_state(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    elevated_state = {"mode": None}
    forget_calls: list[tuple[object | None, str | None]] = []

    async def forget_server_approvals(
        client: object | None,
        target: str | None = None,
    ) -> bool:
        forget_calls.append((client, target))
        return True

    monkeypatch.setattr(chat_cmd, "_forget_server_approvals", forget_server_approvals)

    handled = await chat_cmd._handle_gateway_slash_command(
        "/permissions bypass",
        state,
        fake,
        elevated_state,
    )

    assert handled is True
    assert elevated_state == {"mode": "bypass"}
    assert state.elevated == "bypass"
    assert forget_calls == [(fake, None)]


@pytest.mark.asyncio
async def test_gateway_forget_workflow_clears_all_and_prints_success(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_forget_workflows

    client = object()
    calls: list[tuple[object | None, str | None]] = []
    buffer = io.StringIO()

    async def forget_server_approvals(
        client_arg: object | None,
        target: str | None = None,
    ) -> bool:
        calls.append((client_arg, target))
        return True

    monkeypatch.setattr(
        chat_gateway_forget_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_forget_workflows.handle_gateway_forget_command(
        "/forget",
        client=client,
        forget_server_approvals=forget_server_approvals,
    )

    assert handled is True
    assert calls == [(client, None)]
    output = buffer.getvalue()
    assert "All cached approvals cleared." in output
    assert "Future destructive ops will prompt again." in output


@pytest.mark.asyncio
async def test_gateway_forget_workflow_clears_target_and_prints_success(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_forget_workflows

    client = object()
    calls: list[tuple[object | None, str | None]] = []
    buffer = io.StringIO()

    async def forget_server_approvals(
        client_arg: object | None,
        target: str | None = None,
    ) -> bool:
        calls.append((client_arg, target))
        return True

    monkeypatch.setattr(
        chat_gateway_forget_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_forget_workflows.handle_gateway_forget_command(
        "/forget /tmp/secrets.txt",
        client=client,
        forget_server_approvals=forget_server_approvals,
    )

    assert handled is True
    assert calls == [(client, "/tmp/secrets.txt")]
    output = buffer.getvalue()
    assert "Cached approval for" in output
    assert "/tmp/secrets.txt" in output
    assert "cleared (if one existed)." in output


@pytest.mark.asyncio
async def test_gateway_forget_workflow_suppresses_success_when_clear_fails(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_forget_workflows

    client = object()
    calls: list[tuple[object | None, str | None]] = []
    buffer = io.StringIO()

    async def forget_server_approvals(
        client_arg: object | None,
        target: str | None = None,
    ) -> bool:
        calls.append((client_arg, target))
        return False

    monkeypatch.setattr(
        chat_gateway_forget_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_forget_workflows.handle_gateway_forget_command(
        "/forget /tmp/secrets.txt",
        client=client,
        forget_server_approvals=forget_server_approvals,
    )

    assert handled is True
    assert calls == [(client, "/tmp/secrets.txt")]
    assert "Cached approval for" not in buffer.getvalue()
    assert "All cached approvals cleared." not in buffer.getvalue()


@pytest.mark.asyncio
async def test_gateway_forget_command_uses_forget_helper(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_forget_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    forget_calls: list[tuple[object | None, str | None]] = []

    async def forget_server_approvals(
        client: object | None,
        target: str | None = None,
    ) -> bool:
        forget_calls.append((client, target))
        return True

    monkeypatch.setattr(chat_cmd, "_forget_server_approvals", forget_server_approvals)
    monkeypatch.setattr(
        chat_gateway_forget_workflows,
        "console",
        Console(file=io.StringIO(), force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_cmd._handle_gateway_slash_command(
        "/forget /tmp/secrets.txt",
        state,
        fake,
        {"mode": None},
    )

    assert handled is True
    assert forget_calls == [(fake, "/tmp/secrets.txt")]


@pytest.mark.asyncio
async def test_gateway_forget_unknown_prefix_is_not_handled(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    forget_calls: list[tuple[object | None, str | None]] = []

    async def forget_server_approvals(
        client: object | None,
        target: str | None = None,
    ) -> bool:
        forget_calls.append((client, target))
        return True

    monkeypatch.setattr(chat_cmd, "_forget_server_approvals", forget_server_approvals)

    handled = await chat_cmd._handle_gateway_slash_command(
        "/forgetful",
        state,
        fake,
        {"mode": None},
    )

    assert handled is False
    assert forget_calls == []


@pytest.mark.asyncio
async def test_gateway_approvals_workflow_renders_snapshot_entries(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_approvals_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    client = _FakeGatewayClient()
    client.approvals_snapshot_payload = {
        "mode": "auto-approve",
        "intent_cache_entries": [
            {"scope": "session", "kind": "shell", "target": "rm /tmp/a"},
            {"scope": "workspace", "kind": "path", "target": "/tmp/b"},
        ],
    }
    buffer = io.StringIO()

    monkeypatch.setattr(
        chat_gateway_approvals_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_approvals_workflows.handle_gateway_approvals_command(
        "/approvals",
        client=client,
    )

    assert handled is True
    assert client.approvals_snapshot_calls == 1
    output = buffer.getvalue()
    assert "mode:" in output
    assert "auto-approve" in output
    assert "cached intents (2):" in output
    assert "session" in output
    assert "shell:rm /tmp/a" in output
    assert "workspace" in output
    assert "path:/tmp/b" in output


@pytest.mark.asyncio
async def test_gateway_approvals_workflow_reset_sets_prompt_and_clears_cache(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_approvals_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    client = _FakeGatewayClient()
    buffer = io.StringIO()

    monkeypatch.setattr(
        chat_gateway_approvals_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_approvals_workflows.handle_gateway_approvals_command(
        "/approvals reset",
        client=client,
    )

    assert handled is True
    assert client.approval_mode_calls == ["prompt"]
    assert client.forget_approvals_calls == [None]
    assert "Approval mode reset to prompt; server cache cleared." in buffer.getvalue()


@pytest.mark.asyncio
async def test_gateway_approvals_workflow_query_failure_prints_restart_hint(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_approvals_workflows

    class BrokenClient(_FakeGatewayClient):
        async def approvals_snapshot(self) -> dict[str, object]:
            raise RuntimeError("old gateway")

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", BrokenClient)
    client = BrokenClient()
    buffer = io.StringIO()

    monkeypatch.setattr(
        chat_gateway_approvals_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_approvals_workflows.handle_gateway_approvals_command(
        "/approvals",
        client=client,
    )

    assert handled is True
    output = buffer.getvalue()
    assert "Failed to query approvals:" in output
    assert "RuntimeError: old gateway" in output
    assert "Older gateway? Restart it." in output


@pytest.mark.asyncio
async def test_gateway_approvals_workflow_reset_failure_prints_restart_hint(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_approvals_workflows

    class BrokenClient(_FakeGatewayClient):
        async def set_approval_mode(self, mode: str) -> dict[str, object]:
            raise RuntimeError(f"cannot set {mode}")

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", BrokenClient)
    client = BrokenClient()
    buffer = io.StringIO()

    monkeypatch.setattr(
        chat_gateway_approvals_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_gateway_approvals_workflows.handle_gateway_approvals_command(
        "/approvals reset",
        client=client,
    )

    assert handled is True
    output = buffer.getvalue()
    assert "Failed to reset approvals:" in output
    assert "RuntimeError: cannot set prompt" in output
    assert "Restart the gateway if this is an older build." in output


@pytest.mark.asyncio
async def test_gateway_approvals_command_uses_workflow_boundary(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_approvals_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()

    monkeypatch.setattr(
        chat_gateway_approvals_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_cmd._handle_gateway_slash_command(
        "/approvals",
        state,
        fake,
        {"mode": None},
    )

    assert handled is True
    assert fake.approvals_snapshot_calls == 1
    assert "cached intents (0):" in buffer.getvalue()


@pytest.mark.asyncio
async def test_gateway_approvals_unknown_prefix_is_not_handled(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command(
        "/approvalsx",
        state,
        fake,
        {"mode": None},
    )

    assert handled is False
    assert fake.approvals_snapshot_calls == 0
    assert fake.approval_mode_calls == []
    assert fake.forget_approvals_calls == []


def test_gateway_status_workflow_renders_session_model_and_permissions(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_status_workflows

    state = ChatSessionState(
        session_key="agent:main:abc123",
        model="openai/test",
        elevated="bypass",
    )
    buffer = io.StringIO()

    monkeypatch.setattr(
        chat_gateway_status_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = chat_gateway_status_workflows.handle_gateway_status_command(state)

    assert handled is True
    output = buffer.getvalue()
    assert "session" in output
    assert "agent:main:abc123" in output
    assert "model" in output
    assert "openai/test" in output
    assert "permissions" in output
    assert "bypass" in output


def test_gateway_status_workflow_uses_defaults(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_status_workflows

    state = ChatSessionState(session_key="agent:main:abc123")
    buffer = io.StringIO()

    monkeypatch.setattr(
        chat_gateway_status_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = chat_gateway_status_workflows.handle_gateway_status_command(state)

    assert handled is True
    output = buffer.getvalue()
    assert "agent:main:abc123" in output
    assert "default" in output
    assert "normal" in output


@pytest.mark.asyncio
async def test_gateway_session_command_uses_status_workflow(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_status_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(
        session_key="agent:main:abc123",
        model="openai/test",
        elevated="full",
    )
    buffer = io.StringIO()

    monkeypatch.setattr(
        chat_gateway_status_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_cmd._handle_gateway_slash_command(
        "/session",
        state,
        fake,
        {"mode": "full"},
    )

    assert handled is True
    output = buffer.getvalue()
    assert "agent:main:abc123" in output
    assert "openai/test" in output
    assert "full" in output


@pytest.mark.asyncio
async def test_gateway_status_unknown_prefix_is_not_handled(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command(
        "/statusx",
        state,
        fake,
        {"mode": None},
    )

    assert handled is False


@pytest.mark.asyncio
async def test_gateway_chat_does_not_forward_workspace_fields() -> None:
    from opensquilla.cli.gateway_client import GatewayClient

    client = GatewayClient()
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {}

    client._call = fake_call  # type: ignore[method-assign]
    client._recv_queue.put_nowait({"event": "session.event.done", "payload": {}})

    events = [
        event
        async for event in client.send_message(
            "agent:main:abc123",
            "hello",
            attachments=[],
        )
    ]

    assert events[-1]["event"] == "session.event.done"
    method, params = calls[1]
    assert method == "sessions.send"
    source = params["_source"]
    assert "workspace_dir" not in source
    assert "workspace_strict" not in source


@pytest.mark.asyncio
async def test_gateway_client_follows_background_task_group_until_terminal() -> None:
    from opensquilla.cli.gateway_client import GatewayClient

    client = GatewayClient()
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {}

    client._call = fake_call  # type: ignore[method-assign]
    group_id = "subagent:agent:main:abc123:task-parent"
    for frame in (
        {"event": "session.event.task_group.waiting", "payload": {"group_id": group_id}},
        {"event": "session.event.done", "payload": {"reason": "parent_yielded"}},
        {
            "event": "session.event.task_group.synthesizing",
            "payload": {"group_id": group_id, "synthesis_task_id": "task-synth"},
        },
        {"event": "session.event.done", "payload": {"reason": "synthesis_done"}},
        {"event": "task.succeeded", "payload": {"task_id": "task-synth"}},
        {
            "event": "session.event.task_group.done",
            "payload": {"group_id": group_id, "delivery_status": "not_applicable"},
        },
    ):
        client._recv_queue.put_nowait(frame)

    events = [
        event
        async for event in client.send_message(
            "agent:main:abc123",
            "hello",
            attachments=[],
        )
    ]

    assert [event["event"] for event in events] == [
        "session.event.task_group.waiting",
        "session.event.done",
        "session.event.task_group.synthesizing",
        "session.event.done",
        "task.succeeded",
        "session.event.task_group.done",
    ]
    assert events[-1]["delivery_status"] == "not_applicable"
    assert calls[0][0] == "sessions.messages.subscribe"
    assert calls[1][0] == "sessions.send"


@pytest.mark.asyncio
async def test_gateway_client_does_not_wait_for_late_task_group_after_done() -> None:
    from opensquilla.cli.gateway_client import GatewayClient

    client = GatewayClient()

    async def fake_call(method: str, params: dict[str, object]) -> dict[str, object]:
        return {}

    client._call = fake_call  # type: ignore[method-assign]
    client._recv_queue.put_nowait({"event": "session.event.done", "payload": {}})
    client._recv_queue.put_nowait(
        {
            "event": "session.event.task_group.synthesizing",
            "payload": {"group_id": "late-group"},
        }
    )

    events = [
        event
        async for event in client.send_message(
            "agent:main:abc123",
            "hello",
            attachments=[],
        )
    ]

    assert [event["event"] for event in events] == ["session.event.done"]


@pytest.mark.asyncio
async def test_gateway_client_does_not_end_on_untracked_task_group_terminal() -> None:
    from opensquilla.cli.gateway_client import GatewayClient

    client = GatewayClient()

    async def fake_call(method: str, params: dict[str, object]) -> dict[str, object]:
        return {}

    client._call = fake_call  # type: ignore[method-assign]
    client._recv_queue.put_nowait(
        {
            "event": "session.event.task_group.done",
            "payload": {"group_id": "untracked-group", "delivery_status": "not_applicable"},
        }
    )
    client._recv_queue.put_nowait({"event": "session.event.done", "payload": {}})

    events = [
        event
        async for event in client.send_message(
            "agent:main:abc123",
            "hello",
            attachments=[],
        )
    ]

    assert [event["event"] for event in events] == [
        "session.event.task_group.done",
        "session.event.done",
    ]


@pytest.mark.asyncio
async def test_gateway_slash_clear_resets_session_state(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    state.transcript.add("user", "hello")

    handled = await chat_cmd._handle_gateway_slash_command("/clear", state, fake, {"mode": None})

    assert handled is True
    assert fake.reset_calls == ["agent:main:abc123"]
    assert state.transcript.turns == []


@pytest.mark.asyncio
async def test_gateway_slash_compact_calls_session_rpc(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command("/compact", state, fake, {"mode": None})

    assert handled is True
    assert fake.compact_calls == [{"session_key": "agent:main:abc123"}]


@pytest.mark.asyncio
async def test_gateway_slash_model_updates_session_model(monkeypatch) -> None:
    from opensquilla.cli import chat_model_usage_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/old")
    buffer = io.StringIO()
    monkeypatch.setattr(
        chat_model_usage_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_cmd._handle_gateway_slash_command(
        "/model anthropic/claude-sonnet-4", state, fake, {"mode": None}
    )

    assert handled is True
    assert fake.patch_session_calls == [
        {
            "key": "agent:main:abc123",
            "fields": {"model": "anthropic/claude-sonnet-4"},
        }
    ]
    assert state.model == "anthropic/claude-sonnet-4"
    assert "model:" in buffer.getvalue()
    assert "anthropic/claude-sonnet-4" in buffer.getvalue()


@pytest.mark.asyncio
async def test_gateway_slash_cost_and_usage_emit_usage_views(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_usage_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    state.usage.add(
        UsageSummary(input_tokens=12, output_tokens=34, cached_tokens=5, cost_usd=0.0123)
    )
    buffer = io.StringIO()
    monkeypatch.setattr(
        chat_gateway_usage_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled_cost = await chat_cmd._handle_gateway_slash_command(
        "/cost", state, fake, {"mode": None}
    )
    handled_usage = await chat_cmd._handle_gateway_slash_command(
        "/usage", state, fake, {"mode": None}
    )

    assert handled_cost is True
    assert handled_usage is True
    assert fake.usage_status_calls == 1
    output = buffer.getvalue()
    assert "46 tok (12 in / 34 out)" in output
    assert "$0.012300" in output
    assert "aggregate usage:" in output
    assert "12,345 tok" in output
    assert "$0.045679" in output


@pytest.mark.asyncio
async def test_gateway_usage_unknown_prefixes_are_not_handled(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled_cost = await chat_cmd._handle_gateway_slash_command(
        "/costs",
        state,
        fake,
        {"mode": None},
    )
    handled_usage = await chat_cmd._handle_gateway_slash_command(
        "/usagex",
        state,
        fake,
        {"mode": None},
    )

    assert handled_cost is False
    assert handled_usage is False
    assert fake.usage_status_calls == 0


def test_standalone_model_cost_workflow_updates_state_and_emits_usage(monkeypatch) -> None:
    from opensquilla.cli import chat_standalone_model_cost_workflows

    state = ChatSessionState(session_key="standalone:test", model="openrouter/old")
    state.usage.add(
        UsageSummary(input_tokens=12, output_tokens=34, cached_tokens=5, cost_usd=0.0123)
    )
    buffer = io.StringIO()
    monkeypatch.setattr(
        chat_standalone_model_cost_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    unchanged = chat_standalone_model_cost_workflows.handle_standalone_model_command(
        ["/model"], state
    )
    updated = chat_standalone_model_cost_workflows.handle_standalone_model_command(
        ["/model", "anthropic/claude-sonnet-4"], state
    )
    chat_standalone_model_cost_workflows.handle_standalone_cost_command(state)

    assert unchanged is None
    assert updated == "anthropic/claude-sonnet-4"
    assert state.model == "anthropic/claude-sonnet-4"
    output = buffer.getvalue()
    assert "model=openrouter/old" in output
    assert "model:" in output
    assert "anthropic/claude-sonnet-4" in output
    assert "46 tok (12 in / 34 out)" in output
    assert "$0.012300" in output


def test_standalone_status_workflow_emits_session_model_and_models_notice(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_standalone_status_workflows

    state = ChatSessionState(session_key="standalone:test", model=None)
    buffer = io.StringIO()
    monkeypatch.setattr(
        chat_standalone_status_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    chat_standalone_status_workflows.handle_standalone_status_command(state)
    chat_standalone_status_workflows.handle_standalone_models_command()

    output = buffer.getvalue()
    assert "session" in output
    assert "standalone:test" in output
    assert "model" in output
    assert "default" in output
    assert "/models requires gateway mode." in output


@pytest.mark.asyncio
async def test_standalone_new_workflow_creates_session_state_and_tool_context(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_standalone_session_workflows

    session_manager = _FakeSessionManager()
    built_keys: list[str] = []
    buffer = io.StringIO()

    def fake_uuid4() -> object:
        return SimpleNamespace(hex="cafebabe12345678")

    def build_tool_context(session_key: str) -> dict[str, str]:
        built_keys.append(session_key)
        return {"session_key": session_key}

    monkeypatch.setattr(chat_standalone_session_workflows, "uuid4", fake_uuid4)
    monkeypatch.setattr(
        chat_standalone_session_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    session_key, tool_context, state = (
        await chat_standalone_session_workflows.handle_standalone_new_command(
            ["/new", "Research Notes"],
            session_manager=session_manager,
            build_tool_context=build_tool_context,
            model="openrouter/test",
        )
    )

    assert session_key == "agent:main:standalone:cafebabe"
    assert built_keys == [session_key]
    assert tool_context == {"session_key": session_key}
    assert state == ChatSessionState(session_key=session_key, model="openrouter/test")
    assert session_manager.get_or_create_calls == [
        {"session_key": session_key, "agent_id": "main"}
    ]
    output = buffer.getvalue()
    assert "Started new session (Research Notes):" in output
    assert session_key in output


@pytest.mark.asyncio
async def test_standalone_clear_workflow_truncates_and_resets_state(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_standalone_session_workflows

    services = _FakeServices()
    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    state.transcript.add("user", "hello")
    state.usage.add(
        UsageSummary(input_tokens=12, output_tokens=34, cached_tokens=5, cost_usd=0.0123)
    )
    flush_calls: list[dict[str, object]] = []
    buffer = io.StringIO()

    async def flush_before_rewrite(svc: object, session_key: str, *, operation: str) -> bool:
        flush_calls.append({"svc": svc, "session_key": session_key, "operation": operation})
        return True

    monkeypatch.setattr(
        chat_standalone_session_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_standalone_session_workflows.handle_standalone_clear_command(
        state,
        services=services,
        flush_before_rewrite=flush_before_rewrite,
    )

    assert handled is True
    assert flush_calls == [
        {"svc": services, "session_key": "standalone:test", "operation": "Reset"}
    ]
    assert services.session_manager.truncate_calls == [("standalone:test", 0)]
    assert state.transcript.turns == []
    assert state.usage.render() == "0 tok (0 in / 0 out) · cache 0 · $0.000000"
    output = buffer.getvalue()
    assert "cleared" in output
    assert "standalone:test" in output


@pytest.mark.asyncio
async def test_standalone_clear_workflow_aborts_when_flush_guard_fails() -> None:
    from opensquilla.cli import chat_standalone_session_workflows

    services = _FakeServices()
    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    state.transcript.add("user", "hello")
    state.usage.add(
        UsageSummary(input_tokens=12, output_tokens=34, cached_tokens=5, cost_usd=0.0123)
    )

    async def flush_before_rewrite(svc: object, session_key: str, *, operation: str) -> bool:
        return False

    handled = await chat_standalone_session_workflows.handle_standalone_clear_command(
        state,
        services=services,
        flush_before_rewrite=flush_before_rewrite,
    )

    assert handled is False
    assert services.session_manager.truncate_calls == []
    assert len(state.transcript.turns) == 1
    assert state.usage.render() == "46 tok (12 in / 34 out) · cache 5 · $0.012300"


@pytest.mark.asyncio
async def test_standalone_compact_workflow_compacts_with_provider_config(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_standalone_session_workflows

    services = _FakeServices()
    services.provider_selector = _FakeProviderSelector()
    services.config = SimpleNamespace(
        context_budget_tokens=1234,
        compaction=SimpleNamespace(enabled=True, model=None, timeout_seconds=12.5),
    )
    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    flush_calls: list[dict[str, object]] = []
    buffer = io.StringIO()

    async def flush_before_rewrite(svc: object, session_key: str, *, operation: str) -> bool:
        flush_calls.append({"svc": svc, "session_key": session_key, "operation": operation})
        return True

    monkeypatch.setattr(
        chat_standalone_session_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_standalone_session_workflows.handle_standalone_compact_command(
        state,
        services=services,
        model="openrouter/test",
        flush_before_rewrite=flush_before_rewrite,
        resolve_compaction_provider=chat_cmd._resolve_compaction_provider,
    )

    assert handled is True
    assert flush_calls == [
        {"svc": services, "session_key": "standalone:test", "operation": "Compact"}
    ]
    assert len(services.session_manager.compact_calls) == 1
    session_key, context_window, config = services.session_manager.compact_calls[0]
    assert session_key == "standalone:test"
    assert context_window == 1234
    assert isinstance(config, CompactionConfig)
    assert config.api_key == "cli-provider-key"
    assert config.model == "openrouter/test"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.timeout_seconds == 12.5
    output = buffer.getvalue()
    assert "compacted" in output
    assert "summary 7 chars" in output


@pytest.mark.asyncio
async def test_standalone_compact_workflow_warns_without_session_manager(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_standalone_session_workflows

    services = SimpleNamespace(session_manager=None, config=None, provider_selector=None)
    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    buffer = io.StringIO()

    async def flush_before_rewrite(svc: object, session_key: str, *, operation: str) -> bool:
        raise AssertionError("flush must not run when no session manager is available")

    monkeypatch.setattr(
        chat_standalone_session_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_standalone_session_workflows.handle_standalone_compact_command(
        state,
        services=services,
        model="openrouter/test",
        flush_before_rewrite=flush_before_rewrite,
        resolve_compaction_provider=chat_cmd._resolve_compaction_provider,
    )

    assert handled is False
    assert "No session manager available." in buffer.getvalue()


@pytest.mark.asyncio
async def test_gateway_slash_tool_compress_toggles_config(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command(
        "/tool-compress off", state, fake, {"mode": None}
    )

    assert handled is True
    assert fake.config_patch_safe_calls == [
        {
            "agent_token_saving.tool_result_compression_mode": "off",
            "agent_token_saving.tool_result_compression_enabled": False,
        }
    ]
    assert fake.config_values["agent_token_saving.tool_result_compression_enabled"] is False
    assert fake.config_values["agent_token_saving.tool_result_compression_mode"] == "off"


@pytest.mark.asyncio
async def test_gateway_slash_tool_compress_can_switch_to_summarize(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command(
        "/tool-compress summarize", state, fake, {"mode": None}
    )

    assert handled is True
    assert fake.config_patch_safe_calls == [
        {
            "agent_token_saving.tool_result_compression_mode": "summarize",
            "agent_token_saving.tool_result_compression_enabled": True,
        }
    ]
    assert fake.config_values["agent_token_saving.tool_result_compression_mode"] == "summarize"


@pytest.mark.asyncio
async def test_gateway_slash_tool_compress_status_reads_config(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command(
        "/tool-compress status", state, fake, {"mode": None}
    )

    assert handled is True
    assert fake.config_get_calls == [
        "agent_token_saving.tool_result_compression_mode",
        "agent_token_saving.tool_result_compression_enabled",
        "agent_token_saving.tool_result_compression_summary_model",
    ]
    assert fake.config_patch_safe_calls == []


@pytest.mark.asyncio
async def test_standalone_tool_compress_toggles_config() -> None:
    from opensquilla.cli import chat_tool_compression_workflows

    config = SimpleNamespace(
        agent_token_saving=SimpleNamespace(
            tool_result_compression_enabled=True,
            tool_result_compression_mode=None,
            tool_result_compression_summary_model="cheap/model",
        )
    )

    await chat_tool_compression_workflows.handle_tool_compress_command(
        "/tool-compress off", config=config
    )
    assert config.agent_token_saving.tool_result_compression_enabled is False
    assert config.agent_token_saving.tool_result_compression_mode == "off"

    await chat_tool_compression_workflows.handle_tool_compress_command(
        "/tool-compress status", config=config
    )
    assert config.agent_token_saving.tool_result_compression_enabled is False

    await chat_tool_compression_workflows.handle_tool_compress_command(
        "/tool-compress summarize", config=config
    )
    assert config.agent_token_saving.tool_result_compression_enabled is True
    assert config.agent_token_saving.tool_result_compression_mode == "summarize"

    await chat_tool_compression_workflows.handle_tool_compress_command(
        "/tool-compress on", config=config
    )
    assert config.agent_token_saving.tool_result_compression_mode == "truncate"


@pytest.mark.asyncio
async def test_tool_compress_workflow_emits_status_and_usage_messages(monkeypatch) -> None:
    from opensquilla.cli import chat_tool_compression_workflows

    config = SimpleNamespace(
        agent_token_saving=SimpleNamespace(
            tool_result_compression_enabled=True,
            tool_result_compression_mode=None,
            tool_result_compression_summary_model="cheap/model",
        )
    )
    buffer = io.StringIO()
    monkeypatch.setattr(
        chat_tool_compression_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    await chat_tool_compression_workflows.handle_tool_compress_command(
        "/tool-compress status", config=config
    )
    await chat_tool_compression_workflows.handle_tool_compress_command(
        "/tool-compress summarize", config=config
    )
    await chat_tool_compression_workflows.handle_tool_compress_command(
        "/tool-compress wat", config=config
    )
    await chat_tool_compression_workflows.handle_tool_compress_command(
        "/tool-compress status", config=SimpleNamespace()
    )

    output = buffer.getvalue()
    assert "tool result compression:" in output
    assert "TRUNCATE" in output
    assert "SUMMARIZE" in output
    assert "model=cheap/model" in output
    assert "Usage: /tool-compress" in output
    assert "Tool result compression config is unavailable." in output


@pytest.mark.asyncio
async def test_gateway_slash_delete_resolves_and_reports_errors(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    fake.resolved_payload = {"session_key": "agent:main:abc123"}
    fake.delete_result = {"deleted": [], "errors": ["agent:main:abc123: locked"]}
    state = ChatSessionState(session_key="agent:main:current", model="openai/test")
    buffer = io.StringIO()
    monkeypatch.setattr(
        chat_session_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_cmd._handle_gateway_slash_command(
        "/delete abc", state, fake, {"mode": None}
    )

    assert handled is True
    assert fake.resolve_calls == ["abc"]
    assert fake.delete_calls == [["agent:main:abc123"]]
    output = buffer.getvalue()
    assert "Delete failed" in output
    assert "locked" in output


@pytest.mark.asyncio
async def test_gateway_slash_save_exports_persisted_history(monkeypatch, tmp_path) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    output = tmp_path / "saved.md"

    handled = await chat_cmd._handle_gateway_slash_command(
        f"/save {output}", state, fake, {"mode": None}
    )

    assert handled is True
    assert fake.history_calls == [{"session_key": "agent:main:abc123", "limit": 1000}]
    text = output.read_text(encoding="utf-8")
    assert "## You" in text
    assert "persisted hello" in text
    assert "## Assistant" in text
    assert "persisted reply" in text


def test_standalone_save_transcript_writes_memory_transcript(tmp_path) -> None:
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    state.transcript.add("user", "local hello")
    state.transcript.add("assistant", "local reply")
    output = tmp_path / "standalone.md"

    chat_transcript_exports.save_transcript_command(f"/save {output}", state)

    text = output.read_text(encoding="utf-8")
    assert "## You" in text
    assert "local hello" in text
    assert "## Assistant" in text
    assert "local reply" in text


def test_chat_save_transcript_uses_export_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    standalone_repl_tree = ast.parse(
        Path(chat_standalone_repl.__file__).read_text(encoding="utf-8")
    )
    utility_route_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_utility_route_workflows.py"
    )
    standalone_utility_route_path = Path(chat_cmd.__file__).with_name(
        "chat_standalone_utility_route_workflows.py"
    )
    export_tree = ast.parse(Path(chat_transcript_exports.__file__).read_text(encoding="utf-8"))

    assert utility_route_path.exists()
    assert standalone_utility_route_path.exists()

    utility_route_tree = ast.parse(utility_route_path.read_text(encoding="utf-8"))
    standalone_utility_route_tree = ast.parse(
        standalone_utility_route_path.read_text(encoding="utf-8")
    )
    chat_export_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_transcript_exports"
        for alias in node.names
    }
    chat_utility_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_utility_route_workflows"
        for alias in node.names
    }
    chat_standalone_utility_names = {
        alias.name
        for node in ast.walk(standalone_repl_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_utility_route_workflows"
        for alias in node.names
    }
    utility_export_names = {
        alias.name
        for node in ast.walk(utility_route_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_transcript_exports"
        for alias in node.names
    }
    standalone_utility_export_names = {
        alias.name
        for node in ast.walk(standalone_utility_route_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_transcript_exports"
        for alias in node.names
    }
    chat_repl_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.repl.session_state"
        for alias in node.names
    }
    export_repl_names = {
        alias.name
        for node in ast.walk(export_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.repl.session_state"
        for alias in node.names
    }
    chat_defs = {
        node.name
        for node in ast.walk(chat_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    chat_identifiers = {node.id for node in ast.walk(chat_tree) if isinstance(node, ast.Name)}

    assert chat_export_names == set()
    assert chat_utility_names == {"handle_gateway_utility_route_command"}
    assert chat_standalone_utility_names == {"handle_standalone_utility_route_command"}
    assert utility_export_names == {"SessionHistoryClient", "save_gateway_transcript_command"}
    assert standalone_utility_export_names == {"save_transcript_command"}
    assert chat_repl_names == {"ChatSessionState"}
    assert export_repl_names == {"ChatSessionState", "messages_to_markdown"}
    assert "_save_transcript_command" not in chat_defs
    assert "_save_gateway_transcript_command" not in chat_defs
    assert "messages_to_markdown" not in chat_identifiers


def test_chat_slash_tables_use_presenter_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    presenter_path = Path(chat_cmd.__file__).with_name("chat_presenters.py")

    assert presenter_path.exists()

    presenter_tree = ast.parse(presenter_path.read_text(encoding="utf-8"))
    chat_defs = {
        node.name
        for node in ast.walk(chat_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    chat_imported_modules = {
        node.module
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    presenter_defs = {
        node.name
        for node in ast.walk(presenter_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    presenter_imported_modules = {
        node.module
        for node in ast.walk(presenter_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "_print_sessions_table" not in chat_defs
    assert "_print_models_table" not in chat_defs
    assert "opensquilla.cli.chat_presenters" not in chat_imported_modules
    assert "rich.table" not in chat_imported_modules
    assert {"emit_chat_models_table", "emit_chat_sessions_table"} <= presenter_defs
    assert "rich.table" in presenter_imported_modules


def test_chat_gateway_readonly_lists_use_focused_workflow_boundaries() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    session_route_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_session_route_workflows.py"
    )
    model_route_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_model_route_workflows.py"
    )
    sessions_workflow_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_sessions_workflows.py"
    )
    models_workflow_path = Path(chat_cmd.__file__).with_name("chat_gateway_models_workflows.py")
    compatibility_path = Path(chat_cmd.__file__).with_name("chat_slash_workflows.py")

    assert session_route_path.exists()
    assert model_route_path.exists()
    assert sessions_workflow_path.exists()
    assert models_workflow_path.exists()
    assert compatibility_path.exists()

    session_route_tree = ast.parse(session_route_path.read_text(encoding="utf-8"))
    model_route_tree = ast.parse(model_route_path.read_text(encoding="utf-8"))
    sessions_workflow_tree = ast.parse(sessions_workflow_path.read_text(encoding="utf-8"))
    models_workflow_tree = ast.parse(models_workflow_path.read_text(encoding="utf-8"))
    compatibility_tree = ast.parse(compatibility_path.read_text(encoding="utf-8"))
    chat_workflow_imports = {
        (node.module, alias.name)
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }
    model_route_imports = {
        (node.module, alias.name)
        for node in ast.walk(model_route_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }
    chat_presenter_modules = {
        node.module
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    chat_gateway_calls = {
        node.func.attr
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    chat_direct_presenter_calls = {
        node.func.id
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    sessions_workflow_defs = {
        node.name
        for node in ast.walk(sessions_workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    models_workflow_defs = {
        node.name
        for node in ast.walk(models_workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    session_route_imports = {
        (node.module, alias.name)
        for node in ast.walk(session_route_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }
    compatibility_defs = {
        node.name
        for node in ast.walk(compatibility_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    compatibility_imported_modules = {
        node.module
        for node in ast.walk(compatibility_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    sessions_presenter_names = {
        alias.name
        for node in ast.walk(sessions_workflow_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_presenters"
        for alias in node.names
    }
    models_presenter_names = {
        alias.name
        for node in ast.walk(models_workflow_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_presenters"
        for alias in node.names
    }

    assert (
        "opensquilla.cli.chat_gateway_session_route_workflows",
        "handle_gateway_session_route_command",
    ) in chat_workflow_imports
    assert (
        "opensquilla.cli.chat_gateway_model_route_workflows",
        "handle_gateway_model_route_command",
    ) in chat_workflow_imports
    assert (
        "opensquilla.cli.chat_gateway_sessions_workflows",
        "handle_gateway_sessions_command",
    ) in session_route_imports
    assert (
        "opensquilla.cli.chat_gateway_models_workflows",
        "handle_gateway_models_command",
    ) in model_route_imports
    assert not any(
        module == "opensquilla.cli.chat_slash_workflows"
        for module, _name in chat_workflow_imports
    )
    assert "opensquilla.cli.chat_presenters" not in chat_presenter_modules
    assert "list_sessions" not in chat_gateway_calls
    assert "list_models" not in chat_gateway_calls
    assert "emit_chat_sessions_table" not in chat_direct_presenter_calls
    assert "emit_chat_models_table" not in chat_direct_presenter_calls
    assert "handle_gateway_sessions_command" in sessions_workflow_defs
    assert "handle_gateway_models_command" in models_workflow_defs
    assert "handle_sessions_command" not in compatibility_defs
    assert "handle_models_command" not in compatibility_defs
    assert sessions_presenter_names == {"emit_chat_sessions_table"}
    assert models_presenter_names == {"emit_chat_models_table"}
    assert "opensquilla.cli.chat_gateway_sessions_workflows" in compatibility_imported_modules
    assert "opensquilla.cli.chat_gateway_models_workflows" in compatibility_imported_modules
    assert chat_slash_workflows.handle_sessions_command.__name__ == (
        "handle_gateway_sessions_command"
    )
    assert chat_slash_workflows.handle_models_command.__name__ == "handle_gateway_models_command"


def test_chat_gateway_help_uses_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_gateway_help_workflows.py")
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_exact_route_workflows.py"
    )

    assert workflow_path.exists()
    assert executor_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_exact_route_workflows"
        for alias in node.names
    }
    handler_direct_help_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    executor_workflow_names = {
        alias.name
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_help_workflows"
        for alias in node.names
    }
    executor_name_calls = {
        node.func.id
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    workflow_imported_names = {
        alias.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert chat_workflow_names == {"handle_gateway_exact_route_command"}
    assert "handle_gateway_help_command" not in handler_direct_help_calls
    assert executor_workflow_names == {"handle_gateway_help_command"}
    assert "handle_gateway_help_command" in executor_name_calls
    assert "handle_gateway_help_command" in workflow_defs
    assert {"console", "render_help_table"} <= workflow_imported_names


def test_gateway_slash_routes_preserve_order_and_matching_contract() -> None:
    from opensquilla.cli import chat_gateway_slash_routes

    assert [route.name for route in chat_gateway_slash_routes.GATEWAY_SLASH_ROUTES] == [
        "help",
        "new",
        "status",
        "sessions",
        "resume",
        "delete",
        "clear",
        "compact",
        "models",
        "model",
        "cost",
        "usage",
        "tool_compress",
        "save",
        "image",
        "path",
        "file",
        "permissions",
        "forget",
        "approvals",
    ]

    cases = {
        "/help": ("help", "/help", ["/help"]),
        "/new": ("new", "/new", ["/new"]),
        "/new title": ("new", "/new", ["/new", "title"]),
        "/status": ("status", "/status", ["/status"]),
        "/session": ("status", "/session", ["/session"]),
        "/sessions 3": ("sessions", "/sessions", ["/sessions", "3"]),
        "/models": ("models", "/models", ["/models"]),
        "/model openai/test": ("model", "/model", ["/model", "openai/test"]),
        "/permissions status": ("permissions", "/permissions", ["/permissions", "status"]),
        "/elevated bypass": ("permissions", "/elevated", ["/elevated", "bypass"]),
        "/forget /tmp/a": ("forget", "/forget", ["/forget", "/tmp/a"]),
        "/approvals reset": ("approvals", "/approvals", ["/approvals", "reset"]),
    }
    for command, (route_name, matched_command, parts) in cases.items():
        match = chat_gateway_slash_routes.match_gateway_slash_route(command)
        assert match is not None
        assert match.name == route_name
        assert match.command == matched_command
        assert match.parts == parts

    for command in [
        "",
        "/newer",
        "/sessionsx",
        "/modelsx",
        "/modelx",
        "/forgetful",
        "/permissionsx",
        "/elevatedx",
        "/statusx",
    ]:
        assert chat_gateway_slash_routes.match_gateway_slash_route(command) is None


def test_gateway_slash_dispatch_uses_route_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_gateway_slash_routes.py")

    assert workflow_path.exists()

    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_route_imports = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_slash_routes"
        for alias in node.names
    }
    handler_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    handler_attr_calls = {
        node.func.attr
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert chat_route_imports == {"match_gateway_slash_route"}
    assert "match_gateway_slash_route" in handler_name_calls
    assert "_slash_parts" not in handler_name_calls
    assert "_slash_parts_any" not in handler_name_calls
    assert "startswith" not in handler_attr_calls


def test_gateway_exact_routes_use_executor_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_exact_route_workflows.py"
    )

    assert workflow_path.exists()

    from opensquilla.cli import chat_gateway_exact_route_workflows

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_exact_route_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    exact_handler_calls = {
        "handle_gateway_help_command",
        "handle_gateway_status_command",
        "handle_clear_session_command",
        "handle_compact_session_command",
        "handle_gateway_cost_command",
        "handle_gateway_usage_command",
    }

    assert chat_workflow_names == {"handle_gateway_exact_route_command"}
    assert "handle_gateway_exact_route_command" in slash_name_calls
    assert slash_name_calls.isdisjoint(exact_handler_calls)
    assert "handle_gateway_exact_route_command" in workflow_defs
    assert chat_gateway_exact_route_workflows.GATEWAY_EXACT_ROUTE_NAMES == frozenset(
        {"help", "status", "clear", "compact", "cost", "usage"}
    )


@pytest.mark.asyncio
async def test_gateway_exact_route_executor_delegates_known_routes(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_exact_route_workflows

    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    calls: list[str] = []

    def fake_help() -> None:
        calls.append("help")

    def fake_status(seen_state: ChatSessionState) -> bool:
        assert seen_state is state
        calls.append("status")
        return True

    async def fake_clear(seen_state: ChatSessionState, seen_client: object) -> None:
        assert seen_state is state
        assert seen_client is fake
        calls.append("clear")

    async def fake_compact(seen_state: ChatSessionState, seen_client: object) -> None:
        assert seen_state is state
        assert seen_client is fake
        calls.append("compact")

    def fake_cost(seen_state: ChatSessionState) -> None:
        assert seen_state is state
        calls.append("cost")

    async def fake_usage(seen_client: object) -> None:
        assert seen_client is fake
        calls.append("usage")

    monkeypatch.setattr(
        chat_gateway_exact_route_workflows,
        "handle_gateway_help_command",
        fake_help,
    )
    monkeypatch.setattr(
        chat_gateway_exact_route_workflows,
        "handle_gateway_status_command",
        fake_status,
    )
    monkeypatch.setattr(
        chat_gateway_exact_route_workflows,
        "handle_clear_session_command",
        fake_clear,
    )
    monkeypatch.setattr(
        chat_gateway_exact_route_workflows,
        "handle_compact_session_command",
        fake_compact,
    )
    monkeypatch.setattr(
        chat_gateway_exact_route_workflows,
        "handle_gateway_cost_command",
        fake_cost,
    )
    monkeypatch.setattr(
        chat_gateway_exact_route_workflows,
        "handle_gateway_usage_command",
        fake_usage,
    )

    for route_name in ("help", "status", "clear", "compact", "cost", "usage"):
        handled = await chat_gateway_exact_route_workflows.handle_gateway_exact_route_command(
            route_name,
            state,
            fake,
        )
        assert handled is True

    unhandled = await chat_gateway_exact_route_workflows.handle_gateway_exact_route_command(
        "new",
        state,
        fake,
    )

    assert unhandled is False
    assert calls == ["help", "status", "clear", "compact", "cost", "usage"]


def test_gateway_session_routes_use_executor_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_session_route_workflows.py"
    )

    assert workflow_path.exists()

    from opensquilla.cli import chat_gateway_session_route_workflows

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_session_route_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    workflow_imports = {
        (node.module, alias.name)
        for node in ast.walk(workflow_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }
    session_handler_calls = {
        "handle_new_session_command",
        "handle_gateway_sessions_command",
        "handle_resume_session_command",
        "handle_delete_session_command",
    }

    assert chat_workflow_names == {"handle_gateway_session_route_command"}
    assert "handle_gateway_session_route_command" in slash_name_calls
    assert slash_name_calls.isdisjoint(session_handler_calls)
    assert "handle_gateway_session_route_command" in workflow_defs
    assert {
        ("opensquilla.cli.chat_session_workflows", "handle_new_session_command"),
        ("opensquilla.cli.chat_gateway_sessions_workflows", "handle_gateway_sessions_command"),
        ("opensquilla.cli.chat_session_workflows", "handle_resume_session_command"),
        ("opensquilla.cli.chat_session_workflows", "handle_delete_session_command"),
    } <= workflow_imports
    assert chat_gateway_session_route_workflows.GATEWAY_SESSION_ROUTE_NAMES == frozenset(
        {"new", "sessions", "resume", "delete"}
    )


@pytest.mark.asyncio
async def test_gateway_session_route_executor_delegates_known_routes(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_session_route_workflows

    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    calls: list[tuple[str, str, list[str]]] = []

    async def fake_new(parts: list[str], seen_state: ChatSessionState, seen_client: object) -> None:
        assert seen_state is state
        assert seen_client is fake
        calls.append(("new", "", parts))

    async def fake_sessions(parts: list[str], seen_client: object) -> None:
        assert seen_client is fake
        calls.append(("sessions", "", parts))

    async def fake_resume(
        command: str,
        parts: list[str],
        seen_state: ChatSessionState,
        seen_client: object,
    ) -> None:
        assert seen_state is state
        assert seen_client is fake
        calls.append(("resume", command, parts))

    async def fake_delete(command: str, parts: list[str], seen_client: object) -> None:
        assert seen_client is fake
        calls.append(("delete", command, parts))

    monkeypatch.setattr(
        chat_gateway_session_route_workflows,
        "handle_new_session_command",
        fake_new,
    )
    monkeypatch.setattr(
        chat_gateway_session_route_workflows,
        "handle_gateway_sessions_command",
        fake_sessions,
    )
    monkeypatch.setattr(
        chat_gateway_session_route_workflows,
        "handle_resume_session_command",
        fake_resume,
    )
    monkeypatch.setattr(
        chat_gateway_session_route_workflows,
        "handle_delete_session_command",
        fake_delete,
    )

    cases = [
        ("new", "/new Research", ["/new", "Research"]),
        ("sessions", "/sessions 3", ["/sessions", "3"]),
        ("resume", "/resume abc", ["/resume", "abc"]),
        ("delete", "/delete abc", ["/delete", "abc"]),
    ]
    for route_name, command, parts in cases:
        handled = await chat_gateway_session_route_workflows.handle_gateway_session_route_command(
            route_name,
            command,
            parts,
            state,
            fake,
        )
        assert handled is True

    unhandled = await chat_gateway_session_route_workflows.handle_gateway_session_route_command(
        "models",
        "/models",
        ["/models"],
        state,
        fake,
    )

    assert unhandled is False
    assert calls == [
        ("new", "", ["/new", "Research"]),
        ("sessions", "", ["/sessions", "3"]),
        ("resume", "/resume abc", ["/resume", "abc"]),
        ("delete", "/delete abc", ["/delete", "abc"]),
    ]


def test_gateway_model_routes_use_executor_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_model_route_workflows.py"
    )

    assert workflow_path.exists()

    from opensquilla.cli import chat_gateway_model_route_workflows

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_model_route_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    workflow_imports = {
        (node.module, alias.name)
        for node in ast.walk(workflow_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }

    assert chat_workflow_names == {"handle_gateway_model_route_command"}
    assert "handle_gateway_model_route_command" in slash_name_calls
    assert "handle_gateway_models_command" not in slash_name_calls
    assert "handle_model_command" not in slash_name_calls
    assert "handle_gateway_model_route_command" in workflow_defs
    assert {
        ("opensquilla.cli.chat_gateway_models_workflows", "handle_gateway_models_command"),
        ("opensquilla.cli.chat_model_usage_workflows", "handle_model_command"),
    } <= workflow_imports
    assert chat_gateway_model_route_workflows.GATEWAY_MODEL_ROUTE_NAMES == frozenset(
        {"models", "model"}
    )


@pytest.mark.asyncio
async def test_gateway_model_route_executor_delegates_known_routes(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_model_route_workflows

    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    calls: list[tuple[str, list[str]]] = []

    async def fake_models(parts: list[str], seen_client: object) -> None:
        assert seen_client is fake
        calls.append(("models", parts))

    async def fake_model(
        parts: list[str],
        seen_state: ChatSessionState,
        seen_client: object,
    ) -> None:
        assert seen_state is state
        assert seen_client is fake
        calls.append(("model", parts))

    monkeypatch.setattr(
        chat_gateway_model_route_workflows,
        "handle_gateway_models_command",
        fake_models,
    )
    monkeypatch.setattr(
        chat_gateway_model_route_workflows,
        "handle_model_command",
        fake_model,
    )

    cases = [
        ("models", ["/models"]),
        ("model", ["/model", "openai/test"]),
    ]
    for route_name, parts in cases:
        handled = await chat_gateway_model_route_workflows.handle_gateway_model_route_command(
            route_name,
            parts,
            state,
            fake,
        )
        assert handled is True

    unhandled = await chat_gateway_model_route_workflows.handle_gateway_model_route_command(
        "tool_compress",
        ["/tool-compress"],
        state,
        fake,
    )

    assert unhandled is False
    assert calls == [
        ("models", ["/models"]),
        ("model", ["/model", "openai/test"]),
    ]


def test_gateway_utility_routes_use_executor_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_utility_route_workflows.py"
    )

    assert workflow_path.exists()

    from opensquilla.cli import chat_gateway_utility_route_workflows

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_utility_route_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    workflow_imports = {
        (node.module, alias.name)
        for node in ast.walk(workflow_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }

    assert chat_workflow_names == {"handle_gateway_utility_route_command"}
    assert "handle_gateway_utility_route_command" in slash_name_calls
    assert "handle_tool_compress_command" not in slash_name_calls
    assert "save_gateway_transcript_command" not in slash_name_calls
    assert "handle_gateway_utility_route_command" in workflow_defs
    assert {
        ("opensquilla.cli.chat_tool_compression_workflows", "handle_tool_compress_command"),
        ("opensquilla.cli.chat_transcript_exports", "save_gateway_transcript_command"),
    } <= workflow_imports
    assert chat_gateway_utility_route_workflows.GATEWAY_UTILITY_ROUTE_NAMES == frozenset(
        {"tool_compress", "save"}
    )


@pytest.mark.asyncio
async def test_gateway_utility_route_executor_delegates_known_routes(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_utility_route_workflows

    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    calls: list[tuple[str, str]] = []

    async def fake_tool_compress(command: str, **kwargs: object) -> None:
        assert kwargs == {"client": fake}
        calls.append(("tool_compress", command))

    async def fake_save(
        command: str,
        seen_state: ChatSessionState,
        seen_client: object,
    ) -> None:
        assert seen_state is state
        assert seen_client is fake
        calls.append(("save", command))

    monkeypatch.setattr(
        chat_gateway_utility_route_workflows,
        "handle_tool_compress_command",
        fake_tool_compress,
    )
    monkeypatch.setattr(
        chat_gateway_utility_route_workflows,
        "save_gateway_transcript_command",
        fake_save,
    )

    for route_name, command in [
        ("tool_compress", "/tool-compress status"),
        ("save", "/save out.md"),
    ]:
        handled = await chat_gateway_utility_route_workflows.handle_gateway_utility_route_command(
            route_name,
            command,
            state,
            fake,
        )
        assert handled is True

    unhandled = await chat_gateway_utility_route_workflows.handle_gateway_utility_route_command(
        "image",
        "/image chart.png",
        state,
        fake,
    )

    assert unhandled is False
    assert calls == [
        ("tool_compress", "/tool-compress status"),
        ("save", "/save out.md"),
    ]


def test_standalone_utility_routes_use_executor_boundary() -> None:
    chat_tree = ast.parse(Path(chat_standalone_repl.__file__).read_text(encoding="utf-8"))
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_standalone_utility_route_workflows.py"
    )

    assert executor_path.exists()

    from opensquilla.cli import chat_standalone_utility_route_workflows

    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    standalone_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_standalone_repl"
    )
    chat_executor_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_utility_route_workflows"
        for alias in node.names
    }
    standalone_name_calls = {
        node.func.id
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    executor_defs = {
        node.name
        for node in ast.walk(executor_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    executor_imports = {
        (node.module, alias.name)
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }

    assert chat_executor_names == {"handle_standalone_utility_route_command"}
    assert "handle_standalone_utility_route_command" in standalone_name_calls
    assert "handle_tool_compress_command" not in standalone_name_calls
    assert "save_transcript_command" not in standalone_name_calls
    assert "handle_standalone_utility_route_command" in executor_defs
    assert {
        ("opensquilla.cli.chat_tool_compression_workflows", "handle_tool_compress_command"),
        ("opensquilla.cli.chat_transcript_exports", "save_transcript_command"),
    } <= executor_imports
    assert chat_standalone_utility_route_workflows.STANDALONE_UTILITY_ROUTE_NAMES == frozenset(
        {"tool_compress", "save"}
    )


@pytest.mark.asyncio
async def test_standalone_utility_route_executor_delegates_known_routes(monkeypatch) -> None:
    from opensquilla.cli import chat_standalone_utility_route_workflows

    config = object()
    state = ChatSessionState(session_key="standalone:test", model="openrouter/test")
    calls: list[tuple[str, str]] = []

    async def fake_tool_compress(command: str, **kwargs: object) -> None:
        assert kwargs == {"config": config}
        calls.append(("tool_compress", command))

    def fake_save(command: str, seen_state: ChatSessionState) -> None:
        assert seen_state is state
        calls.append(("save", command))

    monkeypatch.setattr(
        chat_standalone_utility_route_workflows,
        "handle_tool_compress_command",
        fake_tool_compress,
    )
    monkeypatch.setattr(
        chat_standalone_utility_route_workflows,
        "save_transcript_command",
        fake_save,
    )

    for route_name, command in [
        ("tool_compress", "/tool-compress status"),
        ("save", "/save out.md"),
    ]:
        handled = await (
            chat_standalone_utility_route_workflows.handle_standalone_utility_route_command(
                route_name,
                command,
                state,
                config=config,
            )
        )
        assert handled is True

    unhandled = await (
        chat_standalone_utility_route_workflows.handle_standalone_utility_route_command(
            "image",
            "/image cat.png",
            state,
            config=config,
        )
    )

    assert unhandled is False
    assert calls == [
        ("tool_compress", "/tool-compress status"),
        ("save", "/save out.md"),
    ]


def test_chat_stateful_session_slashes_use_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_session_workflows.py")
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_session_route_workflows.py"
    )

    assert workflow_path.exists()
    assert executor_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_session_route_workflows"
        for alias in node.names
    }
    executor_workflow_names = {
        alias.name
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_session_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    handler_gateway_calls = {
        node.func.attr
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_gateway_session_route_command"}
    assert {
        "handle_delete_session_command",
        "handle_new_session_command",
        "handle_resume_session_command",
    } <= executor_workflow_names
    assert "handle_delete_session_command" not in slash_name_calls
    assert "handle_new_session_command" not in slash_name_calls
    assert "handle_resume_session_command" not in slash_name_calls
    assert "create_session" not in handler_gateway_calls
    assert "resolve_session" not in handler_gateway_calls
    assert "delete_sessions" not in handler_gateway_calls
    assert {
        "handle_delete_session_command",
        "handle_new_session_command",
        "handle_resume_session_command",
    } <= workflow_defs


def test_chat_session_maintenance_slashes_use_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_session_maintenance_workflows.py")
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_exact_route_workflows.py"
    )

    assert workflow_path.exists()
    assert executor_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_exact_route_workflows"
        for alias in node.names
    }
    executor_workflow_names = {
        alias.name
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_session_maintenance_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    handler_gateway_calls = {
        node.func.attr
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_gateway_exact_route_command"}
    assert {
        "handle_clear_session_command",
        "handle_compact_session_command",
    } <= executor_workflow_names
    assert "handle_clear_session_command" not in slash_name_calls
    assert "handle_compact_session_command" not in slash_name_calls
    assert "reset_session" not in handler_gateway_calls
    assert "compact_session" not in handler_gateway_calls
    assert {"handle_clear_session_command", "handle_compact_session_command"} <= workflow_defs


def test_chat_model_usage_slashes_use_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_model_usage_workflows.py")
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_model_route_workflows.py"
    )

    assert workflow_path.exists()
    assert executor_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_model_route_workflows"
        for alias in node.names
    }
    executor_workflow_names = {
        alias.name
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_model_usage_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    handler_gateway_calls = {
        node.func.attr
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    handler_usage_render_calls = [
        node
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "render"
    ]
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_gateway_model_route_command"}
    assert executor_workflow_names == {"handle_model_command", "ModelUsageClient"}
    assert "handle_model_command" not in slash_name_calls
    assert "patch_session" not in handler_gateway_calls
    assert "usage_status" not in handler_gateway_calls
    assert handler_usage_render_calls == []
    assert "handle_model_command" in workflow_defs
    assert "handle_cost_command" not in workflow_defs
    assert "handle_usage_command" not in workflow_defs


def test_chat_gateway_usage_slashes_use_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_gateway_usage_workflows.py")
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_exact_route_workflows.py"
    )

    assert workflow_path.exists()
    assert executor_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_exact_route_workflows"
        for alias in node.names
    }
    executor_workflow_names = {
        alias.name
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_usage_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    handler_gateway_calls = {
        node.func.attr
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    handler_usage_render_calls = [
        node
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "render"
    ]
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_gateway_exact_route_command"}
    assert {
        "handle_gateway_cost_command",
        "handle_gateway_usage_command",
    } <= executor_workflow_names
    assert "handle_gateway_cost_command" not in slash_name_calls
    assert "handle_gateway_usage_command" not in slash_name_calls
    assert "usage_status" not in handler_gateway_calls
    assert handler_usage_render_calls == []
    assert {"handle_gateway_cost_command", "handle_gateway_usage_command"} <= workflow_defs


def test_chat_tool_compress_slashes_use_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_tool_compression_workflows.py")
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_utility_route_workflows.py"
    )

    assert workflow_path.exists()
    assert executor_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_utility_route_workflows"
        for alias in node.names
    }
    executor_workflow_names = {
        alias.name
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_tool_compression_workflows"
        for alias in node.names
    }
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    chat_defs = {
        node.name
        for node in ast.walk(chat_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    chat_name_calls = {
        node.func.id
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    chat_literals = {
        node.value
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_gateway_utility_route_command"}
    assert executor_workflow_names == {"handle_tool_compress_command"}
    assert "_handle_tool_compress_command" not in chat_defs
    assert "_handle_tool_compress_command" not in chat_name_calls
    assert "handle_tool_compress_command" not in slash_name_calls
    assert "agent_token_saving.tool_result_compression_enabled" not in chat_literals
    assert "agent_token_saving.tool_result_compression_mode" not in chat_literals
    assert "agent_token_saving.tool_result_compression_summary_model" not in chat_literals
    assert "handle_tool_compress_command" in workflow_defs


def test_chat_standalone_model_cost_slashes_use_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_standalone_repl.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name(
        "chat_standalone_model_cost_workflows.py"
    )

    assert workflow_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    standalone_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_standalone_repl"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_model_cost_workflows"
        for alias in node.names
    }
    standalone_attr_calls = {
        node.func.attr
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    standalone_literals = {
        node.value
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {
        "handle_standalone_cost_command",
        "handle_standalone_model_command",
    }
    assert "render" not in standalone_attr_calls
    assert "[green]model:[/green] {model}" not in standalone_literals
    assert {
        "handle_standalone_cost_command",
        "handle_standalone_model_command",
    } <= workflow_defs


def test_chat_standalone_status_slashes_use_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_standalone_repl.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_standalone_status_workflows.py")

    assert workflow_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    standalone_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_standalone_repl"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_status_workflows"
        for alias in node.names
    }
    standalone_literals = {
        node.value
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {
        "handle_standalone_models_command",
        "handle_standalone_status_command",
    }
    assert "[yellow]/models requires gateway mode.[/yellow]" not in standalone_literals
    assert "model[/] [dim]" not in standalone_literals
    assert {
        "handle_standalone_models_command",
        "handle_standalone_status_command",
    } <= workflow_defs


def test_chat_standalone_new_slash_uses_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_standalone_repl.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_standalone_session_workflows.py")

    assert workflow_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    standalone_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_standalone_repl"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_session_workflows"
        for alias in node.names
    }
    standalone_name_calls = {
        node.func.id
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    standalone_literals = {
        node.value
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "handle_standalone_new_command" in chat_workflow_names
    assert "handle_standalone_new_command" in standalone_name_calls
    assert not any(
        literal.startswith("[green]Started new session")
        for literal in standalone_literals
    )
    assert "handle_standalone_new_command" in workflow_defs


def test_chat_standalone_clear_slash_uses_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_standalone_repl.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_standalone_session_workflows.py")

    assert workflow_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    standalone_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_standalone_repl"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_session_workflows"
        for alias in node.names
    }
    standalone_attr_calls = {
        node.func.attr
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    standalone_literals = {
        node.value
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "handle_standalone_clear_command" in chat_workflow_names
    assert "handle_standalone_new_command" in chat_workflow_names
    assert "handle_standalone_clear_command" in workflow_defs
    assert "truncate" not in standalone_attr_calls
    assert not any("]cleared[/]" in literal for literal in standalone_literals)


def test_chat_standalone_compact_slash_uses_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_standalone_repl.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_standalone_session_workflows.py")

    assert workflow_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    standalone_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_standalone_repl"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_session_workflows"
        for alias in node.names
    }
    standalone_name_calls = {
        node.func.id
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    standalone_attr_calls = {
        node.func.attr
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    standalone_literals = {
        node.value
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {
        "handle_standalone_clear_command",
        "handle_standalone_compact_command",
        "handle_standalone_new_command",
    }
    assert "handle_standalone_compact_command" in standalone_name_calls
    assert "handle_standalone_compact_command" in workflow_defs
    assert "compact" not in standalone_attr_calls
    assert not any("]compacted[/]" in literal for literal in standalone_literals)
    assert not any("]compact skipped[/]" in literal for literal in standalone_literals)


def test_chat_standalone_path_slash_uses_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_standalone_repl.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_standalone_path_workflows.py")

    assert workflow_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    standalone_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_standalone_repl"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_path_workflows"
        for alias in node.names
    }
    standalone_name_calls = {
        node.func.id
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    standalone_literals = {
        node.value
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_standalone_path_command"}
    assert "handle_standalone_path_command" in standalone_name_calls
    assert "_path_prompt_and_attachments" not in standalone_name_calls
    assert "Usage: /path <path> [prompt]" not in standalone_literals
    assert "/path must not create attachments." not in standalone_literals
    assert "handle_standalone_path_command" in workflow_defs


def test_chat_standalone_image_slash_uses_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_standalone_repl.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_standalone_image_workflows.py")

    assert workflow_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    standalone_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_standalone_repl"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_image_workflows"
        for alias in node.names
    }
    standalone_name_calls = {
        node.func.id
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    standalone_literals = {
        node.value
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_standalone_image_command"}
    assert "handle_standalone_image_command" in standalone_name_calls
    assert "_handle_image_command_turnrunner" not in standalone_name_calls
    assert "_image_prompt_from_command" not in standalone_name_calls
    assert "Usage: /image <path> [prompt]" not in standalone_literals
    assert "handle_standalone_image_command" in workflow_defs


def test_chat_standalone_slash_matching_uses_route_boundary() -> None:
    chat_tree = ast.parse(Path(chat_standalone_repl.__file__).read_text(encoding="utf-8"))
    route_path = Path(chat_cmd.__file__).with_name("chat_standalone_slash_routes.py")

    assert route_path.exists()

    from opensquilla.cli import chat_standalone_slash_routes

    route_tree = ast.parse(route_path.read_text(encoding="utf-8"))
    standalone_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_standalone_repl"
    )
    chat_route_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_standalone_slash_routes"
        for alias in node.names
    }
    standalone_name_calls = {
        node.func.id
        for node in ast.walk(standalone_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    route_defs = {
        node.name
        for node in ast.walk(route_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_route_names == {"match_standalone_slash_route"}
    assert "match_standalone_slash_route" in standalone_name_calls
    assert "_slash_parts" not in standalone_name_calls
    assert "match_standalone_slash_route" in route_defs
    assert chat_standalone_slash_routes.STANDALONE_SLASH_ROUTE_NAMES == frozenset(
        {
            "help",
            "new",
            "status",
            "models",
            "model",
            "cost",
            "tool_compress",
            "clear",
            "compact",
            "save",
            "image",
            "path",
        }
    )


def test_gateway_image_route_uses_executor_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_image_route_workflows.py"
    )
    workflow_path = Path(chat_cmd.__file__).with_name("chat_gateway_image_workflows.py")

    assert executor_path.exists()
    assert workflow_path.exists()

    from opensquilla.cli import chat_gateway_image_route_workflows

    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_image_route_workflows"
        for alias in node.names
    }
    executor_workflow_names = {
        alias.name
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_image_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    slash_literals = {
        node.value
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    executor_defs = {
        node.name
        for node in ast.walk(executor_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_gateway_image_route_command"}
    assert "handle_gateway_image_route_command" in slash_name_calls
    assert "handle_gateway_image_command" not in slash_name_calls
    assert "_image_prompt_and_attachments" not in slash_name_calls
    assert "Usage: /image <path> [prompt]" not in slash_literals
    assert "handle_gateway_image_route_command" in executor_defs
    assert "handle_gateway_image_command" in executor_workflow_names
    assert "handle_gateway_image_command" in workflow_defs
    assert chat_gateway_image_route_workflows.GATEWAY_IMAGE_ROUTE_NAMES == frozenset(
        {"image"}
    )


@pytest.mark.asyncio
async def test_gateway_image_route_executor_delegates_known_route(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_image_route_workflows

    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    elevated_state = {"mode": "always"}
    calls: list[dict[str, object]] = []

    async def fake_image(
        command: str,
        parts: list[str],
        seen_state: ChatSessionState,
        *,
        client: object,
        elevated_state: dict[str, str | None],
        stream_response: object,
        image_prompt_and_attachments: object,
    ) -> bool:
        calls.append(
            {
                "command": command,
                "parts": parts,
                "state": seen_state,
                "client": client,
                "elevated_state": elevated_state,
                "stream_response": stream_response,
                "image_prompt_and_attachments": image_prompt_and_attachments,
            }
        )
        return True

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response is passed through, not called here")

    def prompt_builder(command: str) -> tuple[str, list[dict[str, str]]]:
        raise AssertionError("prompt_builder is passed through, not called here")

    monkeypatch.setattr(
        chat_gateway_image_route_workflows,
        "handle_gateway_image_command",
        fake_image,
    )

    handled = await chat_gateway_image_route_workflows.handle_gateway_image_route_command(
        "image",
        "/image /tmp/chart.png describe chart",
        ["/image", "/tmp/chart.png describe chart"],
        state,
        client=fake,
        elevated_state=elevated_state,
        stream_response=stream_response,
        image_prompt_and_attachments=prompt_builder,
    )
    unhandled = await chat_gateway_image_route_workflows.handle_gateway_image_route_command(
        "path",
        "/path /tmp/chart.png",
        ["/path", "/tmp/chart.png"],
        state,
        client=fake,
        elevated_state=elevated_state,
        stream_response=stream_response,
        image_prompt_and_attachments=prompt_builder,
    )

    assert handled is True
    assert unhandled is False
    assert calls == [
        {
            "command": "/image /tmp/chart.png describe chart",
            "parts": ["/image", "/tmp/chart.png describe chart"],
            "state": state,
            "client": fake,
            "elevated_state": elevated_state,
            "stream_response": stream_response,
            "image_prompt_and_attachments": prompt_builder,
        }
    ]


def test_gateway_io_routes_use_executor_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    executor_path = Path(chat_cmd.__file__).with_name("chat_gateway_io_route_workflows.py")
    path_workflow_path = Path(chat_cmd.__file__).with_name("chat_gateway_path_workflows.py")
    file_workflow_path = Path(chat_cmd.__file__).with_name("chat_gateway_file_workflows.py")

    assert executor_path.exists()
    assert path_workflow_path.exists()
    assert file_workflow_path.exists()

    from opensquilla.cli import chat_gateway_io_route_workflows

    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_io_route_workflows"
        for alias in node.names
    }
    executor_workflow_imports = {
        (node.module, alias.name)
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    slash_literals = {
        node.value
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    slash_attr_calls = {
        node.func.attr
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    executor_defs = {
        node.name
        for node in ast.walk(executor_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_gateway_io_route_command"}
    assert "handle_gateway_io_route_command" in slash_name_calls
    assert "handle_gateway_path_command" not in slash_name_calls
    assert "handle_gateway_file_command" not in slash_name_calls
    assert "_path_prompt_and_attachments" not in slash_name_calls
    assert "_async_file_prompt_and_attachments" not in slash_name_calls
    assert "_gateway_client_is_local" not in slash_name_calls
    assert "upload_file" not in slash_attr_calls
    assert "Usage: /path <path> [prompt]" not in slash_literals
    assert "Usage: /file <path> [prompt]" not in slash_literals
    assert "handle_gateway_io_route_command" in executor_defs
    assert {
        ("opensquilla.cli.chat_gateway_path_workflows", "handle_gateway_path_command"),
        ("opensquilla.cli.chat_gateway_file_workflows", "handle_gateway_file_command"),
    } <= executor_workflow_imports
    assert chat_gateway_io_route_workflows.GATEWAY_IO_ROUTE_NAMES == frozenset(
        {"path", "file"}
    )


@pytest.mark.asyncio
async def test_gateway_io_route_executor_delegates_known_routes(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_io_route_workflows

    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    elevated_state = {"mode": "always"}
    calls: list[tuple[str, str, list[str], object, object, object]] = []

    async def fake_path(
        command: str,
        parts: list[str],
        seen_state: ChatSessionState,
        **kwargs: object,
    ) -> bool:
        calls.append(
            (
                "path",
                command,
                parts,
                seen_state,
                kwargs["path_prompt_and_attachments"],
                kwargs["gateway_client_is_local"],
            )
        )
        assert kwargs["client"] is fake
        assert kwargs["elevated_state"] is elevated_state
        assert kwargs["remote_gateway_message"] == "remote path blocked"
        return True

    async def fake_file(
        command: str,
        parts: list[str],
        seen_state: ChatSessionState,
        **kwargs: object,
    ) -> bool:
        calls.append(
            (
                "file",
                command,
                parts,
                seen_state,
                kwargs["async_file_prompt_and_attachments"],
                kwargs["stream_response"],
            )
        )
        assert kwargs["client"] is fake
        assert kwargs["elevated_state"] is elevated_state
        return True

    async def stream_response(*args: object, **kwargs: object) -> TurnResult:
        raise AssertionError("stream_response is passed through, not called here")

    def path_builder(command: str) -> tuple[str, list[dict[str, object]]]:
        raise AssertionError("path_builder is passed through, not called here")

    async def file_builder(command: str, **kwargs: object) -> tuple[str, list[dict[str, object]]]:
        raise AssertionError("file_builder is passed through, not called here")

    def local_check(client: object) -> bool:
        raise AssertionError("local_check is passed through, not called here")

    monkeypatch.setattr(
        chat_gateway_io_route_workflows,
        "handle_gateway_path_command",
        fake_path,
    )
    monkeypatch.setattr(
        chat_gateway_io_route_workflows,
        "handle_gateway_file_command",
        fake_file,
    )

    for route_name, command, parts in [
        ("path", "/path /tmp/a.txt summarize", ["/path", "/tmp/a.txt summarize"]),
        ("file", "/file /tmp/a.txt summarize", ["/file", "/tmp/a.txt summarize"]),
    ]:
        handled = await chat_gateway_io_route_workflows.handle_gateway_io_route_command(
            route_name,
            command,
            parts,
            state,
            client=fake,
            elevated_state=elevated_state,
            stream_response=stream_response,
            path_prompt_and_attachments=path_builder,
            gateway_client_is_local=local_check,
            remote_gateway_message="remote path blocked",
            async_file_prompt_and_attachments=file_builder,
        )
        assert handled is True

    unhandled = await chat_gateway_io_route_workflows.handle_gateway_io_route_command(
        "permissions",
        "/permissions status",
        ["/permissions", "status"],
        state,
        client=fake,
        elevated_state=elevated_state,
        stream_response=stream_response,
        path_prompt_and_attachments=path_builder,
        gateway_client_is_local=local_check,
        remote_gateway_message="remote path blocked",
        async_file_prompt_and_attachments=file_builder,
    )

    assert unhandled is False
    assert calls == [
        (
            "path",
            "/path /tmp/a.txt summarize",
            ["/path", "/tmp/a.txt summarize"],
            state,
            path_builder,
            local_check,
        ),
        (
            "file",
            "/file /tmp/a.txt summarize",
            ["/file", "/tmp/a.txt summarize"],
            state,
            file_builder,
            stream_response,
        ),
    ]


def test_gateway_control_routes_use_executor_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_control_route_workflows.py"
    )
    permissions_workflow_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_permissions_workflows.py"
    )
    forget_workflow_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_forget_workflows.py"
    )
    approvals_workflow_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_approvals_workflows.py"
    )

    assert executor_path.exists()
    assert permissions_workflow_path.exists()
    assert forget_workflow_path.exists()
    assert approvals_workflow_path.exists()

    from opensquilla.cli import chat_gateway_control_route_workflows

    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_control_route_workflows"
        for alias in node.names
    }
    executor_workflow_imports = {
        (node.module, alias.name)
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    slash_literals = {
        node.value
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    executor_defs = {
        node.name
        for node in ast.walk(executor_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_gateway_control_route_command"}
    assert "handle_gateway_control_route_command" in slash_name_calls
    assert "handle_gateway_permissions_command" not in slash_name_calls
    assert "handle_gateway_forget_command" not in slash_name_calls
    assert "handle_gateway_approvals_command" not in slash_name_calls
    assert "_handle_elevated_command" not in slash_name_calls
    assert "_handle_forget_command" not in slash_name_calls
    assert "_handle_approvals_command" not in slash_name_calls
    assert "Usage: /permissions on | off | bypass | full | status" not in slash_literals
    assert "Unknown permissions mode:" not in slash_literals
    assert "All cached approvals cleared." not in slash_literals
    assert "Cached approval for" not in slash_literals
    assert "Approval mode reset to prompt; server cache cleared." not in slash_literals
    assert "Failed to query approvals:" not in slash_literals
    assert "cached intents (" not in slash_literals
    assert "handle_gateway_control_route_command" in executor_defs
    assert {
        (
            "opensquilla.cli.chat_gateway_permissions_workflows",
            "handle_gateway_permissions_command",
        ),
        ("opensquilla.cli.chat_gateway_forget_workflows", "handle_gateway_forget_command"),
        (
            "opensquilla.cli.chat_gateway_approvals_workflows",
            "handle_gateway_approvals_command",
        ),
    } <= executor_workflow_imports
    assert chat_gateway_control_route_workflows.GATEWAY_CONTROL_ROUTE_NAMES == frozenset(
        {"permissions", "forget", "approvals"}
    )


@pytest.mark.asyncio
async def test_gateway_control_route_executor_delegates_known_routes(
    monkeypatch,
) -> None:
    from opensquilla.cli import chat_gateway_control_route_workflows

    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    elevated_state = {"mode": "always"}
    calls: list[tuple[str, str]] = []

    async def forget_server_approvals(client: object | None, target: str | None) -> bool:
        raise AssertionError("forget_server_approvals is passed through, not called here")

    async def fake_permissions(
        command: str,
        seen_state: ChatSessionState,
        seen_elevated_state: dict[str, str | None],
        **kwargs: object,
    ) -> bool:
        assert seen_state is state
        assert seen_elevated_state is elevated_state
        assert kwargs == {
            "client": fake,
            "forget_server_approvals": forget_server_approvals,
        }
        calls.append(("permissions", command))
        return True

    async def fake_forget(command: str, **kwargs: object) -> bool:
        assert kwargs == {
            "client": fake,
            "forget_server_approvals": forget_server_approvals,
        }
        calls.append(("forget", command))
        return True

    async def fake_approvals(command: str, client: object) -> bool:
        assert client is fake
        calls.append(("approvals", command))
        return True

    monkeypatch.setattr(
        chat_gateway_control_route_workflows,
        "handle_gateway_permissions_command",
        fake_permissions,
    )
    monkeypatch.setattr(
        chat_gateway_control_route_workflows,
        "handle_gateway_forget_command",
        fake_forget,
    )
    monkeypatch.setattr(
        chat_gateway_control_route_workflows,
        "handle_gateway_approvals_command",
        fake_approvals,
    )

    for route_name, command in [
        ("permissions", "/permissions status"),
        ("forget", "/forget /tmp/a.txt"),
        ("approvals", "/approvals reset"),
    ]:
        handled = await chat_gateway_control_route_workflows.handle_gateway_control_route_command(
            route_name,
            command,
            state,
            elevated_state,
            client=fake,
            forget_server_approvals=forget_server_approvals,
        )
        assert handled is True

    unhandled = await chat_gateway_control_route_workflows.handle_gateway_control_route_command(
        "path",
        "/path /tmp/a.txt",
        state,
        elevated_state,
        client=fake,
        forget_server_approvals=forget_server_approvals,
    )

    assert unhandled is False
    assert calls == [
        ("permissions", "/permissions status"),
        ("forget", "/forget /tmp/a.txt"),
        ("approvals", "/approvals reset"),
    ]


def test_chat_gateway_status_slash_uses_workflow_boundary() -> None:
    chat_tree = ast.parse(Path(chat_cmd.__file__).read_text(encoding="utf-8"))
    workflow_path = Path(chat_cmd.__file__).with_name("chat_gateway_status_workflows.py")
    executor_path = Path(chat_cmd.__file__).with_name(
        "chat_gateway_exact_route_workflows.py"
    )

    assert workflow_path.exists()
    assert executor_path.exists()

    workflow_tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    slash_handler = next(
        node
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_gateway_slash_command"
    )
    chat_workflow_names = {
        alias.name
        for node in ast.walk(chat_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_exact_route_workflows"
        for alias in node.names
    }
    executor_workflow_names = {
        alias.name
        for node in ast.walk(executor_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.chat_gateway_status_workflows"
        for alias in node.names
    }
    slash_name_calls = {
        node.func.id
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    slash_literals = {
        node.value
        for node in ast.walk(slash_handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    workflow_defs = {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert chat_workflow_names == {"handle_gateway_exact_route_command"}
    assert executor_workflow_names == {"handle_gateway_status_command"}
    assert "handle_gateway_status_command" not in slash_name_calls
    assert "[{ACCENT}]permissions[/] [dim]{state.elevated or 'normal'}[/dim]" not in slash_literals
    assert "handle_gateway_status_command" in workflow_defs


def test_chat_session_presenter_renders_gateway_rows(monkeypatch) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr(
        chat_presenters,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    chat_presenters.emit_chat_sessions_table(
        [
            {
                "session_key": "agent:main:abc123",
                "status": "running",
                "model": "openai/test",
                "entry_count": 2,
            }
        ]
    )

    output = buffer.getvalue()
    assert "Sessions" in output
    assert "agent:main:abc123" in output
    assert "running" in output
    assert "openai/test" in output
    assert "2" in output


@pytest.mark.asyncio
async def test_gateway_slash_help_renders_help_table(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_help_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    buffer = io.StringIO()
    monkeypatch.setattr(
        chat_gateway_help_workflows,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    handled = await chat_cmd._handle_gateway_slash_command(
        "/help",
        state,
        fake,
        {"mode": None},
    )

    output = buffer.getvalue()
    assert handled is True
    assert "OpenSquilla Chat Commands" in output
    assert "/help" in output
    assert "agent:main:abc123" == state.session_key
    assert fake.list_sessions_calls == []
    assert fake.list_models_calls == 0


@pytest.mark.asyncio
async def test_gateway_slash_sessions_uses_presenter_boundary(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_sessions_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    rendered: list[list[dict[str, object]]] = []

    def fake_emit(rows: list[dict[str, object]]) -> None:
        rendered.append(rows)

    monkeypatch.setattr(chat_gateway_sessions_workflows, "emit_chat_sessions_table", fake_emit)

    handled = await chat_cmd._handle_gateway_slash_command(
        "/sessions 3", state, fake, {"mode": None}
    )

    assert handled is True
    assert fake.list_sessions_calls == [3]
    assert rendered == [
        [
            {
                "session_key": "agent:main:abc123",
                "status": "running",
                "model": "openai/test",
                "entry_count": 2,
            }
        ]
    ]


@pytest.mark.asyncio
async def test_gateway_slash_models_does_not_hit_model_prefix(monkeypatch) -> None:
    from opensquilla.cli import chat_gateway_models_workflows

    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")
    rendered: list[list[dict[str, object]]] = []

    def fake_emit(rows: list[dict[str, object]]) -> None:
        rendered.append(rows)

    monkeypatch.setattr(chat_gateway_models_workflows, "emit_chat_models_table", fake_emit)

    handled = await chat_cmd._handle_gateway_slash_command("/models", state, fake, {"mode": None})

    assert handled is True
    assert fake.list_models_calls == 1
    assert rendered == [[{"id": "openai/test", "provider": "openai"}]]
    assert state.model == "openai/test"


@pytest.mark.asyncio
async def test_gateway_slash_unknown_prefix_is_not_handled(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command("/newer", state, fake, {"mode": None})

    assert handled is False
    assert fake.create_calls == []
    assert state.session_key == "agent:main:abc123"


@pytest.mark.asyncio
async def test_gateway_stream_keyboard_interrupt_aborts_turn(monkeypatch) -> None:
    class InterruptingGatewayClient(_FakeGatewayClient):
        async def send_message(self, session_key, message, attachments=None, elevated=None):
            self.send_calls.append(
                {
                    "session_key": session_key,
                    "message": message,
                    "attachments": attachments,
                    "elevated": elevated,
                }
            )
            raise KeyboardInterrupt
            yield {}

    InterruptingGatewayClient.instances = []
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", InterruptingGatewayClient)
    fake = InterruptingGatewayClient()

    result = await chat_cmd._stream_response_gateway(
        fake,
        "agent:main:abc123",
        "hello",
        {"mode": None},
    )

    assert result.cancelled is True
    assert fake.abort_calls == ["agent:main:abc123"]
    assert fake.send_calls[0]["message"] == "hello"


@pytest.mark.asyncio
async def test_gateway_stream_cancelled_error_aborts_turn(monkeypatch) -> None:
    class CancelledGatewayClient(_FakeGatewayClient):
        async def send_message(self, session_key, message, attachments=None, elevated=None):
            self.send_calls.append(
                {
                    "session_key": session_key,
                    "message": message,
                    "attachments": attachments,
                    "elevated": elevated,
                }
            )
            raise asyncio.CancelledError
            yield {}

    CancelledGatewayClient.instances = []
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", CancelledGatewayClient)
    fake = CancelledGatewayClient()

    result = await chat_cmd._stream_response_gateway(
        fake,
        "agent:main:abc123",
        "hello",
        {"mode": None},
    )

    assert result.cancelled is True
    assert fake.abort_calls == ["agent:main:abc123"]
    assert fake.send_calls[0]["message"] == "hello"


@pytest.mark.asyncio
async def test_gateway_stream_renders_task_group_status_without_buffer_pollution(
    monkeypatch,
) -> None:
    class StatusGatewayClient(_FakeGatewayClient):
        async def send_message(self, session_key, message, attachments=None, elevated=None):
            yield {
                "event": "session.event.task_group.waiting",
                "group_id": "group-1",
                "pending_count": 2,
            }
            yield {
                "event": "session.event.task_group.synthesizing",
                "group_id": "group-1",
                "child_count": 2,
            }
            yield {"event": "session.event.text_delta", "text": "answer"}
            yield {
                "event": "session.event.task_group.done",
                "group_id": "group-1",
                "delivery_status": "not_applicable",
            }
            yield {"event": "session.event.done"}

    class RecordingRenderer:
        instances: list[RecordingRenderer] = []

        def __init__(self) -> None:
            self.buffer = ""
            self.statuses: list[str] = []
            self.finalized = False
            RecordingRenderer.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def append_text(self, delta: str) -> None:
            self.buffer += delta

        def status(self, message: str, **_kwargs) -> None:
            self.statuses.append(message)

        def tool_call(self, *_args, **_kwargs) -> None:
            return None

        def error(self, message: str) -> None:
            raise AssertionError(f"unexpected error render: {message}")

        def finalize(self, *_args, **_kwargs) -> None:
            self.finalized = True

    monkeypatch.setattr(chat_cmd, "StreamingRenderer", RecordingRenderer)
    fake = StatusGatewayClient()

    result = await chat_cmd._stream_response_gateway(
        fake,
        "agent:main:abc123",
        "hello",
        {"mode": None},
    )

    renderer = RecordingRenderer.instances[-1]
    assert result.text == "answer"
    assert renderer.buffer == "answer"
    assert renderer.finalized is True
    assert len(renderer.statuses) == 3
    assert "waiting" in renderer.statuses[0]
    assert "synthesizing" in renderer.statuses[1]
    assert "complete" in renderer.statuses[2]


@pytest.mark.asyncio
async def test_gateway_stream_collects_artifact_events(monkeypatch) -> None:
    artifact = {
        "id": "art-chat",
        "kind": "artifact_ref",
        "name": "report.txt",
        "mime": "text/plain",
        "size": 4,
        "sha256": "e" * 64,
        "session_id": "session-1",
        "session_key": "agent:main:abc123",
        "source": "publish_artifact",
        "created_at": "2026-05-06T12:00:00Z",
        "download_url": "/api/v1/artifacts/art-chat?sessionKey=agent%3Amain%3Aabc123",
    }

    class ArtifactGatewayClient(_FakeGatewayClient):
        async def send_message(self, session_key, message, attachments=None, elevated=None):
            yield {"event": "session.event.artifact", **artifact}
            yield {"event": "session.event.text_delta", "text": "answer"}
            yield {"event": "session.event.done"}

    monkeypatch.setattr(chat_cmd, "StreamingRenderer", _RecordingRenderer)
    result = await chat_cmd._stream_response_gateway(
        ArtifactGatewayClient(),
        "agent:main:abc123",
        "hello",
        {"mode": None},
    )

    assert result.text == "answer"
    assert result.artifacts[0]["download_url"] == "/api/v1/artifacts/art-chat"
    assert "session_key" not in result.artifacts[0]
    assert "sessionKey" not in json.dumps(result.artifacts[0])


@pytest.mark.asyncio
async def test_gateway_elevated_unknown_prefix_is_not_handled(monkeypatch) -> None:
    _FakeGatewayClient.instances.clear()
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    fake = _FakeGatewayClient()
    state = ChatSessionState(session_key="agent:main:abc123", model="openai/test")

    handled = await chat_cmd._handle_gateway_slash_command(
        "/elevatedx", state, fake, {"mode": None}
    )

    assert handled is False
