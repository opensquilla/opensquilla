from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from opensquilla.eval.draco_experiment_config import (
    load_draco_experiment_config,
    validate_reference_input,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs/benchmarks/draco_b2_g12.json"


def test_default_b2_config_pins_g12_highest_thinking_and_tool_permissions() -> None:
    config = load_draco_experiment_config(DEFAULT_CONFIG).config

    assert config.reference.source_commit == ("153e5ff267950b0e285efcdb180cea8724c0471d")
    assert config.reference.group == "G12"
    assert config.reference.profile == "g12_k2_replace_gemini"
    assert config.benchmark_input.sha256 == (
        "1eb4e618c8df8e7f68bded3d2b6f77a541744aa1072eb338835b776183188a8d"
    )
    assert config.benchmark_input.task_count == 10
    assert config.routing.selection_mode == "static_openrouter_b5"
    assert config.routing.skip_single_model_router is True
    assert [member.model for member in config.ensemble.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert config.ensemble.aggregator.model == "z-ai/glm-5.2"
    assert [member.thinking for member in config.ensemble.proposers] == [
        "xhigh",
        "xhigh",
        "max",
        "xhigh",
    ]
    assert config.ensemble.aggregator.thinking == "xhigh"
    assert config.generation.require_highest_thinking is True
    assert config.generation.thinking_budget_tokens == 50_000
    assert config.generation.model_thinking_levels == {
        "anthropic/claude-fable-5": "max",
        "anthropic/claude-opus-4.8": "max",
        "deepseek/deepseek-v4-pro": "xhigh",
        "google/gemini-3.1-pro-preview": "high",
        "moonshotai/kimi-k2.7-code": "max",
        "openai/gpt-5.5-pro": "xhigh",
        "openai/gpt-5.6-sol": "max",
        "qwen/qwen3.7-max": "xhigh",
        "sakana/fugu-ultra": "max",
        "z-ai/glm-5.2": "xhigh",
    }
    assert all(member.max_tokens == 16_384 for member in config.ensemble.proposers)
    assert all(member.temperature == 0.0 for member in config.ensemble.proposers)
    assert config.ensemble.aggregator.max_tokens == 16_384
    assert config.ensemble.aggregator.temperature == 0.0
    assert config.ensemble.min_successful_proposers == 1
    assert config.ensemble.all_failed_policy == "fallback_single"
    assert config.ensemble.candidate_max_chars == 24_000
    assert config.ensemble.shuffle_candidates is False
    assert config.ensemble.record_candidates is True
    assert config.ensemble.proposer_tools is False
    assert config.ensemble.aggregator_tools is True
    assert config.ensemble.wait_for_all_proposers is True
    assert config.ensemble.quorum_grace_seconds == 0.0
    assert config.tools.web_search.provider == "brave"
    assert config.tools.web_search.max_results == 5
    assert config.tools.web_fetch.max_content_tokens == 50_000
    assert config.timeouts.proposer_seconds == pytest.approx(907.5)
    assert config.timeouts.aggregator_seconds == pytest.approx(2662.5)
    assert config.timeouts.task_seconds == 3600.0
    assert config.timeouts.task_margin_seconds == 30.0
    assert config.runner.mode == "agent_loop"
    assert config.runner.agent_max_iterations == 12
    assert config.runner.concurrency == 2
    assert config.generation.max_attempts == 3
    assert config.generation.retry_backoff_seconds == 2.0
    assert config.judge.model == "google/gemini-3.1-pro-preview"
    assert config.judge.repeats == 3
    assert config.judge.concurrency == 6
    assert config.judge.max_attempts == 3


def test_override_files_and_inline_paths_apply_in_documented_order(tmp_path: Path) -> None:
    override_path = tmp_path / "override.json"
    override_path.write_text(
        json.dumps(
            {
                "runner": {"concurrency": 3},
                "ensemble": {"candidate_max_chars": 32000},
            }
        ),
        encoding="utf-8",
    )

    bundle = load_draco_experiment_config(
        DEFAULT_CONFIG,
        override_paths=[override_path],
        inline_sets=[
            "runner.concurrency=4",
            "ensemble.proposers.0.max_tokens=8192",
        ],
    )

    assert bundle.config.runner.concurrency == 4
    assert bundle.config.ensemble.candidate_max_chars == 32_000
    assert bundle.config.ensemble.proposers[0].max_tokens == 8192
    assert bundle.provenance()["overrides"][0]["path"] == str(override_path.resolve())


def test_unknown_override_path_fails_instead_of_silently_missing() -> None:
    with pytest.raises(ValueError, match="unknown experiment config override path"):
        load_draco_experiment_config(
            DEFAULT_CONFIG,
            inline_sets=["ensemble.typo_timeout=12"],
        )


def test_highest_thinking_invariant_rejects_accidental_downgrade() -> None:
    with pytest.raises(ValidationError, match="highest configured setting"):
        load_draco_experiment_config(
            DEFAULT_CONFIG,
            inline_sets=["ensemble.proposers.2.thinking=high"],
        )


def test_aggregator_rejects_unsupported_multiple_samples() -> None:
    with pytest.raises(ValidationError, match="ensemble.aggregator.k must be 1"):
        load_draco_experiment_config(
            DEFAULT_CONFIG,
            inline_sets=["ensemble.aggregator.k=2"],
        )


def test_reference_input_validation_checks_bytes_count_ids_and_order(tmp_path: Path) -> None:
    path = tmp_path / "mini.jsonl"
    path.write_text('{"id":"task-a","prompt":"hello"}\n', encoding="utf-8")
    default = load_draco_experiment_config(DEFAULT_CONFIG).config.benchmark_input
    input_config = default.model_copy(
        update={
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "task_count": 1,
            "task_ids": ["task-a"],
        }
    )

    trace = validate_reference_input(
        path,
        task_ids=["task-a"],
        config=input_config,
    )

    assert trace["status"] == "matched"
    with pytest.raises(ValueError, match="task_ids_or_order"):
        validate_reference_input(path, task_ids=["task-b"], config=input_config)
