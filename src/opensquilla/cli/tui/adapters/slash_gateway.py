"""Gateway slash-command adapter for the chat REPL backend.

This module owns gateway-mode slash command dispatch. It is intentionally
independent from raw frontend and chat application objects: callers pass
typed session state, a gateway client, and an optional TUI output handle.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from rich.table import Table

import opensquilla.cli.tui.adapters.input_bridge as _input_bridge
from opensquilla.cli.chat.session_state import ChatSessionState, messages_to_markdown
from opensquilla.cli.chat.turn import TurnResult
from opensquilla.cli.gateway_client import GatewayRPCError, session_history_all
from opensquilla.cli.tui.adapters.commands import render_help_table
from opensquilla.cli.tui.adapters.slash_common import (
    compact_skipped_line,
    compact_success_line,
    compact_summary_stats,
    compact_token_stats,
    dispatch_theme_command,
    record_turn,
    registry_handler_words,
    resolve_transcript_target,
    save_transcript_markdown,
)
from opensquilla.cli.tui.adapters.slash_common import (
    slash_parts as _slash_parts,
)
from opensquilla.cli.tui.adapters.slash_common import (
    slash_parts_any as _slash_parts_any,
)
from opensquilla.cli.tui.backend.contracts import TuiOutputHandle
from opensquilla.cli.ui import ACCENT, ACCENT_HEADER, console, error_panel
from opensquilla.engine.commands import Surface

_CLI_ALLOWED_FILE_MIMES = _input_bridge.CLI_ALLOWED_FILE_MIMES
_CLI_INLINE_THRESHOLD_BYTES = _input_bridge.CLI_INLINE_THRESHOLD_BYTES
_PATH_REMOTE_GATEWAY_MESSAGE = _input_bridge.PATH_REMOTE_GATEWAY_MESSAGE

# Derived from the engine registry so a new slash command only has to be
# declared once; the dispatch chain below is pinned to this set by tests.
GATEWAY_SLASH_HANDLER_WORDS = registry_handler_words(Surface.CLI_GATEWAY)


class GatewayClientLike(Protocol):
    async def call(self, method: str, params: dict | None = None) -> Any: ...

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
        choice: str | None = None,
    ) -> Any: ...

    async def abort_session(self, key: str) -> dict[str, Any]: ...

    async def session_history(
        self,
        session_key: str,
        limit: int = 1000,
        *,
        before: str | None = None,
        after: str | None = None,
        include_canonical: bool | None = None,
        include_summaries: bool | None = None,
    ) -> dict[str, Any]: ...

    async def forget_approvals(self, target: str | None = None) -> dict[str, Any]: ...

    async def approvals_snapshot(self) -> dict[str, Any]: ...

    async def set_approval_mode(self, mode: str) -> dict[str, Any]: ...


class GatewayStreamResponse(Protocol):
    async def __call__(
        self,
        client: GatewayClientLike,
        session_key: str,
        message: str,
        elevated_state: dict[str, str | None] | None = None,
        attachments: list[dict] | None = None,
        *,
        tui_output: TuiOutputHandle | None = None,
    ) -> TurnResult: ...


async def stream_response_gateway(
    client: GatewayClientLike,
    session_key: str,
    message: str,
    elevated_state: dict[str, str | None] | None = None,
    attachments: list[dict] | None = None,
    *,
    tui_output: TuiOutputHandle | None = None,
) -> TurnResult:
    del client, session_key, message, elevated_state, attachments, tui_output
    raise RuntimeError("gateway streaming dependency was not configured")


@dataclass
class GatewaySlashContext:
    state: ChatSessionState
    client: GatewayClientLike
    elevated_state: dict[str, str | None]
    tui_output: TuiOutputHandle | None = None
    stream_response: GatewayStreamResponse | None = None
    # The model the user explicitly requested (--model at launch or the last
    # /model choice). Kept apart from state.model, which tracks the model that
    # last ran and may be a router pick that must not leak into session pins.
    requested_model: str | None = None


async def handle_gateway_slash_command(
    cmd: str,
    context: GatewaySlashContext,
) -> bool:
    """Handle gateway-mode slash commands.

    Returns ``True`` when the command was handled (including handled failures
    such as a lost gateway connection) and ``False`` for unknown commands so
    the runtime can render its unknown-command notice. Exit commands are owned
    by the runtime loop, which intercepts them before slash dispatch.
    """
    try:
        return await _dispatch_gateway_slash_command(cmd, context)
    except (ConnectionError, OSError) as exc:
        console.print(error_panel(str(exc), title="Gateway command failed"))
        console.print(
            "[dim]Check the gateway with[/dim] [bold]opensquilla gateway status[/bold] "
            "[dim]and start it with[/dim] [bold]opensquilla gateway run[/bold] "
            "[dim]if it is down, then retry the command.[/dim]"
        )
        return True


async def _requested_session_model(context: GatewaySlashContext) -> str | None:
    """Return the explicitly requested model for new sessions, if any.

    ``state.model`` is display bookkeeping: after a routed turn it holds the
    router's pick, and pinning a fresh session to it would silently replace
    routing. The explicit request is the in-context ``/model`` choice or,
    failing that, the model stored on the current session (set from
    ``--model`` at creation or an earlier ``/model`` patch).
    """
    if context.requested_model:
        return context.requested_model
    try:
        payload = await asyncio.wait_for(
            context.client.resolve_session(context.state.session_key),
            timeout=2.0,
        )
    except Exception:  # noqa: BLE001 - best-effort read; default to routing
        # The read itself failed (slow/erroring gateway), which is different
        # from "no pin stored". Warn so the user is not surprised that the new
        # session falls back to the router default, and can re-pin explicitly.
        console.print(
            "[yellow]Could not read the current session's model pin; the new "
            "session will use the router default. Re-pin with[/yellow] "
            "[bold]/model <id>[/bold][yellow] if needed.[/yellow]"
        )
        return None
    model = payload.get("model")
    return str(model) if model else None


async def _dispatch_gateway_slash_command(
    cmd: str,
    context: GatewaySlashContext,
) -> bool:
    state = context.state
    client = context.client
    elevated_state = context.elevated_state
    tui_output = context.tui_output
    stream = context.stream_response or stream_response_gateway

    if cmd == "/help":
        console.print(render_help_table(Surface.CLI_GATEWAY))
        return True

    if _slash_parts(cmd, "/theme"):
        await dispatch_theme_command(cmd, tui_output)
        return True

    if parts := _slash_parts(cmd, "/new"):
        title = parts[1].strip() if len(parts) > 1 else None
        requested_model = await _requested_session_model(context)
        session_key = await client.create_session(model=requested_model, display_name=title)
        state.session_key = session_key
        state.transcript.clear()
        state.usage.reset()
        try:
            _resolved = await asyncio.wait_for(client.resolve_session(session_key), timeout=2.0)
            state.model = _resolved.get("model") or state.model
        except Exception:  # noqa: BLE001 - network/timeout; non-fatal
            pass
        label = f" ({title})" if title else ""
        console.print(f"[green]Started new session{label}:[/green] {session_key}")
        return True

    if cmd in {"/status", "/session"}:
        console.print(
            f"[{ACCENT}]session[/] [dim]{state.session_key}[/dim]\n"
            f"[{ACCENT}]model[/] [dim]{state.model or 'default'}[/dim]\n"
            f"[{ACCENT}]permissions[/] [dim]{state.elevated or 'normal'}[/dim]"
        )
        return True

    if parts := _slash_parts(cmd, "/sessions"):
        limit = 10
        if len(parts) > 1:
            try:
                limit = int(parts[1])
            except ValueError:
                console.print("[red]Usage: /sessions [limit][/red]")
                return True
        payload = await client.list_sessions(limit=limit)
        _print_sessions_table(payload.get("sessions", []))
        return True

    if parts := _slash_parts(cmd, "/resume"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /resume <id>[/red]")
            return True
        target = cmd.split(maxsplit=1)[1].strip()
        payload = await client.resolve_session(target)
        state.session_key = payload.get("session_key") or payload.get("key") or target
        state.model = payload.get("model") or state.model
        state.transcript.clear()
        state.usage.reset()
        console.print(f"[green]Resumed session:[/green] {state.session_key}")
        return True

    if parts := _slash_parts(cmd, "/delete"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /delete <id>[/red]")
            return True
        target = cmd.split(maxsplit=1)[1].strip()
        resolved = await client.resolve_session(target)
        session_key = resolved.get("session_key") or resolved.get("key") or target
        deleting_active = session_key == state.session_key
        payload = await client.delete_sessions([session_key])
        errors = [str(item) for item in payload.get("errors") or []]
        deleted = [str(item) for item in payload.get("deleted") or []]
        if errors:
            console.print(error_panel("\n".join(errors), title="Delete failed"))
        elif deleted:
            console.print(f"[yellow]Deleted session:[/yellow] {deleted[0]}")
            if deleting_active:
                # The REPL must not keep sending turns to a deleted key; move
                # to a fresh session that keeps the user's explicit model pin.
                replacement_model = (
                    context.requested_model or resolved.get("model") or None
                )
                new_key = await client.create_session(model=replacement_model)
                state.session_key = new_key
                state.transcript.clear()
                state.usage.reset()
                # Refresh the display model like /new does, so /status and the
                # HUD reflect the replacement session's actual pin instead of
                # the deleted session's stale model.
                try:
                    _resolved = await asyncio.wait_for(
                        client.resolve_session(new_key), timeout=2.0
                    )
                    state.model = _resolved.get("model") or replacement_model or state.model
                except Exception:  # noqa: BLE001 - network/timeout; non-fatal
                    state.model = replacement_model or state.model
                console.print(
                    "[yellow]The deleted session was active; switched to a new "
                    f"session:[/yellow] {new_key}"
                )
        else:
            console.print(error_panel("No session was deleted.", title="Delete failed"))
        return True

    if cmd in {"/clear", "/reset"}:
        await client.reset_session(state.session_key)
        state.transcript.clear()
        state.usage.reset()
        console.print(f"[{ACCENT}]cleared[/] [dim]{state.session_key}[/dim]")
        return True

    if cmd in {"/compact", "/cmp"}:
        console.print(f"[{ACCENT}]compacting context...[/]")
        try:
            payload = await client.compact_session(state.session_key)
        except Exception as exc:  # noqa: BLE001 - keep interactive chat alive.
            console.print(f"[red]compact failed: {exc}[/red]")
            return True
        if payload.get("compacted"):
            before = int(payload.get("tokens_before") or 0)
            after = int(payload.get("tokens_after") or 0)
            remaining = int(payload.get("remaining_budget_tokens") or 0)
            source = payload.get("summary_source") or "unknown"
            token_stats = (
                compact_token_stats(before, after, remaining, source)
                if before or after
                else compact_summary_stats(payload.get("summary_len", 0))
            )
            console.print(compact_success_line(token_stats))
        else:
            console.print(compact_skipped_line())
        return True

    if parts := _slash_parts(cmd, "/models"):
        if len(parts) > 1:
            console.print("[red]Usage: /models[/red]")
            return True
        models = await client.list_models()
        _print_models_table(models)
        return True

    if parts := _slash_parts(cmd, "/model"):
        if len(parts) == 1:
            console.print(f"[dim]model={state.model or 'default'}[/dim]")
        else:
            new_model = parts[1].strip()
            await client.patch_session(state.session_key, model=new_model)
            state.model = new_model
            context.requested_model = new_model
            console.print(f"[green]model:[/green] {new_model}")
        return True

    if cmd == "/cost":
        console.print(state.usage.render())
        return True

    if cmd == "/usage":
        payload = await client.usage_status()
        console.print(
            "[dim]aggregate usage: "
            f"{payload.get('totalTokens', 0):,} tok · "
            f"${float(payload.get('totalCostUsd', 0.0) or 0.0):.6f}[/dim]"
        )
        return True

    if _slash_parts(cmd, "/save"):
        await _save_gateway_transcript_command(cmd, state, client)
        return True

    if parts := _slash_parts(cmd, "/image"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /image <path> [prompt][/red]")
            return True
        try:
            prompt, attachments = _image_prompt_and_attachments(cmd)
        except ValueError as exc:
            console.print(error_panel(str(exc)))
            return True
        result = await stream(
            client,
            state.session_key,
            prompt,
            elevated_state,
            attachments=attachments,
            tui_output=tui_output,
        )
        record_turn(state, prompt, result)
        return True

    if parts := _slash_parts(cmd, "/meta"):
        name = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            payload = await client.call("meta.list", {})
            _print_meta_skills_table(payload)
            return True
        run_result = await client.call("meta.run", {"name": name, "sessionKey": state.session_key})
        if not (isinstance(run_result, dict) and run_result.get("ok")):
            error = ""
            if isinstance(run_result, dict):
                error = str(run_result.get("error") or "")
            console.print(error_panel(error or f"Could not run meta-skill {name!r}."))
            return True
        prompt = f"/meta {name}"
        result = await stream(
            client,
            state.session_key,
            prompt,
            elevated_state,
            tui_output=tui_output,
        )
        record_turn(state, prompt, result)
        return True

    if parts := _slash_parts(cmd, "/path"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /path <path> [prompt][/red]")
            return True
        if not _gateway_client_is_local(client):
            console.print(error_panel(_PATH_REMOTE_GATEWAY_MESSAGE))
            return True
        try:
            prompt, attachments = path_prompt_and_attachments(cmd)
        except ValueError as exc:
            console.print(error_panel(str(exc)))
            return True
        result = await stream(
            client,
            state.session_key,
            prompt,
            elevated_state,
            attachments=attachments,
            tui_output=tui_output,
        )
        record_turn(state, prompt, result)
        return True

    if parts := _slash_parts(cmd, "/file"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /file <path> [prompt][/red]")
            return True

        async def _bridge_upload(path: Path, mime: str, name: str) -> str:
            return await client.upload_file(path, mime, name)

        try:
            prompt, attachments = await _async_file_prompt_and_attachments(
                cmd, upload_callable=_bridge_upload
            )
        except ValueError as exc:
            console.print(error_panel(str(exc)))
            return True
        result = await stream(
            client,
            state.session_key,
            prompt,
            elevated_state,
            attachments=attachments,
            tui_output=tui_output,
        )
        record_turn(state, prompt, result)
        return True

    if _slash_parts_any(cmd, "/permissions", "/elevated"):
        await _handle_elevated_command(cmd, elevated_state, client)
        state.elevated = elevated_state.get("mode")
        return True

    if cmd == "/forget" or cmd.startswith("/forget "):
        await _handle_forget_command(cmd, client)
        return True

    if cmd == "/approvals" or cmd.startswith("/approvals "):
        await _handle_approvals_command(cmd, client)
        return True

    return False


def _print_sessions_table(rows: list[dict[str, Any]]) -> None:
    table = Table(title="Sessions", show_header=True, header_style=ACCENT_HEADER)
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Model")
    table.add_column("Messages", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("key") or row.get("session_key") or ""),
            str(row.get("status") or ""),
            str(row.get("model") or ""),
            str(row.get("message_count") or row.get("entry_count") or 0),
        )
    console.print(table)


def _print_meta_skills_table(payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("disabled"):
        console.print("[dim]meta-skills are disabled.[/dim]")
        return
    skills = payload.get("skills")
    rows = (
        [skill for skill in skills if isinstance(skill, dict)]
        if isinstance(skills, list)
        else []
    )
    if not rows:
        console.print("[dim]No meta-skills available.[/dim]")
        return
    table = Table(title="Meta-skills", show_header=True, header_style=ACCENT_HEADER)
    table.add_column("Name")
    table.add_column("Description")
    for row in rows:
        table.add_row(
            str(row.get("name") or ""),
            str(row.get("description") or ""),
        )
    console.print(table)


def _print_models_table(rows: list[dict[str, Any]]) -> None:
    table = Table(title="Models", show_header=True, header_style=ACCENT_HEADER)
    table.add_column("ID")
    table.add_column("Provider")
    table.add_column("Context", justify="right")
    table.add_column("Capabilities")
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("provider") or ""),
            str(row.get("contextWindow") or ""),
            ", ".join(str(v) for v in row.get("capabilities") or []),
        )
    console.print(table)


async def _save_gateway_transcript_command(
    cmd: str, state: ChatSessionState, client: GatewayClientLike
) -> None:
    target = resolve_transcript_target(cmd, state.session_key)
    try:
        history = await session_history_all(client.session_history, state.session_key)
    except GatewayRPCError as exc:
        console.print(error_panel(str(exc), title="Could not save transcript"))
        return
    messages = history.get("messages") or []
    markdown = messages_to_markdown(messages) if isinstance(messages, list) else ""
    if not markdown.strip():
        markdown = state.transcript.to_markdown()
    save_transcript_markdown(
        target,
        markdown,
        output_console=console,
        error_panel_factory=error_panel,
    )


def _image_prompt_from_command(command: str) -> str:
    return _input_bridge.image_prompt_from_command(command)


def _image_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
    return _input_bridge.image_prompt_and_attachments(command, output_console=console)


def _gateway_client_is_local(client: object) -> bool:
    return _input_bridge.gateway_client_is_local(client)


def _parse_path_command(command: str) -> tuple[Path, str]:
    return _input_bridge.parse_path_command(command)


def _path_strategy_hint(path: Path) -> str:
    return _input_bridge.path_strategy_hint(path)


def path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, Any]]]:
    return _input_bridge.path_prompt_and_attachments(command)


def _path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, Any]]]:
    return path_prompt_and_attachments(command)


def _file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    return _input_bridge.file_prompt_and_attachments(command, upload_callable=upload_callable)


async def _async_file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    return await _input_bridge.async_file_prompt_and_attachments(
        command, upload_callable=upload_callable
    )


async def _forget_server_approvals(
    client: GatewayClientLike | None, target: str | None = None
) -> bool:
    """Compatibility no-op for the removed intent approval cache."""
    if client is not None:
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

    _ = target
    return True


async def _handle_approvals_command(
    cmd: str, client: GatewayClientLike | None = None
) -> None:
    """Diagnostic view / reset for the approval queue."""
    parts = cmd.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"

    if client is None:
        from opensquilla.gateway.approval_queue import get_approval_queue

        queue = get_approval_queue()
        if arg == "reset":
            queue.set_settings(mode="prompt")
            console.print(f"[{ACCENT}]Approval mode reset to prompt.[/]")
            return
        console.print(f"[{ACCENT}]mode:[/] {queue.get_settings().mode}")
        return

    if arg == "reset":
        try:
            await client.set_approval_mode("prompt")
            await client.forget_approvals()
            console.print(f"[{ACCENT}]Approval mode reset to prompt.[/]")
        except Exception as exc:
            console.print(f"[red]Failed to reset approvals:[/red] {type(exc).__name__}: {exc}")
            console.print("[red]Restart the gateway if this is an older build.[/red]")
        return

    try:
        snap = await client.approvals_snapshot()
    except Exception as exc:
        console.print(f"[red]Failed to query approvals:[/red] {type(exc).__name__}: {exc}")
        console.print("[red]Older gateway? Restart it.[/red]")
        return
    console.print(f"[{ACCENT}]mode:[/] {snap.get('mode')}")


async def _handle_forget_command(
    cmd: str, client: GatewayClientLike | None = None
) -> None:
    """Compatibility no-op for removed approval cache."""
    parts = cmd.split(maxsplit=1)
    if len(parts) < 2:
        if await _forget_server_approvals(client):
            console.print(f"[{ACCENT}]Approval cache is inactive.[/]")
        return
    target = parts[1].strip()
    if await _forget_server_approvals(client, target):
        console.print(f"[{ACCENT}]Approval cache is inactive for[/] {target}.")


async def _handle_elevated_command(
    cmd: str,
    state: dict[str, str | None],
    client: GatewayClientLike | None = None,
) -> None:
    """Interpret ``/permissions`` / ``/elevated`` and mutate state in place."""
    parts = cmd.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"
    if arg == "status":
        current = state["mode"] or "off (session override cleared; configured default applies)"
        console.print(f"[{ACCENT}]permissions:[/] {current}")
        return

    known = {"off": None, "on": "on", "bypass": "bypass", "full": "full"}
    if arg not in known:
        console.print(f"[red]Unknown permissions mode:[/red] {arg}")
        console.print("Usage: /permissions on | off | bypass | full | status")
        return

    state["mode"] = known[arg]
    cleared = await _forget_server_approvals(client)
    queue_mode_reset_warning = ""
    if arg == "off":
        if client is not None:
            try:
                await client.set_approval_mode("prompt")
            except Exception as exc:
                queue_mode_reset_warning = (
                    f" [bold red]WARNING: queue mode not reset "
                    f"({type(exc).__name__}: {exc}).[/bold red]"
                )
        else:
            from opensquilla.gateway.approval_queue import get_approval_queue

            get_approval_queue().set_settings(mode="prompt")
    cache_suffix = (
        ""
        if cleared
        else " [bold red]WARNING: legacy approval cache status not confirmed "
        "(see error above).[/bold red]"
    )

    if arg == "off":
        console.print(
            f"[{ACCENT}]permissions: off[/] - exec runs inside the sandbox. "
            f"Queue mode reset to prompt.{cache_suffix}{queue_mode_reset_warning}"
        )
    elif arg == "on":
        console.print(
            f"[yellow]permissions: on[/yellow] - legacy alias for Managed Execution; "
            f"approvals still apply. "
            f"{cache_suffix}"
        )
    elif arg == "bypass":
        console.print(
            f"[red]permissions: bypass[/red] - legacy alias for Managed Execution "
            f"with fewer prompts; host access is not granted.{cache_suffix}"
        )
    else:
        console.print(
            f"[red]permissions: full[/red] - exec on host, approvals skipped, "
            f"sensitive paths bypassed. Trusted operators only.{cache_suffix}"
        )
