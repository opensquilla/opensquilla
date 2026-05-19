"""Tool dispatch: build an async tool handler from a ToolRegistry."""

from __future__ import annotations

import json
from typing import Any

import structlog

from opensquilla.safety.injection_guard import (
    REFUSAL_REASON_TOOL_CALL_IN_UNTRUSTED,
    extract_tool_call_refusal_reason,
)
from opensquilla.safety.permission_matrix import Principal, is_tool_allowed
from opensquilla.tool_boundary import AgentToolHandler, ToolCall, ToolResult
from opensquilla.tools.envelope import build_tool_failure_envelope, is_denial_payload
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    current_tool_context,
)

log = structlog.get_logger(__name__)


_PENDING_APPROVAL_STATUSES: frozenset[str] = frozenset({"approval_required", "approval_pending"})


def _extract_pending_approval(content: Any) -> dict[str, Any] | None:
    """Return the payload when ``content`` carries a pending-approval status."""
    if isinstance(content, dict):
        payload = content
    elif isinstance(content, str):
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
    else:
        return None
    return payload if payload.get("status") in _PENDING_APPROVAL_STATUSES else None


def _has_live_approval_surface(ctx: ToolContext | None) -> bool:
    return ctx is None or ctx.interaction_mode is InteractionMode.INTERACTIVE


def _build_envelope_result(
    tool_call: ToolCall,
    *,
    exc: Exception,
    policy_denial: bool = False,
    error_class_override: str | None = None,
    user_message_override: str | None = None,
) -> ToolResult:
    return ToolResult(
        tool_use_id=tool_call.tool_use_id,
        tool_name=tool_call.tool_name,
        content=json.dumps(
            build_tool_failure_envelope(
                exc,
                tool_call.tool_name,
                policy_denial=policy_denial,
                error_class_override=error_class_override,
                user_message_override=user_message_override,
            )
        ),
        is_error=True,
    )


