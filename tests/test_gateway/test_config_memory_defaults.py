from __future__ import annotations

import pytest
from pydantic import ValidationError

from opensquilla.gateway.config import GatewayConfig


def test_memory_core_defaults_keep_single_stable_path() -> None:
    config = GatewayConfig()

    assert config.memory.embedding.provider == "auto"
    assert config.memory.embedding.mode is None
    assert config.memory.embedding.requested_provider == "auto"
    toml_dict = config.to_toml_dict()
    assert toml_dict["memory"]["embedding"]["provider"] == "auto"
    assert "mode" not in toml_dict["memory"]["embedding"]
    assert config.memory.cost.query_embedding_cache == "on"
    assert config.memory.dream.enabled is False
    assert config.memory.dream.preview_mode is True
    assert config.memory.dream.auto_schedule is False
    assert not hasattr(config.memory.dream, "evidence_" + "enabled")
    assert config.memory.capture_mode == "turn_pair"
    assert config.memory_mode_fingerprint()["mode"] == "stable"
    assert "derived_cache" not in config.memory_mode_fingerprint()


@pytest.mark.parametrize(
    "payload",
    [
        {"profile": "legacy"},
        {"recall_frequency": "always"},
        {"prefetch_enabled": True},
        {"prefetch_max_results": 3},
        {"prefetch_min_score": 0.3},
        {"cost": {"embedding_cache": True}},
        {"cost": {"derived_cache": "shadow"}},
        {"cost": {"facts_lane": "shadow"}},
        {"cost": {"cheap_model_lane": "shadow"}},
        {"cost": {"fact_links_lane": "shadow"}},
        {"cost": {"temporal_events_lane": "shadow"}},
        {"cost": {"multi_hop_recall": "shadow"}},
    ],
)
def test_rejected_memory_lanes_are_not_configurable(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GatewayConfig(memory=payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"capture_mode": "archive_turn_pair"},
        {"index_captured_turns": True},
    ],
)
def test_legacy_turn_archive_controls_are_not_configurable(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GatewayConfig(memory=payload)
