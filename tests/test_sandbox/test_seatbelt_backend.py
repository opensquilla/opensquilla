from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from opensquilla.sandbox.backend import seatbelt as seatbelt_mod
from opensquilla.sandbox.backend import select_backend
from opensquilla.sandbox.backend.seatbelt import (
    SeatbeltBackend,
    _classify_denial,
    build_seatbelt_argv,
    render_seatbelt_profile,
)
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.operation_runtime import SandboxOperation, SandboxOperationResult
from opensquilla.sandbox.permissions import (
    FileSystemAccess,
    FileSystemPermissionEntry,
    FileSystemPermissionProfile,
)
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    NetworkProxySpec,
    ResourceLimits,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SandboxResult,
    SecurityLevel,
)

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Seatbelt backend tests model macOS/POSIX paths",
)


def _policy(
    workspace: Path,
    *,
    network: NetworkMode = NetworkMode.NONE,
    network_proxy: NetworkProxySpec | None = None,
    workspace_rw: bool = True,
    tmp_writable: bool = True,
    mounts: tuple[MountSpec, ...] | None = None,
) -> SandboxPolicy:
    base_mounts = (
        MountSpec(
            host_path=workspace,
            sandbox_path=Path("/workspace"),
            mode="rw" if workspace_rw else "ro",
            required=True,
        ),
    )
    resolved_mounts = mounts or base_mounts
    if workspace_rw:
        file_system = FileSystemPermissionProfile.workspace(
            workspace=workspace,
            readable_roots=(mount.host_path for mount in resolved_mounts if mount.mode == "ro"),
            writable_roots=(
                mount.host_path
                for mount in resolved_mounts
                if mount.mode == "rw" and mount.host_path != workspace
            ),
            tmp_writable=tmp_writable,
            tmpdir_env_writable=tmp_writable,
        )
    else:
        file_system = FileSystemPermissionProfile.read_only(
            readable_roots=(mount.host_path for mount in resolved_mounts),
        )
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=network,
        mounts=resolved_mounts,
        workspace_rw=workspace_rw,
        tmp_writable=tmp_writable,
        limits=ResourceLimits(wall_timeout_s=0.1),
        env_allowlist=("PATH", "LANG"),
        require_approval=False,
        network_proxy=network_proxy,
        file_system=file_system,
    )


def _request(policy: SandboxPolicy, cwd: Path) -> SandboxRequest:
    return SandboxRequest(
        argv=("sh", "-lc", "echo ok"),
        cwd=cwd,
        action_kind="shell.exec",
        policy=policy,
        env={"PATH": "/bin", "SECRET": "nope"},
    )


def _access_rule(profile: str, action: str, root: Path) -> str:
    root_clause = f'(subpath "{root}")'
    rules = [
        line
        for line in profile.splitlines()
        if line.startswith(f"(allow {action}") and root_clause in line
    ]
    assert rules, f"missing {action} rule for {root}"
    return rules[0]


def test_available_false_on_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seatbelt_mod.sys, "platform", "linux")
    assert SeatbeltBackend(binary="sandbox-exec").available() is False


def test_available_true_on_macos_when_sandbox_exec_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seatbelt_mod.sys, "platform", "darwin")
    monkeypatch.setattr(seatbelt_mod.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    assert SeatbeltBackend(binary="sandbox-exec").available() is True


def test_available_false_on_macos_when_sandbox_exec_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seatbelt_mod.sys, "platform", "darwin")
    monkeypatch.setattr(seatbelt_mod.shutil, "which", lambda name: None)
    assert SeatbeltBackend(binary="sandbox-exec").available() is False


def test_auto_selects_seatbelt_on_macos_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import backend as backend_mod

    monkeypatch.setattr(backend_mod.sys, "platform", "darwin")
    monkeypatch.setattr(backend_mod.SeatbeltBackend, "available", lambda self: True)

    backend = select_backend(SandboxSettings(sandbox=True, backend="auto"))

    assert backend.name == "seatbelt"


def test_explicit_seatbelt_fails_closed_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import backend as backend_mod

    monkeypatch.setattr(backend_mod.SeatbeltBackend, "available", lambda self: False)

    with pytest.raises(SandboxBackendError, match="seatbelt.*unavailable"):
        select_backend(SandboxSettings(sandbox=True, backend="seatbelt"))


