"""Client facade for the Windows sandbox service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from opensquilla.sandbox.setup_state import SandboxSetupState, SetupResult


@dataclass(frozen=True)
class WindowsSandboxServiceClient:
    DEFAULT_PIPE_NAME: ClassVar[str] = r"\\.\pipe\opensquilla-sandbox-service"

    pipe_name: str = DEFAULT_PIPE_NAME

    @classmethod
    def from_config(cls, config: Any) -> WindowsSandboxServiceClient:
        sandbox = getattr(config, "sandbox", None)
        pipe_name = getattr(sandbox, "windows_service_pipe", None)
        return cls(pipe_name=pipe_name or cls.DEFAULT_PIPE_NAME)

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


__all__ = ["WindowsSandboxServiceClient"]
