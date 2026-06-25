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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opensquilla.engine.types import THINKING_BUDGETS, ThinkingLevel
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

GROUP_SPECS: dict[str, dict[str, str]] = {
    "B0": {"kind": "single", "model": "anthropic/claude-opus-4.8"},
    "B1": {"kind": "single", "model": "openai/gpt-5.5"},
    "B2": {"kind": "single", "model": "z-ai/glm-5.2"},
    "B3": {"kind": "profile", "profile": "b3_glm_self_fusion"},
    "G1": {"kind": "profile", "profile": "g1_code"},
    "G2": {"kind": "profile", "profile": "g2_general"},
    "G3": {"kind": "profile", "profile": "g3_standard"},
    "G4": {"kind": "profile", "profile": "g4_gemini_aggregator"},
    "G5": {"kind": "profile", "profile": "g5_opus_aggregator"},
    "G6": {"kind": "profile", "profile": "g6_gpt_aggregator"},
    "G7": {"kind": "profile", "profile": "g7_two_proposers"},
    "G8": {"kind": "profile", "profile": "g8_four_proposers"},
}

TOOL_MODE_PROVIDER_ONLY = "provider_only"
TOOL_MODE_OPENROUTER_SERVER_TOOLS = "openrouter_server_tools"
RUNNER_MODE = TOOL_MODE_PROVIDER_ONLY
SUPPORTED_TOOL_MODES = (TOOL_MODE_PROVIDER_ONLY, TOOL_MODE_OPENROUTER_SERVER_TOOLS)
DEFAULT_OPENROUTER_WEB_SEARCH_ENGINE = "exa"
DEFAULT_OPENROUTER_WEB_SEARCH_MAX_RESULTS = 5
DEFAULT_OPENROUTER_WEB_SEARCH_MAX_TOTAL_RESULTS = 10
DEFAULT_OPENROUTER_WEB_SEARCH_CONTEXT_SIZE = "medium"
DEFAULT_OPENROUTER_WEB_FETCH_ENGINE = "openrouter"
DEFAULT_OPENROUTER_WEB_FETCH_MAX_USES = 5
DEFAULT_OPENROUTER_WEB_FETCH_MAX_CONTENT_TOKENS = 50_000
GENERATION_THINKING_PROFILE = "profile"
DEFAULT_GENERATION_THINKING = "high"
DEFAULT_GENERATION_TEMPERATURE = 0.0
SUPPORTED_GENERATION_THINKING = (
    GENERATION_THINKING_PROFILE,
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
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


def benchmark_tool_policy(args: argparse.Namespace | None = None) -> dict[str, Any]:
    mode = str(getattr(args, "tool_mode", RUNNER_MODE) or RUNNER_MODE).strip()
    blocked_domains = parse_domain_list(
        getattr(args, "contamination_blocked_domains", None)
    )
    if mode not in SUPPORTED_TOOL_MODES:
        raise ValueError(f"unknown tool mode: {mode}")
    if mode != TOOL_MODE_PROVIDER_ONLY:
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


def benchmark_tools_for_policy(tool_policy: dict[str, Any]) -> list[ToolDefinition] | None:
    if not tool_policy.get("tools_enabled"):
        return None
    server_tools = tool_policy.get("openrouter_server_tools") or {}
    tools: list[ToolDefinition] = []
    for key, description in (
        ("web_search", "OpenRouter server-side web search."),
        ("web_fetch", "OpenRouter server-side web fetch."),
    ):
        provider_tool = server_tools.get(key)
        if not isinstance(provider_tool, dict):
            continue
        tool_type = str(provider_tool.get("type") or key)
        tools.append(
            ToolDefinition(
                name=tool_type,
                description=description,
                input_schema=ToolInputSchema(),
                provider_tool=provider_tool,
            )
        )
    return tools or None


def normalize_generation_thinking(raw: Any) -> str:
    value = str(raw or DEFAULT_GENERATION_THINKING).strip().lower()
    if value not in SUPPORTED_GENERATION_THINKING:
        allowed = ", ".join(SUPPORTED_GENERATION_THINKING)
        raise ValueError(
            f"unknown generation thinking policy {value!r}; expected one of {allowed}"
        )
    return value


def generation_thinking_policy(args: argparse.Namespace | None = None) -> dict[str, Any]:
    mode = normalize_generation_thinking(
        getattr(args, "generation_thinking", DEFAULT_GENERATION_THINKING)
    )
    if mode == GENERATION_THINKING_PROFILE:
        return {
            "generation_thinking": mode,
            "temperature": DEFAULT_GENERATION_TEMPERATURE,
            "thinking_enabled": "profile_default",
            "thinking_level": None,
            "thinking_budget_tokens": None,
            "applies_to": (
                "profile members keep configured thinking; single baselines use "
                "ChatConfig defaults"
            ),
        }
    if mode == "off":
        return {
            "generation_thinking": mode,
            "temperature": DEFAULT_GENERATION_TEMPERATURE,
            "thinking_enabled": False,
            "thinking_level": ThinkingLevel.OFF.value,
            "thinking_budget_tokens": 0,
            "applies_to": "single baselines and ensemble members",
        }
    level = ThinkingLevel(mode)
    return {
        "generation_thinking": mode,
        "temperature": DEFAULT_GENERATION_TEMPERATURE,
        "thinking_enabled": True,
        "thinking_level": level.value,
        "thinking_budget_tokens": THINKING_BUDGETS[level],
        "applies_to": "single baselines and ensemble members",
    }


def generation_chat_config(policy: dict[str, Any]) -> ChatConfig:
    mode = str(policy.get("generation_thinking") or DEFAULT_GENERATION_THINKING)
    if mode == GENERATION_THINKING_PROFILE:
        return ChatConfig(temperature=DEFAULT_GENERATION_TEMPERATURE)
    if mode == "off":
        return ChatConfig(
            temperature=DEFAULT_GENERATION_TEMPERATURE,
            thinking=False,
            thinking_level=ThinkingLevel.OFF,
            thinking_budget_tokens=0,
        )
    level = ThinkingLevel(mode)
    return ChatConfig(
        temperature=DEFAULT_GENERATION_TEMPERATURE,
        thinking=True,
        thinking_level=level,
        thinking_budget_tokens=THINKING_BUDGETS[level],
    )


def apply_generation_policy_to_profile(profile: Any, policy: dict[str, Any]) -> Any:
    mode = str(policy.get("generation_thinking") or DEFAULT_GENERATION_THINKING)
    member_update: dict[str, Any] = {"temperature": DEFAULT_GENERATION_TEMPERATURE}
    if mode != GENERATION_THINKING_PROFILE:
        member_update["thinking"] = "off" if mode == "off" else mode
    proposers = [
        proposer.model_copy(update=member_update)
        for proposer in profile.proposers
    ]
    aggregator = profile.aggregator.model_copy(update=member_update)
    return profile.model_copy(update={"proposers": proposers, "aggregator": aggregator})


def compact_chat_config(
    config: ChatConfig | None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = str((policy or {}).get("generation_thinking") or "")
    if config is None or mode == GENERATION_THINKING_PROFILE:
        return {
            "thinking": "profile_default",
            "thinking_level": None,
            "thinking_budget_tokens": None,
            "temperature": (
                config.temperature if config is not None else DEFAULT_GENERATION_TEMPERATURE
            ),
            "max_tokens": config.max_tokens if config is not None else None,
        }
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
) -> tuple[float, float]:
    proposer_timeout = max(
        DEFAULT_PROFILE_PROPOSER_TIMEOUT_SECONDS,
        float(getattr(profile, "proposer_timeout_seconds", 0) or 0),
    )
    aggregator_timeout = max(
        DEFAULT_PROFILE_AGGREGATOR_TIMEOUT_SECONDS,
        float(getattr(profile, "aggregator_timeout_seconds", 0) or 0),
    )
    if requested_timeout is None or requested_timeout <= 0:
        return proposer_timeout, aggregator_timeout
    available = max(0.0, float(requested_timeout) - PROFILE_TIMEOUT_MARGIN_SECONDS)
    base_budget = proposer_timeout + aggregator_timeout
    if available <= base_budget:
        return proposer_timeout, aggregator_timeout
    extra = available - base_budget
    return proposer_timeout + extra * 0.25, aggregator_timeout + extra * 0.75


def profile_aggregator_timeout_seconds(
    profile: Any,
    *,
    requested_timeout: float | None = None,
) -> float:
    return profile_timeout_seconds(
        profile,
        requested_timeout=requested_timeout,
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
):
    if dry_run:
        return DryProvider(model=model, group=group)
    cfg = ProviderConfig(
        provider=inherited.provider,
        model=model,
        api_key=inherited.api_key,
        base_url=inherited.base_url,
        proxy=inherited.proxy,
        provider_routing=inherited.provider_routing,
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
    )
    config.llm_ensemble.profiles[profile] = profile_config.model_copy(
        update={
            "record_candidates": True,
            "shuffle_candidates": False,
            "proposer_timeout_seconds": proposer_timeout_s,
            "aggregator_timeout_seconds": aggregator_timeout_s,
        }
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


def candidate_texts(done: DoneEvent | None) -> list[str]:
    if done is None:
        return []
    trace = done.ensemble_trace or {}
    candidates = trace.get("candidates") if isinstance(trace, dict) else None
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
    if result.done is not None:
        if isinstance(result.done.ensemble_trace, dict):
            llm_request_count = coerce_metric_int(
                result.done.ensemble_trace.get("llm_request_count")
            )
        if not llm_request_count and result.done.model_usage_breakdown:
            llm_request_count = len(result.done.model_usage_breakdown)
        if not llm_request_count:
            llm_request_count = 1
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
    max_attempts: int = GENERATION_MAX_ATTEMPTS,
    retry_backoff_seconds: float = 0.0,
) -> tuple[RunResult, list[dict[str, Any]], int]:
    attempts: list[dict[str, Any]] = []
    best_non_empty: RunResult | None = None
    last_result: RunResult | None = None
    attempt_limit = bounded_generation_attempts(max_attempts)
    for attempt_index in range(1, attempt_limit + 1):
        result = await collect_run(
            provider,
            prompt,
            timeout=timeout,
            config=config,
            tools=tools,
        )
        last_result = result
        reason = generation_retry_reason(result)
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
    tool_policy: dict[str, Any],
    generation_policy: dict[str, Any],
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
    generation_config = generation_chat_config(generation_policy)
    effective_timeout = group_timeout_seconds(
        requested_timeout=timeout,
        config=config,
        group=group,
    )
    try:
        if spec["kind"] == "single":
            provider = build_single_provider(
                inherited=inherited,
                group=group,
                model=spec["model"],
                dry_run=dry_run,
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
                enable_proposer_tools=bool(tool_policy.get("tools_enabled")),
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
                max_attempts=generation_attempt_limit,
                retry_backoff_seconds=generation_retry_backoff_s,
            )
        )
    else:
        run = RunResult(final_text="", done=None, error=provider_error)
        generation_attempts = []
        selected_generation_attempt_index = 0
    profile_proposer_timeout_s = getattr(provider, "proposer_timeout_seconds", None)
    profile_aggregator_timeout_s = getattr(provider, "aggregator_timeout_seconds", None)
    judge = await judge_text(
        judge_provider=judge_provider,
        task=task,
        answer=run.final_text,
        dry_run=dry_run and judge_provider is not None,
        judge_repeats=judge_repeats,
        judge_concurrency=judge_concurrency,
        judge_max_attempts=judge_max_attempts,
    )
    candidate_judges: list[dict[str, Any] | None] = []
    if judge_candidates:
        for candidate in candidate_texts(run.done):
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
    return {
        "task_id": task["id"],
        "group": group,
        "domain": task.get("domain", ""),
        "prompt": task["prompt"],
        "prompt_sha256": prompt_sha,
        "metadata": task.get("metadata", {}),
        "provider_spec": dict(spec),
        "runner_mode": tool_policy.get("tool_mode") or RUNNER_MODE,
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
            "requested_timeout_s": timeout,
            "effective_timeout_s": effective_timeout,
            "profile_proposer_timeout_s": profile_proposer_timeout_s,
            "profile_aggregator_timeout_s": profile_aggregator_timeout_s,
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
        "ensemble_trace": (run.done.ensemble_trace if run.done is not None else {}),
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
        requested_timeout=requested_timeout,
    )
    profile_budget = (
        proposer_timeout_s
        + aggregator_timeout_s
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


def row_trajectory_steps(row: dict[str, Any]) -> int:
    llm_requests = row_llm_request_count(row)
    tool_calls = row_total_tool_call_count(row)
    if llm_requests or tool_calls:
        return llm_requests + tool_calls
    return row_metric_int(row, "trajectory_steps")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"groups": {}}
    judging_enabled = any(isinstance(row.get("judge"), dict) for row in rows)
    for group in sorted({row["group"] for row in rows}):
        group_rows = [row for row in rows if row["group"] == group]
        completed_rows = [row for row in group_rows if not row.get("error")]
        latencies = [int(row["latency_ms"] or 0) for row in group_rows]
        scored_totals = [
            float(row["quality_total"])
            for row in group_rows
            if row["quality_total"] is not None
        ]
        quality_values = [
            float(row["quality_total"]) if row["quality_total"] is not None else 0.0
            for row in group_rows
        ] if judging_enabled else []
        pass_rates = [
            float((row.get("judge") or {}).get("pass_rate"))
            for row in group_rows
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
        summary["groups"][group] = {
            "rows": len(group_rows),
            "completed": len(completed_rows),
            "scored_rows": len(scored_totals),
            "score_coverage_pct": (
                len(scored_totals) / len(group_rows) * 100.0 if group_rows else 0.0
            ),
            "avg_quality": statistics.mean(quality_values) if quality_values else None,
            "avg_quality_scored": (
                statistics.mean(scored_totals) if scored_totals else None
            ),
            "avg_pass_rate": statistics.mean(pass_rates) if pass_rates else None,
            "judge_errors": sum(
                int((row.get("judge") or {}).get("judge_error_count") or 0)
                for row in group_rows
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
) -> str:
    stamp = jsonl_path.stem.removeprefix("draco_ensemble_")
    trace_path = jsonl_path.parent / f"draco_run_{stamp}.trace.jsonl"
    policy = tool_policy or benchmark_tool_policy()
    generation = generation_policy or generation_thinking_policy()
    blocked_domains = policy.get("contamination_blocked_domains") or []
    tool_line = (
        f"Runner mode: `{policy.get('tool_mode') or RUNNER_MODE}`; tools enabled: "
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
            f"Runner mode: `{policy.get('tool_mode') or RUNNER_MODE}`; "
            "external research tools are not attached."
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
        f"budget: `{generation.get('thinking_budget_tokens')}`, "
        f"temperature: `{generation.get('temperature')}`).",
        tool_line,
        "Contamination blocked domains: "
        f"`{', '.join(blocked_domains) if blocked_domains else '(none)'}`.",
        "",
        "| Group | Rows | Done | Scored | Avg Quality | AvgQ Scored | Avg Pass | "
        "Judge Err | Avg $ | Avg $ Done | Avg Visible | Avg Reason | Avg Tokens | "
        "Avg Tools | Tool % | Avg Steps | Avg LLM Req | p50 ms | p95 ms | "
        "AvgQ % vs B0 | Avg$ % vs B0 | "
        "AvgQ % vs B1 | Avg$ % vs B1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: | ---: | ---: |",
    ]
    for group, item in sorted(summary["groups"].items()):
        lines.append(
            "| {group} | {rows} | {done} | {scored} | {quality} | "
            "{quality_scored} | {pass_rate} | {judge_errors} | {cost:.6f} | "
            "{cost_done} | {visible_tokens:.1f} | {reasoning_tokens:.1f} | "
            "{tokens:.1f} | {tool_calls:.1f} | {tool_rate:.1f}% | "
            "{steps:.1f} | {llm_requests:.1f} | {p50:.0f} | {p95:.0f} | "
            "{q_b0} | {cost_b0} | {q_b1} | {cost_b1} |".format(
                group=group,
                rows=item["rows"],
                done=item["completed"],
                scored=item["scored_rows"],
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
        "dry_run",
        "judge_model",
        "judge_repeats",
        "judge_concurrency",
        "judge_max_attempts",
        "judge_candidates",
        "generation_max_attempts",
        "generation_retry_backoff",
        "generation_thinking",
        "tool_mode",
        "contamination_blocked_domains",
        "openrouter_web_search_engine",
        "openrouter_web_search_max_results",
        "openrouter_web_search_max_total_results",
        "openrouter_web_search_context_size",
        "openrouter_web_fetch_engine",
        "openrouter_web_fetch_max_uses",
        "openrouter_web_fetch_max_content_tokens",
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
    generation_policy = generation_thinking_policy(args)
    payload: dict[str, Any] = {
        "benchmark": "DRACO",
        "runner": "scripts/run_draco_ensemble.py",
        "runner_mode": policy.get("tool_mode") or RUNNER_MODE,
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
    args.generation_thinking = normalize_generation_thinking(
        getattr(args, "generation_thinking", DEFAULT_GENERATION_THINKING)
    )
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
    benchmark_tools = benchmark_tools_for_policy(tool_policy)
    generation_policy = generation_thinking_policy(args)
    config = GatewayConfig.load(args.config)
    inherited = inherited_provider_config(config)
    if (
        tool_policy.get("tools_enabled")
        and inherited.provider != "openrouter"
        and not getattr(args, "dry_run", False)
    ):
        raise ValueError(
            "--tool-mode=openrouter_server_tools requires an OpenRouter runtime provider"
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
        tool_policy=tool_policy,
        command=command,
    )

    async def _guarded(task: dict[str, Any], group: str) -> dict[str, Any]:
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
                tool_policy=tool_policy,
                generation_policy=generation_policy,
                generation_max_attempts=getattr(
                    args, "generation_max_attempts", GENERATION_MAX_ATTEMPTS
                ),
                generation_retry_backoff=getattr(
                    args,
                    "generation_retry_backoff",
                    DEFAULT_GENERATION_RETRY_BACKOFF_SECONDS,
                ),
                tools=benchmark_tools,
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
            tool_policy=tool_policy,
            generation_policy=generation_policy,
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
        tool_policy=tool_policy,
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
    parser.add_argument("--groups", default="B0,B1,B2,B3,G1,G2,G3,G4,G5,G6,G7,G8")
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
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
        "--generation-thinking",
        choices=SUPPORTED_GENERATION_THINKING,
        default=DEFAULT_GENERATION_THINKING,
        help=(
            "Thinking policy for answer generation. Use 'profile' to preserve "
            "configured profile defaults; otherwise the chosen level is applied "
            "to both single baselines and ensemble members."
        ),
    )
    parser.add_argument(
        "--tool-mode",
        choices=SUPPORTED_TOOL_MODES,
        default=RUNNER_MODE,
        help=(
            "Benchmark tool mode. provider_only attaches no external tools; "
            "openrouter_server_tools attaches OpenRouter web_search and web_fetch "
            "server tools with benchmark leakage domains excluded."
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
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.command_argv = [sys.executable, *sys.argv]
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
