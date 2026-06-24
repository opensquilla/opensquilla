#!/usr/bin/env python3
"""Run DRACO-style B5 ensemble experiments from an external JSONL file."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
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
DEFAULT_CONTAMINATION_BLOCKED_DOMAINS = (
    "huggingface.co",
    "datasets-server.huggingface.co",
    "github.com",
    "raw.githubusercontent.com",
    "arxiv.org",
    "openrouter.ai",
    "perplexity.ai",
    "research.perplexity.ai",
)
PROFILE_TIMEOUT_MARGIN_SECONDS = 30.0
JUDGE_MAX_ATTEMPTS = 3


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
        raise ValueError(
            "DRACO OpenRouter server tools are not wired into this runner yet; "
            "refusing to run until web_search excluded_domains and web_fetch "
            "blocked_domains are enforceable."
        )
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
):
    if dry_run:
        return DryEnsembleProvider(group=group, profile=profile)
    if profile not in config.llm_ensemble.profiles:
        raise ValueError(f"profile {profile!r} for group {group} is not configured")
    config.llm_ensemble.enabled = True
    config.llm_ensemble.active_profile = profile
    config.llm_ensemble.profiles[profile] = config.llm_ensemble.profiles[
        profile
    ].model_copy(update={"record_candidates": True})
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
            tools=None,
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


def done_payload(done: DoneEvent | None) -> dict[str, Any]:
    if done is None:
        return {}
    return {
        "model": done.model,
        "stop_reason": done.stop_reason,
        "input_tokens": done.input_tokens,
        "output_tokens": done.output_tokens,
        "reasoning_tokens": done.reasoning_tokens,
        "cached_tokens": done.cached_tokens,
        "cache_write_tokens": done.cache_write_tokens,
        "billed_cost": done.billed_cost,
        "cost_source": done.cost_source,
        "model_usage_breakdown": done.model_usage_breakdown,
        "reasoning_content_chars": len(done.reasoning_content or ""),
        "thinking_signature_present": bool(done.thinking_signature),
    }


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
    return {
        "latency_ms": result.latency_ms,
        "ttft_ms": result.ttft_ms,
        "tool_call_count": result.tool_call_count,
        "error": result.error,
        "final_text_chars": len(result.final_text),
        "final_text_sha256": text_sha256(result.final_text),
        "usage": done_payload(result.done),
        "trace_events": result.trace_events,
    }


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
) -> dict[str, Any]:
    spec = GROUP_SPECS[group]
    started = time.time()
    provider = None
    provider_error = ""
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
            )
    except Exception as exc:  # noqa: BLE001 - report config errors per row
        provider_error = f"{type(exc).__name__}: {exc}"
    effective_timeout = group_timeout_seconds(
        requested_timeout=timeout,
        config=config,
        group=group,
    )
    run = (
        await collect_run(provider, str(task["prompt"]), timeout=effective_timeout)
        if provider is not None
        else RunResult(final_text="", done=None, error=provider_error)
    )
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
        "contamination_blocked_domains": (
            tool_policy.get("contamination_blocked_domains") or []
        ),
        "started_at": started,
        "completed_at": completed_at,
        "total_elapsed_ms": int((completed_at - started) * 1000),
        "latency_ms": run.latency_ms,
        "ttft_ms": run.ttft_ms,
        "tool_call_count": run.tool_call_count,
        "trajectory_steps": run.tool_call_count,
        "error": run.error,
        "final_text": run.final_text,
        "final_text_chars": len(run.final_text),
        "final_text_sha256": final_text_sha,
        "execution": {
            "provider_error": provider_error,
            "run_error": run.error,
            "requested_timeout_s": timeout,
            "effective_timeout_s": effective_timeout,
            "latency_ms": run.latency_ms,
            "ttft_ms": run.ttft_ms,
            "total_elapsed_ms": int((completed_at - started) * 1000),
            "tool_call_count": run.tool_call_count,
        },
        "run_trace": {
            "event_count": len(run.trace_events),
            "events": run.trace_events,
        },
        "usage": done_payload(run.done),
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
    profile_budget = (
        float(profile.proposer_timeout_seconds)
        + float(profile.aggregator_timeout_seconds)
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
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "prompt_sha256": row.get("prompt_sha256"),
        "final_text_sha256": row.get("final_text_sha256"),
        "final_text_chars": row.get("final_text_chars"),
        "error": row.get("error"),
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


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"groups": {}}
    for group in sorted({row["group"] for row in rows}):
        group_rows = [row for row in rows if row["group"] == group]
        latencies = [int(row["latency_ms"] or 0) for row in group_rows]
        totals = [row["quality_total"] for row in group_rows if row["quality_total"] is not None]
        pass_rates = [
            float((row.get("judge") or {}).get("pass_rate"))
            for row in group_rows
            if isinstance((row.get("judge") or {}).get("pass_rate"), int | float)
        ]
        costs = [
            float((row.get("usage") or {}).get("billed_cost") or 0.0)
            for row in group_rows
        ]
        tokens = [
            int((row.get("usage") or {}).get("input_tokens") or 0)
            + int((row.get("usage") or {}).get("output_tokens") or 0)
            for row in group_rows
        ]
        summary["groups"][group] = {
            "rows": len(group_rows),
            "completed": sum(1 for row in group_rows if not row.get("error")),
            "avg_quality": statistics.mean(totals) if totals else None,
            "avg_pass_rate": statistics.mean(pass_rates) if pass_rates else None,
            "judge_errors": sum(
                int((row.get("judge") or {}).get("judge_error_count") or 0)
                for row in group_rows
            ),
            "avg_cost_usd": statistics.mean(costs) if costs else 0.0,
            "avg_total_tokens": statistics.mean(tokens) if tokens else 0.0,
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
) -> str:
    stamp = jsonl_path.stem.removeprefix("draco_ensemble_")
    trace_path = jsonl_path.parent / f"draco_run_{stamp}.trace.jsonl"
    policy = tool_policy or benchmark_tool_policy()
    blocked_domains = policy.get("contamination_blocked_domains") or []
    tool_line = (
        f"Runner mode: `{policy.get('tool_mode') or RUNNER_MODE}`; tools enabled: "
        f"`{str(bool(policy.get('tools_enabled'))).lower()}`."
    )
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
        tool_line,
        "Contamination blocked domains: "
        f"`{', '.join(blocked_domains) if blocked_domains else '(none)'}`.",
        "",
        "| Group | Rows | Done | Avg Quality | Avg Pass | Judge Err | Avg $ | "
        "Avg Tokens | p50 ms | p95 ms | AvgQ % vs B0 | Avg$ % vs B0 | "
        "AvgQ % vs B1 | Avg$ % vs B1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: | ---: | ---: | ---: |",
    ]
    for group, item in sorted(summary["groups"].items()):
        lines.append(
            "| {group} | {rows} | {done} | {quality} | {pass_rate} | "
            "{judge_errors} | {cost:.6f} | {tokens:.1f} | {p50:.0f} | "
            "{p95:.0f} | {q_b0} | {cost_b0} | {q_b1} | {cost_b1} |".format(
                group=group,
                rows=item["rows"],
                done=item["completed"],
                quality=(
                    f"{item['avg_quality']:.2f}" if item["avg_quality"] is not None else ""
                ),
                pass_rate=(
                    f"{item['avg_pass_rate']:.2f}"
                    if item["avg_pass_rate"] is not None
                    else ""
                ),
                judge_errors=item["judge_errors"],
                cost=item["avg_cost_usd"],
                tokens=item["avg_total_tokens"],
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
        "tool_mode",
        "contamination_blocked_domains",
    ]
    payload: dict[str, Any] = {}
    for key in keys:
        value = getattr(args, key, None)
        payload[key] = str(value) if isinstance(value, Path) else value
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
) -> None:
    policy = tool_policy or benchmark_tool_policy(args)
    payload: dict[str, Any] = {
        "benchmark": "DRACO",
        "runner": "scripts/run_draco_ensemble.py",
        "runner_mode": policy.get("tool_mode") or RUNNER_MODE,
        "tool_policy": policy,
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
    if summary is not None:
        payload["summary"] = summary
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def amain(args: argparse.Namespace) -> int:
    tasks = load_tasks(args.input, max_tasks=args.max_tasks)
    groups = parse_groups(args.groups)
    tool_policy = benchmark_tool_policy(args)
    config = GatewayConfig.load(args.config)
    inherited = inherited_provider_config(config)
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
    summary_json_path = jsonl_path.with_suffix(".summary.json")
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    rows: list[dict[str, Any]] = []
    artifacts = {
        "results_jsonl": str(jsonl_path),
        "trace_jsonl": str(trace_path),
        "manifest_json": str(manifest_path),
        "summary_json": str(summary_json_path),
        "summary_markdown": str(jsonl_path.with_suffix(".md")),
    }
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
        render_markdown(summary, jsonl_path, tool_policy=tool_policy),
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
    )
    print(f"wrote {jsonl_path}")
    print(f"wrote {trace_path}")
    print(f"wrote {manifest_path}")
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
        "--tool-mode",
        choices=SUPPORTED_TOOL_MODES,
        default=RUNNER_MODE,
        help=(
            "Benchmark tool mode. provider_only is the only executable mode today; "
            "openrouter_server_tools is rejected until conflict domains are enforced."
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
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
