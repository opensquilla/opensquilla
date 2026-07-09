"""Explicit-feedback consumption: alignment reasons, weights, gates, rollback.

The load-bearing invariant: ``align_session(samples, feedback=None)`` must be
byte-identical to the pre-feedback behavior — pinned first, below.
"""

from __future__ import annotations

import numpy as np
import pytest

from opensquilla.squilla_router.self_learning.alignment import (
    REASON_CONFIDENCE_BACKOFF,
    REASON_EXPLICIT_DOWNVOTE,
    REASON_EXPLICIT_DOWNVOTE_ENSEMBLE,
    REASON_EXPLICIT_DOWNVOTE_HIGH_TIER,
    REASON_EXPLICIT_UPVOTE,
    REASON_EXPLICIT_UPVOTE_ENSEMBLE,
    REASON_IMMEDIATE_COMPLAINT,
    REASON_NORMAL,
    REASON_RETROSPECTIVE,
    align_session,
)
from opensquilla.squilla_router.self_learning.feedback import FeedbackEntry
from opensquilla.squilla_router.self_learning.schema import (
    RouterTrainSample,
    encode_features,
)

SESSION = "agent:main:webchat:s1"


def _sample(
    turn: int,
    *,
    route: str = "R0",
    final: str | None = None,
    complaint: bool = False,
    gate: bool = False,
    seed: float = 0.0,
) -> RouterTrainSample:
    return RouterTrainSample(
        session_key=SESSION,
        turn_index=turn,
        ts=f"2026-07-01T00:00:{turn:02d}Z",
        feature_schema_version="v1",
        features_390_b64=encode_features(np.full(390, seed, np.float32)),
        route_class=route,
        final_route_class=final or route,
        complaint_detected=complaint,
        confidence_gate_applied=gate,
        decision_id=f"dec-{turn}",
    )


def _fb(rating: str, kind: str = "single") -> FeedbackEntry:
    return FeedbackEntry(rating=rating, executed_kind=kind)


def _fbmap(turn: int, rating: str, kind: str = "single") -> dict:
    return {f"dec-{turn}": _fb(rating, kind)}


# --------------------------------------------------------------------------- #
# Regression anchor: feedback=None keeps the exact pre-feedback output
# --------------------------------------------------------------------------- #


def test_no_feedback_is_byte_identical_to_legacy() -> None:
    samples = [
        _sample(0, route="R0", seed=0.1),
        _sample(1, route="R0", final="R2", complaint=True, seed=0.2),
        _sample(2, route="R1", gate=True, seed=0.3),
        _sample(3, route="R3", seed=0.4),
    ]
    default = align_session(samples)
    explicit_none = align_session(samples, None)
    empty = align_session(samples, {})

    for legacy, a, b in zip(default, explicit_none, empty, strict=True):
        for other in (a, b):
            assert legacy.reason == other.reason
            assert legacy.target_idx == other.target_idx
            assert legacy.confirmed == other.confirmed
            assert np.array_equal(legacy.features_390, other.features_390)

    # Reasons are exactly the legacy set on this fixture.
    assert [s.reason for s in default] == [
        REASON_RETROSPECTIVE,  # turn 0: turn 1 complains, R0 eligible
        REASON_IMMEDIATE_COMPLAINT,
        REASON_CONFIDENCE_BACKOFF,
        REASON_NORMAL,
    ]


# --------------------------------------------------------------------------- #
# Down-vote semantics (single-model)
# --------------------------------------------------------------------------- #


def test_downvote_on_underrouted_turn_upgrades_one_step() -> None:
    samples = [_sample(0, route="R0"), _sample(1, route="R0")]
    fb = _fbmap(0, "down")

    aligned = align_session(samples, fb)

    assert aligned[0].reason == REASON_EXPLICIT_DOWNVOTE
    assert aligned[0].target_idx == 1  # +1 step only, not retro's +2
    assert aligned[0].confirmed is True  # calm follow-up confirms


