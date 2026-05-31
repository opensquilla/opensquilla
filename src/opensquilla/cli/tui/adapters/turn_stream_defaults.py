"""Terminal dependency composition for TUI turn streaming."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import opensquilla.cli.tui.adapters.input_bridge as _input_bridge
import opensquilla.cli.tui.adapters.terminal_bridge as _terminal_bridge
from opensquilla.cli.chat import turn_stream as _turn_stream
from opensquilla.cli.tui.backend.contracts import TuiOutputHandle
from opensquilla.cli.tui.terminal.approval import maybe_handle_approval
from opensquilla.cli.tui.terminal.renderer import TerminalRenderer
from opensquilla.cli.ui import console, error_panel
from opensquilla.engine.commands import Surface

TurnStreamDependencies = _turn_stream.TurnStreamDependencies


def approval_surface_for_tui_output(
    tui_output: TuiOutputHandle | None,
    default: Surface,
) -> Surface:
    resolved = _turn_stream.approval_surface_for_tui_output(tui_output, default)
    if isinstance(resolved, Surface):
        return resolved
    return default


def _approval_surface_for_terminal_output(
    tui_output: TuiOutputHandle | None,
    default: object | None,
) -> object | None:
    if not isinstance(default, Surface):
        return default
    return approval_surface_for_tui_output(tui_output, default)


def image_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
    return _input_bridge.image_prompt_and_attachments(command)


def default_turn_stream_dependencies(
    *,
    renderer_factory: Callable[..., Any] | None = None,
    stream_wrapper: Callable[[Any, Any], Any] | None = None,
    approval_handler: Callable[..., Awaitable[None]] | None = None,
    cancel_clearer: Callable[[], None] | None = None,
    image_attachment_builder: Callable[[str], tuple[str, list[dict[str, str]]]]
    | None = None,
    output_console: Any | None = None,
    error_panel_factory: Callable[[str], Any] | None = None,
) -> TurnStreamDependencies:
    return _turn_stream.default_turn_stream_dependencies(
        renderer_factory=(
            TerminalRenderer if renderer_factory is None else renderer_factory
        ),
        stream_wrapper=stream_wrapper,
        approval_handler=(
            maybe_handle_approval if approval_handler is None else approval_handler
        ),
        cancel_clearer=(
            _terminal_bridge.clear_current_cancel
            if cancel_clearer is None
            else cancel_clearer
        ),
        image_attachment_builder=(
            image_prompt_and_attachments
            if image_attachment_builder is None
            else image_attachment_builder
        ),
        output_console=console if output_console is None else output_console,
        error_panel_factory=(
            error_panel if error_panel_factory is None else error_panel_factory
        ),
        gateway_approval_surface=Surface.CLI_GATEWAY,
        standalone_approval_surface=Surface.CLI_STANDALONE,
        approval_surface_resolver=_approval_surface_for_terminal_output,
    )
