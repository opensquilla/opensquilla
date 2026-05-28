"""REPL launch bridge for interactive chat entrypoints.

This module owns terminal launch preparation and first-screen chat presentation
so CLI commands can stay focused on Typer option wiring and backend callbacks.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable, Coroutine
from typing import Any

import typer
from rich.panel import Panel

from opensquilla.cli.chat.launch import ChatCommandLaunchOverrides, ChatCommandRequest
from opensquilla.cli.ui import ACCENT, console

ChatRunner = Callable[..., Coroutine[Any, Any, None]]


def quiet_logs_for_interactive_chat() -> None:
    """Filter chat-process log output to WARNING+ during the interactive REPL."""
    import logging  # noqa: PLC0415 - keep launch imports light until chat starts

    import structlog  # noqa: PLC0415

    level_name = os.environ.get("OPENSQUILLA_LOG_LEVEL", "warning").strip().upper()
    level = getattr(logging, level_name, logging.WARNING)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )
    logging.getLogger().setLevel(level)
    try:
        import jieba  # type: ignore[import-untyped]  # noqa: F401, PLC0415
    except ImportError:
        pass
    else:
        jieba_logger = logging.getLogger("jieba")
        jieba_logger.setLevel(level)
        jieba_logger.propagate = False
        for handler in list(jieba_logger.handlers):
            jieba_logger.removeHandler(handler)


def clear_screen_for_interactive_chat(
    *,
    output_console: Any | None = None,
) -> None:
    """Start the persistent chat surface on a clean terminal page."""
    active_console = console if output_console is None else output_console
    if active_console.is_terminal:
        active_console.clear()


def prepare_interactive_chat(
    *,
    input_stream: Any | None = None,
    output_console: Any | None = None,
) -> None:
    stream = sys.stdin if input_stream is None else input_stream
    active_console = console if output_console is None else output_console
    if not stream.isatty() or not active_console.is_terminal:
        typer.echo(
            "opensquilla chat is interactive; use `opensquilla agent -m '...'` for non-TTY.",
            err=True,
        )
        raise typer.Exit(2)
    quiet_logs_for_interactive_chat()
    clear_screen_for_interactive_chat(output_console=active_console)


def launch_chat(
    *,
    model: str,
    session_id: str,
    standalone: bool,
    workspace: str,
    workspace_strict: bool | None,
    timeout: float | None,
    standalone_runner: ChatRunner | None,
    gateway_runner: ChatRunner | None,
    output_console: Any | None = None,
    input_stream: Any | None = None,
) -> None:
    active_console = console if output_console is None else output_console
    prepare_interactive_chat(
        input_stream=input_stream,
        output_console=active_console,
    )
    if standalone:
        if standalone_runner is None:
            raise RuntimeError("standalone chat runner was not configured")
        active_console.print(
            Panel(
                f"[bold {ACCENT}]OpenSquilla Chat[/bold {ACCENT}]\n"
                "[dim]Enter sends. Ctrl+C clears input or cancels the current turn. "
                "Ctrl+D exits. /help lists commands.[/dim]",
                title="OpenSquilla",
                border_style=ACCENT,
            )
        )
        if model:
            active_console.print(f"[dim]Model: {model}[/dim]")
        if session_id:
            active_console.print(f"[dim]Session: {session_id}[/dim]")
        asyncio.run(
            standalone_runner(
                model=model or None,
                session_id=session_id or None,
                workspace=workspace or None,
                workspace_strict=workspace_strict,
                timeout=timeout,
            )
        )
        return

    if gateway_runner is None:
        raise RuntimeError("gateway chat runner was not configured")
    if workspace or workspace_strict is not None:
        active_console.print(
            "[yellow]Note:[/yellow] --workspace only affects --standalone chat. "
            "In gateway mode, /path requires the path to be visible to the "
            "gateway runtime; use /file to upload from this CLI machine for "
            "remote gateways."
        )
    asyncio.run(
        gateway_runner(
            model=model or None,
            session_id=session_id or None,
        )
    )


def launch_chat_command(
    request: ChatCommandRequest,
    *,
    overrides: ChatCommandLaunchOverrides | None = None,
    legacy_overrides: dict[str, Any] | None = None,
) -> None:
    if overrides is None:
        from opensquilla.cli.tui.adapters.chat_cmd_exports import (  # noqa: PLC0415
            resolve_legacy_chat_cmd_launch_overrides,
        )

        active_overrides = resolve_legacy_chat_cmd_launch_overrides(legacy_overrides)
    else:
        active_overrides = overrides
    active_launch_chat = (
        launch_chat
        if active_overrides.launch_chat is None
        else active_overrides.launch_chat
    )

    standalone_runner = active_overrides.standalone_runner
    if standalone_runner is None:
        from opensquilla.cli.tui.adapters import runtime_bridge  # noqa: PLC0415

        standalone_runner = runtime_bridge.standalone_chat_runner
    gateway_runner = active_overrides.gateway_runner
    if gateway_runner is None:
        from opensquilla.cli.tui.adapters import runtime_bridge  # noqa: PLC0415

        gateway_runner = runtime_bridge.gateway_chat_runner

    active_launch_chat(
        model=request.model,
        session_id=request.session_id,
        standalone=request.standalone,
        workspace=request.workspace,
        workspace_strict=request.workspace_strict,
        timeout=request.timeout,
        standalone_runner=standalone_runner,
        gateway_runner=gateway_runner,
    )