def test_downvote_without_followup_is_unconfirmed() -> None:
    samples = [_sample(0, route="R0")]
    aligned = align_session(samples, _fbmap(0, "down"))
    assert aligned[0].reason == REASON_EXPLICIT_DOWNVOTE
    assert aligned[0].confirmed is False


def test_downvote_on_high_prediction_never_upgrades() -> None:
    """R2/R3 predictions: dissatisfaction is not attributable to the tier."""
    samples = [_sample(0, route="R2"), _sample(1, route="R3")]
    fb = {**_fbmap(0, "down"), **_fbmap(1, "down")}

    aligned = align_session(samples, fb)

    for a, expected_target in zip(aligned, (2, 3), strict=True):
        assert a.reason == REASON_EXPLICIT_DOWNVOTE_HIGH_TIER  # excluded bucket
        assert a.target_idx == expected_target  # target unchanged — no upgrade


def test_downvote_endorses_existing_complaint_upgrade() -> None:
    samples = [_sample(0, route="R0", final="R2", complaint=True)]
    aligned = align_session(samples, _fbmap(0, "down"))

    assert aligned[0].reason == REASON_EXPLICIT_DOWNVOTE  # upgraded from complaint
    assert aligned[0].target_idx == 2  # complaint target kept


def test_downvote_on_capped_complaint_does_not_endorse_served_tier() -> None:
    """A complaint whose upgrade was capped (final == route) is not a real
    upgrade; the down-vote must take the standalone +1 path, never train the
    rejected tier at the table's highest weight."""
    samples = [_sample(0, route="R0", final="R0", complaint=True)]
    aligned = align_session(samples, _fbmap(0, "down"))

    assert aligned[0].reason == REASON_EXPLICIT_DOWNVOTE
    assert aligned[0].target_idx == 1  # +1 from served, NOT the served R0


def test_downvote_endorses_retrospective() -> None:
    samples = [
        _sample(0, route="R0"),
        _sample(1, route="R0", final="R2", complaint=True),
        _sample(2, route="R0"),
    ]
    aligned = align_session(samples, _fbmap(0, "down"))

    assert aligned[0].reason == REASON_EXPLICIT_DOWNVOTE
    assert aligned[0].target_idx == 2  # retro target (resolving tier) kept


def test_next_turn_complaint_keeps_downvote_unconfirmed() -> None:
    samples = [
        _sample(0, route="R0"),
        _sample(1, route="R0", final="R1", complaint=True),
        _sample(2, route="R0"),
    ]
    # Turn 0 down-voted AND turn 1 complains: retro fires first (target R1),
    # the down-vote endorses it.
    aligned = align_session(samples, _fbmap(0, "down"))
    assert aligned[0].reason == REASON_EXPLICIT_DOWNVOTE
    assert aligned[0].target_idx == 1


# --------------------------------------------------------------------------- #
# Ensemble split
# --------------------------------------------------------------------------- #


def test_ensemble_downvote_never_upgrades() -> None:
    samples = [_sample(0, route="R0")]
    aligned = align_session(samples, _fbmap(0, "down", "ensemble"))

    assert aligned[0].reason == REASON_EXPLICIT_DOWNVOTE_ENSEMBLE
    assert aligned[0].target_idx == 0  # no upgrade even though R0-eligible


def test_ensemble_upvote_uses_diluted_reason() -> None:
    samples = [_sample(0, route="R1")]
    aligned = align_session(samples, _fbmap(0, "up", "ensemble"))
    assert aligned[0].reason == REASON_EXPLICIT_UPVOTE_ENSEMBLE


# --------------------------------------------------------------------------- #
# Up-vote semantics
# --------------------------------------------------------------------------- #


def test_upvote_confirms_served_tier() -> None:
    samples = [_sample(0, route="R1")]
    aligned = align_session(samples, _fbmap(0, "up"))
    assert aligned[0].reason == REASON_EXPLICIT_UPVOTE
    assert aligned[0].target_idx == 1


