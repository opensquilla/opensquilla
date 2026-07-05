"""Router decision-record RPC handlers.

Read/observe surface over the ``router_decisions`` table (V017), which the
engine populates best-effort via
``opensquilla.engine.steps.router_decision_record``. The handlers resolve the
process-wide writer through that hook module's ``get_decision_writer()``
(mirroring how the shared model catalog is consumed) rather than reaching
into boot internals; when no writer is registered (``:memory:`` session DB,
CLI/standalone paths) the list surface degrades to an empty envelope instead
of erroring.

Privacy: the table stores enum tokens and numbers only — no prompt text
(V017 contract, test-enforced) — so every value surfaced here is already
operator-safe and, unlike ``meta.runs.list``, read-only principals need no
per-session gating. These handlers observe routing; they never change it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog

from opensquilla.engine.steps.router_decision_record import get_decision_writer
from opensquilla.gateway.protocol import ERROR_INVALID_REQUEST
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, get_dispatcher
from opensquilla.persistence.router_decision_writer import sanitize_token

log = structlog.get_logger(__name__)

_d = get_dispatcher()

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

_FEEDBACK_RATINGS = frozenset({"up", "down", "neutral"})

# snake_case DB column -> camelCase wire key, in canonical V017 column order.
_WIRE_KEYS: tuple[tuple[str, str], ...] = (
    ("decision_id", "decisionId"),
    ("session_key", "sessionKey"),
    ("turn_index", "turnIndex"),
    ("ts_ms", "tsMs"),
    ("classifier", "classifier"),
    ("proposed_tier", "proposedTier"),
    ("confidence", "confidence"),
    ("probs", "probs"),
    ("flags", "flags"),
    ("final_tier", "finalTier"),
    ("provider", "provider"),
    ("model", "model"),
    ("thinking_level", "thinkingLevel"),
    ("source", "source"),
    ("trail", "trail"),
    ("baseline_model", "baselineModel"),
    # C2: stored display value passes through verbatim — never recomputed.
    ("savings_pct", "savingsPct"),
    ("executed_kind", "executedKind"),
    ("ensemble_profile", "ensembleProfile"),
    ("fallback_hops", "fallbackHops"),
)


def _bounded_limit(value: Any, *, default: int = _DEFAULT_LIMIT, maximum: int = _MAX_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 1:
        return default
    return min(parsed, maximum)


def _optional_int_param(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _wire_decision(record: Mapping[str, Any]) -> dict[str, Any]:
    return {wire: record.get(column) for column, wire in _WIRE_KEYS}


@_d.method("router.decisions.list", scope="operator.read")
async def _handle_router_decisions_list(params: Any, ctx: RpcContext) -> dict[str, Any]:
    """List persisted router decision records, newest first.

    Params (all optional): ``sessionKey`` filters to one session; ``limit``
    (default 50, clamped to 200) bounds the page; ``beforeTs`` (epoch ms,
    exclusive) pages backwards — pass the oldest ``tsMs`` of the previous
    page. With no writer registered the envelope is ``{"decisions": []}``;
    this is a pure local DB read (no network, no routing side effects).
    """
    writer = get_decision_writer()
    if writer is None:
        return {"decisions": []}
    p = params if isinstance(params, dict) else {}
    session_key = p.get("sessionKey") or p.get("session_key")
    rows = writer.list_decisions(
        session_key=str(session_key) if session_key else None,
        limit=_bounded_limit(p.get("limit")),
        before_ts_ms=_optional_int_param(p.get("beforeTs") or p.get("before_ts_ms")),
    )
    return {"decisions": [_wire_decision(row) for row in rows]}


@_d.method("router.feedback.submit", scope="operator.admin")
async def _handle_router_feedback_submit(params: Any, ctx: RpcContext) -> dict[str, Any]:
    """Accept operator feedback about one routing decision.

    Dormant until F7; recorded for later, never read by the router. The
    handler validates ``decisionId`` as an enum-like id token (free text is
    rejected) and ``rating`` against a closed enum, emits one redacted
    structlog event, and returns. Nothing consumes the event: it has zero
    effect on routing, calibration, tier selection, or the
    ``router_decisions`` table.
    """
    p = params if isinstance(params, dict) else {}
    decision_id = sanitize_token(p.get("decisionId") or p.get("decision_id"))
    if decision_id is None:
        raise RpcHandlerError(
            ERROR_INVALID_REQUEST,
            "decisionId must be an id token",
        )
    rating = p.get("rating")
    if not isinstance(rating, str) or rating not in _FEEDBACK_RATINGS:
        raise RpcHandlerError(
            ERROR_INVALID_REQUEST,
            "rating must be one of: up, down, neutral",
        )
    log.info(
        "router_feedback.submitted",
        decision_id=decision_id,
        rating=rating,
    )
    return {"accepted": True}
