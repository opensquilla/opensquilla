"""Tests for M2: trigger gates, train state, trainer, and orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from opensquilla.gateway.config import RouterSelfLearningConfig, SquillaRouterConfig
from opensquilla.squilla_router.self_learning import encode_features, write_sample
from opensquilla.squilla_router.self_learning.dataset import TrainingDataset
from opensquilla.squilla_router.self_learning.gates import (
    AGENT_ACTIVE,
    COOLDOWN,
    DISABLED,
    INSUFFICIENT_CLASS_DIVERSITY,
    INSUFFICIENT_DATA,
    NO_DATA,
    READY,
    evaluate_training_gates,
)
from opensquilla.squilla_router.self_learning.orchestrator import (
    in_process_trainer,
    maybe_run_update_router,
)
from opensquilla.squilla_router.self_learning.schema import RouterTrainSample
from opensquilla.squilla_router.self_learning.state import (
    EventStoreStats,
    TrainState,
    load_train_state,
    save_train_state,
    scan_event_store,
)
from opensquilla.squilla_router.self_learning.store import ENV_DISABLE

NOW = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


def _cfg(**kw) -> RouterSelfLearningConfig:
    base = dict(enabled=True, train_min_samples=5, idle_hours=2.0, cooldown_hours=72.0)
    base.update(kw)
    return RouterSelfLearningConfig(**base)


def _stats(**kw) -> EventStoreStats:
    base = dict(total=100, high_value=50, distinct_classes=3, last_ts="2026-06-06T00:00:00Z")
    base.update(kw)
    return EventStoreStats(**base)


def mk(session, turn, route_class, *, final=None, complaint=False, conf_gate=False, ts=None):
    return RouterTrainSample(
        session_key=session,
        turn_index=turn,
        ts=ts or f"2026-06-06T00:00:{turn:02d}Z",
        feature_schema_version="v1",
        features_390_b64=encode_features(np.random.RandomState(turn).randn(390)),
        route_class=route_class,
        final_route_class=final or route_class,
        complaint_detected=complaint,
        confidence_gate_applied=conf_gate,
    )


# --------------------------------------------------------------------------- #
# Gates (pure)
# --------------------------------------------------------------------------- #


def test_gate_ready_when_all_pass() -> None:
    res = evaluate_training_gates(config=_cfg(), state=TrainState(), stats=_stats(), now=NOW)
    assert res.should_train and res.reason == READY


def test_gate_disabled_master_off() -> None:
    res = evaluate_training_gates(
        config=_cfg(enabled=False), state=TrainState(), stats=_stats(), now=NOW
    )
    assert not res.should_train and res.reason == DISABLED


def test_gate_disabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv(ENV_DISABLE, "1")
    res = evaluate_training_gates(config=_cfg(), state=TrainState(), stats=_stats(), now=NOW)
    assert res.reason == DISABLED


def test_gate_no_data() -> None:
    res = evaluate_training_gates(
        config=_cfg(), state=TrainState(), stats=_stats(total=0), now=NOW
    )
    assert res.reason == NO_DATA


def test_gate_agent_active_blocks() -> None:
    # last activity 30 min ago < idle_hours=2 -> defer
    recent = (NOW - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = evaluate_training_gates(
        config=_cfg(), state=TrainState(), stats=_stats(last_ts=recent), now=NOW
    )
    assert res.reason == AGENT_ACTIVE


def test_gate_cooldown_blocks() -> None:
    recent_train = (NOW - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = evaluate_training_gates(
        config=_cfg(cooldown_hours=72.0),
        state=TrainState(last_train_ts=recent_train),
        stats=_stats(),
        now=NOW,
    )
    assert res.reason == COOLDOWN


def test_gate_insufficient_data() -> None:
    res = evaluate_training_gates(
        config=_cfg(train_min_samples=200), state=TrainState(), stats=_stats(high_value=50), now=NOW
    )
    assert res.reason == INSUFFICIENT_DATA


def test_gate_failure_backoff_doubles_threshold() -> None:
    # base 5, 3 failures -> 5 * 2^3 = 40; high_value=30 fails, 50 passes
    state = TrainState(consecutive_failures=3)
    res = evaluate_training_gates(
        config=_cfg(train_min_samples=5), state=state, stats=_stats(high_value=30), now=NOW
    )
    assert res.reason == INSUFFICIENT_DATA
    assert res.effective_min_samples == 40
    res2 = evaluate_training_gates(
        config=_cfg(train_min_samples=5), state=state, stats=_stats(high_value=50), now=NOW
    )
    assert res2.should_train


def test_gate_class_diversity_floor() -> None:
    res = evaluate_training_gates(
        config=_cfg(), state=TrainState(), stats=_stats(distinct_classes=1), now=NOW
    )
    assert res.reason == INSUFFICIENT_CLASS_DIVERSITY


# --------------------------------------------------------------------------- #
# State + stats scan
# --------------------------------------------------------------------------- #


def test_train_state_roundtrip(tmp_path) -> None:
    assert load_train_state("a", tmp_path) == TrainState()
    st = TrainState(
        last_train_ts="2026-06-06T00:00:00Z", consecutive_failures=2, last_version="v1-x"
    )
    save_train_state(st, "a", tmp_path)
    assert load_train_state("a", tmp_path) == st


def test_scan_event_store_counts(tmp_path) -> None:
    write_sample(mk("s", 0, "R1"), "ag", home=tmp_path)
    write_sample(mk("s", 1, "R1", complaint=True), "ag", home=tmp_path)
    write_sample(mk("s", 2, "R2", conf_gate=True), "ag", home=tmp_path)
    stats = scan_event_store("ag", home=tmp_path)
    assert stats.total == 3
    assert stats.high_value == 2  # complaint + conf_gate
    assert stats.distinct_classes == 2  # R1, R2
    assert stats.dominant_schema_version == "v1"


# --------------------------------------------------------------------------- #
# Trainer (real LightGBM on small synthetic data)
# --------------------------------------------------------------------------- #


def _synthetic_dataset(n=80) -> TrainingDataset:
    rng = np.random.RandomState(0)
    feats = rng.randn(n, 390).astype(np.float32)
    y = rng.randint(0, 4, size=n).astype(np.int64)
    # make features weakly separable so training has signal
    for c in range(4):
        feats[y == c, c] += 3.0
    w = np.ones(n, dtype=np.float32)
    return TrainingDataset(X=feats, y=y, w=w, feature_schema_version="vTEST", n_sessions=5)


def test_train_candidate_fresh_builds_loadable_bundle(tmp_path) -> None:
    pytest.importorskip("lightgbm")
    from types import SimpleNamespace

    import lightgbm as lgb

    from opensquilla.squilla_router.self_learning.train import build_candidate_bundle

    base = tmp_path / "base"
    base.mkdir()
    (base / "router.runtime.yaml").write_text("k: v\n", encoding="utf-8")
    (base / "features").mkdir()
    (base / "features" / "meta.json").write_text("{}", encoding="utf-8")
    # no lgbm_main.bin in base -> trains fresh

    learned = tmp_path / "learned"
    info = build_candidate_bundle(
        _synthetic_dataset(),
        base_dir=base,
        learned_root=learned,
        config=SimpleNamespace(num_boost_round=20),
    )
    assert info.used_init_model is False
    bundle = learned / info.version
    assert (bundle / "lgbm_main.bin").is_file()  # real file, not symlink
    assert (bundle / "router.runtime.yaml").exists()  # reused artifact
    assert (bundle / "learned_manifest.json").exists()
    booster = lgb.Booster(model_file=str(bundle / "lgbm_main.bin"))
    pred = booster.predict(_synthetic_dataset(4).X.astype(np.float64))
    assert pred.shape == (4, 4)  # 4 samples x 4 classes


def test_train_candidate_uses_init_model_when_base_present(tmp_path) -> None:
    pytest.importorskip("lightgbm")
    from types import SimpleNamespace

    from opensquilla.squilla_router.self_learning.train import (
        build_candidate_bundle,
        train_booster,
    )

    # First produce a real base lgbm model to continue from.
    base = tmp_path / "base"
    base.mkdir()
    booster, _ = train_booster(
        _synthetic_dataset(), base_model_path=None, config=SimpleNamespace(num_boost_round=20)
    )
    booster.save_model(str(base / "lgbm_main.bin"))

    info = build_candidate_bundle(
        _synthetic_dataset(),
        base_dir=base,
        learned_root=tmp_path / "learned",
        config=SimpleNamespace(num_boost_round=10),
    )
    assert info.used_init_model is True


def test_assembled_bundle_manifest_matches_retrained_head(tmp_path) -> None:
    """The copied artifact manifest must describe the *new* lgbm head.

    The base manifest pins size/sha256 of the shipped model; without a rewrite
    the runtime's bundle validation rejects every candidate as incomplete.
    """
    pytest.importorskip("lightgbm")
    import hashlib
    import json
    from types import SimpleNamespace

    from opensquilla.squilla_router.self_learning.train import (
        build_candidate_bundle,
        train_booster,
    )

    base = tmp_path / "base"
    base.mkdir()
    booster, _ = train_booster(
        _synthetic_dataset(), base_model_path=None, config=SimpleNamespace(num_boost_round=20)
    )
    booster.save_model(str(base / "lgbm_main.bin"))
    base_bytes = (base / "lgbm_main.bin").read_bytes()
    (base / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [
                    {
                        "path": "lgbm_main.bin",
                        "size_bytes": len(base_bytes),
                        "sha256": hashlib.sha256(base_bytes).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    info = build_candidate_bundle(
        _synthetic_dataset(),
        base_dir=base,
        learned_root=tmp_path / "learned",
        config=SimpleNamespace(num_boost_round=10),
    )
    bundle = tmp_path / "learned" / info.version
    manifest_path = bundle / "artifact_manifest.json"
    assert manifest_path.is_file() and not manifest_path.is_symlink()
    new_bytes = (bundle / "lgbm_main.bin").read_bytes()
    entry = next(
        e
        for e in json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
        if e["path"] == "lgbm_main.bin"
    )
    assert entry["size_bytes"] == len(new_bytes)
    assert entry["sha256"] == hashlib.sha256(new_bytes).hexdigest()
    # The base manifest is untouched.
    base_entry = json.loads((base / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert base_entry["files"][0]["sha256"] == hashlib.sha256(base_bytes).hexdigest()


# --------------------------------------------------------------------------- #
# Orchestrator (injected trainer; no subprocess)
# --------------------------------------------------------------------------- #


def _router_cfg(**kw) -> SquillaRouterConfig:
    return SquillaRouterConfig(self_learning=_cfg(**kw))


def _write_ready_store(tmp_path, agent="ag", n_high=8) -> None:
    # idle: timestamps old enough; >=2 distinct final classes + high-value signals
    for i in range(n_high):
        write_sample(
            mk("s1", i, "R0" if i % 2 else "R1", final="R2" if i % 2 else "R3",
               complaint=True, ts=f"2026-06-01T00:00:{i:02d}Z"),
            agent, home=tmp_path,
        )
    write_sample(mk("s2", 0, "R1", final="R1", ts="2026-06-01T01:00:00Z"), agent, home=tmp_path)


def test_orchestrator_noop_when_gates_fail(tmp_path) -> None:
    # empty store -> NO_DATA, trainer never called
    calls = []
    res = maybe_run_update_router(
        "ag",
        router_cfg=_router_cfg(train_min_samples=5),
        home=tmp_path,
        now=NOW,
        trainer=lambda *a, **k: calls.append(1),
        base_dir=tmp_path / "base",
    )
    assert not res.ran and res.reason == NO_DATA and not calls


def test_orchestrator_trains_and_records_state(tmp_path) -> None:
    pytest.importorskip("lightgbm")
    base = tmp_path / "base"
    base.mkdir()
    (base / "router.runtime.yaml").write_text("k: v\n", encoding="utf-8")
    _write_ready_store(tmp_path, n_high=8)

    res = maybe_run_update_router(
        "ag",
        router_cfg=_router_cfg(train_min_samples=5, idle_hours=2.0, cooldown_hours=72.0),
        home=tmp_path,
        now=NOW,
        trainer=in_process_trainer,
        base_dir=base,
    )
    # Training ran and a candidate + state were recorded (promotion is gated
    # separately; with only 8 samples the gate rejects on insufficient_eval).
    assert res.ran and res.version
    state = load_train_state("ag", tmp_path)
    assert state.last_version == res.version
    assert state.last_train_ts is not None
    receipts = list((tmp_path / "router" / ".receipts").glob("ag-*-*.json"))
    assert receipts


def test_orchestrator_records_failure_and_backsoff(tmp_path) -> None:
    _write_ready_store(tmp_path, n_high=8)

    def boom(*a, **k):
        raise RuntimeError("training blew up")

    res = maybe_run_update_router(
        "ag",
        router_cfg=_router_cfg(train_min_samples=5),
        home=tmp_path,
        now=NOW,
        trainer=boom,
        base_dir=tmp_path / "base",
    )
    assert not res.ran and res.reason == "train_failed" and res.error
    state = load_train_state("ag", tmp_path)
    assert state.consecutive_failures == 1
    assert list((tmp_path / "router" / ".receipts").glob("ag-*-train_failure.json"))
