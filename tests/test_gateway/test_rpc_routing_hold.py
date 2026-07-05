"""Tests for the operator routing-hold RPC surface (``routing.hold.*``).

Covers the wire contract of ``routing.hold.set`` / ``routing.hold.get`` /
``routing.hold.clear``: target validation (tier/auto only, legacy alias
normalization), the non-consuming ``get`` peek, TTL/turn-cap reflection,
scope enforcement, and that the RPC layer operates on the exact hold store
instance the router step consults on the shared ``TurnRunner``.

Authorization note: sessions in this gateway are not per-caller
owner-scoped — ``sessions.patch`` / ``sessions.reset`` authorize purely by
operator scope and accept any existing session key. The routing-hold RPCs
follow that model, so the enforced boundary tested here is scope-based
(admin for mutation, read for the peek), not a per-session ownership ACL.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from opensquilla.gateway.auth import Principal
from opensquilla.gateway.config import GatewayConfig, SquillaRouterConfig
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.gateway.scopes import ADMIN_SCOPE, METHOD_SCOPES, READ_SCOPE
from opensquilla.router_control import (
    DEFAULT_HOLD_TTL_SECONDS,
    DEFAULT_HOLD_TURNS,
    RouterControlHoldStore,
)

SESSION_KEY = "agent:main:webchat:default"

_READ_PRINCIPAL = Principal(
    role="operator",
    scopes=frozenset({READ_SCOPE}),
    is_owner=False,
    authenticated=True,
)


class _FakeStorage:
    def __init__(self, keys: tuple[str, ...]) -> None:
        self._sessions = {key: SimpleNamespace(session_key=key) for key in keys}

    async def get_session(self, key: str) -> Any:
        return self._sessions.get(key)


def _make_ctx(
    *,
    store: RouterControlHoldStore | None = None,
    principal: Principal | None = None,
    config: GatewayConfig | None = None,
    turn_runner: Any | None = None,
    session_keys: tuple[str, ...] = (SESSION_KEY,),
) -> RpcContext:
    if turn_runner is None:
        turn_runner = SimpleNamespace(
            router_control_hold_store=store if store is not None else RouterControlHoldStore()
        )
    kwargs: dict[str, Any] = {}
    if principal is not None:
        kwargs["principal"] = principal
    return RpcContext(
        conn_id="test",
        config=config if config is not None else GatewayConfig(),
        session_manager=SimpleNamespace(storage=_FakeStorage(session_keys)),
        turn_runner=turn_runner,
        **kwargs,
    )


async def _dispatch(method: str, params: dict | None, ctx: RpcContext) -> Any:
    return await get_dispatcher().dispatch("req-1", method, params, ctx)


def test_routing_hold_methods_are_scope_classified() -> None:
    # Explicit METHOD_SCOPES entries are mandatory: the boot audit
    # (validate_classification) hard-fails on declared-vs-table drift.
    assert METHOD_SCOPES["routing.hold.set"] == ADMIN_SCOPE
    assert METHOD_SCOPES["routing.hold.clear"] == ADMIN_SCOPE
    assert METHOD_SCOPES["routing.hold.get"] == READ_SCOPE


async def test_set_then_get_roundtrip() -> None:
    ctx = _make_ctx()

    set_res = await _dispatch(
        "routing.hold.set", {"sessionKey": SESSION_KEY, "target": "c2"}, ctx
    )
    assert set_res.ok is True
    hold = set_res.payload["hold"]
    assert set_res.payload["sessionKey"] == SESSION_KEY
    assert hold["targetId"] == "tier:c2"
    assert hold["tier"] == "c2"
    assert hold["model"]
    assert hold["turnsRemaining"] == DEFAULT_HOLD_TURNS
    assert hold["ttlSeconds"] == DEFAULT_HOLD_TTL_SECONDS
    assert hold["source"] == "routing_hold_rpc"

    get_res = await _dispatch("routing.hold.get", {"sessionKey": SESSION_KEY}, ctx)
    assert get_res.ok is True
    fetched = get_res.payload["hold"]
    assert fetched is not None
    assert fetched["targetId"] == "tier:c2"
    assert fetched["tier"] == "c2"
    assert fetched["model"] == hold["model"]
    assert 0.0 < fetched["ttlRemainingSeconds"] <= DEFAULT_HOLD_TTL_SECONDS
    # The valid target menu rides along so a UI/CLI can render options.
    target_ids = [t["targetId"] for t in get_res.payload["targets"]]
    assert target_ids == ["tier:c0", "tier:c1", "tier:c2", "tier:c3"]
    assert get_res.payload["autoTargetId"] == "auto"
    assert get_res.payload["routerEnabled"] is True


async def test_get_without_hold_returns_null_hold() -> None:
    ctx = _make_ctx()
    res = await _dispatch("routing.hold.get", {"sessionKey": SESSION_KEY}, ctx)
    assert res.ok is True
    assert res.payload["hold"] is None
    assert len(res.payload["targets"]) == 4


async def test_set_normalizes_legacy_tier_aliases() -> None:
    ctx = _make_ctx()
    for raw, canonical in (
        ("t2", "c2"),
        ("tier:t3", "c3"),
        (" C1 ", "c1"),
        ("TIER:C0", "c0"),
    ):
        res = await _dispatch(
            "routing.hold.set", {"sessionKey": SESSION_KEY, "target": raw}, ctx
        )
        assert res.ok is True, raw
        assert res.payload["hold"]["tier"] == canonical
        assert res.payload["hold"]["targetId"] == f"tier:{canonical}"


async def test_set_rejects_mode_targets_and_garbage() -> None:
    ctx = _make_ctx()
    for raw in ("mode:precision", "mode:auto", "c9", "tier:c9", "garbage", "", None):
        res = await _dispatch(
            "routing.hold.set", {"sessionKey": SESSION_KEY, "target": raw}, ctx
        )
        assert res.ok is False, raw
        assert res.error is not None
        assert res.error.code == "INVALID_REQUEST"
    # Nothing was stored by any rejected attempt.
    get_res = await _dispatch("routing.hold.get", {"sessionKey": SESSION_KEY}, ctx)
    assert get_res.payload["hold"] is None


async def test_set_auto_restores_automatic_routing() -> None:
    store = RouterControlHoldStore()
    ctx = _make_ctx(store=store)

    await _dispatch("routing.hold.set", {"sessionKey": SESSION_KEY, "target": "c1"}, ctx)
    res = await _dispatch(
        "routing.hold.set", {"sessionKey": SESSION_KEY, "target": "auto"}, ctx
    )
    assert res.ok is True
    assert res.payload["hold"] is None
    assert store.get_valid(SESSION_KEY) is None


async def test_get_does_not_consume_a_hold_turn() -> None:
    store = RouterControlHoldStore()
    ctx = _make_ctx(store=store)

    set_res = await _dispatch(
        "routing.hold.set", {"sessionKey": SESSION_KEY, "target": "c3", "turns": 2}, ctx
    )
    assert set_res.payload["hold"]["turnsRemaining"] == 2

    for _ in range(3):
        get_res = await _dispatch("routing.hold.get", {"sessionKey": SESSION_KEY}, ctx)
        assert get_res.payload["hold"]["turnsRemaining"] == 2

    # Only the router step's consuming read (decrement=True) spends a turn.
    consumed = store.get_valid(SESSION_KEY, decrement=True)
    assert consumed is not None and consumed.turns_remaining == 1

    get_res = await _dispatch("routing.hold.get", {"sessionKey": SESSION_KEY}, ctx)
    assert get_res.payload["hold"]["turnsRemaining"] == 1


async def test_turns_and_ttl_params_are_reflected() -> None:
    ctx = _make_ctx()
    res = await _dispatch(
        "routing.hold.set",
        {"sessionKey": SESSION_KEY, "target": "c0", "turns": 3, "ttlSeconds": 120},
        ctx,
    )
    assert res.ok is True
    hold = res.payload["hold"]
    assert hold["turnsRemaining"] == 3
    assert hold["ttlSeconds"] == 120.0
    assert 0.0 < hold["ttlRemainingSeconds"] <= 120.0


async def test_set_rejects_invalid_turns_and_ttl() -> None:
    ctx = _make_ctx()
    bad_params: list[dict[str, Any]] = [
        {"turns": -1},
        {"turns": "2"},
        {"turns": True},
        {"ttlSeconds": 0},
        {"ttlSeconds": -5},
        {"ttlSeconds": "soon"},
        {"ttlSeconds": float("inf")},
    ]
    for extra in bad_params:
        res = await _dispatch(
            "routing.hold.set",
            {"sessionKey": SESSION_KEY, "target": "c1", **extra},
            ctx,
        )
        assert res.ok is False, extra
        assert res.error is not None
        assert res.error.code == "INVALID_REQUEST"


async def test_clear_reports_whether_a_hold_existed() -> None:
    ctx = _make_ctx()
    await _dispatch("routing.hold.set", {"sessionKey": SESSION_KEY, "target": "c2"}, ctx)

    first = await _dispatch("routing.hold.clear", {"sessionKey": SESSION_KEY}, ctx)
    assert first.ok is True
    assert first.payload == {"sessionKey": SESSION_KEY, "cleared": True}

    second = await _dispatch("routing.hold.clear", {"sessionKey": SESSION_KEY}, ctx)
    assert second.ok is True
    assert second.payload == {"sessionKey": SESSION_KEY, "cleared": False}


async def test_unknown_session_is_not_found() -> None:
    ctx = _make_ctx()
    for method, params in (
        ("routing.hold.set", {"sessionKey": "agent:main:nope", "target": "c2"}),
        ("routing.hold.get", {"sessionKey": "agent:main:nope"}),
        ("routing.hold.clear", {"sessionKey": "agent:main:nope"}),
    ):
        res = await _dispatch(method, params, ctx)
        assert res.ok is False, method
        assert res.error is not None
        assert res.error.code == "NOT_FOUND"


async def test_missing_session_key_is_invalid() -> None:
    ctx = _make_ctx()
    res = await _dispatch("routing.hold.set", {"target": "c2"}, ctx)
    assert res.ok is False
    assert res.error is not None
    assert res.error.code == "INVALID_REQUEST"


async def test_read_scope_can_peek_but_not_mutate() -> None:
    # Sessions carry no per-caller ownership ACL (see module docstring), so
    # the authorization boundary for the mutating methods is admin scope —
    # exactly like sessions.patch, the nearest session-mutating precedent.
    store = RouterControlHoldStore()
    admin_ctx = _make_ctx(store=store)
    read_ctx = _make_ctx(store=store, principal=_READ_PRINCIPAL)

    await _dispatch(
        "routing.hold.set", {"sessionKey": SESSION_KEY, "target": "c2"}, admin_ctx
    )

    get_res = await _dispatch("routing.hold.get", {"sessionKey": SESSION_KEY}, read_ctx)
    assert get_res.ok is True
    assert get_res.payload["hold"]["tier"] == "c2"

    set_res = await _dispatch(
        "routing.hold.set", {"sessionKey": SESSION_KEY, "target": "c0"}, read_ctx
    )
    clear_res = await _dispatch("routing.hold.clear", {"sessionKey": SESSION_KEY}, read_ctx)
    assert set_res.ok is False and set_res.error.code == "UNAUTHORIZED"
    assert clear_res.ok is False and clear_res.error.code == "UNAUTHORIZED"

    # The denied calls left the admin-set hold untouched.
    hold = store.get_valid(SESSION_KEY)
    assert hold is not None and hold.tier == "c2"


async def test_set_rejects_when_router_disabled() -> None:
    config = GatewayConfig(squilla_router=SquillaRouterConfig(enabled=False))
    ctx = _make_ctx(config=config)
    res = await _dispatch(
        "routing.hold.set", {"sessionKey": SESSION_KEY, "target": "c2"}, ctx
    )
    assert res.ok is False
    assert res.error is not None
    assert res.error.code == "INVALID_REQUEST"

    # Clearing stays available so an operator can drop stale holds after
    # disabling the router.
    clear_res = await _dispatch("routing.hold.clear", {"sessionKey": SESSION_KEY}, ctx)
    assert clear_res.ok is True


async def test_missing_hold_store_is_unavailable() -> None:
    ctx = _make_ctx(turn_runner=SimpleNamespace())
    res = await _dispatch("routing.hold.get", {"sessionKey": SESSION_KEY}, ctx)
    assert res.ok is False
    assert res.error is not None
    assert res.error.code == "UNAVAILABLE"


async def test_rpc_operates_on_the_turn_runner_store() -> None:
    # The RPC must mutate the exact store instance the router step consults:
    # TurnRunner forwards self._router_control_hold_store into turn metadata
    # (engine/runtime.py), and the public property exposes that same object.
    from opensquilla.engine.runtime import TurnRunner

    runner = TurnRunner(provider_selector=None)
    assert runner.router_control_hold_store is runner._router_control_hold_store

    ctx = _make_ctx(turn_runner=runner)
    res = await _dispatch(
        "routing.hold.set", {"sessionKey": SESSION_KEY, "target": "t1"}, ctx
    )
    assert res.ok is True

    hold = runner._router_control_hold_store.get_valid(SESSION_KEY)
    assert hold is not None
    assert hold.tier == "c1"
    assert hold.source == "routing_hold_rpc"
