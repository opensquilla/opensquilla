"""Client facade for the Windows sandbox service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from opensquilla.sandbox.backend import windows_wfp
from opensquilla.sandbox.setup_state import SandboxSetupState, SetupResult

Transport = Callable[[dict[str, object]], Awaitable[dict[str, object]]]
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
    DEFAULT_PIPE_NAME: ClassVar[str] = r"\\.\pipe\opensquilla-sandbox-service"

    pipe_name: str = DEFAULT_PIPE_NAME
    transport: Transport | None = None

    @classmethod
    def from_config(cls, config: Any) -> WindowsSandboxServiceClient:
        sandbox = getattr(config, "sandbox", None)
        pipe_name = getattr(sandbox, "windows_service_pipe", None)
        return cls(pipe_name=pipe_name or cls.DEFAULT_PIPE_NAME)

    async def _request(self, payload: dict[str, object]) -> dict[str, object]:
        if self.transport is not None:
            return await self.transport(payload)
        return await self._named_pipe_request(payload)

    async def _named_pipe_request(self, payload: dict[str, object]) -> dict[str, object]:
        _ = payload
        raise ConnectionError("Windows sandbox service is not reachable")

    async def health(self) -> SetupResult:
        return SetupResult(
            state=SandboxSetupState.NOT_SETUP,
            platform="win32",
            message="Windows sandbox service is not installed or not reachable.",
            requires_admin=True,
        )

    async def ensure_setup(self) -> SetupResult:
        return SetupResult(
            state=SandboxSetupState.FAILED,
            platform="win32",
            message="Windows sandbox service setup is not available in this build.",
            requires_admin=True,
            detail=(
                "Install the Windows sandbox service before enabling "
                "Windows sandbox networking."
            ),
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


__all__ = [
    "InstallPolicyRequest",
    "Transport",
    "WindowsSandboxServiceClient",
    "dispatch_service_request",
]
