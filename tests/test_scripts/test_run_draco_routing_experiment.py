from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.provider.ensemble import (
    _member_chat_config,
    build_ensemble_provider_from_config,
)
from opensquilla.provider.selector import ProviderConfig
from opensquilla.provider.types import ChatConfig

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_draco_routing_experiment.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_draco_routing_experiment_under_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _experiment_config():
    return runner.load_draco_experiment_config(runner.DEFAULT_B2_EXPERIMENT_CONFIG_PATH).config


def _openrouter_config() -> tuple[GatewayConfig, ProviderConfig]:
    config = GatewayConfig(
        llm={
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4-pro",
            "api_key": "fake",
            "base_url": "https://openrouter.example/api/v1",
        },
        llm_ensemble={
            "enabled": True,
            "selection_mode": "static_openrouter_b5",
        },
    )
    inherited = ProviderConfig(
        provider="openrouter",
        model="deepseek/deepseek-v4-pro",
        api_key="fake",
        base_url="https://openrouter.example/api/v1",
    )
    return config, inherited


def test_b2_argument_alignment_reproduces_g12_run_envelope() -> None:
    args = runner.build_parser().parse_args(
        [
            "--input",
            "tasks.jsonl",
            "--groups",
            "B2",
            "--concurrency",
            "8",
            "--timeout",
            "180",
            "--runner-mode",
            "provider",
            "--tool-mode",
            "provider_only",
            "--local-web-search-provider",
            "duckduckgo",
        ]
    )

    record = runner.apply_b2_g12_argument_alignment(args, ["B2"])

    assert record is not None
    assert record["requested_args"]["concurrency"] == 8
    assert record["requested_args"]["timeout"] == 180.0
    assert args.concurrency == 2
    assert args.timeout == 3600.0
    assert args.ensemble_proposer_timeout == pytest.approx(907.5)
    assert args.ensemble_aggregator_timeout == pytest.approx(2662.5)
    assert args.runner_mode == "agent_loop"
    assert args.agent_max_iterations == 12
    assert args.generation_max_tokens == 16_384
    assert args.generation_max_attempts == 3
    assert args.tool_mode == "local_web_tools"
    assert args.local_web_search_provider == "brave"
    assert args.local_web_search_api_key_env == "BRAVE_SEARCH_API_KEY"
    assert args.judge_model == "google/gemini-3.1-pro-preview"
    assert args.judge_repeats == 3
    assert args.judge_concurrency == 6
    assert args.judge_max_attempts == 3


def test_generation_config_preserves_provider_native_max_level() -> None:
    policy = runner.generation_thinking_policy()

    config = runner.generation_chat_config(
        policy,
        model="moonshotai/kimi-k2.7-code",
    )

    assert config.thinking is True
    assert config.thinking_level == "max"
    assert config.thinking_budget_tokens == 50_000


def test_non_b2_groups_do_not_apply_g12_argument_alignment() -> None:
    args = runner.build_parser().parse_args(
        ["--input", "tasks.jsonl", "--groups", "B1", "--concurrency", "8"]
    )

    record = runner.apply_b2_g12_argument_alignment(args, ["B1"])

    assert record is None
    assert args.concurrency == 8
    assert not hasattr(args, "_benchmark_alignments")


def test_local_brave_runtime_allows_missing_key_only_for_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    configure_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "opensquilla.tools.builtin.web.configure_search",
        lambda **kwargs: configure_calls.append(kwargs),
    )
    config = GatewayConfig(search_api_key="")
    args = runner.build_parser().parse_args(
        [
            "--input",
            "tasks.jsonl",
            "--groups",
            "B2",
            "--tool-mode",
            "local_web_tools",
            "--local-web-search-provider",
            "brave",
            "--local-web-search-api-key-env",
            "BRAVE_SEARCH_API_KEY",
        ]
    )
    policy = runner.benchmark_tool_policy(args)

    runtime = runner.configure_local_web_search_runtime(config, policy, dry_run=True)

    assert runtime["credential_status"] == "missing_allowed_dry_run"
    assert runtime["runtime_configured"] is False
    assert runtime["api_key_configured"] is False
    assert configure_calls == []
    with pytest.raises(ValueError, match="requires an API key"):
        runner.configure_local_web_search_runtime(config, policy, dry_run=False)


