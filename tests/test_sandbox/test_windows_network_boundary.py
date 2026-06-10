from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.sandbox.types import (
    NetworkMode,
    NetworkProxySpec,
    ResourceLimits,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


def _request(tmp_path: Path) -> SandboxRequest:
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.PROXY_ALLOWLIST,
        network_proxy=NetworkProxySpec(host="127.0.0.1", port=48123),
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=30),
        env_allowlist=("PATH",),
        require_approval=False,
    )
    return SandboxRequest(
        argv=("python", "-m", "pip", "install", "humanize"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
    )


@pytest.mark.asyncio
async def test_windows_boundary_installs_and_removes_policy(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_network_boundary import WindowsNetworkBoundary

    calls = []

    class Client:
        async def install_policy(self, request):
            calls.append(("install", request.to_payload()))
            return {"status": "ok", "policy_id": "policy-1"}

        async def remove_policy(self, run_id):
            calls.append(("remove", run_id))
            return {"status": "ok"}

    boundary = WindowsNetworkBoundary(service_client=Client())
    identity = SimpleNamespace(appcontainer_sid="S-1-15-2-123")

    context = await boundary.prepare(_request(tmp_path), identity=identity)
    await boundary.cleanup(context)

    assert calls[0][0] == "install"
    assert calls[0][1]["proxy_port"] == 48123
    assert calls[1] == ("remove", context.run_id)


@pytest.mark.asyncio
async def test_windows_boundary_requires_appcontainer_sid(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_network_boundary import WindowsNetworkBoundary

    class Client:
        async def install_policy(self, request):
            raise AssertionError("install_policy should not run without an SID")

    boundary = WindowsNetworkBoundary(service_client=Client())

    with pytest.raises(SandboxBackendError, match="AppContainer SID"):
        await boundary.prepare(_request(tmp_path), identity=SimpleNamespace())
