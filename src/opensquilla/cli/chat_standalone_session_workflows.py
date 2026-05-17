"""Standalone session slash-command workflows for interactive chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import uuid4

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import ACCENT, console
from opensquilla.session.compaction import (
    build_compaction_config_from_provider,
    call_compact_with_optional_config,
)


async def handle_standalone_new_command(
    parts: Sequence[str],
    *,
    session_manager: Any,
    build_tool_context: Callable[[str], object],
    model: str | None,
) -> tuple[str, object, ChatSessionState]:
    """Handle standalone chat /new by creating a fresh session and state."""

    session_key = f"agent:main:standalone:{uuid4().hex[:8]}"
    await session_manager.get_or_create(session_key, agent_id="main")
    tool_context = build_tool_context(session_key)
    state = ChatSessionState(session_key=session_key, model=model)
    title = parts[1].strip() if len(parts) > 1 else None
    label = f" ({title})" if title else ""
    console.print(f"[green]Started new session{label}:[/green] {session_key}")
    return session_key, tool_context, state


async def handle_standalone_clear_command(
    state: ChatSessionState,
    *,
    services: Any,
    flush_before_rewrite: Callable[..., Awaitable[bool]],
) -> bool:
    """Handle standalone chat /clear and /reset."""

    session_manager = getattr(services, "session_manager", None)
    if session_manager is not None:
        safe_to_reset = await flush_before_rewrite(
            services,
            state.session_key,
            operation="Reset",
        )
        if not safe_to_reset:
            return False
        await session_manager.truncate(state.session_key, max_messages=0)
    state.transcript.clear()
    state.usage.reset()
    console.print(f"[{ACCENT}]cleared[/] [dim]{state.session_key}[/dim]")
    return True


async def handle_standalone_compact_command(
    state: ChatSessionState,
    *,
    services: Any,
    model: str | None,
    flush_before_rewrite: Callable[..., Awaitable[bool]],
    resolve_compaction_provider: Callable[[Any, str | None], Any | None],
) -> bool:
    """Handle standalone chat /compact."""

    session_manager = getattr(services, "session_manager", None)
    if session_manager is None:
        console.print("[yellow]No session manager available.[/yellow]")
        return False

    safe_to_compact = await flush_before_rewrite(
        services,
        state.session_key,
        operation="Compact",
    )
    if not safe_to_compact:
        return False

    config = getattr(services, "config", None)
    context_window = (
        getattr(config, "context_budget_tokens", 100_000)
        if config is not None
        else 100_000
    )
    provider_selector = getattr(services, "provider_selector", None)
    compaction_config = build_compaction_config_from_provider(
        resolve_compaction_provider(provider_selector, model),
        model_override=model,
        compaction_config=getattr(config, "compaction", None),
    )
    summary = await call_compact_with_optional_config(
        session_manager.compact,
        state.session_key,
        context_window,
        compaction_config,
    )
    if summary:
        console.print(
            f"[{ACCENT}]compacted[/] [dim]summary {len(summary)} chars[/dim]"
        )
    else:
        console.print(
            f"[{ACCENT}]compact skipped[/] "
            "[dim]context already within budget[/dim]"
        )
    return True
