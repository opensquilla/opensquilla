from __future__ import annotations

from pathlib import Path

import pytest

import opensquilla.sandbox as sandbox
from opensquilla.sandbox.backend.bubblewrap import build_bwrap_argv
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


def test_bubblewrap_proxy_allowlist_with_proxy_requires_linux_bridge(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, network_proxy=_proxy_spec())

    with pytest.raises(SandboxBackendError, match="linux proxy bridge"):
        build_bwrap_argv(_request(policy, tmp_path), binary="bwrap")


def test_seatbelt_proxy_allowlist_with_proxy_remains_unsupported(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path, network_proxy=_proxy_spec())

    with pytest.raises(SandboxBackendError, match="not supported"):
        render_seatbelt_profile(_request(policy, tmp_path))


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
