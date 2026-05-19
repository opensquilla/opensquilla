"""Chat command — interactive chat mode with Rich output.

Two modes:
- Default (gateway): Connect to running gateway daemon via WebSocket. Full features.
- --standalone: TurnRunner-based direct mode, no gateway daemon needed.
"""

from __future__ import annotations

import asyncio
import getpass
import inspect
import json
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import typer
from rich.panel import Panel

from opensquilla.cli import attachments as _cli_attachments
from opensquilla.cli import chat_stream_presenters
from opensquilla.cli import chat_stream_support as _chat_stream_support
from opensquilla.cli.chat_gateway_approvals_workflows import (
    handle_gateway_approvals_command,
)
from opensquilla.cli.chat_gateway_control_route_workflows import (
    handle_gateway_control_route_command,
)
from opensquilla.cli.chat_gateway_exact_route_workflows import (
    handle_gateway_exact_route_command,
)
from opensquilla.cli.chat_gateway_forget_workflows import handle_gateway_forget_command
from opensquilla.cli.chat_gateway_image_route_workflows import (
    handle_gateway_image_route_command,
)
from opensquilla.cli.chat_gateway_io_route_workflows import (
    handle_gateway_io_route_command,
)
from opensquilla.cli.chat_gateway_model_route_workflows import (
    handle_gateway_model_route_command,
)
from opensquilla.cli.chat_gateway_permissions_workflows import (
    handle_permissions_command,
)
from opensquilla.cli.chat_gateway_session_route_workflows import (
    handle_gateway_session_route_command,
)
from opensquilla.cli.chat_gateway_slash_routes import match_gateway_slash_route
from opensquilla.cli.chat_gateway_utility_route_workflows import (
    handle_gateway_utility_route_command,
)
from opensquilla.cli.chat_standalone_image_workflows import handle_standalone_image_command
from opensquilla.cli.chat_standalone_model_cost_workflows import (
    handle_standalone_cost_command,
    handle_standalone_model_command,
)
from opensquilla.cli.chat_standalone_path_workflows import handle_standalone_path_command
from opensquilla.cli.chat_standalone_session_workflows import (
    handle_standalone_clear_command,
    handle_standalone_compact_command,
    handle_standalone_new_command,
)
from opensquilla.cli.chat_standalone_slash_routes import match_standalone_slash_route
from opensquilla.cli.chat_standalone_status_workflows import (
    handle_standalone_models_command,
    handle_standalone_status_command,
)
from opensquilla.cli.chat_standalone_utility_route_workflows import (
    handle_standalone_utility_route_command,
)
from opensquilla.cli.repl.commands import is_exit_command, render_help_table
from opensquilla.cli.repl.prompt import prompt_approval, prompt_user
from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.repl.stream import StreamingRenderer, TurnResult, UsageSummary
from opensquilla.cli.ui import ACCENT, console, error_panel

_CLI_ALLOWED_FILE_MIMES = _cli_attachments.CLI_ALLOWED_FILE_MIMES
_CLI_INLINE_THRESHOLD_BYTES = _cli_attachments.CLI_INLINE_THRESHOLD_BYTES
_PATH_REMOTE_GATEWAY_MESSAGE = _cli_attachments.PATH_REMOTE_GATEWAY_MESSAGE
_CLI_ATTACHMENT_COMPAT_EXPORTS = (_CLI_ALLOWED_FILE_MIMES, _CLI_INLINE_THRESHOLD_BYTES)

_optional_positive_config_float = _chat_stream_support._optional_positive_config_float
_timeout_exception_message = _chat_stream_support._timeout_exception_message
_turn_stream_error_message = _chat_stream_support._turn_stream_error_message
_wrap_cli_turn_stream = _chat_stream_support._wrap_cli_turn_stream


