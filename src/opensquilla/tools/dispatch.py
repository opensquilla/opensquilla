"""Tool dispatch orchestrator.

This module exposes :func:`build_tool_handler`, the single entry point used
by every caller (gateway, CLI, cron, channel adapters). The pipeline is:

1. Ingress injection guard — before registry lookup.
2. Registry lookup — before any policy check.
3. Optional ``ToolHook.before_tool`` fan-out.
4. Policy chain (:func:`opensquilla.tools.policy.run_chain_with_emit`) —
   first denial wins; chain log emission flows through one site.
5. Handler dispatch inside ``current_tool_context.set(effective_ctx)``.
6. Optional ``ToolHook.after_tool`` fan-out with the raw outcome.
7. Single finalisation point (:func:`opensquilla.tools.policy.finalize.finalize`).
8. ``current_tool_context.reset(token)`` in ``finally``.
"""

from __future__ import annotations

import asyncio
import json
import time
import weakref
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import structlog

from opensquilla.engine.hooks import ToolHook, ToolHookCall, ToolHookResult
from opensquilla.execution_status import normalize_execution_status
from opensquilla.result_budget import (
    DEFAULT_TOOL_RESULT_BUDGET_POLICY,
    DEFAULT_TOOL_RUN_BUDGET_POLICY,
    ToolResultBudgetPolicy,
    ToolResultBudgetTracker,
    ToolRunBudgetExceededError,
    ToolRunBudgetPolicy,
    ToolRunBudgetReservation,
    ToolRunBudgetTracker,
    clamp_tool_arguments,
)
from opensquilla.safety.injection_guard import (
    REFUSAL_REASON_TOOL_CALL_IN_UNTRUSTED,
    extract_tool_call_refusal_reason,
)
from opensquilla.sandbox.operation_runtime import (
    prepare_tool_operation_guard,
    record_tool_operation_success,
    run_tool_handler_with_operation_guard,
)
from opensquilla.tool_boundary import AgentToolHandler, ToolCall, ToolResult
from opensquilla.tools.envelope import build_tool_failure_envelope
from opensquilla.tools.policy import DispatchInput, finalize, run_chain_with_emit
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import (
    CallerKind,
    InvalidToolArgumentsError,
    ProjectedToolArgumentsError,
    ToolContext,
    current_tool_context,
)

log = structlog.get_logger("opensquilla.tools.dispatch")

__all__ = ["build_tool_handler", "preflight_tool_call"]

_TOOL_ARGUMENT_PROJECTION_PREFIX = "[tool_use_argument_projection]\n"
_HISTORICAL_TOOL_ARGUMENT_PROJECTION_PREFIX = "[historical_tool_argument_omitted]\n"
_INVALID_PROVIDER_CONTEXT_PROJECTION_PREFIX = "[invalid_provider_context_projection:"
_COMPACTED_TOOL_ARGUMENT_MARKERS = frozenset(
    {
        "_opensquilla_compacted_tool_arguments",
        "_opensquilla_compacted_tool_input",
    }
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_budget_policy(ctx: ToolContext | None) -> ToolResultBudgetPolicy:
    policy = getattr(ctx, "tool_result_budget_policy", None) if ctx is not None else None
    if isinstance(policy, ToolResultBudgetPolicy):
        return policy
    return DEFAULT_TOOL_RESULT_BUDGET_POLICY


def _build_budget_tracker(ctx: ToolContext | None) -> ToolResultBudgetTracker:
    factory = getattr(ctx, "tool_result_budget_tracker_factory", None) if ctx else None
    if callable(factory):
        tracker = factory()
        if isinstance(tracker, ToolResultBudgetTracker):
            return tracker
    return ToolResultBudgetTracker(_resolve_budget_policy(ctx))


def _resolve_run_budget_policy(ctx: ToolContext | None) -> ToolRunBudgetPolicy:
    policy = getattr(ctx, "tool_run_budget_policy", None) if ctx is not None else None
    if isinstance(policy, ToolRunBudgetPolicy):
        return policy
    return DEFAULT_TOOL_RUN_BUDGET_POLICY


def _build_run_budget_tracker(ctx: ToolContext | None) -> ToolRunBudgetTracker:
    factory = getattr(ctx, "tool_run_budget_tracker_factory", None) if ctx else None
    if callable(factory):
        tracker = factory()
        if isinstance(tracker, ToolRunBudgetTracker):
            return tracker
    return ToolRunBudgetTracker(_resolve_run_budget_policy(ctx))


def _build_envelope_result(
    tool_call: ToolCall,
    *,
    exc: Exception,
    policy_denial: bool = False,
    error_class_override: str | None = None,
    user_message_override: str | None = None,
    reason_override: str | None = None,
) -> ToolResult:
    status = {
        "version": 1,
        "status": "error",
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "reason": reason_override or ("denied" if policy_denial else "runtime_error"),
        "source": "tool_runtime",
        "preservation_class": "diagnostic",
    }
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
        execution_status=normalize_execution_status(status),
    )