def test_profile_denies_default_and_network_none(tmp_path: Path) -> None:
    profile = render_seatbelt_profile(_request(_policy(tmp_path), tmp_path))

    assert "(deny default)" in profile
    assert "(deny network*)" in profile
    assert _access_rule(profile, "file-read*", Path("/"))
    assert _access_rule(profile, "file-write*", tmp_path)


def test_profile_fails_closed_without_resolved_filesystem_profile(tmp_path: Path) -> None:
    policy = replace(_policy(tmp_path), file_system=None)

    rendered = render_seatbelt_profile(_request(policy, tmp_path))

    assert not any(
        line.startswith("(allow file-read* (require-all")
        or line.startswith("(allow file-write* (require-all")
        for line in rendered.splitlines()
    )


def test_profile_allows_network_host(tmp_path: Path) -> None:
    profile = render_seatbelt_profile(
        _request(_policy(tmp_path, network=NetworkMode.HOST), tmp_path)
    )

    assert "(allow network-outbound)" in profile
    assert "(allow network-inbound)" in profile


def test_profile_rejects_proxy_allowlist_without_proxy(tmp_path: Path) -> None:
    with pytest.raises(SandboxBackendError, match="network proxy"):
        render_seatbelt_profile(
            _request(_policy(tmp_path, network=NetworkMode.PROXY_ALLOWLIST), tmp_path)
        )


def test_profile_allows_only_proxy_endpoint_for_proxy_allowlist(tmp_path: Path) -> None:
    profile = render_seatbelt_profile(
        _request(
            _policy(
                tmp_path,
                network=NetworkMode.PROXY_ALLOWLIST,
                network_proxy=NetworkProxySpec(host="127.0.0.1", port=18080),
            ),
            tmp_path,
        )
    )

    assert "(allow network-outbound" in profile
    assert "localhost:18080" in profile
    assert "127.0.0.1:18080" not in profile
    assert "(allow network*)" not in profile
    assert "(deny network*)" not in profile


def test_profile_allows_full_disk_read_like_codex(tmp_path: Path) -> None:
    profile = render_seatbelt_profile(_request(_policy(tmp_path), tmp_path))

    assert "; allow read-only file operations" in profile
    assert _access_rule(profile, "file-read*", Path("/"))


def test_profile_full_read_excludes_explicit_denied_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    secret = tmp_path / "secret"
    workspace.mkdir()
    secret.mkdir()
    file_system = FileSystemPermissionProfile.workspace(
        workspace=workspace,
        denied_read_roots=(secret,),
        tmp_writable=False,
        tmpdir_env_writable=False,
    )
    policy = replace(_policy(workspace), file_system=file_system)

    rendered = render_seatbelt_profile(_request(policy, workspace))

    root_read = _access_rule(rendered, "file-read*", Path("/"))
    workspace_write = _access_rule(rendered, "file-write*", workspace)
    assert f'(require-not (subpath "{secret}"))' in root_read
    assert f'(subpath "{workspace}")' in workspace_write


def test_profile_fails_closed_for_unrepresentable_denied_glob(tmp_path: Path) -> None:
    file_system = FileSystemPermissionProfile.workspace(
        workspace=tmp_path,
        denied_read_globs=(str(tmp_path / "**" / "*.pem"),),
    )
    policy = replace(_policy(tmp_path), file_system=file_system)

    with pytest.raises(SandboxBackendError, match="denied read glob"):
        render_seatbelt_profile(_request(policy, tmp_path))


def test_profile_workspace_write_excludes_metadata_and_profile_carveouts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    readonly = workspace / "readonly"
    secret = workspace / "secret"
    workspace.mkdir()
    file_system = FileSystemPermissionProfile(
        entries=(
            FileSystemPermissionEntry(Path("/"), FileSystemAccess.READ),
            FileSystemPermissionEntry(workspace, FileSystemAccess.WRITE),
            FileSystemPermissionEntry(readonly, FileSystemAccess.READ),
            FileSystemPermissionEntry(secret, FileSystemAccess.DENY),
        )
    )
    policy = replace(_policy(workspace), file_system=file_system)

    rendered = render_seatbelt_profile(_request(policy, workspace))

    workspace_write = _access_rule(rendered, "file-write*", workspace)
    assert f'(require-not (subpath "{readonly}"))' in workspace_write
    assert f'(require-not (subpath "{secret}"))' in workspace_write
    for name in (".git", ".agents", ".codex"):
        assert name.replace(".", "\\.") in workspace_write


