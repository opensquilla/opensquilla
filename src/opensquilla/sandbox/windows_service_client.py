"""Client facade for the Windows sandbox service."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from opensquilla.sandbox.backend import windows_wfp
from opensquilla.sandbox.setup_state import SandboxSetupState, SetupResult
from opensquilla.sandbox.windows_service_ipc import (
    DEFAULT_PIPE_NAME,
    BrokerConnectionState,
    broker_state_path,
    new_broker_state,
    read_broker_state,
    request_sync,
    service_state_dir,
    write_broker_state,
)

Transport = Callable[[dict[str, object]], Awaitable[dict[str, object]]]
BrokerLauncher = Callable[[BrokerConnectionState], object]
_POLICIES: dict[str, tuple[object, ...]] = {}


def _validate_run_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("run_id is required")
    return normalized


def _validate_appcontainer_sid(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized.startswith("S-1-15-2-"):
        raise ValueError("appcontainer_sid must be an AppContainer SID")
    return normalized


def _validate_loopback_host(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in {"127.0.0.1", "::1"}:
        raise ValueError("proxy_host must be loopback")
    return normalized


def _validate_port(value: int) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("proxy_port must be in range 1..65535")
    return port


def _validate_ttl(value: int) -> int:
    ttl = int(value)
    if not 1 <= ttl <= 3600:
        raise ValueError("ttl_seconds must be in range 1..3600")
    return ttl


@dataclass(frozen=True)
class InstallPolicyRequest:
    run_id: str
    appcontainer_sid: str
    proxy_host: str
    proxy_port: int
    ttl_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _validate_run_id(self.run_id))
        object.__setattr__(
            self,
            "appcontainer_sid",
            _validate_appcontainer_sid(self.appcontainer_sid),
        )
        object.__setattr__(self, "proxy_host", _validate_loopback_host(self.proxy_host))
        object.__setattr__(self, "proxy_port", _validate_port(self.proxy_port))
        object.__setattr__(self, "ttl_seconds", _validate_ttl(self.ttl_seconds))

    def to_payload(self) -> dict[str, object]:
        return {
            "op": "install_policy",
            "run_id": self.run_id,
            "appcontainer_sid": self.appcontainer_sid,
            "proxy_host": self.proxy_host,
            "proxy_port": self.proxy_port,
            "ttl_seconds": self.ttl_seconds,
        }


@dataclass(frozen=True)
class WindowsSandboxServiceClient:
    DEFAULT_PIPE_NAME: ClassVar[str] = DEFAULT_PIPE_NAME

    pipe_name: str = DEFAULT_PIPE_NAME
    transport: Transport | None = None
    state_dir: Path | None = None
    broker_launcher: BrokerLauncher | None = None
    setup_timeout_s: float = 30.0
    setup_poll_interval_s: float = 0.25

    @classmethod
    def from_config(cls, config: Any) -> WindowsSandboxServiceClient:
        sandbox = getattr(config, "sandbox", None)
        pipe_name = getattr(sandbox, "windows_service_pipe", None)
        return cls(
            pipe_name=pipe_name or cls.DEFAULT_PIPE_NAME,
            state_dir=service_state_dir(config),
        )

    @property
    def state_file(self) -> Path:
        return broker_state_path(self.state_dir)

    async def _request(self, payload: dict[str, object]) -> dict[str, object]:
        if self.transport is not None:
            return await self.transport(payload)
        return await self._named_pipe_request(payload)

    async def _named_pipe_request(self, payload: dict[str, object]) -> dict[str, object]:
        state = read_broker_state(self.state_file)
        if state is None:
            raise ConnectionError("Windows sandbox service is not reachable")
        return await asyncio.to_thread(request_sync, state, payload)

    async def health(self) -> SetupResult:
        try:
            response = await self._request({"op": "health"})
        except Exception as exc:
            return SetupResult(
                state=SandboxSetupState.NOT_SETUP,
                platform="win32",
                message="Windows sandbox service is not installed or not reachable.",
                requires_admin=True,
                detail=str(exc),
            )
        if response.get("status") == "ok" and response.get("admin", True) is not False:
            detail = str(response.get("detail") or "") or None
            return SetupResult(
                state=SandboxSetupState.READY,
                platform="win32",
                message="Windows sandbox service is ready.",
                requires_admin=True,
                detail=detail,
            )
        return SetupResult(
            state=SandboxSetupState.FAILED,
            platform="win32",
            message="Windows sandbox service is reachable but not ready.",
            requires_admin=True,
            detail=str(response),
        )

    async def ensure_setup(self) -> SetupResult:
        current = await self.health()
        if current.state is SandboxSetupState.READY:
            return current

        python_executable = resolve_broker_python_executable()
        state = new_broker_state(
            pipe_name=self.pipe_name,
            base_dir=self.state_dir,
            python_executable=str(python_executable),
        )
        write_broker_state(state)
        launcher = self.broker_launcher or _launch_elevated_broker
        try:
            launcher(state)
        except Exception as exc:
            return SetupResult(
                state=SandboxSetupState.FAILED,
                platform="win32",
                message="Windows sandbox service setup failed.",
                requires_admin=True,
                detail=str(exc),
            )

        deadline = time.monotonic() + max(0.01, float(self.setup_timeout_s))
        last = current
        while time.monotonic() < deadline:
            await asyncio.sleep(max(0.0, float(self.setup_poll_interval_s)))
            last = await self.health()
            if last.state is SandboxSetupState.READY:
                return last

        return SetupResult(
            state=SandboxSetupState.FAILED,
            platform="win32",
            message="Windows sandbox service setup failed.",
            requires_admin=True,
            detail=f"Windows sandbox broker did not become ready: {last.detail or last.message}",
        )

    async def install_policy(self, request: InstallPolicyRequest) -> dict[str, object]:
        return await self._request(request.to_payload())

    async def remove_policy(self, run_id: str) -> dict[str, object]:
        return await self._request({"op": "remove_policy", "run_id": _validate_run_id(run_id)})


async def dispatch_service_request(payload: dict[str, object]) -> dict[str, object]:
    op = str(payload.get("op") or "")
    if op == "health":
        return {"status": "ok"}
    if op == "install_policy":
        request = InstallPolicyRequest(
            run_id=str(payload.get("run_id") or ""),
            appcontainer_sid=str(payload.get("appcontainer_sid") or ""),
            proxy_host=str(payload.get("proxy_host") or ""),
            proxy_port=int(payload.get("proxy_port") or 0),
            ttl_seconds=int(payload.get("ttl_seconds") or 0),
        )
        filter_ids = windows_wfp.install_wfp_policy(
            run_id=request.run_id,
            appcontainer_sid=request.appcontainer_sid,
            broker_host=request.proxy_host,
            broker_port=request.proxy_port,
        )
        _POLICIES[request.run_id] = tuple(filter_ids)
        return {"status": "ok", "filter_ids": list(filter_ids)}
    if op == "remove_policy":
        run_id = _validate_run_id(str(payload.get("run_id") or ""))
        filter_ids = _POLICIES.pop(run_id, ())
        windows_wfp.remove_wfp_filters(filter_ids)
        return {"status": "ok", "removed": len(filter_ids)}
    raise ValueError(f"unknown operation: {op}")


def resolve_broker_python_executable() -> Path:
    configured = os.environ.get("OPENSQUILLA_WINDOWS_BROKER_PYTHON", "").strip()
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    candidates.append(sys.executable)
    executable = Path(sys.executable)
    if executable.name.lower().endswith((".cmd", ".bat")):
        candidates.append(str(executable.with_name("python.exe")))
    candidates.append(getattr(sys, "_base_executable", ""))
    for name in ("python.exe", "python"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)

    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.suffix.lower() in {".cmd", ".bat"}:
            continue
        if path.exists():
            return path
    raise FileNotFoundError(
        "Unable to find a real python.exe for the Windows sandbox broker"
    )


def _launch_elevated_broker(state: BrokerConnectionState) -> None:
    if not sys.platform.startswith("win"):
        raise RuntimeError("Windows sandbox broker setup requires Windows")
    python_executable = Path(
        state.python_executable or str(resolve_broker_python_executable())
    )
    params = subprocess.list2cmdline(
        [
            "-m",
            "opensquilla.sandbox.windows_service_broker",
            "--pipe",
            state.pipe_name,
            "--authkey",
            state.authkey_hex,
        ]
    )
    try:
        import ctypes

        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(python_executable),
            params,
            str(Path.cwd()),
            0,
        )
    except Exception as exc:
        raise RuntimeError(f"failed to launch elevated Windows sandbox broker: {exc}") from exc
    if int(result) <= 32:
        raise PermissionError(
            "Windows sandbox setup was cancelled or blocked by UAC"
        )


__all__ = [
    "InstallPolicyRequest",
    "Transport",
    "WindowsSandboxServiceClient",
    "dispatch_service_request",
    "resolve_broker_python_executable",
]
