"""Native Windows default sandbox backend adapter."""

from __future__ import annotations

from opensquilla.sandbox.backend.base import Backend
from opensquilla.sandbox.types import SandboxBackendError, SandboxRequest, SandboxResult


class WindowsDefaultBackend(Backend):
    """Windows backend used by Standard-Sandbox and Trusted-Sandbox."""

    name = "windows_default"

    def available(self) -> bool:
        return False

    async def run(self, request: SandboxRequest) -> SandboxResult:
        raise SandboxBackendError(
            "windows_default backend unavailable: setup and support checks are not ready"
        )


__all__ = ["WindowsDefaultBackend"]
