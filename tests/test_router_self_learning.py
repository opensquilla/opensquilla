"""Tests for the Squilla Router self-learning capture layer (M0).

Covers feature (de)serialization, the pure sample builder, the per-agent event
store, config gating, and the privacy guarantee that raw prompt text is never
persisted unless the audit sidecar is explicitly enabled.
"""

from __future__ import annotations

import numpy as np
import pytest

from opensquilla.gateway.config import RouterSelfLearningConfig, SquillaRouterConfig
from opensquilla.squilla_router.self_learning import (
    decode_features,
    encode_features,
    iter_samples,
    self_learning_disabled_by_env,
    write_sample,
)
from opensquilla.squilla_router.self_learning.capture import build_train_sample
from opensquilla.squilla_router.self_learning.store import (
    ENV_DISABLE,
    agent_data_dir,
    read_cursor,
    write_cursor,
)


def _features_meta(vec: np.ndarray, *, raw_bge: np.ndarray | None = None) -> dict:
    return {
        "routing_train_features": {
            "features_390": vec,
            "raw_bge_1536": raw_bge,
            "feature_schema_version": "deadbeefcafef00d",
        },
        "routing_train_turn_index": 3,
        "routing_extra": {
            "route_class": "R1",
            "final_route_class": "R2",
            "complaint_detected": True,
            "anti_downgrade_applied": False,
            "confidence_gate_applied": False,
            "probabilities": {"R0": 0.05, "R1": 0.6, "R2": 0.3, "R3": 0.05},
            "margin": 0.3,
        },
        "routed_tier": "c2",
        "routing_confidence": 0.6,
        "routing_source": "v4_phase3",
    }


# --------------------------------------------------------------------------- #
# Feature (de)serialization
# --------------------------------------------------------------------------- #


def test_feature_roundtrip_is_close_and_compact() -> None:
    vec = np.linspace(-3.0, 3.0, 390, dtype=np.float32)
    blob = encode_features(vec)
    back = decode_features(blob, dim=390)
    assert back.dtype == np.float32
    # float16 storage is lossy but adequate for tree/MLP inputs.
    assert np.allclose(vec, back, atol=1e-2)
    # 390 float16 = 780 bytes -> base64 ~1040 chars; far smaller than text JSON.
    assert len(blob) < 1100


def test_decode_rejects_wrong_dim() -> None:
    with pytest.raises(ValueError):
        decode_features(encode_features(np.zeros(10, dtype=np.float32)), dim=390)


# --------------------------------------------------------------------------- #
# Pure sample builder
# --------------------------------------------------------------------------- #


def test_build_sample_extracts_decision_and_flags() -> None:
    vec = np.arange(390, dtype=np.float32)
    sample = build_train_sample(session_key="s1", metadata=_features_meta(vec), message="hello")
    assert sample is not None
    assert sample.session_key == "s1"
    assert sample.turn_index == 3
    assert sample.routed_tier == "c2"
    assert sample.route_class == "R1"
    assert sample.final_route_class == "R2"
    assert sample.complaint_detected is True
    assert sample.probabilities == [0.05, 0.6, 0.3, 0.05]
    assert sample.raw_bge_1536_b64 is None
    np.testing.assert_allclose(decode_features(sample.features_390_b64, 390), vec, atol=1e-2)


def test_build_sample_returns_none_without_features() -> None:
    assert build_train_sample(session_key="s", metadata={"routing_source": "v4_phase3"}) is None


def test_build_sample_skips_image_route_bypass() -> None:
    vec = np.zeros(390, dtype=np.float32)
    meta = _features_meta(vec)
    meta["routing_source"] = "image_route"
    assert build_train_sample(session_key="s", metadata=meta) is None


def test_build_sample_captures_raw_bge_when_present() -> None:
    vec = np.zeros(390, dtype=np.float32)
    raw = np.ones(1536, dtype=np.float32)
    sample = build_train_sample(session_key="s", metadata=_features_meta(vec, raw_bge=raw))
    assert sample is not None and sample.raw_bge_1536_b64 is not None
    np.testing.assert_allclose(decode_features(sample.raw_bge_1536_b64, 1536), raw, atol=1e-2)


# --------------------------------------------------------------------------- #
# Privacy
# --------------------------------------------------------------------------- #


