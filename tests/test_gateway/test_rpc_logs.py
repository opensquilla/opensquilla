from __future__ import annotations

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.diagnostics import DiagnosticsState
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.gateway.rpc_logs import _handle_logs_status, _handle_logs_tail
from opensquilla.observability.trace import TraceContext, TraceEvent, write_trace_event


@pytest.mark.asyncio
async def test_logs_tail_uses_opensquilla_log_dir_and_filters_level(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(tmp_path))
    log_file = tmp_path / "debug.log"
    log_file.write_text(
        "2026-05-03 [DEBUG] opensquilla: ignored\n"
        "2026-05-03 [INFO] opensquilla: selected\n",
        encoding="utf-8",
    )

    result = await _handle_logs_tail({"limit": 10, "cursor": 0, "level": "INFO"}, None)  # type: ignore[arg-type]

    assert result["lines"] == ["2026-05-03 [INFO] opensquilla: selected"]
    assert result["cursor"] == log_file.stat().st_size
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_logs_tail_missing_file_returns_empty_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(tmp_path))

    result = await _handle_logs_tail({"limit": 10, "cursor": 0}, None)  # type: ignore[arg-type]

    assert result == {"lines": [], "cursor": 0, "has_more": False}


@pytest.mark.asyncio
async def test_logs_status_reports_raw_capture_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("OPENSQUILLA_TURN_CALL_LOG", raising=False)
    monkeypatch.delenv("OPENSQUILLA_TURN_CALL_LOG_DIR", raising=False)
    monkeypatch.delenv("OPENSQUILLA_LOG_DIR", raising=False)

    result = await _handle_logs_status({}, RpcContext(conn_id="test", config=GatewayConfig()))

    assert result["raw_turn_call_log"]["enabled"] is False
    assert result["raw_turn_call_log"]["source"] == "off"
    assert result["raw_turn_call_log"]["enable_env"]["set"] is False
    assert result["raw_turn_call_log"]["enable_env"]["truthy"] is False
    assert result["raw_turn_call_log"]["directory"]["source"] == "default"
    assert result["diagnostics_enabled"]["configured"] is False
    assert result["diagnostics_enabled"]["effective"] is False
    assert result["diagnostics_enabled"]["detail"] == "off"
    assert result["diagnostics_enabled"]["controls_raw_turn_call"] is False


@pytest.mark.asyncio
async def test_logs_status_reports_truthy_and_falsy_raw_capture_env(monkeypatch) -> None:
    for value in ("1", "TRUE", " yes ", "on"):
        monkeypatch.setenv("OPENSQUILLA_TURN_CALL_LOG", value)
        result = await _handle_logs_status({}, RpcContext(conn_id="test", config=GatewayConfig()))
        assert result["raw_turn_call_log"]["enabled"] is True
        assert result["raw_turn_call_log"]["source"] == "env"
        assert result["raw_turn_call_log"]["enable_env"]["truthy"] is True

    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("OPENSQUILLA_TURN_CALL_LOG", value)
        result = await _handle_logs_status({}, RpcContext(conn_id="test", config=GatewayConfig()))
        assert result["raw_turn_call_log"]["enabled"] is False
        assert result["raw_turn_call_log"]["source"] == "off"
        assert result["raw_turn_call_log"]["enable_env"]["truthy"] is False


@pytest.mark.asyncio
async def test_logs_status_reports_runtime_raw_capture_source(monkeypatch) -> None:
    monkeypatch.delenv("OPENSQUILLA_TURN_CALL_LOG", raising=False)
    state = DiagnosticsState.from_config(GatewayConfig())
    state.set_runtime(enabled=True, raw=True)

    result = await _handle_logs_status(
        {},
        RpcContext(conn_id="test", config=GatewayConfig(), diagnostics_state=state),
    )

    assert result["raw_turn_call_log"]["enabled"] is True
    assert result["raw_turn_call_log"]["source"] == "runtime"
    assert result["diagnostics_enabled"]["effective"] is True
    assert result["diagnostics_enabled"]["detail"] == "raw"


@pytest.mark.asyncio
async def test_logs_status_reports_env_source_when_env_and_runtime_raw_are_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_TURN_CALL_LOG", "1")
    state = DiagnosticsState.from_config(GatewayConfig())
    state.set_runtime(enabled=True, raw=True)

    result = await _handle_logs_status(
        {},
        RpcContext(conn_id="test", config=GatewayConfig(), diagnostics_state=state),
    )

    assert result["raw_turn_call_log"]["enabled"] is True
    assert result["raw_turn_call_log"]["source"] == "env"
    assert result["diagnostics_enabled"]["raw_source"] == "env"