def test_upvote_never_overrides_corrections() -> None:
    """An up-vote must not weaken complaint/retro corrections on the turn."""
    complaint = [_sample(0, route="R0", final="R2", complaint=True)]
    aligned = align_session(complaint, _fbmap(0, "up"))
    assert aligned[0].reason == REASON_IMMEDIATE_COMPLAINT

    retro = [
        _sample(0, route="R0"),
        _sample(1, route="R0", final="R2", complaint=True),
        _sample(2, route="R0"),
    ]
    aligned2 = align_session(retro, _fbmap(0, "up"))
    assert aligned2[0].reason == REASON_RETROSPECTIVE


def test_upvote_overrides_backoff() -> None:
    samples = [_sample(0, route="R1", gate=True)]
    aligned = align_session(samples, _fbmap(0, "up"))
    assert aligned[0].reason == REASON_EXPLICIT_UPVOTE


# --------------------------------------------------------------------------- #
# Dataset weights
# --------------------------------------------------------------------------- #


def _weights_for(aligned_reasons_and_flags):
    """Build minimal AlignedSample list and run _compute_weights."""
    from opensquilla.squilla_router.self_learning.alignment import AlignedSample
    from opensquilla.squilla_router.self_learning.dataset import _compute_weights

    aligned = []
    for i, (reason, confirmed) in enumerate(aligned_reasons_and_flags):
        aligned.append(
            AlignedSample(
                features_390=np.full(390, float(i), np.float32),
                target_idx=1,
                served_idx=1,
                reason=reason,
                session_key=SESSION,
                turn_index=i,
                day="2026-07-01",
                feature_hash=f"h{i}",  # distinct → no flood damping
                confirmed=confirmed,
            )
        )
    return _compute_weights(aligned)


def test_weight_table_and_exclusion() -> None:
    weights = _weights_for(
        [
            (REASON_EXPLICIT_DOWNVOTE, True),
            (REASON_RETROSPECTIVE, True),
            (REASON_EXPLICIT_UPVOTE, True),
            (REASON_EXPLICIT_UPVOTE_ENSEMBLE, True),
            (REASON_EXPLICIT_DOWNVOTE_ENSEMBLE, True),
            (REASON_EXPLICIT_DOWNVOTE_HIGH_TIER, True),
            (REASON_NORMAL, True),
        ]
    )
    assert weights[0] == pytest.approx(1.2)  # downvote > retro
    assert weights[1] == pytest.approx(1.0)
    assert weights[2] == pytest.approx(0.6)
    assert weights[3] == pytest.approx(0.3)  # ensemble upvote = normal level
    assert weights[4] == 0.0  # excluded entirely
    assert weights[5] == 0.0  # high-tier exclusion, distinct reason
    assert weights[6] == pytest.approx(0.3)


def test_unconfirmed_downvote_halved() -> None:
    weights = _weights_for([(REASON_EXPLICIT_DOWNVOTE, False)])
    assert weights[0] == pytest.approx(0.6)  # 1.2 * 0.5


def test_upvote_flood_damping() -> None:
    """Identical feature vectors: repeated up-votes are damped like normals."""
    from opensquilla.squilla_router.self_learning.alignment import AlignedSample
    from opensquilla.squilla_router.self_learning.dataset import _compute_weights

    aligned = [
        AlignedSample(
            features_390=np.zeros(390, np.float32),
            target_idx=1,
            served_idx=1,
            reason=REASON_EXPLICIT_UPVOTE,
            session_key=SESSION,
            turn_index=i,
            day="2026-07-01",
            feature_hash="same",  # identical vector recurring
            confirmed=True,
        )
        for i in range(4)
    ]
    weights = _compute_weights(aligned)
    assert weights[0] == pytest.approx(0.6 / 2.0)  # 0.6 / sqrt(4)


