"""Meta-skill run history RPC handlers."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.protocol import ERROR_UNAUTHORIZED
from opensquilla.gateway.rpc import (
    RpcContext,
    RpcHandlerError,
    RpcUnavailableError,
    get_dispatcher,
)
from opensquilla.gateway.scopes import ADMIN_SCOPE
from opensquilla.persistence.meta_run_query import parse_since_ms
from opensquilla.persistence.meta_run_writer import (
    RunRecord,
    StepRecord,
    summarize_run_record,
)
from opensquilla.skills.meta.author_seed import draft_meta_skill_seed

_d = get_dispatcher()


def _writer_from_context(ctx: RpcContext) -> Any:
    writer = getattr(ctx, "meta_run_writer", None)
    if writer is not None:
        return writer
    raise RpcUnavailableError("meta run writer is not configured")


def _serialize_record(record: RunRecord) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "meta_skill_name": record.meta_skill_name,
        "meta_skill_digest": record.meta_skill_digest,
        "plan_snapshot_json": record.plan_snapshot_json,
        "triggered_by": record.triggered_by,
        "session_key": record.session_key,
        "turn_id": record.turn_id,
        "owner_pid": record.owner_pid,
        "status": record.status,
        "started_at_ms": record.started_at_ms,
        "ended_at_ms": record.ended_at_ms,
        "inputs_json": record.inputs_json,
        "final_text": record.final_text,
        "failed_step_id": record.failed_step_id,
        "error": record.error,
        "truncated_fields": list(record.truncated_fields),
        "steps": [_serialize_step(step) for step in record.steps],
        "summary": summarize_run_record(record),
    }


def _serialize_record_summary(record: RunRecord) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "meta_skill_name": record.meta_skill_name,
        "triggered_by": record.triggered_by,
        "session_key": record.session_key,
        "turn_id": record.turn_id,
        "status": record.status,
        "started_at_ms": record.started_at_ms,
        "ended_at_ms": record.ended_at_ms,
        "failed_step_id": record.failed_step_id,
        "error_present": bool(record.error),
        "truncated_fields": list(record.truncated_fields),
        "summary": summarize_run_record(record),
    }


def _serialize_step(step: StepRecord) -> dict[str, Any]:
    return {
        "run_id": step.run_id,
        "step_id": step.step_id,
        "step_kind": step.step_kind,
        "declared_skill": step.declared_skill,
        "effective_skill": step.effective_skill,
        "status": step.status,
        "started_at_ms": step.started_at_ms,
        "ended_at_ms": step.ended_at_ms,
        "rendered_inputs_json": step.rendered_inputs_json,
        "output_text": step.output_text,
        "error": step.error,
        "substitute_step_id": step.substitute_step_id,
        "truncated_fields": list(step.truncated_fields),
    }


def _hydrate_records(writer: Any, rows: list[RunRecord]) -> list[RunRecord]:
    hydrate = getattr(writer, "hydrate_runs", None)
    if callable(hydrate):
        return list(hydrate(rows))
    return rows


def _bounded_limit(value: Any, *, default: int = 50, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 1:
        return default
    return min(parsed, maximum)


def _parse_since_param(value: Any) -> int | None:
    if value is None:
        return None
    return parse_since_ms(str(value))


def _session_key_for_history(params: dict[str, Any], ctx: RpcContext) -> str | None:
    session_key = params.get("sessionKey") or params.get("session_key")
    if ADMIN_SCOPE in ctx.principal.scopes or ctx.principal.is_owner:
        if session_key:
            return str(session_key)
        return None
    raise RpcHandlerError(
        ERROR_UNAUTHORIZED,
        "meta run history requires owner/admin scope.",
    )


def _existing_specs(ctx: RpcContext) -> list[Any]:
    loader = getattr(ctx, "skill_loader", None)
    if loader is None:
        return []
    try:
        return list(loader.load_all())
    except Exception:  # noqa: BLE001 - draft conflict detection is advisory
        return []


@_d.method("meta.runs.list", scope="operator.read")
async def _handle_meta_runs_list(params: Any, ctx: RpcContext) -> dict[str, Any]:
    writer = _writer_from_context(ctx)
    p = params if isinstance(params, dict) else {}
    session_key = _session_key_for_history(p, ctx)
    rows = writer.list_runs(
        name=p.get("name"),
        status=p.get("status"),
        session_key=session_key,
        since_ms=_parse_since_param(p.get("since")),
        limit=_bounded_limit(p.get("limit")),
    )
    return {
        "runs": [
            _serialize_record_summary(row)
            for row in _hydrate_records(writer, rows)
        ]
    }


@_d.method("meta.runs.show", scope="operator.admin")
async def _handle_meta_runs_show(params: Any, ctx: RpcContext) -> dict[str, Any]:
    writer = _writer_from_context(ctx)
    p = params if isinstance(params, dict) else {}
    run_id = str(p.get("runId") or p.get("run_id") or "")
    record = writer.get_run(run_id)
    if record is None:
        return {"run": None}
    return {"run": _serialize_record(record)}


@_d.method("meta.runs.failures", scope="operator.read")
async def _handle_meta_runs_failures(params: Any, ctx: RpcContext) -> dict[str, Any]:
    writer = _writer_from_context(ctx)
    p = params if isinstance(params, dict) else {}
    session_key = _session_key_for_history(p, ctx)
    rows = writer.list_failures(
        name=p.get("name"),
        session_key=session_key,
        since_ms=_parse_since_param(p.get("since")),
        limit=_bounded_limit(p.get("limit")),
    )
    return {
        "runs": [
            _serialize_record_summary(row)
            for row in _hydrate_records(writer, rows)
        ]
    }


@_d.method("meta.runs.draft", scope="operator.admin")
async def _handle_meta_runs_draft(params: Any, ctx: RpcContext) -> dict[str, Any]:
    writer = _writer_from_context(ctx)
    p = params if isinstance(params, dict) else {}
    run_id = str(p.get("runId") or p.get("run_id") or "")
    record = writer.get_run(run_id)
    if record is None:
        return {"draft": None}
    return {
        "draft": draft_meta_skill_seed(
            record,
            existing_specs=_existing_specs(ctx),
        ),
    }
