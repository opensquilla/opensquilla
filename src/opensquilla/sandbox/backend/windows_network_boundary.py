"""Windows managed-network boundary backed by the sandbox service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from opensquilla.sandbox.types import NetworkMode, SandboxBackendError, SandboxRequest
from opensquilla.sandbox.windows_service_client import (
    InstallPolicyRequest,
    WindowsSandboxServiceClient,
)


@dataclass(frozen=True)
class WindowsNetworkBoundaryContext:
    run_id: str
    appcontainer_sid: str


@dataclass(frozen=True)
class WindowsNetworkBoundary:
    service_client: Any

    @classmethod
    def from_config(cls, config: Any) -> WindowsNetworkBoundary:
        return cls(service_client=WindowsSandboxServiceClient.from_config(config))

    async def prepare(
        self,
        request: SandboxRequest,
        *,
        identity: Any,
    ) -> WindowsNetworkBoundaryContext:
        if request.policy.network != NetworkMode.PROXY_ALLOWLIST:
            return WindowsNetworkBoundaryContext(run_id="", appcontainer_sid="")
        proxy = request.policy.network_proxy
        if proxy is None:
            raise SandboxBackendError("Windows managed network boundary requires a proxy")
        sid = str(getattr(identity, "appcontainer_sid", "") or "")
        if not sid.startswith("S-1-15-2-"):
            raise SandboxBackendError(
                "Windows managed network boundary requires AppContainer SID"
            )
        run_id = str(uuid.uuid4())
        ttl = max(1, min(int(request.policy.limits.wall_timeout_s) + 30, 3600))
        await self.service_client.install_policy(
            InstallPolicyRequest(
                run_id=run_id,
                appcontainer_sid=sid,
                proxy_host=proxy.host,
                proxy_port=proxy.port,
                ttl_seconds=ttl,
            )
        )
        return WindowsNetworkBoundaryContext(run_id=run_id, appcontainer_sid=sid)

    async def cleanup(self, context: WindowsNetworkBoundaryContext) -> None:
        if not context.run_id:
            return
        await self.service_client.remove_policy(context.run_id)


__all__ = ["WindowsNetworkBoundary", "WindowsNetworkBoundaryContext"]
