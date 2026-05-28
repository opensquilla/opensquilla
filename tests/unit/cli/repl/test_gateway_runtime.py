from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
from typing import Any, cast

import pytest

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.repl.stream import TurnResult, UsageSummary
from opensquilla.cli.tui.contracts import TuiOutputHandle


def test_gateway_runtime_has_no_raw_prompt_application_dependency(monkeypatch) -> None:
    monkeypatch.delitem(
        sys.modules,
        "opensquilla.cli.repl.gateway_runtime",
        raising=False,
    )

    original_import = __import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "prompt_toolkit" or name.startswith("prompt_toolkit."):
            raise AssertionError(f"gateway runtime imported prompt_toolkit via {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _guarded_import)

    module = importlib.import_module("opensquilla.cli.repl.gateway_runtime")
    source = inspect.getsource(module)

    assert "ChatApplication" not in source


def test_gateway_session_context_mirrors_state_to_legacy_scope() -> None:
    from opensquilla.cli.repl.gateway_runtime import GatewaySessionContext

    state = ChatSessionState(session_key="agent:main:original", model="gateway/original")
    context = GatewaySessionContext.create(state)

    assert context.scope["session_key"] == "agent:main:original"
    assert context.scope["state"] is state
    assert context.scope["model"] == "gateway/original"

    state.session_key = "agent:main:slash"
    state.model = "gateway/slash-model"
    context.sync_from_state()

    assert context.session_key == "agent:main:slash"
    assert context.model == "gateway/slash-model"
    assert context.scope["session_key"] == "agent:main:slash"
    assert context.scope["model"] == "gateway/slash-model"


@pytest.mark.asyncio
async def test_gateway_runtime_dispatches_messages_slash_commands_and_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import gateway_runtime

    class _FakeGatewayClient:
        instances: list[_FakeGatewayClient] = []

        def __init__(self) -> None:
            self.connected = False
            self.closed = False
            self.create_calls: list[str | None] = []
            self.resolve_calls: list[str] = []
            self.abort_calls: list[str] = []
            _FakeGatewayClient.instances.append(self)

        async def connect(self) -> None:
            self.connected = True

        async def create_session(self, model: str | None = None) -> str:
            self.create_calls.append(model)
            return "agent:main:new"

        async def resolve_session(self, key: str) -> dict[str, str]:
            self.resolve_calls.append(key)
            return {"model": "gateway/resolved"}

        async def abort_session(self, key: str) -> dict[str, object]:
            self.abort_calls.append(key)
            return {"aborted": True, "key": key}

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)

    output = cast(TuiOutputHandle, object())
    captured: dict[str, Any] = {}

    async def fake_stream_response(
        client: object,
        session_key: str,
        message: str,
        elevated_state: dict[str, str | None] | None = None,
        attachments: list[dict] | None = None,
        *,
        tui_output: object | None = None,
    ) -> TurnResult:
        captured["stream"] = {
            "client": client,
            "session_key": session_key,
            "message": message,
            "elevated_state": elevated_state,
            "attachments": attachments,
            "tui_output": tui_output,
        }
        return TurnResult(
            text="assistant reply",
            usage=UsageSummary(input_tokens=2, output_tokens=3),
            model_after="gateway/after",
        )

    async def fake_handle_slash_command(
        cmd: str,
        state: ChatSessionState,
        client: object,
        elevated_state: dict[str, str | None],
        *,
        tui_output: object | None = None,
    ) -> bool:
        captured["slash"] = {
            "cmd": cmd,
            "client": client,
            "elevated_state": elevated_state,
            "tui_output": tui_output,
        }
        state.session_key = "agent:main:slash"
        state.model = "gateway/slash-model"
        return True

    async def fake_run_concurrent_repl(
        *,
        scope: gateway_runtime.GatewayRuntimeScope,
        dispatch,
        abort_active_turn=None,
    ) -> None:
        captured["initial_scope"] = dict(scope)
        captured["abort_active_turn"] = abort_active_turn

        assert await dispatch("hello") is True
        active_state = cast(ChatSessionState, scope["state"])
        captured["state_after_message"] = active_state
        assert active_state.model == "gateway/after"
        assert active_state.transcript.to_markdown()
        assert active_state.usage.input_tokens == 2
        assert active_state.usage.output_tokens == 3

        assert await dispatch("/reset") is True
        captured["scope_after_slash"] = dict(scope)

        assert await dispatch("/exit") is False

    def fake_get_tui_output(
        _scope: gateway_runtime.GatewayRuntimeScope,
    ) -> TuiOutputHandle | None:
        return output

    deps = gateway_runtime.GatewayRuntimeDependencies(
        stream_response=fake_stream_response,
        handle_slash_command=fake_handle_slash_command,
        run_input_loop=fake_run_concurrent_repl,
        get_tui_output=fake_get_tui_output,
        is_exit_command=lambda value: value.strip() == "/exit",
        notify=lambda notice: captured.setdefault("notices", []).append(notice),
    )

    await gateway_runtime.run_gateway_chat(
        model="anthropic/claude-sonnet-4",
        session_id=None,
        deps=deps,
    )

    client = _FakeGatewayClient.instances[-1]
    assert client.connected is True
    assert client.closed is True
    assert client.create_calls == ["anthropic/claude-sonnet-4"]
    assert client.resolve_calls == ["agent:main:new"]
    assert captured["abort_active_turn"] is not None
    await captured["abort_active_turn"]()
    assert client.abort_calls == []
    assert captured["initial_scope"]["session_key"] == "agent:main:new"
    assert captured["initial_scope"]["model"] == "gateway/resolved"
    assert captured["stream"]["client"] is client
    assert captured["stream"]["session_key"] == "agent:main:new"
    assert captured["stream"]["message"] == "hello"
    assert captured["stream"]["elevated_state"] == {"mode": None}
    assert captured["stream"]["tui_output"] is output
    assert captured["slash"]["cmd"] == "/reset"
    assert captured["slash"]["client"] is client
    assert captured["slash"]["elevated_state"] == {"mode": None}
    assert captured["slash"]["tui_output"] is output
    assert captured["scope_after_slash"]["session_key"] == "agent:main:slash"
    assert captured["scope_after_slash"]["model"] == "gateway/slash-model"
    assert [notice.kind for notice in captured["notices"]] == [
        "created",
        "model",
        "welcome",
        "goodbye",
    ]


