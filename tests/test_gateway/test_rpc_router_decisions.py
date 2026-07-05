"""router.decisions.list / router.feedback.submit RPC handlers.

The list surface is a read/observe view over the V017 ``router_decisions``
table; the feedback surface is dormant plumbing (deferred F7 follow-up).
All fixture data is synthetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.engine.steps.router_decision_record import (
    get_decision_writer,
    set_decision_writer,
)
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.protocol import ERROR_INVALID_REQUEST, ERROR_UNAUTHORIZED
from opensquilla.gateway.rpc import get_dispatcher, validate_classification
from opensquilla.gateway.rpc.registry import RpcContext
from opensquilla.gateway.rpc_router import (
    _bounded_limit,
    _handle_router_decisions_list,
    _handle_router_feedback_submit,
)
from opensquilla.gateway.scopes import ADMIN_SCOPE, METHOD_SCOPES, READ_SCOPE
from opensquilla.persistence.migrator import apply_pending
from opensquilla.persistence.router_decision_writer import (
    RouterDecisionWriter,
    open_router_decision_writer,
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1].parent / "migrations"

EXPECTED_WIRE_KEYS = {
    "decisionId",
    "sessionKey",
    "turnIndex",
    "tsMs",
    "classifier",
    "proposedTier",
    "confidence",
    "probs",
    "flags",
    "finalTier",
    "provider",
    "model",
    "thinkingLevel",
    "source",
    "trail",
    "baselineModel",
    "savingsPct",
    "executedKind",
    "ensembleProfile",
    "fallbackHops",
}


def _base_record(**overrides) -> dict:
    record = {
        "decision_id": "d" * 32,
        "session_key": "agent:main:webchat:s1",
        "turn_index": 0,
        "ts_ms": 1_000_000,
        "classifier": "v4_phase3",
        "proposed_tier": "c1",
        "confidence": 0.91,
        "probs": [0.05, 0.91, 0.03, 0.01],
        "flags": ["code", "multi_step"],
        "final_tier": "c2",
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat",
        "thinking_level": "medium",
        "source": "v4_phase3",
        "trail": [
            {"stage": "classify", "tier": "c1", "route_class": "R1"},
            {"stage": "final", "tier": "c2", "route_class": "R2"},
        ],
        "baseline_model": "anthropic/claude-sonnet",
        "savings_pct": 42.5,
        "executed_kind": "single",
        "ensemble_profile": None,
        "fallback_hops": 0,
    }
    record.update(overrides)
    return record


@pytest.fixture
def writer(tmp_path: Path):
    """Real migrated DB + registered process-wide writer, torn down after."""
    db = str(tmp_path / "sessions.sqlite")
    apply_pending(db, MIGRATIONS_DIR)
    w = open_router_decision_writer(db)
    previous = get_decision_writer()
    set_decision_writer(w)
    try:
        yield w
    finally:
        set_decision_writer(previous)
        w.close()


def _read_only_principal() -> Principal:
    return Principal(
        role="operator",
        scopes=frozenset({READ_SCOPE}),
        is_owner=False,
        authenticated=True,
    )


# ---------------------------------------------------------------------------
# router.decisions.list
# ---------------------------------------------------------------------------


async def test_decisions_list_empty_without_writer() -> None:
    previous = get_decision_writer()
    set_decision_writer(None)
    try:
        payload = await _handle_router_decisions_list({}, RpcContext(conn_id="test"))
    finally:
        set_decision_writer(previous)
    assert payload == {"decisions": []}


async def test_decisions_list_returns_camelcase_envelope(
    writer: RouterDecisionWriter,
) -> None:
    assert writer.record_decision(_base_record()) is True
    payload = await _handle_router_decisions_list({}, RpcContext(conn_id="test"))

    assert set(payload) == {"decisions"}
    (decision,) = payload["decisions"]
    assert set(decision) == EXPECTED_WIRE_KEYS
    assert decision["decisionId"] == "d" * 32
    assert decision["sessionKey"] == "agent:main:webchat:s1"
    assert decision["turnIndex"] == 0
    assert decision["tsMs"] == 1_000_000
    assert decision["classifier"] == "v4_phase3"
    assert decision["proposedTier"] == "c1"
    assert decision["confidence"] == 0.91
    assert decision["finalTier"] == "c2"
    assert decision["provider"] == "openrouter"
    assert decision["model"] == "deepseek/deepseek-chat"
    assert decision["thinkingLevel"] == "medium"
    assert decision["source"] == "v4_phase3"
    assert decision["baselineModel"] == "anthropic/claude-sonnet"
    assert decision["executedKind"] == "single"
    assert decision["ensembleProfile"] is None
    assert decision["fallbackHops"] == 0
    # JSON columns come back as structured JSON, not serialized strings.
    assert decision["probs"] == [0.05, 0.91, 0.03, 0.01]
    assert decision["flags"] == ["code", "multi_step"]
    assert decision["trail"][0] == {"stage": "classify", "tier": "c1", "route_class": "R1"}


async def test_decisions_list_savings_pct_verbatim_passthrough(
    writer: RouterDecisionWriter,
) -> None:
    """C2: savingsPct surfaces the stored column value untouched."""
    writer.record_decision(_base_record(decision_id="s1", savings_pct=42.5))
    writer.record_decision(
        _base_record(decision_id="s2", ts_ms=1_000_001, savings_pct=None)
    )
    payload = await _handle_router_decisions_list({}, RpcContext(conn_id="test"))
    by_id = {d["decisionId"]: d for d in payload["decisions"]}
    assert by_id["s1"]["savingsPct"] == 42.5
    assert by_id["s2"]["savingsPct"] is None


async def test_decisions_list_orders_newest_first_and_pages_with_before_ts(
    writer: RouterDecisionWriter,
) -> None:
    for index in range(3):
        writer.record_decision(
            _base_record(decision_id=f"p{index}", ts_ms=1_000 * (index + 1))
        )
    ctx = RpcContext(conn_id="test")

    payload = await _handle_router_decisions_list({}, ctx)
    assert [d["tsMs"] for d in payload["decisions"]] == [3_000, 2_000, 1_000]

    oldest_seen = payload["decisions"][0]["tsMs"]  # page after the newest row
    page = await _handle_router_decisions_list({"beforeTs": oldest_seen}, ctx)
    assert [d["tsMs"] for d in page["decisions"]] == [2_000, 1_000]


async def test_decisions_list_filters_by_session_key(
    writer: RouterDecisionWriter,
) -> None:
    writer.record_decision(_base_record(decision_id="a1", session_key="agent:a"))
    writer.record_decision(_base_record(decision_id="b1", session_key="agent:b"))
    payload = await _handle_router_decisions_list(
        {"sessionKey": "agent:a"}, RpcContext(conn_id="test")
    )
    assert [d["decisionId"] for d in payload["decisions"]] == ["a1"]
    assert all(d["sessionKey"] == "agent:a" for d in payload["decisions"])


async def test_decisions_list_respects_limit(writer: RouterDecisionWriter) -> None:
    for index in range(3):
        writer.record_decision(
            _base_record(decision_id=f"l{index}", ts_ms=1_000 * (index + 1))
        )
    payload = await _handle_router_decisions_list(
        {"limit": 1}, RpcContext(conn_id="test")
    )
    assert [d["decisionId"] for d in payload["decisions"]] == ["l2"]


def test_decisions_list_limit_is_clamped() -> None:
    assert _bounded_limit(None) == 50
    assert _bounded_limit(-1) == 50
    assert _bounded_limit("oops") == 50
    assert _bounded_limit("5000") == 200
    assert _bounded_limit(5000) == 200
    assert _bounded_limit("12") == 12


async def test_decisions_list_allows_read_only_dispatch(
    writer: RouterDecisionWriter,
) -> None:
    writer.record_decision(_base_record())
    ctx = RpcContext(conn_id="test", principal=_read_only_principal())
    res = await get_dispatcher().dispatch("r1", "router.decisions.list", {}, ctx)
    assert res.error is None, res.error
    assert len(res.payload["decisions"]) == 1


# ---------------------------------------------------------------------------
# router.feedback.submit (dormant)
# ---------------------------------------------------------------------------


async def test_feedback_submit_accepts_and_stays_dormant(
    writer: RouterDecisionWriter,
) -> None:
    writer.record_decision(_base_record())
    before = writer.list_decisions()
    payload = await _handle_router_feedback_submit(
        {"decisionId": "d" * 32, "rating": "down"},
        RpcContext(conn_id="test"),
    )
    assert payload == {"accepted": True}
    # Dormant: the decision table is untouched — nothing is persisted or
    # consumed; the handler only validates and logs.
    assert writer.list_decisions() == before


async def test_feedback_submit_rejects_free_text_decision_id() -> None:
    ctx = RpcContext(conn_id="test")
    res = await get_dispatcher().dispatch(
        "r1",
        "router.feedback.submit",
        {"decisionId": "this routing was wrong today", "rating": "down"},
        ctx,
    )
    assert res.error is not None
    assert res.error.code == ERROR_INVALID_REQUEST


async def test_feedback_submit_rejects_free_text_rating() -> None:
    ctx = RpcContext(conn_id="test")
    res = await get_dispatcher().dispatch(
        "r1",
        "router.feedback.submit",
        {"decisionId": "d" * 32, "rating": "amazing model, keep it!"},
        ctx,
    )
    assert res.error is not None
    assert res.error.code == ERROR_INVALID_REQUEST


async def test_feedback_submit_denies_read_only_dispatch() -> None:
    ctx = RpcContext(conn_id="test", principal=_read_only_principal())
    res = await get_dispatcher().dispatch(
        "r1",
        "router.feedback.submit",
        {"decisionId": "d" * 32, "rating": "up"},
        ctx,
    )
    assert res.error is not None
    assert res.error.code == ERROR_UNAUTHORIZED


def test_feedback_handler_is_dormant_static() -> None:
    """The handler module must not touch routing, calibration, or selection."""
    source = Path("src/opensquilla/gateway/rpc_router.py").read_text()
    assert "Dormant until F7" in source
    assert "RoutingHistoryStore" not in source
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    forbidden = ("smart_routing", "router_control", "squilla_router", "calibration", "routing")
    for line in import_lines:
        assert not any(token in line for token in forbidden), line


# ---------------------------------------------------------------------------
# Scope classification / boot audit
# ---------------------------------------------------------------------------


def test_router_rpc_scope_contract() -> None:
    assert METHOD_SCOPES["router.decisions.list"] == READ_SCOPE
    assert METHOD_SCOPES["router.feedback.submit"] == ADMIN_SCOPE


def test_router_rpc_methods_pass_boot_scope_audit() -> None:
    registry = get_dispatcher()
    assert "router.decisions.list" in registry.methods()
    assert "router.feedback.submit" in registry.methods()
    # Same audit boot runs at the end of opensquilla.gateway.rpc.__init__;
    # raises ScopeDriftError on declared-vs-table drift.
    validate_classification(registry)
