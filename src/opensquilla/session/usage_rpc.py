"""RPC payload builders for usage and cost session surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opensquilla.session.cost_rollup import rollup_cost_source


async def usage_status_rpc_payload(
    *,
    session_manager: Any | None,
    usage_tracker: Any | None,
    config: Any | None,
    now_ms: int,
) -> dict[str, Any]:
    """Build the RPC wire payload for ``usage.status``."""

    tracker_rows = _tracker_rows(usage_tracker, config=config, now_ms=now_ms)

    if session_manager is None:
        return _usage_status_payload(rows=tracker_rows, active_sessions=len(tracker_rows))
    try:
        sessions = await session_manager.list_sessions()
        rows = []
        active = sum(1 for s in sessions if _field(s, "status", "") == "running")
        for session in sessions:
            rows.append(_session_usage_row(session, config=config))
        rows = _append_tracker_only_rows(rows, tracker_rows)
        tracker_only_count = len(rows) - len(sessions)
        return _usage_status_payload(
            rows=rows,
            active_sessions=active + tracker_only_count,
        )
    except (AttributeError, NotImplementedError):
        return _usage_status_payload(rows=tracker_rows, active_sessions=len(tracker_rows))


async def usage_cost_rpc_payload(
    *,
    session_manager: Any | None,
    usage_tracker: Any | None,
    config: Any | None,
    now_ms: int,
) -> dict[str, Any]:
    """Build the RPC wire payload for ``usage.cost``."""

    tracker_rows = _tracker_rows(usage_tracker, config=config, now_ms=now_ms)

    if session_manager is None:
        return _usage_cost_payload(tracker_rows)
    try:
        sessions = await session_manager.list_sessions()
        breakdown = [_session_usage_row(session, config=config) for session in sessions]
        breakdown = _append_tracker_only_rows(breakdown, tracker_rows)
        return _usage_cost_payload(breakdown)
    except (AttributeError, NotImplementedError):
        return _usage_cost_payload(tracker_rows)


def _usage_status_payload(
    *,
    rows: list[dict[str, Any]],
    active_sessions: int,
) -> dict[str, Any]:
    totals = _usage_totals(rows)
    return {
        "totalSessions": len(rows),
        "activeSessions": active_sessions,
        "totalInputTokens": totals["input"],
        "totalOutputTokens": totals["output"],
        "totalTokens": totals["input"] + totals["output"],
        "totalCostUsd": round(float(totals["cost"]), 6),
        "totalCacheReadTokens": totals["cache_read"],
        "totalCacheWriteTokens": totals["cache_write"],
        "sessions": rows,
    }


def _usage_cost_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "breakdown": rows,
        "totalCostUsd": round(float(_usage_totals(rows)["cost"]), 6),
    }


def _field(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _first_field(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = _field(source, name)
        if value is not None:
            return value
    return default


def _resolved_session_cost_fields(
    source: Any,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    ephemeral: bool = False,
) -> dict[str, Any]:
    legacy_total = _field(source, "estimated_cost_usd")
    total_cost = _field(source, "total_cost_usd")

    billed_cost = _field(source, "billed_cost_usd")
    if billed_cost is None:
        billed_cost = _field(source, "billed_cost", 0.0) or 0.0

    estimated_component = _field(source, "estimated_cost_component_usd")
    if estimated_component is None:
        source_name = _field(source, "cost_source")
        estimated_component = (
            float(total_cost or 0.0)
            if source_name in {None, "", "none", "opensquilla_estimate"}
            and not billed_cost
            else 0.0
        )

    missing_entries = _field(source, "missing_cost_entries", 0) or 0
    cost_source = _field(source, "cost_source")
    if total_cost is None:
        total_cost = legacy_total
    if (
        legacy_total
        and not billed_cost
        and not estimated_component
        and not missing_entries
        and cost_source in {None, "", "none", "opensquilla_estimate"}
    ):
        if not total_cost:
            total_cost = legacy_total
        estimated_component = legacy_total
    if total_cost is None:
        total_cost = 0.0

    if not cost_source or cost_source == "none":
        if billed_cost or estimated_component or missing_entries:
            cost_source = rollup_cost_source(
                billed_cost_usd=float(billed_cost or 0.0),
                estimated_cost_component_usd=float(estimated_component or 0.0),
                missing_cost_entries=int(missing_entries or 0),
            )
        elif input_tokens or output_tokens or cache_read_tokens or cache_write_tokens:
            cost_source = "unavailable"
        else:
            cost_source = "none"

    return {
        "cost_usd": float(total_cost or 0.0),
        "billed_cost_usd": float(billed_cost or 0.0),
        "estimated_cost_usd": float(estimated_component or 0.0),
        "cost_source": cost_source,
        "missing_cost_entries": int(missing_entries or 0),
        "cost_ephemeral": bool(ephemeral),
    }


def _usage_row(
    *,
    session_key: str,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    billed_cost_usd: float = 0.0,
    estimated_cost_usd: float = 0.0,
    cost_source: str = "none",
    missing_cost_entries: int = 0,
    cost_ephemeral: bool = False,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    created_at: int | None = None,
    updated_at: int | None = None,
    started_at: int | None = None,
    ended_at: int | None = None,
) -> dict[str, Any]:
    cost = round(cost_usd, 6)
    billed_cost = round(billed_cost_usd, 6)
    estimated_cost = round(estimated_cost_usd, 6)
    return {
        "sessionKey": session_key,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "costUsd": cost,
        "billedCostUsd": billed_cost,
        "estimatedCostUsd": estimated_cost,
        "costSource": cost_source,
        "missingCostEntries": missing_cost_entries,
        "costEphemeral": cost_ephemeral,
        "cacheReadTokens": cache_read_tokens,
        "cacheWriteTokens": cache_write_tokens,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "startedAt": started_at,
        "endedAt": ended_at,
        "model": model,
        "session": session_key,
        "key": session_key,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "billed_cost_usd": billed_cost,
        "estimated_cost_usd": estimated_cost,
        "cost_source": cost_source,
        "missing_cost_entries": missing_cost_entries,
        "cost_ephemeral": cost_ephemeral,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "created_at": created_at,
        "updated_at": updated_at,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def _tracker_rows(
    usage_tracker: Any | None,
    *,
    config: Any | None,
    now_ms: int,
) -> list[dict[str, Any]]:
    if usage_tracker is None:
        return []
    all_sessions = usage_tracker.all_sessions()
    if not all_sessions:
        return []

    config_model = _config_model(config)
    rows = []
    for session_key, usage in all_sessions.items():
        cache_read_tokens = getattr(usage, "cache_read_tokens", 0) or 0
        cache_write_tokens = getattr(usage, "cache_write_tokens", 0) or 0
        cost_fields = _resolved_session_cost_fields(
            usage,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            ephemeral=True,
        )
        cost_fields["cost_usd"] = usage.cost
        cost_fields["estimated_cost_usd"] = usage.cost
        cost_fields["cost_source"] = "opensquilla_estimate"
        row = _usage_row(
            session_key=session_key,
            model=usage.model_id or config_model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            **cost_fields,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            created_at=now_ms,
            updated_at=now_ms,
        )
        row["modelBreakdown"] = getattr(usage, "model_breakdown", [])
        rows.append(row)
    return rows


def _session_usage_row(session: Any, *, config: Any | None) -> dict[str, Any]:
    input_tokens = _first_field(session, "input_tokens", "total_input_tokens", default=0) or 0
    output_tokens = _first_field(session, "output_tokens", "total_output_tokens", default=0) or 0
    cache_read = _field(session, "cache_read", 0) or 0
    cache_write = _field(session, "cache_write", 0) or 0
    cost_fields = _resolved_session_cost_fields(
        session,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
    session_model = _field(session, "model") or _field(session, "model_override")
    if not session_model:
        session_model = _config_model(config)
    return _usage_row(
        session_key=_field(session, "session_key", "unknown"),
        model=session_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        **cost_fields,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        created_at=_field(session, "created_at"),
        updated_at=_field(session, "updated_at"),
        started_at=_field(session, "started_at"),
        ended_at=_field(session, "ended_at"),
    )


def _config_model(config: Any | None) -> str | None:
    llm = getattr(config, "llm", None) if config is not None else None
    return getattr(llm, "model", None) if llm is not None else None


def _append_tracker_only_rows(
    rows: list[dict[str, Any]],
    tracker_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge in-memory tracker rows into disk-loaded rows."""

    tracker_by_key = {tr["session"]: tr for tr in tracker_rows}
    seen = set()
    for row in rows:
        seen.add(row["session"])
        tracker_row = tracker_by_key.get(row["session"])
        if (
            tracker_row
            and tracker_row.get("modelBreakdown")
            and not row.get("modelBreakdown")
        ):
            row["modelBreakdown"] = tracker_row["modelBreakdown"]
    return rows + [row for row in tracker_rows if row["session"] not in seen]


def _usage_totals(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    total_in = sum(int(row["input_tokens"] or 0) for row in rows)
    total_out = sum(int(row["output_tokens"] or 0) for row in rows)
    total_cost = sum(float(row["cost_usd"] or 0.0) for row in rows)
    return {
        "input": total_in,
        "output": total_out,
        "cost": total_cost,
        "cache_read": sum(int(row["cache_read_tokens"] or 0) for row in rows),
        "cache_write": sum(int(row["cache_write_tokens"] or 0) for row in rows),
    }


__all__ = [
    "usage_cost_rpc_payload",
    "usage_status_rpc_payload",
]
