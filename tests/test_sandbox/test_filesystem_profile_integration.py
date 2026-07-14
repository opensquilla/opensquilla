from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opensquilla.sandbox.backend.bubblewrap import BubblewrapBackend
from opensquilla.sandbox.backend.seatbelt import SeatbeltBackend
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.operation_runtime import SandboxOperation
from opensquilla.sandbox.path_validation import decide_path_access
from opensquilla.sandbox.permissions import FileSystemPermissionProfile
from opensquilla.sandbox.policy import build_policy
from opensquilla.sandbox.types import SandboxRequest, SecurityLevel


@pytest.mark.asyncio
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux native smoke")
@pytest.mark.parametrize("target", [Path("/etc"), Path("/home"), Path("/var"), Path.home()])
async def test_bubblewrap_shell_and_worker_read_codex_host_view(
    target: Path,
    tmp_path: Path,
) -> None:
    backend = BubblewrapBackend()
    if not backend.available() or not target.exists():
        pytest.skip("bubblewrap or target is unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        workspace,
        SandboxSettings(),
    )
    assert policy.file_system is not None

    worker = await backend.run_operation(
        SandboxOperation.filesystem(
            kind="list_dir",
            workspace=workspace,
            run_mode="standard",
            path=target,
            paths=(target,),
            display_path=str(target),
            file_system_profile=policy.file_system,
        )
    )
    shell = await backend.run(
        SandboxRequest(
            argv=("/bin/ls", str(target)),
            cwd=workspace,
            action_kind="shell.exec",
            policy=policy,
            run_mode="standard",
        )
    )

    assert isinstance(worker.message, str)
    assert worker.message
    assert shell.returncode == 0


def test_explicit_denied_read_is_blocked_before_backend(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    denied = tmp_path / "secret"
    profile = FileSystemPermissionProfile.workspace(
        workspace=workspace,
        denied_read_roots=(denied,),
    )

    decision = decide_path_access(
        denied / "token",
        workspace=workspace,
        profile=profile,
    )

    assert decision.status == "blocked"
    assert decision.reason == "denied_read"


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="native Seatbelt required")
@pytest.mark.parametrize("target", [Path("/etc"), Path.home()])
async def test_seatbelt_shell_and_worker_share_host_read_profile(
    target: Path,
    tmp_path: Path,
) -> None:
    backend = SeatbeltBackend()
    if not backend.available() or not target.exists():
        pytest.skip("Seatbelt or target is unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        workspace,
        SandboxSettings(),
    )
    assert policy.file_system is not None

    worker = await backend.run_operation(
        SandboxOperation.filesystem(
            kind="list_dir",
            workspace=workspace,
            run_mode="standard",
            path=target,
            paths=(target,),
            display_path=str(target),
            file_system_profile=policy.file_system,
        )
    )
    shell = await backend.run(
        SandboxRequest(
            argv=("/bin/ls", str(target)),
            cwd=workspace,
            action_kind="shell.exec",
            policy=policy,
            run_mode="standard",
        )
    )

    assert worker.message
    assert shell.returncode == 0
