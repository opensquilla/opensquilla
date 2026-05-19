from __future__ import annotations

import ast
import inspect

import pytest

from opensquilla.cli import chat_gateway_repl
from opensquilla.cli.gateway_client import GatewayRPCError
from opensquilla.cli.repl.stream import TurnResult, UsageSummary


class _FakeConsole:
    def __init__(self) -> None:
        self.prints: list[tuple[object, ...]] = []

    def print(self, *objects: object, **_: object) -> None:
        self.prints.append(objects)

    def text(self) -> str:
        return "\n".join(str(obj) for objects in self.prints for obj in objects)


class _FakeGatewayClient:
    instances: list[_FakeGatewayClient] = []

    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.create_calls: list[dict[str, object]] = []
        self.send_calls: list[dict[str, object]] = []
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
        return "agent:main:created"

    async def send_message(
        self,
        session_key: str,
        message: str,
        attachments: list[dict[str, object]] | None = None,
        elevated: str | None = None,
    ):
        self.send_calls.append(
            {
                "session_key": session_key,
                "message": message,
                "attachments": attachments,
                "elevated": elevated,
            }
        )
        if False:
            yield {}

    async def close(self) -> None:
        self.closed = True


class _Transcript:
    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self.turns.append((role, content))


class _Usage:
    def __init__(self) -> None:
        self.items: list[UsageSummary | None] = []

    def add(self, usage: UsageSummary | None) -> None:
        self.items.append(usage)


class _PromptState:
    label = "fake prompt > "


class _FakeState:
    def __init__(self, *, session_key: str, model: str | None = None) -> None:
        self.session_key = session_key
        self.model = model
        self.transcript = _Transcript()
        self.usage = _Usage()

    def prompt_state(self) -> _PromptState:
        return _PromptState()


def _factory_from_prompts(prompts: list[str | None]):
    seen_labels: list[str] = []
    values = iter(prompts)

    async def fake_prompt(label: str) -> str | None:
        seen_labels.append(label)
        return next(values)

    return fake_prompt, seen_labels


async def _fake_stream_response(
    client: _FakeGatewayClient,
    session_key: str,
    message: str,
    elevated_state: dict[str, str | None] | None = None,
) -> TurnResult:
    async for _event in client.send_message(
        session_key,
        message,
        elevated=elevated_state["mode"] if elevated_state else None,
    ):
        pass
    return TurnResult(text="assistant reply", usage=UsageSummary(input_tokens=2))


def test_module_boundary_exists_without_importing_chat_cmd() -> None:
    source = inspect.getsource(chat_gateway_repl)
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert hasattr(chat_gateway_repl, "run_gateway_chat")
    assert "opensquilla.cli.chat_cmd" not in imported_modules
    assert "opensquilla.cli.chat_cmd" not in source


@pytest.mark.asyncio
async def test_create_session_path_forwards_model_and_closes_client() -> None:
    _FakeGatewayClient.instances.clear()
    console = _FakeConsole()
    prompt, labels = _factory_from_prompts(["/quit"])

    await chat_gateway_repl.run_gateway_chat(
        "anthropic/claude-sonnet-4",
        None,
        gateway_client_factory=_FakeGatewayClient,
        prompt_user_fn=prompt,
        stream_response=_fake_stream_response,
        console_obj=console,
        state_factory=_FakeState,
    )

    client = _FakeGatewayClient.instances[-1]
    assert client.connected is True
    assert client.closed is True
    assert client.create_calls == [
        {
            "agent_id": "main",
            "model": "anthropic/claude-sonnet-4",
            "display_name": None,
        }
    ]
    assert labels == ["fake prompt > "]
    assert "Connected to gateway. Session: agent:main:created" in console.text()
    assert "Model: anthropic/claude-sonnet-4" in console.text()


