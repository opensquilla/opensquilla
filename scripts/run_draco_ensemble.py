#!/usr/bin/env python3
"""Run DRACO-style B5 ensemble experiments from an external JSONL file."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opensquilla.engine.agent import Agent
from opensquilla.engine.types import (
    THINKING_BUDGETS,
    AgentConfig,
    DoneEvent as AgentDoneEvent,
    ErrorEvent as AgentErrorEvent,
    RunHeartbeatEvent as AgentRunHeartbeatEvent,
    StateChangeEvent as AgentStateChangeEvent,
    TextDeltaEvent as AgentTextDeltaEvent,
    ThinkingEvent as AgentThinkingEvent,
    ThinkingLevel,
    ToolResultEvent as AgentToolResultEvent,
    ToolUseDeltaEvent as AgentToolUseDeltaEvent,
    ToolUseStartEvent as AgentToolUseStartEvent,
    WarningEvent as AgentWarningEvent,
)
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config
from opensquilla.provider.ensemble import build_ensemble_provider_from_config
from opensquilla.provider.selector import ModelSelector, ProviderConfig, SelectorConfig
from opensquilla.provider.types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ProviderHeartbeatEvent,
    ReasoningDeltaEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolInputSchema,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)
from opensquilla.result_budget import build_webresearch_tool_run_budget_policy
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import CallerKind, InteractionMode, ToolContext, ToolSpec

GROUP_SPECS: dict[str, dict[str, str]] = {
    "B0": {"kind": "single", "model": "anthropic/claude-opus-4.8"},
    "B1": {"kind": "single", "model": "openai/gpt-5.5"},
    "B2": {"kind": "single", "model": "z-ai/glm-5.2"},
    "B3": {"kind": "profile", "profile": "b3_glm_self_fusion"},
    "B4": {"kind": "single", "model": "deepseek/deepseek-v4-pro"},
    "B5": {"kind": "single", "model": "moonshotai/kimi-k2.7-code"},
    "B6": {"kind": "single", "model": "qwen/qwen3.7-max"},
    "B7": {"kind": "single", "model": "google/gemini-3.1-pro-preview"},
    "B8": {
        "kind": "single",
        "model": "z-ai/glm-5.2",
        "server_tool_profile": "openrouter_fusion",
    },
    "B9": {"kind": "single", "model": "anthropic/claude-fable-5"},
    "B10": {"kind": "single", "model": "sakana/fugu-ultra"},
    "B11": {
        "kind": "single",
        "model": "MoM",
        "provider": "vllm",
        "base_url": "http://127.0.0.1:8888/v1",
        "api_key": "dummy",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "B12": {"kind": "single", "model": "openai/gpt-5.6-sol"},
    "G1": {"kind": "profile", "profile": "g1_code"},
    "G2": {"kind": "profile", "profile": "g2_general"},
    "G3": {"kind": "profile", "profile": "g3_standard"},
    "G4": {"kind": "profile", "profile": "g4_gemini_aggregator"},
    "G5": {"kind": "profile", "profile": "g5_opus_aggregator"},
    "G6": {"kind": "profile", "profile": "g6_gpt_aggregator"},
    "G7": {"kind": "profile", "profile": "g7_two_proposers"},
    "G8": {"kind": "profile", "profile": "g8_four_proposers"},
    "G9": {"kind": "profile", "profile": "g9_qwen_aggregator"},
    "G10": {"kind": "profile", "profile": "g10_gemini_aggregator"},
    "G11": {"kind": "profile", "profile": "g11_deepseek_aggregator"},
    "G12": {"kind": "profile", "profile": "g12_k2_replace_gemini"},
    "G13": {"kind": "profile", "profile": "g13_five_proposers"},
    "G14": {"kind": "profile", "profile": "g14_k2_replace_qwen"},
    "G15": {"kind": "profile", "profile": "g15_g8_top3_prefilter"},
    "G16": {"kind": "profile", "profile": "g16_sampled_cheap_proposers"},
    "G17": {"kind": "profile", "profile": "g17_two_layer_moa"},
    "G18": {"kind": "profile", "profile": "g18_select_best_candidate"},
    "G19": {"kind": "profile", "profile": "g19_g12_top3_prefilter"},
    "G20": {"kind": "profile", "profile": "g20_g12_top2_prefilter"},
    "G21": {"kind": "profile", "profile": "g21_g13_top3_prefilter"},
    "G22": {"kind": "profile", "profile": "g22_g12_glm_top3_prefilter"},
    "G23": {"kind": "profile", "profile": "g23_g12_plus_gemini_sampled_top3_prefilter"},
    "G24": {"kind": "profile", "profile": "g24_g12_drop_k2_7_code"},
    "G25": {"kind": "profile", "profile": "g25_g12_drop_qwen3_7"},
}

TOOL_MODE_PROVIDER_ONLY = "provider_only"
TOOL_MODE_OPENROUTER_SERVER_TOOLS = "openrouter_server_tools"
TOOL_MODE_LOCAL_WEB_TOOLS = "local_web_tools"
RUNNER_MODE = TOOL_MODE_PROVIDER_ONLY
RUNNER_MODE_PROVIDER = "provider"
RUNNER_MODE_AGENT_LOOP = "agent_loop"
DEFAULT_DRACO_RUNNER_MODE = RUNNER_MODE_AGENT_LOOP
DEFAULT_AGENT_MAX_ITERATIONS = 12
SUPPORTED_RUNNER_MODES = (RUNNER_MODE_PROVIDER, RUNNER_MODE_AGENT_LOOP)
SUPPORTED_TOOL_MODES = (
    TOOL_MODE_PROVIDER_ONLY,
    TOOL_MODE_OPENROUTER_SERVER_TOOLS,
    TOOL_MODE_LOCAL_WEB_TOOLS,
)
DEFAULT_OPENROUTER_WEB_SEARCH_ENGINE = "exa"
DEFAULT_OPENROUTER_WEB_SEARCH_MAX_RESULTS = 5
DEFAULT_OPENROUTER_WEB_SEARCH_MAX_TOTAL_RESULTS = 10
DEFAULT_OPENROUTER_WEB_SEARCH_CONTEXT_SIZE = "medium"
DEFAULT_LOCAL_WEB_SEARCH_PROVIDER = "duckduckgo"
SUPPORTED_LOCAL_WEB_SEARCH_PROVIDERS = ("duckduckgo", "brave")
DEFAULT_OPENROUTER_WEB_FETCH_ENGINE = "openrouter"
DEFAULT_OPENROUTER_WEB_FETCH_MAX_USES = 5
DEFAULT_OPENROUTER_WEB_FETCH_MAX_CONTENT_TOKENS = 50_000
DEFAULT_OPENROUTER_FUSION_ANALYSIS_MODELS = (
    "deepseek/deepseek-v4-pro",
    "z-ai/glm-5.2",
    "google/gemini-3.1-pro-preview",
    "qwen/qwen3.7-max",
)
DEFAULT_OPENROUTER_FUSION_MODEL = "z-ai/glm-5.2"
DEFAULT_OPENROUTER_FUSION_MAX_TOOL_CALLS = 12
DEFAULT_OPENROUTER_FUSION_MAX_COMPLETION_TOKENS = 16_384
DEFAULT_OPENROUTER_FUSION_REASONING_EFFORT = "xhigh"
DEFAULT_OPENROUTER_FUSION_TEMPERATURE = 0.0
GENERATION_THINKING_MODEL_MAX = "model_max"
DEFAULT_GENERATION_THINKING = GENERATION_THINKING_MODEL_MAX
DEFAULT_GENERATION_THINKING_FALLBACK = "xhigh"
DEFAULT_MODEL_MAX_GENERATION_THINKING: dict[str, str] = {
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
DEFAULT_GENERATION_TEMPERATURE = 0.0
DEFAULT_CONTAMINATION_BLOCKED_DOMAINS = (
    "hf.co",
    "huggingface.co",
    "datasets-server.huggingface.co",
    "github.com",
    "raw.githubusercontent.com",
    "openrouter.ai",
    "perplexity.ai",
    "research.perplexity.ai",
)
PROFILE_TIMEOUT_MARGIN_SECONDS = 30.0
DEFAULT_PROFILE_PROPOSER_TIMEOUT_SECONDS = 120.0
DEFAULT_PROFILE_AGGREGATOR_TIMEOUT_SECONDS = 300.0
JUDGE_MAX_ATTEMPTS = 3
GENERATION_MAX_ATTEMPTS = 3
DEFAULT_GENERATION_RETRY_BACKOFF_SECONDS = 2.0
GENERATION_EMPTY_OUTPUT_ERROR = "empty_generation_output"
GENERATION_MISSING_DONE_ERROR = "generation_missing_done"


class _BenchmarkApprovalQueue:
    """Non-interactive approval queue for unattended benchmark runs."""

    def request(self, namespace: str = "exec", params: dict | None = None) -> str:
        return "draco-benchmark:auto-deny"

    async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
        return False

    def resolve(self, approval_id: str, approved: bool) -> None:
        return None


@dataclass
class RunResult:
    final_text: str
    done: DoneEvent | None
    error: str = ""
    latency_ms: int = 0
    ttft_ms: int | None = None
    tool_call_count: int = 0
    trace_events: list[dict[str, Any]] = field(default_factory=list)


class DryProvider:
    provider_name = "dry"

    def __init__(self, model: str, group: str) -> None:
        self.model = model
        self.group = group

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001
        prompt = str(messages[-1].content if messages else "")
        text = f"[dry:{self.group}:{self.model}] {prompt[:160]}"
        yield TextDeltaEvent(text=text)
        yield DoneEvent(
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(text) // 4),
            model=self.model,
            cost_source="none",
        )

    async def list_models(self) -> list[Any]:
        return []


class DryEnsembleProvider:
    provider_name = "dry_ensemble"

    def __init__(self, *, group: str, profile: str, model: str = "dry-aggregator") -> None:
        self.group = group
        self.profile = profile
        self.model = model

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001
        prompt = str(messages[-1].content if messages else "")
        candidates = [
            {
                "index": 0,
                "sample_index": 0,
                "label": "proposer_1",
                "provider": "dry",
                "model": "dry-proposer-a",
                "ok": True,
                "text": f"Candidate A for {prompt[:80]}",
                "input_tokens": 10,
                "output_tokens": 8,
                "billed_cost": 0.0,
                "cost_source": "none",
            },
            {
                "index": 1,
                "sample_index": 0,
                "label": "proposer_2",
                "provider": "dry",
                "model": "dry-proposer-b",
                "ok": True,
                "text": f"Candidate B for {prompt[:80]}",
                "input_tokens": 11,
                "output_tokens": 8,
                "billed_cost": 0.0,
                "cost_source": "none",
            },
        ]
        text = f"[dry:{self.group}:{self.profile}] fused answer for {prompt[:120]}"
        yield TextDeltaEvent(text=text)
        yield DoneEvent(
            input_tokens=42,
            output_tokens=max(1, len(text) // 4),
            model=self.model,
            model_usage_breakdown=[
                {
                    "role": "proposer",
                    "model": "dry-proposer-a",
                    "input_tokens": 10,
                    "output_tokens": 8,
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                    "billed_cost": 0.0,
                    "cost_source": "none",
                },
                {
                    "role": "proposer",
                    "model": "dry-proposer-b",
                    "input_tokens": 11,
                    "output_tokens": 8,
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                    "billed_cost": 0.0,
                    "cost_source": "none",
                },
                {
                    "role": "aggregator",
                    "model": self.model,
                    "input_tokens": 21,
                    "output_tokens": max(1, len(text) // 4),
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                    "billed_cost": 0.0,
                    "cost_source": "none",
                },
            ],
            ensemble_trace={
                "mode": "b5_fusion",
                "profile": self.profile,
                "successful_proposers": 2,
                "total_candidates": 2,
                "fallback_used": False,
                "candidates": candidates,
                "shuffle_candidates": False,
                "final_request_role": "aggregator",
                "llm_request_count": 3,
            },
        )

    async def list_models(self) -> list[Any]:
        return []


def load_tasks(path: Path, *, max_tasks: int = 0) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        payload = json.loads(line)
        task_id = str(payload.get("id") or payload.get("task_id") or "").strip()
        prompt = str(payload.get("prompt") or payload.get("problem") or "").strip()
        if not task_id or not prompt:
            raise ValueError(f"{path}:{lineno} requires non-empty id/task_id and prompt/problem")
        payload["id"] = task_id
        payload["prompt"] = prompt
        if "rubric" in payload:
            payload["rubric"] = parse_maybe_json(payload["rubric"])
        elif "answer" in payload:
            payload["rubric"] = parse_maybe_json(payload["answer"])
        tasks.append(payload)
        if max_tasks and len(tasks) >= max_tasks:
            break
    return tasks


def parse_groups(raw: str) -> list[str]:
    groups = [item.strip().upper() for item in raw.split(",") if item.strip()]
    unknown = [group for group in groups if group not in GROUP_SPECS]
    if unknown:
        raise ValueError(f"unknown group(s): {', '.join(unknown)}")
    return groups


def normalize_domain(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or parsed.netloc
    else:
        host = raw.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
        host = urlparse(f"//{host}").hostname or host
    return host.strip().lstrip("*.").strip(".")


def parse_domain_list(raw: Any) -> list[str]:
    if raw is None:
        values: list[Any] = list(DEFAULT_CONTAMINATION_BLOCKED_DOMAINS)
    elif isinstance(raw, str):
        values = raw.split(",")
    else:
        values = list(raw)
    domains: list[str] = []
    for value in values:
        domain = normalize_domain(value)
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def positive_int_value(raw: Any, *, default: int, field: str) -> int:
    value = default if raw is None else raw
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def bounded_int_value(
    raw: Any,
    *,
    default: int,
    field: str,
    minimum: int,
    maximum: int,
) -> int:
    value = positive_int_value(raw, default=default, field=field)
    if value < minimum or value > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def parse_csv_values(raw: Any, *, default: tuple[str, ...] = ()) -> list[str]:
    value = raw if raw is not None else ",".join(default)
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, tuple | list):
        candidates = list(value)
    else:
        candidates = [str(value)]
    items: list[str] = []
    for candidate in candidates:
        item = str(candidate).strip()
        if item and item not in items:
            items.append(item)
    return items


def float_range_value(
    raw: Any,
    *,
    default: float,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    value = default if raw is None else raw
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def approx_chars_for_content_tokens(tokens: int) -> int:
    return max(100, int(tokens) * 4)


def openrouter_server_tool_settings(
    args: argparse.Namespace | None,
    *,
    blocked_domains: list[str],
) -> dict[str, Any]:
    search_context_size = str(
        getattr(
            args,
            "openrouter_web_search_context_size",
            DEFAULT_OPENROUTER_WEB_SEARCH_CONTEXT_SIZE,
        )
        or DEFAULT_OPENROUTER_WEB_SEARCH_CONTEXT_SIZE
    ).strip().lower()
    if search_context_size not in {"low", "medium", "high"}:
        raise ValueError(
            "openrouter_web_search_context_size must be one of: low, medium, high"
        )
    web_search = {
        "type": "openrouter:web_search",
        "parameters": {
            "engine": str(
                getattr(
                    args,
                    "openrouter_web_search_engine",
                    DEFAULT_OPENROUTER_WEB_SEARCH_ENGINE,
                )
                or DEFAULT_OPENROUTER_WEB_SEARCH_ENGINE
            ).strip(),
            "max_results": positive_int_value(
                getattr(args, "openrouter_web_search_max_results", None),
                default=DEFAULT_OPENROUTER_WEB_SEARCH_MAX_RESULTS,
                field="openrouter_web_search_max_results",
            ),
            "max_total_results": positive_int_value(
                getattr(args, "openrouter_web_search_max_total_results", None),
                default=DEFAULT_OPENROUTER_WEB_SEARCH_MAX_TOTAL_RESULTS,
                field="openrouter_web_search_max_total_results",
            ),
            "search_context_size": search_context_size,
            "excluded_domains": blocked_domains,
        },
    }
    web_fetch = {
        "type": "openrouter:web_fetch",
        "parameters": {
            "engine": str(
                getattr(
                    args,
                    "openrouter_web_fetch_engine",
                    DEFAULT_OPENROUTER_WEB_FETCH_ENGINE,
                )
                or DEFAULT_OPENROUTER_WEB_FETCH_ENGINE
            ).strip(),
            "max_uses": positive_int_value(
                getattr(args, "openrouter_web_fetch_max_uses", None),
                default=DEFAULT_OPENROUTER_WEB_FETCH_MAX_USES,
                field="openrouter_web_fetch_max_uses",
            ),
            "max_content_tokens": positive_int_value(
                getattr(args, "openrouter_web_fetch_max_content_tokens", None),
                default=DEFAULT_OPENROUTER_WEB_FETCH_MAX_CONTENT_TOKENS,
                field="openrouter_web_fetch_max_content_tokens",
            ),
            "blocked_domains": blocked_domains,
        },
    }
    return {
        "web_search": web_search,
        "web_fetch": web_fetch,
    }


def openrouter_fusion_tool_settings(args: argparse.Namespace | None) -> dict[str, Any]:
    analysis_models = parse_csv_values(
        getattr(args, "openrouter_fusion_analysis_models", None),
        default=DEFAULT_OPENROUTER_FUSION_ANALYSIS_MODELS,
    )
    if not 1 <= len(analysis_models) <= 8:
        raise ValueError("openrouter_fusion_analysis_models must contain 1 to 8 models")
    judge_model = str(
        getattr(args, "openrouter_fusion_model", DEFAULT_OPENROUTER_FUSION_MODEL)
        or DEFAULT_OPENROUTER_FUSION_MODEL
    ).strip()
    if not judge_model:
        raise ValueError("openrouter_fusion_model must not be empty")
    reasoning_effort = str(
        getattr(
            args,
            "openrouter_fusion_reasoning_effort",
            DEFAULT_OPENROUTER_FUSION_REASONING_EFFORT,
        )
        or DEFAULT_OPENROUTER_FUSION_REASONING_EFFORT
    ).strip().lower()
    if reasoning_effort not in {"minimal", "low", "medium", "high", "xhigh", "max"}:
        raise ValueError(
            "openrouter_fusion_reasoning_effort must be one of: "
            "minimal, low, medium, high, xhigh, max"
        )
    return {
        "type": "openrouter:fusion",
        "parameters": {
            "analysis_models": analysis_models,
            "model": judge_model,
            "max_tool_calls": bounded_int_value(
                getattr(args, "openrouter_fusion_max_tool_calls", None),
                default=DEFAULT_OPENROUTER_FUSION_MAX_TOOL_CALLS,
                field="openrouter_fusion_max_tool_calls",
                minimum=1,
                maximum=16,
            ),
            "max_completion_tokens": positive_int_value(
                getattr(args, "openrouter_fusion_max_completion_tokens", None),
                default=DEFAULT_OPENROUTER_FUSION_MAX_COMPLETION_TOKENS,
                field="openrouter_fusion_max_completion_tokens",
            ),
            "reasoning": {"effort": reasoning_effort},
            "temperature": float_range_value(
                getattr(args, "openrouter_fusion_temperature", None),
                default=DEFAULT_OPENROUTER_FUSION_TEMPERATURE,
                field="openrouter_fusion_temperature",
                minimum=0.0,
                maximum=2.0,
            ),
        },
    }


def benchmark_tool_policy(args: argparse.Namespace | None = None) -> dict[str, Any]:
    mode = str(getattr(args, "tool_mode", RUNNER_MODE) or RUNNER_MODE).strip()
    blocked_domains = parse_domain_list(
        getattr(args, "contamination_blocked_domains", None)
    )
    if mode not in SUPPORTED_TOOL_MODES:
        raise ValueError(f"unknown tool mode: {mode}")
    if mode == TOOL_MODE_LOCAL_WEB_TOOLS:
        if not blocked_domains:
            raise ValueError(
                "DRACO research-tool runs require contamination-blocked domains"
            )
        local_search_max_results = positive_int_value(
            getattr(args, "openrouter_web_search_max_results", None),
            default=DEFAULT_OPENROUTER_WEB_SEARCH_MAX_RESULTS,
            field="openrouter_web_search_max_results",
        )
        local_search_provider = str(
            getattr(args, "local_web_search_provider", DEFAULT_LOCAL_WEB_SEARCH_PROVIDER)
            or DEFAULT_LOCAL_WEB_SEARCH_PROVIDER
        ).strip() or DEFAULT_LOCAL_WEB_SEARCH_PROVIDER
        if local_search_provider not in SUPPORTED_LOCAL_WEB_SEARCH_PROVIDERS:
            raise ValueError(
                "local_web_search_provider must be one of: "
                f"{', '.join(SUPPORTED_LOCAL_WEB_SEARCH_PROVIDERS)}"
            )
        local_search_api_key_env = str(
            getattr(args, "local_web_search_api_key_env", "") or ""
        ).strip()
        local_fetch_max_content_tokens = positive_int_value(
            getattr(args, "openrouter_web_fetch_max_content_tokens", None),
            default=DEFAULT_OPENROUTER_WEB_FETCH_MAX_CONTENT_TOKENS,
            field="openrouter_web_fetch_max_content_tokens",
        )
        return {
            "tool_mode": mode,
            "tools_enabled": True,
            "tool_names": ["web_search", "web_fetch"],
            "local_web_tools": {
                "web_search": {
                    "excluded_domains": blocked_domains,
                    "max_results": local_search_max_results,
                    "provider": local_search_provider,
                    "api_key_env": local_search_api_key_env,
                },
                "web_fetch": {
                    "blocked_domains": blocked_domains,
                    "max_content_tokens": local_fetch_max_content_tokens,
                    "max_content_chars": approx_chars_for_content_tokens(
                        local_fetch_max_content_tokens
                    ),
                },
            },
            "contamination_blocked_domains": blocked_domains,
            "contamination_controls": {
                "status": "enforced_by_local_web_tools",
                "web_search_field": "excluded_domains_query_and_result_filter",
                "web_fetch_field": "blocked_domains",
            },
        }
    if mode == TOOL_MODE_OPENROUTER_SERVER_TOOLS:
        if not blocked_domains:
            raise ValueError(
                "DRACO research-tool runs require contamination-blocked domains"
            )
        server_tools = openrouter_server_tool_settings(
            args,
            blocked_domains=blocked_domains,
        )
        return {
            "tool_mode": mode,
            "tools_enabled": True,
            "tool_names": [
                server_tools["web_search"]["type"],
                server_tools["web_fetch"]["type"],
            ],
            "openrouter_server_tools": server_tools,
            "contamination_blocked_domains": blocked_domains,
            "contamination_controls": {
                "status": "enforced_by_openrouter_server_tools",
                "web_search_field": "excluded_domains",
                "web_fetch_field": "blocked_domains",
            },
        }
    return {
        "tool_mode": mode,
        "tools_enabled": False,
        "tool_names": [],
        "contamination_blocked_domains": blocked_domains,
        "contamination_controls": {
            "status": "not_applicable_no_external_tools",
            "web_search_field": "excluded_domains",
            "web_fetch_field": "blocked_domains",
        },
    }


def group_uses_openrouter_fusion(group: str) -> bool:
    spec = GROUP_SPECS[group]
    return spec.get("server_tool_profile") == "openrouter_fusion"


def validate_runner_mode_for_groups(runner_mode: str, groups: list[str]) -> None:
    if runner_mode != RUNNER_MODE_AGENT_LOOP:
        return
    fusion_groups = [group for group in groups if group_uses_openrouter_fusion(group)]
    if fusion_groups:
        raise ValueError(
            "OpenRouter Fusion experiment groups are provider-level server-side "
            "agent baselines; run "
            f"{','.join(fusion_groups)} with --runner-mode=provider"
        )


def benchmark_tool_policy_for_group(
    tool_policy: dict[str, Any],
    group: str,
    *,
    args: argparse.Namespace | None = None,
) -> dict[str, Any]:
    if not group_uses_openrouter_fusion(group):
        return tool_policy
    fusion_tool = openrouter_fusion_tool_settings(args)
    fusion_tool_name = str(fusion_tool.get("type") or "openrouter:fusion")
    return {
        **tool_policy,
        "tools_enabled": True,
        "tool_names": [fusion_tool_name],
        "openrouter_fusion_enabled": True,
        "openrouter_fusion_only": True,
        "openrouter_fusion_tool": fusion_tool,
        "openrouter_fusion_tool_choice": "required",
        "contamination_controls": {
            **dict(tool_policy.get("contamination_controls") or {}),
            "fusion_status": "internal_web_domain_controls_not_exposed",
            "fusion_internal_web_tools": (
                "openrouter_fusion_enables_internal_web_search_and_fetch; "
                "domain exclusion is not exposed in the documented fusion parameters"
            ),
        },
    }


def benchmark_tool_policies_for_groups(
    tool_policy: dict[str, Any],
    groups: list[str],
    *,
    args: argparse.Namespace | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        group: benchmark_tool_policy_for_group(tool_policy, group, args=args)
        for group in groups
    }


def _local_web_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="web_search",
            description=(
                "Search the web and return result titles, URLs, and snippets. "
                "Benchmark leakage domains are excluded and filtered."
            ),
            input_schema=ToolInputSchema(
                properties={
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return.",
                    },
                },
                required=["query"],
            ),
        ),
        ToolDefinition(
            name="web_fetch",
            description=(
                "Fetch a URL and extract readable content. Benchmark leakage "
                "domains are blocked."
            ),
            input_schema=ToolInputSchema(
                properties={
                    "url": {"type": "string", "description": "URL to fetch."},
                    "extract_mode": {
                        "type": "string",
                        "description": "Extraction mode, usually markdown.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return.",
                    },
                },
                required=["url"],
            ),
        ),
    ]


def _provider_tool_definition(
    provider_tool: dict[str, Any],
    *,
    description: str,
) -> ToolDefinition:
    tool_type = str(provider_tool.get("type") or "")
    return ToolDefinition(
        name=tool_type,
        description=description,
        input_schema=ToolInputSchema(),
        provider_tool=provider_tool,
    )


def benchmark_tools_for_policy(tool_policy: dict[str, Any]) -> list[ToolDefinition] | None:
    fusion_enabled = bool(tool_policy.get("openrouter_fusion_enabled"))
    if not tool_policy.get("tools_enabled") and not fusion_enabled:
        return None
    tools: list[ToolDefinition] = []
    if (
        tool_policy.get("tool_mode") == TOOL_MODE_LOCAL_WEB_TOOLS
        and not tool_policy.get("openrouter_fusion_only")
    ):
        tools.extend(_local_web_tool_definitions())
    server_tools = tool_policy.get("openrouter_server_tools") or {}
    if not tool_policy.get("openrouter_fusion_only"):
        for key, description in (
            ("web_search", "OpenRouter server-side web search."),
            ("web_fetch", "OpenRouter server-side web fetch."),
        ):
            provider_tool = server_tools.get(key)
            if not isinstance(provider_tool, dict):
                continue
            tools.append(_provider_tool_definition(provider_tool, description=description))
    fusion_tool = tool_policy.get("openrouter_fusion_tool")
    if fusion_enabled and isinstance(fusion_tool, dict):
        tools.append(
            _provider_tool_definition(
                fusion_tool,
                description=(
                    "OpenRouter Fusion server-side multi-model deliberation."
                ),
            )
        )
    return tools or None


def local_web_search_max_results(tool_policy: dict[str, Any]) -> int:
    local_policy = tool_policy.get("local_web_tools") or {}
    search_defaults = local_policy.get("web_search") or {}
    return positive_int_value(
        search_defaults.get("max_results"),
        default=DEFAULT_OPENROUTER_WEB_SEARCH_MAX_RESULTS,
        field="local_web_search_max_results",
    )


def local_web_search_provider(tool_policy: dict[str, Any]) -> str:
    local_policy = tool_policy.get("local_web_tools") or {}
    search_defaults = local_policy.get("web_search") or {}
    provider = str(
        search_defaults.get("provider") or DEFAULT_LOCAL_WEB_SEARCH_PROVIDER
    ).strip() or DEFAULT_LOCAL_WEB_SEARCH_PROVIDER
    if provider not in SUPPORTED_LOCAL_WEB_SEARCH_PROVIDERS:
        raise ValueError(
            "local_web_search_provider must be one of: "
            f"{', '.join(SUPPORTED_LOCAL_WEB_SEARCH_PROVIDERS)}"
        )
    return provider


def local_web_search_api_key_env(tool_policy: dict[str, Any]) -> str:
    local_policy = tool_policy.get("local_web_tools") or {}
    search_defaults = local_policy.get("web_search") or {}
    return str(search_defaults.get("api_key_env") or "").strip()


def local_web_fetch_max_chars(tool_policy: dict[str, Any]) -> int:
    local_policy = tool_policy.get("local_web_tools") or {}
    fetch_defaults = local_policy.get("web_fetch") or {}
    chars = fetch_defaults.get("max_content_chars")
    if isinstance(chars, int | float) and not isinstance(chars, bool):
        return max(100, int(chars))
    tokens = positive_int_value(
        fetch_defaults.get("max_content_tokens"),
        default=DEFAULT_OPENROUTER_WEB_FETCH_MAX_CONTENT_TOKENS,
        field="local_web_fetch_max_content_tokens",
    )
    return approx_chars_for_content_tokens(tokens)


def bounded_tool_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        if isinstance(value, bool):
            parsed = default
        elif isinstance(value, int | float):
            parsed = int(value)
        else:
            parsed = int(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def configure_local_web_search_runtime(
    config: GatewayConfig,
    tool_policy: dict[str, Any],
) -> dict[str, Any]:
    if tool_policy.get("tool_mode") != TOOL_MODE_LOCAL_WEB_TOOLS:
        return {}

    import opensquilla.search.providers.brave  # noqa: F401
    import opensquilla.search.providers.duckduckgo  # noqa: F401
    from opensquilla.search.registry import get_provider_spec
    from opensquilla.tools.builtin.web import configure_search

    configured_provider = local_web_search_provider(tool_policy)
    provider = configured_provider
    env_key = local_web_search_api_key_env(tool_policy)
    if not env_key:
        env_key = str(getattr(config, "search_api_key_env", "") or "").strip()
    try:
        spec = get_provider_spec(provider)
    except Exception as exc:
        raise ValueError(f"unknown local web search provider: {provider}") from exc
    if not spec.runtime_supported:
        raise ValueError(f"local web search provider is not runtime-supported: {provider}")
    api_key = ""
    api_key_source = ""
    if spec.requires_api_key:
        api_key = str(getattr(config, "search_api_key", "") or "").strip()
        api_key_source = "config" if api_key else ""
        if not api_key:
            if not env_key:
                env_key = str(getattr(spec, "env_key", "") or "").strip()
            if env_key and os.environ.get(env_key):
                api_key = str(os.environ.get(env_key) or "")
                api_key_source = f"env:{env_key}"
        if not api_key:
            env_hint = env_key or getattr(spec, "env_key", "") or "the provider API key env var"
            raise ValueError(
                f"local web search provider '{provider}' requires an API key; "
                f"set {env_hint} or choose --local-web-search-provider duckduckgo"
            )
    else:
        env_key = ""

    runtime_max_results = local_web_search_max_results(tool_policy)
    proxy = str(getattr(config, "search_proxy", "") or "").strip()
    fallback_policy = str(getattr(config, "search_fallback_policy", "off") or "off")
    diagnostics = bool(getattr(config, "search_diagnostics", False))
    use_env_proxy = bool(getattr(config, "search_use_env_proxy", False))
    configure_search(
        provider_name=provider,
        max_results=runtime_max_results,
        api_key=api_key,
        proxy=proxy,
        use_env_proxy=use_env_proxy,
        fallback_policy=fallback_policy,
        diagnostics=diagnostics,
    )
    return {
        "configured_provider": configured_provider,
        "provider": provider,
        "max_results": runtime_max_results,
        "api_key_configured": bool(api_key),
        "api_key_source": api_key_source,
        "api_key_env": env_key,
        "proxy_configured": bool(proxy),
        "use_env_proxy": use_env_proxy,
        "fallback_policy": fallback_policy,
        "diagnostics": diagnostics,
    }


def configure_benchmark_sandbox_runtime(
    config: GatewayConfig,
    tool_policy: dict[str, Any],
) -> dict[str, Any]:
    if tool_policy.get("tool_mode") != TOOL_MODE_LOCAL_WEB_TOOLS:
        return {}

    from opensquilla.sandbox.integration import configure_runtime

    workspace = Path(config.workspace_dir) if config.workspace_dir else ROOT
    runtime = configure_runtime(
        config.sandbox,
        approval_queue=_BenchmarkApprovalQueue(),
        workspace=workspace,
    )
    return {
        "configured": True,
        "backend": runtime.backend.name,
        "workspace": str(runtime.workspace),
        "approval_queue": "auto_deny_unattended",
        "effective": runtime.effective.as_dict(),
    }


def blocked_domain_match(url: str, blocked_domains: list[str]) -> str:
    domain = normalize_domain(url)
    if not domain:
        return ""
    for blocked in blocked_domains:
        if domain == blocked or domain.endswith(f".{blocked}"):
            return blocked
    return ""


def append_search_exclusions(query: str, blocked_domains: list[str]) -> str:
    clean_query = str(query or "").strip()
    exclusions = " ".join(f"-site:{domain}" for domain in blocked_domains if domain)
    return f"{clean_query} {exclusions}".strip() if exclusions else clean_query


def filter_blocked_search_results(
    payload: dict[str, Any],
    *,
    blocked_domains: list[str],
    original_query: str,
    executed_query: str,
) -> dict[str, Any]:
    filtered = dict(payload)
    results = filtered.get("results")
    removed: list[dict[str, str]] = []
    kept: list[Any] = []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            match = blocked_domain_match(str(item.get("url") or ""), blocked_domains)
            if match:
                removed.append(
                    {
                        "url": str(item.get("url") or ""),
                        "blocked_domain": match,
                    }
                )
            else:
                kept.append(item)
        filtered["results"] = kept
    filtered["query"] = original_query
    filtered["executed_query"] = executed_query
    filtered["blocked_domains"] = blocked_domains
    filtered["blocked_result_count"] = len(removed)
    if removed:
        filtered["blocked_results"] = removed
    return filtered


def build_local_web_tool_registry(tool_policy: dict[str, Any]) -> ToolRegistry:
    registry = ToolRegistry()
    blocked_domains = parse_domain_list(
        tool_policy.get("contamination_blocked_domains") or []
    )
    default_max_results = local_web_search_max_results(tool_policy)
    default_fetch_max_chars = local_web_fetch_max_chars(tool_policy)

    async def _web_search(query: str, max_results: int | None = None) -> str:
        from opensquilla.tools.builtin.web import run_web_search_payload

        original_query = str(query or "")
        executed_query = append_search_exclusions(original_query, blocked_domains)
        limit = bounded_tool_int(
            max_results,
            default=default_max_results,
            minimum=1,
            maximum=default_max_results,
        )
        payload = await run_web_search_payload(executed_query, limit)
        filtered = filter_blocked_search_results(
            payload,
            blocked_domains=blocked_domains,
            original_query=original_query,
            executed_query=executed_query,
        )
        return json.dumps(filtered, ensure_ascii=False, indent=2)

    async def _web_fetch(
        url: str,
        extract_mode: str = "markdown",
        max_chars: int | None = None,
    ) -> str:
        from opensquilla.tools.builtin.web_fetch import web_fetch

        match = blocked_domain_match(str(url or ""), blocked_domains)
        if match:
            return json.dumps(
                {
                    "url": url,
                    "error_class": "BlockedDomain",
                    "error": (
                        "This URL belongs to a DRACO contamination-blocked domain "
                        f"({match}) and was not fetched."
                    ),
                    "blocked_domain": match,
                    "blocked_domains": blocked_domains,
                },
                ensure_ascii=False,
                indent=2,
            )
        effective_max_chars = bounded_tool_int(
            max_chars,
            default=default_fetch_max_chars,
            minimum=100,
            maximum=default_fetch_max_chars,
        )
        return await web_fetch(
            url,
            extract_mode=extract_mode,
            max_chars=effective_max_chars,
        )

    registry.register(
        ToolSpec(
            name="web_search",
            description=(
                "Search the web and return result titles, URLs, and snippets. "
                "Benchmark leakage domains are excluded and filtered."
            ),
            parameters={
                "query": {"type": "string", "description": "Search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                },
            },
            required=["query"],
            result_budget_class="external",
        ),
        _web_search,
    )
    registry.register(
        ToolSpec(
            name="web_fetch",
            description=(
                "Fetch a URL and extract readable content. Benchmark leakage "
                "domains are blocked."
            ),
            parameters={
                "url": {"type": "string", "description": "URL to fetch."},
                "extract_mode": {
                    "type": "string",
                    "description": "Extraction mode, usually markdown.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return.",
                },
            },
            required=["url"],
            result_budget_class="external",
        ),
        _web_fetch,
    )
    return registry


def build_benchmark_tool_context(
    *,
    task_id: str,
    group: str,
    tool_policy: dict[str, Any],
    output_dir: Path | None = None,
) -> ToolContext:
    scratch_dir = None
    if output_dir is not None:
        scratch_dir = str(output_dir / "scratch" / group / task_id)
    return ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        interaction_mode=InteractionMode.UNATTENDED,
        agent_id=f"draco-{group}",
        session_key=f"draco:{group}:{task_id}",
        task_id=task_id,
        allowed_tools={"web_search", "web_fetch"},
        workspace_dir=str(ROOT),
        workspace_strict=True,
        scratch_dir=scratch_dir,
        tool_run_budget_policy=build_webresearch_tool_run_budget_policy(
            max_single_fetch_chars=local_web_fetch_max_chars(tool_policy),
            max_web_search_results=local_web_search_max_results(tool_policy),
        ),
    )


def generation_thinking_policy(args: argparse.Namespace | None = None) -> dict[str, Any]:
    _ = args
    mode = DEFAULT_GENERATION_THINKING
    fallback_level = ThinkingLevel(DEFAULT_GENERATION_THINKING_FALLBACK)
    return {
        "generation_thinking": mode,
        "temperature": DEFAULT_GENERATION_TEMPERATURE,
        "thinking_enabled": True,
        "thinking_level": "model-specific",
        "default_thinking_level": fallback_level.value,
        "thinking_budget_tokens": "model-specific",
        "max_thinking_budget_tokens": THINKING_BUDGETS[ThinkingLevel.MAX],
        "model_thinking_levels": dict(DEFAULT_MODEL_MAX_GENERATION_THINKING),
        "applies_to": "single baselines and ensemble members",
    }


def _normalized_model_id(model: str | None) -> str:
    return str(model or "").strip().lower()


def generation_thinking_for_model(
    model: str | None,
    policy: dict[str, Any] | None = None,
) -> str:
    policy = policy or generation_thinking_policy()
    mode = str(policy.get("generation_thinking") or DEFAULT_GENERATION_THINKING)
    if mode != GENERATION_THINKING_MODEL_MAX:
        return mode
    raw_mapping = policy.get("model_thinking_levels")
    mapping = raw_mapping if isinstance(raw_mapping, dict) else {}
    normalized_mapping = {
        _normalized_model_id(str(key)): str(value)
        for key, value in mapping.items()
    }
    return normalized_mapping.get(
        _normalized_model_id(model),
        str(policy.get("default_thinking_level") or DEFAULT_GENERATION_THINKING_FALLBACK),
    )


def generation_chat_config(
    policy: dict[str, Any],
    *,
    model: str | None = None,
    tool_choice: Any | None = None,
) -> ChatConfig:
    mode = generation_thinking_for_model(model, policy)
    level = ThinkingLevel(mode)
    return ChatConfig(
        temperature=DEFAULT_GENERATION_TEMPERATURE,
        thinking=True,
        thinking_level=level,
        thinking_budget_tokens=THINKING_BUDGETS[level],
        tool_choice=tool_choice,
    )


def apply_generation_policy_to_profile(profile: Any, policy: dict[str, Any]) -> Any:
    preserve_temperature = bool(getattr(profile, "preserve_member_temperature", False))

    def _apply_member_policy(member: Any) -> Any:
        update: dict[str, Any] = {
            "temperature": DEFAULT_GENERATION_TEMPERATURE,
            "thinking": generation_thinking_for_model(
                str(getattr(member, "model", "") or ""),
                policy,
            ),
        }
        if preserve_temperature and getattr(member, "temperature", None) is not None:
            update.pop("temperature", None)
        return member.model_copy(update=update)

    proposers = [
        _apply_member_policy(proposer)
        for proposer in profile.proposers
    ]
    aggregator = _apply_member_policy(profile.aggregator)
    update: dict[str, Any] = {"proposers": proposers, "aggregator": aggregator}
    if getattr(profile, "candidate_scorer", None) is not None:
        update["candidate_scorer"] = _apply_member_policy(profile.candidate_scorer)
    return profile.model_copy(update=update)


def compact_chat_config(
    config: ChatConfig | None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ = policy
    if config is None:
        config = generation_chat_config(generation_thinking_policy())
    level = config.thinking_level
    return {
        "thinking": config.thinking,
        "thinking_level": level.value if isinstance(level, ThinkingLevel) else level,
        "thinking_budget_tokens": config.thinking_budget_tokens,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }


def profile_timeout_seconds(
    profile: Any,
    *,
    requested_timeout: float | None = None,
    proposer_timeout_override: float | None = None,
    aggregator_timeout_override: float | None = None,
    expand_to_requested_timeout: bool = False,
) -> tuple[float, float]:
    moa_layers = max(1, int(getattr(profile, "moa_layers", 1) or 1))
    proposer_timeout = max(
        DEFAULT_PROFILE_PROPOSER_TIMEOUT_SECONDS,
        float(getattr(profile, "proposer_timeout_seconds", 0) or 0),
    )
    aggregator_timeout = max(
        DEFAULT_PROFILE_AGGREGATOR_TIMEOUT_SECONDS,
        float(getattr(profile, "aggregator_timeout_seconds", 0) or 0),
    )
    if proposer_timeout_override is not None and proposer_timeout_override > 0:
        proposer_timeout = float(proposer_timeout_override)
    if aggregator_timeout_override is not None and aggregator_timeout_override > 0:
        aggregator_timeout = float(aggregator_timeout_override)
    if (
        not expand_to_requested_timeout
        or requested_timeout is None
        or requested_timeout <= 0
    ):
        return proposer_timeout, aggregator_timeout
    available = max(0.0, float(requested_timeout) - PROFILE_TIMEOUT_MARGIN_SECONDS)
    base_budget = proposer_timeout + aggregator_timeout * moa_layers
    if available <= base_budget:
        return proposer_timeout, aggregator_timeout
    extra = available - base_budget
    return (
        proposer_timeout + extra * 0.25,
        aggregator_timeout + (extra * 0.75 / moa_layers),
    )


def profile_aggregator_timeout_seconds(
    profile: Any,
    *,
    requested_timeout: float | None = None,
    aggregator_timeout_override: float | None = None,
    expand_to_requested_timeout: bool = False,
) -> float:
    return profile_timeout_seconds(
        profile,
        requested_timeout=requested_timeout,
        aggregator_timeout_override=aggregator_timeout_override,
        expand_to_requested_timeout=expand_to_requested_timeout,
    )[1]


def parse_maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def coerce_weight(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def rubric_criteria(task: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = task.get("rubric_items") or task.get("criteria")
    if isinstance(raw_items, list):
        return [
            item
            for index, raw in enumerate(raw_items, start=1)
            if (item := normalize_criterion(raw, index=index)) is not None
        ]
    rubric = parse_maybe_json(task.get("rubric"))
    if not isinstance(rubric, dict):
        return []
    items: list[dict[str, Any]] = []
    for section in rubric.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or "").strip()
        section_title = str(section.get("title") or section_id).strip()
        for raw in section.get("criteria") or []:
            item = normalize_criterion(
                raw,
                index=len(items) + 1,
                section_id=section_id,
                section_title=section_title,
            )
            if item is not None:
                items.append(item)
    return items


def normalize_criterion(
    raw: Any,
    *,
    index: int,
    section_id: str = "",
    section_title: str = "",
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    requirement = str(
        raw.get("requirement")
        or raw.get("criterion")
        or raw.get("description")
        or raw.get("text")
        or ""
    ).strip()
    if not requirement:
        return None
    return {
        "id": str(raw.get("id") or f"criterion-{index}"),
        "section_id": str(raw.get("section_id") or section_id or "rubric"),
        "section_title": str(raw.get("section_title") or section_title or section_id or "Rubric"),
        "weight": coerce_weight(raw.get("weight")),
        "requirement": requirement,
    }


def parse_verdict(value: Any) -> bool | None:
    verdict = str(value or "").strip().upper()
    if verdict in {"MET", "TRUE", "YES", "PASS", "PASSED", "1"}:
        return True
    if verdict in {"UNMET", "FALSE", "NO", "FAIL", "FAILED", "0"}:
        return False
    return None


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def normalize_legacy_judge_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    normalized.setdefault("mode", "legacy_dimension_score")
    normalized["score_scale"] = "0-100"

    scores = normalized.get("scores")
    score_values: list[float] = []
    if isinstance(scores, dict):
        score_values = [
            float(value) for value in scores.values() if isinstance(value, int | float)
        ]

    raw_total = normalized.get("total")
    if isinstance(raw_total, int | float):
        normalized["raw_total"] = float(raw_total)

    normalized_score: float | None = None
    if score_values:
        max_score = len(score_values) * 5.0
        normalized_score = sum(score_values) / max_score * 100.0 if max_score else None
    elif isinstance(raw_total, int | float):
        raw_float = float(raw_total)
        normalized_score = raw_float if raw_float > 20.0 else raw_float / 20.0 * 100.0

    if normalized_score is not None:
        normalized["normalized_score"] = clamp_percent(normalized_score)
        normalized["total"] = normalized["normalized_score"]
    return normalized


def inherited_provider_config(config: GatewayConfig) -> ProviderConfig:
    runtime = resolve_llm_runtime_config(config)
    base_url = runtime.base_url[:-3] if runtime.base_url.endswith("/v1") else runtime.base_url
    return ProviderConfig(
        provider=runtime.provider,
        model=runtime.model,
        api_key=runtime.api_key,
        base_url=base_url,
        proxy=runtime.proxy,
        provider_routing=runtime.provider_routing,
    )


def build_single_provider(
    *,
    inherited: ProviderConfig,
    group: str,
    model: str,
    dry_run: bool,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
):
    if dry_run:
        return DryProvider(model=model, group=group)
    resolved_api_key = api_key if api_key is not None else inherited.api_key
    if api_key_env:
        resolved_api_key = os.environ.get(api_key_env, resolved_api_key)
    cfg = ProviderConfig(
        provider=provider or inherited.provider,
        model=model,
        api_key=resolved_api_key,
        base_url=base_url or inherited.base_url,
        proxy=inherited.proxy,
        provider_routing=inherited.provider_routing if provider is None else {},
    )
    return ModelSelector(SelectorConfig(primary=cfg)).resolve()


def build_profile_provider(
    *,
    config: GatewayConfig,
    inherited: ProviderConfig,
    group: str,
    profile: str,
    dry_run: bool,
    generation_policy: dict[str, Any] | None = None,
    requested_timeout: float | None = None,
    enable_proposer_tools: bool = False,
    ensemble_proposer_timeout: float | None = None,
    ensemble_aggregator_timeout: float | None = None,
    ensemble_proposer_early_stop_success_count: int | None = None,
    ensemble_proposer_early_stop_after: float | None = None,
    expand_ensemble_timeouts_to_task_timeout: bool = False,
):
    if dry_run:
        return DryEnsembleProvider(group=group, profile=profile)
    if profile not in config.llm_ensemble.profiles:
        raise ValueError(f"profile {profile!r} for group {group} is not configured")
    config.llm_ensemble.enabled = True
    config.llm_ensemble.active_profile = profile
    config.llm_ensemble.proposer_tools = bool(enable_proposer_tools)
    profile_config = config.llm_ensemble.profiles[profile]
    if generation_policy is not None:
        profile_config = apply_generation_policy_to_profile(
            profile_config,
            generation_policy,
        )
    proposer_timeout_s, aggregator_timeout_s = profile_timeout_seconds(
        profile_config,
        requested_timeout=requested_timeout,
        proposer_timeout_override=ensemble_proposer_timeout,
        aggregator_timeout_override=ensemble_aggregator_timeout,
        expand_to_requested_timeout=expand_ensemble_timeouts_to_task_timeout,
    )
    profile_updates: dict[str, Any] = {
        "record_candidates": True,
        "shuffle_candidates": False,
        "proposer_timeout_seconds": proposer_timeout_s,
        "aggregator_timeout_seconds": aggregator_timeout_s,
    }
    if ensemble_proposer_early_stop_success_count is not None:
        profile_updates["proposer_early_stop_success_count"] = max(
            0,
            int(ensemble_proposer_early_stop_success_count or 0),
        )
    if ensemble_proposer_early_stop_after is not None:
        profile_updates["proposer_early_stop_after_seconds"] = max(
            0.0,
            float(ensemble_proposer_early_stop_after or 0.0),
        )
    config.llm_ensemble.profiles[profile] = profile_config.model_copy(
        update=profile_updates
    )
    fallback = build_single_provider(
        inherited=inherited,
        group=f"{group}-fallback",
        model=inherited.model,
        dry_run=False,
    )
    return build_ensemble_provider_from_config(
        config=config,
        inherited_provider_config=inherited,
        fallback_provider=fallback,
    )


async def collect_run(
    provider: Any,
    prompt: str,
    *,
    timeout: float,
    config: ChatConfig | None = None,
    tools: list[ToolDefinition] | None = None,
) -> RunResult:
    messages = [Message(role="user", content=prompt)]
    text_parts: list[str] = []
    done: DoneEvent | None = None
    error = ""
    ttft_ms: int | None = None
    tool_call_count = 0
    trace_events: list[dict[str, Any]] = []
    started = time.monotonic()

    def _trace(kind: str, **payload: Any) -> None:
        trace_events.append(
            {
                "seq": len(trace_events) + 1,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "kind": kind,
                **payload,
            }
        )

    try:
        chat_config = (
            config.model_copy(update={"timeout": timeout})
            if config is not None
            else ChatConfig(timeout=timeout)
        )
        stream = provider.chat(
            messages,
            tools=tools,
            config=chat_config,
        )
        async def _consume() -> None:
            nonlocal done, error, ttft_ms, tool_call_count
            async for event in stream:
                if isinstance(event, TextDeltaEvent):
                    if ttft_ms is None and event.text:
                        ttft_ms = int((time.monotonic() - started) * 1000)
                        _trace("first_text_delta", text_chars=len(event.text))
                    else:
                        _trace("text_delta", text_chars=len(event.text))
                    text_parts.append(event.text)
                elif isinstance(event, ReasoningDeltaEvent):
                    _trace("reasoning_delta", text_chars=len(event.text))
                elif isinstance(event, ToolUseStartEvent):
                    tool_call_count += 1
                    _trace(
                        "tool_use_start",
                        tool_use_id=event.tool_use_id,
                        tool_name=event.tool_name,
                        synthetic_from_text=event.synthetic_from_text,
                    )
                elif isinstance(event, ToolUseDeltaEvent):
                    _trace(
                        "tool_use_delta",
                        tool_use_id=event.tool_use_id,
                        json_fragment_chars=len(event.json_fragment),
                    )
                elif isinstance(event, ToolUseEndEvent):
                    _trace(
                        "tool_use_end",
                        tool_use_id=event.tool_use_id,
                        tool_name=event.tool_name,
                        argument_keys=sorted(event.arguments.keys()),
                        synthetic_from_text=event.synthetic_from_text,
                    )
                elif isinstance(event, ProviderHeartbeatEvent):
                    _trace(
                        "provider_heartbeat",
                        phase=event.phase,
                        message=event.message,
                    )
                elif isinstance(event, DoneEvent):
                    done = event
                    _trace(
                        "done",
                        stop_reason=event.stop_reason,
                        usage=done_payload(event),
                        has_ensemble_trace=bool(event.ensemble_trace),
                    )
                elif isinstance(event, ErrorEvent):
                    if done is None and isinstance(event.diagnostic_done, DoneEvent):
                        done = event.diagnostic_done
                        _trace(
                            "diagnostic_done",
                            stop_reason=done.stop_reason,
                            usage=done_payload(done),
                            has_ensemble_trace=bool(done.ensemble_trace),
                        )
                    error = event.message
                    _trace("error", message=event.message, code=event.code)
                    break
                else:
                    _trace("stream_event", event_type=type(event).__name__)

        if timeout and timeout > 0:
            try:
                async with asyncio.timeout(timeout):
                    await _consume()
            except TimeoutError:
                error = f"TimeoutError: run timed out after {timeout:g}s"
                _trace("timeout", timeout_s=timeout)
        else:
            await _consume()
    except Exception as exc:  # noqa: BLE001 - benchmark rows should keep going
        error = f"{type(exc).__name__}: {exc}"
        _trace("exception", error=error)
    return RunResult(
        final_text="".join(text_parts),
        done=done,
        error=error,
        latency_ms=int((time.monotonic() - started) * 1000),
        ttft_ms=ttft_ms,
        tool_call_count=tool_call_count,
        trace_events=trace_events,
    )


class BenchmarkTurnCallRecorder:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, kind: str, payload: dict[str, Any]) -> None:
        self.records.append(
            {
                "seq": len(self.records) + 1,
                "kind": kind,
                "payload": json_safe(payload),
            }
        )


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, Path):
        return str(value)
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def agent_thinking_from_chat_config(config: ChatConfig | None) -> bool | ThinkingLevel:
    if config is None or not config.thinking:
        return False
    if config.thinking_level is not None:
        try:
            return ThinkingLevel(str(config.thinking_level))
        except ValueError:
            return True
    return True


def agent_config_from_chat_config(
    config: ChatConfig | None,
    *,
    timeout: float,
    model_id: str,
    max_iterations: int,
) -> AgentConfig:
    return AgentConfig(
        max_iterations=max(0, int(max_iterations or 0)),
        timeout=timeout,
        iteration_timeout=timeout,
        request_timeout=(
            float(config.timeout)
            if config is not None and getattr(config, "timeout", 0)
            else timeout
        ),
        max_tokens=(
            int(config.max_tokens)
            if config is not None and getattr(config, "max_tokens", 0)
            else AgentConfig().max_tokens
        ),
        temperature=config.temperature if config is not None else None,
        thinking=agent_thinking_from_chat_config(config),
        thinking_budget_tokens=(
            int(config.thinking_budget_tokens)
            if config is not None and getattr(config, "thinking_budget_tokens", 0)
            else AgentConfig().thinking_budget_tokens
        ),
        stop_sequences=list(config.stop_sequences) if config is not None else [],
        model_capabilities=config.model_capabilities if config is not None else None,
        model_id=model_id,
        workspace_dir=str(ROOT),
        tool_result_external_keep_recent=3,
        metadata={
            "benchmark": "DRACO",
            "runner_mode": RUNNER_MODE_AGENT_LOOP,
            "tool_activity_heartbeat_interval": 30.0,
        },
    )


def llm_response_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record.get("kind") in {"llm_response", "llm_error"}
        and isinstance(record.get("payload"), dict)
    ]


def aggregate_agent_model_usage(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for call_index, record in enumerate(llm_response_records(records), start=1):
        payload = record["payload"]
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if not isinstance(usage, dict):
            continue
        breakdown = usage.get("model_usage_breakdown")
        if isinstance(breakdown, list) and breakdown:
            for row in breakdown:
                if not isinstance(row, dict):
                    continue
                enriched = dict(row)
                enriched["agent_call_index"] = call_index
                enriched["agent_iteration"] = coerce_metric_int(payload.get("iteration"))
                enriched["agent_call_attempt"] = coerce_metric_int(
                    payload.get("call_attempt")
                )
                rows.append(enriched)
            continue
        rows.append(
            {
                "role": "agent_llm_call",
                "agent_call_index": call_index,
                "agent_iteration": coerce_metric_int(payload.get("iteration")),
                "agent_call_attempt": coerce_metric_int(payload.get("call_attempt")),
                "model": str(usage.get("model") or ""),
                "input_tokens": coerce_metric_int(usage.get("input_tokens")),
                "output_tokens": coerce_metric_int(usage.get("output_tokens")),
                "reasoning_tokens": coerce_metric_int(usage.get("reasoning_tokens")),
                "cached_tokens": coerce_metric_int(usage.get("cached_tokens")),
                "cache_write_tokens": coerce_metric_int(
                    usage.get("cache_write_tokens")
                ),
                "billed_cost": float(usage.get("billed_cost") or 0.0),
                "cost_source": str(usage.get("cost_source") or "none"),
            }
        )
    return rows


def aggregate_agent_ensemble_trace(records: list[dict[str, Any]]) -> dict[str, Any]:
    traces: list[dict[str, Any]] = []
    total_llm_requests = 0
    for call_index, record in enumerate(llm_response_records(records), start=1):
        payload = record["payload"]
        trace = payload.get("ensemble_trace") if isinstance(payload, dict) else None
        if not isinstance(trace, dict) or not trace:
            continue
        enriched = dict(trace)
        enriched["agent_call_index"] = call_index
        if payload.get("call_id") is not None:
            enriched["agent_call_id"] = str(payload.get("call_id"))
        enriched["agent_iteration"] = coerce_metric_int(payload.get("iteration"))
        enriched["agent_call_attempt"] = coerce_metric_int(payload.get("attempt"))
        enriched["agent_call_duration_ms"] = coerce_metric_int(
            payload.get("duration_ms")
        )
        traces.append(enriched)
        total_llm_requests += coerce_metric_int(trace.get("llm_request_count"))
    if not traces:
        return {}
    first_trace = traces[0]
    payload: dict[str, Any] = {
        "mode": "agent_loop",
        "agent_llm_call_count": len(llm_response_records(records)),
        "llm_request_count": total_llm_requests or len(llm_response_records(records)),
        "calls": traces,
    }
    for key in (
        "profile",
        "shuffle_candidates",
        "successful_proposers",
        "total_candidates",
        "fallback_used",
        "final_request_role",
        "moa_layers",
        "moa_refine_count",
        "moa_intermediate_layers",
        "output_strategy",
    ):
        if key in first_trace:
            payload[key] = first_trace[key]
    if first_trace.get("output_strategy") == "select_best_candidate":
        for key in ("selected_candidate_count", "selected_candidate_indexes"):
            if key in first_trace:
                payload[key] = first_trace[key]
    return payload


def provider_done_from_agent_done(
    done: AgentDoneEvent | None,
    *,
    recorder: BenchmarkTurnCallRecorder,
    fallback_model: str,
) -> DoneEvent | None:
    if done is None:
        return None
    breakdown = aggregate_agent_model_usage(recorder.records)
    trace = aggregate_agent_ensemble_trace(recorder.records)
    if trace:
        trace["agent_iterations"] = done.iterations
    provider_usage: dict[str, Any] = {
        "agent_iterations": done.iterations,
        "agent_llm_call_count": len(llm_response_records(recorder.records)),
    }
    return DoneEvent(
        stop_reason="stop",
        input_tokens=done.input_tokens,
        output_tokens=done.output_tokens,
        reasoning_content=done.reasoning_content,
        reasoning_tokens=done.reasoning_tokens,
        cached_tokens=done.cached_tokens,
        billed_cost=done.billed_cost or done.cost_usd,
        model=done.model or fallback_model,
        cache_write_tokens=done.cache_write_tokens,
        cost_source=done.cost_source,
        model_usage_breakdown=breakdown,
        ensemble_trace=trace,
        provider_usage=provider_usage,
    )


async def collect_agent_run(
    provider: Any,
    prompt: str,
    *,
    timeout: float,
    config: ChatConfig | None,
    tools: list[ToolDefinition] | None,
    tool_policy: dict[str, Any],
    task_id: str,
    group: str,
    output_dir: Path | None = None,
    max_iterations: int = DEFAULT_AGENT_MAX_ITERATIONS,
) -> RunResult:
    text_parts: list[str] = []
    done: AgentDoneEvent | None = None
    error = ""
    ttft_ms: int | None = None
    tool_call_count = 0
    trace_events: list[dict[str, Any]] = []
    started = time.monotonic()
    recorder = BenchmarkTurnCallRecorder()

    def _trace(kind: str, **payload: Any) -> None:
        trace_events.append(
            {
                "seq": len(trace_events) + 1,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "kind": kind,
                **payload,
            }
        )

    tool_registry: ToolRegistry | None = None
    tool_context: ToolContext | None = None
    tool_handler = None
    if tool_policy.get("tool_mode") == TOOL_MODE_LOCAL_WEB_TOOLS:
        tool_registry = build_local_web_tool_registry(tool_policy)
        tool_context = build_benchmark_tool_context(
            task_id=task_id,
            group=group,
            tool_policy=tool_policy,
            output_dir=output_dir,
        )
        tool_handler = build_tool_handler(tool_registry, tool_context)

    model_id = getattr(provider, "model", "") or getattr(provider, "profile_name", "")
    agent = Agent(
        provider=provider,
        config=agent_config_from_chat_config(
            config,
            timeout=timeout,
            model_id=str(model_id or ""),
            max_iterations=max_iterations,
        ),
        tool_definitions=tools,
        tool_handler=tool_handler,
        tool_registry=tool_registry,
        tool_context=tool_context,
        session_key=f"draco:{group}:{task_id}",
        turn_call_logger=recorder,
    )
    try:
        async def _consume() -> None:
            nonlocal done, error, ttft_ms, tool_call_count
            async for event in agent.run_turn(prompt):
                if isinstance(event, AgentTextDeltaEvent):
                    if event.presentation == "answer":
                        if ttft_ms is None and event.text:
                            ttft_ms = int((time.monotonic() - started) * 1000)
                            _trace(
                                "first_text_delta",
                                text_chars=len(event.text),
                                presentation=event.presentation,
                            )
                        else:
                            _trace(
                                "text_delta",
                                text_chars=len(event.text),
                                presentation=event.presentation,
                            )
                        text_parts.append(event.text)
                    else:
                        _trace(
                            "intermediate_text_delta",
                            text_chars=len(event.text),
                            presentation=event.presentation,
                        )
                elif isinstance(event, AgentThinkingEvent):
                    _trace("thinking_delta", text_chars=len(event.text))
                elif isinstance(event, AgentToolUseStartEvent):
                    tool_call_count += 1
                    _trace(
                        "tool_use_start",
                        tool_use_id=event.tool_use_id,
                        tool_name=event.tool_name,
                        synthetic_from_text=event.synthetic_from_text,
                    )
                elif isinstance(event, AgentToolUseDeltaEvent):
                    _trace(
                        "tool_use_delta",
                        tool_use_id=event.tool_use_id,
                        json_fragment_chars=len(event.json_fragment),
                    )
                elif isinstance(event, AgentToolResultEvent):
                    _trace(
                        "tool_result",
                        tool_use_id=event.tool_use_id,
                        tool_name=event.tool_name,
                        is_error=event.is_error,
                        result_chars=len(event.result or ""),
                    )
                elif isinstance(event, AgentRunHeartbeatEvent):
                    _trace(
                        "run_heartbeat",
                        phase=event.phase,
                        message=event.message,
                        idle_ms=event.idle_ms,
                    )
                elif isinstance(event, AgentStateChangeEvent):
                    _trace(
                        "state_change",
                        from_state=str(event.from_state),
                        to_state=str(event.to_state),
                    )
                elif isinstance(event, AgentWarningEvent):
                    _trace("warning", code=event.code, message=event.message)
                elif isinstance(event, AgentDoneEvent):
                    done = event
                    if event.text and not "".join(text_parts).strip():
                        text_parts.append(event.text)
                    _trace(
                        "done",
                        usage={
                            "input_tokens": event.input_tokens,
                            "output_tokens": event.output_tokens,
                            "reasoning_tokens": event.reasoning_tokens,
                            "cached_tokens": event.cached_tokens,
                            "cache_write_tokens": event.cache_write_tokens,
                            "billed_cost": event.billed_cost,
                            "cost_usd": event.cost_usd,
                            "cost_source": event.cost_source,
                            "model": event.model,
                            "iterations": event.iterations,
                        },
                    )
                elif isinstance(event, AgentErrorEvent):
                    error = event.message
                    _trace("error", message=event.message, code=event.code)
                else:
                    _trace("agent_event", event_type=type(event).__name__)

        if timeout and timeout > 0:
            try:
                async with asyncio.timeout(timeout):
                    await _consume()
            except TimeoutError:
                error = f"TimeoutError: agent run timed out after {timeout:g}s"
                _trace("timeout", timeout_s=timeout)
        else:
            await _consume()
    except Exception as exc:  # noqa: BLE001 - benchmark rows should keep going
        error = f"{type(exc).__name__}: {exc}"
        _trace("exception", error=error)

    provider_done = provider_done_from_agent_done(
        done,
        recorder=recorder,
        fallback_model=str(model_id or ""),
    )
    trace_events.append(
        {
            "seq": len(trace_events) + 1,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "kind": "turn_call_log_summary",
            "llm_response_records": len(llm_response_records(recorder.records)),
            "records": recorder.records,
        }
    )
    return RunResult(
        final_text="".join(text_parts),
        done=provider_done,
        error=error,
        latency_ms=int((time.monotonic() - started) * 1000),
        ttft_ms=ttft_ms,
        tool_call_count=tool_call_count,
        trace_events=trace_events,
    )


def coerce_metric_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return max(0, int(value))
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def server_tool_counts_from_provider_usage(provider_usage: Any) -> dict[str, int]:
    if not isinstance(provider_usage, dict):
        return {}
    raw_counts = provider_usage.get("server_tool_use")
    if not isinstance(raw_counts, dict):
        return {}
    counts: dict[str, int] = {}
    for key, value in raw_counts.items():
        count = coerce_metric_int(value)
        if count:
            counts[str(key)] = counts.get(str(key), 0) + count
    return counts


def add_metric_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + int(value)


def server_tool_counts_from_usage_payload(usage: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    breakdown = usage.get("model_usage_breakdown")
    if isinstance(breakdown, list):
        for row in breakdown:
            if isinstance(row, dict):
                add_metric_counts(
                    counts,
                    server_tool_counts_from_provider_usage(row.get("provider_usage")),
                )
        if counts:
            return counts
    return server_tool_counts_from_provider_usage(usage.get("provider_usage"))


def llm_request_count_for_run(
    *,
    spec: dict[str, str],
    done: DoneEvent | None,
    provider_attempted: bool,
) -> int:
    if not provider_attempted:
        return 0
    if done is not None and isinstance(done.ensemble_trace, dict):
        traced = coerce_metric_int(done.ensemble_trace.get("llm_request_count"))
        if traced:
            return traced
    if done is not None and done.model_usage_breakdown:
        return len(done.model_usage_breakdown)
    if spec.get("kind") == "single":
        return 1
    return 1


def done_payload(done: DoneEvent | None) -> dict[str, Any]:
    if done is None:
        return {}
    payload = {
        "model": done.model,
        "stop_reason": done.stop_reason,
        "input_tokens": done.input_tokens,
        "output_tokens": done.output_tokens,
        "reasoning_tokens": done.reasoning_tokens,
        "cached_tokens": done.cached_tokens,
        "cache_write_tokens": done.cache_write_tokens,
        "billed_cost": done.billed_cost,
        "cost_source": done.cost_source,
        "provider_usage": done.provider_usage,
        "model_usage_breakdown": done.model_usage_breakdown,
        "reasoning_content_chars": len(done.reasoning_content or ""),
        "thinking_signature_present": bool(done.thinking_signature),
    }
    server_tool_use = server_tool_counts_from_usage_payload(payload)
    payload["server_tool_use"] = server_tool_use
    payload["server_tool_call_count"] = sum(server_tool_use.values())
    return payload


def candidate_texts(
    done: DoneEvent | None,
    *,
    final_agent_call_only: bool = False,
) -> list[str]:
    if done is None:
        return []
    trace = done.ensemble_trace or {}
    candidates: list[Any] = []
    if isinstance(trace, dict):
        direct_candidates = trace.get("candidates")
        if isinstance(direct_candidates, list):
            candidates.extend(direct_candidates)
        calls = trace.get("calls")
        if isinstance(calls, list):
            selected_calls = calls[-1:] if final_agent_call_only else calls
            for call in selected_calls:
                if not isinstance(call, dict):
                    continue
                call_candidates = call.get("candidates")
                if isinstance(call_candidates, list):
                    candidates.extend(call_candidates)
    if not isinstance(candidates, list):
        return []
    return [
        str(candidate.get("text") or "")
        for candidate in candidates
        if isinstance(candidate, dict) and str(candidate.get("text") or "").strip()
    ]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_result_summary(result: RunResult) -> dict[str, Any]:
    usage = done_payload(result.done)
    server_tool_call_count = coerce_metric_int(usage.get("server_tool_call_count"))
    total_tool_call_count = result.tool_call_count + server_tool_call_count
    llm_request_count = 0
    usage_unknown_count = 0
    if result.done is not None:
        if isinstance(result.done.ensemble_trace, dict):
            llm_request_count = coerce_metric_int(
                result.done.ensemble_trace.get("llm_request_count")
            )
            usage_unknown_count = ensemble_usage_unknown_count(
                result.done.ensemble_trace
            )
        if not llm_request_count and result.done.model_usage_breakdown:
            llm_request_count = len(result.done.model_usage_breakdown)
        if not llm_request_count:
            llm_request_count = 1
        usage_unknown_count = max(
            usage_unknown_count,
            usage_unknown_count_from_usage_payload(usage),
        )
    elif result.error or result.final_text:
        llm_request_count = 1
    return {
        "latency_ms": result.latency_ms,
        "ttft_ms": result.ttft_ms,
        "tool_call_count": result.tool_call_count,
        "stream_tool_call_count": result.tool_call_count,
        "server_tool_call_count": server_tool_call_count,
        "server_tool_use": usage.get("server_tool_use") or {},
        "total_tool_call_count": total_tool_call_count,
        "trajectory_steps": total_tool_call_count + llm_request_count,
        "llm_request_count": llm_request_count,
        "usage_unknown_count": usage_unknown_count,
        "error": result.error,
        "final_text_chars": len(result.final_text),
        "final_text_sha256": text_sha256(result.final_text),
        "usage": usage,
        "trace_events": result.trace_events,
    }


def bounded_generation_attempts(value: int | None) -> int:
    try:
        attempts = GENERATION_MAX_ATTEMPTS if value is None else int(value)
    except (TypeError, ValueError):
        attempts = GENERATION_MAX_ATTEMPTS
    return max(1, min(GENERATION_MAX_ATTEMPTS, attempts))


def bounded_generation_retry_backoff(value: Any) -> float:
    try:
        backoff = float(value)
    except (TypeError, ValueError):
        backoff = DEFAULT_GENERATION_RETRY_BACKOFF_SECONDS
    return max(0.0, backoff)


def generation_retry_reason(result: RunResult) -> str:
    if result.error:
        return result.error
    if result.done is None:
        return GENERATION_MISSING_DONE_ERROR
    if not result.final_text.strip():
        return GENERATION_EMPTY_OUTPUT_ERROR
    return ""


def mark_empty_generation_output(result: RunResult) -> None:
    if result.error or result.final_text.strip():
        return
    result.error = GENERATION_EMPTY_OUTPUT_ERROR
    result.trace_events.append(
        {
            "seq": len(result.trace_events) + 1,
            "elapsed_ms": result.latency_ms,
            "kind": GENERATION_EMPTY_OUTPUT_ERROR,
        }
    )


def mark_retryable_generation_error(result: RunResult, reason: str) -> None:
    if result.error or not reason:
        return
    if reason not in {GENERATION_EMPTY_OUTPUT_ERROR, GENERATION_MISSING_DONE_ERROR}:
        return
    result.error = reason
    result.trace_events.append(
        {
            "seq": len(result.trace_events) + 1,
            "elapsed_ms": result.latency_ms,
            "kind": reason,
        }
    )


def selected_generation_attempt(
    attempts: list[dict[str, Any]],
    selected_result: RunResult,
) -> int:
    selected_sha = text_sha256(selected_result.final_text)
    selected_error = selected_result.error
    for attempt in attempts:
        run = attempt.get("run")
        if not isinstance(run, dict):
            continue
        if (
            run.get("final_text_sha256") == selected_sha
            and run.get("error") == selected_error
        ):
            return coerce_metric_int(attempt.get("attempt"))
    return coerce_metric_int(attempts[-1].get("attempt")) if attempts else 0


async def collect_generation_with_retries(
    provider: Any,
    prompt: str,
    *,
    timeout: float,
    config: ChatConfig | None = None,
    tools: list[ToolDefinition] | None = None,
    runner_mode: str = RUNNER_MODE_PROVIDER,
    tool_policy: dict[str, Any] | None = None,
    task_id: str = "",
    group: str = "",
    output_dir: Path | None = None,
    agent_max_iterations: int = DEFAULT_AGENT_MAX_ITERATIONS,
    max_attempts: int = GENERATION_MAX_ATTEMPTS,
    retry_backoff_seconds: float = 0.0,
) -> tuple[RunResult, list[dict[str, Any]], int]:
    attempts: list[dict[str, Any]] = []
    best_non_empty: RunResult | None = None
    last_result: RunResult | None = None
    attempt_limit = bounded_generation_attempts(max_attempts)
    for attempt_index in range(1, attempt_limit + 1):
        if runner_mode == RUNNER_MODE_AGENT_LOOP:
            result = await collect_agent_run(
                provider,
                prompt,
                timeout=timeout,
                config=config,
                tools=tools,
                tool_policy=tool_policy or {},
                task_id=task_id,
                group=group,
                output_dir=output_dir,
                max_iterations=agent_max_iterations,
            )
        else:
            result = await collect_run(
                provider,
                prompt,
                timeout=timeout,
                config=config,
                tools=tools,
            )
        last_result = result
        reason = generation_retry_reason(result)
        mark_retryable_generation_error(result, reason)
        if result.final_text.strip() and best_non_empty is None:
            best_non_empty = result
        will_retry = bool(reason) and attempt_index < attempt_limit
        retry_backoff_s = (
            bounded_generation_retry_backoff(retry_backoff_seconds)
            * (2 ** (attempt_index - 1))
            if will_retry
            else 0.0
        )
        attempts.append(
            {
                "attempt": attempt_index,
                "retryable": bool(reason),
                "retry_reason": reason,
                "will_retry": will_retry,
                "retry_backoff_s": retry_backoff_s,
                "run": run_result_summary(result),
            }
        )
        if not reason:
            return result, attempts, attempt_index
        if retry_backoff_s > 0:
            await asyncio.sleep(retry_backoff_s)
    selected = best_non_empty or last_result or RunResult(
        final_text="",
        done=None,
        error=GENERATION_MISSING_DONE_ERROR,
    )
    mark_empty_generation_output(selected)
    if best_non_empty is None and attempts:
        return selected, attempts, coerce_metric_int(attempts[-1].get("attempt"))
    return selected, attempts, selected_generation_attempt(attempts, selected)


def sum_generation_attempt_metric(attempts: list[dict[str, Any]], key: str) -> int:
    total = 0
    for attempt in attempts:
        run = attempt.get("run")
        if isinstance(run, dict):
            total += coerce_metric_int(run.get(key))
    return total


def sum_generation_attempt_server_tools(attempts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for attempt in attempts:
        run = attempt.get("run")
        if not isinstance(run, dict):
            continue
        server_tool_use = run.get("server_tool_use")
        if isinstance(server_tool_use, dict):
            add_metric_counts(counts, server_tool_use)
    return counts


def sum_generation_attempt_billed_cost(attempts: list[dict[str, Any]]) -> float:
    total = 0.0
    for attempt in attempts:
        run = attempt.get("run")
        if not isinstance(run, dict):
            continue
        usage = run.get("usage")
        if not isinstance(usage, dict):
            continue
        billed_cost = usage.get("billed_cost")
        if isinstance(billed_cost, int | float):
            total += float(billed_cost)
    return total


def bounded_judge_attempts(value: int | None) -> int:
    try:
        attempts = JUDGE_MAX_ATTEMPTS if value is None else int(value)
    except (TypeError, ValueError):
        attempts = JUDGE_MAX_ATTEMPTS
    return max(1, min(JUDGE_MAX_ATTEMPTS, attempts))


async def judge_text(
    *,
    judge_provider: Any | None,
    task: dict[str, Any],
    answer: str,
    dry_run: bool,
    judge_repeats: int = 1,
    judge_concurrency: int = 1,
    judge_max_attempts: int = JUDGE_MAX_ATTEMPTS,
) -> dict[str, Any] | None:
    if not answer.strip():
        return None
    criteria = rubric_criteria(task)
    if dry_run:
        if criteria:
            repeats = max(1, int(judge_repeats or 1))
            judgments = [
                {
                    **criterion,
                    "repeat_index": repeat_index,
                    "verdict": "UNMET" if criterion["weight"] < 0 else "MET",
                    "met": criterion["weight"] >= 0,
                    "rationale": "dry-run heuristic",
                }
                for repeat_index in range(repeats)
                for criterion in criteria
            ]
            return score_criterion_judgments(
                rubric_id=rubric_id(task),
                judgments=judgments,
                judge_model="dry-run",
                judge_repeats=repeats,
            )
        score = min(20, max(4, len(answer) // 40))
        return normalize_legacy_judge_result({
            "mode": "legacy_dimension_score",
            "scores": {
                "accuracy": score // 4,
                "completeness": score // 4,
                "objectivity": score // 4,
                "citation": score // 4,
            },
            "total": score,
            "rationale": "dry-run heuristic",
        })
    if judge_provider is None:
        return None
    max_attempts = bounded_judge_attempts(judge_max_attempts)
    if criteria:
        repeats = max(1, int(judge_repeats or 1))
        semaphore = asyncio.Semaphore(max(1, int(judge_concurrency or 1)))

        async def _guarded_judge(
            criterion: dict[str, Any],
            repeat_index: int,
        ) -> dict[str, Any]:
            async with semaphore:
                return await judge_criterion(
                    judge_provider=judge_provider,
                    task=task,
                    answer=answer,
                    criterion=criterion,
                    repeat_index=repeat_index,
                    max_attempts=max_attempts,
                )

        judgments = await asyncio.gather(
            *[
                _guarded_judge(criterion, repeat_index)
                for repeat_index in range(repeats)
                for criterion in criteria
            ]
        )
        return score_criterion_judgments(
            rubric_id=rubric_id(task),
            judgments=judgments,
            judge_model=str(getattr(judge_provider, "model", "") or ""),
            judge_repeats=repeats,
        )
    rubric = task.get("rubric") or "accuracy, completeness, objectivity, citation quality"
    reference = task.get("reference") or ""
    prompt = (
        "Judge this DRACO answer. Return only JSON with keys scores, total, rationale. "
        "scores must contain accuracy, completeness, objectivity, citation, each 1-5.\n\n"
        f"Task:\n{task['prompt']}\n\n"
        f"Rubric:\n{rubric}\n\n"
        f"Reference:\n{reference}\n\n"
        f"Answer:\n{answer}"
    )
    attempts: list[dict[str, Any]] = []
    last_result: RunResult | None = None
    for attempt_index in range(1, max_attempts + 1):
        result = await collect_run(
            judge_provider,
            prompt,
            timeout=120.0,
            config=ChatConfig(temperature=0.0, thinking=False),
        )
        last_result = result
        parsed = extract_json_object(result.final_text)
        attempts.append(
            {
                "attempt": attempt_index,
                "parsed": parsed is not None,
                "run": run_result_summary(result),
            }
        )
        if parsed is not None:
            normalized = normalize_legacy_judge_result(parsed)
            normalized["judge_run"] = run_result_summary(result)
            normalized["judge_attempt_count"] = attempt_index
            normalized["judge_attempts"] = attempts
            return normalized
    last_text = last_result.final_text if last_result is not None else ""
    return {
        "error": "judge_json_parse_failed",
        "raw": last_text[:2000],
        "judge_run": run_result_summary(last_result) if last_result is not None else {},
        "judge_attempt_count": len(attempts),
        "judge_attempts": attempts,
    }


def rubric_id(task: dict[str, Any]) -> str:
    rubric = parse_maybe_json(task.get("rubric"))
    if isinstance(rubric, dict):
        return str(rubric.get("id") or task.get("id") or "")
    return str(task.get("id") or "")


async def judge_criterion(
    *,
    judge_provider: Any,
    task: dict[str, Any],
    answer: str,
    criterion: dict[str, Any],
    repeat_index: int = 0,
    max_attempts: int = JUDGE_MAX_ATTEMPTS,
) -> dict[str, Any]:
    weight = coerce_weight(criterion.get("weight"))
    criterion_type = "negative" if weight < 0 else "positive"
    prompt = (
        "You are grading a DRACO deep research answer against one rubric criterion.\n"
        "Return only JSON with keys verdict and rationale. verdict must be MET or UNMET.\n"
        "Positive criteria describe desired content. Negative criteria describe an error; "
        "for negative criteria, MET means the answer contains that error.\n\n"
        f"Original query:\n{task['prompt']}\n\n"
        f"Answer:\n{answer}\n\n"
        "Criterion:\n"
        f"- id: {criterion.get('id')}\n"
        f"- section: {criterion.get('section_title') or criterion.get('section_id')}\n"
        f"- type: {criterion_type}\n"
        f"- weight: {weight}\n"
        f"- requirement: {criterion.get('requirement')}\n"
    )
    attempts: list[dict[str, Any]] = []
    last_row: dict[str, Any] | None = None
    for attempt_index in range(1, bounded_judge_attempts(max_attempts) + 1):
        result = await collect_run(
            judge_provider,
            prompt,
            timeout=120.0,
            config=ChatConfig(temperature=0.0, thinking=False),
        )
        parsed = extract_json_object(result.final_text) or {}
        met = parse_verdict(parsed.get("verdict"))
        run_summary = run_result_summary(result)
        attempts.append(
            {
                "attempt": attempt_index,
                "verdict": parsed.get("verdict") if parsed else "",
                "met": met,
                "run": run_summary,
            }
        )
        row = {
            **criterion,
            "weight": weight,
            "repeat_index": repeat_index,
            "verdict": parsed.get("verdict") if parsed else "",
            "met": met,
            "rationale": str(parsed.get("rationale") or parsed.get("reason") or "")[:1000],
            "judge_run": run_summary,
            "judge_attempt_count": attempt_index,
            "judge_attempts": list(attempts),
        }
        if met is not None:
            return row
        row["error"] = result.error or "judge_verdict_parse_failed"
        row["raw"] = result.final_text[:1000]
        last_row = row
    return last_row if last_row is not None else {
        **criterion,
        "weight": weight,
        "repeat_index": repeat_index,
        "verdict": "",
        "met": None,
        "rationale": "",
        "error": "judge_verdict_parse_failed",
        "judge_attempt_count": 0,
        "judge_attempts": [],
    }


def score_criterion_judgments(
    *,
    rubric_id: str,
    judgments: list[dict[str, Any]],
    judge_model: str,
    judge_repeats: int = 1,
) -> dict[str, Any]:
    valid_judgments = [
        item for item in judgments if isinstance(item.get("met"), bool)
    ]
    invalid_count = len(judgments) - len(valid_judgments)
    score_status = "partial" if invalid_count else "complete"
    positive_weight_total = sum(
        max(0, coerce_weight(item.get("weight"))) for item in judgments
    )
    raw_score = sum(
        coerce_weight(item.get("weight")) for item in valid_judgments if item.get("met") is True
    )
    valid_positive_weight_total = sum(
        max(0, coerce_weight(item.get("weight"))) for item in valid_judgments
    )
    valid_normalized = (
        clamp_percent((raw_score / valid_positive_weight_total) * 100.0)
        if valid_positive_weight_total > 0
        else None
    )
    normalized = (
        clamp_percent((raw_score / positive_weight_total) * 100.0)
        if positive_weight_total > 0
        else None
    )

    def _passed(item: dict[str, Any]) -> bool:
        weight = coerce_weight(item.get("weight"))
        met = item.get("met")
        return bool(met) if weight >= 0 else met is False

    valid_passed = [_passed(item) for item in valid_judgments]
    valid_pass_rate = (
        sum(1 for item in valid_passed if item) / len(valid_passed) * 100.0
        if valid_passed
        else None
    )
    section_scores: dict[str, dict[str, Any]] = {}
    for item in judgments:
        section_id = str(item.get("section_id") or "rubric")
        section = section_scores.setdefault(
            section_id,
            {
                "title": item.get("section_title") or section_id,
                "criteria_count": 0,
                "valid_criteria_count": 0,
                "invalid_criteria_count": 0,
                "raw_score": 0,
                "positive_weight_total": 0,
                "valid_positive_weight_total": 0,
                "passed_count": 0,
            },
        )
        weight = coerce_weight(item.get("weight"))
        met = item.get("met")
        section["criteria_count"] += 1
        section["positive_weight_total"] += max(0, weight)
        if isinstance(met, bool):
            section["valid_criteria_count"] += 1
            section["valid_positive_weight_total"] += max(0, weight)
        else:
            section["invalid_criteria_count"] += 1
            continue
        if met is True:
            section["raw_score"] += weight
        if (met is True and weight >= 0) or (met is False and weight < 0):
            section["passed_count"] += 1
    for section in section_scores.values():
        total = section["positive_weight_total"]
        valid_total = section["valid_positive_weight_total"]
        valid_section_normalized = (
            clamp_percent((section["raw_score"] / valid_total) * 100.0)
            if valid_total > 0
            else None
        )
        valid_section_pass_rate = (
            section["passed_count"] / section["valid_criteria_count"] * 100.0
            if section["valid_criteria_count"]
            else None
        )
        section["score_status"] = (
            "partial" if section["invalid_criteria_count"] else "complete"
        )
        section["valid_normalized_score"] = valid_section_normalized
        section["valid_pass_rate"] = valid_section_pass_rate
        section["normalized_score"] = (
            clamp_percent((section["raw_score"] / total) * 100.0)
            if total > 0 and not section["invalid_criteria_count"]
            else None
        )
        section["pass_rate"] = (
            valid_section_pass_rate if not section["invalid_criteria_count"] else None
        )
    judge_error_count = sum(
        1
        for item in judgments
        if item.get("error") or not isinstance(item.get("met"), bool)
    )
    return {
        "mode": "draco_criterion_judgments",
        "rubric_id": rubric_id,
        "judge_model": judge_model,
        "judge_repeats": judge_repeats,
        "rubric_criteria_count": (
            len(judgments) // max(1, judge_repeats) if judgments else 0
        ),
        "criteria_count": len(judgments),
        "valid_criteria_count": len(valid_judgments),
        "invalid_criteria_count": invalid_count,
        "score_status": score_status,
        "raw_score": raw_score,
        "positive_weight_total": positive_weight_total,
        "valid_positive_weight_total": valid_positive_weight_total,
        "valid_normalized_score": valid_normalized,
        "valid_pass_rate": valid_pass_rate,
        "normalized_score": normalized if score_status == "complete" else None,
        "pass_rate": valid_pass_rate if score_status == "complete" else None,
        "section_scores": section_scores,
        "criterion_judgments": judgments,
        "judge_error_count": judge_error_count,
        "total": normalized if score_status == "complete" else None,
    }


def quality_total(judge: dict[str, Any] | None) -> float | None:
    if not isinstance(judge, dict):
        return None
    if (
        judge.get("mode") == "draco_criterion_judgments"
        and judge.get("score_status") != "complete"
    ):
        return None
    normalized = judge.get("normalized_score")
    if isinstance(normalized, int | float):
        return clamp_percent(float(normalized))
    total = judge.get("total")
    if isinstance(total, int | float):
        if judge.get("mode") == "legacy_dimension_score":
            total_float = float(total)
            normalized_total = (
                total_float if total_float > 20.0 else total_float / 20.0 * 100.0
            )
            return clamp_percent(normalized_total)
        return float(total)
    scores = judge.get("scores")
    if isinstance(scores, dict):
        values = [value for value in scores.values() if isinstance(value, int | float)]
        if values:
            return clamp_percent(float(sum(values)) / (len(values) * 5.0) * 100.0)
    return None


async def run_one(
    *,
    task: dict[str, Any],
    group: str,
    config: GatewayConfig,
    inherited: ProviderConfig,
    dry_run: bool,
    judge_provider: Any | None,
    judge_candidates: bool,
    judge_repeats: int,
    judge_concurrency: int,
    judge_max_attempts: int,
    timeout: float,
    ensemble_proposer_timeout: float | None,
    ensemble_aggregator_timeout: float | None,
    ensemble_proposer_early_stop_success_count: int | None,
    ensemble_proposer_early_stop_after: float | None,
    expand_ensemble_timeouts_to_task_timeout: bool,
    tool_policy: dict[str, Any],
    generation_policy: dict[str, Any],
    runner_mode: str = RUNNER_MODE_PROVIDER,
    output_dir: Path | None = None,
    agent_max_iterations: int = DEFAULT_AGENT_MAX_ITERATIONS,
    generation_max_attempts: int = GENERATION_MAX_ATTEMPTS,
    generation_retry_backoff: float = DEFAULT_GENERATION_RETRY_BACKOFF_SECONDS,
    tools: list[ToolDefinition] | None = None,
) -> dict[str, Any]:
    spec = GROUP_SPECS[group]
    started = time.time()
    provider = None
    provider_error = ""
    generation_attempt_limit = bounded_generation_attempts(generation_max_attempts)
    generation_retry_backoff_s = bounded_generation_retry_backoff(
        generation_retry_backoff
    )
    effective_timeout = group_timeout_seconds(
        requested_timeout=timeout,
        config=config,
        group=group,
        ensemble_proposer_timeout=ensemble_proposer_timeout,
        ensemble_aggregator_timeout=ensemble_aggregator_timeout,
    )
    generation_config = generation_chat_config(
        generation_policy,
        model=spec["model"] if spec["kind"] == "single" else None,
        tool_choice=tool_policy.get("openrouter_fusion_tool_choice"),
    )
    try:
        if spec["kind"] == "single":
            provider = build_single_provider(
                inherited=inherited,
                group=group,
                model=spec["model"],
                dry_run=dry_run,
                provider=spec.get("provider"),
                base_url=spec.get("base_url"),
                api_key=spec.get("api_key"),
                api_key_env=spec.get("api_key_env"),
            )
        else:
            provider = build_profile_provider(
                config=config.model_copy(deep=True),
                inherited=inherited,
                group=group,
                profile=spec["profile"],
                dry_run=dry_run,
                generation_policy=generation_policy,
                requested_timeout=effective_timeout,
                enable_proposer_tools=bool(
                    tool_policy.get("tools_enabled")
                    and tool_policy.get("tool_mode") != TOOL_MODE_LOCAL_WEB_TOOLS
                ),
                ensemble_proposer_timeout=ensemble_proposer_timeout,
                ensemble_aggregator_timeout=ensemble_aggregator_timeout,
                ensemble_proposer_early_stop_success_count=(
                    ensemble_proposer_early_stop_success_count
                ),
                ensemble_proposer_early_stop_after=ensemble_proposer_early_stop_after,
                expand_ensemble_timeouts_to_task_timeout=(
                    expand_ensemble_timeouts_to_task_timeout
                ),
            )
    except Exception as exc:  # noqa: BLE001 - report config errors per row
        provider_error = f"{type(exc).__name__}: {exc}"
    if provider is not None:
        run, generation_attempts, selected_generation_attempt_index = (
            await collect_generation_with_retries(
                provider,
                str(task["prompt"]),
                timeout=effective_timeout,
                config=generation_config,
                tools=tools,
                runner_mode=runner_mode,
                tool_policy=tool_policy,
                task_id=str(task["id"]),
                group=group,
                output_dir=output_dir,
                agent_max_iterations=agent_max_iterations,
                max_attempts=generation_attempt_limit,
                retry_backoff_seconds=generation_retry_backoff_s,
            )
        )
    else:
        run = RunResult(final_text="", done=None, error=provider_error)
        generation_attempts = []
        selected_generation_attempt_index = 0
    terminal_generation_reason = generation_retry_reason(run)
    mark_retryable_generation_error(run, terminal_generation_reason)
    profile_proposer_timeout_s = getattr(provider, "proposer_timeout_seconds", None)
    profile_aggregator_timeout_s = getattr(provider, "aggregator_timeout_seconds", None)
    profile_proposer_early_stop_success_count = getattr(
        provider,
        "proposer_early_stop_success_count",
        None,
    )
    profile_proposer_early_stop_after_s = getattr(
        provider,
        "proposer_early_stop_after_seconds",
        None,
    )
    should_judge = not terminal_generation_reason and run.done is not None
    judge = (
        await judge_text(
            judge_provider=judge_provider,
            task=task,
            answer=run.final_text,
            dry_run=dry_run and judge_provider is not None,
            judge_repeats=judge_repeats,
            judge_concurrency=judge_concurrency,
            judge_max_attempts=judge_max_attempts,
        )
        if should_judge
        else None
    )
    candidate_judges: list[dict[str, Any] | None] = []
    if judge_candidates and should_judge:
        for candidate in candidate_texts(
            run.done,
            final_agent_call_only=runner_mode == RUNNER_MODE_AGENT_LOOP,
        ):
            candidate_judges.append(
                await judge_text(
                    judge_provider=judge_provider,
                    task=task,
                    answer=candidate,
                    dry_run=dry_run and judge_provider is not None,
                    judge_repeats=judge_repeats,
                    judge_concurrency=judge_concurrency,
                    judge_max_attempts=judge_max_attempts,
                )
            )
    fused_total = quality_total(judge)
    candidate_totals = [
        total for total in (quality_total(item) for item in candidate_judges) if total is not None
    ]
    completed_at = time.time()
    final_text_sha = text_sha256(run.final_text)
    prompt_sha = text_sha256(str(task["prompt"]))
    usage_payload = done_payload(run.done)
    selected_server_tool_call_count = coerce_metric_int(
        usage_payload.get("server_tool_call_count")
    )
    server_tool_use = usage_payload.get("server_tool_use") or {}
    selected_total_tool_call_count = run.tool_call_count + selected_server_tool_call_count
    selected_llm_request_count = llm_request_count_for_run(
        spec=spec,
        done=run.done,
        provider_attempted=provider is not None,
    )
    attempt_stream_tool_call_count = sum_generation_attempt_metric(
        generation_attempts, "stream_tool_call_count"
    )
    attempt_server_tool_call_count = sum_generation_attempt_metric(
        generation_attempts, "server_tool_call_count"
    )
    attempt_total_tool_call_count = sum_generation_attempt_metric(
        generation_attempts, "total_tool_call_count"
    )
    attempt_llm_request_count = sum_generation_attempt_metric(
        generation_attempts, "llm_request_count"
    )
    attempt_usage_unknown_count = sum_generation_attempt_metric(
        generation_attempts, "usage_unknown_count"
    )
    attempt_trajectory_steps = sum_generation_attempt_metric(
        generation_attempts, "trajectory_steps"
    )
    attempt_latency_ms = sum_generation_attempt_metric(generation_attempts, "latency_ms")
    attempt_server_tool_use = sum_generation_attempt_server_tools(generation_attempts)
    generation_attempt_total_billed_cost = sum_generation_attempt_billed_cost(
        generation_attempts
    )
    generation_retry_reasons = [
        str(attempt.get("retry_reason") or "")
        for attempt in generation_attempts
        if attempt.get("retry_reason")
    ]
    latency_ms = attempt_latency_ms or run.latency_ms
    stream_tool_call_count = attempt_stream_tool_call_count or run.tool_call_count
    server_tool_call_count = (
        attempt_server_tool_call_count or selected_server_tool_call_count
    )
    if attempt_server_tool_use:
        server_tool_use = attempt_server_tool_use
    total_tool_call_count = attempt_total_tool_call_count or selected_total_tool_call_count
    llm_request_count = attempt_llm_request_count or selected_llm_request_count
    trajectory_steps = total_tool_call_count + llm_request_count
    if attempt_trajectory_steps:
        trajectory_steps = attempt_trajectory_steps
    ensemble_trace = run.done.ensemble_trace if run.done is not None else {}
    usage_unknown_count = max(
        ensemble_usage_unknown_count(ensemble_trace),
        usage_unknown_count_from_usage_payload(usage_payload),
    )
    if attempt_usage_unknown_count:
        usage_unknown_count = attempt_usage_unknown_count
    return {
        "task_id": task["id"],
        "group": group,
        "domain": task.get("domain", ""),
        "prompt": task["prompt"],
        "prompt_sha256": prompt_sha,
        "metadata": task.get("metadata", {}),
        "provider_spec": dict(spec),
        "runner_mode": runner_mode,
        "tools_enabled": bool(tool_policy.get("tools_enabled")),
        "tool_policy": tool_policy,
        "generation_policy": generation_policy,
        "generation_config": compact_chat_config(generation_config, generation_policy),
        "contamination_blocked_domains": (
            tool_policy.get("contamination_blocked_domains") or []
        ),
        "started_at": started,
        "completed_at": completed_at,
        "total_elapsed_ms": int((completed_at - started) * 1000),
        "latency_ms": latency_ms,
        "ttft_ms": run.ttft_ms,
        "tool_call_count": stream_tool_call_count,
        "stream_tool_call_count": stream_tool_call_count,
        "server_tool_call_count": server_tool_call_count,
        "server_tool_use": server_tool_use,
        "total_tool_call_count": total_tool_call_count,
        "trajectory_steps": trajectory_steps,
        "llm_request_count": llm_request_count,
        "usage_unknown_count": usage_unknown_count,
        "generation_attempt_count": len(generation_attempts),
        "generation_max_attempts": generation_attempt_limit,
        "generation_retry_backoff_s": generation_retry_backoff_s,
        "generation_attempt_total_billed_cost": generation_attempt_total_billed_cost,
        "generation_retry_reasons": generation_retry_reasons,
        "error": run.error,
        "final_text": run.final_text,
        "final_text_chars": len(run.final_text),
        "final_text_sha256": final_text_sha,
        "execution": {
            "provider_error": provider_error,
            "run_error": run.error,
            "judge_skipped_reason": "run_not_done" if not should_judge else "",
            "requested_timeout_s": timeout,
            "effective_timeout_s": effective_timeout,
            "profile_proposer_timeout_s": profile_proposer_timeout_s,
            "profile_aggregator_timeout_s": profile_aggregator_timeout_s,
            "profile_proposer_early_stop_success_count": (
                profile_proposer_early_stop_success_count
            ),
            "profile_proposer_early_stop_after_s": profile_proposer_early_stop_after_s,
            "runner_mode": runner_mode,
            "agent_max_iterations": agent_max_iterations,
            "latency_ms": latency_ms,
            "selected_generation_latency_ms": run.latency_ms,
            "ttft_ms": run.ttft_ms,
            "total_elapsed_ms": int((completed_at - started) * 1000),
            "tool_call_count": stream_tool_call_count,
            "stream_tool_call_count": stream_tool_call_count,
            "server_tool_call_count": server_tool_call_count,
            "server_tool_use": server_tool_use,
            "total_tool_call_count": total_tool_call_count,
            "trajectory_steps": trajectory_steps,
            "llm_request_count": llm_request_count,
            "usage_unknown_count": usage_unknown_count,
            "generation_attempt_count": len(generation_attempts),
            "generation_max_attempts": generation_attempt_limit,
            "generation_retry_backoff_s": generation_retry_backoff_s,
            "selected_generation_attempt": selected_generation_attempt_index,
            "generation_retry_reasons": generation_retry_reasons,
            "generation_attempt_total_billed_cost": generation_attempt_total_billed_cost,
            "generation_attempts": generation_attempts,
        },
        "run_trace": {
            "event_count": len(run.trace_events),
            "events": run.trace_events,
        },
        "usage": usage_payload,
        "ensemble_trace": ensemble_trace,
        "judge": judge,
        "candidate_judges": candidate_judges,
        "quality_total": fused_total,
        "fusion_delta": (
            fused_total - max(candidate_totals)
            if fused_total is not None and candidate_totals
            else None
        ),
    }


def group_timeout_seconds(
    *,
    requested_timeout: float,
    config: GatewayConfig,
    group: str,
    ensemble_proposer_timeout: float | None = None,
    ensemble_aggregator_timeout: float | None = None,
) -> float:
    if requested_timeout <= 0:
        return requested_timeout
    spec = GROUP_SPECS[group]
    if spec["kind"] != "profile":
        return requested_timeout
    profile = config.llm_ensemble.profiles.get(spec["profile"])
    if profile is None:
        return requested_timeout
    proposer_timeout_s, aggregator_timeout_s = profile_timeout_seconds(
        profile,
        proposer_timeout_override=ensemble_proposer_timeout,
        aggregator_timeout_override=ensemble_aggregator_timeout,
    )
    moa_layers = max(1, int(getattr(profile, "moa_layers", 1) or 1))
    profile_budget = (
        proposer_timeout_s
        + aggregator_timeout_s * moa_layers
        + PROFILE_TIMEOUT_MARGIN_SECONDS
    )
    return max(float(requested_timeout), profile_budget)


def compact_judge_summary(judge: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(judge, dict):
        return {}
    return {
        "mode": judge.get("mode"),
        "score_status": judge.get("score_status"),
        "quality_total": quality_total(judge),
        "pass_rate": judge.get("pass_rate"),
        "valid_pass_rate": judge.get("valid_pass_rate"),
        "judge_error_count": judge.get("judge_error_count"),
        "criteria_count": judge.get("criteria_count"),
        "valid_criteria_count": judge.get("valid_criteria_count"),
        "invalid_criteria_count": judge.get("invalid_criteria_count"),
    }


def trace_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_index": row.get("row_index"),
        "task_id": row.get("task_id"),
        "group": row.get("group"),
        "domain": row.get("domain"),
        "runner_mode": row.get("runner_mode"),
        "tools_enabled": row.get("tools_enabled"),
        "tool_policy": row.get("tool_policy") or {},
        "generation_policy": row.get("generation_policy") or {},
        "generation_config": row.get("generation_config") or {},
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "prompt_sha256": row.get("prompt_sha256"),
        "final_text_sha256": row.get("final_text_sha256"),
        "final_text_chars": row.get("final_text_chars"),
        "error": row.get("error"),
        "stream_tool_call_count": row.get("stream_tool_call_count"),
        "server_tool_call_count": row.get("server_tool_call_count"),
        "server_tool_use": row.get("server_tool_use") or {},
        "total_tool_call_count": row.get("total_tool_call_count"),
        "trajectory_steps": row.get("trajectory_steps"),
        "llm_request_count": row.get("llm_request_count"),
        "generation_attempt_count": row.get("generation_attempt_count"),
        "generation_max_attempts": row.get("generation_max_attempts"),
        "generation_retry_backoff_s": row.get("generation_retry_backoff_s"),
        "generation_attempt_total_billed_cost": row.get(
            "generation_attempt_total_billed_cost"
        ),
        "generation_retry_reasons": row.get("generation_retry_reasons") or [],
        "execution": row.get("execution") or {},
        "usage": row.get("usage") or {},
        "run_trace": row.get("run_trace") or {},
        "ensemble_trace": row.get("ensemble_trace") or {},
        "judge": compact_judge_summary(row.get("judge")),
        "candidate_judge_count": len(row.get("candidate_judges") or []),
        "fusion_delta": row.get("fusion_delta"),
    }


def percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return float(ordered[index])


def numeric_pct_delta(value: Any, baseline: Any) -> float | None:
    if isinstance(value, int | float) and isinstance(baseline, int | float):
        baseline_float = float(baseline)
        if baseline_float == 0.0:
            return None
        return (float(value) - baseline_float) / baseline_float * 100.0
    return None


def row_metric_int(row: dict[str, Any], key: str, fallback_key: str | None = None) -> int:
    value = row.get(key)
    if value is None and fallback_key is not None:
        value = row.get(fallback_key)
    return coerce_metric_int(value)


def row_generation_attempt_usage_total(row: dict[str, Any], key: str) -> float | None:
    execution = row.get("execution") or {}
    attempts = execution.get("generation_attempts")
    if not isinstance(attempts, list) or not attempts:
        return None
    total = 0.0
    observed_usage = False
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        run = attempt.get("run")
        if not isinstance(run, dict):
            continue
        usage = run.get("usage")
        if not isinstance(usage, dict):
            continue
        value = usage.get(key)
        if isinstance(value, int | float):
            total += float(value)
            observed_usage = True
    return total if observed_usage else 0.0


def row_usage_number(row: dict[str, Any], key: str) -> float:
    attempt_total = row_generation_attempt_usage_total(row, key)
    if attempt_total is not None:
        return attempt_total
    usage = row.get("usage") or {}
    if isinstance(usage, dict):
        value = usage.get(key)
        if isinstance(value, int | float):
            return float(value)
    return 0.0


def row_billed_cost(row: dict[str, Any]) -> float:
    attempt_cost = row_generation_attempt_usage_total(row, "billed_cost")
    if attempt_cost is not None:
        return attempt_cost
    value = row.get("generation_attempt_total_billed_cost")
    if isinstance(value, int | float):
        return float(value)
    execution = row.get("execution") or {}
    value = execution.get("generation_attempt_total_billed_cost")
    if isinstance(value, int | float):
        return float(value)
    return row_usage_number(row, "billed_cost")


def row_server_tool_call_count(row: dict[str, Any]) -> int:
    direct = row_metric_int(row, "server_tool_call_count")
    if direct:
        return direct
    usage = row.get("usage") or {}
    if isinstance(usage, dict):
        return sum(server_tool_counts_from_usage_payload(usage).values())
    return 0


def row_total_tool_call_count(row: dict[str, Any]) -> int:
    direct = row_metric_int(row, "total_tool_call_count")
    if direct:
        return direct
    stream_count = row_metric_int(row, "stream_tool_call_count", "tool_call_count")
    return stream_count + row_server_tool_call_count(row)


def row_llm_request_count(row: dict[str, Any]) -> int:
    direct = row_metric_int(row, "llm_request_count")
    if direct:
        return direct
    usage = row.get("usage") or {}
    breakdown = usage.get("model_usage_breakdown") if isinstance(usage, dict) else None
    if isinstance(breakdown, list) and breakdown:
        return len(breakdown)
    provider_spec = row.get("provider_spec") or {}
    execution = row.get("execution") or {}
    if provider_spec.get("kind") == "single" and not execution.get("provider_error"):
        return 1
    return 0


def ensemble_usage_unknown_count(trace: Any) -> int:
    if not isinstance(trace, dict):
        return 0
    calls = trace.get("calls")
    if isinstance(calls, list):
        return sum(ensemble_usage_unknown_count(call) for call in calls)
    early_stop = trace.get("proposer_early_stop")
    if isinstance(early_stop, dict):
        value = coerce_metric_int(early_stop.get("usage_unknown_count"))
        if value:
            return value
    candidates = trace.get("candidates")
    if isinstance(candidates, list):
        return sum(
            1
            for candidate in candidates
            if isinstance(candidate, dict)
            and candidate.get("error_code") == "early_stopped"
        )
    return 0


def usage_unknown_count_from_usage_payload(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    breakdown = usage.get("model_usage_breakdown")
    if not isinstance(breakdown, list):
        return 0
    return sum(
        1
        for item in breakdown
        if isinstance(item, dict)
        and (
            item.get("cost_source") == "unknown_canceled"
            or item.get("error_code") == "early_stopped"
        )
    )


def row_generation_attempt_usage_unknown_count(row: dict[str, Any]) -> int:
    execution = row.get("execution") or {}
    attempts = execution.get("generation_attempts") if isinstance(execution, dict) else None
    if not isinstance(attempts, list):
        return 0
    total = 0
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        run = attempt.get("run")
        if not isinstance(run, dict):
            continue
        total += max(
            coerce_metric_int(run.get("usage_unknown_count")),
            usage_unknown_count_from_usage_payload(run.get("usage")),
            ensemble_usage_unknown_count(run.get("ensemble_trace")),
        )
    return total


def row_usage_unknown_count(row: dict[str, Any]) -> int:
    direct = row_metric_int(row, "usage_unknown_count")
    execution = row.get("execution") or {}
    execution_value = 0
    if isinstance(execution, dict):
        execution_value = coerce_metric_int(execution.get("usage_unknown_count"))
    return max(
        direct,
        execution_value,
        row_generation_attempt_usage_unknown_count(row),
        usage_unknown_count_from_usage_payload(row.get("usage")),
        ensemble_usage_unknown_count(row.get("ensemble_trace")),
    )


def row_trajectory_steps(row: dict[str, Any]) -> int:
    llm_requests = row_llm_request_count(row)
    tool_calls = row_total_tool_call_count(row)
    if llm_requests or tool_calls:
        return llm_requests + tool_calls
    return row_metric_int(row, "trajectory_steps")


def completed_quality_value(row: dict[str, Any]) -> float:
    if row.get("error"):
        return 0.0
    value = row.get("quality_total")
    return float(value) if isinstance(value, int | float) else 0.0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"groups": {}}
    judging_enabled = any(isinstance(row.get("judge"), dict) for row in rows)
    for group in sorted({row["group"] for row in rows}):
        group_rows = [row for row in rows if row["group"] == group]
        completed_rows = [row for row in group_rows if not row.get("error")]
        latencies = [int(row["latency_ms"] or 0) for row in group_rows]
        scored_totals = [
            completed_quality_value(row)
            for row in completed_rows
            if row["quality_total"] is not None
        ]
        quality_values = (
            [completed_quality_value(row) for row in group_rows]
            if judging_enabled
            else []
        )
        completed_quality_values = [
            completed_quality_value(row)
            for row in completed_rows
        ] if judging_enabled else []
        pass_rates = [
            float((row.get("judge") or {}).get("pass_rate"))
            for row in completed_rows
            if isinstance((row.get("judge") or {}).get("pass_rate"), int | float)
        ]
        costs = [row_billed_cost(row) for row in group_rows]
        completed_costs = [row_billed_cost(row) for row in completed_rows]
        visible_tokens = [
            int(row_usage_number(row, "input_tokens"))
            + int(row_usage_number(row, "output_tokens"))
            for row in group_rows
        ]
        reasoning_tokens = [
            int(row_usage_number(row, "reasoning_tokens"))
            for row in group_rows
        ]
        all_tokens = [
            visible + reasoning
            for visible, reasoning in zip(visible_tokens, reasoning_tokens, strict=False)
        ]
        stream_tool_calls = [
            row_metric_int(row, "stream_tool_call_count", "tool_call_count")
            for row in group_rows
        ]
        server_tool_calls = [
            row_server_tool_call_count(row)
            for row in group_rows
        ]
        total_tool_calls = [
            row_total_tool_call_count(row)
            for row in group_rows
        ]
        trajectory_steps = [
            row_trajectory_steps(row)
            for row in group_rows
        ]
        llm_requests = [row_llm_request_count(row) for row in group_rows]
        usage_unknown = [row_usage_unknown_count(row) for row in group_rows]
        summary["groups"][group] = {
            "rows": len(group_rows),
            "completed": len(completed_rows),
            "scored_rows": len(scored_totals),
            "score_coverage_pct": (
                len(scored_totals) / len(group_rows) * 100.0 if group_rows else 0.0
            ),
            "avg_quality": statistics.mean(quality_values) if quality_values else None,
            "avg_quality_scored": (
                statistics.mean(completed_quality_values)
                if completed_quality_values
                else None
            ),
            "avg_pass_rate": statistics.mean(pass_rates) if pass_rates else None,
            "judge_errors": sum(
                int((row.get("judge") or {}).get("judge_error_count") or 0)
                for row in completed_rows
            ),
            "avg_cost_usd": statistics.mean(costs) if costs else 0.0,
            "avg_cost_completed_usd": (
                statistics.mean(completed_costs) if completed_costs else None
            ),
            "avg_visible_tokens": (
                statistics.mean(visible_tokens) if visible_tokens else 0.0
            ),
            "avg_reasoning_tokens": (
                statistics.mean(reasoning_tokens) if reasoning_tokens else 0.0
            ),
            "avg_total_tokens": statistics.mean(all_tokens) if all_tokens else 0.0,
            "avg_stream_tool_calls": (
                statistics.mean(stream_tool_calls) if stream_tool_calls else 0.0
            ),
            "avg_server_tool_calls": (
                statistics.mean(server_tool_calls) if server_tool_calls else 0.0
            ),
            "avg_tool_calls": (
                statistics.mean(total_tool_calls) if total_tool_calls else 0.0
            ),
            "total_tool_calls": sum(total_tool_calls),
            "tool_call_rate_pct": (
                sum(1 for count in total_tool_calls if count > 0)
                / len(total_tool_calls)
                * 100.0
                if total_tool_calls
                else 0.0
            ),
            "avg_trajectory_steps": (
                statistics.mean(trajectory_steps) if trajectory_steps else 0.0
            ),
            "avg_llm_requests": (
                statistics.mean(llm_requests) if llm_requests else 0.0
            ),
            "total_llm_requests": sum(llm_requests),
            "avg_usage_unknown": (
                statistics.mean(usage_unknown) if usage_unknown else 0.0
            ),
            "total_usage_unknown": sum(usage_unknown),
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
        }
    for item in summary["groups"].values():
        for baseline in ("B0", "B1"):
            baseline_item = summary["groups"].get(baseline) or {}
            suffix = baseline.lower()
            item[f"avg_quality_pct_delta_vs_{suffix}"] = numeric_pct_delta(
                item.get("avg_quality"),
                baseline_item.get("avg_quality"),
            )
            item[f"avg_cost_pct_delta_vs_{suffix}"] = numeric_pct_delta(
                item.get("avg_cost_usd"),
                baseline_item.get("avg_cost_usd"),
            )
    return summary


def render_markdown(
    summary: dict[str, Any],
    jsonl_path: Path,
    tool_policy: dict[str, Any] | None = None,
    generation_policy: dict[str, Any] | None = None,
    runner_mode: str = DEFAULT_DRACO_RUNNER_MODE,
    agent_max_iterations: int = DEFAULT_AGENT_MAX_ITERATIONS,
) -> str:
    stamp = jsonl_path.stem.removeprefix("draco_ensemble_")
    trace_path = jsonl_path.parent / f"draco_run_{stamp}.trace.jsonl"
    policy = tool_policy or benchmark_tool_policy()
    generation = generation_policy or generation_thinking_policy()
    blocked_domains = policy.get("contamination_blocked_domains") or []
    tool_line = (
        f"Runner mode: `{runner_mode}`; tool mode: `{policy.get('tool_mode') or RUNNER_MODE}`; "
        "tools enabled: "
        f"`{str(bool(policy.get('tools_enabled'))).lower()}`"
    )
    if policy.get("tools_enabled"):
        tool_names = ", ".join(str(name) for name in policy.get("tool_names") or [])
        if tool_names:
            tool_line = f"{tool_line}; tools: `{tool_names}`."
        else:
            tool_line = f"{tool_line}."
    if not policy.get("tools_enabled"):
        tool_line = (
            f"Runner mode: `{runner_mode}`; tool mode: "
            f"`{policy.get('tool_mode') or RUNNER_MODE}`; "
            "external research tools are not attached."
        )
    group_tool_policies = policy.get("group_tool_policies") or {}
    fusion_groups = [
        str(group)
        for group, group_policy in group_tool_policies.items()
        if isinstance(group_policy, dict) and group_policy.get("openrouter_fusion_enabled")
    ]
    fusion_line = ""
    if fusion_groups:
        if not policy.get("tools_enabled"):
            tool_line = (
                f"Runner mode: `{runner_mode}`; tool mode: "
                f"`{policy.get('tool_mode') or RUNNER_MODE}`; "
                "no global external research tools are attached."
            )
        fusion_line = (
            "OpenRouter Fusion groups: "
            f"`{', '.join(sorted(fusion_groups))}` use only `openrouter:fusion` "
            "with `tool_choice=required`; Fusion's internal web_search/web_fetch "
            "domain controls are not exposed in the documented tool parameters."
        )
    generation_budget_note = f"budget: `{generation.get('thinking_budget_tokens')}`"
    if generation.get("max_thinking_budget_tokens") is not None:
        generation_budget_note = (
            f"{generation_budget_note}, "
            f"max budget: `{generation.get('max_thinking_budget_tokens')}`"
        )

    def _signed_pct(value: Any) -> str:
        return f"{float(value):+.2f}%" if isinstance(value, int | float) else ""

    lines = [
        "# DRACO Ensemble Summary",
        "",
        f"Raw JSONL: `{jsonl_path}`",
        f"Trace JSONL: `{trace_path}`",
        "",
        "Generation thinking: "
        f"`{generation.get('generation_thinking')}` "
        f"(enabled: `{generation.get('thinking_enabled')}`, "
        f"level: `{generation.get('thinking_level')}`, "
        f"{generation_budget_note}, "
        f"temperature: `{generation.get('temperature')}`).",
        f"Agent max iterations: `{agent_max_iterations}`.",
        tool_line,
        *([fusion_line] if fusion_line else []),
        "Contamination blocked domains: "
        f"`{', '.join(blocked_domains) if blocked_domains else '(none)'}`.",
        "",
        "| Group | Rows | Done | Avg Quality | AvgQ Scored | Avg Pass | "
        "Judge Err | Avg $ | Avg $ Done | Avg Visible | Avg Reason | Avg Tokens | "
        "Avg Tools | Tool % | Avg Steps | Avg LLM Req | Usage Unknown | p50 ms | p95 ms | "
        "AvgQ % vs B0 | Avg$ % vs B0 | "
        "AvgQ % vs B1 | Avg$ % vs B1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: | ---: | ---: | ---: |",
    ]
    for group, item in sorted(summary["groups"].items()):
        lines.append(
            "| {group} | {rows} | {done} | {quality} | {quality_scored} | "
            "{pass_rate} | {judge_errors} | {cost:.6f} | "
            "{cost_done} | {visible_tokens:.1f} | {reasoning_tokens:.1f} | "
            "{tokens:.1f} | {tool_calls:.1f} | {tool_rate:.1f}% | "
            "{steps:.1f} | {llm_requests:.1f} | {usage_unknown:.1f} | "
            "{p50:.0f} | {p95:.0f} | "
            "{q_b0} | {cost_b0} | {q_b1} | {cost_b1} |".format(
                group=group,
                rows=item["rows"],
                done=item["completed"],
                quality=(
                    f"{item['avg_quality']:.2f}" if item["avg_quality"] is not None else ""
                ),
                quality_scored=(
                    f"{item['avg_quality_scored']:.2f}"
                    if item["avg_quality_scored"] is not None
                    else ""
                ),
                pass_rate=(
                    f"{item['avg_pass_rate']:.2f}"
                    if item["avg_pass_rate"] is not None
                    else ""
                ),
                judge_errors=item["judge_errors"],
                cost=item["avg_cost_usd"],
                cost_done=(
                    f"{item['avg_cost_completed_usd']:.6f}"
                    if item["avg_cost_completed_usd"] is not None
                    else ""
                ),
                visible_tokens=item["avg_visible_tokens"],
                reasoning_tokens=item["avg_reasoning_tokens"],
                tokens=item["avg_total_tokens"],
                tool_calls=item["avg_tool_calls"],
                tool_rate=item["tool_call_rate_pct"],
                steps=item["avg_trajectory_steps"],
                llm_requests=item["avg_llm_requests"],
                usage_unknown=item["avg_usage_unknown"],
                p50=item["latency_p50_ms"],
                p95=item["latency_p95_ms"],
                q_b0=_signed_pct(item.get("avg_quality_pct_delta_vs_b0")),
                cost_b0=_signed_pct(item.get("avg_cost_pct_delta_vs_b0")),
                q_b1=_signed_pct(item.get("avg_quality_pct_delta_vs_b1")),
                cost_b1=_signed_pct(item.get("avg_cost_pct_delta_vs_b1")),
            )
        )
    return "\n".join(lines) + "\n"


def manifest_args(args: argparse.Namespace) -> dict[str, Any]:
    keys = [
        "input",
        "config",
        "output_dir",
        "groups",
        "max_tasks",
        "concurrency",
        "timeout",
        "ensemble_proposer_timeout",
        "ensemble_aggregator_timeout",
        "ensemble_proposer_early_stop_success_count",
        "ensemble_proposer_early_stop_after",
        "expand_ensemble_timeouts_to_task_timeout",
        "runner_mode",
        "agent_max_iterations",
        "dry_run",
        "judge_model",
        "judge_repeats",
        "judge_concurrency",
        "judge_max_attempts",
        "judge_candidates",
        "generation_max_attempts",
        "generation_retry_backoff",
        "tool_mode",
        "contamination_blocked_domains",
        "local_web_search_provider",
        "local_web_search_api_key_env",
        "openrouter_web_search_engine",
        "openrouter_web_search_max_results",
        "openrouter_web_search_max_total_results",
        "openrouter_web_search_context_size",
        "openrouter_web_fetch_engine",
        "openrouter_web_fetch_max_uses",
        "openrouter_web_fetch_max_content_tokens",
        "openrouter_fusion_analysis_models",
        "openrouter_fusion_model",
        "openrouter_fusion_max_tool_calls",
        "openrouter_fusion_max_completion_tokens",
        "openrouter_fusion_reasoning_effort",
        "openrouter_fusion_temperature",
    ]
    payload: dict[str, Any] = {}
    for key in keys:
        value = getattr(args, key, None)
        payload[key] = str(value) if isinstance(value, Path) else value
    return payload


def reconstructed_cli_args(args: argparse.Namespace) -> list[str]:
    cli_args: list[str] = []
    for key, value in manifest_args(args).items():
        if value is None or value == "" or value is False:
            continue
        flag = f"--{key.replace('_', '-')}"
        if value is True:
            cli_args.append(flag)
        else:
            cli_args.extend([flag, str(value)])
    return cli_args


def command_argv(args: argparse.Namespace) -> list[str]:
    raw_argv = getattr(args, "command_argv", None)
    if raw_argv:
        return [str(item) for item in raw_argv]
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        *reconstructed_cli_args(args),
    ]


def command_payload(args: argparse.Namespace) -> dict[str, Any]:
    argv = command_argv(args)
    pythonpath = os.environ.get("PYTHONPATH", "")
    shell = shlex.join(argv)
    if pythonpath:
        shell = f"PYTHONPATH={shlex.quote(pythonpath)} {shell}"
    return {
        "cwd": str(Path.cwd()),
        "python": sys.executable,
        "argv": argv,
        "shell": shell,
        "pythonpath": pythonpath,
        "parsed_args": manifest_args(args),
    }


def write_command_file(
    path: Path,
    *,
    args: argparse.Namespace,
    stamp: str,
) -> dict[str, Any]:
    payload = command_payload(args)
    lines = [
        "# DRACO benchmark command",
        f"stamp: {stamp}",
        f"cwd: {payload['cwd']}",
        f"python: {payload['python']}",
    ]
    if payload["pythonpath"]:
        lines.append(f"PYTHONPATH: {payload['pythonpath']}")
    lines.extend(
        [
            "",
            payload["shell"],
            "",
            "# Parsed args",
            json.dumps(payload["parsed_args"], ensure_ascii=False, indent=2, sort_keys=True),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return payload


def write_manifest(
    path: Path,
    *,
    args: argparse.Namespace,
    stamp: str,
    status: str,
    started_at: float,
    tasks: list[dict[str, Any]],
    groups: list[str],
    artifacts: dict[str, str],
    rows_written: int = 0,
    finished_at: float | None = None,
    summary: dict[str, Any] | None = None,
    tool_policy: dict[str, Any] | None = None,
    command: dict[str, Any] | None = None,
) -> None:
    policy = tool_policy or benchmark_tool_policy(args)
    generation_policy = generation_thinking_policy()
    payload: dict[str, Any] = {
        "benchmark": "DRACO",
        "runner": "scripts/run_draco_ensemble.py",
        "runner_mode": getattr(args, "runner_mode", DEFAULT_DRACO_RUNNER_MODE),
        "agent_max_iterations": getattr(
            args,
            "agent_max_iterations",
            DEFAULT_AGENT_MAX_ITERATIONS,
        ),
        "tool_policy": policy,
        "generation_policy": generation_policy,
        "stamp": stamp,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_ms": (
            int((finished_at - started_at) * 1000) if finished_at is not None else None
        ),
        "args": manifest_args(args),
        "groups": groups,
        "group_specs": {group: GROUP_SPECS[group] for group in groups},
        "task_count": len(tasks),
        "task_ids": [str(task["id"]) for task in tasks],
        "rows_written": rows_written,
        "artifacts": artifacts,
    }
    if command is not None:
        payload["command"] = command
    if summary is not None:
        payload["summary"] = summary
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def amain(args: argparse.Namespace) -> int:
    tasks = load_tasks(args.input, max_tasks=args.max_tasks)
    groups = parse_groups(args.groups)
    args.runner_mode = str(
        getattr(args, "runner_mode", DEFAULT_DRACO_RUNNER_MODE)
        or DEFAULT_DRACO_RUNNER_MODE
    ).strip()
    if args.runner_mode not in SUPPORTED_RUNNER_MODES:
        raise ValueError(f"unknown runner mode: {args.runner_mode}")
    validate_runner_mode_for_groups(args.runner_mode, groups)
    try:
        args.agent_max_iterations = int(
            getattr(args, "agent_max_iterations", DEFAULT_AGENT_MAX_ITERATIONS)
            or DEFAULT_AGENT_MAX_ITERATIONS
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("agent_max_iterations must be an integer") from exc
    args.agent_max_iterations = max(0, args.agent_max_iterations)
    args.generation_max_attempts = bounded_generation_attempts(
        getattr(args, "generation_max_attempts", GENERATION_MAX_ATTEMPTS)
    )
    args.generation_retry_backoff = bounded_generation_retry_backoff(
        getattr(
            args,
            "generation_retry_backoff",
            DEFAULT_GENERATION_RETRY_BACKOFF_SECONDS,
        )
    )
    tool_policy = benchmark_tool_policy(args)
    if (
        args.runner_mode == RUNNER_MODE_AGENT_LOOP
        and tool_policy.get("tool_mode") == TOOL_MODE_OPENROUTER_SERVER_TOOLS
    ):
        raise ValueError(
            "--runner-mode=agent_loop requires executable local tools; use "
            "--tool-mode=local_web_tools, or use --runner-mode=provider for "
            "OpenRouter server-side tools."
        )
    generation_policy = generation_thinking_policy()
    config = GatewayConfig.load(args.config)
    sandbox_runtime = configure_benchmark_sandbox_runtime(config, tool_policy)
    search_runtime = configure_local_web_search_runtime(config, tool_policy)
    if search_runtime or sandbox_runtime:
        local_web_tools = dict(tool_policy.get("local_web_tools") or {})
        if search_runtime:
            local_web_tools["search_runtime"] = search_runtime
        if sandbox_runtime:
            local_web_tools["sandbox_runtime"] = sandbox_runtime
        tool_policy = {**tool_policy, "local_web_tools": local_web_tools}
    inherited = inherited_provider_config(config)
    group_tool_policies = benchmark_tool_policies_for_groups(
        tool_policy,
        groups,
        args=args,
    )
    manifest_tool_policy = {
        **tool_policy,
        "group_tool_policies": group_tool_policies,
    }
    if (
        tool_policy.get("tools_enabled")
        and tool_policy.get("tool_mode") == TOOL_MODE_OPENROUTER_SERVER_TOOLS
        and inherited.provider != "openrouter"
        and not getattr(args, "dry_run", False)
    ):
        raise ValueError(
            "--tool-mode=openrouter_server_tools requires an OpenRouter runtime provider"
        )
    if (
        any(policy.get("openrouter_fusion_enabled") for policy in group_tool_policies.values())
        and inherited.provider != "openrouter"
        and not getattr(args, "dry_run", False)
    ):
        raise ValueError(
            "OpenRouter Fusion experiment groups require an OpenRouter runtime provider"
        )
    judge_provider = None
    if args.judge_model:
        judge_provider = build_single_provider(
            inherited=inherited,
            group="judge",
            model=args.judge_model,
            dry_run=args.dry_run,
        )
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_started_at = time.time()
    jsonl_path = output_dir / f"draco_ensemble_{stamp}.jsonl"
    trace_path = output_dir / f"draco_run_{stamp}.trace.jsonl"
    manifest_path = output_dir / f"draco_run_{stamp}.manifest.json"
    command_path = output_dir / f"draco_run_{stamp}.command.txt"
    summary_json_path = jsonl_path.with_suffix(".summary.json")
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    rows: list[dict[str, Any]] = []
    artifacts = {
        "results_jsonl": str(jsonl_path),
        "trace_jsonl": str(trace_path),
        "manifest_json": str(manifest_path),
        "command_txt": str(command_path),
        "summary_json": str(summary_json_path),
        "summary_markdown": str(jsonl_path.with_suffix(".md")),
    }
    command = write_command_file(command_path, args=args, stamp=stamp)
    write_manifest(
        manifest_path,
        args=args,
        stamp=stamp,
        status="running",
        started_at=run_started_at,
        tasks=tasks,
        groups=groups,
        artifacts=artifacts,
        tool_policy=manifest_tool_policy,
        command=command,
    )

    async def _guarded(task: dict[str, Any], group: str) -> dict[str, Any]:
        group_tool_policy = group_tool_policies[group]
        group_tools = benchmark_tools_for_policy(group_tool_policy)
        async with semaphore:
            return await run_one(
                task=task,
                group=group,
                config=config,
                inherited=inherited,
                dry_run=args.dry_run,
                judge_provider=judge_provider,
                judge_candidates=args.judge_candidates,
                judge_repeats=args.judge_repeats,
                judge_concurrency=getattr(args, "judge_concurrency", 1),
                judge_max_attempts=getattr(args, "judge_max_attempts", JUDGE_MAX_ATTEMPTS),
                timeout=args.timeout,
                ensemble_proposer_timeout=getattr(
                    args, "ensemble_proposer_timeout", None
                ),
                ensemble_aggregator_timeout=getattr(
                    args, "ensemble_aggregator_timeout", None
                ),
                ensemble_proposer_early_stop_success_count=getattr(
                    args,
                    "ensemble_proposer_early_stop_success_count",
                    None,
                ),
                ensemble_proposer_early_stop_after=getattr(
                    args,
                    "ensemble_proposer_early_stop_after",
                    None,
                ),
                expand_ensemble_timeouts_to_task_timeout=getattr(
                    args,
                    "expand_ensemble_timeouts_to_task_timeout",
                    False,
                ),
                tool_policy=group_tool_policy,
                generation_policy=generation_policy,
                runner_mode=args.runner_mode,
                output_dir=output_dir,
                agent_max_iterations=args.agent_max_iterations,
                generation_max_attempts=getattr(
                    args, "generation_max_attempts", GENERATION_MAX_ATTEMPTS
                ),
                generation_retry_backoff=getattr(
                    args,
                    "generation_retry_backoff",
                    DEFAULT_GENERATION_RETRY_BACKOFF_SECONDS,
                ),
                tools=group_tools,
            )

    pending = [_guarded(task, group) for task in tasks for group in groups]
    with jsonl_path.open("w", encoding="utf-8") as fh, trace_path.open(
        "w", encoding="utf-8"
    ) as trace_fh:
        for row_index, coro in enumerate(asyncio.as_completed(pending), start=1):
            row = await coro
            row["row_index"] = row_index
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            trace_fh.write(json.dumps(trace_row(row), ensure_ascii=False) + "\n")
            trace_fh.flush()
            print(f"{row['group']} {row['task_id']} error={bool(row['error'])}", flush=True)
    summary = summarize(rows)
    summary_path = jsonl_path.with_suffix(".md")
    summary_path.write_text(
        render_markdown(
            summary,
            jsonl_path,
            tool_policy=manifest_tool_policy,
            generation_policy=generation_policy,
            runner_mode=args.runner_mode,
            agent_max_iterations=args.agent_max_iterations,
        ),
        encoding="utf-8",
    )
    summary_json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_manifest(
        manifest_path,
        args=args,
        stamp=stamp,
        status="complete",
        started_at=run_started_at,
        finished_at=time.time(),
        tasks=tasks,
        groups=groups,
        rows_written=len(rows),
        artifacts=artifacts,
        summary=summary,
        tool_policy=manifest_tool_policy,
        command=command,
    )
    print(f"wrote {jsonl_path}")
    print(f"wrote {trace_path}")
    print(f"wrote {manifest_path}")
    print(f"wrote {command_path}")
    print(f"wrote {summary_json_path}")
    print(f"wrote {summary_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="DRACO JSONL input.")
    parser.add_argument("--config", type=Path, default=None, help="OpenSquilla TOML config.")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/draco"))
    parser.add_argument(
        "--groups",
        required=True,
        help="Comma-separated experiment groups to run, for example B0,B1,G3,G8.",
    )
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--ensemble-proposer-timeout",
        type=float,
        default=None,
        help=(
            "Per proposer request timeout in seconds for ensemble profile groups. "
            "By default the profile/default proposer timeout is used and is not "
            "expanded to match --timeout."
        ),
    )
    parser.add_argument(
        "--ensemble-aggregator-timeout",
        type=float,
        default=None,
        help=(
            "Per aggregator/scorer request timeout in seconds for ensemble profile "
            "groups. By default the profile/default aggregator timeout is used and "
            "is not expanded to match --timeout."
        ),
    )
    parser.add_argument(
        "--ensemble-proposer-early-stop-success-count",
        type=int,
        default=None,
        help=(
            "For ensemble profile groups, stop waiting for remaining proposers once "
            "this many successful candidate responses are available. Omit to use "
            "the profile default; pass 0 to disable."
        ),
    )
    parser.add_argument(
        "--ensemble-proposer-early-stop-after",
        type=float,
        default=None,
        help=(
            "Minimum seconds to wait before applying proposer early-stop. Omit to "
            "use the profile default; pass 0 to stop as soon as the success quorum "
            "is reached."
        ),
    )
    parser.add_argument(
        "--expand-ensemble-timeouts-to-task-timeout",
        action="store_true",
        help=(
            "Legacy behavior: distribute spare --timeout budget into per-member "
            "ensemble proposer/aggregator timeouts. Leave off for lower tail latency."
        ),
    )
    parser.add_argument(
        "--runner-mode",
        choices=SUPPORTED_RUNNER_MODES,
        default=DEFAULT_DRACO_RUNNER_MODE,
        help=(
            "Generation runner. agent_loop runs the full Agent tool loop; "
            "provider runs one provider.chat call for provider-level ablations."
        ),
    )
    parser.add_argument(
        "--agent-max-iterations",
        type=int,
        default=DEFAULT_AGENT_MAX_ITERATIONS,
        help=(
            "Maximum Agent LLM/tool-loop iterations when --runner-mode=agent_loop; "
            "0 means unlimited."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--judge-model", default="")
    parser.add_argument("--judge-repeats", type=int, default=3)
    parser.add_argument("--judge-concurrency", type=int, default=1)
    parser.add_argument("--judge-max-attempts", type=int, default=JUDGE_MAX_ATTEMPTS)
    parser.add_argument("--judge-candidates", action="store_true")
    parser.add_argument(
        "--generation-max-attempts",
        type=int,
        default=GENERATION_MAX_ATTEMPTS,
        help="Maximum answer-generation attempts per row; capped at 3.",
    )
    parser.add_argument(
        "--generation-retry-backoff",
        type=float,
        default=DEFAULT_GENERATION_RETRY_BACKOFF_SECONDS,
        help="Initial seconds to wait before retrying answer generation; doubles each retry.",
    )
    parser.add_argument(
        "--tool-mode",
        choices=SUPPORTED_TOOL_MODES,
        default=TOOL_MODE_PROVIDER_ONLY,
        help=(
            "Benchmark tool mode. provider_only attaches no external tools; "
            "local_web_tools attaches executable web_search and web_fetch tools "
            "for the Agent loop; openrouter_server_tools attaches OpenRouter "
            "server tools for provider-level runs."
        ),
    )
    parser.add_argument(
        "--contamination-blocked-domains",
        default=",".join(DEFAULT_CONTAMINATION_BLOCKED_DOMAINS),
        help=(
            "Comma-separated benchmark leakage domains to exclude from web search "
            "and block from web fetch when research tools are wired."
        ),
    )
    parser.add_argument(
        "--local-web-search-provider",
        choices=SUPPORTED_LOCAL_WEB_SEARCH_PROVIDERS,
        default=DEFAULT_LOCAL_WEB_SEARCH_PROVIDER,
        help=(
            "Provider for executable local web_search when "
            "--tool-mode=local_web_tools."
        ),
    )
    parser.add_argument(
        "--local-web-search-api-key-env",
        default="",
        help=(
            "Environment variable that contains the local web_search provider API key. "
            "Use BRAVE_SEARCH_API_KEY for --local-web-search-provider=brave. "
            "The key value is never written to benchmark command/manifest files."
        ),
    )
    parser.add_argument(
        "--openrouter-web-search-engine",
        default=DEFAULT_OPENROUTER_WEB_SEARCH_ENGINE,
        help="OpenRouter web_search engine used when --tool-mode=openrouter_server_tools.",
    )
    parser.add_argument(
        "--openrouter-web-search-max-results",
        type=int,
        default=DEFAULT_OPENROUTER_WEB_SEARCH_MAX_RESULTS,
        help="Maximum results per OpenRouter web_search call.",
    )
    parser.add_argument(
        "--openrouter-web-search-max-total-results",
        type=int,
        default=DEFAULT_OPENROUTER_WEB_SEARCH_MAX_TOTAL_RESULTS,
        help="Maximum total results across OpenRouter web_search calls.",
    )
    parser.add_argument(
        "--openrouter-web-search-context-size",
        choices=("low", "medium", "high"),
        default=DEFAULT_OPENROUTER_WEB_SEARCH_CONTEXT_SIZE,
        help="Search context size for OpenRouter web_search.",
    )
    parser.add_argument(
        "--openrouter-web-fetch-engine",
        default=DEFAULT_OPENROUTER_WEB_FETCH_ENGINE,
        help="OpenRouter web_fetch engine used when --tool-mode=openrouter_server_tools.",
    )
    parser.add_argument(
        "--openrouter-web-fetch-max-uses",
        type=int,
        default=DEFAULT_OPENROUTER_WEB_FETCH_MAX_USES,
        help="Maximum OpenRouter web_fetch uses per request.",
    )
    parser.add_argument(
        "--openrouter-web-fetch-max-content-tokens",
        type=int,
        default=DEFAULT_OPENROUTER_WEB_FETCH_MAX_CONTENT_TOKENS,
        help="Maximum content tokens returned by OpenRouter web_fetch.",
    )
    parser.add_argument(
        "--openrouter-fusion-analysis-models",
        default=",".join(DEFAULT_OPENROUTER_FUSION_ANALYSIS_MODELS),
        help=(
            "Comma-separated OpenRouter Fusion panel models. Used by B8; "
            "OpenRouter documents 1 to 8 models."
        ),
    )
    parser.add_argument(
        "--openrouter-fusion-model",
        default=DEFAULT_OPENROUTER_FUSION_MODEL,
        help="OpenRouter Fusion judge model. Used by B8.",
    )
    parser.add_argument(
        "--openrouter-fusion-max-tool-calls",
        type=int,
        default=DEFAULT_OPENROUTER_FUSION_MAX_TOOL_CALLS,
        help=(
            "Maximum OpenRouter web_search/web_fetch steps for each Fusion "
            "panel model and judge call; range 1 to 16."
        ),
    )
    parser.add_argument(
        "--openrouter-fusion-max-completion-tokens",
        type=int,
        default=DEFAULT_OPENROUTER_FUSION_MAX_COMPLETION_TOKENS,
        help="Maximum completion tokens for each inner Fusion panel/judge call.",
    )
    parser.add_argument(
        "--openrouter-fusion-reasoning-effort",
        default=DEFAULT_OPENROUTER_FUSION_REASONING_EFFORT,
        help="Reasoning effort forwarded to OpenRouter Fusion panel and judge calls.",
    )
    parser.add_argument(
        "--openrouter-fusion-temperature",
        type=float,
        default=DEFAULT_OPENROUTER_FUSION_TEMPERATURE,
        help="Temperature forwarded to OpenRouter Fusion panel calls.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.command_argv = [sys.executable, *sys.argv]
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
