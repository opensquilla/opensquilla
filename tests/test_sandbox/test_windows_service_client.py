from __future__ import annotations

import threading
from pathlib import Path

import pytest


def test_install_policy_request_rejects_non_appcontainer_sid() -> None:
    from opensquilla.sandbox.windows_service_client import InstallPolicyRequest

    with pytest.raises(ValueError, match="AppContainer SID"):
        InstallPolicyRequest(
            run_id="run-1",
            appcontainer_sid="S-1-5-21-123",
            proxy_host="127.0.0.1",
            proxy_port=48123,
            ttl_seconds=60,
        )


def test_new_broker_state_defaults_to_localhost_tcp(tmp_path: Path) -> None:
    from opensquilla.sandbox.windows_service_ipc import new_broker_state

    state = new_broker_state(base_dir=tmp_path)

    assert state.ipc_kind == "tcp"
    assert state.broker_host == "127.0.0.1"
    assert 1 <= state.broker_port <= 65535
    assert state.to_json()["ipc_kind"] == "tcp"
    assert state.to_json()["broker_host"] == "127.0.0.1"
    assert isinstance(state.to_json()["broker_port"], int)


def test_request_sync_supports_localhost_tcp_ipc(tmp_path: Path) -> None:
    from multiprocessing.connection import Listener

    from opensquilla.sandbox.windows_service_ipc import (
        BrokerConnectionState,
        request_sync,
    )

    authkey_hex = "01" * 32
    listener = Listener(("127.0.0.1", 0), family="AF_INET", authkey=bytes.fromhex(authkey_hex))
    host, port = listener.address

    def serve_once() -> None:
        conn = listener.accept()
        try:
            assert conn.recv() == {"op": "health"}
            conn.send({"status": "ok", "admin": True})
        finally:
            conn.close()
            listener.close()

    thread = threading.Thread(target=serve_once)
    thread.start()
    try:
        response = request_sync(
            BrokerConnectionState(
                pipe_name=r"\\.\pipe\unused",
                authkey_hex=authkey_hex,
                state_file=tmp_path / "state.json",
                ipc_kind="tcp",
                broker_host=host,
                broker_port=port,
            ),
            {"op": "health"},
        )
    finally:
        thread.join(timeout=5)

    assert response == {"status": "ok", "admin": True}


def test_install_policy_request_rejects_non_loopback_proxy() -> None:
    from opensquilla.sandbox.windows_service_client import InstallPolicyRequest

    with pytest.raises(ValueError, match="loopback"):
        InstallPolicyRequest(
            run_id="run-1",
            appcontainer_sid="S-1-15-2-123",
            proxy_host="192.168.1.2",
            proxy_port=48123,
            ttl_seconds=60,
        )


def test_install_policy_payload_shape() -> None:
    from opensquilla.sandbox.windows_service_client import InstallPolicyRequest

    request = InstallPolicyRequest(
        run_id="run-1",
        appcontainer_sid="S-1-15-2-123",
        proxy_host="127.0.0.1",
        proxy_port=48123,
        ttl_seconds=60,
    )

    assert request.to_payload() == {
        "op": "install_policy",
        "run_id": "run-1",
        "appcontainer_sid": "S-1-15-2-123",
        "proxy_host": "127.0.0.1",
        "proxy_port": 48123,
        "ttl_seconds": 60,
    }


