from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest

from opensquilla.engine.types import ThinkingLevel
from opensquilla.gateway.config import GatewayConfig
from opensquilla.provider.ensemble import (
    _member_chat_config,
    build_ensemble_provider_from_config,
)
from opensquilla.provider.selector import ProviderConfig
from opensquilla.provider.types import ChatConfig, DoneEvent
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.sandbox.run_context import PublicNetworkGrant, RunContext
from opensquilla.sandbox.run_mode import RunMode
from opensquilla.tool_boundary import ToolCall
from opensquilla.tools.types import current_tool_context

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_draco_routing_experiment.py"
RESUME_SCRIPT_PATH = SCRIPT_PATH.with_name("run_draco_routing_experiment_resume.py")
ROOT = SCRIPT_PATH.parent.parent


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


def _openrouter_exact_evidence(cost: float, response_id: str) -> dict[str, object]:
    return {
        "is_byok": False,
        "provider_reported_cost": cost,
        "response_ids": [response_id],
        "router_metadata": {"is_byok": False},
    }


def _load_resume_runner():
    spec = importlib.util.spec_from_file_location(
        "run_draco_routing_experiment_resume_under_test",
        RESUME_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


resume_runner = _load_resume_runner()


@pytest.fixture
def configured_tool_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Exercise web-tool behavior through a granted Standard sandbox context."""

    configure_runtime(
        SandboxSettings(),
        approval_queue=runner._BenchmarkApprovalQueue(),
        workspace=tmp_path,
    )
    original_builder = runner.build_benchmark_tool_context

    def _standard_context(**kwargs):
        context = original_builder(**kwargs)
        context.run_mode = RunMode.STANDARD.value
        context.sandbox_run_context = RunContext(
            run_mode=RunMode.STANDARD,
            workspace=str(tmp_path),
            public_network=(PublicNetworkGrant(scope="chat", source="test"),),
            source="test_standard_network_grant",
        )
        return context

    monkeypatch.setattr(runner, "build_benchmark_tool_context", _standard_context)
    try:
        yield
    finally:
        reset_runtime()


@pytest.mark.asyncio
async def test_judge_concurrency_is_capped_across_concurrent_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    peak = 0

    async def fake_judge_criterion(*, criterion, repeat_index, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {
            **criterion,
            "repeat_index": repeat_index,
            "verdict": "MET",
            "met": True,
            "rationale": "ok",
        }

    monkeypatch.setattr(runner, "judge_criterion", fake_judge_criterion)
    task = {
        "id": "task-1",
        "prompt": "prompt",
        "rubric": {
            "id": "rubric-1",
            "sections": [
                {
                    "id": "section-1",
                    "title": "Section",
                    "criteria": [
                        {"id": f"criterion-{index}", "weight": 1, "requirement": "x"}
                        for index in range(3)
                    ],
                }
            ],
        },
    }
    shared = asyncio.Semaphore(2)
    await asyncio.gather(
        *[
            runner.judge_text(
                judge_provider=object(),
                task=task,
                answer="answer",
                dry_run=False,
                judge_repeats=1,
                judge_concurrency=6,
                judge_semaphore=shared,
            )
            for _ in range(2)
        ]
    )

    assert peak == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module",
    [runner, _load_resume_runner()],
    ids=["main", "resume"],
)
async def test_legacy_judge_uses_the_experiment_wide_semaphore(
    module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    peak = 0

    async def fake_collect_run(*_args, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return module.RunResult(
            final_text=json.dumps(
                {
                    "scores": {
                        "accuracy": 5,
                        "completeness": 5,
                        "objectivity": 5,
                        "citation": 5,
                    },
                    "total": 20,
                    "rationale": "ok",
                }
            ),
            done=None,
        )

    monkeypatch.setattr(module, "collect_run", fake_collect_run)
    shared = asyncio.Semaphore(2)
    task = {"id": "task-1", "prompt": "prompt", "rubric": "legacy rubric"}
    await asyncio.gather(
        *[
            module.judge_text(
                judge_provider=object(),
                task=task,
                answer="answer",
                dry_run=False,
                judge_concurrency=8,
                judge_semaphore=shared,
            )
            for _ in range(5)
        ]
    )

    assert peak == 2


def _experiment_config():
    return runner.load_draco_experiment_config(runner.DEFAULT_B2_EXPERIMENT_CONFIG_PATH).config


def test_reasoning_tokens_are_not_double_counted_as_total_tokens() -> None:
    usage = {
        "input_tokens": 50,
        "output_tokens": 100,
        "reasoning_tokens": 80,
    }

    assert runner._usage_token_count(usage) == 150
    assert _load_resume_runner()._usage_token_count(usage) == 150


@pytest.mark.parametrize("module", [runner, _load_resume_runner()], ids=["main", "resume"])
def test_task_analyzer_provider_preserves_routing_and_disables_replay(
    module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    class _Selector:
        def __init__(self, config) -> None:
            captured["primary"] = config.primary

        def resolve(self):
            return sentinel

    monkeypatch.setattr(module, "ModelSelector", _Selector)
    routed = ProviderConfig(
        provider="openrouter",
        model="original",
        api_key="fake",
        base_url="https://openrouter.example/api/v1",
        provider_routing={"order": ["OpenAI"], "allow_fallbacks": False},
        replay_provider_state=True,
    )

    resolved = module.build_task_analyzer_provider(
        routed,
        provider_id="openrouter",
        model_id="openai/gpt-analyzer",
    )
    primary = captured["primary"]

    assert resolved is sentinel
    assert primary.provider_routing == routed.provider_routing
    assert primary.replay_provider_state is False
    assert primary.model == "openai/gpt-analyzer"


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


@pytest.mark.parametrize("module", [runner, resume_runner], ids=["main", "resume"])
@pytest.mark.parametrize(
    ("model", "expected_level"),
    [
        ("anthropic/claude-opus-4.8", "max"),
        ("openai/gpt-5.5", "xhigh"),
    ],
)
def test_generation_config_enables_openrouter_baseline_reasoning(
    module,
    model: str,
    expected_level: str,
) -> None:
    config = module.generation_chat_config(
        module.generation_thinking_policy(),
        model=model,
    )

    assert config.thinking is True
    assert config.thinking_level == expected_level
    assert config.model_capabilities is not None
    assert config.model_capabilities.supports_reasoning is True
    assert config.model_capabilities.reasoning_format == "openrouter"


@pytest.mark.parametrize("module", [runner, resume_runner], ids=["main", "resume"])
def test_router_single_selected_model_receives_reasoning_capabilities(module) -> None:
    config = module.generation_chat_config(
        module.generation_thinking_policy(),
        model=None,
    )
    assert config.model_capabilities is None

    resolved = module.with_openrouter_model_capabilities(config, "openai/gpt-5.5")

    assert resolved.model_capabilities is not None
    assert resolved.model_capabilities.supports_reasoning is True
    assert resolved.model_capabilities.reasoning_format == "openrouter"


@pytest.mark.parametrize("module", [runner, resume_runner], ids=["main", "resume"])
def test_agent_loop_preserves_provider_native_max_thinking(module) -> None:
    chat_config = module.generation_chat_config(
        module.generation_thinking_policy(),
        model="anthropic/claude-opus-4.8",
    )

    agent_config = module.agent_config_from_chat_config(
        chat_config,
        timeout=3600,
        model_id="anthropic/claude-opus-4.8",
        max_iterations=12,
    )

    assert agent_config.thinking is ThinkingLevel.MAX
    assert agent_config.resolve_thinking("prompt") == (True, 50_000)


def _ensemble_member(module, model: str, *, thinking: str = "low"):
    return module.EnsembleMemberConfig(
        provider_config=ProviderConfig(
            provider="openrouter",
            model=model,
            provider_routing={model: "verified-upstream"},
        ),
        label=model.rsplit("/", 1)[-1],
        temperature=0.7,
        max_tokens=1024,
        thinking=thinking,
    )


@pytest.mark.parametrize("module", [runner, resume_runner], ids=["main", "resume"])
def test_run_wide_generation_policy_overrides_realized_ensemble_members(module) -> None:
    provider = module.EnsembleProvider(
        profile_name="router_dynamic/c3",
        proposers=[
            _ensemble_member(module, "anthropic/claude-opus-4.8"),
            _ensemble_member(module, "qwen/qwen3.7-max"),
            _ensemble_member(module, "x-ai/grok-4.5"),
        ],
        aggregator=_ensemble_member(module, "anthropic/claude-sonnet-5"),
    )
    policy = {
        **module.generation_thinking_policy(),
        "temperature": 0.0,
        "max_tokens": 16_384,
        "max_tokens_overridden": True,
        "thinking_budget_tokens": 50_000,
    }

    aligned = module.apply_generation_policy_to_ensemble_provider(provider, policy)

    assert [member.thinking for member in aligned.proposers] == [
        "max",
        "xhigh",
        "xhigh",
    ]
    assert aligned.aggregator.thinking == "xhigh"
    assert all(member.temperature == 0.0 for member in aligned.proposers)
    assert aligned.aggregator.temperature == 0.0
    assert all(member.max_tokens == 16_384 for member in aligned.proposers)
    assert aligned.aggregator.max_tokens == 16_384
    assert aligned.selection_plan["generation_policy_applied"] is True
    assert {
        row["model"]: row["thinking"]
        for row in aligned.selection_plan["member_generation"]
    } == {
        "anthropic/claude-opus-4.8": "max",
        "qwen/qwen3.7-max": "xhigh",
        "x-ai/grok-4.5": "xhigh",
        "anthropic/claude-sonnet-5": "xhigh",
    }


@pytest.mark.parametrize("module", [runner, resume_runner], ids=["main", "resume"])
def test_default_model_specific_budget_is_resolved_per_ensemble_member(module) -> None:
    provider = module.EnsembleProvider(
        profile_name="router_dynamic/c3",
        proposers=[_ensemble_member(module, "anthropic/claude-opus-4.8")],
        aggregator=_ensemble_member(module, "x-ai/grok-4.5"),
    )
    policy = module.generation_thinking_policy()
    assert policy["thinking_budget_tokens"] == "model-specific"

    aligned = module.apply_generation_policy_to_ensemble_provider(provider, policy)

    assert {
        row["model"]: row["thinking_budget_tokens"]
        for row in aligned.selection_plan["member_generation"]
    } == {
        "anthropic/claude-opus-4.8": 50_000,
        "x-ai/grok-4.5": 50_000,
    }


@pytest.mark.parametrize("module", [runner, resume_runner], ids=["main", "resume"])
def test_strict_ensemble_validation_rejects_unproved_reasoning_member(
    module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "kwaipilot/kat-coder-pro-v2.5"
    provider = module.EnsembleProvider(
        profile_name="router_dynamic/c3",
        proposers=[_ensemble_member(module, model, thinking="xhigh")],
        aggregator=_ensemble_member(module, "x-ai/grok-4.5", thinking="xhigh"),
    )
    monkeypatch.setenv("OPENSQUILLA_PROVIDER_ROUTING_STRICT", "1")
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_REQUIRE_PARAMETERS", "1")

    with pytest.raises(ValueError, match="cannot prove support"):
        module.validate_strict_openrouter_ensemble_members(
            provider,
            module.generation_thinking_policy(),
        )


@pytest.mark.parametrize("module", [runner, resume_runner], ids=["main", "resume"])
def test_strict_ensemble_validation_requires_upstream_pin(
    module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "x-ai/grok-4.5"
    member = _ensemble_member(module, model, thinking="xhigh")
    member.provider_config.provider_routing.clear()
    provider = module.EnsembleProvider(
        profile_name="router_dynamic/c3",
        proposers=[member],
        aggregator=_ensemble_member(module, "anthropic/claude-sonnet-5"),
    )
    monkeypatch.setenv("OPENSQUILLA_PROVIDER_ROUTING_STRICT", "1")
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_REQUIRE_PARAMETERS", "1")

    with pytest.raises(ValueError, match="no strict upstream provider pin"):
        module.validate_strict_openrouter_ensemble_members(
            provider,
            module.generation_thinking_policy(),
        )


@pytest.mark.parametrize("module", [runner, resume_runner], ids=["main", "resume"])
def test_strict_ensemble_validation_checks_fallback_and_enabled_boolean(
    module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "deepseek/deepseek-v4-pro"
    provider = module.EnsembleProvider(
        profile_name="static_openrouter_b5",
        proposers=[_ensemble_member(module, model, thinking="xhigh")],
        aggregator=_ensemble_member(module, "z-ai/glm-5.2", thinking="xhigh"),
        fallback_model=model,
    )
    fallback_config = ProviderConfig(
        provider="openrouter",
        model=model,
        provider_routing={},
    )
    monkeypatch.setenv("OPENSQUILLA_PROVIDER_ROUTING_STRICT", "enabled")
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_REQUIRE_PARAMETERS", "enabled")

    with pytest.raises(ValueError, match="no strict upstream provider pin"):
        module.validate_strict_openrouter_ensemble_members(
            provider,
            module.generation_thinking_policy(),
            fallback_config=fallback_config,
        )


@pytest.mark.parametrize("module", [runner, resume_runner], ids=["main", "resume"])
def test_ensemble_fallback_model_receives_openrouter_reasoning_capabilities(module) -> None:
    policy = module.generation_thinking_policy()
    config = module.generation_chat_config(policy, model=None)

    resolved = module.with_openrouter_model_capabilities(
        config,
        "deepseek/deepseek-v4-pro",
    )

    assert resolved.model_capabilities is not None
    assert resolved.model_capabilities.supports_reasoning is True
    assert resolved.model_capabilities.reasoning_format == "openrouter"


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


def test_explicit_brave_environment_key_overrides_stale_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "fresh-env-key")
    configure_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "opensquilla.tools.builtin.web.configure_search",
        lambda **kwargs: configure_calls.append(kwargs),
    )
    config = GatewayConfig(search_api_key="stale-config-key")
    args = runner.build_parser().parse_args(
        [
            "--input",
            "tasks.jsonl",
            "--groups",
            "B1",
            "--tool-mode",
            "local_web_tools",
            "--local-web-search-provider",
            "brave",
            "--local-web-search-api-key-env",
            "BRAVE_SEARCH_API_KEY",
        ]
    )

    runtime = runner.configure_local_web_search_runtime(
        config,
        runner.benchmark_tool_policy(args),
    )

    assert runtime["api_key_source"] == "env:BRAVE_SEARCH_API_KEY"
    assert configure_calls[0]["api_key"] == "fresh-env-key"


def _local_web_tool_policy():
    args = runner.build_parser().parse_args(
        [
            "--input",
            "tasks.jsonl",
            "--groups",
            "B1",
            "--tool-mode",
            "local_web_tools",
        ]
    )
    return runner.benchmark_tool_policy(args)


def test_benchmark_tool_context_does_not_force_full_host_access() -> None:
    policy = _local_web_tool_policy()

    context = runner.build_benchmark_tool_context(
        task_id="task-1",
        group="B1",
        tool_policy=policy,
    )

    assert context.run_mode is None
    assert context.sandbox_run_context is None
    assert context.allowed_tools == {"web_search", "web_fetch"}


@pytest.mark.asyncio
async def test_local_web_preflight_does_not_enable_full_host_access(
    monkeypatch: pytest.MonkeyPatch,
    configured_tool_runtime,
) -> None:
    calls = {"search": 0, "fetch": 0}

    async def _fake_search(query: str, max_results: int, *, exclude_domains, provider: str):
        calls["search"] += 1
        assert "OpenAI official website" in query
        assert max_results == 1
        assert "github.com" in exclude_domains
        assert provider == "duckduckgo"
        return {
            "query": query,
            "results": [
                {
                    "title": "OpenAI",
                    "url": "https://openai.com/",
                    "snippet": "Official site",
                }
            ],
        }

    async def _fake_fetch(
        url: str,
        *,
        extract_mode: str,
        max_chars: int | None,
        extractor: str,
    ):
        from opensquilla.tools.run_mode import full_host_access_active

        calls["fetch"] += 1
        assert full_host_access_active() is False
        assert url == "https://example.com/"
        assert extract_mode == "text"
        assert max_chars == 1_000
        assert extractor == "auto"
        return {
            "url": url,
            "final_url": url,
            "status": 200,
            "text": "<external-content>Example Domain</external-content>",
        }

    monkeypatch.setattr(
        "opensquilla.tools.builtin.web.run_web_search_payload",
        _fake_search,
    )
    monkeypatch.setattr(
        "opensquilla.tools.builtin.web_fetch.run_web_fetch_payload",
        _fake_fetch,
    )

    result = await runner.run_local_web_tools_preflight(_local_web_tool_policy())

    assert result["status"] == "passed"
    assert "run_mode" not in result
    assert result["web_search_result_count"] == 1
    assert result["web_fetch_http_status"] == 200
    assert result["attempts_used"] == 1
    assert result["preflight_calls"] == {"web_search": 1, "web_fetch": 1}
    assert calls == {"search": 1, "fetch": 1}


@pytest.mark.asyncio
async def test_local_web_fetch_keeps_draco_contamination_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_called = False

    async def _fake_fetch(*args, **kwargs):
        nonlocal fetch_called
        fetch_called = True
        return {"status": 200, "text": "should not be fetched"}

    monkeypatch.setattr(
        "opensquilla.tools.builtin.web_fetch.run_web_fetch_payload",
        _fake_fetch,
    )
    policy = _local_web_tool_policy()
    registry = runner.build_local_web_tool_registry(policy)
    context = runner.build_benchmark_tool_context(
        task_id="task-1",
        group="B1",
        tool_policy=policy,
    )
    handler = runner.build_tool_handler(registry, context)

    result = await handler(
        ToolCall(
            tool_use_id="blocked-fetch",
            tool_name="web_fetch",
            arguments={"url": "https://github.com/openai/example"},
        )
    )

    payload = json.loads(result.content)
    assert fetch_called is False
    assert payload["error_class"] == "BlockedDomain"
    assert payload["blocked_domain"] == "github.com"


@pytest.mark.asyncio
async def test_local_web_preflight_fails_closed_on_denial_payload(
    monkeypatch: pytest.MonkeyPatch,
    configured_tool_runtime,
) -> None:
    async def _fake_search(query: str, max_results: int, *, exclude_domains, provider: str):
        assert provider == "duckduckgo"
        return {
            "query": query,
            "results": [{"title": "OpenAI", "url": "https://openai.com/"}],
        }

    async def _denied_fetch(*args, **kwargs):
        return {
            "status": "error",
            "reason": "policy_denied",
            "error": "network denied",
        }

    monkeypatch.setattr(
        "opensquilla.tools.builtin.web.run_web_search_payload",
        _fake_search,
    )
    monkeypatch.setattr(
        "opensquilla.tools.builtin.web_fetch.run_web_fetch_payload",
        _denied_fetch,
    )

    with pytest.raises(RuntimeError, match="web_fetch preflight failed"):
        await runner.run_local_web_tools_preflight(
            _local_web_tool_policy(),
            max_attempts=1,
        )


@pytest.mark.asyncio
async def test_benchmark_tools_respect_ambient_standard_context(
    monkeypatch: pytest.MonkeyPatch,
    configured_tool_runtime,
) -> None:
    observed: list[tuple[bool, str | None]] = []

    async def _fake_fetch(
        url: str,
        *,
        extract_mode: str,
        max_chars: int | None,
        extractor: str,
    ):
        from opensquilla.tools.run_mode import full_host_access_active

        active = current_tool_context.get()
        observed.append((full_host_access_active(), active.task_id if active else None))
        return {"url": url, "final_url": url, "status": 200, "text": "ok"}

    monkeypatch.setattr(
        "opensquilla.tools.builtin.web_fetch.run_web_fetch_payload",
        _fake_fetch,
    )
    policy = _local_web_tool_policy()
    benchmark_context = runner.build_benchmark_tool_context(
        task_id="benchmark-task",
        group="B1",
        tool_policy=policy,
    )
    ambient = runner.ToolContext(
        run_mode="standard",
        sandbox_run_context=benchmark_context.sandbox_run_context,
        task_id="outer-task",
    )
    handler = runner.build_tool_handler(
        runner.build_local_web_tool_registry(policy),
        benchmark_context,
    )

    token = current_tool_context.set(ambient)
    try:
        result = await handler(
            ToolCall(
                tool_use_id="ambient-override",
                tool_name="web_fetch",
                arguments={"url": "https://example.com/"},
            )
        )
        assert result.is_error is False
        assert current_tool_context.get() is ambient
    finally:
        current_tool_context.reset(token)
    assert observed == [(False, "outer-task")]


@pytest.mark.asyncio
async def test_local_web_search_filters_results_sources_and_internal_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_search(query: str, max_results: int, *, exclude_domains, provider: str):
        captured.update(
            query=query,
            max_results=max_results,
            exclude_domains=list(exclude_domains),
            provider=provider,
        )
        return {
            "query": query,
            "results": [
                {"title": "blocked", "url": "https://github.com/example"},
                {"title": "allowed", "url": "https://example.com/allowed"},
            ],
            "sources": [
                {"url": "https://huggingface.co/datasets/example", "text": "blocked"},
                {"url": "https://example.com/source", "text": "allowed"},
            ],
        }

    monkeypatch.setattr(
        "opensquilla.tools.builtin.web.run_web_search_payload",
        _fake_search,
    )
    policy = _local_web_tool_policy()
    policy["local_web_tools"]["web_search"]["provider"] = "brave"
    context = runner.build_benchmark_tool_context(
        task_id="search-task",
        group="B1",
        tool_policy=policy,
    )
    handler = runner.build_tool_handler(
        runner.build_local_web_tool_registry(policy),
        context,
    )
    result = await handler(
        ToolCall(
            tool_use_id="search-contamination",
            tool_name="web_search",
            arguments={"query": "test"},
        )
    )

    payload = json.loads(result.content)
    assert captured["query"] == "test"
    assert captured["max_results"] == runner.local_web_search_max_results(policy)
    assert "github.com" in captured["exclude_domains"]
    assert captured["provider"] == "brave"
    assert [item["url"] for item in payload["results"]] == [
        "https://example.com/allowed"
    ]
    assert [item["url"] for item in payload["sources"]] == [
        "https://example.com/source"
    ]
    assert payload["blocked_result_count"] == 1
    assert payload["blocked_source_count"] == 1


@pytest.mark.asyncio
async def test_local_web_fetch_discards_blocked_redirect_content(
    monkeypatch: pytest.MonkeyPatch,
    configured_tool_runtime,
) -> None:
    async def _redirected_fetch(*args, **kwargs):
        return {
            "url": "https://example.com/start",
            "final_url": "https://github.com/private/answer",
            "status": 200,
            "text": "must not reach the model",
        }

    monkeypatch.setattr(
        "opensquilla.tools.builtin.web_fetch.run_web_fetch_payload",
        _redirected_fetch,
    )
    policy = _local_web_tool_policy()
    context = runner.build_benchmark_tool_context(
        task_id="redirect-task",
        group="B1",
        tool_policy=policy,
    )
    handler = runner.build_tool_handler(
        runner.build_local_web_tool_registry(policy),
        context,
    )
    result = await handler(
        ToolCall(
            tool_use_id="redirect-contamination",
            tool_name="web_fetch",
            arguments={"url": "https://example.com/start"},
        )
    )

    payload = json.loads(result.content)
    assert payload["error_class"] == "BlockedDomain"
    assert payload["blocked_domain"] == "github.com"
    assert "must not reach the model" not in result.content


@pytest.mark.asyncio
async def test_local_web_preflight_retries_and_records_all_setup_calls(
    monkeypatch: pytest.MonkeyPatch,
    configured_tool_runtime,
) -> None:
    fetch_attempt = 0

    async def _fake_search(query: str, max_results: int, *, exclude_domains, provider: str):
        assert provider == "duckduckgo"
        return {"query": query, "results": [{"url": "https://openai.com/"}]}

    async def _flaky_fetch(*args, **kwargs):
        nonlocal fetch_attempt
        fetch_attempt += 1
        if fetch_attempt == 1:
            return {"status": 503, "text": "temporarily unavailable"}
        return {
            "url": "https://example.com/",
            "final_url": "https://example.com/",
            "status": 200,
            "text": "Example Domain",
        }

    monkeypatch.setattr("opensquilla.tools.builtin.web.run_web_search_payload", _fake_search)
    monkeypatch.setattr(
        "opensquilla.tools.builtin.web_fetch.run_web_fetch_payload",
        _flaky_fetch,
    )

    result = await runner.run_local_web_tools_preflight(
        _local_web_tool_policy(),
        retry_backoff_seconds=0,
    )

    assert result["attempts_used"] == 2
    assert result["preflight_calls"] == {"web_search": 2, "web_fetch": 2}


@pytest.mark.asyncio
async def test_local_web_preflight_times_out_closed(
    monkeypatch: pytest.MonkeyPatch,
    configured_tool_runtime,
) -> None:
    async def _fake_search(query: str, max_results: int, *, exclude_domains, provider: str):
        assert provider == "duckduckgo"
        return {"query": query, "results": [{"url": "https://openai.com/"}]}

    async def _hanging_fetch(*args, **kwargs):
        await asyncio.sleep(1)
        return {"status": 200, "text": "too late"}

    monkeypatch.setattr("opensquilla.tools.builtin.web.run_web_search_payload", _fake_search)
    monkeypatch.setattr(
        "opensquilla.tools.builtin.web_fetch.run_web_fetch_payload",
        _hanging_fetch,
    )

    with pytest.raises(RuntimeError, match="timed out"):
        await runner.run_local_web_tools_preflight(
            _local_web_tool_policy(),
            max_attempts=1,
            call_timeout_seconds=0.01,
        )


def test_runner_tool_mode_combinations_fail_closed() -> None:
    with pytest.raises(ValueError, match="requires --runner-mode=agent_loop"):
        runner.validate_tool_mode_for_runner("provider", "local_web_tools")
    with pytest.raises(ValueError, match="requires --runner-mode=provider"):
        runner.validate_tool_mode_for_runner("agent_loop", "openrouter_server_tools")
    runner.validate_tool_mode_for_runner(
        "provider",
        "local_web_tools",
        smoke_only=True,
    )


def test_select_tasks_by_ids_preserves_reference_order_and_rejects_bad_ids() -> None:
    tasks = [
        {"id": "task-a", "prompt": "a"},
        {"id": "task-b", "prompt": "b"},
        {"id": "task-c", "prompt": "c"},
    ]

    selected = runner.select_tasks_by_ids(tasks, ["task-c", "task-a"])

    assert [task["id"] for task in selected] == ["task-a", "task-c"]
    with pytest.raises(ValueError, match="duplicate --task-ids"):
        runner.select_tasks_by_ids(tasks, ["task-a", "task-a"])
    with pytest.raises(ValueError, match="unknown --task-ids"):
        runner.select_tasks_by_ids(tasks, ["task-missing"])


def test_recovery_cli_arguments_are_manifested_and_reconstructed() -> None:
    args = runner.build_parser().parse_args(
        [
            "--input",
            "tasks.jsonl",
            "--groups",
            "B0,B1",
            "--task-ids",
            "task-a",
            "--task-ids",
            "task-c",
            "--continue-after-cost-audit-failure",
        ]
    )

    manifest = runner.manifest_args(args)
    reconstructed = runner.reconstructed_cli_args(args)
    assert manifest["task_ids"] == ["task-a", "task-c"]
    assert manifest["continue_after_cost_audit_failure"] is True
    assert reconstructed.count("--task-ids") == 2
    assert "--continue-after-cost-audit-failure" in reconstructed


@pytest.mark.asyncio
async def test_preflight_failure_writes_audit_manifest_before_any_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "tasks.jsonl"
    input_path.write_text(
        json.dumps({"id": "task-1", "prompt": "test prompt"}) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    args = runner.build_parser().parse_args(
        [
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--groups",
            "B1",
            "--runner-mode",
            "agent_loop",
            "--tool-mode",
            "local_web_tools",
            "--local-web-search-provider",
            "duckduckgo",
        ]
    )

    monkeypatch.setattr(runner.GatewayConfig, "load", lambda _path: GatewayConfig())
    monkeypatch.setattr(
        runner,
        "configure_local_web_search_runtime",
        lambda *_args, **_kwargs: {"provider": "duckduckgo"},
    )

    async def _failed_preflight(*_args, **_kwargs):
        raise RuntimeError("synthetic preflight failure")

    monkeypatch.setattr(runner, "run_local_web_tools_preflight", _failed_preflight)

    with pytest.raises(RuntimeError, match="synthetic preflight failure"):
        await runner.amain(args)

    manifests = list(output_dir.glob("*.preflight-failed.manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "preflight_failed"
    assert manifest["failure"]["stage"] == "local_web_tools_preflight"
    assert manifest["failure"]["model_or_judge_started"] is False
    assert manifest["rows_written"] == 0
    assert not list(output_dir.glob("draco_ensemble_*.jsonl"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("continue_after_failure", "expected_rows"),
    [(False, 1), (True, 2)],
    ids=["fail-fast-default", "continue-recovery"],
)
async def test_cost_audit_recovery_mode_finishes_independent_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continue_after_failure: bool,
    expected_rows: int,
) -> None:
    input_path = tmp_path / "tasks.jsonl"
    input_path.write_text(
        "\n".join(
            json.dumps({"id": task_id, "prompt": f"prompt {task_id}"})
            for task_id in ("task-a", "task-b")
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    argv = [
        "--input",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--groups",
        "B0",
        "--dry-run",
        "--require-openrouter-non-byok",
        "--concurrency",
        "1",
    ]
    if continue_after_failure:
        argv.append("--continue-after-cost-audit-failure")
    args = runner.build_parser().parse_args(argv)
    monkeypatch.setattr(runner.GatewayConfig, "load", lambda _path: GatewayConfig())

    status = await runner.amain(args)

    assert status == 2
    result_paths = list(output_dir.glob("draco_ensemble_*.jsonl"))
    manifest_paths = list(output_dir.glob("draco_run_*.manifest.json"))
    assert len(result_paths) == 1
    assert len(manifest_paths) == 1
    rows = [
        json.loads(line)
        for line in result_paths[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert len(rows) == expected_rows
    assert manifest["rows_written"] == expected_rows
    assert manifest["status"] == "cost_audit_failed"
    assert all(row["error"] == "openrouter_non_byok_verification_failed" for row in rows)
    if continue_after_failure:
        assert manifest["failure"]["failure_count"] == 2
        assert len(manifest["failure"]["failures"]) == 2
    else:
        assert manifest["failure"]["task_id"] in {"task-a", "task-b"}


def test_local_web_fetch_runtime_disables_hidden_firecrawl_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "secret-not-serialized")
    policy = _local_web_tool_policy()

    runtime = runner.configure_local_web_fetch_runtime(policy)

    assert runtime["firecrawl_allowed"] is False
    assert runtime["firecrawl_api_key_active"] is False
    assert runtime["firecrawl_disabled_for_reproducibility"] is True
    assert "FIRECRAWL_API_KEY" not in runner.os.environ


def test_cost_accounting_includes_judge_and_never_prices_unknown_as_zero() -> None:
    generation_usage = {
        "model_usage_breakdown": [
            {
                "provider": "openrouter",
                "model": "known",
                "input_tokens": 100,
                "output_tokens": 20,
                "billed_cost": 0.10,
                "cost_source": "provider_billed",
                "provider_usage": _openrouter_exact_evidence(0.10, "gen-known"),
            },
            {
                "model": "unknown",
                "input_tokens": 200,
                "output_tokens": 40,
                "billed_cost": 0.0,
                "cost_source": "none",
            },
        ]
    }
    judge_attempts = [
        {
            "attempt": 1,
            "run": {
                "llm_request_count": 1,
                "usage": {
                    "provider": "openrouter",
                    "model": "judge-model",
                    "input_tokens": 50,
                    "output_tokens": 5,
                    "billed_cost": 0.03,
                    "cost_source": "provider_billed",
                    "provider_usage": _openrouter_exact_evidence(0.03, "judge-1"),
                },
            },
        },
        {
            "attempt": 2,
            "run": {
                "llm_request_count": 1,
                "usage": {
                    "provider": "openrouter",
                    "model": "judge-model",
                    "input_tokens": 60,
                    "output_tokens": 6,
                    "billed_cost": 0.04,
                    "cost_source": "provider_billed",
                    "provider_usage": _openrouter_exact_evidence(0.04, "judge-2"),
                },
            },
        },
    ]
    row = {
        "tool_policy": {"tool_mode": "provider_only"},
        "llm_request_count": 2,
        "execution": {
            "generation_attempts": [
                {
                    "attempt": 1,
                    "run": {"llm_request_count": 2, "usage": generation_usage},
                }
            ]
        },
        "judge": {
            "criterion_judgments": [
                {
                    "judge_attempts": judge_attempts,
                    # This is a duplicate of the final attempt and must not be counted.
                    "judge_run": judge_attempts[-1]["run"],
                }
            ]
        },
        "candidate_judges": [],
    }

    accounting = runner.row_cost_accounting(row)

    assert runner.usage_unknown_count_from_usage_payload(generation_usage) == 1
    assert accounting["generation"]["request_count"] == 2
    assert accounting["generation"]["unknown_request_count"] == 1
    assert accounting["generation"]["unknown_tokens"] == 240
    assert accounting["generation"]["recorded_cost_usd"] == pytest.approx(0.10)
    assert accounting["judge"]["request_count"] == 2
    assert accounting["judge"]["recorded_cost_usd"] == pytest.approx(0.07)
    assert accounting["llm_total"]["recorded_cost_usd"] == pytest.approx(0.17)
    assert accounting["result_cost_complete"] is False


def test_resume_runner_does_not_force_full_host_access() -> None:
    resume_runner = _load_resume_runner()
    args = resume_runner.build_parser().parse_args(
        [
            "--input",
            "tasks.jsonl",
            "--groups",
            "B1",
            "--tool-mode",
            "local_web_tools",
        ]
    )
    policy = resume_runner.benchmark_tool_policy(args)

    context = resume_runner.build_benchmark_tool_context(
        task_id="task-1",
        group="B1",
        tool_policy=policy,
    )

    assert context.run_mode is None
    assert context.sandbox_run_context is None


def test_agent_llm_error_without_usage_is_counted_as_unknown_cost() -> None:
    breakdown = runner.aggregate_agent_model_usage(
        [
            {
                "kind": "llm_error",
                "payload": {"iteration": 2, "attempt": 1, "error": "timeout"},
            }
        ]
    )

    assert len(breakdown) == 1
    assert breakdown[0]["role"] == "agent_llm_request_unknown"
    accounting = runner.usage_cost_accounting(
        {"model_usage_breakdown": breakdown},
        expected_requests=1,
        scope="generation",
    )
    assert accounting["unknown_request_count"] == 1
    assert accounting["cost_exact"] is False


def test_agent_llm_error_without_usage_honors_missing_request_count() -> None:
    breakdown = runner.aggregate_agent_model_usage(
        [
            {
                "kind": "llm_error",
                "payload": {"iteration": 2, "attempt": 1, "usage_missing_count": 2},
            }
        ]
    )

    assert len(breakdown) == 2
    assert all(row["cost_source"] == "none" for row in breakdown)


def test_agent_usage_does_not_double_count_abandoned_stream_placeholder() -> None:
    breakdown = runner.aggregate_agent_model_usage(
        [
            {
                "kind": "llm_response",
                "payload": {
                    "iteration": 1,
                    "attempt": 1,
                    "usage_missing_count": 1,
                    "usage": {
                        "model_usage_breakdown": [
                            {
                                "role": "abandoned_stream_request",
                                "provider": "openrouter",
                                "model": "model-a",
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "billed_cost": 0.0,
                                "cost_source": "none",
                            }
                        ]
                    },
                },
            }
        ]
    )

    assert len(breakdown) == 1
    assert breakdown[0]["role"] == "abandoned_stream_request"


def test_agent_usage_does_not_treat_generic_unpriced_row_as_missing_placeholder() -> None:
    breakdown = runner.aggregate_agent_model_usage(
        [
            {
                "kind": "llm_error",
                "payload": {
                    "iteration": 1,
                    "attempt": 1,
                    "usage_missing_count": 1,
                    "usage": {
                        "model_usage_breakdown": [
                            {
                                "role": "proposer",
                                "provider": "openrouter",
                                "model": "model-a",
                                "input_tokens": 3,
                                "output_tokens": 1,
                                "billed_cost": 0.0,
                                "cost_source": "none",
                            }
                        ]
                    },
                },
            }
        ]
    )

    assert len(breakdown) == 2
    assert [row["role"] for row in breakdown] == [
        "proposer",
        "agent_llm_request_unknown",
    ]


def test_agent_retry_partial_error_preserves_missing_physical_request() -> None:
    first_attempt_rows = [
        {
            "provider": "openrouter",
            "model": f"proposer-{index}",
            "input_tokens": 10,
            "output_tokens": 2,
            "billed_cost": 0.01,
            "cost_source": "provider_billed",
            "provider_usage": _openrouter_exact_evidence(
                0.01, f"failed-attempt-proposer-{index}"
            ),
        }
        for index in range(4)
    ]
    retry_rows = [
        {
            "provider": "openrouter",
            "model": f"retry-model-{index}",
            "input_tokens": 10,
            "output_tokens": 2,
            "billed_cost": 0.02,
            "cost_source": "provider_billed",
            "provider_usage": _openrouter_exact_evidence(
                0.02, f"successful-retry-{index}"
            ),
        }
        for index in range(5)
    ]

    breakdown = runner.aggregate_agent_model_usage(
        [
            {
                "kind": "llm_error",
                "payload": {
                    "iteration": 1,
                    "attempt": 1,
                    "usage_missing_count": 1,
                    "usage": {"model_usage_breakdown": first_attempt_rows},
                },
            },
            {
                "kind": "llm_response",
                "payload": {
                    "iteration": 1,
                    "attempt": 2,
                    "usage": {"model_usage_breakdown": retry_rows},
                },
            },
        ]
    )

    assert len(breakdown) == 10
    assert sum(row["cost_source"] == "provider_billed" for row in breakdown) == 9
    unknown = [row for row in breakdown if row["cost_source"] == "none"]
    assert len(unknown) == 1
    assert unknown[0]["role"] == "agent_llm_request_unknown"
    accounting = runner.usage_cost_accounting(
        {"model_usage_breakdown": breakdown},
        expected_requests=9,
        scope="generation",
    )
    assert accounting["request_count"] == 10
    assert accounting["unknown_request_count"] == 1
    assert accounting["cost_exact"] is False


def test_estimated_and_mixed_usage_record_their_actual_cost_fields() -> None:
    accounting = runner.usage_cost_accounting(
        {
            "model_usage_breakdown": [
                {
                    "provider": "openrouter",
                    "model": "estimated-model",
                    "input_tokens": 3,
                    "output_tokens": 1,
                    "billed_cost": 0.0,
                    "estimated_cost_usd": 0.40,
                    "cost_usd": 0.40,
                    "cost_source": "opensquilla_estimate",
                },
                {
                    "provider": "openrouter",
                    "model": "mixed-model",
                    "input_tokens": 4,
                    "output_tokens": 2,
                    "billed_cost": 0.10,
                    "billed_cost_usd": 0.10,
                    "estimated_cost_usd": 0.20,
                    "cost_usd": 0.30,
                    "cost_source": "mixed",
                },
            ]
        },
        expected_requests=2,
        scope="generation",
    )

    assert accounting["estimated_request_count"] == 1
    assert accounting["mixed_request_count"] == 1
    assert accounting["recorded_cost_usd"] == pytest.approx(0.70)


def test_agent_model_usage_preserves_physical_provider_evidence() -> None:
    provider_usage = _openrouter_exact_evidence(0.01, "generation-1")
    breakdown = runner.aggregate_agent_model_usage(
        [
            {
                "kind": "llm_response",
                "payload": {
                    "iteration": 1,
                    "call_attempt": 1,
                    "usage": {
                        "provider": "openrouter",
                        "model": "model-a",
                        "input_tokens": 3,
                        "output_tokens": 1,
                        "billed_cost": 0.01,
                        "cost_source": "provider_billed",
                        "provider_usage": provider_usage,
                    },
                },
            }
        ]
    )

    assert breakdown[0]["provider"] == "openrouter"
    assert breakdown[0]["provider_usage"] == provider_usage
    assert runner.usage_cost_accounting(
        {"model_usage_breakdown": breakdown},
        expected_requests=1,
        scope="generation",
    )["cost_exact"] is True


def test_failed_agent_attempt_synthesizes_diagnostic_usage_from_recorder() -> None:
    recorder = runner.BenchmarkTurnCallRecorder()
    recorder.write(
        "llm_error",
        {
            "iteration": 1,
            "call_attempt": 1,
            "usage": {
                "provider": "openrouter",
                "model": "model-a",
                "input_tokens": 12,
                "output_tokens": 3,
                "billed_cost": 0.25,
                "cost_source": "provider_billed",
                "provider_usage": _openrouter_exact_evidence(0.25, "failed-1"),
            },
            "error": {"code": "timeout", "message": "timed out"},
        },
    )

    done = runner.provider_done_from_agent_done(
        None,
        recorder=recorder,
        fallback_model="model-a",
    )

    assert done is not None
    assert done.stop_reason == "error"
    assert done.input_tokens == 12
    assert done.output_tokens == 3
    assert done.billed_cost == pytest.approx(0.25)
    assert done.provider_usage["diagnostic_usage_only"] is True
    assert done.model_usage_breakdown[0]["provider_usage"]["response_ids"] == [
        "failed-1"
    ]
    assert runner.usage_cost_accounting(
        runner.done_payload(done),
        expected_requests=1,
        scope="generation",
    )["cost_exact"] is True


def test_main_and_resume_share_identical_critical_runtime_functions() -> None:
    resume_runner = _load_resume_runner()
    critical = (
        "validate_tool_mode_for_runner",
        "configure_benchmark_sandbox_runtime",
        "configure_local_web_fetch_runtime",
        "filter_blocked_search_results",
        "build_local_web_tool_registry",
        "build_benchmark_tool_context",
        "run_local_web_tools_preflight",
        "build_task_analyzer_provider",
        "_openrouter_non_byok_receipt_is_exact",
        "_first_usage_cost",
        "_mixed_usage_cost",
        "usage_cost_accounting",
        "merge_cost_accounting",
        "aggregate_agent_model_usage",
        "row_cost_accounting",
        "canonical_json_sha256",
        "gateway_execution_contract",
        "resolved_llm_runtime_contract",
        "build_run_compatibility",
        "openrouter_non_byok_audit",
        "judge_text",
        "run_one",
        "trace_row",
    )

    for name in critical:
        assert inspect.getsource(getattr(runner, name)) == inspect.getsource(
            getattr(resume_runner, name)
        )


def test_resume_only_skips_strict_valid_matching_prompt(tmp_path: Path) -> None:
    resume_runner = _load_resume_runner()
    prompt_hash = resume_runner.text_sha256("same prompt")
    valid = resume_runner.seal_result_row({
        "group": "B1",
        "task_id": "task-1",
        "prompt_sha256": prompt_hash,
        "task_input_sha256": "sha256:task-input",
        "run_compatibility_fingerprint": "sha256:run-contract",
        "error": None,
        "final_text": "answer",
        "quality_total": 80.0,
        "judge": {"score_status": "complete", "judge_error_count": 0},
        "ensemble_trace": {},
    })
    failed = resume_runner.seal_result_row(
        {**valid, "task_id": "task-2", "error": "provider failure"}
    )
    wrong_prompt = resume_runner.seal_result_row(
        {**valid, "task_id": "task-3", "prompt_sha256": "wrong"}
    )
    path = tmp_path / "prior.jsonl"
    path.write_text(
        "\n".join(json.dumps(row) for row in (valid, failed, wrong_prompt)) + "\n",
        encoding="utf-8",
    )
    selected = {("B1", "task-1"), ("B1", "task-2"), ("B1", "task-3")}

    completed, audit = resume_runner.load_strict_completed_group_task_keys(
        resume_paths=[path],
        selected_keys=selected,
        prompt_hashes={task_id: prompt_hash for _, task_id in selected},
        task_input_hashes={task_id: "sha256:task-input" for _, task_id in selected},
        run_compatibility_fingerprints={"B1": "sha256:run-contract"},
    )

    assert completed == {("B1", "task-1")}
    assert audit["matching_attempt_count"] == 3
    assert audit["strict_valid_pair_count"] == 1
    assert audit["strict_invalid_attempt_count"] == 2


def test_resume_rejects_legacy_or_incompatible_contract_rows(tmp_path: Path) -> None:
    resume_runner = _load_resume_runner()
    prompt_hash = resume_runner.text_sha256("same prompt")
    base = {
        "group": "B1",
        "prompt_sha256": prompt_hash,
        "task_input_sha256": "sha256:task-input",
        "run_compatibility_fingerprint": "sha256:old-contract",
        "error": None,
        "final_text": "answer",
        "quality_total": 80.0,
        "judge": {"score_status": "complete", "judge_error_count": 0},
        "ensemble_trace": {},
    }
    legacy = {
        key: value
        for key, value in {**base, "task_id": "task-1"}.items()
        if key not in {"task_input_sha256", "run_compatibility_fingerprint"}
    }
    mismatched = resume_runner.seal_result_row({**base, "task_id": "task-2"})
    path = tmp_path / "prior.jsonl"
    path.write_text(
        "\n".join(json.dumps(row) for row in (legacy, mismatched)) + "\n",
        encoding="utf-8",
    )

    completed, audit = resume_runner.load_strict_completed_group_task_keys(
        resume_paths=[path],
        selected_keys={("B1", "task-1"), ("B1", "task-2")},
        prompt_hashes={"task-1": prompt_hash, "task-2": prompt_hash},
        task_input_hashes={"task-1": "sha256:task-input", "task-2": "sha256:task-input"},
        run_compatibility_fingerprints={"B1": "sha256:new-contract"},
    )

    assert completed == set()
    assert audit["strict_invalid_reason_counts"] == {
        "invalid_result_evidence": 1,
        "missing_run_compatibility_fingerprint": 1,
        "missing_task_input_sha256": 1,
        "run_compatibility_fingerprint_mismatch": 1,
    }


def test_resume_requires_recomputed_non_byok_cost_evidence() -> None:
    resume_runner = _load_resume_runner()
    prompt_hash = resume_runner.text_sha256("same prompt")
    base = {
        "group": "B1",
        "task_id": "task-1",
        "prompt_sha256": prompt_hash,
        "task_input_sha256": "sha256:task-input",
        "run_compatibility_fingerprint": "sha256:run-contract",
        "error": None,
        "final_text": "answer",
        "quality_total": 80.0,
        "judge": {"score_status": "complete", "judge_error_count": 0},
        "ensemble_trace": {},
    }
    invalid = resume_runner.seal_result_row(base)
    invalid_reasons = resume_runner.strict_resume_row_invalid_reasons(
        invalid,
        expected_prompt_sha256=prompt_hash,
        expected_task_input_sha256="sha256:task-input",
        expected_run_compatibility_fingerprint="sha256:run-contract",
        require_openrouter_non_byok=True,
    )
    assert "openrouter_non_byok_unverified" in invalid_reasons

    exact = {
        **base,
        "llm_request_count": 1,
        "usage": {
            "provider": "openrouter",
            "model": "model-a",
            "input_tokens": 3,
            "output_tokens": 1,
            "billed_cost": 0.01,
            "cost_source": "provider_billed",
            "provider_usage": _openrouter_exact_evidence(0.01, "resume-1"),
        },
    }
    exact["openrouter_non_byok_audit"] = resume_runner.openrouter_non_byok_audit(
        exact
    )
    sealed_exact = resume_runner.seal_result_row(exact)
    exact_reasons = resume_runner.strict_resume_row_invalid_reasons(
        sealed_exact,
        expected_prompt_sha256=prompt_hash,
        expected_task_input_sha256="sha256:task-input",
        expected_run_compatibility_fingerprint="sha256:run-contract",
        require_openrouter_non_byok=True,
    )
    assert exact_reasons == []


def _compatibility_for(
    module,
    *,
    concurrency: int = 1,
    judge_repeats: int = 3,
    api_key: str = "benchmark-key-secret",
):
    args = module.build_parser().parse_args(
        [
            "--input",
            "tasks.jsonl",
            "--groups",
            "B1",
            "--concurrency",
            str(concurrency),
            "--judge-model",
            "google/gemini-3.1-pro-preview",
            "--judge-repeats",
            str(judge_repeats),
        ]
    )
    args._source_provenance = {
        "git_head": "a" * 40,
        "source_tree_sha256": "b" * 64,
    }
    policy = module.benchmark_tool_policy(args)
    generation = module.generation_thinking_policy(args)
    config = GatewayConfig(
        llm={
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4-pro",
            "api_key": api_key,
        }
    )
    return module.build_run_compatibility(
        args=args,
        config=config,
        groups=["B1"],
        group_tool_policies=module.benchmark_tool_policies_for_groups(
            policy,
            ["B1"],
            args=args,
        ),
        generation_policy=generation,
    )


def test_run_compatibility_is_shared_by_main_and_resume_and_excludes_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENSQUILLA_PROVIDER_ROUTING_STRICT", raising=False)
    resume_runner = _load_resume_runner()
    main_contract = _compatibility_for(runner, concurrency=1)
    resume_contract = _compatibility_for(resume_runner, concurrency=5)

    assert main_contract["fingerprints"] == resume_contract["fingerprints"]
    assert "benchmark-key-secret" not in json.dumps(main_contract)
    changed_key = _compatibility_for(runner, api_key="different-benchmark-key")
    assert changed_key["fingerprints"]["B1"] != main_contract["fingerprints"]["B1"]
    changed_judge = _compatibility_for(runner, judge_repeats=2)
    assert changed_judge["fingerprints"]["B1"] != main_contract["fingerprints"]["B1"]
    monkeypatch.setenv("OPENSQUILLA_PROVIDER_ROUTING_STRICT", "1")
    strict = _compatibility_for(runner)
    assert strict["fingerprints"]["B1"] != main_contract["fingerprints"]["B1"]


def _b2_compatibility_for(
    module, *, runner_concurrency: int, judge_concurrency: int
):
    args = module.build_parser().parse_args(
        [
            "--input",
            "tasks.jsonl",
            "--groups",
            "B2",
            "--experiment-config",
            str(ROOT / "configs" / "benchmarks" / "draco_b2_g12.json"),
            "--experiment-config-set",
            f"runner.concurrency={runner_concurrency}",
            "--experiment-config-set",
            f"judge.concurrency={judge_concurrency}",
        ]
    )
    module.apply_b2_g12_argument_alignment(args, ["B2"])
    args._source_provenance = {
        "git_head": "a" * 40,
        "source_tree_sha256": "b" * 64,
    }
    policy = module.benchmark_tool_policy(args)
    config = GatewayConfig(
        llm={"provider": "openrouter", "model": "deepseek/deepseek-v4-pro"}
    )
    return module.build_run_compatibility(
        args=args,
        config=config,
        groups=["B2"],
        group_tool_policies=module.benchmark_tool_policies_for_groups(
            policy,
            ["B2"],
            args=args,
        ),
        generation_policy=module.generation_thinking_policy(args),
    )


def test_b2_compatibility_excludes_effective_scheduling_concurrency() -> None:
    canary = _b2_compatibility_for(
        runner,
        runner_concurrency=1,
        judge_concurrency=1,
    )
    full = _b2_compatibility_for(
        runner,
        runner_concurrency=5,
        judge_concurrency=6,
    )

    assert canary["fingerprints"]["B2"] == full["fingerprints"]["B2"]
    experiment = canary["contracts"]["B2"]["experiment_config"]
    assert "concurrency" not in experiment["runner"]
    assert "concurrency" not in experiment["judge"]
    provider_routing = canary["contracts"]["B2"]["resolved_llm_runtime"][
        "provider_routing"
    ]
    assert provider_routing["deepseek/deepseek-v4-pro"] == "deepseek"
    assert provider_routing["google/gemini-3.1-pro-preview"] == "google-ai-studio"
    assert provider_routing["moonshotai/kimi-k2.7-code"] == "moonshotai"
    assert provider_routing["qwen/qwen3.7-max"] == "alibaba"
    assert provider_routing["z-ai/glm-5.2"] == "z-ai"


def test_resume_expected_manifest_rejects_incompatible_contract(tmp_path: Path) -> None:
    resume_runner = _load_resume_runner()
    actual = _compatibility_for(resume_runner)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "run_compatibility": {
                    "fingerprints": {"B1": "sha256:different"}
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="incompatible"):
        resume_runner.validate_expected_run_compatibility(
            path=manifest,
            actual=actual,
            groups=["B1"],
        )


def test_task_input_hash_covers_rubric_not_only_prompt() -> None:
    first = {"id": "task-1", "prompt": "same", "rubric": {"criteria": ["a"]}}
    second = {"id": "task-1", "prompt": "same", "rubric": {"criteria": ["b"]}}

    assert runner.text_sha256(first["prompt"]) == runner.text_sha256(second["prompt"])
    assert runner.canonical_json_sha256(first) != runner.canonical_json_sha256(second)


def test_openrouter_non_byok_audit_fails_closed() -> None:
    exact = {
        "llm_request_count": 2,
        "usage": {
            "model_usage_breakdown": [
                {
                    "provider": "openrouter",
                    "model": "model-a",
                    "input_tokens": 3,
                    "output_tokens": 1,
                    "billed_cost": 0.01,
                    "cost_source": "provider_billed",
                    "provider_usage": _openrouter_exact_evidence(0.01, "exact-1"),
                },
                {
                    "provider": "openrouter",
                    "model": "model-b",
                    "input_tokens": 4,
                    "output_tokens": 2,
                    "billed_cost": 0.02,
                    "cost_source": "provider_billed",
                    "provider_usage": _openrouter_exact_evidence(0.02, "exact-2"),
                },
            ]
        },
        # A forged/stale summary must not bypass physical receipt validation.
        "cost_accounting": {
            "llm_total": {
                "cost_exact": True,
                "request_count": 2,
                "exact_request_count": 2,
            }
        }
    }
    unverified = {
        **exact,
        "usage": {
            "model_usage_breakdown": [
                exact["usage"]["model_usage_breakdown"][0],
                {
                    **exact["usage"]["model_usage_breakdown"][1],
                    "provider_usage": {
                        "is_byok": True,
                        "provider_reported_cost": 0.02,
                        "response_ids": ["byok-2"],
                        "router_metadata": {"is_byok": True},
                    },
                },
            ]
        },
        "cost_accounting": {
            "llm_total": {
                "cost_exact": True,
                "request_count": 2,
                "exact_request_count": 2,
            }
        }
    }

    assert runner.openrouter_non_byok_audit(exact)["pass"] is True
    audit = runner.openrouter_non_byok_audit(unverified)
    assert audit["pass"] is False
    assert audit["unverified_or_byok_request_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strict", "expected_requests", "expected_judge_calls", "expected_error"),
    [
        (True, 5, 0, "openrouter_non_byok_verification_failed"),
        (True, 4, 1, ""),
        (False, 5, 1, ""),
    ],
    ids=["strict-missing-receipt", "strict-all-exact", "non-strict-unchanged"],
)
async def test_generation_non_byok_gate_runs_before_judge(
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
    expected_requests: int,
    expected_judge_calls: int,
    expected_error: str,
) -> None:
    config, inherited = _openrouter_config()
    rows = [
        {
            "provider": "openrouter",
            "model": f"model-{index}",
            "input_tokens": 3,
            "output_tokens": 1,
            "billed_cost": 0.01,
            "cost_source": "provider_billed",
            "provider_usage": _openrouter_exact_evidence(
                0.01,
                f"generation-{index}",
            ),
        }
        for index in range(4)
    ]
    done = DoneEvent(
        input_tokens=sum(int(row["input_tokens"]) for row in rows),
        output_tokens=sum(int(row["output_tokens"]) for row in rows),
        billed_cost=sum(float(row["billed_cost"]) for row in rows),
        cost_source="provider_billed",
        model="model-final",
        provider="openrouter",
        model_usage_breakdown=rows,
        ensemble_trace={"llm_request_count": expected_requests},
    )
    result = runner.RunResult(final_text="answer", done=done)
    attempts = [
        {
            "attempt": 1,
            "retryable": False,
            "retry_reason": "",
            "will_retry": False,
            "retry_backoff_s": 0.0,
            "run": runner.run_result_summary(result),
        }
    ]

    async def fake_build_experiment_provider(**_kwargs):
        return runner.ProviderBuildResult(provider=object(), prompt="prompt")

    async def fake_collect_generation_with_retries(*_args, **_kwargs):
        return result, attempts, 1

    judge_calls = 0

    async def fake_judge_text(**_kwargs):
        nonlocal judge_calls
        judge_calls += 1
        return {"total": 10.0}

    monkeypatch.setattr(runner, "build_experiment_provider", fake_build_experiment_provider)
    monkeypatch.setattr(
        runner,
        "collect_generation_with_retries",
        fake_collect_generation_with_retries,
    )
    monkeypatch.setattr(runner, "judge_text", fake_judge_text)

    row = await runner.run_one(
        task={"id": "task-1", "prompt": "prompt"},
        group="B3",
        config=config,
        inherited=inherited,
        dry_run=False,
        judge_provider=object(),
        judge_candidates=False,
        judge_repeats=1,
        judge_concurrency=1,
        judge_max_attempts=1,
        judge_semaphore=None,
        timeout=10.0,
        ensemble_proposer_timeout=None,
        ensemble_aggregator_timeout=None,
        ensemble_proposer_early_stop_success_count=None,
        ensemble_proposer_early_stop_after=None,
        expand_ensemble_timeouts_to_task_timeout=False,
        tool_policy={"tools_enabled": False, "tool_mode": "provider_only"},
        generation_policy={},
        require_openrouter_non_byok=strict,
    )

    assert judge_calls == expected_judge_calls
    assert row["error"] == expected_error
    assert (row.get("judge") is not None) is bool(expected_judge_calls)
    if strict:
        assert row["openrouter_non_byok_audit"]["pass"] is (not expected_error)
    else:
        assert "openrouter_non_byok_audit" not in row


@pytest.mark.asyncio
async def test_provider_build_failure_preserves_already_billed_setup_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, inherited = _openrouter_config()
    setup_usage = {
        "provider": "openrouter",
        "model": "anthropic/claude-opus-4.8",
        "input_tokens": 12,
        "output_tokens": 3,
        "billed_cost": 0.25,
        "cost_source": "provider_billed",
        "provider_usage": _openrouter_exact_evidence(0.25, "setup-receipt-1"),
    }

    async def fake_build_experiment_provider(**_kwargs):
        raise runner.ProviderBuildError(
            RuntimeError("strict dynamic selection failed"),
            setup_latency_ms=123,
            setup_usage=[setup_usage],
            routing_trace={"task_analyzer": {"model": setup_usage["model"]}},
        )

    judge_calls = 0

    async def fake_judge_text(**_kwargs):
        nonlocal judge_calls
        judge_calls += 1
        return {"total": 10.0}

    monkeypatch.setattr(runner, "build_experiment_provider", fake_build_experiment_provider)
    monkeypatch.setattr(runner, "judge_text", fake_judge_text)

    row = await runner.run_one(
        task={"id": "task-1", "prompt": "prompt"},
        group="G1",
        config=config,
        inherited=inherited,
        dry_run=False,
        judge_provider=object(),
        judge_candidates=False,
        judge_repeats=1,
        judge_concurrency=1,
        judge_max_attempts=1,
        judge_semaphore=None,
        timeout=10.0,
        ensemble_proposer_timeout=None,
        ensemble_aggregator_timeout=None,
        ensemble_proposer_early_stop_success_count=None,
        ensemble_proposer_early_stop_after=None,
        expand_ensemble_timeouts_to_task_timeout=False,
        tool_policy={"tools_enabled": False, "tool_mode": "provider_only"},
        generation_policy={},
        require_openrouter_non_byok=True,
    )

    assert row["error"] == "RuntimeError: strict dynamic selection failed"
    assert row["llm_request_count"] == 1
    assert row["execution"]["routing_setup_latency_ms"] == 123
    assert row["usage"]["model_usage_breakdown"] == [setup_usage]
    assert runner.openrouter_non_byok_audit(row)["pass"] is True
    assert judge_calls == 0


@pytest.mark.parametrize("module", [runner, _load_resume_runner()], ids=["main", "resume"])
def test_openrouter_exact_receipt_requires_billed_and_reported_cost_match(module) -> None:
    usage = {
        "provider": "openrouter",
        "model": "model-a",
        "input_tokens": 3,
        "output_tokens": 1,
        "billed_cost": 0.0,
        "cost_source": "provider_billed",
        "provider_usage": _openrouter_exact_evidence(0.25, "mismatch-1"),
    }

    accounting = module.usage_cost_accounting(
        usage,
        expected_requests=1,
        scope="generation",
    )

    assert accounting["exact_request_count"] == 0
    assert accounting["unknown_request_count"] == 1
    assert accounting["cost_exact"] is False


def test_done_payload_keeps_provider_for_single_exact_receipt() -> None:
    done = runner.DoneEvent(
        provider="openrouter",
        model="model-a",
        input_tokens=3,
        output_tokens=1,
        billed_cost=0.25,
        cost_source="provider_billed",
        provider_usage=_openrouter_exact_evidence(0.25, "single-1"),
    )

    payload = runner.done_payload(done)

    assert payload["provider"] == "openrouter"
    assert runner.usage_cost_accounting(
        payload,
        expected_requests=1,
        scope="generation",
    )["cost_exact"] is True


def test_b2_provider_alignment_pins_effective_member_configuration() -> None:
    config, inherited = _openrouter_config()
    provider = build_ensemble_provider_from_config(
        config=config,
        inherited_provider_config=inherited,
        fallback_provider=None,
    )
    assert provider.min_successful_proposers == 3
    assert provider.quorum_grace_seconds == 5.0

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
    assert len(manifest["source_provenance"]["runner_sha256"]) == 64
    assert "git_head" in manifest["source_provenance"]


def test_manifest_reuses_source_provenance_frozen_at_process_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runner.build_parser().parse_args(
        ["--input", "tasks.jsonl", "--groups", "B1"]
    )
    args._source_provenance = {
        "runner_path": "/frozen/runner.py",
        "runner_sha256": "a" * 64,
        "git_head": "b" * 40,
        "git_dirty": False,
        "source_tree_sha256": "c" * 64,
    }
    monkeypatch.setattr(
        runner,
        "source_provenance",
        lambda: {"runner_sha256": "changed-after-start"},
    )
    path = tmp_path / "manifest.json"

    runner.write_manifest(
        path,
        args=args,
        stamp="test",
        status="complete",
        started_at=1.0,
        tasks=[{"id": "task-1"}],
        groups=["B1"],
        artifacts={},
    )

    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["source_provenance"] == args._source_provenance


def test_source_provenance_detects_tracked_changes_against_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            stdout = "a" * 40 + "\n"
        elif command[:3] == ["git", "diff", "--binary"]:
            stdout = "tracked diff\n"
        else:
            stdout = ""
        return runner.subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    provenance = runner.source_provenance()

    diff_command = next(command for command in commands if command[1] == "diff")
    assert diff_command.count("HEAD") == 1
    assert provenance["git_tracked_dirty"] is True
    assert provenance["git_dirty"] is True


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
