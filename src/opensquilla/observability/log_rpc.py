"""RPC payload builders for log and trace observability surfaces."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from opensquilla.observability.trace import load_trace_events
from opensquilla.observability.turn_call_log import (
    LOG_DIR_ENV,
    TURN_CALL_LOG_DIR_ENV,
    TURN_CALL_LOG_ENABLED_VALUES,
    TURN_CALL_LOG_ENV,
    is_turn_call_log_enabled,
    resolve_turn_call_log_dir_with_source,
)
from opensquilla.paths import default_opensquilla_home


def logs_status_rpc_payload(
    *,
    config: Any | None,
    diagnostics_state: Any | None,
    diagnostics_status: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the RPC wire payload for ``logs.status``."""

    raw_dir, raw_dir_source = resolve_turn_call_log_dir_with_source()
    configured_debug_log, configured_debug_log_source = _configured_debug_log_path()
    trace_dir, trace_dir_source = _configured_trace_log_dir()
    trace_files = sorted(trace_dir.glob("traces-*.jsonl")) if trace_dir.is_dir() else []
    active_tail_path = _find_log_file()

    raw_turn_call = diagnostics_status["raw_turn_call"]
    return {
        "raw_turn_call_log": {
            "enabled": is_turn_call_log_enabled(diagnostics_state),
            "source": raw_turn_call["source"],
            "enable_env": _env_status(
                TURN_CALL_LOG_ENV,
                truthy_values=TURN_CALL_LOG_ENABLED_VALUES,
            ),
            "enabled_values": sorted(TURN_CALL_LOG_ENABLED_VALUES),
            "directory": {
                "path": str(raw_dir),
                "source": raw_dir_source,
                "exists": raw_dir.exists(),
            },
        },
        "gateway_file_log": {
            "enabled": bool(_config_value(config, "log_file_enabled", True)),
            "level": str(_config_value(config, "log_level", "DEBUG")),
            "path": str(configured_debug_log),
            "path_source": configured_debug_log_source,
            "exists": configured_debug_log.exists(),
            "active_tail_path": str(active_tail_path) if active_tail_path is not None else None,
            "active_tail_path_exists": active_tail_path.exists() if active_tail_path else False,
        },
        "trace_log": {
            "directory": {
                "path": str(trace_dir),
                "source": trace_dir_source,
                "exists": trace_dir.exists(),
            },
            "file_count": len(trace_files),
            "latest_path": str(trace_files[-1]) if trace_files else None,
        },
        "diagnostics_enabled": {
            "configured": bool(_config_value(config, "diagnostics_enabled", False)),
            "effective": diagnostics_status["enabled"],
            "detail": diagnostics_status["detail"],
            "controls_raw_turn_call": raw_turn_call["source"] == "runtime",
            "raw_source": raw_turn_call["source"],
        },
        "diagnostics": dict(diagnostics_status),
        "env": {
            TURN_CALL_LOG_ENV: _env_status(
                TURN_CALL_LOG_ENV,
                truthy_values=TURN_CALL_LOG_ENABLED_VALUES,
            ),
            TURN_CALL_LOG_DIR_ENV: _env_status(TURN_CALL_LOG_DIR_ENV),
            LOG_DIR_ENV: _env_status(LOG_DIR_ENV),
        },
    }


def logs_trace_rpc_payload(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build the RPC wire payload for ``logs.trace``."""

    p = params or {}
    trace_id = str(p.get("trace_id") or "").strip()
    try:
        limit = max(1, min(int(p.get("limit", 1000)), 5000))
    except (TypeError, ValueError):
        limit = 1000
    if not trace_id:
        return {"trace_id": "", "events": [], "count": 0, "total": 0}

    events = load_trace_events(trace_id)
    limited = events[-limit:]
    return {
        "trace_id": trace_id,
        "events": [event.to_dict() for event in limited],
        "count": len(limited),
        "total": len(events),
    }


def logs_tail_rpc_payload(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build the RPC wire payload for ``logs.tail``."""

    p = params or {}
    limit = min(p.get("limit", 100), 1000)
    level_filter = (p.get("level", "") or "").upper()
    cursor = p.get("cursor", 0)

    log_file = _find_log_file()
    if log_file is None or not log_file.exists():
        return {"lines": [], "cursor": 0, "has_more": False}

    file_size = log_file.stat().st_size
    if cursor >= file_size:
        return {"lines": [], "cursor": file_size, "has_more": False}

    with log_file.open(encoding="utf-8", errors="replace") as f:
        f.seek(cursor)
        raw_lines = f.readlines()
        new_cursor = f.tell()

    if level_filter:
        filtered = [ln for ln in raw_lines if level_filter in ln.upper()]
    else:
        filtered = raw_lines

    has_more = len(filtered) > limit
    lines = [ln.rstrip() for ln in filtered[-limit:]]

    return {"lines": lines, "cursor": new_cursor, "has_more": has_more}


def _non_empty_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value


def _find_log_file() -> Path | None:
    """Find the structlog output file."""

    env_log_dir = _non_empty_env(LOG_DIR_ENV)
    if env_log_dir:
        candidates = [Path(env_log_dir) / "debug.log"]
    else:
        candidates = [
            default_opensquilla_home() / "logs" / "debug.log",
            Path("data") / "debug.log",
            Path("debug.log"),
        ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _env_status(name: str, *, truthy_values: frozenset[str] | None = None) -> dict[str, Any]:
    value = os.environ.get(name)
    stripped = value.strip() if value is not None else ""
    result: dict[str, Any] = {
        "name": name,
        "set": value is not None,
        "empty": value is not None and stripped == "",
    }
    if truthy_values is not None:
        result["truthy"] = stripped.lower() in truthy_values
    return result


def _configured_debug_log_path() -> tuple[Path, str]:
    log_dir = _non_empty_env(LOG_DIR_ENV)
    if log_dir is not None:
        return Path(log_dir) / "debug.log", LOG_DIR_ENV
    return default_opensquilla_home() / "logs" / "debug.log", "default"


def _configured_trace_log_dir() -> tuple[Path, str]:
    log_dir = _non_empty_env(LOG_DIR_ENV)
    if log_dir is not None:
        return Path(log_dir), LOG_DIR_ENV
    return default_opensquilla_home() / "logs", "default"


def _config_value(config: Any | None, name: str, default: Any) -> Any:
    if config is None:
        return default
    return getattr(config, name, default)


__all__ = [
    "logs_status_rpc_payload",
    "logs_tail_rpc_payload",
    "logs_trace_rpc_payload",
]