@pytest.mark.asyncio
async def test_gateway_abort_targets_active_turn_session_after_session_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import gateway_runtime

    class _FakeGatewayClient:
        instances: list[_FakeGatewayClient] = []

        def __init__(self) -> None:
            self.abort_calls: list[str] = []
            _FakeGatewayClient.instances.append(self)

        async def connect(self) -> None:
            return None

        async def create_session(self, model: str | None = None) -> str:
            return "agent:main:old"

        async def resolve_session(self, key: str) -> dict[str, str]:
            return {"model": "gateway/old"}

        async def abort_session(self, key: str) -> dict[str, object]:
            self.abort_calls.append(key)
            return {"aborted": True, "key": key}

        async def close(self) -> None:
            return None

    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)

    stream_started = asyncio.Event()
    release_stream = asyncio.Event()

    async def fake_stream_response(
        _client: object,
        session_key: str,
        _message: str,
        _elevated_state: dict[str, str | None] | None = None,
        _attachments: list[dict] | None = None,
        *,
        tui_output: object | None = None,
    ) -> TurnResult:
        assert session_key == "agent:main:old"
        stream_started.set()
        await release_stream.wait()
        return TurnResult(
            text="assistant reply",
            usage=UsageSummary(input_tokens=1, output_tokens=1),
            model_after="gateway/old",
        )

    async def fake_handle_slash_command(
        _cmd: str,
        _state: ChatSessionState,
        _client: object,
        _elevated_state: dict[str, str | None],
        *,
        tui_output: object | None = None,
    ) -> bool:
        return True

    async def fake_run_concurrent_repl(
        *,
        scope: gateway_runtime.GatewayRuntimeScope,
        dispatch,
        abort_active_turn=None,
    ) -> None:
        assert abort_active_turn is not None

        turn = asyncio.create_task(dispatch("hello"))
        await asyncio.wait_for(stream_started.wait(), timeout=2.0)

        active_state = cast(ChatSessionState, scope["state"])
        active_state.session_key = "agent:main:new"
        active_state.model = "gateway/new"
        scope["session_key"] = active_state.session_key
        scope["model"] = active_state.model

        await abort_active_turn()
        release_stream.set()
        assert await asyncio.wait_for(turn, timeout=2.0) is True

    deps = gateway_runtime.GatewayRuntimeDependencies(
        stream_response=fake_stream_response,
        handle_slash_command=fake_handle_slash_command,
        run_input_loop=fake_run_concurrent_repl,
        get_tui_output=lambda _scope: None,
        is_exit_command=lambda _value: False,
        notify=lambda _notice: None,
    )

    await gateway_runtime.run_gateway_chat(
        model=None,
        session_id=None,
        deps=deps,
    )

    client = _FakeGatewayClient.instances[-1]
    assert client.abort_calls == ["agent:main:old"]