async def _emit_webresearch_tool_run_diagnostics(
    *,
    tool_call: ToolCall,
    effective_ctx: ToolContext | None,
    reservation: ToolRunBudgetReservation,
    run_budget_tracker: ToolRunBudgetTracker,
    started_at: float,
    raw_result: Any,
    exception: BaseException | None,
) -> None:
    if not reservation.counted_as_external_text:
        return
    snapshot = await run_budget_tracker.snapshot()
    if exception is None:
        status = "ok"
    elif isinstance(exception, ToolRunBudgetExceededError):
        status = "budget_exhausted"
    else:
        status = "error"
    result_chars = 0
    if raw_result is not None:
        result_chars = len(raw_result if isinstance(raw_result, str) else str(raw_result))
    log.debug(
        "dispatch.webresearch_tool_run_diagnostics",
        tool=tool_call.tool_name,
        tool_use_id=tool_call.tool_use_id,
        agent_id=effective_ctx.agent_id if effective_ctx else None,
        session_key=effective_ctx.session_key if effective_ctx else None,
        status=status,
        tool_wall_time_ms=round((time.monotonic() - started_at) * 1000, 3),
        result_chars=result_chars,
        reserved_external_text_chars=reservation.reserved_external_text_chars,
        counted_as_search=reservation.counted_as_search,
        counted_as_fetch=reservation.counted_as_fetch,
        **snapshot,
    )


def _build_run_budget_control_result(
    tool_call: ToolCall,
    exc: ToolRunBudgetExceededError,
) -> ToolResult:
    payload = {
        "status": "control",
        "tool": tool_call.tool_name,
        "reason": "tool_run_budget_exhausted",
        "user_message": (
            "The tool was skipped by a runtime resource guard. Continue with "
            "available evidence or choose a smaller request."
        ),
        "retry_allowed": False,
    }
    status = {
        "version": 1,
        "status": "unknown",
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "reason": "tool_run_budget_exhausted",
        "source": "tool_runtime",
        "preservation_class": "ephemeral",
    }
    log.info(
        "dispatch.tool_run_budget_exhausted",
        tool=tool_call.tool_name,
        tool_use_id=tool_call.tool_use_id,
        message=str(exc),
    )
    return ToolResult(
        tool_use_id=tool_call.tool_use_id,
        tool_name=tool_call.tool_name,
        content=json.dumps(payload),
        is_error=False,
        execution_status=normalize_execution_status(status),
    )


