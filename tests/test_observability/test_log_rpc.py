from __future__ import annotations

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.diagnostics import DiagnosticsState, diagnostics_status_payload
from opensquilla.observability.log_rpc import (
    logs_status_rpc_payload,
    logs_tail_rpc_payload,
    logs_trace_rpc_payload,
)
from opensquilla.observability.trace import TraceContext, TraceEvent, write_trace_event


def _diagnostics_status(
    config: GatewayConfig,
    diagnostics_state: DiagnosticsState | None = None,
) -> dict:
    return diagnostics_status_payload(diagnostics_state, config)


def test_logs_status_rpc_payload_owns_log_status_wire_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("OPENSQUILLA_TURN_CALL_LOG", "1")
    log_file = tmp_path / "debug.log"
    log_file.write_text("2026-05-03 [INFO] opensquilla: selected\n", encoding="utf-8")
    config = GatewayConfig(log_file_enabled=False, log_level="INFO", diagnostics_enabled=True)

    payload = logs_status_rpc_payload(
        config=config,
        diagnostics_state=None,
        diagnostics_status=_diagnostics_status(config),
    )

    assert payload["raw_turn_call_log"]["enabled"] is True
    assert payload["raw_turn_call_log"]["source"] == "env"
    assert payload["gateway_file_log"] == {
        "enabled": False,
        "level": "INFO",
        "path": str(log_file),
        "path_source": "OPENSQUILLA_LOG_DIR",
        "exists": True,
        "active_tail_path": str(log_file),
        "active_tail_path_exists": True,
    }
    assert payload["diagnostics_enabled"]["configured"] is True
    assert payload["env"]["OPENSQUILLA_LOG_DIR"]["set"] is True


def test_logs_tail_rpc_payload_owns_tail_wire_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(tmp_path))
    log_file = tmp_path / "debug.log"
    log_file.write_text(
        "2026-05-03 [DEBUG] opensquilla: ignored\n"
        "2026-05-03 [INFO] opensquilla: selected\n",
        encoding="utf-8",
    )

    payload = logs_tail_rpc_payload({"limit": 10, "cursor": 0, "level": "INFO"})

    assert payload == {
        "lines": ["2026-05-03 [INFO] opensquilla: selected"],
        "cursor": log_file.stat().st_size,
        "has_more": False,
    }


def test_logs_trace_rpc_payload_owns_trace_wire_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(tmp_path))
    for seq in range(3):
        write_trace_event(
            TraceEvent(
                kind="turn_start",
                context=TraceContext.new(trace_id="trace-1", session_key=f"agent:main:{seq}"),
                seq=seq,
            ),
            log_dir=tmp_path,
        )

    payload = logs_trace_rpc_payload({"trace_id": "trace-1", "limit": 2})

    assert payload["trace_id"] == "trace-1"
    assert payload["count"] == 2
    assert payload["total"] == 3
    assert [event["session_key"] for event in payload["events"]] == [
        "agent:main:1",
        "agent:main:2",
    ]
