"""Standalone slash-command adapter for the chat REPL backend.

This module owns TurnRunner-backed slash command dispatch. It stays independent
from raw frontend and chat application objects: callers pass typed session
state, service handles, and optional stream callbacks.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

import opensquilla.cli.tui.adapters.input_bridge as _input_bridge
from opensquilla.cli.chat.session_state import ChatSessionState
from opensquilla.cli.chat.turn import TurnResult
from opensquilla.cli.tui.adapters.commands import is_exit_command, render_help_table
from opensquilla.cli.tui.backend.contracts import TuiOutputHandle
from opensquilla.cli.ui import ACCENT, console, error_panel
from opensquilla.engine.commands import Surface
from opensquilla.session.compaction import (
    build_compaction_config_from_provider,
    call_compact_with_optional_config,
)
from opensquilla.session.compaction_lifecycle import (
    flush_receipt_is_successful_flush,
)

if TYPE_CHECKING:
    from opensquilla.engine.agent_injection import PendingInputProvider

STANDALONE_SLASH_HANDLER_WORDS = frozenset(
    {
        "/clear",
        "/compact",
        "/cmp",
        "/cost",
        "/exit",
        "/help",
        "/image",
        "/meta",
        "/model",
        "/new",
        "/path",
        "/quit",
        "/reset",
        "/save",
        "/session",
        "/status",
        "/theme",
    }
)


class StandaloneStreamResponse(Protocol):
    async def __call__(
        self,
        turn_runner: object,
        session_key: str,
        tool_context: object,
        message: str,
        *,
        model: str | None = None,
        services: object = None,
        timeout: float | None = None,
        tui_output: TuiOutputHandle | None = None,
        pending_input_provider: PendingInputProvider | None = None,
    ) -> TurnResult: ...


class StandaloneImageCommandHandler(Protocol):
    async def __call__(
        self,
        turn_runner: object,
        session_key: str,
        tool_context: object,
        command: str,
        *,
        model: str | None = None,
        services: object = None,
        timeout: float | None = None,
        tui_output: TuiOutputHandle | None = None,
        pending_input_provider: PendingInputProvider | None = None,
    ) -> TurnResult: ...


class StandaloneSessionReplacer(Protocol):
    def __call__(
        self,
        *,
        session_key: str,
        tool_ctx: object,
        state: ChatSessionState,
        model: str | None,
    ) -> Awaitable[None] | None: ...


class CompactWithResult(Protocol):
    def __call__(
        self,
        session_key: str,
        context_window_tokens: int,
        compaction_config: object | None,
    ) -> Awaitable[Any]: ...


class StandaloneCreateSession(Protocol):
    def __call__(self, session_key: str, *, agent_id: str = "main") -> Awaitable[Any]: ...


class StandaloneReadTranscript(Protocol):
    def __call__(self, session_key: str) -> Awaitable[Any] | Any: ...


class StandaloneTruncateSession(Protocol):
    def __call__(self, session_key: str, *, max_messages: int = 0) -> Awaitable[None]: ...


class StandaloneCompactSession(Protocol):
    def __call__(
        self,
        session_key: str,
        context_window_tokens: int,
        config: object | None = None,
    ) -> Awaitable[str]: ...


class StandaloneFlushTranscript(Protocol):
    def __call__(
        self,
        transcript: object,
        session_key: str,
        **kwargs: Any,
    ) -> Awaitable[Any]: ...


@dataclass
class StandaloneSlashServices:
    create_session: StandaloneCreateSession | None = None
    read_transcript: StandaloneReadTranscript | None = None
    truncate_session: StandaloneTruncateSession | None = None
    compact_session: StandaloneCompactSession | None = None
    compact_with_result: CompactWithResult | None = None
    flush_transcript: StandaloneFlushTranscript | None = None
    config: object | None = None
    provider_selector: object | None = None


@dataclass
class StandaloneSlashContext:
    state: ChatSessionState
    session_key: str
    model: str | None
    tool_ctx: object
    slash_services: StandaloneSlashServices
    turn_runner: object
    build_tool_ctx: Callable[[str], object]
    replace_session: StandaloneSessionReplacer
    runtime_services: object = None
    timeout: float | None = None
    tui_output: TuiOutputHandle | None = None
    stream_response: StandaloneStreamResponse | None = None
    image_command_handler: StandaloneImageCommandHandler | None = None


def _slash_parts(cmd: str, name: str) -> list[str] | None:
    if cmd == name or cmd.startswith(f"{name} "):
        return cmd.split(maxsplit=1)
    return None


async def _maybe_await(value: Awaitable[Any] | Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def stream_response_turnrunner(
    turn_runner: object,
    session_key: str,
    tool_context: object,
    message: str,
    *,
    model: str | None = None,
    services: object = None,
    timeout: float | None = None,
    tui_output: TuiOutputHandle | None = None,
    pending_input_provider: PendingInputProvider | None = None,
) -> TurnResult:
    del (
        turn_runner,
        session_key,
        tool_context,
        message,
        model,
        services,
        timeout,
        tui_output,
        pending_input_provider,
    )
    raise RuntimeError("standalone streaming dependency was not configured")


async def handle_image_command_turnrunner(
    turn_runner: object,
    session_key: str,
    tool_context: object,
    command: str,
    *,
    model: str | None = None,
    services: object = None,
    timeout: float | None = None,
    tui_output: TuiOutputHandle | None = None,
    pending_input_provider: PendingInputProvider | None = None,
) -> TurnResult:
    del (
        turn_runner,
        session_key,
        tool_context,
        command,
        model,
        services,
        timeout,
        tui_output,
        pending_input_provider,
    )
    raise RuntimeError("standalone image dependency was not configured")


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


def _coerce_transcript_result(result: Any) -> list[Any] | None:
    if result is None:
        return []
    if isinstance(result, str | bytes) or not isinstance(result, Iterable):
        return None
    return list(result)


async def _read_standalone_transcript_handle(
    read_transcript: StandaloneReadTranscript | None,
    session_key: str,
) -> list[Any] | None:
    if read_transcript is None:
        return []
    try:
        result = read_transcript(session_key)
        if inspect.isawaitable(result):
            result = await result
    except KeyError:
        return []
    except Exception:  # noqa: BLE001
        return None
    return _coerce_transcript_result(result)


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
        return _coerce_transcript_result(result)
    return None


async def _flush_before_standalone_rewrite(
    slash_services: StandaloneSlashServices,
    session_key: str,
    *,
    operation: str,
) -> bool:
    """Fail closed before reset; compact can continue on flush degradation."""
    compaction_operation = operation.strip().lower() == "compact"
    transcript = await _read_standalone_transcript_handle(
        slash_services.read_transcript,
        session_key,
    )
    if transcript is None:
        if compaction_operation:
            console.print(
                f"[yellow]{operation}: could not inspect durable transcript; "
                "continuing with compaction only.[/yellow]"
            )
            return True
        console.print(
            f"[yellow]{operation} aborted: could not inspect the durable transcript.[/yellow]"
        )
        return False
    if not transcript:
        return True

    flush_transcript = slash_services.flush_transcript
    if flush_transcript is None:
        if compaction_operation:
            console.print(
                f"[yellow]{operation}: flush service is unavailable; "
                "continuing with compaction only.[/yellow]"
            )
            return True
        console.print(
            f"[yellow]{operation} aborted: flush service is unavailable and "
            "the durable transcript is non-empty.[/yellow]"
        )
        return False

    try:
        receipt = await flush_transcript(
            transcript,
            session_key,
            agent_id="main",
            timeout=30.0,
            message_window=0,
            segment_mode="auto",
        )
    except Exception as exc:  # noqa: BLE001
        if compaction_operation:
            console.print(
                f"[yellow]{operation}: flush failed ({exc}); "
                "continuing with compaction only.[/yellow]"
            )
            return True
        console.print(f"[yellow]{operation} aborted: flush failed ({exc}).[/yellow]")
        return False

    if not flush_receipt_is_successful_flush(receipt):
        if compaction_operation:
            error = getattr(receipt, "error", None) or "degraded receipt"
            console.print(
                f"[yellow]{operation}: flush failed ({error}); "
                "continuing with compaction only.[/yellow]"
            )
            return True
        error = getattr(receipt, "error", None) or "unknown error"
        console.print(f"[yellow]{operation} aborted: flush failed ({error}).[/yellow]")
        return False
    return True


def _save_transcript_command(cmd: str, state: ChatSessionState) -> None:
    parts = cmd.split(maxsplit=1)
    if len(parts) > 1:
        target = Path(parts[1]).expanduser()
    else:
        suffix = state.session_key.replace(":", "-")
        target = Path(f"opensquilla-chat-{suffix}.md")
    target.write_text(state.transcript.to_markdown(), encoding="utf-8")
    console.print(f"[green]Saved transcript:[/green] {target}")


def _image_prompt_from_command(command: str) -> str:
    return _input_bridge.image_prompt_from_command(command)


def _path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, Any]]]:
    return _input_bridge.path_prompt_and_attachments(command)


async def _replace_with_new_session(
    context: StandaloneSlashContext,
    *,
    title: str | None = None,
) -> str:
    session_key = f"agent:main:standalone:{uuid4().hex[:8]}"
    create_session = context.slash_services.create_session
    if create_session is None:
        raise RuntimeError("standalone chat requires session manager")
    await create_session(session_key, agent_id="main")
    state = ChatSessionState(session_key=session_key, model=context.model)
    tool_ctx = context.build_tool_ctx(session_key)

    context.session_key = session_key
    context.tool_ctx = tool_ctx
    context.state = state
    await _maybe_await(
        context.replace_session(
            session_key=session_key,
            tool_ctx=tool_ctx,
            state=state,
            model=context.model,
        )
    )
    label = f" ({title})" if title else ""
    console.print(f"[green]Started new session{label}:[/green] {session_key}")
    return session_key


async def _compact_standalone_context(context: StandaloneSlashContext) -> None:
    slash_services = context.slash_services
    compact_session = slash_services.compact_session
    compact_with_result = slash_services.compact_with_result
    if compact_session is None and compact_with_result is None:
        console.print("[yellow]No session manager available.[/yellow]")
        return

    safe_to_compact = await _flush_before_standalone_rewrite(
        slash_services,
        context.session_key,
        operation="Compact",
    )
    if not safe_to_compact:
        return

    console.print(f"[{ACCENT}]compacting context...[/]")
    config = slash_services.config
    context_window = (
        getattr(config, "context_budget_tokens", 100_000) if config is not None else 100_000
    )
    compaction_config = build_compaction_config_from_provider(
        _resolve_compaction_provider(
            slash_services.provider_selector,
            context.model,
        ),
        model_override=context.model,
        compaction_config=getattr(config, "compaction", None),
    )
    try:
        if compact_with_result is not None:
            result = await compact_with_result(
                context.session_key,
                context_window,
                compaction_config,
            )
            summary = getattr(result, "summary", "") or ""
            token_stats = (
                f"{getattr(result, 'tokens_before', 0)} -> "
                f"{getattr(result, 'tokens_after', 0)} tokens, "
                f"{getattr(result, 'remaining_budget_tokens', 0)} remaining, "
                f"{getattr(result, 'summary_source', 'unknown')}"
            )
        else:
            if compact_session is None:
                console.print("[yellow]No session manager available.[/yellow]")
                return
            summary = await call_compact_with_optional_config(
                compact_session,
                context.session_key,
                context_window,
                compaction_config,
            )
            token_stats = f"summary {len(summary)} chars"
    except Exception as exc:  # noqa: BLE001 - keep chat command recoverable.
        console.print(f"[red]compact failed: {exc}[/red]")
        return

    if summary:
        console.print(f"[{ACCENT}]compacted[/] [dim]{token_stats}[/dim]")
    else:
        console.print(
            f"[{ACCENT}]compact skipped[/] "
            "[dim]already within context budget; no compact was applied[/dim]"
        )


async def handle_standalone_slash_command(
    cmd: str,
    context: StandaloneSlashContext,
) -> bool:
    """Handle standalone-mode slash commands.

    Unknown slash commands are handled here so callers can keep the input loop
    free of command-specific fallback rendering.
    """

    state = context.state
    stream = context.stream_response or stream_response_turnrunner
    image_handler = context.image_command_handler or handle_image_command_turnrunner

    if is_exit_command(cmd, Surface.CLI_STANDALONE):
        console.print("[yellow]Goodbye.[/yellow]")
        return False

    if cmd == "/help":
        console.print(render_help_table(Surface.CLI_STANDALONE))
        return True

    if _slash_parts(cmd, "/theme"):
        from opensquilla.cli.tui.opentui.themes import handle_theme_command  # noqa: PLC0415

        await handle_theme_command(cmd, context.tui_output)
        return True

    if parts := _slash_parts(cmd, "/new"):
        title = parts[1].strip() if len(parts) > 1 else None
        await _replace_with_new_session(context, title=title)
        return True

    if cmd in {"/status", "/session"}:
        console.print(
            f"[{ACCENT}]session[/] [dim]{state.session_key}[/dim]\n"
            f"[{ACCENT}]model[/] [dim]{state.model or 'default'}[/dim]"
        )
        return True

    if cmd == "/models":
        console.print("[yellow]/models requires gateway mode.[/yellow]")
        return True

    if _slash_parts(cmd, "/meta"):
        console.print("[yellow]/meta requires gateway mode.[/yellow]")
        return True

    if parts := _slash_parts(cmd, "/model"):
        if len(parts) == 1:
            console.print(f"[dim]model={state.model or 'default'}[/dim]")
        else:
            new_model = parts[1].strip()
            context.model = new_model
            state.model = new_model
            console.print(f"[green]model:[/green] {new_model}")
        return True

    if cmd == "/cost":
        console.print(state.usage.render())
        return True

    if cmd in {"/clear", "/reset"}:
        truncate_session = context.slash_services.truncate_session
        if truncate_session is not None:
            safe_to_reset = await _flush_before_standalone_rewrite(
                context.slash_services,
                context.session_key,
                operation="Reset",
            )
            if not safe_to_reset:
                return True
            await truncate_session(context.session_key, max_messages=0)
        state.transcript.clear()
        state.usage.reset()
        console.print(f"[{ACCENT}]cleared[/] [dim]{state.session_key}[/dim]")
        return True

    if cmd in {"/compact", "/cmp"}:
        await _compact_standalone_context(context)
        return True

    if _slash_parts(cmd, "/save"):
        _save_transcript_command(cmd, state)
        return True

    if parts := _slash_parts(cmd, "/image"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /image <path> [prompt][/red]")
            return True
        result = await image_handler(
            context.turn_runner,
            context.session_key,
            context.tool_ctx,
            cmd,
            model=context.model,
            services=context.runtime_services,
            timeout=context.timeout,
            tui_output=context.tui_output,
        )
        state.transcript.add("user", _image_prompt_from_command(cmd))
        state.transcript.add("assistant", result.text)
        state.usage.apply(result.usage)
        return True

    if parts := _slash_parts(cmd, "/path"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /path <path> [prompt][/red]")
            return True
        try:
            prompt, attachments = _path_prompt_and_attachments(cmd)
        except ValueError as exc:
            console.print(error_panel(str(exc)))
            return True
        if attachments:
            console.print(error_panel("/path must not create attachments."))
            return True
        result = await stream(
            context.turn_runner,
            context.session_key,
            context.tool_ctx,
            prompt,
            model=context.model,
            services=context.runtime_services,
            timeout=context.timeout,
            tui_output=context.tui_output,
        )
        state.transcript.add("user", prompt)
        state.transcript.add("assistant", result.text)
        state.usage.apply(result.usage)
        return True

    console.print("[red]Unknown command.[/red] [dim]Use /help.[/dim]")
    return True