def _check_injection_guard(
    tool_call: ToolCall, effective_ctx: ToolContext | None
) -> ToolResult | None:
    origin = tool_call.origin_trace
    if not origin:
        return None
    reason = extract_tool_call_refusal_reason(origin)
    if reason != REFUSAL_REASON_TOOL_CALL_IN_UNTRUSTED:
        return None
    log.warning(
        "dispatch.injection_refused",
        tool=tool_call.tool_name,
        reason=reason,
        tool_use_id=tool_call.tool_use_id,
        agent_id=effective_ctx.agent_id if effective_ctx else None,
        session_key=effective_ctx.session_key if effective_ctx else None,
    )
    return _build_envelope_result(
        tool_call,
        exc=ValueError("dispatch injection refused"),
        policy_denial=True,
        error_class_override="InjectionRefused",
        user_message_override=str(reason),
    )


def _check_non_executable_arguments(
    tool_call: ToolCall,
    effective_ctx: ToolContext | None,
) -> ToolResult | None:
    arguments = tool_call.arguments
    if set(arguments) == {"_raw"} and isinstance(arguments.get("_raw"), str):
        log.warning(
            "dispatch.invalid_tool_arguments",
            tool=tool_call.tool_name,
            tool_use_id=tool_call.tool_use_id,
            agent_id=effective_ctx.agent_id if effective_ctx else None,
            session_key=effective_ctx.session_key if effective_ctx else None,
            reason="unparsed_raw_arguments",
        )
        return _build_envelope_result(
            tool_call,
            exc=InvalidToolArgumentsError(),
        )

    if any(arguments.get(marker) is True for marker in _COMPACTED_TOOL_ARGUMENT_MARKERS):
        log.warning(
            "dispatch.projected_tool_arguments_refused",
            tool=tool_call.tool_name,
            tool_use_id=tool_call.tool_use_id,
            agent_id=effective_ctx.agent_id if effective_ctx else None,
            session_key=effective_ctx.session_key if effective_ctx else None,
            reason="compacted_argument_marker",
        )
        return _build_envelope_result(
            tool_call,
            exc=ProjectedToolArgumentsError(),
            reason_override="provider_context_projection_reused",
        )

    for argument_name, value in arguments.items():
        if isinstance(value, str) and value.startswith(
            (
                _TOOL_ARGUMENT_PROJECTION_PREFIX,
                _HISTORICAL_TOOL_ARGUMENT_PROJECTION_PREFIX,
                _INVALID_PROVIDER_CONTEXT_PROJECTION_PREFIX,
            )
        ):
            log.warning(
                "dispatch.projected_tool_arguments_refused",
                tool=tool_call.tool_name,
                tool_use_id=tool_call.tool_use_id,
                agent_id=effective_ctx.agent_id if effective_ctx else None,
                session_key=effective_ctx.session_key if effective_ctx else None,
                reason="projection_string",
                field=argument_name,
            )
            return _build_envelope_result(
                tool_call,
                exc=ProjectedToolArgumentsError(),
                reason_override="provider_context_projection_reused",
            )

    return None


def _is_untrusted_caller(ctx: ToolContext | None) -> bool:
    """Return True when the caller cannot be trusted with tool-name disclosure.

    Untrusted callers (CHANNEL surfaces without owner standing, or anonymous
    callers with no ``ToolContext`` at all) must receive an opaque envelope on
    a registry miss so they cannot enumerate the tool catalogue by probing
    names. Owner CHANNEL traffic is treated as trusted because owner promotion
    happens upstream and the owner already sees the full tool surface.
    """
    if ctx is None:
        return True
    return ctx.caller_kind is CallerKind.CHANNEL and not ctx.is_owner


