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
from typing import Any, Protocol, cast

from rich.table import Table

import opensquilla.cli.tui.adapters.input_bridge as _input_bridge
from opensquilla.cli.chat.session_state import ChatSessionState, messages_to_markdown
from opensquilla.cli.chat.turn import TurnResult
from opensquilla.cli.tui.adapters.commands import render_help_table
from opensquilla.cli.tui.backend.contracts import TuiOutputHandle
from opensquilla.cli.ui import ACCENT, ACCENT_HEADER, console, error_panel
from opensquilla.engine.commands import Surface

_CLI_ALLOWED_FILE_MIMES = _input_bridge.CLI_ALLOWED_FILE_MIMES
_CLI_INLINE_THRESHOLD_BYTES = _input_bridge.CLI_INLINE_THRESHOLD_BYTES
_PATH_REMOTE_GATEWAY_MESSAGE = _input_bridge.PATH_REMOTE_GATEWAY_MESSAGE

GATEWAY_SLASH_HANDLER_WORDS = frozenset(
    {
        "/approvals",
        "/clear",
        "/compact",
        "/cmp",
        "/cost",
        "/delete",
        "/elevated",
        "/exit",
        "/file",
        "/forget",
        "/help",
        "/image",
        "/meta",
        "/model",
        "/models",
        "/new",
        "/path",
        "/permissions",
        "/quit",
        "/reset",
        "/resume",
        "/session",
        "/sessions",
        "/save",
        "/status",
        "/theme",
        "/usage",
    }
)


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
        allow_always: bool = False,
    ) -> Any: ...

    async def abort_session(self, key: str) -> dict[str, Any]: ...


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


async def handle_gateway_slash_command(
    cmd: str,
    context: GatewaySlashContext,
) -> bool:
    """Handle gateway-mode slash commands. Returns False for unknown commands."""

    state = context.state
    client = context.client
    elevated_state = context.elevated_state
    tui_output = context.tui_output
    stream = context.stream_response or stream_response_gateway

    if cmd == "/help":
        console.print(render_help_table(Surface.CLI_GATEWAY))
        return True

    if _slash_parts(cmd, "/theme"):
        from opensquilla.cli.tui.opentui.themes import handle_theme_command  # noqa: PLC0415

        await handle_theme_command(cmd, tui_output)
        return True

    if parts := _slash_parts(cmd, "/new"):
        title = parts[1].strip() if len(parts) > 1 else None
        session_key = await client.create_session(model=state.model, display_name=title)
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
        payload = await client.delete_sessions([session_key])
        errors = [str(item) for item in payload.get("errors") or []]
        deleted = [str(item) for item in payload.get("deleted") or []]
        if errors:
            console.print(error_panel("\n".join(errors), title="Delete failed"))
        elif deleted:
            console.print(f"[yellow]Deleted session:[/yellow] {deleted[0]}")
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
                f"{before} -> {after} tokens, {remaining} remaining, {source}"
                if before or after
                else f"summary {payload.get('summary_len', 0)} chars"
            )
            console.print(f"[{ACCENT}]compacted[/] [dim]{token_stats}[/dim]")
        else:
            console.print(
                f"[{ACCENT}]compact skipped[/] "
                "[dim]already within context budget; no compact was applied[/dim]"
            )
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
        state.transcript.add("user", prompt)
        state.transcript.add("assistant", result.text)
        state.usage.apply(result.usage)
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
        state.transcript.add("user", prompt)
        state.transcript.add("assistant", result.text)
        state.usage.apply(result.usage)
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
        state.transcript.add("user", prompt)
        state.transcript.add("assistant", result.text)
        state.usage.apply(result.usage)
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
        state.transcript.add("user", prompt)
        state.transcript.add("assistant", result.text)
        state.usage.apply(result.usage)
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


async def _handle_tool_compress_command(
    cmd: str,
    *,
    config: object | None = None,
    client: object | None = None,
) -> None:
    parts = cmd.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"
    aliases = {"on": "truncate", "trim": "truncate", "summary": "summarize"}
    mode_arg = aliases.get(arg, arg)
    modes = {"off", "truncate", "summarize", "tokenjuice", "status"}
    if len(parts) > 2 or mode_arg not in modes:
        console.print("[red]Usage: /tool-compress [off|truncate|summarize|tokenjuice|status][/red]")
        return

    enabled_path = "agent_token_saving.tool_result_compression_enabled"
    mode_path = "agent_token_saving.tool_result_compression_mode"
    model_path = "agent_token_saving.tool_result_compression_summary_model"
    if client is not None:
        from opensquilla.cli.gateway_client import GatewayClient

        assert isinstance(client, GatewayClient)
        if mode_arg == "status":
            mode = await client.get_config(mode_path)
            enabled = bool(await client.get_config(enabled_path))
            model = await client.get_config(model_path)
            mode = mode if mode in {"off", "truncate", "summarize", "tokenjuice"} else None
            resolved_mode = str(mode or ("truncate" if enabled else "off"))
        else:
            resolved_mode = mode_arg
            await client.patch_config_safe(
                {
                    mode_path: resolved_mode,
                    enabled_path: resolved_mode != "off",
                }
            )
            model = await client.get_config(model_path) if resolved_mode == "summarize" else None
    else:
        cfg = getattr(config, "agent_token_saving", None)
        if cfg is None:
            console.print("[yellow]Tool result compression config is unavailable.[/yellow]")
            return
        if mode_arg == "status":
            mode = getattr(cfg, "tool_result_compression_mode", None)
            enabled = bool(getattr(cfg, "tool_result_compression_enabled", True))
            model = getattr(cfg, "tool_result_compression_summary_model", None)
            if mode in {"off", "truncate", "summarize", "tokenjuice"}:
                resolved_mode = str(mode)
            else:
                resolved_mode = "truncate" if enabled else "off"
        else:
            resolved_mode = mode_arg
            setattr(cfg, "tool_result_compression_mode", resolved_mode)
            setattr(cfg, "tool_result_compression_enabled", resolved_mode != "off")
            model = getattr(cfg, "tool_result_compression_summary_model", None)

    model_suffix = f" [dim]model={model}[/dim]" if resolved_mode == "summarize" and model else ""
    console.print(f"[{ACCENT}]tool result compression:[/] {resolved_mode.upper()}{model_suffix}")


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
    cmd: str, state: ChatSessionState, client: object
) -> None:
    from opensquilla.cli.gateway_client import GatewayClient

    assert isinstance(client, GatewayClient)
    parts = cmd.split(maxsplit=1)
    if len(parts) > 1:
        target = Path(parts[1]).expanduser()
    else:
        suffix = state.session_key.replace(":", "-")
        target = Path(f"opensquilla-chat-{suffix}.md")

    history = await client.session_history(state.session_key, limit=1000)
    messages = history.get("messages") or []
    markdown = messages_to_markdown(messages) if isinstance(messages, list) else ""
    if not markdown.strip():
        markdown = state.transcript.to_markdown()
    target.write_text(markdown, encoding="utf-8")
    console.print(f"[green]Saved transcript:[/green] {target}")


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


