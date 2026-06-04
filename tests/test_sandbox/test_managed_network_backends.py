from __future__ import annotations

import asyncio
import sys
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

import opensquilla.sandbox as sandbox
from opensquilla.gateway.routing import build_cli_route_envelope, tool_context_from_envelope
from opensquilla.sandbox import integration as integration_mod
from opensquilla.sandbox.backend import bubblewrap as bubblewrap_mod
from opensquilla.sandbox.backend.bubblewrap import BubblewrapBackend, build_bwrap_argv
from opensquilla.sandbox.backend.seatbelt import render_seatbelt_profile
from opensquilla.sandbox.run_context import DomainGrant, RunContext
from opensquilla.sandbox.run_mode import RunMode
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
from opensquilla.tools.types import current_tool_context

_UNSET = object()
_BWRAP_PROXY_BRIDGE_LINUX_ONLY = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="bubblewrap proxy bridge uses Linux mount and Unix socket paths",
)


def _proxy_spec(host: str = "127.0.0.1", port: int = 8080) -> NetworkProxySpec:
    return NetworkProxySpec(host=host, port=port)


def _policy(
    workspace: Path,
    *,
    network: NetworkMode = NetworkMode.PROXY_ALLOWLIST,
    network_proxy: NetworkProxySpec | object = _UNSET,
) -> SandboxPolicy:
    kwargs = {
        "level": SecurityLevel.STANDARD,
        "network": network,
        "mounts": (
            MountSpec(
                host_path=workspace,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
        "workspace_rw": True,
        "tmp_writable": True,
        "limits": ResourceLimits(wall_timeout_s=0.1),
        "env_allowlist": ("PATH",),
        "require_approval": False,
    }
    if network_proxy is not _UNSET:
        kwargs["network_proxy"] = network_proxy
    return SandboxPolicy(**kwargs)


def _request(policy: SandboxPolicy, cwd: Path) -> SandboxRequest:
    return SandboxRequest(
        argv=("sh", "-lc", "echo ok"),
        cwd=cwd,
        action_kind="network.http",
        policy=policy,
        env={"PATH": "/bin"},
    )


def test_bubblewrap_treats_sandbox_paths_as_posix_on_windows(
    tmp_path: Path,
) -> None:
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(
                host_path=tmp_path,
                sandbox_path=PureWindowsPath("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=0.1),
        env_allowlist=("PATH",),
        require_approval=False,
    )

    argv = build_bwrap_argv(_request(policy, tmp_path), binary="bwrap")

    assert "/workspace" in argv
    assert "\\workspace" not in argv


def test_bubblewrap_proxy_allowlist_without_proxy_fails_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(SandboxBackendError, match="network proxy"):
        build_bwrap_argv(_request(_policy(tmp_path), tmp_path), binary="bwrap")


def test_seatbelt_proxy_allowlist_without_proxy_fails_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(SandboxBackendError, match="network proxy"):
        render_seatbelt_profile(_request(_policy(tmp_path), tmp_path))


@_BWRAP_PROXY_BRIDGE_LINUX_ONLY
def test_bubblewrap_proxy_allowlist_with_proxy_builds_bridge_argv(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, network_proxy=_proxy_spec())
    bridge_uds_path = tmp_path / "bridge" / "proxy.sock"
    bridge_script_path = bridge_uds_path.parent / "inner_bridge.py"

    argv = build_bwrap_argv(
        _request(policy, tmp_path),
        binary="bwrap",
        bridge_uds_path=bridge_uds_path,
        bridge_script_path=bridge_script_path,
    )

    separator = argv.index("--")
    child_argv = argv[separator + 1 :]
    assert "--unshare-net" in argv
    assert child_argv[:3] == [
        "/usr/bin/python3",
        str(bridge_script_path),
        "--",
    ]
    assert child_argv[3:] == ["sh", "-lc", "echo ok"]
    assert sys.executable not in child_argv
    assert "-m" not in child_argv
    assert "opensquilla.sandbox.backend.linux_proxy_bridge" not in child_argv
    assert argv.count("echo ok") == 1
    assert "OPENSQUILLA_SANDBOX_PROXY_UDS" in argv
    assert "OPENSQUILLA_SANDBOX_PROXY_PORT" in argv
    assert "HTTP_PROXY" in argv
    assert "http://127.0.0.1:8080" in argv


@_BWRAP_PROXY_BRIDGE_LINUX_ONLY
def test_bubblewrap_proxy_allowlist_proxy_env_overrides_user_input(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, network_proxy=_proxy_spec())
    request = _request(policy, tmp_path)
    request.env["HTTP_PROXY"] = "http://attacker.invalid:1"

    argv = build_bwrap_argv(request, binary="bwrap")

    assert "http://127.0.0.1:8080" in argv
    assert "http://attacker.invalid:1" not in argv


def test_bubblewrap_sets_home_to_workspace_when_workspace_is_mounted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/home/lrk")
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(
                host_path=tmp_path,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=0.1),
        env_allowlist=("PATH", "HOME"),
        require_approval=False,
    )
    request = SandboxRequest(
        argv=("sh", "-lc", "echo $HOME"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        env={"HOME": "/home/lrk"},
    )

    argv = build_bwrap_argv(request, binary="bwrap")

    home_index = argv.index("HOME")
    assert argv[home_index + 1] == "/workspace"
    assert "/home/lrk" not in argv[home_index : home_index + 2]


@_BWRAP_PROXY_BRIDGE_LINUX_ONLY
@pytest.mark.asyncio
async def test_bubblewrap_run_starts_and_stops_proxy_bridge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, network_proxy=_proxy_spec(port=18080))
    events: list[str] = []
    captured: dict[str, object] = {}

    class FakeBridge:
        def __init__(self, uds_path: Path, upstream_host: str, upstream_port: int) -> None:
            captured["bridge"] = (uds_path, upstream_host, upstream_port)

        async def start(self) -> None:
            events.append("bridge.start")

        async def stop(self) -> None:
            events.append("bridge.stop")

    class FakeProcess:
        pid = 12345
        returncode = 0

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            events.append("process.communicate")
            return b"ok\n", b""

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> FakeProcess:
        events.append("process.spawn")
        captured["argv"] = argv
        return FakeProcess()

    monkeypatch.setattr(BubblewrapBackend, "available", lambda self: True)
    monkeypatch.setattr(bubblewrap_mod, "LinuxProxyBridgeHost", FakeBridge)
    monkeypatch.setattr(
        bubblewrap_mod.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await BubblewrapBackend(binary="bwrap").run(_request(policy, tmp_path))

    assert events == [
        "bridge.start",
        "process.spawn",
        "process.communicate",
        "bridge.stop",
    ]
    assert result.returncode == 0
    assert result.stdout == "ok\n"
    bridge = captured["bridge"]
    assert isinstance(bridge, tuple)
    assert bridge[1:] == ("127.0.0.1", 18080)
    argv = captured["argv"]
    assert isinstance(argv, tuple)
    assert "--unshare-net" in argv
    assert "opensquilla.sandbox.backend.linux_proxy_bridge" not in argv
    assert "-m" not in argv
    assert "/usr/bin/python3" in argv
    assert any(str(arg).endswith("/inner_bridge.py") for arg in argv)


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="asyncio Unix domain sockets are unavailable on Windows",
)
@pytest.mark.asyncio
async def test_linux_proxy_bridge_host_writes_and_removes_inner_script(
    tmp_path: Path,
) -> None:
    bridge = bubblewrap_mod.LinuxProxyBridgeHost(
        tmp_path / "proxy.sock",
        "127.0.0.1",
        9,
    )

    await bridge.start()
    try:
        assert bridge.script_path.exists()
        script = bridge.script_path.read_text(encoding="utf-8")
        assert "def main(" in script
        assert "asyncio.start_server" in script
    finally:
        await bridge.stop()

    assert not bridge.script_path.exists()


def test_seatbelt_proxy_allowlist_with_proxy_renders_proxy_only_profile(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, network_proxy=_proxy_spec())

    profile = render_seatbelt_profile(_request(policy, tmp_path))

    assert "(allow network-outbound" in profile
    assert "127.0.0.1:8080" in profile
    assert "(allow network*)" not in profile
    assert "(deny network*)" not in profile


@pytest.mark.asyncio
async def test_run_under_backend_populates_proxy_from_current_run_context(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}

    class FakeBackend:
        name = "fake"

        async def run(self, request: SandboxRequest) -> SandboxResult:
            proxy = request.policy.network_proxy
            seen["proxy"] = proxy
            assert proxy is not None
            reader, writer = await asyncio.open_connection(proxy.host, proxy.port)
            try:
                writer.write(
                    b"GET http://Blocked.test/path HTTP/1.1\r\n"
                    b"\r\n"
                )
                await writer.drain()
                seen["proxy_response"] = await reader.read(4096)
            finally:
                writer.close()
                await writer.wait_closed()
            return SandboxResult(
                returncode=0,
                stdout="ok",
                stderr="",
                wall_time_s=0.0,
                backend_used="fake",
            )

    runtime = SimpleNamespace(backend=FakeBackend())
    policy = _policy(tmp_path, network_proxy=None)
    run_context = RunContext(
        run_mode=RunMode.STANDARD,
        domains=(DomainGrant(domain="allowed.test"),),
    )
    envelope = build_cli_route_envelope(
        session_key="agent:main:webchat:abc",
        run_mode="standard",
    )
    envelope.metadata["sandbox_run_context"] = run_context.to_origin_payload()
    ctx = tool_context_from_envelope(envelope, workspace_dir=str(tmp_path))
    token = current_tool_context.set(ctx)
    try:
        result = await integration_mod.run_under_backend(
            _request(policy, tmp_path),
            runtime=runtime,
        )
    finally:
        current_tool_context.reset(token)

    assert result.stdout == "ok"
    assert seen["proxy_response"].startswith(b"HTTP/1.1 403")
    proxy = seen["proxy"]
    assert isinstance(proxy, NetworkProxySpec)
    assert proxy.host == "127.0.0.1"
    assert proxy.port > 0


@pytest.mark.asyncio
async def test_run_under_backend_proxy_allowlist_without_context_fails_closed(
    tmp_path: Path,
) -> None:
    class FakeBackend:
        name = "fake"

        async def run(self, request: SandboxRequest) -> SandboxResult:
            raise AssertionError("backend should not run without proxy context")

    runtime = SimpleNamespace(backend=FakeBackend())

    with pytest.raises(SandboxBackendError, match="Run Context"):
        await integration_mod.run_under_backend(
            _request(_policy(tmp_path, network_proxy=None), tmp_path),
            runtime=runtime,
        )


def test_policy_positional_description_keeps_legacy_binding(
    tmp_path: Path,
) -> None:
    policy = SandboxPolicy(
        SecurityLevel.STANDARD,
        NetworkMode.NONE,
        (
            MountSpec(
                host_path=tmp_path,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
        True,
        True,
        ResourceLimits(wall_timeout_s=0.1),
        ("PATH",),
        False,
        "legacy description",
    )

    assert policy.description == "legacy description"
    assert policy.network_proxy is None


def test_package_reexports_network_proxy_spec() -> None:
    assert sandbox.NetworkProxySpec is NetworkProxySpec


def test_policy_summary_includes_network_proxy_none(tmp_path: Path) -> None:
    summary = _policy(tmp_path).summary()

    assert summary.get("network_proxy", _UNSET) is None


def test_policy_summary_includes_network_proxy_object(tmp_path: Path) -> None:
    summary = _policy(
        tmp_path,
        network_proxy=_proxy_spec(host="127.0.0.1", port=18080),
    ).summary()

    assert summary["network_proxy"] == {"host": "127.0.0.1", "port": 18080}
