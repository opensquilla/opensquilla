"""Tests for M3 (promotion gate + active pointer) and M4 (auto-rollback)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from opensquilla.gateway.config import RouterSelfLearningConfig, SquillaRouterConfig
from opensquilla.squilla_router.self_learning import encode_features, write_sample
from opensquilla.squilla_router.self_learning.dataset import TrainingDataset
from opensquilla.squilla_router.self_learning.evaluate import (
    decide_promotion,
    route_metrics,
    session_holdout_splits,
)
from opensquilla.squilla_router.self_learning.orchestrator import (
    in_process_trainer,
    maybe_run_update_router,
)
from opensquilla.squilla_router.self_learning.promotion import (
    learned_bundle_dir,
    promote_candidate,
    quarantine_candidate,
    read_active,
    resolve_active_bundle_dir,
    rollback_active,
    should_rollback,
    write_active_atomic,
)
from opensquilla.squilla_router.self_learning.schema import RouterTrainSample
from opensquilla.squilla_router.self_learning.state import (
    TrainState,
    load_train_state,
    save_train_state,
)

NOW = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


def _cfg(**kw) -> RouterSelfLearningConfig:
    base = dict(
        enabled=True,
        train_min_samples=4,
        idle_hours=2.0,
        cooldown_hours=72.0,
        holdout_min_size=4,
        holdout_pct=0.4,
        holdout_repeats=2,
        max_critical_under_routing=0.5,
        cost_tolerance_pct=25.0,
    )
    base.update(kw)
    return RouterSelfLearningConfig(**base)


# --------------------------------------------------------------------------- #
# Active pointer primitives
# --------------------------------------------------------------------------- #


def test_active_pointer_defaults_to_baseline(tmp_path) -> None:
    assert read_active(tmp_path) == "baseline"
    assert resolve_active_bundle_dir(tmp_path) is None


def test_promote_and_resolve(tmp_path) -> None:
    bundle = learned_bundle_dir("v1-x", tmp_path)
    bundle.mkdir(parents=True)
    (bundle / "lgbm_main.bin").write_text("model", encoding="utf-8")
    prev = promote_candidate("v1-x", tmp_path)
    assert prev == "baseline"
    assert read_active(tmp_path) == "learned/v1-x"
    assert resolve_active_bundle_dir(tmp_path) == bundle


def test_resolve_falls_back_when_bundle_incomplete(tmp_path) -> None:
    write_active_atomic("learned/ghost", tmp_path)  # no such bundle on disk
    assert resolve_active_bundle_dir(tmp_path) is None


def test_rollback_reverts_to_baseline(tmp_path) -> None:
    write_active_atomic("learned/v1-x", tmp_path)
    prev = rollback_active(tmp_path)
    assert prev == "learned/v1-x"
    assert read_active(tmp_path) == "baseline"


def test_quarantine_moves_bundle_out(tmp_path) -> None:
    bundle = learned_bundle_dir("v1-x", tmp_path)
    bundle.mkdir(parents=True)
    (bundle / "lgbm_main.bin").write_text("m", encoding="utf-8")
    dest = quarantine_candidate("v1-x", tmp_path)
    assert dest is not None and dest.exists()
    assert not bundle.exists()


def test_should_rollback_rules() -> None:
    cfg = _cfg(min_monitor_samples=10, complaint_regression_delta=0.05)
    # regression beyond delta with enough samples -> rollback
    assert should_rollback(pre_complaint_rate=0.1, post_complaint_rate=0.3, post_n=20, config=cfg)
    # not enough samples yet
    assert not should_rollback(
        pre_complaint_rate=0.1, post_complaint_rate=0.9, post_n=5, config=cfg
    )
    # within delta
    assert not should_rollback(
        pre_complaint_rate=0.1, post_complaint_rate=0.12, post_n=50, config=cfg
    )
    # no baseline recorded
    assert not should_rollback(
        pre_complaint_rate=None, post_complaint_rate=0.9, post_n=50, config=cfg
    )
    # auto_rollback disabled
    off = _cfg(auto_rollback=False)
    assert not should_rollback(
        pre_complaint_rate=0.0, post_complaint_rate=0.9, post_n=99, config=off
    )


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


def test_route_metrics_basic() -> None:
    pred = np.array([1, 2, 0, 3])
    target = np.array([1, 3, 0, 3])  # under-routes the 2nd (pred 2 < target 3)
    served = np.array([1, 1, 0, 3])
    m = route_metrics(pred, target, served)
    assert m.n == 4
    assert m.agreement == 0.75
    # critical = target>=2 -> indices 1,3; pred<target only at idx1 -> 0.5
    assert m.critical_under_routing_rate == 0.5


def test_holdout_splits_are_session_whole_and_floored(tmp_path) -> None:
    ds = TrainingDataset(
        X=np.zeros((10, 390), np.float32),
        y=np.zeros(10, np.int64),
        w=np.ones(10, np.float32),
        session_keys=[f"s{i % 2}" for i in range(10)],  # 2 sessions
    )
    splits = session_holdout_splits(ds, holdout_pct=0.4, repeats=2, min_size=2)
    assert splits
    for train_idx, hold_idx in splits:
        # no session appears on both sides
        train_sessions = {ds.session_keys[i] for i in train_idx}
        hold_sessions = {ds.session_keys[i] for i in hold_idx}
        assert not (train_sessions & hold_sessions)
    # too few sessions -> no splits
    single = TrainingDataset(
        X=np.zeros((4, 390), np.float32),
        y=np.zeros(4, np.int64),
        w=np.ones(4, np.float32),
        session_keys=["s0"] * 4,
    )
    assert session_holdout_splits(single, holdout_pct=0.4, repeats=2, min_size=2) == []


def test_decide_promotion_paths() -> None:
    cfg = _cfg(holdout_min_size=4, max_critical_under_routing=0.3, cost_tolerance_pct=10.0)
    good_cv = {
        "agreement": 0.9,
        "critical_under_routing_rate": 0.1,
        "mean_pred_idx": 1.0,
        "served_mean_idx": 1.0,
        "n_holdout": 20,
    }
    assert decide_promotion(good_cv, golden=None, baseline_golden=None, config=cfg).promote
    # quality regression
    bad_q = {**good_cv, "critical_under_routing_rate": 0.6}
    d = decide_promotion(bad_q, golden=None, baseline_golden=None, config=cfg)
    assert not d.promote and "quality_regression" in d.reason
    # cost regression (predicts much higher than served)
    bad_c = {**good_cv, "mean_pred_idx": 2.5, "served_mean_idx": 1.0}
    d = decide_promotion(bad_c, golden=None, baseline_golden=None, config=cfg)
    assert not d.promote and "cost_regression" in d.reason
    # insufficient eval (no cv, no golden)
    empty = {"agreement": None, "n_holdout": 0, "served_mean_idx": 0.0}
    assert decide_promotion(empty, golden=None, baseline_golden=None, config=cfg).reason == (
        "insufficient_eval"
    )


# --------------------------------------------------------------------------- #
# Strategy integration (cache)
# --------------------------------------------------------------------------- #


def test_invalidate_strategy_cache(monkeypatch) -> None:
    from opensquilla.engine.steps import squilla_router as step

    step._strategy = object()
    step._strategy_key = ("x",)
    step.invalidate_strategy_cache()
    assert step._strategy is None and step._strategy_key is None


def test_cache_key_tracks_active_bundle(monkeypatch) -> None:
    from opensquilla.engine.steps import squilla_router as step

    cfg = SquillaRouterConfig(self_learning=_cfg())
    monkeypatch.setattr(step, "_active_bundle_dir", lambda _c: "learned/v1")
    key1 = step._strategy_cache_key(cfg)
    monkeypatch.setattr(step, "_active_bundle_dir", lambda _c: "learned/v2")
    key2 = step._strategy_cache_key(cfg)
    assert key1 != key2


def test_active_bundle_dir_none_when_disabled() -> None:
    from opensquilla.engine.steps import squilla_router as step

    cfg = SquillaRouterConfig(self_learning=RouterSelfLearningConfig(enabled=False))
    assert step._active_bundle_dir(cfg) is None


# --------------------------------------------------------------------------- #
# Orchestrator: promote / reject / rollback
# --------------------------------------------------------------------------- #


def _write_separable_store(tmp_path, agent="agp", n=36) -> None:
    """Confidence-gate (high-value) turns with features cleanly separable by
    final class, so CV agreement is high and cost does not regress.

    Across 3 sessions this leaves each whole-session holdout fold ~12 training
    rows (6 per class) — enough for LightGBM to split past ``min_data_in_leaf``.
    """
    rng = np.random.RandomState(1)
    for i in range(n):
        cls = i % 2  # 0 -> R1, 1 -> R2
        fc = "R2" if cls else "R1"
        feats = (rng.randn(390) * 0.1).astype(np.float32)
        feats[0] = 5.0 if cls else -5.0
        write_sample(
            RouterTrainSample(
                session_key=f"s{i % 3}",
                turn_index=i,
                ts=f"2026-06-01T00:00:{i:02d}Z",
                feature_schema_version="v1",
                features_390_b64=encode_features(feats),
                route_class=fc,
                final_route_class=fc,
                routed_tier="c2" if cls else "c1",
                confidence_gate_applied=True,
            ),
            agent,
            home=tmp_path,
        )


def test_orchestrator_promotes_good_candidate(tmp_path) -> None:
    pytest.importorskip("lightgbm")
    base = tmp_path / "base"
    base.mkdir()
    (base / "router.runtime.yaml").write_text("k: v\n", encoding="utf-8")
    _write_separable_store(tmp_path)

    res = maybe_run_update_router(
        "agp",
        router_cfg=SquillaRouterConfig(self_learning=_cfg()),
        home=tmp_path,
        now=NOW,
        trainer=in_process_trainer,
        base_dir=base,
    )
    assert res.ran and res.promoted and res.reason == "promoted", res
    assert read_active(tmp_path) == f"learned/{res.version}"
    state = load_train_state("agp", tmp_path)
    assert state.active_version == res.version
    assert state.promoted_at is not None
    assert list((tmp_path / "router" / ".receipts").glob("agp-*-promoted.json"))


def test_orchestrator_rejects_on_golden_floor(tmp_path) -> None:
    pytest.importorskip("lightgbm")
    base = tmp_path / "base"
    base.mkdir()
    (base / "router.runtime.yaml").write_text("k: v\n", encoding="utf-8")
    _write_separable_store(tmp_path, agent="agr")

    # Golden set whose labels contradict the separable signal -> low agreement.
    rng = np.random.RandomState(2)
    gx = (rng.randn(20, 390) * 0.1).astype(np.float32)
    gy = np.zeros(20, np.int64)
    for i in range(20):
        gx[i, 0] = 5.0 if i % 2 else -5.0
        gy[i] = 0 if i % 2 else 2  # inverted vs training signal
    golden = tmp_path / "golden.npz"
    np.savez(golden, X=gx, y=gy)

    res = maybe_run_update_router(
        "agr",
        router_cfg=SquillaRouterConfig(
            self_learning=_cfg(golden_eval_path=str(golden), min_golden_agreement=0.9)
        ),
        home=tmp_path,
        now=NOW,
        trainer=in_process_trainer,
        base_dir=base,
    )
    assert res.ran and not res.promoted
    assert "golden_below_floor" in res.reason
    assert read_active(tmp_path) == "baseline"  # never swapped
    # candidate quarantined
    assert (tmp_path / "router" / "learned" / ".quarantine" / res.version).exists()


def test_orchestrator_auto_rolls_back_regressed_candidate(tmp_path) -> None:
    # Pre-promoted state with a clean baseline complaint rate.
    bundle = learned_bundle_dir("vBad", tmp_path)
    bundle.mkdir(parents=True)
    (bundle / "lgbm_main.bin").write_text("m", encoding="utf-8")
    write_active_atomic("learned/vBad", tmp_path)
    save_train_state(
        TrainState(
            active_version="vBad",
            promoted_at="2026-06-05T00:00:00Z",
            pre_promotion_complaint_rate=0.0,
        ),
        "agx",
        tmp_path,
    )
    # Post-swap traffic with high complaint rate, recent (so the agent looks
    # active and no training runs after the rollback).
    for i in range(30):
        write_sample(
            RouterTrainSample(
                session_key="s",
                turn_index=i,
                ts=f"2026-06-06T11:5{i % 10}:00Z",
                feature_schema_version="v1",
                features_390_b64=encode_features(np.zeros(390, np.float32)),
                route_class="R1",
                final_route_class="R2",
                complaint_detected=(i < 20),  # 20/30 complaints
            ),
            "agx",
            home=tmp_path,
        )

    res = maybe_run_update_router(
        "agx",
        router_cfg=SquillaRouterConfig(
            self_learning=_cfg(min_monitor_samples=10, complaint_regression_delta=0.05)
        ),
        home=tmp_path,
        now=NOW,
        trainer=in_process_trainer,
        base_dir=tmp_path / "base",
    )
    assert res.rolled_back
    assert read_active(tmp_path) == "baseline"
    state = load_train_state("agx", tmp_path)
    assert state.active_version is None
    assert (tmp_path / "router" / "learned" / ".quarantine" / "vBad").exists()
    assert list((tmp_path / "router" / ".receipts").glob("agx-*-rollback.json"))
