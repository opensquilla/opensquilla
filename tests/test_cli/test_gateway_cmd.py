from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from typer.testing import CliRunner

from opensquilla.cli import gateway_lifecycle
from opensquilla.cli.gateway_run_presenters import gateway_startup_guidance
from opensquilla.cli.main import app
from opensquilla.paths import default_opensquilla_home

runner = CliRunner()
Manager = gateway_lifecycle.GatewayLifecycleManager


def _payload(result):
    return json.loads(result.stdout)


def _write_pidfile(record: dict) -> None:
    path = gateway_lifecycle.gateway_pidfile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def _record(pid: int = 1234, *, port: int = 18790) -> dict:
    return {
        "pid": pid,
        "host": "127.0.0.1",
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "healthUrl": f"http://127.0.0.1:{port}/health",
        "logPath": str(gateway_lifecycle.gateway_log_path()),
        "startedAt": "2026-05-04T00:00:00Z",
        "argv": [
            sys.executable,
            "-m",
            "opensquilla.cli.main",
            "gateway",
            "run",
            "--listen",
            "127.0.0.1",
            "--port",
            str(port),
        ],
    }


def _patch_health(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(Manager, "_probe_health", lambda self: value)


def _patch_wait_for_health(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(Manager, "_wait_for_health", lambda self: value)


def _patch_pid_running(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(Manager, "_pid_running", lambda self, pid: value)


class _FakeHealthResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def test_gateway_startup_guidance_shows_operator_next_steps() -> None:
    guidance = gateway_startup_guidance("127.0.0.1", 18790)

    assert "[bold]Web UI:[/bold] http://127.0.0.1:18790/control/" in guidance
    assert "[bold]API base:[/bold] http://127.0.0.1:18790" in guidance
    debug_log = default_opensquilla_home() / "logs" / "debug.log"
    assert f"[bold]Debug log:[/bold] {debug_log}" in guidance
    assert "[dim]Keep this terminal open. Press Ctrl+C to stop.[/dim]" in guidance


def test_gateway_lifecycle_paths_use_state_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))

    assert gateway_lifecycle.gateway_pidfile_path() == (
        tmp_path / "home" / "state" / "gateway" / "gateway.json"
    )
    assert gateway_lifecycle.gateway_log_path() == tmp_path / "home" / "logs" / "gateway.log"


def test_gateway_help_lists_lifecycle_commands() -> None:
    result = runner.invoke(app, ["gateway", "--help"])

    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "start" in result.stdout
    assert "status" in result.stdout
    assert "stop" in result.stdout
    assert "restart" in result.stdout


def test_gateway_status_json_reports_not_started(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _patch_health(monkeypatch, False)

    result = runner.invoke(app, ["gateway", "status", "--json"])

    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["ok"] is True
    assert payload["state"] == "not_started"
    assert payload["managed"] is False


def test_gateway_status_reports_stale_without_mutating_pidfile(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _write_pidfile(_record(pid=9999))
    before = gateway_lifecycle.gateway_pidfile_path().read_text(encoding="utf-8")
    _patch_pid_running(monkeypatch, False)
    _patch_health(monkeypatch, False)

    result = runner.invoke(app, ["gateway", "status", "--json"])

    assert result.exit_code == 0
    assert _payload(result)["state"] == "stale"
    assert gateway_lifecycle.gateway_pidfile_path().read_text(encoding="utf-8") == before


def test_gateway_start_refuses_unmanaged_healthy_gateway(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _patch_health(monkeypatch, True)

    result = runner.invoke(app, ["gateway", "start", "--json"])

    assert result.exit_code == 3
    payload = _payload(result)
    assert payload["ok"] is False
    assert payload["state"] == "unmanaged"
    assert payload["code"] == "UNMANAGED_GATEWAY_RUNNING"
    assert not gateway_lifecycle.gateway_pidfile_path().exists()


def test_gateway_start_uses_same_interpreter_cli_boundary(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fake_popen)
    _patch_health(monkeypatch, False)
    _patch_wait_for_health(monkeypatch, True)

    result = runner.invoke(
        app,
        ["gateway", "start", "--listen", "127.0.0.2", "--port", "18888", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = _payload(result)
    assert payload["state"] == "running"
    assert payload["pid"] == 4242
    argv, kwargs = calls[0]
    assert argv[:5] == [sys.executable, "-m", "opensquilla.cli.main", "gateway", "run"]
    assert "--listen" in argv
    assert argv[argv.index("--listen") + 1] == "127.0.0.2"
    assert kwargs["shell"] is False


def test_gateway_start_waits_for_readiness_after_liveness(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    calls = []
    health_checks = 0
    ready_checks = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(pid=4244)

    def fake_health(self):
        nonlocal health_checks
        health_checks += 1
        return health_checks > 1

    def fake_ready(self):
        ready_checks.append(True)
        return len(ready_checks) > 1

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(Manager, "_probe_health", fake_health)
    monkeypatch.setattr(Manager, "_probe_ready", fake_ready, raising=False)
    monkeypatch.setattr(gateway_lifecycle.time, "sleep", lambda _seconds: None)

    result = runner.invoke(app, ["gateway", "start", "--json"])

    assert result.exit_code == 0, result.stdout
    assert _payload(result)["state"] == "running"
    assert calls
    assert len(ready_checks) == 2


def test_gateway_health_probe_uses_loopback_for_wildcard_bind(monkeypatch) -> None:
    urls = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        assert timeout == 0.5
        return _FakeHealthResponse()

    monkeypatch.setattr(gateway_lifecycle, "urlopen", fake_urlopen)

    manager = Manager(host="0.0.0.0", port=18888)

    assert manager._probe_health() is True
    assert urls == ["http://127.0.0.1:18888/health"]


def test_gateway_start_with_wildcard_listen_keeps_bind_and_reports_probe_host(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(pid=4243)

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fake_popen)
    _patch_health(monkeypatch, False)
    _patch_wait_for_health(monkeypatch, True)

    result = runner.invoke(
        app,
        ["gateway", "start", "--listen", "0.0.0.0", "--port", "18889", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = _payload(result)
    assert payload["host"] == "0.0.0.0"
    assert payload["probeHost"] == "127.0.0.1"
    assert payload["url"] == "http://0.0.0.0:18889"
    assert payload["healthUrl"] == "http://127.0.0.1:18889/health"

    record = json.loads(gateway_lifecycle.gateway_pidfile_path().read_text(encoding="utf-8"))
    assert record["host"] == "0.0.0.0"
    assert record["probeHost"] == "127.0.0.1"
    assert record["url"] == "http://0.0.0.0:18889"
    assert record["healthUrl"] == "http://127.0.0.1:18889/health"

    argv, kwargs = calls[0]
    assert argv[argv.index("--listen") + 1] == "0.0.0.0"
    assert kwargs["shell"] is False


def test_gateway_start_does_not_spawn_duplicate_recorded_gateway(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _write_pidfile(_record(pid=321))
    _patch_pid_running(monkeypatch, True)
    _patch_health(monkeypatch, True)

    def fail_popen(*args, **kwargs):
        raise AssertionError("duplicate gateway should not be spawned")

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fail_popen)

    result = runner.invoke(app, ["gateway", "start", "--json"])

    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["state"] == "running"
    assert payload["pid"] == 321


def test_gateway_start_refuses_live_pidfile_for_different_target(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _write_pidfile(_record(pid=321, port=18790))
    _patch_pid_running(monkeypatch, True)
    _patch_health(monkeypatch, False)

    def fail_popen(*args, **kwargs):
        raise AssertionError("target mismatch must not spawn a second gateway")

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fail_popen)

    result = runner.invoke(app, ["gateway", "start", "--port", "18791", "--json"])

    assert result.exit_code == 3
    payload = _payload(result)
    assert payload["state"] == "target_mismatch"
    assert payload["code"] == "MANAGED_GATEWAY_TARGET_MISMATCH"
    assert gateway_lifecycle.gateway_pidfile_path().exists()


def test_gateway_stop_clears_stale_pidfile(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _write_pidfile(_record(pid=9999))
    _patch_pid_running(monkeypatch, False)
    _patch_health(monkeypatch, False)

    result = runner.invoke(app, ["gateway", "stop", "--json"])

    assert result.exit_code == 0
    assert _payload(result)["state"] == "cleared_stale"
    assert not gateway_lifecycle.gateway_pidfile_path().exists()


def test_gateway_stop_refuses_unmanaged_healthy_gateway(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _patch_health(monkeypatch, True)

    result = runner.invoke(app, ["gateway", "stop", "--json"])

    assert result.exit_code == 3
    payload = _payload(result)
    assert payload["code"] == "UNMANAGED_GATEWAY_RUNNING"
    assert payload["state"] == "unmanaged"


def test_gateway_stop_refuses_live_pidfile_for_different_target(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _write_pidfile(_record(pid=321, port=18790))
    _patch_pid_running(monkeypatch, True)
    _patch_health(monkeypatch, False)

    def fail_terminate(self, pid):
        raise AssertionError("target mismatch must not terminate another gateway")

    monkeypatch.setattr(Manager, "_terminate_pid", fail_terminate)

    result = runner.invoke(app, ["gateway", "stop", "--port", "18791", "--json"])

    assert result.exit_code == 3
    payload = _payload(result)
    assert payload["state"] == "target_mismatch"
    assert payload["code"] == "MANAGED_GATEWAY_TARGET_MISMATCH"
    assert gateway_lifecycle.gateway_pidfile_path().exists()


def test_gateway_restart_refuses_live_pidfile_for_different_target(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _write_pidfile(_record(pid=321, port=18790))
    _patch_pid_running(monkeypatch, True)
    _patch_health(monkeypatch, False)

    def fail_popen(*args, **kwargs):
        raise AssertionError("target mismatch must not restart over another gateway")

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fail_popen)

    result = runner.invoke(app, ["gateway", "restart", "--port", "18791", "--json"])

    assert result.exit_code == 3
    payload = _payload(result)
    assert payload["state"] == "target_mismatch"
    assert payload["code"] == "MANAGED_GATEWAY_TARGET_MISMATCH"
    assert gateway_lifecycle.gateway_pidfile_path().exists()


def test_gateway_restart_stops_before_starting(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _write_pidfile(_record(pid=777))
    events = []

    def fake_popen(argv, **kwargs):
        events.append("start")
        return SimpleNamespace(pid=888)

    def fake_terminate(self, pid):
        events.append("stop")
        return True

    _patch_pid_running(monkeypatch, True)
    _patch_health(monkeypatch, False)
    monkeypatch.setattr(Manager, "_terminate_pid", fake_terminate)
    _patch_wait_for_health(monkeypatch, True)
    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fake_popen)

    result = runner.invoke(app, ["gateway", "restart", "--json"])

    assert result.exit_code == 0, result.stdout
    assert events == ["stop", "start"]
    assert _payload(result)["state"] == "running"
