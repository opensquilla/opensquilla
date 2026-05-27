from __future__ import annotations

import json
import platform
import sys
from types import SimpleNamespace

from typer.testing import CliRunner

from opensquilla.cli import gateway_cmd, gateway_lifecycle
from opensquilla.cli.gateway_cmd import gateway_startup_guidance
from opensquilla.cli.main import app
from opensquilla.paths import default_opensquilla_home

runner = CliRunner()
Manager = gateway_lifecycle.GatewayLifecycleManager


def _env_hint(env_key: str) -> str:
    if platform.system().lower().startswith("win"):
        return f'PowerShell: $env:{env_key} = "<your-key>"'
    return f'export {env_key}="<your-key>"'


def _payload(result):
    return json.loads(result.stdout)


def _write_pidfile(record: dict) -> None:
    path = gateway_lifecycle.gateway_pidfile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def _record(pid: int = 1234, *, port: int = 18791) -> dict:
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
    guidance = gateway_startup_guidance("127.0.0.1", 18791)

    assert "[bold]Web UI:[/bold] http://127.0.0.1:18791/control/" in guidance
    assert "[bold]API base:[/bold] http://127.0.0.1:18791" in guidance
    debug_log = default_opensquilla_home() / "logs" / "debug.log"
    assert f"[bold]Debug log:[/bold] {debug_log}" in guidance
    assert "[dim]Keep this terminal open. Press Ctrl+C to stop.[/dim]" in guidance