@pytest.mark.asyncio
async def test_logs_status_resolves_raw_directory_precedence_without_creating_paths(
    tmp_path, monkeypatch
) -> None:
    raw_dir = tmp_path / "raw"
    shared_log_dir = tmp_path / "shared"
    monkeypatch.setenv("OPENSQUILLA_TURN_CALL_LOG_DIR", str(raw_dir))
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(shared_log_dir))

    result = await _handle_logs_status({}, RpcContext(conn_id="test", config=GatewayConfig()))

    assert result["raw_turn_call_log"]["directory"] == {
        "path": str(raw_dir),
        "source": "OPENSQUILLA_TURN_CALL_LOG_DIR",
        "exists": False,
    }
    assert not raw_dir.exists()
    assert not shared_log_dir.exists()

    monkeypatch.setenv("OPENSQUILLA_TURN_CALL_LOG_DIR", " ")
    result = await _handle_logs_status({}, RpcContext(conn_id="test", config=GatewayConfig()))

    assert result["raw_turn_call_log"]["directory"] == {
        "path": str(shared_log_dir),
        "source": "OPENSQUILLA_LOG_DIR",
        "exists": False,
    }
    assert not raw_dir.exists()
    assert not shared_log_dir.exists()


@pytest.mark.asyncio
async def test_logs_status_reports_gateway_file_log_path_and_existence(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(tmp_path))
    log_file = tmp_path / "debug.log"
    log_file.write_text("2026-05-03 [INFO] opensquilla: selected\n", encoding="utf-8")
    config = GatewayConfig(log_file_enabled=False, log_level="INFO", diagnostics_enabled=True)

    result = await _handle_logs_status({}, RpcContext(conn_id="test", config=config))

    assert result["gateway_file_log"]["enabled"] is False
    assert result["gateway_file_log"]["level"] == "INFO"
    assert result["gateway_file_log"]["path"] == str(log_file)
    assert result["gateway_file_log"]["path_source"] == "OPENSQUILLA_LOG_DIR"
    assert result["gateway_file_log"]["exists"] is True
    assert result["gateway_file_log"]["active_tail_path"] == str(log_file)
    assert result["gateway_file_log"]["active_tail_path_exists"] is True
    assert result["diagnostics_enabled"]["configured"] is True
    assert result["diagnostics_enabled"]["effective"] is True
    assert result["diagnostics_enabled"]["detail"] == "standard"
    assert result["diagnostics_enabled"]["controls_raw_turn_call"] is False


@pytest.mark.asyncio
async def test_logs_status_reports_trace_log_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(tmp_path))
    write_trace_event(
        TraceEvent(kind="turn_start", context=TraceContext.new(trace_id="trace-1")),
        log_dir=tmp_path,
    )

    result = await _handle_logs_status({}, RpcContext(conn_id="test", config=GatewayConfig()))

    assert result["trace_log"] == {
        "directory": {
            "path": str(tmp_path),
            "source": "OPENSQUILLA_LOG_DIR",
            "exists": True,
        },
        "file_count": 1,
        "latest_path": str(next(tmp_path.glob("traces-*.jsonl"))),
    }


@pytest.mark.asyncio
async def test_logs_trace_returns_persisted_trace_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(tmp_path))
    write_trace_event(
        TraceEvent(
            kind="turn_start",
            context=TraceContext.new(
                trace_id="trace-1",
                session_key="agent:main:test",
                turn_id="turn-1",
            ),
            seq=1,
        ),
        log_dir=tmp_path,
    )
    ctx = RpcContext(conn_id="test", config=GatewayConfig())

    response = await get_dispatcher().dispatch(
        "req-1", "logs.trace", {"trace_id": "trace-1"}, ctx
    )

    assert response.ok is True
    assert response.payload["trace_id"] == "trace-1"
    assert response.payload["count"] == 1
    assert response.payload["events"][0]["kind"] == "turn_start"
    assert response.payload["events"][0]["session_key"] == "agent:main:test"


@pytest.mark.asyncio
async def test_logs_status_is_mounted_on_dispatcher(monkeypatch) -> None:
    monkeypatch.delenv("OPENSQUILLA_TURN_CALL_LOG", raising=False)
    ctx = RpcContext(conn_id="test", config=GatewayConfig())

    response = await get_dispatcher().dispatch("req-1", "logs.status", {}, ctx)

    assert response.ok is True
    assert isinstance(response.payload, dict)
    assert response.payload["raw_turn_call_log"]["enabled"] is False