@pytest.mark.asyncio
async def test_service_dispatch_install_policy_calls_wfp(monkeypatch) -> None:
    from opensquilla.sandbox import windows_service_client

    calls = []

    def fake_install(**kwargs):
        calls.append(kwargs)
        return (11, 12, 13, 14)

    monkeypatch.setattr(
        windows_service_client.windows_wfp,
        "install_wfp_policy",
        fake_install,
    )

    response = await windows_service_client.dispatch_service_request(
        {
            "op": "install_policy",
            "run_id": "run-1",
            "appcontainer_sid": "S-1-15-2-123",
            "proxy_host": "127.0.0.1",
            "proxy_port": 48123,
            "ttl_seconds": 60,
        }
    )

    assert response["status"] == "ok"
    assert response["filter_ids"] == [11, 12, 13, 14]
    assert calls[0]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_health_reports_ready_when_broker_answers() -> None:
    from opensquilla.sandbox.setup_state import SandboxSetupState
    from opensquilla.sandbox.windows_service_client import WindowsSandboxServiceClient

    async def transport(payload):
        assert payload == {"op": "health"}
        return {"status": "ok", "admin": True, "detail": "ready"}

    client = WindowsSandboxServiceClient(transport=transport)

    result = await client.health()

    assert result.state is SandboxSetupState.READY
    assert result.message == "Windows sandbox service is ready."
    assert result.detail == "ready"


@pytest.mark.asyncio
async def test_ensure_setup_launches_broker_when_not_reachable(tmp_path: Path) -> None:
    from opensquilla.sandbox.setup_state import SandboxSetupState
    from opensquilla.sandbox.windows_service_client import WindowsSandboxServiceClient

    launched = []

    async def transport(payload):
        if payload == {"op": "health"} and not launched:
            raise ConnectionError("missing broker")
        return {"status": "ok", "admin": True}

    def launcher(state):
        launched.append(state)

    client = WindowsSandboxServiceClient(
        pipe_name=r"\\.\pipe\opensquilla-test-service",
        state_dir=tmp_path,
        transport=transport,
        broker_launcher=launcher,
        setup_timeout_s=0.25,
        setup_poll_interval_s=0.01,
    )

    result = await client.ensure_setup()

    assert result.state is SandboxSetupState.READY
    assert launched
    assert launched[0].pipe_name == r"\\.\pipe\opensquilla-test-service"
    assert launched[0].ipc_kind == "tcp"
    assert launched[0].broker_host == "127.0.0.1"
    assert 1 <= launched[0].broker_port <= 65535
    assert (tmp_path / "windows-sandbox-service.json").exists()


@pytest.mark.asyncio
async def test_ensure_setup_fails_when_broker_never_becomes_ready(tmp_path: Path) -> None:
    from opensquilla.sandbox.setup_state import SandboxSetupState
    from opensquilla.sandbox.windows_service_client import WindowsSandboxServiceClient

    async def transport(payload):
        assert payload == {"op": "health"}
        raise ConnectionError("still missing")

    client = WindowsSandboxServiceClient(
        state_dir=tmp_path,
        transport=transport,
        broker_launcher=lambda state: None,
        setup_timeout_s=0.03,
        setup_poll_interval_s=0.01,
    )

    result = await client.ensure_setup()

    assert result.state is SandboxSetupState.FAILED
    assert result.requires_admin is True
    assert "did not become ready" in (result.detail or "")


def test_resolve_broker_python_avoids_cmd_shim(monkeypatch, tmp_path: Path) -> None:
    from opensquilla.sandbox import windows_service_client as mod

    shim = tmp_path / "py.cmd"
    base_python = tmp_path / "python.exe"
    shim.write_text("@echo off\n", encoding="utf-8")
    base_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(mod.sys, "executable", str(shim))
    monkeypatch.setattr(mod.sys, "_base_executable", str(base_python), raising=False)

    assert mod.resolve_broker_python_executable() == base_python


def test_resolve_broker_python_prefers_current_real_executable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import windows_service_client as mod

    current_python = tmp_path / "venv" / "python.exe"
    base_python = tmp_path / "base" / "python.exe"
    current_python.parent.mkdir()
    base_python.parent.mkdir()
    current_python.write_text("", encoding="utf-8")
    base_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(mod.sys, "executable", str(current_python))
    monkeypatch.setattr(mod.sys, "_base_executable", str(base_python), raising=False)

    assert mod.resolve_broker_python_executable() == current_python