async def preflight_tool_call(
    *,
    registry: ToolRegistry,
    ctx: ToolContext | None,
    tool_call: ToolCall,
    known_skill_names: set[str] | None = None,
) -> ToolResult | None:
    """Run the policy-check gate for a tool call.

    Returns a ``ToolResult`` envelope (with ``is_error=True``) when any
    check rejects the call; returns ``None`` when the call passes every
    check and the caller may dispatch to the registered handler.

    Checks, in order:

    1. Ingress-path injection guard (origin trace inside ``<untrusted>``).
    2. Registry lookup, including skill-name-mismatch detection.
    3. ``owner_only`` rejection for non-owner contexts.
    4. ``denied_tools`` rejection.
    5. ``allowed_tools`` strict allowlist.
    6. Channel permission matrix (operator/user role).

    This function is the single source of truth for tool policy. It is
    shared by :func:`build_tool_handler` and by callers that need to
    short-circuit on policy before dispatch (e.g. streaming tool
    interceptors that bypass the regular handler).

    Used by:
    - build_tool_handler (standard dispatch path) — preflight then handler call
    - Agent._run_one_streaming (Task 5: meta_invoke special path)

    Caller responsibilities — IMPORTANT:

    * **Contextvar resolution**: this function does NOT consult
      ``current_tool_context``. Callers must resolve the effective
      context themselves with ``current_tool_context.get() or ctx``
      BEFORE passing ``ctx``. Otherwise per-request overrides set by
      channel adapters are silently ignored.

    * **ctx=None bypasses gates 3-6**: when ``ctx`` is None, the
      ``owner_only``, ``denied_tools``, ``allowed_tools``, and channel
      permission matrix gates are SKIPPED. Gates 1 and 2 (untrusted
      origin, registry lookup) still fire. This matches the
      pre-extraction inline behaviour but is hazardous in production
      callers — never pass ``ctx=None`` outside test code.
    """

    # Ingress-path injection guard:
    # if the tool-call origin trace lies inside an <untrusted> block,
    # refuse immediately with a structured JSON payload.
    origin = tool_call.origin_trace
    if origin:
        reason = extract_tool_call_refusal_reason(origin)
        if reason == REFUSAL_REASON_TOOL_CALL_IN_UNTRUSTED:
            log.warning(
                "dispatch.injection_refused",
                tool=tool_call.tool_name,
                reason=reason,
                tool_use_id=tool_call.tool_use_id,
                agent_id=ctx.agent_id if ctx else None,
                session_key=ctx.session_key if ctx else None,
            )
            return _build_envelope_result(
                tool_call,
                exc=ValueError("dispatch injection refused"),
                policy_denial=True,
                error_class_override="InjectionRefused",
                user_message_override=str(reason),
            )

    registered = registry.get(tool_call.tool_name)
    if registered is None:
        if tool_call.tool_name in (known_skill_names or set()):
            skill_name = tool_call.tool_name
            user_message = (
                f"{skill_name} is a skill, not a tool. Do not call skill names as tools. "
                f'Use skill_view(name="{skill_name}") to read the skill instructions, '
                "then continue using only tools listed in Available Tools."
            )
            return _build_envelope_result(
                tool_call,
                exc=ValueError("skill call mismatch"),
                policy_denial=True,
                error_class_override="UnsupportedSurface",
                user_message_override=user_message,
            )
        return _build_envelope_result(
            tool_call,
            exc=KeyError(tool_call.tool_name),
            policy_denial=True,
            error_class_override="ToolNotFound",
            user_message_override=f"Tool not found: {tool_call.tool_name}",
        )

    # Defense-in-depth: reject owner_only tools if context says non-owner
    if ctx and registered.spec.owner_only and not ctx.is_owner:
        log.warning(
            "dispatch.defense_in_depth_block",
            tool=tool_call.tool_name,
            reason="owner_only",
            tool_use_id=tool_call.tool_use_id,
            agent_id=ctx.agent_id if ctx else None,
            session_key=ctx.session_key if ctx else None,
        )
        return _build_envelope_result(
            tool_call,
            exc=PermissionError("owner-only tool"),
            policy_denial=True,
            error_class_override="OwnerOnly",
            user_message_override=f"Tool '{tool_call.tool_name}' restricted to owner.",
        )

    # Defense-in-depth: reject denied tools
    if ctx and tool_call.tool_name in ctx.denied_tools:
        log.warning(
            "dispatch.defense_in_depth_block",
            tool=tool_call.tool_name,
            reason="denied",
            tool_use_id=tool_call.tool_use_id,
            agent_id=ctx.agent_id if ctx else None,
            session_key=ctx.session_key if ctx else None,
        )
        return _build_envelope_result(
            tool_call,
            exc=PermissionError("tool blocked"),
            policy_denial=True,
            error_class_override="PolicyDenied",
            user_message_override=(
                f"Tool '{tool_call.tool_name}' not available in this context."
            ),
        )

    if (
        ctx
        and ctx.allowed_tools is not None
        and tool_call.tool_name not in ctx.allowed_tools
    ):
        log.warning(
            "dispatch.defense_in_depth_block",
            tool=tool_call.tool_name,
            reason="not_allowed",
            tool_use_id=tool_call.tool_use_id,
            agent_id=ctx.agent_id if ctx else None,
            session_key=ctx.session_key if ctx else None,
        )
        return _build_envelope_result(
            tool_call,
            exc=PermissionError("tool blocked"),
            policy_denial=True,
            error_class_override="PolicyDenied",
            user_message_override=(
                f"Tool '{tool_call.tool_name}' not available in this context."
            ),
        )

    if ctx and ctx.caller_kind is CallerKind.CHANNEL:
        principal = Principal(
            role="operator" if ctx.is_owner else "user",
            channel_id=ctx.session_key,
        )
        decision = is_tool_allowed(tool_call.tool_name, "dm", principal)
        if not decision.allowed:
            log.warning(
                "dispatch.permission_matrix_block",
                tool=tool_call.tool_name,
                reason=decision.reason,
                tool_use_id=tool_call.tool_use_id,
                agent_id=ctx.agent_id if ctx else None,
                session_key=ctx.session_key if ctx else None,
            )
            return _build_envelope_result(
                tool_call,
                exc=PermissionError("tool denied"),
                policy_denial=True,
                error_class_override="UnsupportedSurface",
                user_message_override=(
                    f"Tool '{tool_call.tool_name}' denied: {decision.reason}."
                ),
            )

    return None