class _GatewayClientLike(Protocol):
    async def create_session(
        self,
        agent_id: str = "main",
        model: str | None = None,
        display_name: str | None = None,
    ) -> str: ...

    async def list_sessions(self, limit: int = 50) -> dict[str, Any]: ...

    async def resolve_session(self, key: str) -> dict[str, Any]: ...

    async def delete_sessions(self, keys: list[str]) -> dict[str, Any]: ...

    async def reset_session(self, key: str) -> dict[str, Any]: ...

    async def compact_session(self, key: str) -> dict[str, Any]: ...

    async def list_models(
        self,
        provider: str | None = None,
        capabilities: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...

    async def patch_session(self, key: str, **fields: Any) -> dict[str, Any]: ...

    async def usage_status(self) -> dict[str, Any]: ...

    async def upload_file(self, path: Path, mime: str, name: str) -> str: ...

    def send_message(
        self,
        session_key: str,
        message: str,
        attachments: list[dict] | None = None,
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

    async def session_history(self, session_key: str, limit: int = 1000) -> dict[str, Any]: ...


def _resolve_compaction_provider(
    provider_selector: Any,
    model_override: str | None = None,
) -> Any | None:
    if provider_selector is None:
        return None
    selector = provider_selector
    clone = getattr(provider_selector, "clone", None)
    if callable(clone):
        try:
            selector = clone()
        except Exception:  # noqa: BLE001
            selector = provider_selector
    if model_override and selector is not provider_selector:
        override = getattr(selector, "override_model", None)
        if callable(override):
            try:
                override(model_override)
            except Exception:  # noqa: BLE001
                pass
    resolver = getattr(selector, "resolve", None)
    if not callable(resolver):
        return None
    try:
        return resolver()
    except Exception:  # noqa: BLE001
        return None


async def _maybe_handle_approval(
    result: Any,
    live: Any,
    resolver: Callable[..., Awaitable[Any]],
    elevated_state: dict[str, str | None] | None = None,
) -> None:
    """If *result* is an approval-required/pending payload, prompt/notify the user.

    The prompt offers four approval choices:

    * ``o`` / ``y`` — allow once (approve only this specific call)
    * ``a``         — allow always (cache intent for the session lifetime)
    * ``b``         — bypass (approve + flip session into /elevated bypass mode;
                      future destructive ops auto-approve, sensitive paths still
                      hard-blocked)
    * ``d`` / ``n`` — deny

    ``resolver(approval_id, approved, allow_always=...)`` is called with the
    user's decision. The Live display is paused during input and resumed
    afterwards so the prompt isn't mangled by the refresh loop.
    """
    payload: dict[str, Any]
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return
        if not isinstance(parsed, dict):
            return
        payload = parsed
    elif isinstance(result, dict):
        payload = result
    else:
        return

    # Hard-block envelope (sensitive path, etc.) — just show the refusal,
    # no prompt to offer.
    if payload.get("status") == "blocked":
        live.stop()
        try:
            console.print()
            console.print(
                Panel(
                    f"[bold]Command:[/bold] {str(payload.get('command', '')).strip()}\n"
                    f"[dim]{payload.get('message', '')}[/dim]",
                    title="[red]Blocked (sensitive path)[/red]",
                    border_style="red",
                )
            )
        finally:
            live.start()
        return

    status = str(payload.get("status") or "")
    if status not in {"approval_required", "approval_pending"}:
        return
    approval_id = payload.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        return
    command = str(payload.get("command", "")).strip()
    warning = str(payload.get("warning") or payload.get("message") or "").strip()

    live.stop()
    try:
        console.print()
        body = f"[bold]Command:[/bold] {command or '(not shown)'}"
        if warning:
            body += f"\n[dim]{warning}[/dim]"
        console.print(
            Panel(
                body,
                title=(
                    "[yellow]Approval pending[/yellow]"
                    if status == "approval_pending"
                    else "[yellow]Approval required[/yellow]"
                ),
                border_style="yellow",
            )
        )
        console.print(
            "[dim]  [bold]o[/bold]nce    allow this call only[/dim]\n"
            "[dim]  [bold]a[/bold]lways  allow this intent for the session[/dim]\n"
            "[dim]  [bold]b[/bold]ypass  approve + skip future approvals "
            "(sensitive paths still blocked)[/dim]\n"
            "[dim]  [bold]d[/bold]eny    reject[/dim]"
        )
        answer = await prompt_approval("Decision [o/a/b/d]: ")

        flip_to_bypass = False
        # Backwards compatibility: y still means once, n still means deny.
        if answer in ("b", "bypass"):
            approved, allow_always, label = True, True, "Approved + bypass mode"
            flip_to_bypass = True
        elif answer in ("a", "always"):
            approved, allow_always, label = True, True, "Always approved"
        elif answer in ("o", "y", "yes", "once", ""):
            approved, allow_always, label = True, False, "Approved (once)"
        else:
            approved, allow_always, label = False, False, "Denied"

        try:
            await resolver(approval_id, approved, allow_always=allow_always)
            color = "green" if approved else "red"
            if flip_to_bypass:
                if elevated_state is not None:
                    elevated_state["mode"] = "bypass"
                suffix = (
                    " — session now in [red]bypass[/red] mode. "
                    "Sensitive paths still blocked. Use /elevated off to revert."
                )
            elif allow_always:
                suffix = " — future similar intents auto-approve."
            else:
                suffix = ""
            console.print(f"[{color}]{label}[/{color}]{suffix}")
        except Exception as exc:  # pragma: no cover — RPC/queue transport errors
            console.print(f"[red]Failed to resolve approval:[/red] {exc}")
    finally:
        live.start()


def _cli_sender_id() -> str:
    raw = os.environ.get("USER")
    if raw and raw.strip():
        return raw.strip()
    try:
        return getpass.getuser() or "cli-user"
    except Exception:
        return "cli-user"


def _slash_parts(cmd: str, name: str) -> list[str] | None:
    if cmd == name or cmd.startswith(f"{name} "):
        return cmd.split(maxsplit=1)
    return None


def _slash_parts_any(cmd: str, *names: str) -> list[str] | None:
    for name in names:
        parts = _slash_parts(cmd, name)
        if parts is not None:
            return parts
    return None


def _clear_current_cancel() -> None:
    """Keep one Ctrl+C scoped to the active turn under asyncio.run."""
    task = asyncio.current_task()
    if task is not None and hasattr(task, "uncancel"):
        task.uncancel()


def run_chat(
    model: str = typer.Option("", "--model", "-m", help="Model override (provider/model)"),
    session_id: str = typer.Option("", "--session", "-s", help="Resume session ID"),
    standalone: bool = typer.Option(False, "--standalone", help="Direct Agent without gateway"),
    workspace: str = typer.Option("", "--workspace", help="Workspace root for standalone tools"),
    workspace_strict: bool | None = typer.Option(
        None,
        "--workspace-strict/--no-workspace-strict",
        help="Restrict read-side file tools to --workspace in standalone mode",
    ),
    timeout: float | None = None,
) -> None:
    """Start interactive chat with the agent.

    Default: connects to the running gateway daemon for full features
    (tools, skills, session persistence). Use --standalone for direct
    TurnRunner mode without a gateway daemon.
    """
    _timeout = timeout
    if not sys.stdin.isatty() or not console.is_terminal:
        typer.echo(
            "opensquilla chat is interactive; use `opensquilla agent -m '...'` for non-TTY.",
            err=True,
        )
        raise typer.Exit(2)
    if standalone:
        console.print(
            Panel(
                f"[bold {ACCENT}]OpenSquilla Chat[/bold {ACCENT}]\n"
                "[dim]Enter sends. Ctrl+C clears input or cancels the current turn. "
                "Ctrl+D exits. /help lists commands.[/dim]",
                title="OpenSquilla",
                border_style=ACCENT,
            )
        )
        if model:
            console.print(f"[dim]Model: {model}[/dim]")
        if session_id:
            console.print(f"[dim]Session: {session_id}[/dim]")
        asyncio.run(
            _standalone_repl(
                model=model or None,
                session_id=session_id or None,
                workspace=workspace or None,
                workspace_strict=workspace_strict,
                timeout=_timeout,
            )
        )
    else:
        # Default: gateway mode — full agent capabilities
        if workspace or workspace_strict is not None:
            console.print(
                "[yellow]Note:[/yellow] --workspace only affects --standalone chat. "
                "In gateway mode, /path requires the path to be visible to the "
                "gateway runtime; use /file to upload from this CLI machine for "
                "remote gateways."
            )
        asyncio.run(
            _gateway_chat(
                model=model or None,
                session_id=session_id or None,
            )
        )


# ---------------------------------------------------------------------------
# Standalone mode (--standalone) — TurnRunner + build_services, no daemon
# ---------------------------------------------------------------------------


async def _read_standalone_transcript(
    session_manager: Any,
    session_key: str,
) -> list[Any] | None:
    """Read the durable transcript before a destructive standalone command."""
    if session_manager is None:
        return []
    for method_name in ("get_transcript", "read_transcript"):
        reader = getattr(session_manager, method_name, None)
        if not callable(reader):
            continue
        try:
            result = reader(session_key)
            if inspect.isawaitable(result):
                result = await result
        except KeyError:
            return []
        except Exception:  # noqa: BLE001
            return None
        return list(result or [])
    return None


async def _flush_before_standalone_rewrite(
    svc: Any,
    session_key: str,
    *,
    operation: str,
) -> bool:
    """Fail closed before reset/compact when a durable transcript exists."""
    transcript = await _read_standalone_transcript(
        getattr(svc, "session_manager", None),
        session_key,
    )
    if transcript is None:
        console.print(
            f"[yellow]{operation} aborted: could not inspect the durable transcript.[/yellow]"
        )
        return False
    if not transcript:
        return True

    flush_service = getattr(svc, "flush_service", None)
    if flush_service is None:
        console.print(
            f"[yellow]{operation} aborted: flush service is unavailable and "
            "the durable transcript is non-empty.[/yellow]"
        )
        return False

    try:
        receipt = await flush_service.execute(
            transcript,
            session_key,
            agent_id="main",
            timeout=30.0,
            message_window=0,
            segment_mode="auto",
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]{operation} aborted: flush failed ({exc}).[/yellow]")
        return False

    if getattr(receipt, "mode", None) == "error":
        error = getattr(receipt, "error", None) or "unknown error"
        console.print(f"[yellow]{operation} aborted: flush failed ({error}).[/yellow]")
        return False
    return True


async def _standalone_repl(
    model: str | None,
    session_id: str | None,
    workspace: str | None = None,
    workspace_strict: bool | None = None,
    timeout: float | None = None,
) -> None:
    """Interactive REPL backed by TurnRunner (full tools, skills, session persistence)."""
    from opensquilla.cli.agent_cmd import _resolve_workspace_strict
    from opensquilla.gateway import build_services, build_turn_runner_from_services
    from opensquilla.gateway.routing import build_cli_route_envelope, tool_context_from_envelope

    svc = await build_services()
    session_manager = svc.session_manager
    if session_manager is None:
        raise RuntimeError("standalone chat requires session manager")
    session_key = session_id or f"agent:main:standalone:{uuid4().hex[:8]}"
    await session_manager.get_or_create(session_key, agent_id="main")
    active_workspace = workspace or getattr(svc.config, "workspace_dir", None)
    effective_workspace_strict = _resolve_workspace_strict(
        cli_value=workspace_strict,
        config_value=getattr(svc.config, "workspace_strict", None),
        entrypoint_default=bool(active_workspace),
    )

    def _build_tool_ctx(active_session_key: str) -> object:
        route_envelope = build_cli_route_envelope(
            session_key=active_session_key,
            agent_id="main",
            channel_id="cli:chat",
            sender_id=_cli_sender_id(),
            source_name="chat",
        )
        return tool_context_from_envelope(
            route_envelope,
            is_owner=True,
            workspace_dir=active_workspace,
            workspace_strict=effective_workspace_strict,
        )

    tool_ctx = _build_tool_ctx(session_key)
    state = ChatSessionState(session_key=session_key, model=model)

    turn_runner = build_turn_runner_from_services(svc)

    try:
        while True:
            try:
                user_input = await prompt_user(state.prompt_state().label)
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Goodbye.[/yellow]")
                break

            if user_input is None or is_exit_command(user_input):
                console.print("[yellow]Goodbye.[/yellow]")
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            if stripped.startswith("/"):
                route_match = match_standalone_slash_route(stripped)
                if route_match is None:
                    console.print("[red]Unknown command.[/red] [dim]Use /help.[/dim]")
                    continue

                route_name = route_match.name
                parts = route_match.parts

                if route_name == "help":
                    console.print(render_help_table())
                    continue
                if route_name == "new":
                    session_key, tool_ctx, state = await handle_standalone_new_command(
                        parts,
                        session_manager=session_manager,
                        build_tool_context=_build_tool_ctx,
                        model=model,
                    )
                    continue
                if route_name == "status":
                    handle_standalone_status_command(state)
                    continue
                if route_name == "models":
                    handle_standalone_models_command()
                    continue
                if route_name == "model":
                    updated_model = handle_standalone_model_command(parts, state)
                    if updated_model is not None:
                        model = updated_model
                    continue
                if route_name == "cost":
                    handle_standalone_cost_command(state)
                    continue
                if await handle_standalone_utility_route_command(
                    route_name,
                    stripped,
                    state,
                    config=svc.config,
                ):
                    continue
                if route_name == "clear":
                    await handle_standalone_clear_command(
                        state,
                        services=svc,
                        flush_before_rewrite=_flush_before_standalone_rewrite,
                    )
                    continue
                if route_name == "compact":
                    await handle_standalone_compact_command(
                        state,
                        services=svc,
                        model=model,
                        flush_before_rewrite=_flush_before_standalone_rewrite,
                        resolve_compaction_provider=_resolve_compaction_provider,
                    )
                    continue
                if route_name == "image":
                    await handle_standalone_image_command(
                        stripped,
                        parts,
                        state,
                        turn_runner=turn_runner,
                        tool_context=tool_ctx,
                        services=svc,
                        model=model,
                        timeout=timeout,
                        run_image_command=_handle_image_command_turnrunner,
                        image_prompt_from_command=_image_prompt_from_command,
                    )
                    continue
                if route_name == "path":
                    await handle_standalone_path_command(
                        stripped,
                        parts,
                        state,
                        turn_runner=turn_runner,
                        tool_context=tool_ctx,
                        services=svc,
                        model=model,
                        timeout=timeout,
                        stream_response=_stream_response_turnrunner,
                    )
                    continue
                console.print("[red]Unknown command.[/red] [dim]Use /help.[/dim]")
                continue

            result = await _stream_response_turnrunner(
                turn_runner,
                session_key,
                tool_ctx,
                user_input,
                model=model,
                svc=svc,
                timeout=timeout,
            )
            state.transcript.add("user", user_input)
            state.transcript.add("assistant", result.text)
            state.usage.add(result.usage)
    finally:
        await svc.close()


# ---------------------------------------------------------------------------
# Gateway mode (--gateway) — connect to running daemon via WebSocket
# ---------------------------------------------------------------------------


async def _gateway_chat(model: str | None, session_id: str | None) -> None:
    """Chat via gateway daemon. Full features: tools, skills, session persistence."""
    from opensquilla.cli.gateway_client import GatewayClient, GatewayRPCError

    client = GatewayClient()
    await client.connect()

    elevated_state: dict[str, str | None] = {"mode": None}

    try:
        if session_id:
            session_key = session_id
            console.print(f"[dim]Connected to gateway. Resuming session: {session_key}[/dim]")
            if model:
                console.print(
                    "[yellow]Note: --model is honored only at session creation; "
                    "ignored when resuming a session.[/yellow]"
                )
        else:
            session_key = await client.create_session(model=model)
            console.print(f"[dim]Connected to gateway. Session: {session_key}[/dim]")
            if model:
                console.print(f"[dim]Model: {model}[/dim]")
        state = ChatSessionState(session_key=session_key, model=model)

        # Interactive REPL via gateway
        console.print(
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
                user_input = await prompt_user(state.prompt_state().label)
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Goodbye.[/yellow]")
                break

            if user_input is None or is_exit_command(user_input):
                console.print("[yellow]Goodbye.[/yellow]")
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            if stripped.startswith("/"):
                try:
                    handled = await _handle_gateway_slash_command(
                        stripped, state, client, elevated_state
                    )
                except GatewayRPCError as exc:
                    console.print(error_panel(str(exc)))
                    continue
                if handled:
                    session_key = state.session_key
                    model = state.model
                    continue
                console.print("[red]Unknown command.[/red] [dim]Use /help.[/dim]")
                continue

            try:
                result = await _stream_response_gateway(
                    client, session_key, user_input, elevated_state
                )
            except GatewayRPCError as exc:
                console.print(error_panel(str(exc)))
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
    """Handle gateway-mode slash commands. Returns False for unknown commands."""

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


def _image_prompt_from_command(command: str) -> str:
    return _cli_attachments.image_prompt_from_command(command)


def _image_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
    prompt, attachments = _cli_attachments.image_prompt_and_attachments(command)
    if attachments:
        name = attachments[0].get("name") or "image"
        data = attachments[0].get("data") or ""
        console.print(f"[dim]Sending image: {name} ({len(data) // 1024}KB base64)[/dim]")
    return prompt, attachments


def _gateway_client_is_local(client: object) -> bool:
    local_attr = getattr(client, "is_local_gateway", None)
    if callable(local_attr):
        try:
            return bool(local_attr())
        except TypeError:
            return False
    if local_attr is not None:
        return bool(local_attr)

    try:
        from opensquilla.cli.gateway_client import gateway_base_is_local
    except Exception:  # pragma: no cover - defensive import fallback
        return False
    return gateway_base_is_local(getattr(client, "_http_base", None))


def _parse_path_command(command: str) -> tuple[Path, str]:
    return _cli_attachments.parse_path_command(command)


def _path_strategy_hint(path: Path) -> str:
    return _cli_attachments.path_strategy_hint(path)


def _path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, Any]]]:
    return _cli_attachments.path_prompt_and_attachments(command)