# --------------------------------------------------------------------------- #
# Dataset join end-to-end (store -> feedback -> aligned matrix)
# --------------------------------------------------------------------------- #


def test_build_dataset_joins_feedback(tmp_path) -> None:
    from opensquilla.squilla_router.self_learning.dataset import build_training_dataset
    from opensquilla.squilla_router.self_learning.feedback import write_feedback
    from opensquilla.squilla_router.self_learning.store import write_sample

    for turn in range(3):
        write_sample(_sample(turn, route="R0", seed=float(turn)), "main", home=tmp_path)
    write_feedback(
        "main",
        decision_id="dec-0",
        session_key=SESSION,
        turn_index=0,
        rating="down",
        home=tmp_path,
    )

    ds = build_training_dataset("main", home=tmp_path)

    reasons = dict(zip(ds.turn_indices, ds.reasons, strict=True))
    assert reasons[0] == REASON_EXPLICIT_DOWNVOTE
    assert reasons[1] == REASON_NORMAL
    labels = dict(zip(ds.turn_indices, ds.y.tolist(), strict=True))
    assert labels[0] == 1  # R0 -> R1 upgrade label


def test_build_dataset_without_feedback_unchanged(tmp_path) -> None:
    """No sidecar present: dataset identical to the pre-feedback pipeline."""
    from opensquilla.squilla_router.self_learning.dataset import build_training_dataset
    from opensquilla.squilla_router.self_learning.store import write_sample

    for turn in range(3):
        write_sample(_sample(turn, route="R0", seed=float(turn)), "main", home=tmp_path)

    ds = build_training_dataset("main", home=tmp_path)
    assert set(ds.reasons) == {REASON_NORMAL}
    assert ds.y.tolist() == [0, 0, 0]


# --------------------------------------------------------------------------- #
# Rollback second trigger
# --------------------------------------------------------------------------- #


def test_downvote_rate_triggers_rollback() -> None:
    from types import SimpleNamespace

    from opensquilla.squilla_router.self_learning.promotion import should_rollback

    cfg = SimpleNamespace()
    # Complaint rate flat; downvote rate jumped 0.0 -> 0.4 on 6 ratings.
    assert should_rollback(
        pre_complaint_rate=0.1,
        post_complaint_rate=0.1,
        post_n=100,
        config=cfg,
        pre_downvote_rate=0.0,
        post_downvote_rate=0.4,
        post_feedback_n=6,
    )


def test_downvote_trigger_respects_min_samples() -> None:
    from types import SimpleNamespace

    from opensquilla.squilla_router.self_learning.promotion import should_rollback

    assert not should_rollback(
        pre_complaint_rate=0.1,
        post_complaint_rate=0.1,
        post_n=100,
        config=SimpleNamespace(),
        pre_downvote_rate=0.0,
        post_downvote_rate=1.0,
        post_feedback_n=4,  # below min_feedback_monitor_samples default 5
    )


def test_complaint_trigger_unchanged() -> None:
    from types import SimpleNamespace

    from opensquilla.squilla_router.self_learning.promotion import should_rollback

    assert should_rollback(
        pre_complaint_rate=0.1,
        post_complaint_rate=0.3,
        post_n=30,
        config=SimpleNamespace(),
    )
    assert not should_rollback(
        pre_complaint_rate=0.1,
        post_complaint_rate=0.12,
        post_n=30,
        config=SimpleNamespace(),
    )


# --------------------------------------------------------------------------- #
# Volume gate counts down-votes
# --------------------------------------------------------------------------- #


