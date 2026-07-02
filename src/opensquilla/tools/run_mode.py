"""Request-scoped sandbox run mode helpers for tool implementations."""

from __future__ import annotations

import contextlib
from typing import cast

from opensquilla.tools.types import current_tool_context

_VALID_RUN_MODES = frozenset({"standard", "trusted", "full"})


def current_run_mode() -> str | None:
    """Return the active Standard/Trusted/Full mode for this tool call."""

    ctx = current_tool_context.get()
    if ctx is None:
        return None
    if ctx.run_mode in _VALID_RUN_MODES:
        return ctx.run_mode
    run_context_mode = getattr(getattr(ctx, "sandbox_run_context", None), "run_mode", None)
    run_context_mode_value = getattr(run_context_mode, "value", run_context_mode)
    if run_context_mode_value in _VALID_RUN_MODES:
        mode = cast(str, run_context_mode_value)
        ctx.run_mode = mode
        return mode
    if ctx.session_key:
        with contextlib.suppress(Exception):
            from opensquilla.gateway.approval_queue import get_approval_queue

            queued_mode = get_approval_queue().get_run_mode(ctx.session_key)
            if queued_mode in _VALID_RUN_MODES:
                mode = cast(str, queued_mode)
                ctx.run_mode = mode
                return mode
    if ctx.elevated == "full":
        return "full"
    if ctx.elevated in ("on", "bypass"):
        return "trusted"
    return None


def full_host_access_active() -> bool:
    """True when the current tool call should use Full Host Access semantics."""

    return current_run_mode() == "full"


def trusted_sandbox_active() -> bool:
    """True when the current tool call is in Trusted-Sandbox mode."""

    return current_run_mode() == "trusted"


__all__ = [
    "current_run_mode",
    "full_host_access_active",
    "trusted_sandbox_active",
]