def _file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    return _cli_attachments.file_prompt_and_attachments(
        command, upload_callable=upload_callable
    )


async def _async_file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    return await _cli_attachments.async_file_prompt_and_attachments(
        command, upload_callable=upload_callable
    )


async def _forget_server_approvals(client: object | None, target: str | None = None) -> bool:
    """Clear intent cache. Returns True when the right cache actually changed.

    In gateway mode we must hit the server — the chat process's in-memory
    cache is disjoint from the gateway process's. If the RPC fails (e.g.
    older gateway without the ``exec.approval.forget`` handler), clearing
    locally is a no-op for the running agent, so the caller must be told.
    """
    if client is not None:
        from opensquilla.cli.gateway_client import GatewayClient

        assert isinstance(client, GatewayClient)
        try:
            await client.forget_approvals(target)
            return True
        except Exception as exc:
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


async def _handle_approvals_command(cmd: str, client: object | None = None) -> None:
    """Compatibility wrapper for approval queue diagnostics."""
    await handle_gateway_approvals_command(cmd, client)


async def _handle_forget_command(cmd: str, client: object | None = None) -> None:
    """Compatibility wrapper for approval-cache clearing."""
    await handle_gateway_forget_command(
        cmd,
        client=client,
        forget_server_approvals=_forget_server_approvals,
    )


