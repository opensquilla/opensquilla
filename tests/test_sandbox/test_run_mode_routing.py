from __future__ import annotations

from opensquilla.gateway.auth import Principal
from opensquilla.gateway.routing import build_cli_route_envelope, tool_context_from_envelope
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_sessions import (
    _apply_run_context_route_metadata,
    _trusted_run_mode_hint,
)
from opensquilla.sandbox.run_context import (
    DomainGrant,
    MountGrant,
    PackageBundleGrant,
    RunContext,
)
from opensquilla.sandbox.run_mode import RunMode


def _owner_rpc_context(*, is_owner: bool = True) -> RpcContext:
    return RpcContext(
        conn_id="c",
        principal=Principal(
            role="operator",
            scopes=frozenset(["operator.write", "operator.read"]),
            is_owner=is_owner,
            authenticated=True,
        ),
    )


def test_saved_route_run_mode_wins_over_later_global_full_default() -> None:
    envelope = build_cli_route_envelope(
        session_key="agent:main:cli",
        run_mode="standard",
    )

    ctx = tool_context_from_envelope(
        envelope,
        is_owner=True,
        default_elevated="full",
    )

    assert ctx.run_mode == "standard"
    assert ctx.elevated is None


def test_route_metadata_hydrates_full_sandbox_run_context() -> None:
    envelope = build_cli_route_envelope(
        session_key="agent:main:cli",
        run_mode="standard",
    )
    run_context = RunContext(
        run_mode=RunMode.STANDARD,
        domains=(DomainGrant(domain="pypi.org"),),
        bundles=(
            PackageBundleGrant(bundle_id="python-package-install", scope="chat"),
            PackageBundleGrant(bundle_id="node-package-install", source="disabled"),
        ),
    )

    _apply_run_context_route_metadata(
        envelope,
        run_context,
        principal_is_owner=True,
    )
    ctx = tool_context_from_envelope(envelope, is_owner=True)

    assert envelope.metadata["run_mode"] == "standard"
    assert envelope.metadata["sandbox_mounts"] == []
    assert envelope.metadata["sandbox_run_context"]["domains"] == [
        {"domain": "pypi.org", "scope": "chat", "source": "manual"}
    ]
    assert envelope.metadata["sandbox_run_context"]["bundles"] == [
        {
            "bundle_id": "python-package-install",
            "scope": "chat",
            "source": "manual",
        },
        {
            "bundle_id": "node-package-install",
            "scope": "workspace",
            "source": "disabled",
        },
    ]
    assert ctx.run_mode == "standard"
    assert isinstance(ctx.sandbox_run_context, RunContext)
    assert [grant.domain for grant in ctx.sandbox_run_context.domains] == ["pypi.org"]
    assert [
        (grant.bundle_id, grant.scope, grant.source)
        for grant in ctx.sandbox_run_context.bundles
    ] == [
        ("python-package-install", "chat", "manual"),
        ("node-package-install", "workspace", "disabled"),
    ]


def test_route_metadata_filters_stale_workspace_mounts_from_legacy_mounts(
    tmp_path,
) -> None:
    from opensquilla.sandbox.integration import _session_mounts_for_policy
    from opensquilla.tools.types import current_tool_context

    workspace = tmp_path / "workspace"
    chat_mount = tmp_path / "chat-mount"
    stale_mount = tmp_path / "stale-mount"
    for path in (workspace, chat_mount, stale_mount):
        path.mkdir()
    envelope = build_cli_route_envelope(
        session_key="agent:main:cli",
        run_mode="standard",
    )
    run_context = RunContext(
        run_mode=RunMode.STANDARD,
        workspace=str(workspace),
        mounts=(
            MountGrant(path=str(chat_mount), access="ro", scope="chat"),
            MountGrant(path=str(stale_mount), access="rw", scope="workspace"),
        ),
    )

    _apply_run_context_route_metadata(
        envelope,
        run_context,
        principal_is_owner=True,
    )
    ctx = tool_context_from_envelope(envelope, is_owner=True)

    assert envelope.metadata["sandbox_run_context"]["mounts"] == [
        {"path": str(chat_mount), "access": "ro", "scope": "chat"},
        {"path": str(stale_mount), "access": "rw", "scope": "workspace"},
    ]
    assert envelope.metadata["sandbox_mounts"] == [
        {"path": str(chat_mount), "access": "ro", "scope": "chat"}
    ]
    assert isinstance(ctx.sandbox_run_context, RunContext)
    assert [(grant.path, grant.scope) for grant in ctx.sandbox_run_context.mounts] == [
        (str(chat_mount), "chat")
    ]
    assert ctx.sandbox_mounts == [
        {"path": str(chat_mount), "access": "ro", "scope": "chat"}
    ]

    token = current_tool_context.set(ctx)
    try:
        policy_mounts = _session_mounts_for_policy(workspace)
    finally:
        current_tool_context.reset(token)

    assert [(str(mount.host_path), mount.mode) for mount in policy_mounts] == [
        (str(chat_mount), "ro")
    ]

    legacy_envelope = build_cli_route_envelope(
        session_key="agent:main:cli",
        run_mode="standard",
    )
    legacy_payload = run_context.to_origin_payload()
    legacy_envelope.metadata["sandbox_run_context"] = legacy_payload
    legacy_envelope.metadata["sandbox_mounts"] = legacy_payload["mounts"]

    legacy_ctx = tool_context_from_envelope(legacy_envelope, is_owner=True)

    assert legacy_ctx.sandbox_mounts == [
        {"path": str(chat_mount), "access": "ro", "scope": "chat"}
    ]


def test_invalid_route_run_context_metadata_is_ignored() -> None:
    envelope = build_cli_route_envelope(
        session_key="agent:main:cli",
        run_mode="standard",
    )
    envelope.metadata["sandbox_run_context"] = {"run_mode": "unknown", "domains": "pypi.org"}

    ctx = tool_context_from_envelope(envelope, is_owner=True)

    assert ctx.sandbox_run_context is None


def test_legacy_owner_elevated_aliases_map_to_trusted_run_mode() -> None:
    ctx = _owner_rpc_context(is_owner=True)

    assert _trusted_run_mode_hint(ctx, {"elevated": "on"}) == RunMode.TRUSTED
    assert _trusted_run_mode_hint(ctx, {"elevated": "bypass"}) == RunMode.TRUSTED


def test_legacy_owner_full_elevated_alias_maps_to_full_run_mode() -> None:
    ctx = _owner_rpc_context(is_owner=True)

    assert _trusted_run_mode_hint(ctx, {"elevated": "full"}) == RunMode.FULL


def test_legacy_elevated_aliases_are_ignored_for_non_owner() -> None:
    ctx = _owner_rpc_context(is_owner=False)

    assert _trusted_run_mode_hint(ctx, {"elevated": "bypass"}) is None
    assert _trusted_run_mode_hint(ctx, {"elevated": "full"}) is None
