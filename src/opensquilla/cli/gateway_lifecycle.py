"""Local process lifecycle helpers for ``opensquilla gateway``."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from opensquilla.cli.url_utils import normalize_gateway_url
from opensquilla.paths import default_opensquilla_home, state_dir

UNMANAGED_GATEWAY_RUNNING = "UNMANAGED_GATEWAY_RUNNING"
MANAGED_GATEWAY_TARGET_MISMATCH = "MANAGED_GATEWAY_TARGET_MISMATCH"
REMOTE_GATEWAY_UNAVAILABLE = "REMOTE_GATEWAY_UNAVAILABLE"


def gateway_pidfile_path() -> Path:
    return state_dir("gateway", "gateway.json")


def gateway_log_path() -> Path:
    return default_opensquilla_home() / "logs" / "gateway.log"


@dataclass
class GatewayLifecycleResult:
    action: str
    state: str
    ok: bool = True
    pid: int | None = None
    host: str = "127.0.0.1"
    probe_host: str | None = None
    port: int = 18791
    managed: bool = False
    code: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    pidfile: str = ""
    log_path: str = ""
    started_at: str | None = None
    exit_code_value: int = 0
    remote: bool = False
    gateway_url: str | None = None
    url_override: str | None = None
    health_url_override: str | None = None

    @property
    def url(self) -> str:
        if self.url_override:
            return self.url_override
        return _http_url(self.host, self.port)

    @property
    def health_url(self) -> str:
        if self.health_url_override:
            return self.health_url_override
        return f"{_http_url(self.probe_host or self.host, self.port)}/health"

    @property
    def exit_code(self) -> int:
        if self.ok:
            return 0
        if self.code == UNMANAGED_GATEWAY_RUNNING:
            return 3
        return self.exit_code_value or 1

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "action": self.action,
            "state": self.state,
            "host": self.host,
            "port": self.port,
            "url": self.url,
            "healthUrl": self.health_url,
            "managed": self.managed,
            "pidfile": self.pidfile,
            "logPath": self.log_path,
        }
        if self.remote:
            payload["remote"] = True
        if self.gateway_url:
            payload["gatewayUrl"] = self.gateway_url
        if self.probe_host and self.probe_host != self.host:
            payload["probeHost"] = self.probe_host
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.started_at:
            payload["startedAt"] = self.started_at
        if self.message:
            payload["message"] = self.message
        if self.code:
            payload["code"] = self.code
        if self.details:
            payload["details"] = self.details
        elif not self.ok:
            payload["details"] = {}
        return payload


class GatewayLifecycleManager:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 18791,
        config_path: str | None = None,
        health_timeout: float = 60.0,
        shutdown_timeout: float = 10.0,
        poll_interval: float = 0.2,
    ) -> None:
        self.host = host
        self.probe_host = _health_probe_host(host)
        self.port = port
        self.config_path = str(config_path) if config_path else None
        self.health_timeout = health_timeout
        self.shutdown_timeout = shutdown_timeout
        self.poll_interval = poll_interval
        self.pidfile = gateway_pidfile_path()
        self.log_path = gateway_log_path()

    def status(self) -> GatewayLifecycleResult:
        record, error = self._read_pidfile()
        if error is not None:
            return self._result(
                "status",
                "stale",
                managed=False,
                message="Gateway pidfile is unreadable.",
                details={"error": error},
            )

        if record is None:
            if self._probe_health():
                return self._unmanaged_result("status", ok=True)
            return self._result("status", "not_started", managed=False)

        if not self._record_matches_target(record):
            pid = self._record_pid(record)
            if pid is not None and self._pid_running(pid):
                return self._target_mismatch_result(
                    "status",
                    ok=True,
                    pid=pid,
                    record=record,
                )
            if self._probe_health():
                return self._unmanaged_result("status", ok=True)
            return self._result(
                "status",
                "stale",
                managed=False,
                details={"reason": "pidfile_target_mismatch"},
            )

        pid = self._record_pid(record)
        if pid is None or not self._pid_running(pid):
            if self._probe_health():
                return self._unmanaged_result("status", ok=True)
            return self._result(
                "status",
                "stale",
                pid=pid,
                managed=False,
                started_at=self._record_started_at(record),
            )

        if self._probe_health():
            return self._result(
                "status",
                "running",
                pid=pid,
                managed=True,
                started_at=self._record_started_at(record),
            )

        return self._result(
            "status",
            "unhealthy",
            pid=pid,
            managed=True,
            started_at=self._record_started_at(record),
        )

    def start(self) -> GatewayLifecycleResult:
        current = self.status()
        if current.state == "running" and current.managed:
            current.action = "start"
            current.message = "Gateway is already running."
            return current
        if current.state == "unmanaged":
            return self._unmanaged_result("start", ok=False)
        if current.state == "target_mismatch":
            return self._target_mismatch_result(
                "start",
                ok=False,
                pid=current.pid,
                record=current.details,
            )
        if current.state == "unhealthy" and current.managed:
            return self._result(
                "start",
                "start_failed",
                ok=False,
                pid=current.pid,
                managed=True,
                code="RECORDED_GATEWAY_UNHEALTHY",
                message="Recorded gateway process is running but health check failed.",
                exit_code_value=1,
            )
        if current.state == "stale":
            self._remove_pidfile()

        argv = self._gateway_run_argv()
        started_at = self._now()
        try:
            process = self._spawn_gateway(argv)
        except OSError as exc:
            return self._result(
                "start",
                "start_failed",
                ok=False,
                code="SPAWN_FAILED",
                message=str(exc),
                exit_code_value=1,
            )

        record = self._record(process.pid, argv, started_at)
        self._write_pidfile(record)
        if self._wait_for_health():
            return self._result(
                "start",
                "running",
                pid=process.pid,
                managed=True,
                started_at=started_at,
                message="Gateway started.",
            )

        self._terminate_pid(process.pid)
        self._remove_pidfile()
        return self._result(
            "start",
            "start_failed",
            ok=False,
            pid=process.pid,
            managed=True,
            code="HEALTH_TIMEOUT",
            message="Gateway did not become ready before the timeout.",
            exit_code_value=1,
        )

    def stop(self) -> GatewayLifecycleResult:
        current = self.status()
        if current.state == "not_started":
            return self._result("stop", "stopped", managed=False, message="Gateway is not running.")
        if current.state == "unmanaged":
            return self._unmanaged_result("stop", ok=False)
        if current.state == "target_mismatch":
            return self._target_mismatch_result(
                "stop",
                ok=False,
                pid=current.pid,
                record=current.details,
            )
        if current.state == "stale":
            self._remove_pidfile()
            return self._result("stop", "cleared_stale", managed=False)
        if current.pid is None:
            return self._result(
                "stop",
                "stop_failed",
                ok=False,
                code="PID_MISSING",
                message="Recorded gateway pid is missing.",
                exit_code_value=1,
            )

        if not self._terminate_pid(current.pid):
            return self._result(
                "stop",
                "stop_failed",
                ok=False,
                pid=current.pid,
                managed=True,
                code="TERMINATE_FAILED",
                message="Gateway process did not stop before the timeout.",
                exit_code_value=1,
            )

        self._remove_pidfile()
        return self._result(
            "stop",
            "stopped",
            pid=current.pid,
            managed=True,
            message="Gateway stopped.",
        )

    def restart(self) -> GatewayLifecycleResult:
        stopped = self.stop()
        if stopped.exit_code != 0:
            return self._result(
                "restart",
                stopped.state,
                ok=False,
                pid=stopped.pid,
                managed=stopped.managed,
                code=stopped.code,
                message=stopped.message,
                details={"stop": stopped.to_payload()},
                exit_code_value=stopped.exit_code,
            )

        started = self.start()
        started.action = "restart"
        started.details = {**started.details, "stop": stopped.to_payload()}
        return started

    def _result(
        self,
        action: str,
        state: str,
        *,
        ok: bool = True,
        pid: int | None = None,
        managed: bool = False,
        code: str | None = None,
        message: str = "",
        details: dict[str, Any] | None = None,
        started_at: str | None = None,
        exit_code_value: int = 0,
    ) -> GatewayLifecycleResult:
        return GatewayLifecycleResult(
            action=action,
            state=state,
            ok=ok,
            pid=pid,
            host=self.host,
            probe_host=self.probe_host,
            port=self.port,
            managed=managed,
            code=code,
            message=message,
            details=details or {},
            pidfile=str(self.pidfile),
            log_path=str(self.log_path),
            started_at=started_at,
            exit_code_value=exit_code_value,
        )

    def _unmanaged_result(self, action: str, *, ok: bool) -> GatewayLifecycleResult:
        return self._result(
            action,
            "unmanaged",
            ok=ok,
            managed=False,
            code=None if ok else UNMANAGED_GATEWAY_RUNNING,
            message=(
                "A healthy gateway is already running on the requested host/port, "
                "but OpenSquilla does not own it."
            ),
            exit_code_value=3,
        )

    def _target_mismatch_result(
        self,
        action: str,
        *,
        ok: bool,
        pid: int | None,
        record: dict[str, Any],
    ) -> GatewayLifecycleResult:
        details = {
            "recordedHost": record.get("host") or record.get("recordedHost"),
            "recordedPort": record.get("port") or record.get("recordedPort"),
            "requestedHost": self.host,
            "requestedPort": self.port,
        }
        if self.config_path or record.get("configPath"):
            details["recordedConfigPath"] = record.get("configPath")
            details["requestedConfigPath"] = self.config_path
        return self._result(
            action,
            "target_mismatch",
            ok=ok,
            pid=pid,
            managed=True,
            code=None if ok else MANAGED_GATEWAY_TARGET_MISMATCH,
            message=(
                "A managed gateway is recorded for a different host/port. "
                "Refusing to mutate it from this target."
            ),
            details=details,
            exit_code_value=3,
        )

    def _read_pidfile(self) -> tuple[dict[str, Any] | None, str | None]:
        if not self.pidfile.exists():
            return None, None
        try:
            payload = json.loads(self.pidfile.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, str(exc)
        if not isinstance(payload, dict):
            return None, "pidfile payload is not an object"
        return payload, None

    def _write_pidfile(self, record: dict[str, Any]) -> None:
        self.pidfile.parent.mkdir(parents=True, exist_ok=True)
        self.pidfile.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")

    def _remove_pidfile(self) -> None:
        try:
            self.pidfile.unlink()
        except FileNotFoundError:
            pass

    def _record(self, pid: int, argv: list[str], started_at: str) -> dict[str, Any]:
        record: dict[str, Any] = {
            "pid": pid,
            "host": self.host,
            "port": self.port,
            "url": _http_url(self.host, self.port),
            "healthUrl": f"{_http_url(self.probe_host, self.port)}/health",
            "logPath": str(self.log_path),
            "startedAt": started_at,
            "argv": argv,
        }
        if self.probe_host != self.host:
            record["probeHost"] = self.probe_host
        if self.config_path:
            record["configPath"] = self.config_path
        return record

    def _record_matches_target(self, record: dict[str, Any]) -> bool:
        try:
            record_port = int(record.get("port", -1))
        except (TypeError, ValueError):
            return False
        if record.get("host") != self.host or record_port != self.port:
            return False
        record_config_path = record.get("configPath")
        if self.config_path is not None and record_config_path:
            return bool(record_config_path == self.config_path)
        return True

    def _record_pid(self, record: dict[str, Any]) -> int | None:
        value = record.get("pid")
        if value is None:
            return None
        try:
            pid = int(value)
        except (TypeError, ValueError):
            return None
        return pid if pid > 0 else None

    def _record_started_at(self, record: dict[str, Any]) -> str | None:
        value = record.get("startedAt")
        return value if isinstance(value, str) else None

    def _gateway_run_argv(self) -> list[str]:
        argv = [
            sys.executable,
            "-m",
            "opensquilla.cli.main",
            "gateway",
            "run",
            "--listen",
            self.host,
            "--port",
            str(self.port),
        ]
        if self.config_path:
            argv.extend(["--config", self.config_path])
        # The active profile is forwarded to the child via env, not argv.
        # `_spawn_gateway` does `os.environ.copy()` so the child sees
        # OPENSQUILLA_HOME + OPENSQUILLA_PROFILE from this process.
        # We deliberately do NOT pass --profile on the CLI: `gateway run`
        # is served by the standalone `gateway_app` Typer instance and does
        # not declare the --profile option. Plumbing it through env
        # instead is both simpler and correct.
        return argv

    def _spawn_gateway(self, argv: list[str]) -> subprocess.Popen[Any]:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        if self.config_path:
            env["OPENSQUILLA_GATEWAY_CONFIG_PATH"] = self.config_path

        log = self.log_path.open("ab")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            process = subprocess.Popen(  # noqa: S603 - argv is constructed internally.
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                shell=False,
                start_new_session=os.name != "nt",
                creationflags=creationflags,
            )
        finally:
            log.close()
        return process

    def _probe_health(self) -> bool:
        for path in ("health", "healthz"):
            request = Request(f"{_http_url(self.probe_host, self.port)}/{path}", method="GET")
            try:
                with urlopen(request, timeout=0.5) as response:  # noqa: S310 - local health probe.
                    if 200 <= int(response.status) < 300:
                        return True
            except (HTTPError, OSError, URLError, TimeoutError):
                continue
        return False

    def _probe_ready(self) -> bool:
        saw_ready_endpoint = False
        for path in ("ready", "readyz"):
            request = Request(f"{_http_url(self.probe_host, self.port)}/{path}", method="GET")
            try:
                with urlopen(request, timeout=0.5) as response:  # noqa: S310 - local readiness probe.
                    saw_ready_endpoint = True
                    if 200 <= int(response.status) < 300:
                        return True
            except HTTPError as exc:
                if int(getattr(exc, "code", 0)) != 404:
                    saw_ready_endpoint = True
                continue
            except (OSError, URLError, TimeoutError):
                continue
        if saw_ready_endpoint:
            return False
        return self._probe_health()

    def _wait_for_health(self) -> bool:
        deadline = time.monotonic() + max(self.health_timeout, 0.0)
        while time.monotonic() <= deadline:
            if self._probe_ready():
                return True
            time.sleep(self.poll_interval)
        return False

    def _pid_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            return _windows_pid_running(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _terminate_pid(self, pid: int) -> bool:
        if not self._pid_running(pid):
            return True
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        except OSError:
            return False

        deadline = time.monotonic() + max(self.shutdown_timeout, 0.0)
        while time.monotonic() <= deadline:
            if not self._pid_running(pid):
                return True
            time.sleep(self.poll_interval)

        sigkill = getattr(signal, "SIGKILL", None)
        if sigkill is not None and os.name != "nt":
            try:
                os.kill(pid, sigkill)
            except OSError:
                pass
            return not self._pid_running(pid)
        return False

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _health_probe_host(host: str) -> str:
    if host == "0.0.0.0":
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


def _http_url(host: str, port: int) -> str:
    return f"http://{_format_url_host(host)}:{port}"


def remote_gateway_status(gateway_url: str, *, timeout: float = 0.5) -> GatewayLifecycleResult:
    normalized = normalize_gateway_url(gateway_url)
    base_url = _gateway_http_base_url(normalized)
    attempts: list[dict[str, Any]] = []

    for path in ("health", "healthz"):
        health_url = f"{base_url}/{path}"
        request = Request(health_url, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-provided gateway URL.
                status = int(response.status)
                if 200 <= status < 300:
                    return GatewayLifecycleResult(
                        action="status",
                        state="running",
                        ok=True,
                        managed=False,
                        remote=True,
                        gateway_url=normalized,
                        url_override=base_url,
                        health_url_override=health_url,
                        details={"status": status},
                    )
                attempts.append({"url": health_url, "status": status})
        except HTTPError as exc:
            attempts.append({"url": health_url, "status": int(exc.code)})
        except (OSError, URLError, TimeoutError) as exc:
            attempts.append(
                {
                    "url": health_url,
                    "errorType": type(exc).__name__,
                    "error": str(exc),
                }
            )

    return GatewayLifecycleResult(
        action="status",
        state="unavailable",
        ok=False,
        managed=False,
        remote=True,
        code=REMOTE_GATEWAY_UNAVAILABLE,
        message="Remote gateway is unavailable.",
        details={"attempts": attempts},
        exit_code_value=1,
        gateway_url=normalized,
        url_override=base_url,
        health_url_override=f"{base_url}/health",
    )


def _gateway_http_base_url(normalized_gateway_url: str) -> str:
    parsed = urlparse(normalized_gateway_url)
    scheme = "https" if parsed.scheme == "wss" else "http"
    return urlunparse((scheme, parsed.netloc, "", "", "", ""))


def _format_url_host(host: str) -> str:
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host


def _windows_pid_running(pid: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    process_query_limited_information = 0x1000
    still_active = 259
    ctypes_mod = cast(Any, ctypes)
    kernel32 = ctypes_mod.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return int(exit_code.value) == still_active
    finally:
        kernel32.CloseHandle(handle)