def test_profile_more_specific_read_reopens_denied_parent(tmp_path: Path) -> None:
    denied_parent = tmp_path / "home"
    readable_child = denied_parent / "user" / "project"
    denied_grandchild = readable_child / "private"
    profile = FileSystemPermissionProfile(
        entries=(
            FileSystemPermissionEntry(Path("/"), FileSystemAccess.READ),
            FileSystemPermissionEntry(denied_parent, FileSystemAccess.DENY),
            FileSystemPermissionEntry(readable_child, FileSystemAccess.READ),
            FileSystemPermissionEntry(denied_grandchild, FileSystemAccess.DENY),
        )
    )
    policy = replace(_policy(tmp_path), file_system=profile)

    rendered = render_seatbelt_profile(_request(policy, tmp_path))

    root_read = _access_rule(rendered, "file-read*", Path("/"))
    child_read = _access_rule(rendered, "file-read*", readable_child)
    assert f'(require-not (subpath "{denied_parent}"))' in root_read
    assert f'(require-not (subpath "{denied_grandchild}"))' in child_read


def test_profile_more_specific_write_reopens_readonly_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    readonly = workspace / "readonly"
    writable_child = readonly / "generated"
    denied_grandchild = writable_child / "secret"
    profile = FileSystemPermissionProfile(
        entries=(
            FileSystemPermissionEntry(workspace, FileSystemAccess.WRITE),
            FileSystemPermissionEntry(readonly, FileSystemAccess.READ),
            FileSystemPermissionEntry(writable_child, FileSystemAccess.WRITE),
            FileSystemPermissionEntry(denied_grandchild, FileSystemAccess.DENY),
        )
    )
    policy = replace(_policy(workspace), file_system=profile)

    rendered = render_seatbelt_profile(_request(policy, workspace))

    workspace_write = _access_rule(rendered, "file-write*", workspace)
    child_write = _access_rule(rendered, "file-write*", writable_child)
    assert f'(require-not (subpath "{readonly}"))' in workspace_write
    assert f'(require-not (subpath "{denied_grandchild}"))' in child_write


def test_profile_scoped_workspace_write_also_grants_read_without_ambient_access(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    file_system = FileSystemPermissionProfile.workspace(
        workspace=workspace,
        host_root_readonly=False,
        tmp_writable=False,
        tmpdir_env_writable=False,
    )
    policy = replace(_policy(workspace), file_system=file_system)

    rendered = render_seatbelt_profile(_request(policy, workspace))

    assert _access_rule(rendered, "file-read*", workspace)
    assert _access_rule(rendered, "file-write*", workspace)
    assert f'(subpath "{outside}")' not in rendered
    assert "(allow file-read*)\n" not in rendered


def test_profile_does_not_add_ambient_tmp_write_outside_shared_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    env_tmp = tmp_path / "ambient-tmp"
    workspace.mkdir()
    env_tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(env_tmp))
    file_system = FileSystemPermissionProfile.workspace(
        workspace=workspace,
        host_root_readonly=False,
        tmp_writable=False,
        tmpdir_env_writable=False,
    )
    policy = replace(
        _policy(workspace, tmp_writable=True),
        file_system=file_system,
    )

    rendered = render_seatbelt_profile(_request(policy, workspace))

    assert f'(subpath "{Path("/tmp")}")' not in rendered
    assert f'(subpath "{env_tmp}")' not in rendered


def test_profile_adds_ambient_tmp_write_only_once_from_shared_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TMPDIR", "/tmp")
    policy = _policy(tmp_path)

    rendered = render_seatbelt_profile(_request(policy, tmp_path))

    tmp_write_rules = [
        line
        for line in rendered.splitlines()
        if line.startswith("(allow file-write*") and '(subpath "/tmp")' in line
    ]
    assert len(tmp_write_rules) == 1


