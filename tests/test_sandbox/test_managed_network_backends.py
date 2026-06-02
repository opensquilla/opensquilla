from __future__ import annotations

import sys
from pathlib import Path

import pytest

import opensquilla.sandbox as sandbox
from opensquilla.sandbox.backend import bubblewrap as bubblewrap_mod
from opensquilla.sandbox.backend.bubblewrap import BubblewrapBackend, build_bwrap_argv
from opensquilla.sandbox.backend.seatbelt import render_seatbelt_profile
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    NetworkProxySpec,
    ResourceLimits,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)

_UNSET = object()


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


def test_bubblewrap_proxy_allowlist_with_proxy_builds_bridge_argv(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, network_proxy=_proxy_spec())

    argv = build_bwrap_argv(_request(policy, tmp_path), binary="bwrap")

    separator = argv.index("--")
    child_argv = argv[separator + 1 :]
    assert "--unshare-net" in argv
    assert child_argv[:4] == [
        sys.executable,
        "-m",
        "opensquilla.sandbox.backend.linux_proxy_bridge",
        "--",
    ]
    assert child_argv[4:] == ["sh", "-lc", "echo ok"]
    assert argv.count("echo ok") == 1
    assert "OPENSQUILLA_SANDBOX_PROXY_UDS" in argv
    assert "OPENSQUILLA_SANDBOX_PROXY_PORT" in argv
    assert "HTTP_PROXY" in argv
    assert "http://127.0.0.1:8080" in argv


def test_bubblewrap_proxy_allowlist_proxy_env_overrides_user_input(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, network_proxy=_proxy_spec())
    request = _request(policy, tmp_path)
    request.env["HTTP_PROXY"] = "http://attacker.invalid:1"

    argv = build_bwrap_argv(request, binary="bwrap")

    assert "http://127.0.0.1:8080" in argv
    assert "http://attacker.invalid:1" not in argv


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
    assert "opensquilla.sandbox.backend.linux_proxy_bridge" in argv


def test_seatbelt_proxy_allowlist_with_proxy_renders_proxy_only_profile(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, network_proxy=_proxy_spec())

    profile = render_seatbelt_profile(_request(policy, tmp_path))

    assert "(allow network-outbound" in profile
    assert "127.0.0.1:8080" in profile
    assert "(allow network*)" not in profile
    assert "(deny network*)" not in profile


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