def test_audit_summary_off_by_default() -> None:
    vec = np.zeros(390, dtype=np.float32)
    sample = build_train_sample(
        session_key="s", metadata=_features_meta(vec), message="secret task text"
    )
    assert sample is not None and sample.audit_summary is None


def test_audit_summary_opt_in_is_redacted() -> None:
    vec = np.zeros(390, dtype=np.float32)
    sample = build_train_sample(
        session_key="s",
        metadata=_features_meta(vec),
        store_audit_summary=True,
        message="email me at a@b.com and visit https://x.com",
    )
    assert sample is not None and sample.audit_summary is not None
    assert "a@b.com" not in sample.audit_summary
    assert "https://x.com" not in sample.audit_summary


def test_written_file_contains_no_raw_prompt_text(tmp_path) -> None:
    vec = np.arange(390, dtype=np.float32)
    secret = "DELETE FROM prod WHERE 1=1 -- highly sensitive"
    sample = build_train_sample(session_key="s", metadata=_features_meta(vec), message=secret)
    assert sample is not None
    path = write_sample(sample, "agentA", home=tmp_path)
    assert secret not in path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Event store
# --------------------------------------------------------------------------- #


def test_write_and_iter_roundtrip(tmp_path) -> None:
    vec = np.zeros(390, dtype=np.float32)
    for _ in range(3):
        sample = build_train_sample(session_key="s", metadata=_features_meta(vec))
        assert sample is not None
        write_sample(sample, "agentB", home=tmp_path)
    rows = list(iter_samples("agentB", home=tmp_path))
    assert len(rows) == 3
    assert all(r.routed_tier == "c2" for r in rows)


def test_iter_since_ts_filters(tmp_path) -> None:
    vec = np.zeros(390, dtype=np.float32)
    sample = build_train_sample(session_key="s", metadata=_features_meta(vec))
    assert sample is not None
    sample.ts = "2026-01-01T00:00:00Z"
    write_sample(sample, "agentC", home=tmp_path)
    assert list(iter_samples("agentC", since_ts="2026-06-01T00:00:00Z", home=tmp_path)) == []
    assert len(list(iter_samples("agentC", since_ts="2025-01-01T00:00:00Z", home=tmp_path))) == 1


def test_agent_id_is_sanitized_for_filesystem(tmp_path) -> None:
    data_root = (tmp_path / "router" / "data").resolve()
    # Separators are stripped, so the result stays a single segment under the
    # data root (no traversal), regardless of how hostile the agent id is.
    for weird in ("../../etc/passwd", "..", ".", "a/b/c", "", "  ../x  "):
        d = agent_data_dir(weird, home=tmp_path)
        assert d.parent == tmp_path / "router" / "data"
        assert data_root in d.resolve().parents or d.resolve().parent == data_root


def test_cursor_read_write(tmp_path) -> None:
    assert read_cursor("agentD", home=tmp_path) is None
    write_cursor("agentD", "2026-06-06T00:00:00Z", home=tmp_path)
    assert read_cursor("agentD", home=tmp_path) == "2026-06-06T00:00:00Z"


def test_iter_skips_malformed_lines(tmp_path) -> None:
    data_dir = agent_data_dir("agentE", home=tmp_path)
    data_dir.mkdir(parents=True)
    (data_dir / "samples-20260606.jsonl").write_text("not json\n{bad\n", encoding="utf-8")
    assert list(iter_samples("agentE", home=tmp_path)) == []


# --------------------------------------------------------------------------- #
# Config gating
# --------------------------------------------------------------------------- #


def test_capture_disabled_by_default() -> None:
    cfg = SquillaRouterConfig()
    assert cfg.self_learning.enabled is False
    assert cfg.self_learning.capture_enabled is True  # sub-toggle on, but master off


def test_capture_flags_helper() -> None:
    from opensquilla.engine.steps.squilla_router import _capture_flags

    assert _capture_flags(SquillaRouterConfig()) == (False, False)
    on = SquillaRouterConfig(self_learning=RouterSelfLearningConfig(enabled=True))
    assert _capture_flags(on) == (True, False)
    mlp = SquillaRouterConfig(
        self_learning=RouterSelfLearningConfig(enabled=True, enable_mlp=True)
    )
    assert _capture_flags(mlp) == (True, True)
    paused = SquillaRouterConfig(
        self_learning=RouterSelfLearningConfig(enabled=True, capture_enabled=False)
    )
    assert _capture_flags(paused) == (False, False)


