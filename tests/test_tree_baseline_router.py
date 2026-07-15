from __future__ import annotations

import pytest

from opensquilla.gateway.config import (
    LEGACY_OPENROUTER_MODEL_OPTIONS,
    ROUTER_TREE_BASELINE_SELECTION_MODE,
)
from opensquilla.onboarding.config_store import load_config
from opensquilla.provider.ensemble import (
    TREE_BASELINE_SELECTION_MODE as ENSEMBLE_TREE_BASELINE_SELECTION_MODE,
)
from opensquilla.provider.tree_baseline_router import (
    TREE_BASELINE_SELECTION_MODE,
    TreeBaselineError,
    load_tree_baseline_config,
    select_tree_baseline,
)


def test_tree_baseline_parameters_are_versioned_and_isolated() -> None:
    first = load_tree_baseline_config()
    second = load_tree_baseline_config()

    assert first["schema_version"] == "router-tree-baseline-config-v1"
    assert TREE_BASELINE_SELECTION_MODE == ROUTER_TREE_BASELINE_SELECTION_MODE
    assert ENSEMBLE_TREE_BASELINE_SELECTION_MODE == TREE_BASELINE_SELECTION_MODE
    assert first["algorithm_version"] == "legacy-router-dynamic-v1"
    assert first["default_model_options"] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "qwen/qwen3.7-plus",
        "deepseek/deepseek-v4-flash",
        "qwen/qwen3.7-max",
        "moonshotai/kimi-k2.6",
        "moonshotai/kimi-k2.7-code",
        "minimax/minimax-m3",
    ]
    assert first["default_model_options"] == LEGACY_OPENROUTER_MODEL_OPTIONS
    assert first["slot_templates"]["c3"] == [
        "anchor",
        "strong_critic",
        "orthogonal_family",
        "fast_sanity",
    ]
    first["scoring"]["slot_weights"]["cheap_contrast"]["quality"] = 99
    assert second["scoring"]["slot_weights"]["cheap_contrast"]["quality"] == 0.16


@pytest.mark.parametrize("selection_mode", ["router_dynamic", "router_tree_baseline"])
def test_dynamic_modes_can_be_selected_directly_from_toml(
    tmp_path,
    selection_mode: str,
) -> None:
    config_path = tmp_path / "opensquilla.toml"
    config_path.write_text(
        "[llm_ensemble]\n"
        "enabled = true\n"
        f'selection_mode = "{selection_mode}"\n',
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.llm_ensemble.enabled is True
    assert config.llm_ensemble.selection_mode == selection_mode


def test_tree_baseline_rejects_malformed_external_weight_snapshot() -> None:
    config = load_tree_baseline_config()
    config["scoring"]["slot_weights"]["cheap_contrast"]["quality"] = 0.99

    with pytest.raises(TreeBaselineError, match="must be non-negative and sum to 1"):
        select_tree_baseline(
            anchor_provider="openrouter",
            anchor_model="deepseek/deepseek-v4-flash",
            routed_tier="c0",
            routing_confidence=1.0,
            baseline_config=config,
        )


def test_tree_baseline_rejects_non_integer_role_targets() -> None:
    config = load_tree_baseline_config()
    config["scoring"]["role_match"]["cheap_contrast"]["tier_target"]["targets"] = [
        "c0"
    ]

    with pytest.raises(TreeBaselineError, match="non-empty integer list"):
        select_tree_baseline(
            anchor_provider="openrouter",
            anchor_model="deepseek/deepseek-v4-flash",
            routed_tier="c0",
            routing_confidence=1.0,
            baseline_config=config,
        )


def test_tree_baseline_rejects_unknown_config_fields() -> None:
    config = load_tree_baseline_config()
    config["scoring"]["unversioned_parameter"] = 0.5

    with pytest.raises(TreeBaselineError, match="missing or unknown fields"):
        select_tree_baseline(
            anchor_provider="openrouter",
            anchor_model="deepseek/deepseek-v4-flash",
            routed_tier="c0",
            routing_confidence=1.0,
            baseline_config=config,
        )


def test_tree_baseline_selection_is_deterministic_for_a_frozen_snapshot() -> None:
    kwargs = {
        "anchor_provider": "openrouter",
        "anchor_model": "z-ai/glm-5.2",
        "routed_tier": "c2",
        "routing_confidence": 0.82,
        "model_options": [
            "deepseek/deepseek-v4-pro",
            "z-ai/glm-5.2",
            "qwen/qwen3.7-max",
            "anthropic/claude-opus-4.8",
        ],
    }

    first = select_tree_baseline(**kwargs)
    second = select_tree_baseline(**kwargs)

    assert first.proposers == second.proposers
    assert first.aggregator == second.aggregator
    assert first.trace == second.trace
    assert first.trace["uses_remote_task_analyzer"] is False


def test_tree_baseline_uses_the_original_pool_when_options_are_omitted() -> None:
    decision = select_tree_baseline(
        anchor_provider="openrouter",
        anchor_model="routed/anchor",
        routed_tier="c1",
        routing_confidence=0.5,
    )

    assert decision.trace["model_options_source"] == "frozen_default"
    assert [
        row["model"] for row in decision.trace["candidate_pool"][1:]
    ] == load_tree_baseline_config()["default_model_options"]


@pytest.mark.parametrize(
    ("tier", "anchor", "expected_proposers", "expected_aggregator"),
    [
        (
            "c0",
            "deepseek/deepseek-v4-flash",
            ["deepseek/deepseek-v4-flash", "minimax/minimax-m3"],
            "deepseek/deepseek-v4-pro",
        ),
        (
            "c1",
            "deepseek/deepseek-v4-pro",
            ["deepseek/deepseek-v4-pro", "minimax/minimax-m3"],
            "z-ai/glm-5.2",
        ),
        (
            "c2",
            "z-ai/glm-5.2",
            [
                "z-ai/glm-5.2",
                "deepseek/deepseek-v4-pro",
                "minimax/minimax-m3",
            ],
            "moonshotai/kimi-k2.6",
        ),
        (
            "c3",
            "anthropic/claude-opus-4.8",
            [
                "anthropic/claude-opus-4.8",
                "qwen/qwen3.7-max",
                "z-ai/glm-5.2",
                "deepseek/deepseek-v4-flash",
            ],
            "minimax/minimax-m3",
        ),
    ],
)
def test_tree_baseline_frozen_default_lineups(
    tier: str,
    anchor: str,
    expected_proposers: list[str],
    expected_aggregator: str,
) -> None:
    decision = select_tree_baseline(
        anchor_provider="openrouter",
        anchor_model=anchor,
        routed_tier=tier,
        routing_confidence=0.91,
    )

    assert [selection.candidate.model for selection in decision.proposers] == (
        expected_proposers
    )
    assert decision.aggregator.candidate.model == expected_aggregator