async def _handle_elevated_command(
    cmd: str,
    state: dict[str, str | None],
    client: object | None = None,
) -> None:
    """Compatibility wrapper for the shared permissions interpreter."""

    await handle_permissions_command(
        cmd,
        state,
        client=client,
        forget_server_approvals=_forget_server_approvals,
    )


def _render_gateway_task_group_status(
    event_name: str,
    event: dict[str, Any],
    renderer: StreamingRenderer,
) -> None:
    chat_stream_presenters.render_gateway_task_group_status(event_name, event, renderer)


def _artifact_event_payload(event: Any) -> dict[str, Any]:
    return chat_stream_presenters.artifact_event_payload(event)


def _artifact_status_line(artifact: dict[str, Any]) -> str:
    return chat_stream_presenters.artifact_status_line(artifact)


def _render_artifact_status(artifact: dict[str, Any], renderer: StreamingRenderer) -> None:
    chat_stream_presenters.render_artifact_status(artifact, renderer)


async def _stream_response_gateway(
    client: _GatewayClientLike,
    session_key: str,
    message: str,
    elevated_state: dict[str, str | None] | None = None,
    attachments: list[dict] | None = None,
) -> TurnResult:
    """Stream response from gateway with Rich live display."""
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
                    _render_gateway_task_group_status(event_name, event, renderer)
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _local_approval_resolver() -> Callable[..., Awaitable[None]]:
    """Return a resolver that talks directly to the in-process approval queue.

    Used in --standalone mode where there is no gateway RPC to call.
    """

    async def _resolve(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        from opensquilla.application.approval_queue import get_approval_queue

        get_approval_queue().resolve(approval_id, approved, allow_always=allow_always)

    return _resolve


async def _stream_response_turnrunner(
    turn_runner: object,
    session_key: str,
    tool_ctx: object,
    message: str,
    model: str | None = None,
    svc: object = None,
    timeout: float | None = None,
) -> TurnResult:
    """Stream TurnRunner response with Rich live display (standalone mode)."""
    from opensquilla.engine.runtime import TurnRunner
    from opensquilla.engine.types import (
        ArtifactEvent,
        DoneEvent,
        ErrorEvent,
        RunHeartbeatEvent,
        TextDeltaEvent,
        ToolResultEvent,
        ToolUseStartEvent,
        WarningEvent,
    )
    from opensquilla.tools.types import ToolContext

    assert isinstance(turn_runner, TurnRunner)
    assert isinstance(tool_ctx, ToolContext)

    # Persist user message — TurnRunner only persists assistant responses
    session_manager = getattr(svc, "session_manager", None) if svc is not None else None
    if session_manager is not None:
        _persisted = await session_manager.append_message(
            session_key, role="user", content=message
        )
        if _persisted is not None and isinstance(_persisted.content, str):
            message = _persisted.content

    resolver = _local_approval_resolver()
    usage: UsageSummary | None = None
    cancelled = False
    artifacts: list[dict[str, Any]] = []

    with StreamingRenderer() as renderer:
        try:
            stream = turn_runner.run(
                message, session_key, tool_context=tool_ctx, model=model, timeout=timeout
            )
            async for event in _wrap_cli_turn_stream(stream, svc):
                if isinstance(event, TextDeltaEvent):
                    renderer.append_text(event.text)
                elif isinstance(event, RunHeartbeatEvent):
                    renderer.pulse()
                elif isinstance(event, ToolUseStartEvent):
                    renderer.tool_call(event.tool_name)
                elif isinstance(event, ToolResultEvent):
                    await _maybe_handle_approval(event.result, renderer, resolver)
                elif isinstance(event, ArtifactEvent):
                    artifact = _artifact_event_payload(event)
                    artifacts.append(artifact)
                    _render_artifact_status(artifact, renderer)
                elif isinstance(event, WarningEvent):
                    console.print(f"[yellow]{event.message}[/yellow]")
                elif isinstance(event, ErrorEvent):
                    message_text = _turn_stream_error_message(event)
                    renderer.error(message_text)
                    return TurnResult(
                        text=renderer.buffer,
                        usage=usage,
                        error=message_text,
                        artifacts=artifacts,
                    )
                elif isinstance(event, DoneEvent):
                    usage = UsageSummary.from_done_event(event)
        except (KeyboardInterrupt, asyncio.CancelledError):
            _clear_current_cancel()
            cancelled = True
        except TimeoutError as exc:
            message_text = _timeout_exception_message(exc)
            renderer.error(message_text)
            return TurnResult(text=renderer.buffer, error=message_text)
        renderer.finalize(usage, cancelled=cancelled)
    return TurnResult(
        text=renderer.buffer,
        usage=usage,
        cancelled=cancelled,
        artifacts=artifacts,
    )


async def _handle_image_command_turnrunner(
    turn_runner: object,
    session_key: str,
    tool_ctx: object,
    command: str,
    model: str | None = None,
    svc: object = None,
    timeout: float | None = None,
) -> TurnResult:
    """Handle /image <path> [prompt] — send image via TurnRunner attachments."""
    from opensquilla.engine.runtime import TurnRunner
    from opensquilla.engine.types import (
        DoneEvent,
        ErrorEvent,
        RunHeartbeatEvent,
        TextDeltaEvent,
        ToolUseStartEvent,
    )
    from opensquilla.tools.types import ToolContext

    assert isinstance(turn_runner, TurnRunner)
    assert isinstance(tool_ctx, ToolContext)

    try:
        prompt, attachments = _image_prompt_and_attachments(command)
    except ValueError as exc:
        console.print(error_panel(str(exc)))
        return TurnResult(error=str(exc))

    # Persist user message before running turn
    session_manager = getattr(svc, "session_manager", None) if svc is not None else None
    if session_manager is not None:
        _persisted = await session_manager.append_message(
            session_key, role="user", content=prompt
        )
        if _persisted is not None and isinstance(_persisted.content, str):
            prompt = _persisted.content

    usage: UsageSummary | None = None
    with StreamingRenderer() as renderer:
        try:
            stream = turn_runner.run(
                prompt,
                session_key,
                tool_context=tool_ctx,
                model=model,
                attachments=attachments,
                timeout=timeout,
            )
            async for event in _wrap_cli_turn_stream(stream, svc):
                if isinstance(event, TextDeltaEvent):
                    renderer.append_text(event.text)
                elif isinstance(event, RunHeartbeatEvent):
                    renderer.pulse()
                elif isinstance(event, ToolUseStartEvent):
                    renderer.tool_call(event.tool_name)
                elif isinstance(event, ErrorEvent):
                    message_text = _turn_stream_error_message(event)
                    renderer.error(message_text)
                    return TurnResult(text=renderer.buffer, usage=usage, error=message_text)
                elif isinstance(event, DoneEvent):
                    usage = UsageSummary.from_done_event(event)
        except TimeoutError as exc:
            message_text = _timeout_exception_message(exc)
            renderer.error(message_text)
            return TurnResult(text=renderer.buffer, error=message_text)
        renderer.finalize(usage)
    return TurnResult(text=renderer.buffer, usage=usage)
