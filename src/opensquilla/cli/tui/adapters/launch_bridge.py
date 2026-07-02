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
# Backend id whose host renders its own full-screen UI, so the native launch
# banner is suppressed to avoid a pre-launch flash. Mirrors OpenTuiRendererBackend.
_OPENTUI_BACKEND_ID = "opentui"
_INTERACTIVE_STRUCTLOG_FILE: Any | None = None
_INTERACTIVE_STDLIB_LOG_HANDLER: Any | None = None
_INTERACTIVE_LOG_HANDLER_ATTR = "_opensquilla_interactive_log_handler"


def validate_tui_backend_or_exit() -> str:
    from opensquilla.cli.tui.adapters import runtime_bridge  # noqa: PLC0415
    from opensquilla.cli.tui.renderers.selection import (  # noqa: PLC0415
        RendererBackendSelectionError,
        RendererBackendUnavailableError,
    )

    try:
        return runtime_bridge.validate_tui_backend_selection()
    except (RendererBackendSelectionError, RendererBackendUnavailableError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


def quiet_logs_for_interactive_chat() -> None:
    """Keep chat-process logs out of the interactive terminal surface."""
    import logging  # noqa: PLC0415 - keep launch imports light until chat starts

    import structlog  # noqa: PLC0415

    global _INTERACTIVE_STDLIB_LOG_HANDLER  # noqa: PLW0603 - process-wide logging sink
    global _INTERACTIVE_STRUCTLOG_FILE  # noqa: PLW0603 - process-wide logging sink

    level_name = os.environ.get("OPENSQUILLA_LOG_LEVEL", "warning").strip().upper()
    level = getattr(logging, level_name, logging.WARNING)
    log_dir = os.environ.get("OPENSQUILLA_LOG_DIR", "").strip()
    log_file = None
    if log_dir:
        from pathlib import Path  # noqa: PLC0415

        path = Path(log_dir) / "interactive.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            log_file = path.open("a", encoding="utf-8")
        except OSError:
            log_file = None
    if log_file is None:
        log_file = open(os.devnull, "a", encoding="utf-8")  # noqa: SIM115
    root_logger = logging.getLogger()

    def _targets_interactive_stream(handler: logging.Handler) -> bool:
        if not isinstance(handler, logging.StreamHandler) or isinstance(
            handler, logging.FileHandler
        ):
            return False
        stream = getattr(handler, "stream", None)
        if stream in (sys.stdout, sys.stderr):
            return True
        isatty = getattr(stream, "isatty", None)
        if not callable(isatty):
            return False
        try:
            return bool(isatty())
        except OSError:
            return False

    for handler in list(root_logger.handlers):
        if getattr(handler, _INTERACTIVE_LOG_HANDLER_ATTR, False) or _targets_interactive_stream(
            handler
        ):
            root_logger.removeHandler(handler)
            handler.close()
    if _INTERACTIVE_STRUCTLOG_FILE is not None:
        try:
            _INTERACTIVE_STRUCTLOG_FILE.close()
        except OSError:
            pass
    _INTERACTIVE_STRUCTLOG_FILE = log_file
    _INTERACTIVE_STDLIB_LOG_HANDLER = logging.StreamHandler(log_file)
    _INTERACTIVE_STDLIB_LOG_HANDLER.setLevel(level)
    _INTERACTIVE_STDLIB_LOG_HANDLER.setFormatter(
        logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    )
    setattr(_INTERACTIVE_STDLIB_LOG_HANDLER, _INTERACTIVE_LOG_HANDLER_ATTR, True)
    root_logger.addHandler(_INTERACTIVE_STDLIB_LOG_HANDLER)
    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=log_file),
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )
    root_logger.setLevel(level)
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
    backend_id = validate_tui_backend_or_exit()
    prepare_interactive_chat(
        input_stream=input_stream,
        output_console=active_console,
    )
    if standalone:
        if standalone_runner is None:
            raise RuntimeError("standalone chat runner was not configured")
        # The OpenTUI backend draws its own full-screen footer host (with the
        # model in the router HUD), and it enters the alternate screen a beat
        # after launch. Printing this banner on the main screen first just makes
        # the native chrome flash for ~1s before OpenTUI takes over, so skip it
        # and let OpenTUI come up clean. The native backend keeps the banner.
        if backend_id != _OPENTUI_BACKEND_ID:
            active_console.print(
                Panel(
                    f"[bold {ACCENT}]OpenSquilla Chat[/bold {ACCENT}]\n"
                    "[dim]Enter sends. Ctrl+C clears input or cancels the current turn. "
                    "Ctrl+D exits. /help lists commands.[/dim]",
                    title="OpenSquilla",
                    border_style=ACCENT,
                    expand=False,
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
        launch_chat if active_overrides.launch_chat is None else active_overrides.launch_chat
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
