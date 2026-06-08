"""Tests for M1 offline alignment + evidence-ledger dataset building."""

from __future__ import annotations

import numpy as np

from opensquilla.squilla_router.self_learning import (
    build_training_dataset,
    encode_features,
    export_training_dataset,
    write_sample,
)
from opensquilla.squilla_router.self_learning.alignment import (
    REASON_CONFIDENCE_BACKOFF,
    REASON_IMMEDIATE_COMPLAINT,
    REASON_NORMAL,
    REASON_RETROSPECTIVE,
    align_session,
)
from opensquilla.squilla_router.self_learning.schema import RouterTrainSample


def mk(
    session: str,
    turn: int,
    route_class: str,
    *,
    final: str | None = None,
    complaint: bool = False,
    conf_gate: bool = False,
    image: bool = False,
    schema: str = "v1",
    feats: np.ndarray | None = None,
    day: int | None = None,
) -> RouterTrainSample:
    vec = feats if feats is not None else (np.arange(390, dtype=np.float32) + turn)
    d = day if day is not None else (turn % 28) + 1
    return RouterTrainSample(
        session_key=session,
        turn_index=turn,
        ts=f"2026-06-{d:02d}T00:00:{turn:02d}Z",
        feature_schema_version=schema,
        features_390_b64=encode_features(vec),
        route_class=route_class,
        final_route_class=final or route_class,
        routed_tier="c1",
        complaint_detected=complaint,
        confidence_gate_applied=conf_gate,
        image_route=image,
    )


# --------------------------------------------------------------------------- #
# Alignment
# --------------------------------------------------------------------------- #


def _reasons(aligned):
    return [(a.turn_index, a.reason, a.target_idx) for a in aligned]


def test_immediate_complaint_labels_to_upgraded_tier() -> None:
    aligned = align_session([mk("s", 0, "R1", final="R3", complaint=True)])
    assert _reasons(aligned) == [(0, REASON_IMMEDIATE_COMPLAINT, 3)]


def test_retrospective_bumps_prior_under_routed_turn() -> None:
    # turn0 routed R0, turn1 complains and resolves at R2, turn2 calm -> confirmed
    aligned = align_session(
        [
            mk("s", 0, "R0", final="R0"),
            mk("s", 1, "R1", final="R2", complaint=True),
            mk("s", 2, "R1", final="R1"),
        ]
    )
    by_turn = {a.turn_index: a for a in aligned}
    assert by_turn[0].reason == REASON_RETROSPECTIVE
    assert by_turn[0].target_idx == 2  # min(resolved=2, cur0+2=2)
    assert by_turn[0].confirmed is True
    assert by_turn[1].reason == REASON_IMMEDIATE_COMPLAINT


def test_retrospective_is_capped_at_max_step() -> None:
    # turn0 R0, complaint resolves at R3, but cap limits bump to cur(0)+2 = R2
    aligned = align_session(
        [mk("s", 0, "R0", final="R0"), mk("s", 1, "R1", final="R3", complaint=True)]
    )
    by_turn = {a.turn_index: a for a in aligned}
    assert by_turn[0].reason == REASON_RETROSPECTIVE
    assert by_turn[0].target_idx == 2  # capped, not 3
    assert by_turn[0].confirmed is False  # no T+2 to confirm


def test_retrospective_rejected_when_already_high() -> None:
    # turn0 routed R2 (> eligible R1) -> a later complaint is not "under-routing"
    aligned = align_session(
        [mk("s", 0, "R2", final="R2"), mk("s", 1, "R1", final="R3", complaint=True)]
    )
    assert {a.turn_index: a for a in aligned}[0].reason == REASON_NORMAL


def test_retrospective_rejected_when_t2_recomplains() -> None:
    # complaint at t1 upgraded to R2, but t2 complains again -> not resolved -> noise
    aligned = align_session(
        [
            mk("s", 0, "R0", final="R0"),
            mk("s", 1, "R1", final="R2", complaint=True),
            mk("s", 2, "R1", final="R3", complaint=True),
        ]
    )
    assert {a.turn_index: a for a in aligned}[0].reason == REASON_NORMAL


