from __future__ import annotations

from opensquilla.gateway.auth import Principal
from opensquilla.gateway.routing import build_cli_route_envelope, tool_context_from_envelope
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_sessions import _trusted_run_mode_hint
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