def test_b2_provider_alignment_pins_effective_member_configuration() -> None:
    config, inherited = _openrouter_config()
    provider = build_ensemble_provider_from_config(
        config=config,
        inherited_provider_config=inherited,
        fallback_provider=None,
    )
    assert provider.min_successful_proposers == 3
    assert provider.quorum_grace_seconds == 30.0

    provider = runner.align_b2_provider_to_g12(provider, _experiment_config())

    assert provider.profile_name == "g12_k2_replace_gemini"
    assert [member.provider_config.model for member in provider.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert provider.aggregator.provider_config.model == "z-ai/glm-5.2"
    assert provider.min_successful_proposers == 1
    assert provider.proposer_timeout_seconds == pytest.approx(907.5)
    assert provider.aggregator_timeout_seconds == pytest.approx(2662.5)
    assert provider.quorum_grace_seconds == 0.0
    assert provider.candidate_max_chars == 24_000
    assert provider.shuffle_candidates is False
    assert provider.record_candidates is True
    assert provider.proposer_tools is False
    assert provider.aggregator_tools is True

    members = [*provider.proposers, provider.aggregator]
    assert all(member.max_tokens == 16_384 for member in members)
    assert all(member.temperature == 0.0 for member in members)
    assert all(member.k == 1 for member in members)
    assert [member.thinking for member in provider.proposers] == [
        "xhigh",
        "xhigh",
        "max",
        "xhigh",
    ]
    base = ChatConfig(max_tokens=999, temperature=0.9, thinking=False)
    effective = [_member_chat_config(base, member) for member in members]
    assert all(config.max_tokens == 16_384 for config in effective)
    assert all(config.temperature == 0.0 for config in effective)
    assert all(config.thinking is True for config in effective)
    assert [config.thinking_level for config in effective] == [
        "xhigh",
        "xhigh",
        "max",
        "xhigh",
        "xhigh",
    ]

    plan = provider.selection_plan
    assert plan["benchmark_alignment"]["id"] == "opensquilla_g12_20260630"
    assert plan["pre_alignment"]["min_successful_proposers"] == 3
    assert plan["pre_alignment"]["selection_plan"]["profile"] == "static_openrouter_b5"
    assert plan["proposer_models"] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert plan["aggregator_model"] == "z-ai/glm-5.2"
    assert plan["proposer_count"] == 4
    assert plan["proposer_sample_count"] == 4
    assert plan["selected_P"] == [
        "openrouter:deepseek/deepseek-v4-pro",
        "openrouter:z-ai/glm-5.2",
        "openrouter:moonshotai/kimi-k2.7-code",
        "openrouter:qwen/qwen3.7-max",
    ]
    assert plan["selected_A"] == "openrouter:z-ai/glm-5.2"
    assert plan["wait_for_all_proposers"] is True
    assert plan["member_generation"][2]["model"] == "moonshotai/kimi-k2.7-code"
    assert plan["member_generation"][2]["max_tokens"] == 16_384
    assert plan["member_generation"][2]["thinking"] == "max"
    assert plan["proposer_tools"] is False
    assert plan["aggregator_tools"] is True


def test_b2_provider_alignment_rebuilds_trace_after_lineup_override() -> None:
    config, inherited = _openrouter_config()
    provider = build_ensemble_provider_from_config(
        config=config,
        inherited_provider_config=inherited,
        fallback_provider=None,
    )
    experiment = runner.load_draco_experiment_config(
        runner.DEFAULT_B2_EXPERIMENT_CONFIG_PATH,
        inline_sets=[
            'ensemble.proposers.0.model="openai/gpt-5.5-pro"',
            'ensemble.proposers.0.thinking="xhigh"',
            'ensemble.aggregator.model="deepseek/deepseek-v4-pro"',
            'ensemble.aggregator.thinking="xhigh"',
        ],
    ).config

    provider = runner.align_b2_provider_to_g12(provider, experiment)

    assert provider.proposers[0].provider_config.model == "openai/gpt-5.5-pro"
    assert provider.aggregator.provider_config.model == "deepseek/deepseek-v4-pro"
    assert provider.selection_plan["proposer_models"][0] == "openai/gpt-5.5-pro"
    assert provider.selection_plan["aggregator_model"] == "deepseek/deepseek-v4-pro"
    assert provider.selection_plan["selected_P"][0] == "openrouter:openai/gpt-5.5-pro"
    assert provider.selection_plan["selected_A"] == ("openrouter:deepseek/deepseek-v4-pro")
    assert (
        provider.selection_plan["pre_alignment"]["selection_plan"]["aggregator_model"]
        == "z-ai/glm-5.2"
    )


@pytest.mark.asyncio
async def test_b2_build_skips_single_model_router_and_aligns_provider(monkeypatch) -> None:
    config, inherited = _openrouter_config()

    async def _unexpected_router(*_args, **_kwargs):
        raise AssertionError("fixed B2 must not run SquillaRouter")

    monkeypatch.setattr(runner, "run_pipeline", _unexpected_router)
    result = await runner.build_experiment_provider(
        config=config,
        inherited=inherited,
        group="B2",
        prompt="test prompt",
        dry_run=False,
        enable_proposer_tools=True,
        ensemble_proposer_timeout=1.0,
        ensemble_aggregator_timeout=2.0,
        experiment_config=_experiment_config(),
    )

    assert result.routing_trace["routing_applied"] is False
    assert result.routing_trace["routing_source"] == "fixed_g12_alignment"
    assert result.routing_trace["selection_plan"]["wait_for_all_proposers"] is True
    assert result.provider.proposer_tools is False
    assert result.provider.aggregator_tools is True
    assert result.provider.proposer_timeout_seconds == pytest.approx(907.5)
    assert result.provider.aggregator_timeout_seconds == pytest.approx(2662.5)


@pytest.mark.asyncio
async def test_b2_dry_build_records_canonical_selection_plan() -> None:
    config, inherited = _openrouter_config()

    result = await runner.build_experiment_provider(
        config=config,
        inherited=inherited,
        group="B2",
        prompt="test prompt",
        dry_run=True,
        enable_proposer_tools=True,
        ensemble_proposer_timeout=1.0,
        ensemble_aggregator_timeout=2.0,
        experiment_config=_experiment_config(),
    )

    plan = result.routing_trace["selection_plan"]
    assert plan["proposer_models"] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert plan["aggregator_model"] == "z-ai/glm-5.2"
    assert plan["selected_P"][2] == "openrouter:moonshotai/kimi-k2.7-code"
    assert plan["selected_A"] == "openrouter:z-ai/glm-5.2"
    assert plan["proposer_count"] == 4
    assert plan["proposer_sample_count"] == 4
    assert plan["member_generation"][-1]["role"] == "aggregator"
    assert plan["member_generation"][-1]["thinking"] == "xhigh"


def test_manifest_records_effective_and_requested_b2_alignment(tmp_path: Path) -> None:
    args = runner.build_parser().parse_args(
        ["--input", "tasks.jsonl", "--groups", "B2", "--concurrency", "8"]
    )
    runner.apply_b2_g12_argument_alignment(args, ["B2"])
    path = tmp_path / "manifest.json"

    runner.write_manifest(
        path,
        args=args,
        stamp="test",
        status="running",
        started_at=1.0,
        tasks=[{"id": "task-1"}],
        groups=["B2"],
        artifacts={},
        tool_policy={"tool_mode": "local_web_tools", "tools_enabled": True},
    )

    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["runner"] == "scripts/run_draco_routing_experiment.py"
    assert manifest["args"]["concurrency"] == 2
    alignment = manifest["benchmark_alignments"]["B2"]
    assert alignment["requested_args"]["concurrency"] == 8
    assert alignment["effective_args"]["concurrency"] == 2
    assert alignment["effective_config"]["ensemble"]["wait_for_all_proposers"] is True
    assert alignment["reference"]["source_commit"] == ("153e5ff267950b0e285efcdb180cea8724c0471d")


def test_experiment_config_artifacts_save_source_effective_and_resolution(
    tmp_path: Path,
) -> None:
    override_path = tmp_path / "override.json"
    override_path.write_text('{"judge":{"repeats":2}}\n', encoding="utf-8")
    args = runner.build_parser().parse_args(
        [
            "--input",
            "tasks.jsonl",
            "--groups",
            "B2",
            "--experiment-config-override",
            str(override_path),
            "--experiment-config-set",
            "runner.concurrency=4",
        ]
    )
    runner.apply_b2_g12_argument_alignment(args, ["B2"])
    args._draco_input_validation = {"status": "matched"}

    artifacts = runner.write_experiment_config_artifacts(
        tmp_path,
        args=args,
        stamp="test",
    )

    assert set(artifacts) == {
        "experiment_config_base_json",
        "experiment_config_effective_json",
        "experiment_config_override_01_json",
        "experiment_config_inline_overrides_json",
        "experiment_config_resolution_json",
    }
    effective = json.loads(
        Path(artifacts["experiment_config_effective_json"]).read_text(encoding="utf-8")
    )
    inline = json.loads(
        Path(artifacts["experiment_config_inline_overrides_json"]).read_text(encoding="utf-8")
    )
    resolution = json.loads(
        Path(artifacts["experiment_config_resolution_json"]).read_text(encoding="utf-8")
    )
    assert effective["runner"]["concurrency"] == 4
    assert effective["judge"]["repeats"] == 2
    copied_override = json.loads(
        Path(artifacts["experiment_config_override_01_json"]).read_text(encoding="utf-8")
    )
    assert copied_override == {"judge": {"repeats": 2}}
    assert inline == [{"path": "runner.concurrency", "value": 4}]
    assert resolution["input_validation"]["status"] == "matched"
    assert resolution["artifact_keys"] == sorted(artifacts)