@pytest.mark.asyncio
async def test_resume_path_skips_create_session_and_sends_user_message() -> None:
    _FakeGatewayClient.instances.clear()
    console = _FakeConsole()
    prompt, _labels = _factory_from_prompts(["hello", "/quit"])

    await chat_gateway_repl.run_gateway_chat(
        None,
        "agent:main:resumed",
        gateway_client_factory=_FakeGatewayClient,
        prompt_user_fn=prompt,
        stream_response=_fake_stream_response,
        console_obj=console,
        state_factory=_FakeState,
    )

    client = _FakeGatewayClient.instances[-1]
    assert client.create_calls == []
    assert client.send_calls == [
        {
            "session_key": "agent:main:resumed",
            "message": "hello",
            "attachments": None,
            "elevated": None,
        }
    ]
    assert client.closed is True
    assert "Connected to gateway. Resuming session: agent:main:resumed" in console.text()


@pytest.mark.asyncio
async def test_resume_with_model_prints_ignored_model_note() -> None:
    _FakeGatewayClient.instances.clear()
    console = _FakeConsole()
    prompt, _labels = _factory_from_prompts(["/quit"])

    await chat_gateway_repl.run_gateway_chat(
        "openai/gpt-5",
        "agent:main:resumed",
        gateway_client_factory=_FakeGatewayClient,
        prompt_user_fn=prompt,
        stream_response=_fake_stream_response,
        console_obj=console,
        state_factory=_FakeState,
    )

    assert "ignored when resuming a session" in console.text()
    assert _FakeGatewayClient.instances[-1].create_calls == []


@pytest.mark.asyncio
async def test_slash_command_errors_render_error_panel_and_continue() -> None:
    _FakeGatewayClient.instances.clear()
    console = _FakeConsole()
    prompt, _labels = _factory_from_prompts(["/boom", "/quit"])
    slash_calls: list[str] = []

    async def failing_slash_command(
        command: str,
        _state: _FakeState,
        _client: _FakeGatewayClient,
        _elevated_state: dict[str, str | None],
    ) -> bool:
        slash_calls.append(command)
        raise GatewayRPCError("test.method", code="bad", message="broken")

    await chat_gateway_repl.run_gateway_chat(
        None,
        None,
        gateway_client_factory=_FakeGatewayClient,
        prompt_user_fn=prompt,
        stream_response=_fake_stream_response,
        handle_slash_command=failing_slash_command,
        console_obj=console,
        error_panel_fn=lambda message: f"ERROR PANEL: {message}",
        state_factory=_FakeState,
    )

    assert slash_calls == ["/boom"]
    assert "ERROR PANEL: test.method failed: bad: broken" in console.text()
    assert "Goodbye." in console.text()


@pytest.mark.asyncio
async def test_dependencies_are_injected_for_chat_cmd_facade_compatibility() -> None:
    _FakeGatewayClient.instances.clear()
    console = _FakeConsole()
    prompt, labels = _factory_from_prompts(["hello", "custom-exit"])
    states: list[_FakeState] = []

    def state_factory(*, session_key: str, model: str | None = None) -> _FakeState:
        state = _FakeState(session_key=session_key, model=model)
        states.append(state)
        return state

    await chat_gateway_repl.run_gateway_chat(
        "openai/test",
        None,
        gateway_client_factory=_FakeGatewayClient,
        prompt_user_fn=prompt,
        stream_response=_fake_stream_response,
        handle_slash_command=lambda *_args: False,
        console_obj=console,
        error_panel_fn=lambda message: f"ERROR: {message}",
        state_factory=state_factory,
        is_exit_command_fn=lambda value: value == "custom-exit",
    )

    state = states[-1]
    client = _FakeGatewayClient.instances[-1]
    assert state.session_key == "agent:main:created"
    assert state.model == "openai/test"
    assert labels == ["fake prompt > ", "fake prompt > "]
    assert client.send_calls[0]["message"] == "hello"
    assert state.transcript.turns == [("user", "hello"), ("assistant", "assistant reply")]
    assert state.usage.items == [UsageSummary(input_tokens=2)]
    assert client.closed is True