def test_retrospective_rejected_when_no_real_upgrade() -> None:
    # complaint "resolved" at same tier as cur -> no signal
    aligned = align_session(
        [mk("s", 0, "R1", final="R1"), mk("s", 1, "R1", final="R1", complaint=True)]
    )
    assert {a.turn_index: a for a in aligned}[0].reason == REASON_NORMAL


def test_confidence_backoff_reason() -> None:
    aligned = align_session([mk("s", 0, "R2", final="R1", conf_gate=True)])
    assert aligned[0].reason == REASON_CONFIDENCE_BACKOFF
    assert aligned[0].target_idx == 1


def test_normal_reason_default() -> None:
    aligned = align_session([mk("s", 0, "R1", final="R1")])
    assert aligned[0].reason == REASON_NORMAL


# --------------------------------------------------------------------------- #
# Dataset building (end-to-end through the store)
# --------------------------------------------------------------------------- #


def test_build_dataset_end_to_end(tmp_path) -> None:
    for s in [
        mk("sessA", 0, "R0", final="R0"),
        mk("sessA", 1, "R1", final="R2", complaint=True),
        mk("sessA", 2, "R1", final="R1"),
    ]:
        write_sample(s, "agentX", home=tmp_path)
    ds = build_training_dataset("agentX", home=tmp_path)
    assert ds.X.shape == (3, 390)
    assert ds.y.shape == (3,) and ds.w.shape == (3,)
    assert ds.n_sessions == 1
    assert ds.feature_schema_version == "v1"
    assert set(ds.session_keys) == {"sessA"}
    assert REASON_RETROSPECTIVE in ds.reason_distribution()


def test_dataset_keeps_only_dominant_schema_version(tmp_path) -> None:
    for s in [
        mk("s", 0, "R1", schema="v1"),
        mk("s", 1, "R1", schema="v1"),
        mk("s", 2, "R1", schema="v2"),
    ]:
        write_sample(s, "agentY", home=tmp_path)
    ds = build_training_dataset("agentY", home=tmp_path)
    assert ds.feature_schema_version == "v1"
    assert len(ds) == 2
    assert ds.skipped_schema_mismatch == 1


def test_dataset_excludes_image_route(tmp_path) -> None:
    write_sample(mk("s", 0, "R1"), "agentZ", home=tmp_path)
    write_sample(mk("s", 1, "R1", image=True), "agentZ", home=tmp_path)
    ds = build_training_dataset("agentZ", home=tmp_path)
    assert len(ds) == 1
    assert ds.skipped_bypass == 1


def test_correction_outweighs_flooded_normal(tmp_path) -> None:
    flood = np.ones(390, dtype=np.float32)
    # 4 identical "normal" turns (flooding) ...
    for t in range(4):
        write_sample(mk("flood", t, "R1", feats=flood), "agentW", home=tmp_path)
    # ... plus one retrospective correction in another session
    write_sample(mk("corr", 0, "R0", final="R0"), "agentW", home=tmp_path)
    write_sample(mk("corr", 1, "R1", final="R2", complaint=True), "agentW", home=tmp_path)
    ds = build_training_dataset("agentW", home=tmp_path)
    w_by_reason = {}
    for reason, weight in zip(ds.reasons, ds.w):
        w_by_reason.setdefault(reason, []).append(float(weight))
    normal_w = max(w_by_reason[REASON_NORMAL])
    retro_w = max(w_by_reason[REASON_RETROSPECTIVE])
    assert retro_w > normal_w
    # flooded identical normals are damped below their 0.3 base
    assert normal_w < 0.3


def test_export_npz_roundtrip(tmp_path) -> None:
    for s in [mk("s", 0, "R1"), mk("s", 1, "R2")]:
        write_sample(s, "agentE", home=tmp_path)
    ds = build_training_dataset("agentE", home=tmp_path)
    path = export_training_dataset(ds, "agentE", home=tmp_path)
    assert path.exists()
    loaded = np.load(path, allow_pickle=True)
    assert loaded["X"].shape == (2, 390)
    np.testing.assert_array_equal(loaded["y"], ds.y)
    assert (path.parent / f"{ds.feature_schema_version}.meta.json").exists()


def test_empty_store_returns_empty_dataset(tmp_path) -> None:
    ds = build_training_dataset("nobody", home=tmp_path)
    assert len(ds) == 0
    assert ds.X.shape == (0, 390)