async def _forget_server_approvals(client: object | None, target: str | None = None) -> bool:
    """Clear intent cache. Returns True when the right cache actually changed."""
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

    from opensquilla.sandbox.intent_cache import get_intent_cache

    cache = get_intent_cache()
    if target:
        cache.forget(f"rm {target}")
        cache.forget(target)
    else:
        cache.clear()
    return True


async def _handle_approvals_command(cmd: str, client: object | None = None) -> None:
    """Diagnostic view / reset for the approval queue."""
    parts = cmd.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"

    if client is None:
        from opensquilla.gateway.approval_queue import get_approval_queue
        from opensquilla.sandbox.intent_cache import get_intent_cache

        queue = get_approval_queue()
        cache = get_intent_cache()
        if arg == "reset":
            queue.set_settings(mode="prompt")
            cache.clear()
            console.print(f"[{ACCENT}]Approval mode reset to prompt; cache cleared.[/]")
            return
        entries = [
            f"  [dim]{scope}[/dim] {k}:{t}"
            for (k, t), (_exp, scope) in cache._entries.items()  # noqa: SLF001
        ]
        console.print(f"[{ACCENT}]mode:[/] {queue.get_settings().mode}")
        console.print(f"[{ACCENT}]cached intents ({len(entries)}):[/]")
        for line in entries or ["  [dim](none)[/dim]"]:
            console.print(line)
        return

    from opensquilla.cli.gateway_client import GatewayClient

    assert isinstance(client, GatewayClient)

    if arg == "reset":
        try:
            await client.set_approval_mode("prompt")
            await client.forget_approvals()
            console.print(f"[{ACCENT}]Approval mode reset to prompt; server cache cleared.[/]")
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
    raw_entries = snap.get("intent_cache_entries")
    approval_entries = (
        cast(list[dict[str, Any]], raw_entries) if isinstance(raw_entries, list) else []
    )
    console.print(f"[{ACCENT}]cached intents ({len(approval_entries)}):[/]")
    if not approval_entries:
        console.print("  [dim](none)[/dim]")
    for e in approval_entries:
        console.print(f"  [dim]{e.get('scope')}[/dim] {e.get('kind')}:{e.get('target')}")


async def _handle_forget_command(cmd: str, client: object | None = None) -> None:
    """Clear cached approvals. ``/forget`` wipes all; ``/forget <path>`` wipes one."""
    parts = cmd.split(maxsplit=1)
    if len(parts) < 2:
        if await _forget_server_approvals(client):
            console.print(
                f"[{ACCENT}]All cached approvals cleared.[/] Future destructive "
                "ops will prompt again."
            )
        return
    target = parts[1].strip()
    if await _forget_server_approvals(client, target):
        console.print(
            f"[{ACCENT}]Cached approval for[/] {target} [{ACCENT}]cleared[/] (if one existed)."
        )


async def _handle_elevated_command(
    cmd: str,
    state: dict[str, str | None],
    client: object | None = None,
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
            from opensquilla.cli.gateway_client import GatewayClient

            assert isinstance(client, GatewayClient)
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
    revoked_suffix = (
        "Cached approvals revoked."
        if cleared
        else "[bold red]WARNING: cached approvals NOT revoked (see error above).[/bold red]"
    )

    if arg == "off":
        console.print(
            f"[{ACCENT}]permissions: off[/] - exec runs inside the sandbox. "
            f"Queue mode reset to prompt. {revoked_suffix}{queue_mode_reset_warning}"
        )
    elif arg == "on":
        console.print(
            f"[yellow]permissions: on[/yellow] - exec on host, approvals required. "
            f"{revoked_suffix}"
        )
    elif arg == "bypass":
        console.print(
            f"[red]permissions: bypass[/red] - exec on host, approvals auto-granted. "
            f"Sensitive paths (~/.ssh, /etc, ...) still hard-blocked. {revoked_suffix}"
        )
    else:
        console.print(
            f"[red]permissions: full[/red] - exec on host, approvals skipped, "
            f"sensitive paths bypassed. Trusted operators only. {revoked_suffix}"
        )