def _resolve_registry_miss(
    tool_call: ToolCall,
    known_skill_names: frozenset[str],
    ctx: ToolContext | None,
) -> ToolResult:
    untrusted = _is_untrusted_caller(ctx)
    is_skill = tool_call.tool_name in known_skill_names

    # Always record the actual tool name in the structured log so operators
    # retain debug visibility regardless of what the caller is allowed to see.
    log.warning(
        "dispatch.registry_miss",
        tool=tool_call.tool_name,
        tool_use_id=tool_call.tool_use_id,
        is_skill=is_skill,
        untrusted_caller=untrusted,
        agent_id=ctx.agent_id if ctx else None,
        session_key=ctx.session_key if ctx else None,
    )

    if untrusted:
        # Opaque envelope: do NOT echo tool_call.tool_name. A bare CHANNEL
        # caller could otherwise enumerate the registry by probing names and
        # observing which ones come back as ToolNotFound vs. UnsupportedSurface.
        return _build_envelope_result(
            tool_call,
            exc=PermissionError("tool unavailable for this surface"),
            policy_denial=True,
            error_class_override="PolicyDenied",
            user_message_override="Tool unavailable for this surface.",
        )

    if is_skill:
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
    if tool_call.tool_name == "bash":
        user_message = (
            "Tool not found: bash. Use exec_command with a command string instead; "
            "do not retry bash as a tool."
        )
    else:
        user_message = (
            f"Tool not found: {tool_call.tool_name}. Do not retry unavailable tools; "
            "use only tools listed in Available Tools."
        )
    return _build_envelope_result(
        tool_call,
        exc=KeyError(tool_call.tool_name),
        policy_denial=True,
        error_class_override="ToolNotFound",
        user_message_override=user_message,
    )