def test_profile_process_local_tmp_is_private_readwrite_transport(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    private_tmp = tmp_path / "seatbelt-private-tmp"
    workspace.mkdir()
    private_tmp.mkdir()
    file_system = FileSystemPermissionProfile.workspace(
        workspace=workspace,
        host_root_readonly=False,
        tmp_writable=False,
        tmpdir_env_writable=False,
    )
    policy = replace(_policy(workspace), file_system=file_system)

    rendered = render_seatbelt_profile(
        _request(policy, workspace),
        tmp_dir=private_tmp,
    )

    assert _access_rule(rendered, "file-read*", private_tmp)
    assert _access_rule(rendered, "file-write*", private_tmp)


def test_profile_rejects_non_loopback_proxy_endpoint(tmp_path: Path) -> None:
    policy = _policy(
        tmp_path,
        network=NetworkMode.PROXY_ALLOWLIST,
        network_proxy=NetworkProxySpec(host="192.0.2.10", port=18080),
    )

    with pytest.raises(SandboxBackendError, match="loopback"):
        render_seatbelt_profile(_request(policy, tmp_path))


def test_profile_keeps_workspace_ro_when_policy_ro(tmp_path: Path) -> None:
    profile = render_seatbelt_profile(
        _request(_policy(tmp_path, workspace_rw=False), tmp_path)
    )

    assert _access_rule(profile, "file-read*", Path("/"))
    assert not any(
        line.startswith("(allow file-write*") and f'(subpath "{tmp_path}")' in line
        for line in profile.splitlines()
    )


def test_profile_denies_writes_to_protected_metadata_under_workspace(tmp_path: Path) -> None:
    for name in (".git", ".codex", ".agents"):
        (tmp_path / name).mkdir()

    profile = render_seatbelt_profile(_request(_policy(tmp_path), tmp_path))

    for name in (".git", ".codex", ".agents"):
        assert name.replace(".", "\\.") in profile
        assert "(require-not (regex" in profile


def test_profile_escapes_paths(tmp_path: Path) -> None:
    hostile = tmp_path / 'quote"path'
    hostile.mkdir()
    policy = _policy(
        hostile,
        mounts=(
            MountSpec(
                host_path=hostile,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
    )

    profile = render_seatbelt_profile(_request(policy, hostile))

    assert '\\"' in profile
    assert '"quote"path"' not in profile


def test_missing_required_mount_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    policy = _policy(
        tmp_path,
        mounts=(
            MountSpec(
                host_path=missing,
                sandbox_path=Path("/workspace"),
                mode="ro",
                required=True,
            ),
        ),
    )

    with pytest.raises(SandboxBackendError, match="required mount missing"):
        seatbelt_mod._validate_request(_request(policy, tmp_path))


def test_missing_optional_mount_is_skipped(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    policy = _policy(
        tmp_path,
        mounts=(
            MountSpec(
                host_path=tmp_path,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
            MountSpec(
                host_path=missing,
                sandbox_path=missing,
                mode="rw",
                required=False,
            ),
        ),
    )

    policy = replace(
        policy,
        file_system=FileSystemPermissionProfile.workspace(
            workspace=tmp_path,
            tmp_writable=False,
            tmpdir_env_writable=False,
        ),
    )

    profile = render_seatbelt_profile(_request(policy, tmp_path))

    assert str(missing) not in profile


def test_build_argv_uses_sandbox_exec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        seatbelt_mod,
        "_sandbox_exec_binary",
        lambda binary=None: "/usr/bin/sandbox-exec",
    )

    argv = build_seatbelt_argv(
        _request(_policy(tmp_path), tmp_path),
        tmp_path / "profile.sb",
    )

    assert argv[:3] == ["/usr/bin/sandbox-exec", "-f", str(tmp_path / "profile.sb")]
    assert argv[3:] == ["sh", "-lc", "echo ok"]


@pytest.mark.asyncio
async def test_run_filters_env_and_returns_nonzero_without_raise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 12345
        returncode = 7

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            return b"", b"nope"

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> FakeProcess:
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        captured["cwd"] = kwargs["cwd"]
        return FakeProcess()

    monkeypatch.setattr(seatbelt_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        seatbelt_mod,
        "_sandbox_exec_binary",
        lambda binary=None: "/usr/bin/sandbox-exec",
    )
    monkeypatch.setattr(
        seatbelt_mod.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await SeatbeltBackend().run(_request(_policy(tmp_path), tmp_path))

    assert result.returncode == 7
    assert result.stderr == "nope"
    assert result.backend_used == "seatbelt"
    assert result.timed_out is False
    assert captured["cwd"] == str(tmp_path)
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["PATH"] == "/bin"
    assert "SECRET" not in env
    assert "TMPDIR" in env
    tmpdir = Path(env["TMPDIR"])
    assert env["XDG_CACHE_HOME"] == str(tmpdir / "cache" / "xdg")
    assert env["npm_config_cache"] == str(tmpdir / "cache" / "npm")
    assert env["PIP_CACHE_DIR"] == str(tmpdir / "cache" / "pip")
    assert env["UV_CACHE_DIR"] == str(tmpdir / "cache" / "uv")


@pytest.mark.asyncio
async def test_run_injects_proxy_env_for_proxy_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 12345
        returncode = 0

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            return b"ok\n", b""

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> FakeProcess:
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(seatbelt_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        seatbelt_mod,
        "_sandbox_exec_binary",
        lambda binary=None: "/usr/bin/sandbox-exec",
    )
    monkeypatch.setattr(
        seatbelt_mod.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    policy = _policy(
        tmp_path,
        network=NetworkMode.PROXY_ALLOWLIST,
        network_proxy=NetworkProxySpec(host="127.0.0.1", port=18080),
    )
    request = _request(policy, tmp_path)
    request.env["HTTP_PROXY"] = "http://attacker.invalid:1"

    result = await SeatbeltBackend().run(request)

    assert result.returncode == 0
    env = captured["env"]
    assert isinstance(env, dict)
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "npm_config_proxy",
        "PIP_PROXY",
    ):
        assert env[key] == "http://127.0.0.1:18080"
    assert env["NODE_USE_ENV_PROXY"] == "1"
    assert env["OPENSQUILLA_SANDBOX_NETWORK"] == "proxy_allowlist"
    assert "http://attacker.invalid:1" not in env.values()


@pytest.mark.asyncio
async def test_run_timeout_returns_timed_out_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeProcess:
        pid = 12345
        returncode = -15
        stdout = None
        stderr = None

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            await asyncio.sleep(1)
            return b"", b""

        async def wait(self) -> None:
            return None

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(seatbelt_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        seatbelt_mod,
        "_sandbox_exec_binary",
        lambda binary=None: "/usr/bin/sandbox-exec",
    )
    monkeypatch.setattr(
        seatbelt_mod.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(seatbelt_mod.os, "killpg", lambda pid, sig: None)

    result = await SeatbeltBackend().run(_request(_policy(tmp_path), tmp_path))

    assert result.timed_out is True
    assert result.returncode == -15


@pytest.mark.asyncio
async def test_real_seatbelt_runs_python_when_available(tmp_path: Path) -> None:
    if not SeatbeltBackend().available():
        pytest.skip("requires macOS sandbox-exec")
    policy = _policy(tmp_path)
    request = SandboxRequest(
        argv=(sys.executable, "-c", "print('ok')"),
        cwd=tmp_path,
        action_kind="code.exec",
        policy=policy,
        env={"PATH": "/bin:/usr/bin"},
    )

    result = await SeatbeltBackend().run(request)

    assert result.returncode == 0
    assert result.stdout == "ok\n"
    assert result.stderr == ""


@pytest.mark.asyncio
async def test_real_seatbelt_shell_can_write_slash_tmp_when_available(
    tmp_path: Path,
) -> None:
    if not SeatbeltBackend().available():
        pytest.skip("requires macOS sandbox-exec")
    target = Path("/tmp") / f"opensquilla_sandbox_shell_probe_{os.getpid()}.txt"
    policy = _policy(tmp_path)
    request = SandboxRequest(
        argv=(
            "sh",
            "-lc",
            f"printf '%s\\n' shell-temp-ok > {target} && cat {target} && rm {target}",
        ),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        env={"PATH": "/bin:/usr/bin"},
    )

    try:
        result = await SeatbeltBackend().run(request)
    finally:
        target.unlink(missing_ok=True)

    assert result.returncode == 0
    assert result.stdout == "shell-temp-ok\n"
    assert result.stderr == ""
    assert result.backend_notes == ()


@pytest.mark.asyncio
async def test_real_seatbelt_blocks_write_outside_workspace_when_available(
    tmp_path: Path,
) -> None:
    if not SeatbeltBackend().available():
        pytest.skip("requires macOS sandbox-exec")
    outside = Path.home() / f"opensquilla-seatbelt-outside-{os.getpid()}.txt"
    policy = _policy(tmp_path)
    request = SandboxRequest(
        argv=(
            sys.executable,
            "-c",
            f"open({str(outside)!r}, 'w').write('blocked')",
        ),
        cwd=tmp_path,
        action_kind="code.exec",
        policy=policy,
        env={"PATH": "/bin:/usr/bin"},
    )

    result = await SeatbeltBackend().run(request)

    assert result.returncode != 0
    assert "PermissionError" in result.stderr
    assert not outside.exists()


@pytest.mark.asyncio
async def test_real_seatbelt_proxy_allowlist_allows_loopback_proxy_port_when_available(
    tmp_path: Path,
) -> None:
    if not SeatbeltBackend().available():
        pytest.skip("requires macOS sandbox-exec")

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _ = await reader.read(16)
        writer.write(b"ok\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        sock = server.sockets[0]
        host, port = sock.getsockname()[:2]
        policy = _policy(
            tmp_path,
            network=NetworkMode.PROXY_ALLOWLIST,
            network_proxy=NetworkProxySpec(host=str(host), port=int(port)),
        )
        code = (
            "import socket\n"
            f"s = socket.create_connection(('127.0.0.1', {int(port)}), timeout=2)\n"
            "s.sendall(b'hi')\n"
            "print(s.recv(16).decode(), end='')\n"
            "s.close()\n"
        )
        request = SandboxRequest(
            argv=(sys.executable, "-c", code),
            cwd=tmp_path,
            action_kind="network.http",
            policy=policy,
            env={"PATH": "/bin:/usr/bin"},
        )

        result = await SeatbeltBackend().run(request)
    finally:
        server.close()
        await server.wait_closed()

    assert result.returncode == 0
    assert result.stdout == "ok\n"
    assert result.stderr == ""


@pytest.mark.asyncio
async def test_real_seatbelt_blocks_loopback_tcp_when_network_none(
    tmp_path: Path,
) -> None:
    if not SeatbeltBackend().available():
        pytest.skip("requires macOS sandbox-exec")

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _ = await reader.read(16)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        sock = server.sockets[0]
        _host, port = sock.getsockname()[:2]
        policy = _policy(tmp_path, network=NetworkMode.NONE, network_proxy=None)
        code = (
            "import socket\n"
            f"socket.create_connection(('127.0.0.1', {int(port)}), timeout=2)\n"
            "print('connected')\n"
        )
        request = SandboxRequest(
            argv=(sys.executable, "-c", code),
            cwd=tmp_path,
            action_kind="network.http",
            policy=policy,
            env={"PATH": "/bin:/usr/bin"},
        )

        result = await SeatbeltBackend().run(request)
    finally:
        server.close()
        await server.wait_closed()

    assert result.returncode != 0
    assert "connected" not in result.stdout
    assert "PermissionError" in result.stderr or "Operation not permitted" in result.stderr


# ─── _classify_denial tests ───────────────────────────────────────────────


def test_classify_denial_execvp_blocked() -> None:
    stderr = "sandbox-exec: execvp() of '/opt/homebrew/bin/uv' failed: Operation not permitted"
    notes = _classify_denial(("sh",), stderr)
    assert len(notes) == 1
    assert notes[0].category == "execve.denied"
    assert "/opt/homebrew/bin/uv" in notes[0].hint


def test_classify_denial_filesystem_read_blocked() -> None:
    stderr = "/etc/ssl/cert.pem: Operation not permitted"
    notes = _classify_denial(("python",), stderr)
    assert len(notes) == 1
    assert notes[0].category == "filesystem.read"
    assert "/etc/ssl/cert.pem" in notes[0].hint


def test_classify_denial_ping_sendto_blocked() -> None:
    stderr = "ping: sendto: Operation not permitted\n"

    notes = _classify_denial(("sh", "-lc", "/sbin/ping -c 1 1.1.1.1"), stderr)

    assert len(notes) == 1
    assert notes[0].category == "network.denied"
    assert "ICMP" in notes[0].hint


def test_classify_denial_ping_packet_loss_under_restricted_network() -> None:
    stdout = (
        "PING 1.1.1.1 (1.1.1.1): 56 data bytes\n\n"
        "--- 1.1.1.1 ping statistics ---\n"
        "1 packets transmitted, 0 packets received, 100.0% packet loss\n"
    )

    notes = _classify_denial(
        ("sh", "-lc", "ping -c 1 -W 3000 1.1.1.1"),
        "",
        stdout=stdout,
        network=NetworkMode.PROXY_ALLOWLIST,
    )

    assert len(notes) == 1
    assert notes[0].category == "network.denied"
    assert "ICMP" in notes[0].hint


def test_classify_denial_ping_packet_loss_ignored_on_host_network() -> None:
    stdout = "1 packets transmitted, 0 packets received, 100.0% packet loss\n"

    notes = _classify_denial(
        ("sh", "-lc", "ping -c 1 1.1.1.1"),
        "",
        stdout=stdout,
        network=NetworkMode.HOST,
    )

    assert notes == ()


def test_classify_denial_dyld_library_not_loaded() -> None:
    stderr = "dyld[123]: Library not loaded: /opt/homebrew/opt/openssl/lib/libssl.dylib"
    notes = _classify_denial(("python",), stderr)
    assert len(notes) == 1
    assert notes[0].category == "filesystem.read"
    assert "libssl.dylib" in notes[0].hint


def test_classify_denial_empty_stderr_returns_empty() -> None:
    assert _classify_denial(("sh",), "") == ()


def test_classify_denial_unrelated_stderr_returns_empty() -> None:
    assert _classify_denial(("sh",), "syntax error near unexpected token") == ()


def test_classify_denial_deduplicates_same_path() -> None:
    stderr = (
        "/etc/ssl/cert.pem: Operation not permitted\n"
        "/etc/ssl/cert.pem: Operation not permitted\n"
    )
    notes = _classify_denial(("python",), stderr)
    assert len(notes) == 1


@pytest.mark.asyncio
async def test_run_populates_backend_notes_on_denial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    denial_stderr = (
        "sandbox-exec: execvp() of '/opt/homebrew/bin/uv' failed: Operation not permitted"
    )

    class FakeProcess:
        pid = 12345
        returncode = 1

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            return b"", denial_stderr.encode()

    async def fake_create(*args: object, **kwargs: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(seatbelt_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        seatbelt_mod, "_sandbox_exec_binary", lambda binary=None: "/usr/bin/sandbox-exec"
    )
    monkeypatch.setattr(seatbelt_mod.asyncio, "create_subprocess_exec", fake_create)

    result = await SeatbeltBackend().run(_request(_policy(tmp_path), tmp_path))

    assert len(result.backend_notes) == 1
    assert result.backend_notes[0].startswith("execve.denied:")


@pytest.mark.asyncio
async def test_run_populates_backend_notes_for_zero_exit_ping_packet_loss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ping_stdout = (
        "PING 1.1.1.1 (1.1.1.1): 56 data bytes\n\n"
        "--- 1.1.1.1 ping statistics ---\n"
        "1 packets transmitted, 0 packets received, 100.0% packet loss\n"
    )

    class FakeProcess:
        pid = 12345
        returncode = 0

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            return ping_stdout.encode(), b""

    async def fake_create(*args: object, **kwargs: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(seatbelt_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        seatbelt_mod, "_sandbox_exec_binary", lambda binary=None: "/usr/bin/sandbox-exec"
    )
    monkeypatch.setattr(seatbelt_mod.asyncio, "create_subprocess_exec", fake_create)
    policy = _policy(
        tmp_path,
        network=NetworkMode.PROXY_ALLOWLIST,
        network_proxy=NetworkProxySpec(host="127.0.0.1", port=18080),
    )
    request = SandboxRequest(
        argv=("sh", "-lc", "ping -c 1 -W 3000 1.1.1.1"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
    )

    result = await SeatbeltBackend().run(request)

    assert result.returncode == 0
    assert len(result.backend_notes) == 1
    assert result.backend_notes[0].startswith("network.denied:")


@pytest.mark.asyncio
async def test_run_backend_notes_empty_on_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeProcess:
        pid = 12345
        returncode = 0

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            return b"ok", b""

    async def fake_create(*args: object, **kwargs: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(seatbelt_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        seatbelt_mod, "_sandbox_exec_binary", lambda binary=None: "/usr/bin/sandbox-exec"
    )
    monkeypatch.setattr(seatbelt_mod.asyncio, "create_subprocess_exec", fake_create)

    result = await SeatbeltBackend().run(_request(_policy(tmp_path), tmp_path))

    assert result.backend_notes == ()


@pytest.mark.asyncio
async def test_run_operation_delegates_filesystem_to_seatbelt_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    profile = FileSystemPermissionProfile.workspace(workspace=workspace)
    captured: dict[str, object] = {}

    async def fake_run(self: SeatbeltBackend, request: SandboxRequest) -> object:
        payload_path = Path(request.argv[-1])
        captured["request"] = request
        captured["payload_path"] = payload_path
        captured["payload"] = json.loads(payload_path.read_text(encoding="utf-8"))
        return SandboxResult(
            returncode=0,
            stdout=json.dumps({"message": f"Written 5 bytes to {target}", "created": True}),
            stderr="",
            wall_time_s=0.0,
            backend_used=self.name,
        )

    monkeypatch.setattr(SeatbeltBackend, "run", fake_run)

    operation = SandboxOperation.filesystem(
        kind="write_text",
        workspace=workspace,
        run_mode="trusted",
        path=target,
        paths=(target,),
        content="hello",
        file_system_profile=profile,
    )
    result = await SeatbeltBackend().run_operation(operation)

    assert result == SandboxOperationResult(
        message=f"Written 5 bytes to {target}",
        created=True,
    )
    request = captured["request"]
    assert isinstance(request, SandboxRequest)
    assert request.action_kind == "fs.worker.write_text"
    assert request.cwd == workspace / ".opensquilla-cache" / "fs-worker"
    assert request.policy.network == NetworkMode.NONE
    assert request.policy.file_system is profile
    assert target not in {mount.host_path for mount in request.policy.mounts}
    runtime_roots = set(seatbelt_mod._runtime_readonly_roots())
    assert {
        mount.host_path for mount in request.policy.mounts if mount.mode == "ro"
    } == runtime_roots
    assert {mount.host_path for mount in request.policy.mounts if mount.mode == "rw"} == {
        request.cwd
    }
    assert "opensquilla.sandbox.filesystem_worker" in request.argv
    assert captured["payload"] == {
        "domain": "filesystem",
        "kind": "write_text",
        "workspace": str(workspace),
        "runMode": "trusted",
        "toolName": "filesystem",
        "operationId": "",
        "summary": "",
        "permissions": {
            "filesystem": {},
            "network": {},
            "process": {},
            "artifact": {},
            "media": {},
        },
        "approval": {
            "required": False,
            "reason": "",
            "namespace": "sandbox",
            "payload": {},
        },
        "request": {
            "path": str(target),
            "paths": [str(target)],
            "displayPath": "",
            "content": "hello",
            "oldText": "",
            "newText": "",
            "patch": "",
            "root": None,
            "offset": None,
            "limit": None,
            "pattern": "",
            "include": None,
            "maxResults": None,
        },
        "path": str(target),
        "paths": [str(target)],
        "displayPath": "",
        "content": "hello",
        "oldText": "",
        "newText": "",
        "patch": "",
        "root": None,
        "offset": None,
        "limit": None,
        "pattern": "",
        "include": None,
        "maxResults": None,
    }
    payload_path = captured["payload_path"]
    assert isinstance(payload_path, Path)
    assert not payload_path.exists()


@pytest.mark.asyncio
async def test_run_operation_fails_closed_without_resolved_profile(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"

    with pytest.raises(
        ValueError,
        match="^filesystem operation is missing resolved filesystem profile$",
    ):
        await SeatbeltBackend().run_operation(
            SandboxOperation.filesystem(
                kind="write_text",
                workspace=workspace,
                run_mode="trusted",
                path=target,
                content="hello",
            )
        )


def test_filesystem_operation_validates_missing_read_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    missing = workspace / "missing.txt"
    operation = SandboxOperation.filesystem(
        kind="read_file",
        workspace=workspace,
        run_mode="trusted",
        path=missing,
        file_system_profile=FileSystemPermissionProfile.workspace(workspace=workspace),
    )

    with pytest.raises(FileNotFoundError, match="File not found"):
        seatbelt_mod._filesystem_operation_request(
            operation,
            workspace / ".opensquilla-cache" / "fs-worker" / "payload.json",
        )


def test_filesystem_operation_validates_list_target_type(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("hello", encoding="utf-8")
    operation = SandboxOperation.filesystem(
        kind="list_dir",
        workspace=workspace,
        run_mode="trusted",
        path=target,
        file_system_profile=FileSystemPermissionProfile.workspace(workspace=workspace),
    )

    with pytest.raises(NotADirectoryError, match="Not a directory"):
        seatbelt_mod._filesystem_operation_request(
            operation,
            workspace / ".opensquilla-cache" / "fs-worker" / "payload.json",
        )
