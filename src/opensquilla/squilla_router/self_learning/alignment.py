"""Offline label alignment for the router self-learning loop.

Turns a session's captured runtime signals (the model's raw prediction plus the
heuristic markers — complaint, confidence gate, anti-downgrade) into a corrected
supervised label per turn.

Pure functions over :class:`RouterTrainSample`; no IO, no raw text (alignment
relies only on the captured boolean/class signals), so it is fully unit-testable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from opensquilla.squilla_router.self_learning.schema import RouterTrainSample, decode_features

ROUTE_CLASSES = ("R0", "R1", "R2", "R3")
# A single retrospective correction may bump at most this many tiers, so one
# complaint never teaches a c0 input to jump straight to c3.
MAX_RETRO_STEP = 2
# Only inputs the model routed at or below this index are eligible for
# retrospective up-routing; higher served tiers make "under-routed" implausible
# and the complaint is more likely about correctness/style than capability.
RETRO_ELIGIBLE_MAX_IDX = 1  # R1

REASON_NORMAL = "normal"
REASON_CONFIDENCE_BACKOFF = "confidence_backoff"
REASON_IMMEDIATE_COMPLAINT = "immediate_complaint"
REASON_RETROSPECTIVE = "retrospective_under_routing"


def route_index(route_class: str) -> int:
    """Map ``R0``..``R3`` to ``0``..``3`` (unknown -> R1, the safe default)."""

    try:
        return ROUTE_CLASSES.index(route_class)
    except ValueError:
        return 1


def class_at(idx: int) -> str:
    return ROUTE_CLASSES[max(0, min(len(ROUTE_CLASSES) - 1, idx))]


def _day(ts: str) -> str:
    return ts[:10] if ts else ""


def _feature_hash(b64: str) -> str:
    return hashlib.sha256(b64.encode("ascii")).hexdigest()[:16]


@dataclass
class AlignedSample:
    """One turn with its corrected training target and provenance."""

    features_390: np.ndarray  # float32, decoded
    target_idx: int  # 0..3 (corrected label)
    served_idx: int  # 0..3 (what actually ran; cost-gate reference)
    reason: str
    session_key: str
    turn_index: int
    day: str
    feature_hash: str
    confirmed: bool = True  # retrospective: did T+2 confirm resolution?


def align_session(samples: list[RouterTrainSample]) -> list[AlignedSample]:
    """Align one session's samples into corrected training targets.

    Per turn ``i`` the label is decided in increasing priority:
    normal -> confidence_backoff -> immediate_complaint, then a retrospective
    override when the *next* turn complains and turn ``i`` was under-routed.
    """

    ordered = sorted(samples, key=lambda s: (s.turn_index, s.ts))
    n = len(ordered)
    out: list[AlignedSample] = []

    for i, s in enumerate(ordered):
        target_idx = route_index(s.final_route_class)
        reason = REASON_NORMAL
        confirmed = True

        if s.confidence_gate_applied:
            # The gate forced the served (default) tier on a low-confidence call;
            # teach the classifier that this ambiguous input resolves there.
            reason = REASON_CONFIDENCE_BACKOFF

        if s.complaint_detected:
            # The user's complaint drove an upgrade this turn; the upgraded tier
            # is the truest label for this (complaint) input.
            reason = REASON_IMMEDIATE_COMPLAINT
        else:
            retro = _retrospective_target(ordered, i, n)
            if retro is not None:
                target_idx, confirmed = retro
                reason = REASON_RETROSPECTIVE

        out.append(
            AlignedSample(
                features_390=decode_features(s.features_390_b64, 390),
                target_idx=target_idx,
                served_idx=route_index(s.final_route_class),
                reason=reason,
                session_key=s.session_key,
                turn_index=s.turn_index,
                day=_day(s.ts),
                feature_hash=_feature_hash(s.features_390_b64),
                confirmed=confirmed,
            )
        )

    return out


def _retrospective_target(
    ordered: list[RouterTrainSample],
    i: int,
    n: int,
) -> tuple[int, bool] | None:
    """Return ``(target_idx, confirmed)`` if turn ``i`` was under-routed.

    Triggered when turn ``i+1`` complains and turn ``i`` was routed low. The
    target is capped at ``+MAX_RETRO_STEP`` and never exceeds the tier that
    actually resolved the complaint. If turn ``i+2`` complains again, the higher
    tier did *not* resolve the issue, so the signal is rejected as noise.
    """

    if i + 1 >= n:
        return None
    nxt = ordered[i + 1]
    if not nxt.complaint_detected:
        return None

    cur_idx = route_index(ordered[i].route_class)
    if cur_idx > RETRO_ELIGIBLE_MAX_IDX:
        return None

    resolved_idx = route_index(nxt.final_route_class)
    if resolved_idx <= cur_idx:
        return None  # no genuine upgrade signal to learn from

    after = ordered[i + 2] if i + 2 < n else None
    if after is not None and after.complaint_detected:
        return None  # the upgrade did not resolve it -> reject as noise

    target_idx = min(resolved_idx, cur_idx + MAX_RETRO_STEP, len(ROUTE_CLASSES) - 1)
    target_idx = max(target_idx, cur_idx + 1)
    confirmed = after is not None  # i+2 exists and (per above) did not complain
    return target_idx, confirmed