def test_gate_counts_feedback_down_toward_volume() -> None:
    from opensquilla.gateway.config import RouterSelfLearningConfig
    from opensquilla.squilla_router.self_learning.gates import evaluate_training_gates
    from opensquilla.squilla_router.self_learning.state import EventStoreStats, TrainState

    cfg = RouterSelfLearningConfig(
        enabled=True, train_min_samples=10, idle_hours=0.0, cooldown_hours=0.0
    )
    stats = EventStoreStats(
        total=50, high_value=6, distinct_classes=2, last_ts="2026-01-01T00:00:00Z"
    )
    gate = evaluate_training_gates(config=cfg, state=TrainState(), stats=stats)
    assert not gate.should_train  # 6 < 10

    stats_fb = EventStoreStats(
        total=50,
        high_value=6,
        distinct_classes=2,
        last_ts="2026-01-01T00:00:00Z",
        feedback_down=4,
    )
    gate2 = evaluate_training_gates(config=cfg, state=TrainState(), stats=stats_fb)
    assert gate2.should_train  # 6 + 4 >= 10


# --------------------------------------------------------------------------- #
# Orchestrator end-to-end with feedback (promote baseline / rollback / receipt)
# --------------------------------------------------------------------------- #


def _write_min_store(tmp_path, n_high=8) -> None:
    from opensquilla.squilla_router.self_learning.store import write_sample

    for i in range(n_high):
        s = RouterTrainSample(
            session_key="agent:main:webchat:s1",
            turn_index=i,
            ts=f"2026-06-01T00:00:{i:02d}Z",
            feature_schema_version="v1",
            features_390_b64=encode_features(np.full(390, float(i), np.float32)),
            route_class="R0" if i % 2 else "R1",
            final_route_class="R2" if i % 2 else "R3",
            complaint_detected=True,
        )
        write_sample(s, "main", home=tmp_path)
    calm = RouterTrainSample(
        session_key="agent:main:webchat:s2",
        turn_index=0,
        ts="2026-06-01T01:00:00Z",
        feature_schema_version="v1",
        features_390_b64=encode_features(np.zeros(390, np.float32)),
        route_class="R1",
        final_route_class="R1",
    )
    write_sample(calm, "main", home=tmp_path)


def test_orchestrator_records_and_clears_downvote_baseline(tmp_path) -> None:
    from datetime import UTC, datetime

    from opensquilla.gateway.config import RouterSelfLearningConfig, SquillaRouterConfig
    from opensquilla.squilla_router.self_learning.feedback import write_feedback
    from opensquilla.squilla_router.self_learning.orchestrator import (
        in_process_trainer,
        maybe_run_update_router,
    )
    from opensquilla.squilla_router.self_learning.state import load_train_state

    now = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)
    _write_min_store(tmp_path)
    # Pre-promotion feedback: 1 down / 4 up (single) -> baseline 0.2.
    for i, rating in enumerate(["down", "up", "up", "up", "up"]):
        write_feedback(
            "main",
            decision_id=f"pre-{i}",
            session_key="agent:main:webchat:s1",
            turn_index=i,
            rating=rating,
            home=tmp_path,
            now=datetime(2026, 6, 2, 0, 0, i, tzinfo=UTC),
        )

    cfg = SquillaRouterConfig(
        self_learning=RouterSelfLearningConfig(
            enabled=True,
            train_min_samples=4,
            idle_hours=2.0,
            cooldown_hours=72.0,
            holdout_min_size=4,
            holdout_pct=0.4,
            holdout_repeats=2,
            max_critical_under_routing=1.0,
            cost_tolerance_pct=500.0,
        )
    )
    (tmp_path / "base").mkdir()  # empty base -> trains fresh
    res = maybe_run_update_router(
        "main",
        router_cfg=cfg,
        home=tmp_path,
        now=now,
        trainer=in_process_trainer,
        base_dir=tmp_path / "base",
    )
    assert res.promoted, res
    state = load_train_state("main", tmp_path)
    assert state.pre_promotion_downvote_rate == pytest.approx(0.2)

    import json as _json

    receipts = list((tmp_path / "router" / ".receipts").glob("main-*-promoted.json"))
    assert receipts
    payload = _json.loads(receipts[0].read_text())
    assert payload["pre_promotion_downvote_rate"] == pytest.approx(0.2)


