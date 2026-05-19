"""Gateway chat REPL orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from rich.panel import Panel

from opensquilla.cli import attachments as _cli_attachments
from opensquilla.cli import chat_approval_prompts as _chat_approval_prompts
from opensquilla.cli import chat_stream_presenters
from opensquilla.cli.chat_gateway_control_route_workflows import (
    handle_gateway_control_route_command,
)
from opensquilla.cli.chat_gateway_exact_route_workflows import (
    handle_gateway_exact_route_command,
)
from opensquilla.cli.chat_gateway_image_route_workflows import (
    handle_gateway_image_route_command,
)
from opensquilla.cli.chat_gateway_io_route_workflows import (
    handle_gateway_io_route_command,
)
from opensquilla.cli.chat_gateway_model_route_workflows import (
    handle_gateway_model_route_command,
)
from opensquilla.cli.chat_gateway_session_route_workflows import (
    handle_gateway_session_route_command,
)
from opensquilla.cli.chat_gateway_slash_routes import match_gateway_slash_route
from opensquilla.cli.chat_gateway_utility_route_workflows import (
    handle_gateway_utility_route_command,
)
from opensquilla.cli.chat_input_builders import (
    _async_file_prompt_and_attachments,
    _gateway_client_is_local,
    _image_prompt_and_attachments,
    _path_prompt_and_attachments,
)
from opensquilla.cli.repl.commands import is_exit_command
from opensquilla.cli.repl.prompt import prompt_user
from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.repl.stream import StreamingRenderer, TurnResult, UsageSummary
from opensquilla.cli.ui import ACCENT, console, error_panel

_PATH_REMOTE_GATEWAY_MESSAGE = _cli_attachments.PATH_REMOTE_GATEWAY_MESSAGE
_maybe_handle_approval = _chat_approval_prompts.maybe_handle_approval


class _ConsoleLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


class _GatewayClientLike(Protocol):
    async def connect(self) -> None: ...

    async def create_session(
        self,
        agent_id: str = "main",
        model: str | None = None,
        display_name: str | None = None,
    ) -> str: ...

    async def reset_session(self, key: str) -> dict[str, Any]: ...

    async def compact_session(self, key: str) -> dict[str, Any]: ...

    async def usage_status(self) -> dict[str, Any]: ...

    async def resolve_session(self, key: str) -> dict[str, Any]: ...

    async def delete_sessions(self, keys: list[str]) -> dict[str, Any]: ...

    async def list_sessions(self, limit: int = 50) -> dict[str, Any]: ...

    async def list_models(self) -> list[dict[str, Any]]: ...

    async def patch_session(self, key: str, **fields: Any) -> dict[str, Any]: ...

    async def session_history(self, session_key: str, limit: int = 1000) -> dict[str, Any]: ...

    def send_message(
        self,
        session_key: str,
        message: str,
        attachments: list[dict[str, Any]] | None = None,
        elevated: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def resolve_approval(
        self,
        approval_id: str,
        approved: bool,
        *,
        allow_always: bool = False,
    ) -> Any: ...

    async def abort_session(self, key: str) -> dict[str, Any]: ...

    async def upload_file(self, path: Path, mime: str, name: str) -> str: ...

    async def close(self) -> None: ...


GatewayClientFactory = Callable[[], _GatewayClientLike]
PromptUser = Callable[[str], Awaitable[str | None]]
StreamResponse = Callable[..., Awaitable[TurnResult]]
SlashCommandHandler = Callable[
    [str, Any, _GatewayClientLike, dict[str, str | None]],
    Awaitable[bool],
]
StateFactory = Callable[..., Any]
ExitCommandPredicate = Callable[[str], bool]
ErrorPanelFactory = Callable[[str], object]


async def run_gateway_chat(
    model: str | None,
    session_id: str | None,
    *,
    gateway_client_factory: GatewayClientFactory | None = None,
    prompt_user_fn: PromptUser | None = None,
    stream_response: StreamResponse | None = None,
    handle_slash_command: SlashCommandHandler | None = None,
    console_obj: _ConsoleLike | None = None,
    error_panel_fn: ErrorPanelFactory | None = None,
    state_factory: StateFactory | None = None,
    is_exit_command_fn: ExitCommandPredicate | None = None,
) -> None:
    """Run the gateway-backed interactive chat REPL."""

    from opensquilla.cli.gateway_client import GatewayClient, GatewayRPCError

    client_factory = gateway_client_factory or GatewayClient
    prompt_fn = prompt_user_fn or prompt_user
    stream_fn = stream_response or _stream_response_gateway
    slash_fn = handle_slash_command or _handle_gateway_slash_command
    output = console_obj or console
    render_error = error_panel_fn or error_panel
    make_state = state_factory or ChatSessionState
    exit_command = is_exit_command_fn or is_exit_command

    client = client_factory()
    await client.connect()

    elevated_state: dict[str, str | None] = {"mode": None}

    try:
        if session_id:
            session_key = session_id
            output.print(f"[dim]Connected to gateway. Resuming session: {session_key}[/dim]")
            if model:
                output.print(
                    "[yellow]Note: --model is honored only at session creation; "
                    "ignored when resuming a session.[/yellow]"
                )
        else:
            session_key = await client.create_session(model=model)
            output.print(f"[dim]Connected to gateway. Session: {session_key}[/dim]")
            if model:
                output.print(f"[dim]Model: {model}[/dim]")
        state = make_state(session_key=session_key, model=model)

        output.print(
            Panel(
                f"[bold {ACCENT}]OpenSquilla Chat[/bold {ACCENT}]\n"
                "[dim]Enter sends. Ctrl+C cancels the current turn or clears input. "
                "Ctrl+D exits. /help lists commands.[/dim]",
                title="Gateway",
                border_style=ACCENT,
            )
        )

        while True:
            try:
                user_input = await prompt_fn(state.prompt_state().label)
            except (EOFError, KeyboardInterrupt):
                output.print("\n[yellow]Goodbye.[/yellow]")
                break

            if user_input is None or exit_command(user_input):
                output.print("[yellow]Goodbye.[/yellow]")
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            if stripped.startswith("/"):
                try:
                    handled = await slash_fn(stripped, state, client, elevated_state)
                except GatewayRPCError as exc:
                    output.print(render_error(str(exc)))
                    continue
                if handled:
                    session_key = state.session_key
                    model = state.model
                    continue
                output.print("[red]Unknown command.[/red] [dim]Use /help.[/dim]")
                continue

            try:
                result = await stream_fn(client, session_key, user_input, elevated_state)
            except GatewayRPCError as exc:
                output.print(render_error(str(exc)))
                continue
            state.transcript.add("user", user_input)
            state.transcript.add("assistant", result.text)
            state.usage.add(result.usage)
    finally:
        await client.close()


async def _handle_gateway_slash_command(
    cmd: str,
    state: ChatSessionState,
    client: _GatewayClientLike,
    elevated_state: dict[str, str | None],
) -> bool:
    route_match = match_gateway_slash_route(cmd)
    if route_match is None:
        return False

    route_name = route_match.name
    parts = route_match.parts

    if await handle_gateway_exact_route_command(route_name, state, client):
        return True

    if await handle_gateway_session_route_command(route_name, cmd, parts, state, client):
        return True

    if await handle_gateway_model_route_command(route_name, parts, state, client):
        return True

    if await handle_gateway_utility_route_command(route_name, cmd, state, client):
        return True

    if await handle_gateway_image_route_command(
        route_name,
        cmd,
        parts,
        state,
        client=client,
        elevated_state=elevated_state,
        stream_response=_stream_response_gateway,
        image_prompt_and_attachments=_image_prompt_and_attachments,
    ):
        return True

    if await handle_gateway_io_route_command(
        route_name,
        cmd,
        parts,
        state,
        client=client,
        elevated_state=elevated_state,
        stream_response=_stream_response_gateway,
        path_prompt_and_attachments=_path_prompt_and_attachments,
        gateway_client_is_local=_gateway_client_is_local,
        remote_gateway_message=_PATH_REMOTE_GATEWAY_MESSAGE,
        async_file_prompt_and_attachments=_async_file_prompt_and_attachments,
    ):
        return True

    if await handle_gateway_control_route_command(
        route_name,
        cmd,
        state,
        elevated_state,
        client=client,
        forget_server_approvals=_forget_server_approvals,
    ):
        return True

    return False


async def _forget_server_approvals(client: object | None, target: str | None = None) -> bool:
    if client is not None:
        try:
            forget_approvals = getattr(client, "forget_approvals")
            await forget_approvals(target)
            return True
        except Exception as exc:  # noqa: BLE001
            console.print(
                f"[red]Failed to clear server-side approvals:[/red] {type(exc).__name__}: {exc}"
            )
            console.print(
                "[red]The gateway is likely running older code. "
                "Restart it with[/red] [bold]pkill -f 'opensquilla gateway' "
                "&& opensquilla gateway run[/bold][red] and retry.[/red]"
            )
            return False

    from opensquilla.application.intent_cache import get_intent_cache

    cache = get_intent_cache()
    if target:
        cache.forget(f"rm {target}")
        cache.forget(target)
    else:
        cache.clear()
    return True


def _clear_current_cancel() -> None:
    task = asyncio.current_task()
    if task is not None and hasattr(task, "uncancel"):
        task.uncancel()


def _artifact_event_payload(event: Any) -> dict[str, Any]:
    return chat_stream_presenters.artifact_event_payload(event)


def _render_artifact_status(artifact: dict[str, Any], renderer: StreamingRenderer) -> None:
    chat_stream_presenters.render_artifact_status(artifact, renderer)


async def _stream_response_gateway(
    client: _GatewayClientLike,
    session_key: str,
    message: str,
    elevated_state: dict[str, str | None] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> TurnResult:
    elevated = elevated_state["mode"] if elevated_state else None
    usage: UsageSummary | None = None
    cancelled = False
    artifacts: list[dict[str, Any]] = []

    with StreamingRenderer() as renderer:
        try:
            async for event in client.send_message(
                session_key, message, attachments=attachments, elevated=elevated
            ):
                event_name = event.get("event", "")
                if event_name == "session.event.text_delta":
                    renderer.append_text(event.get("text", ""))
                elif event_name == "session.event.tool_use_start":
                    renderer.tool_call(event.get("tool_name") or event.get("toolName") or "tool")
                elif event_name == "session.event.tool_result":
                    await _maybe_handle_approval(
                        event.get("result"),
                        renderer,
                        client.resolve_approval,
                        elevated_state=elevated_state,
                    )
                elif event_name == "session.event.artifact":
                    artifact = _artifact_event_payload(event)
                    artifacts.append(artifact)
                    _render_artifact_status(artifact, renderer)
                elif event_name.startswith("session.event.task_group."):
                    chat_stream_presenters.render_gateway_task_group_status(
                        event_name, event, renderer
                    )
                elif event_name == "session.event.error":
                    message_text = event.get("message", "unknown")
                    renderer.error(message_text)
                    return TurnResult(
                        text=renderer.buffer,
                        usage=usage,
                        error=message_text,
                        artifacts=artifacts,
                    )
                elif event_name == "session.event.done":
                    usage = UsageSummary.from_gateway_payload(event)
                    cancelled = event.get("reason") == "aborted"
        except (KeyboardInterrupt, asyncio.CancelledError):
            _clear_current_cancel()
            await client.abort_session(session_key)
            cancelled = True
        renderer.finalize(usage, cancelled=cancelled)
    return TurnResult(
        text=renderer.buffer,
        usage=usage,
        cancelled=cancelled,
        artifacts=artifacts,
    )