def test_gateway_run_turns_missing_onboarding_env_into_recovery_hint(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "custom.toml"
    target.write_text(
        '[llm]\n'
        'provider = "openrouter"\n'
        'model = "deepseek/deepseek-v4-flash"\n'
        'api_key = "sk-or"\n'
        '\n'
        '[memory.embedding]\n'
        'provider = "openai"\n'
        '\n'
        '[memory.embedding.remote]\n'
        'api_key_env = "OPENAI_EMBEDDINGS_API_KEY"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    monkeypatch.delenv("OPENAI_EMBEDDINGS_API_KEY", raising=False)

    async def fail_start_gateway_server(**_kwargs):
        raise ValueError(
            "memory.embedding.provider='openai' requires "
            "memory.embedding.remote.api_key"
        )

    monkeypatch.setattr(gateway_cmd, "start_gateway_server", fail_start_gateway_server)

    result = runner.invoke(app, ["gateway", "run", "--config", str(target)])

    assert result.exit_code == 1
    output = result.stdout + (result.stderr or "")
    compact = "".join(output.split())
    assert "Gateway could not start" in output
    assert (
        f"Set memory key: {_env_hint('OPENAI_EMBEDDINGS_API_KEY')}".replace(" ", "")
        in compact
    )
    assert f"opensquillaonboardstatus--config{target}" in compact
    assert "Traceback" not in output


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


def test_gateway_start_help_explains_config_backed_target_defaults() -> None:
    result = runner.invoke(app, ["gateway", "start", "--help"])

    assert result.exit_code == 0
    assert "Port to bind (default: config port, usually 18791)" in result.stdout
    assert "Host to bind (default: config host, usually 127.0.0.1)" in result.stdout


def test_gateway_status_json_reports_not_started(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _patch_health(monkeypatch, False)

    result = runner.invoke(app, ["gateway", "status", "--json"])

    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["ok"] is True
    assert payload["state"] == "not_started"
    assert payload["managed"] is False


def test_gateway_status_gateway_url_probes_remote_https_health(monkeypatch) -> None:
    urls = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        assert timeout == 0.5
        return _FakeHealthResponse()

    monkeypatch.setattr(gateway_lifecycle, "urlopen", fake_urlopen)

    result = runner.invoke(
        app,
        ["gateway", "status", "--gateway", "https://squilla.example.com", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = _payload(result)
    assert payload["ok"] is True
    assert payload["remote"] is True
    assert payload["managed"] is False
    assert payload["state"] == "running"
    assert payload["gatewayUrl"] == "wss://squilla.example.com/ws"
    assert payload["url"] == "https://squilla.example.com"
    assert payload["healthUrl"] == "https://squilla.example.com/health"
    assert urls == ["https://squilla.example.com/health"]


def test_gateway_status_gateway_url_reports_remote_unavailable(monkeypatch) -> None:
    urls = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        assert timeout == 0.5
        raise OSError("offline")

    monkeypatch.setattr(gateway_lifecycle, "urlopen", fake_urlopen)

    result = runner.invoke(
        app,
        ["gateway", "status", "--gateway", "wss://squilla.example.com/ws", "--json"],
    )

    assert result.exit_code == 1, result.stdout
    payload = _payload(result)
    assert payload["ok"] is False
    assert payload["remote"] is True
    assert payload["managed"] is False
    assert payload["state"] == "unavailable"
    assert payload["code"] == "REMOTE_GATEWAY_UNAVAILABLE"
    assert payload["gatewayUrl"] == "wss://squilla.example.com/ws"
    assert payload["url"] == "https://squilla.example.com"
    assert payload["healthUrl"] == "https://squilla.example.com/health"
    assert urls == [
        "https://squilla.example.com/health",
        "https://squilla.example.com/healthz",
    ]
    assert [attempt["errorType"] for attempt in payload["details"]["attempts"]] == [
        "OSError",
        "OSError",
    ]


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


def test_gateway_start_uses_explicit_config_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    default_config = tmp_path / "default.toml"
    custom_config = tmp_path / "custom.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(default_config))
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(pid=4245)

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fake_popen)
    _patch_health(monkeypatch, False)
    _patch_wait_for_health(monkeypatch, True)

    result = runner.invoke(
        app,
        ["gateway", "start", "--config", str(custom_config), "--json"],
    )

    assert result.exit_code == 0, result.stdout
    argv, kwargs = calls[0]
    assert argv[argv.index("--config") + 1] == str(custom_config)
    assert kwargs["env"]["OPENSQUILLA_GATEWAY_CONFIG_PATH"] == str(custom_config)
    record = json.loads(gateway_lifecycle.gateway_pidfile_path().read_text(encoding="utf-8"))
    assert record["configPath"] == str(custom_config)


def test_gateway_start_uses_config_host_port_when_flags_are_omitted(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    custom_config = tmp_path / "custom.toml"
    custom_config.write_text('host = "127.0.0.2"\nport = 19999\n', encoding="utf-8")
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(pid=4246)

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fake_popen)
    _patch_health(monkeypatch, False)
    _patch_wait_for_health(monkeypatch, True)

    result = runner.invoke(
        app,
        ["gateway", "start", "--config", str(custom_config), "--json"],
    )

    assert result.exit_code == 0, result.stdout
    argv, _kwargs = calls[0]
    assert argv[argv.index("--listen") + 1] == "127.0.0.2"
    assert argv[argv.index("--port") + 1] == "19999"
    payload = _payload(result)
    assert payload["url"] == "http://127.0.0.2:19999"


def test_gateway_status_uses_config_host_port_when_flags_are_omitted(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    custom_config = tmp_path / "custom.toml"
    custom_config.write_text('host = "127.0.0.2"\nport = 19999\n', encoding="utf-8")
    probes = []

    def fake_probe(self):
        probes.append((self.host, self.port))
        return False

    monkeypatch.setattr(Manager, "_probe_health", fake_probe)

    result = runner.invoke(
        app,
        ["gateway", "status", "--config", str(custom_config), "--json"],
    )

    assert result.exit_code == 0, result.stdout
    assert probes == [("127.0.0.2", 19999)]
    payload = _payload(result)
    assert payload["url"] == "http://127.0.0.2:19999"


def test_gateway_run_uses_config_host_port_when_flags_are_omitted(
    tmp_path, monkeypatch
) -> None:
    custom_config = tmp_path / "custom.toml"
    custom_config.write_text('host = "127.0.0.2"\nport = 19999\n', encoding="utf-8")
    captured = {}

    class FakeServer:
        def __init__(self, task):
            self._task = task

        async def close(self, _reason):
            return None

    async def fake_start_gateway_server(*, config, subscription_manager, run):
        captured["config"] = config

        async def done():
            return None

        import asyncio

        return FakeServer(asyncio.create_task(done()))

    monkeypatch.setattr(gateway_cmd, "start_gateway_server", fake_start_gateway_server)

    gateway_cmd.run_gateway(
        port=None,
        bind=None,
        listen="",
        debug=False,
        config_path=str(custom_config),
    )

    assert captured["config"].host == "127.0.0.2"
    assert captured["config"].port == 19999


def test_gateway_run_keeps_missing_explicit_config_path_for_setup(
    tmp_path,
    monkeypatch,
) -> None:
    custom_config = tmp_path / "first-run.toml"
    captured = {}

    class FakeServer:
        def __init__(self, task):
            self._task = task

        async def close(self, _reason):
            return None

    async def fake_start_gateway_server(*, config, subscription_manager, run):
        captured["config"] = config

        async def done():
            return None

        import asyncio

        return FakeServer(asyncio.create_task(done()))

    monkeypatch.setattr(gateway_cmd, "start_gateway_server", fake_start_gateway_server)

    gateway_cmd.run_gateway(
        port=19876,
        bind=None,
        listen="",
        debug=False,
        config_path=str(custom_config),
    )

    assert captured["config"].config_path == str(custom_config)
    assert not custom_config.exists()


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
    _write_pidfile(_record(pid=321, port=18791))
    _patch_pid_running(monkeypatch, True)
    _patch_health(monkeypatch, False)

    def fail_popen(*args, **kwargs):
        raise AssertionError("target mismatch must not spawn a second gateway")

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fail_popen)

    result = runner.invoke(app, ["gateway", "start", "--port", "18792", "--json"])

    assert result.exit_code == 3
    payload = _payload(result)
    assert payload["state"] == "target_mismatch"
    assert payload["code"] == "MANAGED_GATEWAY_TARGET_MISMATCH"
    assert gateway_lifecycle.gateway_pidfile_path().exists()


def test_gateway_status_reports_recorded_config_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    record = _record(pid=321, port=18791)
    record["configPath"] = str(tmp_path / "first.toml")
    _write_pidfile(record)
    _patch_pid_running(monkeypatch, True)
    _patch_health(monkeypatch, False)

    result = runner.invoke(
        app,
        [
            "gateway",
            "status",
            "--config",
            str(tmp_path / "second.toml"),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["state"] == "target_mismatch"
    assert payload["details"]["recordedConfigPath"] == str(tmp_path / "first.toml")
    assert payload["details"]["requestedConfigPath"] == str(tmp_path / "second.toml")


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
    _write_pidfile(_record(pid=321, port=18791))
    _patch_pid_running(monkeypatch, True)
    _patch_health(monkeypatch, False)

    def fail_terminate(self, pid):
        raise AssertionError("target mismatch must not terminate another gateway")

    monkeypatch.setattr(Manager, "_terminate_pid", fail_terminate)

    result = runner.invoke(app, ["gateway", "stop", "--port", "18792", "--json"])

    assert result.exit_code == 3
    payload = _payload(result)
    assert payload["state"] == "target_mismatch"
    assert payload["code"] == "MANAGED_GATEWAY_TARGET_MISMATCH"
    assert gateway_lifecycle.gateway_pidfile_path().exists()


def test_gateway_restart_refuses_live_pidfile_for_different_target(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "home"))
    _write_pidfile(_record(pid=321, port=18791))
    _patch_pid_running(monkeypatch, True)
    _patch_health(monkeypatch, False)

    def fail_popen(*args, **kwargs):
        raise AssertionError("target mismatch must not restart over another gateway")

    monkeypatch.setattr(gateway_lifecycle.subprocess, "Popen", fail_popen)

    result = runner.invoke(app, ["gateway", "restart", "--port", "18792", "--json"])

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