def test_orchestrator_no_feedback_baseline_is_none(tmp_path) -> None:
    """Zero recorded ratings -> unmeasured baseline (None), never 0.0."""
    from datetime import UTC, datetime

    from opensquilla.gateway.config import RouterSelfLearningConfig, SquillaRouterConfig
    from opensquilla.squilla_router.self_learning.orchestrator import (
        in_process_trainer,
        maybe_run_update_router,
    )
    from opensquilla.squilla_router.self_learning.state import load_train_state

    _write_min_store(tmp_path)
    cfg = SquillaRouterConfig(
        self_learning=RouterSelfLearningConfig(
            enabled=True,
            train_min_samples=4,
            idle_hours=2.0,
            cooldown_hours=72.0,
            holdout_min_size=4,
            holdout_pct=0.4,
            holdout_repeats=2,
            max_critical_under_routing=1.0,
            cost_tolerance_pct=500.0,
        )
    )
    (tmp_path / "base").mkdir()  # empty base -> trains fresh
    res = maybe_run_update_router(
        "main",
        router_cfg=cfg,
        home=tmp_path,
        now=datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC),
        trainer=in_process_trainer,
        base_dir=tmp_path / "base",
    )
    assert res.promoted, res
    state = load_train_state("main", tmp_path)
    assert state.pre_promotion_downvote_rate is None
    # And with a None baseline the feedback trigger cannot fire even on a
    # burst of early downvotes (should_rollback skips it).
    from types import SimpleNamespace

    from opensquilla.squilla_router.self_learning.promotion import should_rollback

    assert not should_rollback(
        pre_complaint_rate=0.5,  # flat
        post_complaint_rate=0.5,
        post_n=100,
        config=SimpleNamespace(),
        pre_downvote_rate=None,
        post_downvote_rate=1.0,
        post_feedback_n=50,
    )


def test_ensemble_downvotes_do_not_open_volume_gate(tmp_path) -> None:
    """Design invariant: gate counts only label-producing (single) downvotes."""
    from opensquilla.squilla_router.self_learning.feedback import write_feedback
    from opensquilla.squilla_router.self_learning.orchestrator import _with_feedback_stats
    from opensquilla.squilla_router.self_learning.state import EventStoreStats

    for i in range(6):
        write_feedback(
            "main",
            decision_id=f"e-{i}",
            session_key="agent:main:webchat:s1",
            turn_index=i,
            rating="down",
            executed_kind="ensemble",
            home=tmp_path,
        )
    stats = _with_feedback_stats(EventStoreStats(total=10), "main", tmp_path)
    assert stats.feedback_down == 0  # ensemble downvotes produce no labels

    write_feedback(
        "main",
        decision_id="s-1",
        session_key="agent:main:webchat:s1",
        turn_index=9,
        rating="down",
        executed_kind="single",
        home=tmp_path,
    )
    stats2 = _with_feedback_stats(EventStoreStats(total=10), "main", tmp_path)
    assert stats2.feedback_down == 1


def test_downvote_anchor_is_served_aware() -> None:
    """Gate/hold turns: the bump starts from the SERVED tier, not the raw
    prediction, so a downvote never trains the tier the user just rejected."""
    # Confidence gate: predicted R0, served R1 (gate default). Downvote must
    # target R2, not R1.
    gated = _sample(0, route="R0", final="R1", gate=True)
    aligned = align_session([gated], _fbmap(0, "down"))
    assert aligned[0].reason == REASON_EXPLICIT_DOWNVOTE
    assert aligned[0].target_idx == 2

    # Anti-downgrade hold: predicted R0, served R2. Served index is above the
    # eligibility cap -> excluded, no upgrade label pointing below the served.
    held = _sample(0, route="R0", final="R2")
    aligned2 = align_session([held], _fbmap(0, "down"))
    assert aligned2[0].reason == REASON_EXPLICIT_DOWNVOTE_HIGH_TIER
    assert aligned2[0].target_idx == 2
