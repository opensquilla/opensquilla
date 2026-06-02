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
        bundles=(PackageBundleGrant(bundle_id="python-package-install"),),
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
    assert ctx.run_mode == "standard"
    assert isinstance(ctx.sandbox_run_context, RunContext)
    assert [grant.domain for grant in ctx.sandbox_run_context.domains] == ["pypi.org"]
    assert [grant.bundle_id for grant in ctx.sandbox_run_context.bundles] == [
        "python-package-install"
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
