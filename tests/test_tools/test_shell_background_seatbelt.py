from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.sandbox.backend import seatbelt as seatbelt_mod
from opensquilla.sandbox.backend.seatbelt import SeatbeltBackend
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)
from opensquilla.tools.builtin import shell

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Seatbelt background test models macOS/POSIX paths",
)


class _FakeProcess:
    pid = 12345
    returncode = None
    stdout = None
    stderr = None


def _request(workspace: Path) -> SandboxRequest:
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(
                host_path=workspace,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=60.0),
        env_allowlist=("PATH", "TMPDIR"),
        require_approval=False,
    )
    return SandboxRequest(
        argv=("sh", "-lc", "sleep 10"),
        cwd=workspace,
        action_kind="shell.background",
        policy=policy,
        env={"PATH": "/bin:/usr/bin"},
    )


@pytest.mark.asyncio
async def test_spawn_sandboxed_background_supports_seatbelt_and_cleans_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> _FakeProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(
        seatbelt_mod,
        "_sandbox_exec_binary",
        lambda binary=None: "/usr/bin/sandbox-exec",
    )
    monkeypatch.setattr(
        shell.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    spawned = await shell._spawn_sandboxed_background_process(
        runtime=SimpleNamespace(backend=SeatbeltBackend()),
        request=_request(tmp_path),
    )

    argv = captured["argv"]
    assert isinstance(argv, tuple)
    assert argv[:3] == ("/usr/bin/sandbox-exec", "-f", argv[2])
    profile_path = Path(argv[2])
    assert profile_path.exists()
    assert argv[3:] == ("sh", "-lc", "sleep 10")
    kwargs = captured["kwargs"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"] == {"PATH": "/bin:/usr/bin"}
    assert spawned.process.pid == 12345

    session = shell._BgSession(
        session_id="seatbelt",
        command="sleep 10",
        process=spawned.process,
        cleanup_callbacks=spawned.cleanup_callbacks,
    )
    shell._finalize_bg_session(session)

    assert not profile_path.exists()
