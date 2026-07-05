"""On-device router calibration: aggregation, clamps, I/O, and policy parity.

All records are synthetic dummy data built in-test — never real state. The pure
:func:`aggregate_calibration` is exercised with an injected clock so every
assertion is deterministic. The policy paired-run proves the default
(``None``)/neutral calibration path is byte-identical to today's confidence
gate; the routing parity golden (``test_routing_policy_parity.py``) pins the
same guarantee end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from opensquilla.engine.routing import (
    ConfidenceGateResult,
    confidence_gate,
)
from opensquilla.engine.routing.calibration import (
    BIAS_CLAMP,
    THRESHOLD_ADJUST_CLAMP,
    THRESHOLD_CEIL,
    THRESHOLD_FLOOR,
    CalibrationState,
    aggregate_calibration,
    apply_bias,
    calibration_path,
    effective_threshold,
    load_calibration,
    save_calibration,
)

_NOW_MS = 1_700_000_000_000
_DAY_MS = 24 * 60 * 60 * 1000


def _record(
    proposed_tier: str,
    *,
    gated: bool = False,
    complained: bool = False,
    pinned: bool = False,
    ts_ms: int = _NOW_MS,
    decision_id: str = "d",
) -> dict[str, Any]:
    trail: list[dict[str, Any]] = []
    if gated:
        trail.append({"stage": "confidence_gate", "applied": True})
    if complained:
        trail.append({"stage": "complaint_upgrade", "applied": True})
    return {
        "decision_id": decision_id,
        "proposed_tier": proposed_tier,
        "final_tier": proposed_tier,
        "source": "router_control_hold" if pinned else "v4_phase3",
        "flags": [],
        "trail": trail,
        "ts_ms": ts_ms,
    }


def _many(count: int, **kwargs: Any) -> list[dict[str, Any]]:
    return [_record(decision_id=f"d{i}", **kwargs) for i in range(count)]


# ---------------------------------------------------------------------------
# Deterministic aggregation
# ---------------------------------------------------------------------------


def test_aggregate_empty_is_neutral() -> None:
    state = aggregate_calibration([], now=_NOW_MS)
    assert state.is_neutral()
    assert state.sample_count == 0
    assert state.per_class_bias == {}
    assert state.threshold_adjust == 0.0
    assert state.generated_at_ms == _NOW_MS


def test_clean_gate_downgrades_bias_tier_down_and_raise_threshold() -> None:
    # 30 clean downgrades of c2: bias c2 down, push the threshold up.
    state = aggregate_calibration(_many(30, proposed_tier="c2", gated=True), now=_NOW_MS)
    assert state.sample_count == 30
    # 0.15 * (-30) / max(30, 20=min) -> -0.15 (hits the clamp exactly).
    assert state.per_class_bias == {"c2": -0.15}
    # 0.20 * 30 / max(30, 50=min) -> +0.12.
    assert state.threshold_adjust == 0.12


def test_false_downgrade_biases_tier_up_and_lowers_threshold() -> None:
    # 40 gate downgrades that were then complained about: trust c1 more.
    state = aggregate_calibration(
        _many(40, proposed_tier="c1", gated=True, complained=True), now=_NOW_MS
    )
    assert state.sample_count == 40
    assert state.per_class_bias == {"c1": 0.15}  # 0.15 * 40 / 40 clamped
    assert state.threshold_adjust == -0.16  # 0.20 * -40 / max(40,50)


def test_pins_lower_threshold_without_per_class_bias() -> None:
    state = aggregate_calibration(_many(50, proposed_tier="c3", pinned=True), now=_NOW_MS)
    assert state.sample_count == 50
    assert state.per_class_bias == {}  # pins carry no per-class gate signal
    assert state.threshold_adjust == -0.20  # 0.20 * -50 / 50


def test_aggregation_is_deterministic() -> None:
    records = (
        _many(12, proposed_tier="c2", gated=True)
        + _many(8, proposed_tier="c1", gated=True, complained=True)
        + _many(5, proposed_tier="c3", pinned=True)
    )
    first = aggregate_calibration(records, now=_NOW_MS)
    second = aggregate_calibration(list(reversed(records)), now=_NOW_MS)
    assert first == second


def test_records_outside_window_are_ignored() -> None:
    fresh = _many(10, proposed_tier="c2", gated=True, ts_ms=_NOW_MS)
    stale = _many(10, proposed_tier="c2", gated=True, ts_ms=_NOW_MS - 31 * _DAY_MS)
    state = aggregate_calibration(fresh + stale, now=_NOW_MS)
    assert state.sample_count == 10


def test_unknown_proposed_tier_does_not_contribute() -> None:
    state = aggregate_calibration(
        _many(5, proposed_tier="zz_unknown", gated=True), now=_NOW_MS
    )
    assert state.sample_count == 0
    assert state.is_neutral()


def test_prior_is_blended_fifty_fifty() -> None:
    # 25 clean c2 downgrades -> computed {c2: -0.15}, threshold +0.10.
    records = _many(25, proposed_tier="c2", gated=True)
    prior = CalibrationState(
        per_class_bias={"c2": 0.05, "c1": 0.10}, threshold_adjust=-0.04
    )
    state = aggregate_calibration(records, now=_NOW_MS, prior=prior)
    assert state.per_class_bias == {"c2": -0.05, "c1": 0.05}
    assert state.threshold_adjust == 0.03  # 0.5*-0.04 + 0.5*0.10
    assert state.sample_count == 25  # the fresh sample count, not the prior's


# ---------------------------------------------------------------------------
# Clamp property tests (adversarial inputs)
# ---------------------------------------------------------------------------

_ADVERSARIAL_BIASES = [0.0, 0.15, -0.15, 0.1499, 1.0, -1.0, 42.0, -42.0, 1e9, -1e9]
_ADVERSARIAL_THRESHOLDS = [0.0, 0.2, -0.2, 0.5, -0.5, 5.0, -5.0, 1e6, -1e6]
_BASES = [0.0, 0.3, 0.5, 0.7, 1.0, -1.0, 2.0]
_CONFIDENCES = [0.0, 0.25, 0.5, 0.75, 1.0]
_TIERS = ["c0", "c1", "c2", "c3"]


def test_effective_threshold_always_within_hard_band() -> None:
    for base in _BASES:
        for adjust in _ADVERSARIAL_THRESHOLDS:
            state = CalibrationState(threshold_adjust=adjust)
            result = effective_threshold(base, state)
            assert THRESHOLD_FLOOR <= result <= THRESHOLD_CEIL


def test_effective_threshold_none_is_identity() -> None:
    for base in _BASES:
        assert effective_threshold(base, None) == base


def test_apply_bias_effect_never_exceeds_clamp() -> None:
    for tier in _TIERS:
        for bias in _ADVERSARIAL_BIASES:
            state = CalibrationState(per_class_bias={tier: bias})
            for conf in _CONFIDENCES:
                biased = apply_bias(conf, tier, state)
                assert 0.0 <= biased <= 1.0
                assert abs(biased - conf) <= BIAS_CLAMP + 1e-9


def test_apply_bias_none_is_identity() -> None:
    for tier in _TIERS:
        for conf in _CONFIDENCES:
            assert apply_bias(conf, tier, None) == conf


def test_from_dict_clamps_adversarial_file() -> None:
    state = CalibrationState.from_dict(
        {
            "per_class_bias": {"c2": 99.0, "c1": -99.0, "bogus": 0.1, "c3": float("nan")},
            "threshold_adjust": 99.0,
            "sample_count": -5,
        }
    )
    assert state.per_class_bias == {"c2": BIAS_CLAMP, "c1": -BIAS_CLAMP}
    assert state.threshold_adjust == THRESHOLD_ADJUST_CLAMP
    assert state.sample_count == 0  # negative rejected


def test_aggregate_never_exceeds_clamps_on_extreme_counts() -> None:
    records = (
        _many(5000, proposed_tier="c2", gated=True, complained=True)
        + _many(5000, proposed_tier="c0", gated=True)
    )
    state = aggregate_calibration(records, now=_NOW_MS)
    for value in state.per_class_bias.values():
        assert abs(value) <= BIAS_CLAMP
    assert abs(state.threshold_adjust) <= THRESHOLD_ADJUST_CLAMP


# ---------------------------------------------------------------------------
# Load / save (atomic; tolerate missing/corrupt)
# ---------------------------------------------------------------------------


def test_load_missing_file_is_neutral(tmp_path: Path) -> None:
    assert load_calibration(tmp_path / "nope.json").is_neutral()


def test_load_corrupt_file_is_neutral(tmp_path: Path) -> None:
    bad = tmp_path / "router_calibration.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    assert load_calibration(bad).is_neutral()

    bad.write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, wrong shape
    assert load_calibration(bad).is_neutral()


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "router_calibration.json"
    state = CalibrationState(
        per_class_bias={"c2": -0.1, "c0": 0.05},
        threshold_adjust=0.08,
        sample_count=123,
        generated_at_ms=_NOW_MS,
    )
    written = save_calibration(state, target)
    assert written == target
    loaded = load_calibration(target)
    assert loaded.per_class_bias == {"c2": -0.1, "c0": 0.05}
    assert loaded.threshold_adjust == 0.08
    assert loaded.sample_count == 123


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "router_calibration.json"
    save_calibration(CalibrationState(threshold_adjust=0.1), target)
    save_calibration(CalibrationState(threshold_adjust=-0.1), target)  # overwrite
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["threshold_adjust"] == -0.1
    # No leftover ".router_calibration.*.tmp" files in the directory.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == []


def test_calibration_path_honors_state_dir(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path))
    path = calibration_path()
    assert path == tmp_path / "state" / "router_calibration.json"


# ---------------------------------------------------------------------------
# Policy paired-run: neutral/None == today's confidence gate
# ---------------------------------------------------------------------------


def _router_cfg(**overrides: Any) -> SimpleNamespace:
    knobs: dict[str, Any] = {
        "default_tier": "c1",
        "confidence_threshold": 0.5,
        "confidence_high_tier_margin": 0.05,
    }
    knobs.update(overrides)
    return SimpleNamespace(**knobs)


_VALID = ["c0", "c1", "c2", "c3"]
_TIERS_CFG = {t: {"model": f"m-{t}"} for t in _VALID}


def test_confidence_gate_none_equals_neutral_equals_default() -> None:
    neutral = CalibrationState.neutral()
    for tier in _VALID + ["image_model"]:
        for conf in [0.0, 0.3, 0.44, 0.45, 0.5, 0.6, 0.9, 1.0]:
            for default_tier in ["c1", "c0", None]:
                for margin in [0.05, 0.0, 0.1]:
                    cfg = _router_cfg(default_tier=default_tier, confidence_high_tier_margin=margin)
                    tiers = {
                        **_TIERS_CFG,
                        "image_model": {"model": "m-img", "image_only": True},
                    }
                    baseline = confidence_gate(
                        tier, confidence=conf, router_cfg=cfg, valid_tiers=_VALID, tiers=tiers
                    )
                    with_none = confidence_gate(
                        tier,
                        confidence=conf,
                        router_cfg=cfg,
                        valid_tiers=_VALID,
                        tiers=tiers,
                        calibration=None,
                    )
                    with_neutral = confidence_gate(
                        tier,
                        confidence=conf,
                        router_cfg=cfg,
                        valid_tiers=_VALID,
                        tiers=tiers,
                        calibration=neutral,
                    )
                    assert isinstance(baseline, ConfidenceGateResult)
                    assert with_none == baseline
                    assert with_neutral == baseline


def test_non_neutral_bias_can_flip_the_gate() -> None:
    cfg = _router_cfg()
    # c2 at 0.50 with threshold 0.50 is KEPT today (0.50 < 0.50 is False).
    kept = confidence_gate(
        "c2", confidence=0.50, router_cfg=cfg, valid_tiers=_VALID, tiers=_TIERS_CFG
    )
    assert kept.applied is False and kept.tier == "c2"
    # A -0.15 bias on c2 drops effective confidence to 0.35 -> downgraded.
    biased_state = CalibrationState(per_class_bias={"c2": -0.15})
    biased = confidence_gate(
        "c2",
        confidence=0.50,
        router_cfg=cfg,
        valid_tiers=_VALID,
        tiers=_TIERS_CFG,
        calibration=biased_state,
    )
    assert biased.applied is True and biased.tier == "c1"


def test_non_neutral_threshold_adjust_shifts_cutoff() -> None:
    cfg = _router_cfg(confidence_high_tier_margin=0.0)
    # c2 at 0.60, threshold 0.50 -> kept today.
    kept = confidence_gate(
        "c2", confidence=0.60, router_cfg=cfg, valid_tiers=_VALID, tiers=_TIERS_CFG
    )
    assert kept.applied is False
    # +0.15 threshold adjust -> effective 0.65 > 0.60 -> downgraded.
    raised = CalibrationState(threshold_adjust=0.15)
    gated = confidence_gate(
        "c2",
        confidence=0.60,
        router_cfg=cfg,
        valid_tiers=_VALID,
        tiers=_TIERS_CFG,
        calibration=raised,
    )
    assert gated.applied is True
    assert gated.threshold == 0.65