def test_env_kill_switch(monkeypatch) -> None:
    monkeypatch.delenv(ENV_DISABLE, raising=False)
    assert self_learning_disabled_by_env() is False
    monkeypatch.setenv(ENV_DISABLE, "1")
    assert self_learning_disabled_by_env() is True
    monkeypatch.setenv(ENV_DISABLE, "false")
    assert self_learning_disabled_by_env() is False


# --------------------------------------------------------------------------- #
# Transport: inference result -> strategy extra -> router step metadata
# (deterministic; does not require the LFS-backed model binaries)
# --------------------------------------------------------------------------- #


def _fake_inference_result(*, with_features: bool):
    from types import SimpleNamespace

    decision = SimpleNamespace(
        route_class="R2",
        margin=0.4,
        difficulty_score=0.7,
        thinking_mode="T2",
        prompt_policy="P1",
        flags={},
        aux_downgrade_applied=False,
        sticky_applied=False,
        selected_model="m",
    )
    intermediates: dict = {"bge_channels_used": [], "asst_signal_present": False}
    if with_features:
        intermediates["features_390"] = np.arange(390, dtype=np.float32)
        intermediates["raw_bge_1536"] = np.zeros(1536, dtype=np.float32)
    return SimpleNamespace(
        decision=decision,
        probabilities={"R0": 0.1, "R1": 0.2, "R2": 0.6, "R3": 0.1},
        aux_decision_probs=None,
        intermediates=intermediates,
    )


def test_map_result_surfaces_features_under_private_key() -> None:
    from opensquilla.squilla_router.v4_phase3 import V4Phase3Strategy

    strat = V4Phase3Strategy(bundle_dir="/nonexistent-bundle")  # init fails -> unavailable
    strat._feature_schema_version = "schemaX"
    _, _, _, extra = strat._map_result(
        _fake_inference_result(with_features=True), ["c0", "c1", "c2", "c3"], "msg"
    )
    tf = extra.get("_train_features")
    assert tf is not None
    assert np.asarray(tf["features_390"]).shape == (390,)
    assert np.asarray(tf["raw_bge_1536"]).shape == (1536,)
    assert tf["feature_schema_version"] == "schemaX"


def test_map_result_omits_features_when_not_emitted() -> None:
    from opensquilla.squilla_router.v4_phase3 import V4Phase3Strategy

    strat = V4Phase3Strategy(bundle_dir="/nonexistent-bundle")
    _, _, _, extra = strat._map_result(
        _fake_inference_result(with_features=False), ["c0", "c1", "c2", "c3"], "msg"
    )
    assert "_train_features" not in extra


class _FeatureFakeStrategy:
    """Minimal history-aware strategy returning captured features in extra."""

    requires_history = True
    source = "v4_phase3"

    async def classify(self, message, valid_tiers, routing_history=None, **kwargs):
        extra = {
            "route_class": "R2",
            "final_route_class": "R2",
            "thinking_mode": "T2",
            "prompt_policy": "P1",
            "probabilities": {"R0": 0.1, "R1": 0.2, "R2": 0.6, "R3": 0.1},
            "margin": 0.4,
            "_train_features": {
                "features_390": np.arange(390, dtype=np.float32),
                "raw_bge_1536": None,
                "feature_schema_version": "schemaY",
            },
        }
        return "c2", 0.6, "v4_phase3", extra


@pytest.mark.asyncio
async def test_router_step_pops_features_out_of_routing_extra(monkeypatch) -> None:
    from opensquilla.engine.pipeline import TurnContext
    from opensquilla.engine.steps import squilla_router as step
    from opensquilla.gateway.config import GatewayConfig

    monkeypatch.setattr(step, "_get_strategy", lambda _config: _FeatureFakeStrategy())
    config = GatewayConfig()
    ctx = TurnContext(
        message="compare postgres and mysql locking",
        session_key="sess-pop",
        config=config,
        provider=None,
        model=config.llm.model,
        tool_defs=[],
        system_prompt="system",
    )
    out = await step.apply_squilla_router(ctx)
    # Features moved to their own slot; routing_extra (logged/historized) is clean.
    assert "routing_train_features" in out.metadata
    assert out.metadata["routing_train_features"]["feature_schema_version"] == "schemaY"
    assert "_train_features" not in out.metadata.get("routing_extra", {})
    sample = build_train_sample(session_key="sess-pop", metadata=out.metadata)
    assert sample is not None and sample.routed_tier == "c2"