def build_tool_handler(
    registry: ToolRegistry,
    ctx: ToolContext | None = None,
    *,
    known_skill_names: set[str] | None = None,
) -> AgentToolHandler:
    """Build an async tool handler function from a ToolRegistry.

    The returned handler:
    1. Runs :func:`preflight_tool_call` to enforce policy (injection
       guard, registry lookup, owner/denied/allowed/channel matrix).
    2. Dispatches to the registered handler if preflight passes.
    3. Wraps results and errors into a :class:`ToolResult`.
    """

    async def _handler(tool_call: ToolCall) -> ToolResult:
        effective_ctx = current_tool_context.get() or ctx

        preflight = await preflight_tool_call(
            registry=registry,
            ctx=effective_ctx,
            tool_call=tool_call,
            known_skill_names=known_skill_names,
        )
        if preflight is not None:
            return preflight

        # preflight returned None ⇒ tool is registered and policy allows it.
        registered = registry.get(tool_call.tool_name)
        assert registered is not None  # preflight guarantees this

        # Dispatch to handler — set request-scoped context for tools that need agent_id
        token = current_tool_context.set(effective_ctx)
        try:
            artifact_start = (
                len(effective_ctx.published_artifacts) if effective_ctx is not None else 0
            )
            result = await registered.handler(**tool_call.arguments)
            if not _has_live_approval_surface(effective_ctx):
                pending = _extract_pending_approval(result)
                if pending is not None:
                    surface = effective_ctx.caller_kind.value if effective_ctx else "unknown"
                    log.warning(
                        "dispatch.approval_required_unsupported_surface",
                        tool=tool_call.tool_name,
                        surface=surface,
                        approval_id=pending.get("approval_id"),
                        tool_use_id=tool_call.tool_use_id,
                        agent_id=effective_ctx.agent_id if effective_ctx else None,
                        session_key=effective_ctx.session_key if effective_ctx else None,
                    )
                    user_message = (
                        f"Tool '{tool_call.tool_name}' requires human approval, but the {surface} "
                        "surface has no interactive approval path. Re-run with --interactive "
                        "or from an interactive operator surface."
                    )
                    envelope = build_tool_failure_envelope(
                        ValueError("approval required"),
                        tool_call.tool_name,
                        policy_denial=True,
                        error_class_override="UnsupportedSurface",
                        user_message_override=user_message,
                    )
                    return ToolResult(
                        tool_use_id=tool_call.tool_use_id,
                        tool_name=tool_call.tool_name,
                        content=json.dumps(envelope),
                        is_error=True,
                    )

            denial = is_denial_payload(result)
            artifacts = (
                list(effective_ctx.published_artifacts[artifact_start:])
                if effective_ctx is not None
                else []
            )
            return ToolResult(
                tool_use_id=tool_call.tool_use_id,
                tool_name=tool_call.tool_name,
                content=result,
                is_error=denial,
                artifacts=artifacts,
            )
        except Exception as exc:
            # Stable failure envelope, no raw exception leakage.
            envelope = build_tool_failure_envelope(exc, tool_call.tool_name)
            log.warning(
                "dispatch.tool_failed",
                tool=tool_call.tool_name,
                tool_use_id=tool_call.tool_use_id,
                agent_id=effective_ctx.agent_id if effective_ctx else None,
                session_key=effective_ctx.session_key if effective_ctx else None,
                error_class=envelope["error_class"],
                retry_allowed=envelope["retry_allowed"],
            )
            return ToolResult(
                tool_use_id=tool_call.tool_use_id,
                tool_name=tool_call.tool_name,
                content=json.dumps(envelope),
                is_error=True,
            )
        finally:
            current_tool_context.reset(token)

    return _handler