async def preflight_tool_call(
    *,
    registry: ToolRegistry,
    ctx: ToolContext | None,
    tool_call: ToolCall,
    known_skill_names: set[str] | frozenset[str] | None = None,
) -> ToolResult | None:
    """Return a denial envelope when a tool call fails dispatch preflight."""
    known = frozenset(known_skill_names or ())

    injection_envelope = _check_injection_guard(tool_call, ctx)
    if injection_envelope is not None:
        return injection_envelope

    registered = registry.get(tool_call.tool_name)
    if registered is None:
        return _resolve_registry_miss(tool_call, known, ctx)

    non_executable_arguments = _check_non_executable_arguments(tool_call, ctx)
    if non_executable_arguments is not None:
        return non_executable_arguments

    dispatch_input = DispatchInput(
        tool_call=tool_call,
        ctx=ctx,
        registered=registered,
        known_skill_names=known,
        registry=registry,
    )

    def _emit_policy_log(log_event: dict) -> None:
        event = log_event.get("event", "dispatch.policy_block")
        fields = {k: v for k, v in log_event.items() if k != "event"}
        log.warning(event, **fields)

    decision = run_chain_with_emit(dispatch_input, emit=_emit_policy_log)
    if not decision.allowed:
        if decision.envelope is None:
            raise RuntimeError("PolicyCheck returned a denial without an envelope")
        return decision.envelope
    return None


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def build_tool_handler(
    registry: ToolRegistry,
    ctx: ToolContext | None = None,
    *,
    known_skill_names: set[str] | None = None,
    tool_hooks: Sequence[ToolHook] | None = None,
) -> AgentToolHandler:
    """Build an async tool handler from a :class:`ToolRegistry`.

    The returned handler:

    1. Injection-guard check before registry lookup.
    2. Registry lookup; returns structured error on miss.
    3. ``ToolHook.before_tool`` fan-out (no-op if ``tool_hooks`` is empty).
    4. Policy chain; first denial returns immediately.
    5. Reserves run budget, including external call counts and text caps.
    6. Dispatches to the registered handler inside the request-scoped contextvar.
    7. Commits or aborts the run-budget reservation.
    8. ``ToolHook.after_tool`` fan-out with the raw outcome.
    9. Finalises the result (execution status, budget, artefacts) via
       :func:`opensquilla.tools.policy.finalize`.
    10. Resets ``current_tool_context`` unconditionally in ``finally``.

    ``tool_hooks`` defaults to empty so callers that do not pass hooks are
    bit-for-bit equivalent to the legacy path.
    """
    known = frozenset(known_skill_names or ())
    hooks: tuple[ToolHook, ...] = tuple(tool_hooks or ())
    fallback_budget_tracker = _build_budget_tracker(ctx)
    scoped_budget_trackers: dict[
        int,
        tuple[weakref.ReferenceType[ToolContext], ToolResultBudgetTracker],
    ] = {}
    keyed_run_budget_trackers: dict[str, ToolRunBudgetTracker] = {}

    def _budget_tracker_for(effective_ctx: ToolContext | None) -> ToolResultBudgetTracker:
        if effective_ctx is None or effective_ctx is ctx:
            return fallback_budget_tracker
        key = id(effective_ctx)
        entry = scoped_budget_trackers.get(key)
        if entry is not None:
            context_ref, tracker = entry
            if context_ref() is effective_ctx:
                return tracker
        tracker = _build_budget_tracker(effective_ctx)
        scoped_budget_trackers[key] = (weakref.ref(effective_ctx), tracker)
        return tracker

    def _run_budget_tracker_for(
        effective_ctx: ToolContext | None,
    ) -> ToolRunBudgetTracker:
        run_budget_key = (
            getattr(effective_ctx, "tool_run_budget_key", None)
            if effective_ctx is not None
            else None
        )
        if isinstance(run_budget_key, str) and run_budget_key:
            tracker = keyed_run_budget_trackers.get(run_budget_key)
            if tracker is not None:
                return tracker
            tracker = _build_run_budget_tracker(effective_ctx)
            keyed_run_budget_trackers[run_budget_key] = tracker
            return tracker
        tracker = _build_run_budget_tracker(effective_ctx)
        return tracker

    async def _handler(tool_call: ToolCall) -> ToolResult:  # type: ignore[return]
        effective_ctx = current_tool_context.get() or ctx

        # 1. Ingress injection guard.
        injection_envelope = _check_injection_guard(tool_call, effective_ctx)
        if injection_envelope is not None:
            return injection_envelope

        # 2. Registry lookup.
        registered = registry.get(tool_call.tool_name)
        if registered is None:
            return _resolve_registry_miss(tool_call, known, effective_ctx)

        non_executable_arguments = _check_non_executable_arguments(tool_call, effective_ctx)
        if non_executable_arguments is not None:
            return non_executable_arguments

        # 3. ToolHook.before_tool — optional observability hook.
        hook_call = ToolHookCall(tool_call=tool_call, ctx=effective_ctx) if hooks else None
        if hook_call is not None:
            for hook in hooks:
                try:
                    hook.before_tool(hook_call)
                except Exception as exc:  # noqa: BLE001 - hooks must not break dispatch
                    log.warning(
                        "dispatch.tool_hook_failed",
                        hook=getattr(hook, "name", type(hook).__name__),
                        phase="before_tool",
                        error=str(exc),
                    )

        # 4. Policy chain — first denial wins. Single emission site via run_chain_with_emit.
        dispatch_input = DispatchInput(
            tool_call=tool_call,
            ctx=effective_ctx,
            registered=registered,
            known_skill_names=known,
            registry=registry,
        )

        def _emit_policy_log(log_event: dict) -> None:
            event = log_event.get("event", "dispatch.policy_block")
            fields = {k: v for k, v in log_event.items() if k != "event"}
            log.warning(event, **fields)

        decision = run_chain_with_emit(dispatch_input, emit=_emit_policy_log)
        if not decision.allowed:
            if decision.envelope is None:
                raise RuntimeError(
                    "PolicyCheck returned a denial without an envelope"
                )
            if hook_call is not None:
                for hook in hooks:
                    try:
                        hook.after_tool(
                            hook_call,
                            ToolHookResult(result=decision.envelope),
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "dispatch.tool_hook_failed",
                            hook=getattr(hook, "name", type(hook).__name__),
                            phase="after_tool",
                            error=str(exc),
                        )
            return decision.envelope

        # 5. Handler dispatch inside the request-scoped contextvar.
        run_budget_tracker = _run_budget_tracker_for(effective_ctx)
        try:
            run_budget_policy = _resolve_run_budget_policy(effective_ctx)
            reservation = await run_budget_tracker.reserve_tool_call(
                tool_name=tool_call.tool_name,
                arguments=clamp_tool_arguments(
                    tool_call.tool_name,
                    dict(tool_call.arguments),
                    run_budget_policy,
                ),
            )
        except ToolRunBudgetExceededError as exc:
            envelope = _build_run_budget_control_result(tool_call, exc)
            if hook_call is not None:
                for hook in hooks:
                    try:
                        hook.after_tool(hook_call, ToolHookResult(result=envelope))
                    except Exception as hook_exc:  # noqa: BLE001
                        log.warning(
                            "dispatch.tool_hook_failed",
                            hook=getattr(hook, "name", type(hook).__name__),
                            phase="after_tool",
                            error=str(hook_exc),
                        )
            return envelope

        token = current_tool_context.set(effective_ctx)
        tool_started_at = time.monotonic()
        raw_result: Any = None
        exception: BaseException | None = None
        artifact_start = (
            len(effective_ctx.published_artifacts) if effective_ctx is not None else 0
        )
        try:
            sandbox_descriptor = registered.spec.sandbox
            if sandbox_descriptor.enforce:
                workspace = (
                    Path(effective_ctx.workspace_dir)
                    if effective_ctx is not None and effective_ctx.workspace_dir
                    else None
                )
                sandbox_guard = await prepare_tool_operation_guard(
                    sandbox_descriptor,
                    tool_name=tool_call.tool_name,
                    arguments=reservation.arguments,
                    workspace=workspace,
                    run_mode=getattr(effective_ctx, "run_mode", None),
                )
                raw_result = await run_tool_handler_with_operation_guard(
                    registered.handler,
                    reservation.arguments,
                    sandbox_guard,
                )
                if sandbox_guard.denial_payload is None and sandbox_guard.record_payload:
                    try:
                        await record_tool_operation_success(sandbox_guard, raw_result)
                    except Exception:  # pragma: no cover - cache failures should not fail tools
                        log.exception(
                            "dispatch.sandbox_record_success_failed",
                            tool=tool_call.tool_name,
                        )
            else:
                raw_result = await registered.handler(**reservation.arguments)
            await run_budget_tracker.commit_tool_result(reservation, raw_result)
        except asyncio.CancelledError as exc:
            exception = exc
            await run_budget_tracker.abort_tool_result(reservation)
            raise
        except ToolRunBudgetExceededError as exc:
            exception = exc
            if raw_result is None:
                await run_budget_tracker.abort_tool_result(reservation)
        except Exception as exc:  # noqa: BLE001
            exception = exc
            await run_budget_tracker.abort_tool_result(reservation)
        finally:
            try:
                # 6. ToolHook.after_tool — observability seam.
                if hook_call is not None:
                    outcome = ToolHookResult(result=raw_result, exception=exception)
                    for hook in hooks:
                        try:
                            hook.after_tool(hook_call, outcome)
                        except Exception as hook_exc:  # noqa: BLE001
                            log.warning(
                                "dispatch.tool_hook_failed",
                                hook=getattr(hook, "name", type(hook).__name__),
                                phase="after_tool",
                                error=str(hook_exc),
                            )
                if not isinstance(exception, asyncio.CancelledError):
                    await _emit_webresearch_tool_run_diagnostics(
                        tool_call=tool_call,
                        effective_ctx=effective_ctx,
                        reservation=reservation,
                        run_budget_tracker=run_budget_tracker,
                        started_at=tool_started_at,
                        raw_result=raw_result,
                        exception=exception,
                    )
                    # 7. Single finalisation point.
                    return await finalize(
                        tool_call,
                        effective_ctx,
                        raw_result,
                        exception,
                        artifact_start,
                        _budget_tracker_for(effective_ctx),
                        registered,
                    )
            finally:
                current_tool_context.reset(token)

    return _handler
