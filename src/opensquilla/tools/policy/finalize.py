"""Single execution-status finalisation point.

:func:`finalize` is the only place the new pipeline mints execution status
for a tool result. It branches on the four mutually exclusive outcomes from
the orchestrator — exception, approval-pending on an unsupported surface,
denial payload, and success — and always routes through
:func:`normalize_execution_status` exactly once.

The function preserves the budget-bypass behaviour: when
artifacts were published the model-facing content is returned unbudgeted;
otherwise the result is normalised through the budget tracker.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from opensquilla.engine.tool_result_store import ToolResultStore, ToolResultStoreBudgetError
from opensquilla.execution_status import (
    derive_is_error,
    execution_status_for_tool_result,
    mark_execution_status_truncated,
    normalize_execution_status,
)
from opensquilla.result_budget import (
    ToolResultBudgetTracker,
    ToolRunBudgetExceededError,
    resolve_budget_class,
)
from opensquilla.router_control import router_control_payload_terminates_turn
from opensquilla.safety.secret_redaction import redact_secret_value
from opensquilla.tool_boundary import ToolCall, ToolResult
from opensquilla.tools.envelope import build_tool_failure_envelope, is_denial_payload
from opensquilla.tools.types import InteractionMode, ToolContext

log = structlog.get_logger("opensquilla.tools.dispatch")

_PENDING_APPROVAL_STATUSES: frozenset[str] = frozenset(
    {"approval_required", "approval_pending"}
)


_TOOL_RESULT_PROJECTION_FAILED = "tool_result_projection_failed"


# Semantic non-success fragments shared by structured tool receipts. This keeps
# projection eligibility independent of any tool-specific success vocabulary.
_NON_SUCCESS_RESULT_STATUS_PARTS: frozenset[str] = frozenset(
    {
        "blocked",
        "cancelled",
        "canceled",
        "control",
        "denied",
        "error",
        "failed",
        "failure",
        "killed",
        "missing",
        "not",
        "pending",
        "rejected",
        "required",
        "running",
        "timed",
        "timeout",
        "unavailable",
        "unknown",
        "unsupported",
    }
)


_DISPATCH_TRUNCATION_RETRIEVE_HINT = (
    "This tool result was truncated before entering model context. "
    "Use retrieve_tool_result with tool_result_handle to inspect the full "
    "pre-budget model-facing output."
)


def _store_dispatch_truncated_snapshot(
    *,
    ctx: ToolContext | None,
    call: ToolCall,
    content: str,
) -> dict[str, Any] | None:
    """Persist model-facing output before dispatch-level budget truncation."""
    if ctx is None or not ctx.tool_result_store_dir:
        return None

    session_id = (
        ctx.tool_result_store_session_id
        or ctx.artifact_session_id
        or ctx.session_key
    )
    session_key = ctx.session_key or session_id
    agent_id = ctx.agent_id or "main"
    if not session_id or not session_key or not agent_id:
        return None

    try:
        record = ToolResultStore(ctx.tool_result_store_dir).write(
            content,
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            session_id=session_id,
            session_key=session_key,
            agent_id=agent_id,
        )
    except ToolResultStoreBudgetError as exc:
        log.info(
            "dispatch.truncated_raw_snapshot_skipped",
            tool=call.tool_name,
            tool_use_id=call.tool_use_id,
            reason=str(exc),
        )
        return None
    except Exception as exc:  # pragma: no cover - tracing must not break tools
        log.warning(
            "dispatch.truncated_raw_snapshot_failed",
            tool=call.tool_name,
            tool_use_id=call.tool_use_id,
            error=str(exc),
        )
        return None

    return {
        "tool_result_handle": record.handle,
        "tool_result_sha256": record.sha256,
        "tool_result_storage_encoding": record.storage_encoding,
        "tool_result_stored_size_bytes": record.stored_size_bytes,
        "retrieve_hint": _DISPATCH_TRUNCATION_RETRIEVE_HINT,
    }


def _attach_dispatch_truncated_snapshot(
    *,
    content: str,
    snapshot: dict[str, Any] | None,
) -> str:
    if not snapshot:
        return content
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return content
    if not isinstance(payload, dict) or payload.get("result_truncated") is not True:
        return content
    payload.update(snapshot)
    return json.dumps(payload, ensure_ascii=False)


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

def _denial_reason(content: Any) -> str:
    payload: Any = content
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            return "denied"
    if isinstance(payload, dict) and payload.get("status") == "approval_denied":
        return "approval_denied"
    return "denied"

def _has_live_approval_surface(ctx: ToolContext | None) -> bool:
    return ctx is None or ctx.interaction_mode is InteractionMode.INTERACTIVE


def _result_payload(content: Any) -> dict[str, Any] | None:
    payload: Any = content
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None
    return payload


def _result_status(content: Any) -> str | int | None:
    payload = _result_payload(content)
    if payload is None:
        return None
    status = payload.get("status")
    if isinstance(status, int) and not isinstance(status, bool):
        return status
    if not isinstance(status, str):
        return None
    normalized = status.strip().lower()
    return normalized or None


def _structured_receipt_success(payload: dict[str, Any]) -> bool | None:
    if payload.get("timed_out") is True:
        return False

    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return exit_code == 0

    for key in ("success", "ok"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
    return None


def _status_indicates_non_success(status: str) -> bool:
    normalized = (
        status.replace("-", "_").replace(" ", "_").replace(".", "_")
    )
    return any(
        part in _NON_SUCCESS_RESULT_STATUS_PARTS
        for part in normalized.split("_")
        if part
    )


def _is_successful_projection_result(
    *,
    result: Any,
    denial: bool,
    execution_status: Any,
) -> bool:
    if denial or _extract_pending_approval(result) is not None:
        return False
    if execution_status is not None:
        return execution_status.get("status") == "success"

    payload = _result_payload(result)
    if payload is None:
        return True

    receipt_success = _structured_receipt_success(payload)
    if receipt_success is False:
        return False
    if "status" not in payload:
        return True

    status = _result_status(payload)
    if isinstance(status, int):
        return 200 <= status < 400
    if status == "router_control":
        return payload.get("accepted") is True
    if status is None or _status_indicates_non_success(status):
        return False
    return True


def _projection_failure_result(
    *,
    call: ToolCall,
    artifacts: list[dict[str, Any]],
) -> ToolResult:
    envelope = build_tool_failure_envelope(
        RuntimeError(_TOOL_RESULT_PROJECTION_FAILED),
        call.tool_name,
        error_class_override=_TOOL_RESULT_PROJECTION_FAILED,
        user_message_override="The tool result could not be safely projected.",
    )
    status = {
        "version": 1,
        "status": "error",
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "reason": _TOOL_RESULT_PROJECTION_FAILED,
        "source": "tool_runtime",
        "preservation_class": "diagnostic",
    }
    return ToolResult(
        tool_use_id=call.tool_use_id,
        tool_name=call.tool_name,
        content=json.dumps(envelope),
        is_error=True,
        artifacts=artifacts,
        execution_status=normalize_execution_status(status),
    )


def _project_successful_result(
    *,
    call: ToolCall,
    result: Any,
    artifacts: list[dict[str, Any]],
    registered: Any,
) -> tuple[Any, list[dict[str, Any]], bool] | ToolResult:
    model_projector = registered.spec.model_result_projector
    sources_projector = registered.spec.result_sources_projector
    if model_projector is None and sources_projector is None:
        return result, [], False

    full_redacted_content = result if isinstance(result, str) else str(result)
    sources: list[dict[str, Any]] = []
    try:
        if sources_projector is not None:
            sources = sources_projector(full_redacted_content)
            if not isinstance(sources, list) or any(
                not isinstance(source, dict) for source in sources
            ):
                raise TypeError("result sources projector returned an invalid value")
        if model_projector is not None:
            model_content = model_projector(full_redacted_content)
            if not isinstance(model_content, str):
                raise TypeError("model result projector returned a non-string value")
            return model_content, sources, True
    except Exception as exc:
        log.warning(
            "dispatch.tool_result_projection_failed",
            tool=call.tool_name,
            error_type=type(exc).__name__,
        )
        return _projection_failure_result(call=call, artifacts=artifacts)
    return result, sources, False


async def finalize(
    call: ToolCall,
    ctx: ToolContext | None,
    raw_result: Any,
    exception: BaseException | None,
    artifact_start: int,
    budget_tracker: ToolResultBudgetTracker,
    registered: Any,
) -> ToolResult:
    """Build the canonical :class:`ToolResult` for one dispatched call.

    Branches on the orchestrator-provided outcome state. ``exception``
    takes precedence — when set, ``raw_result`` is ignored and a runtime
    error envelope is returned. With no exception, an
    ``approval_required`` payload returned to an unattended surface
    short-circuits to the approval-pending envelope. Otherwise the result
    flows through the budget tracker (unless artifacts were published)
    and execution-status pipeline.
    """
    # ---------------- Exception branch ----------------
    if exception is not None:
        if isinstance(exception, ToolRunBudgetExceededError):
            payload = {
                "status": "control",
                "tool": call.tool_name,
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
            return ToolResult(
                tool_use_id=call.tool_use_id,
                tool_name=call.tool_name,
                content=json.dumps(payload),
                is_error=False,
                execution_status=normalize_execution_status(status),
            )

        envelope = redact_secret_value(
            build_tool_failure_envelope(exception, call.tool_name)
        )
        log.warning(
            "dispatch.tool_failed",
            tool=call.tool_name,
            tool_use_id=call.tool_use_id,
            agent_id=ctx.agent_id if ctx else None,
            session_key=ctx.session_key if ctx else None,
            error_class=envelope["error_class"],
            retry_allowed=envelope["retry_allowed"],
            # ``finalize`` runs from the dispatcher's ``finally`` block after the
            # ``except`` clause has already handled the exception, so
            # ``sys.exc_info()`` is empty here — pass the exception object
            # explicitly so the traceback reaches debug.log.
            exc_info=exception,
        )
        status = {
            "version": 1,
            "status": "error",
            "exit_code": None,
            "timed_out": False,
            "truncated": False,
            "reason": "runtime_error",
            "source": "tool_runtime",
            "preservation_class": "diagnostic",
        }
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content=json.dumps(envelope),
            is_error=True,
            execution_status=normalize_execution_status(status),
        )

    result = redact_secret_value(raw_result)

    # ---------------- Approval-on-unsupported-surface branch ----------------
    if not _has_live_approval_surface(ctx):
        pending = _extract_pending_approval(result)
        if pending is not None:
            surface = ctx.caller_kind.value if ctx else "unknown"
            log.warning(
                "dispatch.approval_required_unsupported_surface",
                tool=call.tool_name,
                surface=surface,
                approval_id=pending.get("approval_id"),
                tool_use_id=call.tool_use_id,
                agent_id=ctx.agent_id if ctx else None,
                session_key=ctx.session_key if ctx else None,
            )
            user_message = (
                f"Tool '{call.tool_name}' requires human approval, but the {surface} "
                "surface has no interactive approval path. Re-run with --interactive "
                "or from an interactive operator surface."
            )
            envelope = build_tool_failure_envelope(
                ValueError("approval required"),
                call.tool_name,
                policy_denial=True,
                error_class_override="UnsupportedSurface",
                user_message_override=user_message,
            )
            status = {
                "version": 1,
                "status": "unknown",
                "exit_code": None,
                "timed_out": False,
                "truncated": False,
                "reason": "approval_pending",
                "source": "tool_runtime",
                "preservation_class": "ephemeral",
            }
            return ToolResult(
                tool_use_id=call.tool_use_id,
                tool_name=call.tool_name,
                content=json.dumps(envelope),
                is_error=False,
                execution_status=normalize_execution_status(status),
            )

    # ---------------- Standard branch (success or denial payload) ----------------
    denial = is_denial_payload(result)
    denial_reason = _denial_reason(result) if denial else None
    execution_status = execution_status_for_tool_result(call.tool_name, result)
    if execution_status is None:
        pending = _extract_pending_approval(result)
        if pending is not None:
            execution_status = {
                "version": 1,
                "status": "unknown",
                "exit_code": None,
                "timed_out": False,
                "truncated": False,
                "reason": "approval_pending",
                "source": "tool_runtime",
                "preservation_class": "ephemeral",
            }
    if execution_status is None and denial:
        execution_status = {
            "version": 1,
            "status": "error",
            "exit_code": None,
            "timed_out": False,
            "truncated": False,
            "reason": denial_reason or "denied",
            "source": "tool_runtime",
            "preservation_class": "diagnostic",
        }
    if execution_status is not None:
        execution_status = normalize_execution_status(execution_status)
        log.debug(
            "tool.execution_status_normalized",
            tool=call.tool_name,
            status=execution_status["status"],
            reason=execution_status["reason"],
            source=execution_status["source"],
        )

    status_is_error = derive_is_error(execution_status) if execution_status else False
    is_error = denial or status_is_error

    artifacts = (
        list(ctx.published_artifacts[artifact_start:]) if ctx is not None else []
    )
    sources: list[dict[str, Any]] = []
    model_result_projected = False
    projected_result = result
    if _is_successful_projection_result(
        result=result,
        denial=denial,
        execution_status=execution_status,
    ):
        projection = _project_successful_result(
            call=call,
            result=result,
            artifacts=artifacts,
            registered=registered,
        )
        if isinstance(projection, ToolResult):
            return projection
        projected_result, sources, model_result_projected = projection

    if artifacts:
        content = projected_result
    else:
        budget_class = resolve_budget_class(
            call.tool_name,
            registered.spec.result_budget_class,
        )
        raw_budget_content = (
            projected_result
            if isinstance(projected_result, str)
            else str(projected_result)
        )
        budgeted = await budget_tracker.normalize(
            tool_name=call.tool_name,
            content=raw_budget_content,
            budget_class=budget_class,
            is_error=is_error,
            arguments=call.arguments,
        )
        content = budgeted.content
        if budgeted.changed:
            content = _attach_dispatch_truncated_snapshot(
                content=content,
                snapshot=_store_dispatch_truncated_snapshot(
                    ctx=ctx,
                    call=call,
                    content=raw_budget_content,
                ),
            )
        if budgeted.changed and execution_status is not None:
            execution_status = mark_execution_status_truncated(execution_status)
    return ToolResult(
        tool_use_id=call.tool_use_id,
        tool_name=call.tool_name,
        content=content,
        is_error=is_error,
        artifacts=artifacts,
        execution_status=execution_status,
        sources=sources,
        terminates_turn=(
            call.tool_name == "router_control"
            and router_control_payload_terminates_turn(
                result if model_result_projected else content
            )
        ),
    )
