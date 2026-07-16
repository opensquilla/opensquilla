"""Experimental B5 multi-model ensemble provider."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from .protocol import LLMProvider, ProviderMetadata
from .registry import get_provider_spec
from .selector import ModelSelector, ProviderConfig, SelectorConfig
from .types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ModelInfo,
    ProviderHeartbeatEvent,
    ReasoningDeltaEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


REQUEST_TRACE_MESSAGE_MAX_CHARS = _env_int(
    "OPENSQUILLA_ENSEMBLE_TRACE_MESSAGE_MAX_CHARS",
    12000,
)
PROPOSER_TOOL_ERROR_MAX_ITEMS = 32


@dataclass(frozen=True)
class EnsembleMemberConfig:
    """A provider plus per-call generation overrides for one ensemble member."""

    provider_config: ProviderConfig
    label: str = ""
    temperature: float | None = None
    max_tokens: int = 0
    thinking: str | None = None
    k: int = 1


@dataclass
class _CandidateResult:
    index: int
    sample_index: int
    label: str
    provider: str
    model: str
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    prompt_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_calls_truncated: bool = False
    tool_call_errors: list[str] = field(default_factory=list)
    tool_call_error_total: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    billed_cost: float = 0.0
    cost_source: str = "none"
    provider_usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ""
    elapsed_ms: int = 0
    ttft_ms: int | None = None
    error: str = ""
    error_code: str = ""
    request: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error and (bool(self.text.strip()) or bool(self.prompt_tool_calls))

    def usage_row(self, *, role: str, profile: str) -> dict[str, Any]:
        row = {
            "role": role,
            "profile": profile,
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "sample_index": self.sample_index,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "billed_cost": self.billed_cost,
            "cost_source": self.cost_source,
        }
        if self.provider_usage:
            row["provider_usage"] = self.provider_usage
        return row

    def trace_row(self, *, include_text: bool) -> dict[str, Any]:
        row: dict[str, Any] = {
            "index": self.index,
            "sample_index": self.sample_index,
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "ok": self.ok,
            "stop_reason": self.stop_reason,
            "elapsed_ms": self.elapsed_ms,
            "ttft_ms": self.ttft_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "billed_cost": self.billed_cost,
            "cost_source": self.cost_source,
        }
        if self.error:
            row["error"] = self.error
            row["error_code"] = self.error_code
        row["tool_call_count"] = len(self.tool_calls)
        if self.tool_call_error_total:
            row["tool_call_error_count"] = self.tool_call_error_total
            row["tool_call_errors"] = list(self.tool_call_errors)
            if self.tool_call_error_total > len(self.tool_call_errors):
                row["tool_call_errors_truncated"] = True
        if self.tool_calls_truncated:
            row["tool_calls_truncated"] = True
        if include_text:
            row["text"] = self.text
            if self.prompt_tool_calls:
                row["tool_calls"] = _jsonable(self.prompt_tool_calls)
            elif self.tool_calls:
                row["tool_calls_omitted"] = True
        return row


@dataclass
class _AggregatorAccumulator:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    billed_cost: float = 0.0
    cost_source: str = "none"
    model: str = ""
    provider_usage: dict[str, Any] = field(default_factory=dict)

    def usage_row(
        self,
        *,
        profile: str,
        member: EnsembleMemberConfig,
        role: str = "aggregator",
        label: str = "",
    ) -> dict[str, Any]:
        cfg = member.provider_config
        row = {
            "role": role,
            "profile": profile,
            "label": label or member.label or role,
            "provider": cfg.provider,
            "model": self.model or cfg.model,
            "sample_index": 0,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "billed_cost": self.billed_cost,
            "cost_source": self.cost_source,
        }
        if self.provider_usage:
            row["provider_usage"] = self.provider_usage
        return row


@dataclass
class _PrefilterResult:
    candidates: list[_CandidateResult]
    usage_rows: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    request_count: int = 0


@dataclass
class _SelectionResult:
    selected: _CandidateResult
    usage_rows: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    request_count: int = 0


@dataclass(frozen=True)
class _CandidateTaskMeta:
    index: int
    sample_index: int
    member: EnsembleMemberConfig
    started: float
    messages: list[Message]
    tools: list[ToolDefinition] | None
    config: ChatConfig | None


@dataclass
class _PendingProposerToolCall:
    tool_use_id: str
    tool_name: str
    synthetic_from_text: bool = False
    json_parts: list[str] = field(default_factory=list)


def _normalize_thinking(value: str | None) -> tuple[bool | None, Any | None]:
    if value is None:
        return None, None
    normalized = str(value).strip().lower()
    if not normalized:
        return None, None
    if normalized == "off":
        return False, "off"
    return True, normalized


def _member_chat_config(base: ChatConfig | None, member: EnsembleMemberConfig) -> ChatConfig:
    cfg = base.model_copy(deep=True) if base is not None else ChatConfig()
    updates: dict[str, Any] = {"model_capabilities": None}
    if member.temperature is not None:
        updates["temperature"] = member.temperature
    if member.max_tokens and member.max_tokens > 0:
        updates["max_tokens"] = member.max_tokens
    thinking, thinking_level = _normalize_thinking(member.thinking)
    if thinking is not None:
        updates["thinking"] = thinking
    if thinking_level is not None:
        updates["thinking_level"] = thinking_level
    return cfg.model_copy(update=updates)


def _build_provider(cfg: ProviderConfig) -> LLMProvider:
    selector = ModelSelector(SelectorConfig(primary=cfg))
    return selector.resolve()


def _truncate_text(
    text: str,
    max_chars: int,
    *,
    strict_budget: bool = False,
) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker = "\n\n[truncated]"
    if strict_budget and max_chars <= len(marker):
        return text[:max_chars]
    return text[: max(0, max_chars - len(marker))] + marker


def _tool_calls_json(tool_calls: Sequence[dict[str, Any]]) -> str:
    return json.dumps(_jsonable(list(tool_calls)), ensure_ascii=False, sort_keys=True)


def _bounded_candidate_tool_calls(
    tool_calls: Sequence[dict[str, Any]],
    max_chars: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    normalized = _jsonable(list(tool_calls))
    if not isinstance(normalized, list):
        normalized = []
    if not normalized:
        return [], 0, False
    serialized = _tool_calls_json(normalized)
    if max_chars <= 0 or len(serialized) <= max_chars:
        return normalized, len(serialized), False

    summaries: list[dict[str, Any]] = []
    for call in normalized:
        if not isinstance(call, dict):
            continue
        arguments = call.get("arguments")
        arguments_json = json.dumps(
            _jsonable(arguments),
            ensure_ascii=False,
            sort_keys=True,
        )
        summary = {
            "tool_use_id": str(call.get("tool_use_id") or ""),
            "name": str(call.get("name") or ""),
            "arguments": {
                "_truncated": True,
                "_original_chars": len(arguments_json),
            },
            "synthetic_from_text": bool(call.get("synthetic_from_text")),
        }
        candidate = [*summaries, summary]
        if len(_tool_calls_json(candidate)) > max_chars:
            break
        summaries.append(summary)
    if not summaries:
        return [], 0, True
    return summaries, len(_tool_calls_json(summaries)), True


def _trace_text(text: str, max_chars: int = REQUEST_TRACE_MESSAGE_MAX_CHARS) -> dict[str, Any]:
    return {
        "content": _truncate_text(text, max_chars),
        "content_chars": len(text),
        "truncated": max_chars > 0 and len(text) > max_chars,
    }


def _jsonable(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _content_to_trace_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(_jsonable(content), ensure_ascii=False, sort_keys=True)


def _message_trace_rows(messages: Sequence[Message]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        row = {
            "index": index,
            "role": message.role,
            **_trace_text(_content_to_trace_text(message.content)),
        }
        if message.reasoning_content:
            reasoning = _trace_text(message.reasoning_content)
            row["reasoning_content"] = reasoning["content"]
            row["reasoning_content_chars"] = reasoning["content_chars"]
            row["reasoning_truncated"] = reasoning["truncated"]
        rows.append(row)
    return rows


def _config_trace(config: ChatConfig | None) -> dict[str, Any]:
    if config is None:
        return {}
    fields = (
        "max_tokens",
        "temperature",
        "thinking",
        "thinking_budget_tokens",
        "thinking_level",
        "timeout",
        "cache_mode",
        "tool_choice",
        "provider_request_max_chars",
    )
    return {field: _jsonable(getattr(config, field)) for field in fields}


def _tool_trace_rows(tools: Sequence[ToolDefinition] | None) -> list[dict[str, Any]]:
    rows = []
    for tool in tools or []:
        rows.append(
            {
                "name": getattr(tool, "name", ""),
                "description_chars": len(getattr(tool, "description", "") or ""),
            }
        )
    return rows


def _request_trace(
    *,
    role: str,
    profile: str,
    member: EnsembleMemberConfig,
    messages: Sequence[Message],
    tools: Sequence[ToolDefinition] | None,
    config: ChatConfig | None,
    label: str = "",
    sample_index: int = 0,
    layer_index: int | None = None,
) -> dict[str, Any]:
    cfg = member.provider_config
    row: dict[str, Any] = {
        "role": role,
        "profile": profile,
        "label": label or member.label or role,
        "provider": cfg.provider,
        "model": cfg.model,
        "sample_index": sample_index,
        "params": {
            "member_temperature": member.temperature,
            "member_max_tokens": member.max_tokens,
            "member_thinking": member.thinking,
            "member_k": member.k,
            "effective_config": _config_trace(config),
        },
        "tool_count": len(tools or []),
        "tools": _tool_trace_rows(tools),
        "messages": _message_trace_rows(messages),
    }
    if layer_index is not None:
        row["layer_index"] = layer_index
    return row


def _append_request_trace(trace: dict[str, Any], request: dict[str, Any]) -> None:
    if not request:
        return
    trace.setdefault("requests", []).append(request)


def _fallback_request_trace(
    *,
    profile: str,
    provider: LLMProvider,
    messages: Sequence[Message],
    tools: Sequence[ToolDefinition] | None,
    config: ChatConfig | None,
) -> dict[str, Any]:
    return {
        "role": "fallback_single",
        "profile": profile,
        "label": "fallback",
        "provider": str(getattr(provider, "provider_name", "fallback")),
        "model": str(getattr(provider, "model", "")),
        "sample_index": 0,
        "params": {"effective_config": _config_trace(config)},
        "tool_count": len(tools or []),
        "tools": _tool_trace_rows(tools),
        "messages": _message_trace_rows(messages),
    }


def _fill_last_request_model(trace: dict[str, Any], *, role: str, model: str) -> None:
    if not model:
        return
    for request in reversed(trace.get("requests", [])):
        if isinstance(request, dict) and request.get("role") == role and not request.get("model"):
            request["model"] = model
            return


def _rollup_cost_source(rows: Sequence[dict[str, Any]]) -> str:
    sources = {str(row.get("cost_source") or "none") for row in rows}
    billed = sum(1 for row in rows if float(row.get("billed_cost") or 0.0) > 0)
    if billed and billed == len(rows):
        return "provider_billed"
    if billed:
        return "mixed"
    if sources - {"none", "unavailable"}:
        return sorted(sources - {"none", "unavailable"})[0]
    return "none"


def _summed_int(rows: Sequence[dict[str, Any]], key: str) -> int:
    return sum(int(row.get(key) or 0) for row in rows)


def _summed_float(rows: Sequence[dict[str, Any]], key: str) -> float:
    return sum(float(row.get(key) or 0.0) for row in rows)


def _candidate_has_usage(candidate: _CandidateResult) -> bool:
    return bool(
        candidate.ok
        or candidate.error_code == "early_stopped"
        or candidate.input_tokens
        or candidate.output_tokens
        or candidate.reasoning_tokens
        or candidate.cached_tokens
        or candidate.cache_write_tokens
        or candidate.billed_cost
    )


def _candidate_usage_rows(
    candidates: Sequence[_CandidateResult],
    *,
    profile: str,
) -> list[dict[str, Any]]:
    return [
        candidate.usage_row(role="proposer", profile=profile)
        for candidate in candidates
        if _candidate_has_usage(candidate)
    ]


def _extract_json_payload(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    starts = [index for index in (stripped.find("{"), stripped.find("[")) if index >= 0]
    for start in sorted(starts):
        try:
            payload, _end = decoder.raw_decode(stripped[start:])
            return payload
        except json.JSONDecodeError:
            continue
    return None


def _candidate_index(value: Any, allowed: set[int]) -> int | None:
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if index in allowed else None


def _ranked_candidate_indexes(
    text: str,
    candidates: Sequence[_CandidateResult],
    *,
    include_single: bool = False,
) -> list[int]:
    allowed = {candidate.index for candidate in candidates}
    payload = _extract_json_payload(text)
    ranked: list[int] = []

    def append(value: Any) -> None:
        index = _candidate_index(value, allowed)
        if index is not None and index not in ranked:
            ranked.append(index)

    if isinstance(payload, dict):
        if include_single:
            for key in (
                "selected_candidate_index",
                "candidate_index",
                "best_candidate_index",
                "index",
                "choice",
            ):
                if key in payload:
                    append(payload.get(key))
        for key in (
            "ranked_candidate_indexes",
            "selected_candidate_indexes",
            "candidate_indexes",
            "ranking",
        ):
            values = payload.get(key)
            if isinstance(values, list):
                for value in values:
                    append(value.get("index") if isinstance(value, dict) else value)
        scores = payload.get("scores")
        if isinstance(scores, list):
            scored: list[tuple[float, int]] = []
            for item in scores:
                if not isinstance(item, dict):
                    continue
                index = _candidate_index(item.get("index"), allowed)
                if index is None:
                    continue
                try:
                    score = float(item.get("score"))
                except (TypeError, ValueError):
                    score = 0.0
                scored.append((score, index))
            for _score, index in sorted(scored, reverse=True):
                append(index)
    elif isinstance(payload, list):
        for value in payload:
            append(value.get("index") if isinstance(value, dict) else value)
    return ranked


def _done_usage_row(
    event: DoneEvent,
    *,
    role: str,
    profile: str,
    label: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    row = {
        "role": role,
        "profile": profile,
        "label": label,
        "provider": provider,
        "model": event.model or model,
        "sample_index": 0,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "reasoning_tokens": event.reasoning_tokens,
        "cached_tokens": event.cached_tokens,
        "cache_write_tokens": event.cache_write_tokens,
        "billed_cost": event.billed_cost,
        "cost_source": event.cost_source,
    }
    if event.provider_usage:
        row["provider_usage"] = event.provider_usage
    return row


class EnsembleProvider:
    """B5 fusion provider: proposer candidates first, one aggregator stream after."""

    provider_name = "ensemble"

    def __init__(
        self,
        *,
        profile_name: str,
        proposers: Sequence[EnsembleMemberConfig],
        aggregator: EnsembleMemberConfig,
        fallback_provider: LLMProvider | None = None,
        min_successful_proposers: int = 1,
        all_failed_policy: Literal["fallback_single", "error"] = "fallback_single",
        proposer_timeout_seconds: float = 120.0,
        aggregator_timeout_seconds: float = 120.0,
        candidate_max_chars: int = 24_000,
        shuffle_candidates: bool = True,
        record_candidates: bool = False,
        proposer_tools: bool = False,
        candidate_scorer: EnsembleMemberConfig | None = None,
        candidate_prefilter_top_k: int = 0,
        proposer_early_stop_success_count: int = 0,
        proposer_early_stop_after_seconds: float = 0.0,
        output_strategy: Literal["fusion", "select_best_candidate"] = "fusion",
        moa_layers: int = 1,
    ) -> None:
        self.profile_name = profile_name
        self.proposers = list(proposers)
        self.aggregator = aggregator
        self.fallback_provider = fallback_provider
        self.min_successful_proposers = max(1, int(min_successful_proposers or 1))
        self.all_failed_policy = all_failed_policy
        self.proposer_timeout_seconds = float(proposer_timeout_seconds or 120.0)
        self.aggregator_timeout_seconds = float(aggregator_timeout_seconds or 120.0)
        self.candidate_max_chars = int(candidate_max_chars or 0)
        self.shuffle_candidates = bool(shuffle_candidates)
        self.record_candidates = bool(record_candidates)
        self.proposer_tools = bool(proposer_tools)
        self.candidate_scorer = candidate_scorer
        self.candidate_prefilter_top_k = max(0, int(candidate_prefilter_top_k or 0))
        self.proposer_early_stop_success_count = max(
            0, int(proposer_early_stop_success_count or 0)
        )
        self.proposer_early_stop_after_seconds = max(
            0.0, float(proposer_early_stop_after_seconds or 0.0)
        )
        strategy = str(output_strategy or "fusion").strip()
        self.output_strategy = (
            strategy if strategy in {"fusion", "select_best_candidate"} else "fusion"
        )
        self.moa_layers = max(1, int(moa_layers or 1))

    def provider_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_name="ensemble",
            provider_kind="ensemble",
            model=f"ensemble/{self.profile_name}",
            base_url="",
        )

    async def list_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        members = [*self.proposers, self.aggregator]
        if self.candidate_scorer is not None:
            members.append(self.candidate_scorer)
        for member in members:
            try:
                models.extend(await _build_provider(member.provider_config).list_models())
            except Exception:
                continue
        return models

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        return self._chat(messages, tools=tools, config=config)

    async def _chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if not self.proposers:
            async for event in self._fallback_or_error(
                messages,
                tools=tools,
                config=config,
                reason="llm ensemble profile has no proposers",
                code="ensemble_no_proposers",
                candidates=[],
            ):
                yield event
            return

        yield ProviderHeartbeatEvent(
            phase="ensemble_proposers",
            message=f"Running {len(self.proposers)} proposer model(s)",
        )
        candidates = await self._run_proposers(messages, tools=tools, config=config)
        successful = [candidate for candidate in candidates if candidate.ok]
        if len(successful) < self.min_successful_proposers:
            async for event in self._fallback_or_error(
                messages,
                tools=tools,
                config=config,
                reason=(
                    "llm ensemble had "
                    f"{len(successful)} successful proposer(s), "
                    f"requires {self.min_successful_proposers}"
                ),
                code="ensemble_insufficient_proposers",
                candidates=candidates,
            ):
                yield event
            return

        prefilter = await self._prefilter_candidates(successful, messages, config=config)
        aggregator_cfg = _member_chat_config(config, self.aggregator)
        if self.aggregator_timeout_seconds > 0:
            aggregator_cfg = aggregator_cfg.model_copy(
                update={"timeout": self.aggregator_timeout_seconds}
            )
        provider = _build_provider(self.aggregator.provider_config)
        proposer_rows = _candidate_usage_rows(candidates, profile=self.profile_name)
        prefilter_rows = prefilter.usage_rows
        if self.output_strategy == "select_best_candidate":
            yield ProviderHeartbeatEvent(
                phase="ensemble_selector",
                message="Selecting the best candidate draft",
            )
            selection = await self._select_candidate(
                prefilter.candidates,
                messages,
                provider=provider,
                config=aggregator_cfg,
            )
            selected_has_tools = bool(selection.selected.tool_calls)
            final_request_role = (
                "candidate_tool_reissuer" if selected_has_tools else "candidate_selector"
            )
            trace = self._trace_payload(
                candidates,
                successful_count=len(successful),
                fallback_used=False,
                fallback_reason="",
                final_request_role=final_request_role,
                selected_candidates=[selection.selected],
                prefilter_trace=prefilter.trace or None,
                prefilter_request_count=prefilter.request_count,
                final_request_count=(
                    selection.request_count + 1 if selected_has_tools else selection.request_count
                ),
                output_strategy=self.output_strategy,
                selection_trace=selection.trace,
            )
            if selected_has_tools:
                trace["candidate_tool_reissue"] = {
                    "required": True,
                    "source_candidate_index": selection.selected.index,
                    "proposed_call_count": len(selection.selected.tool_calls),
                    "prompt_truncated": selection.selected.tool_calls_truncated,
                }
                yield ProviderHeartbeatEvent(
                    phase="ensemble_aggregator",
                    message="Authorizing the selected candidate's proposed tool call(s)",
                )
                aggregator_messages = self._build_aggregator_messages(
                    messages,
                    [selection.selected],
                )
                async for event in self._stream_final_aggregator(
                    provider=provider,
                    messages=aggregator_messages,
                    tools=tools,
                    config=aggregator_cfg,
                    prior_rows=[
                        *proposer_rows,
                        *prefilter_rows,
                        *selection.usage_rows,
                    ],
                    trace=trace,
                    label="candidate_tool_reissuer",
                ):
                    yield event
                return
            async for event in self._stream_selected_candidate(
                selection,
                prior_rows=[*proposer_rows, *prefilter_rows],
                trace=trace,
            ):
                yield event
            return
        aggregator_messages = self._build_aggregator_messages(messages, prefilter.candidates)
        trace = self._trace_payload(
            candidates,
            successful_count=len(successful),
            fallback_used=False,
            fallback_reason="",
            final_request_role="aggregator",
            selected_candidates=prefilter.candidates,
            prefilter_trace=prefilter.trace or None,
            prefilter_request_count=prefilter.request_count,
            final_request_count=self.moa_layers,
            moa_layers=self.moa_layers,
        )
        async for event in self._stream_aggregator_layers(
            provider=provider,
            base_messages=messages,
            first_layer_messages=aggregator_messages,
            tools=tools,
            config=aggregator_cfg,
            proposer_rows=proposer_rows,
            prefilter_rows=prefilter_rows,
            trace=trace,
        ):
            yield event

    async def _select_candidate(
        self,
        candidates: Sequence[_CandidateResult],
        messages: list[Message],
        *,
        provider: LLMProvider,
        config: ChatConfig,
    ) -> _SelectionResult:
        ordered = sorted(candidates, key=lambda candidate: candidate.index)
        fallback = ordered[0]
        text_parts: list[str] = []
        usage_rows: list[dict[str, Any]] = []
        error = ""
        error_code = ""
        got_done = False
        selector_messages = self._build_selector_messages(messages, candidates)
        selector_config = config.model_copy(update={"tool_choice": None})
        request_trace = _request_trace(
            role="candidate_selector",
            profile=self.profile_name,
            member=self.aggregator,
            messages=selector_messages,
            tools=None,
            config=selector_config,
            label="candidate_selector",
        )
        try:
            stream = provider.chat(selector_messages, tools=None, config=selector_config)
            if self.aggregator_timeout_seconds > 0:
                async with asyncio.timeout(self.aggregator_timeout_seconds):
                    async for event in stream:
                        got_done = self._collect_selector_event(
                            event,
                            text_parts,
                            usage_rows,
                            got_done=got_done,
                        )
                        if isinstance(event, ErrorEvent):
                            error = event.message
                            error_code = event.code or "candidate_selector_error"
                            break
            else:
                async for event in stream:
                    got_done = self._collect_selector_event(
                        event,
                        text_parts,
                        usage_rows,
                        got_done=got_done,
                    )
                    if isinstance(event, ErrorEvent):
                        error = event.message
                        error_code = event.code or "candidate_selector_error"
                        break
        except TimeoutError:
            error = f"candidate selector timed out after {self.aggregator_timeout_seconds:g}s"
            error_code = "candidate_selector_timeout"
        except Exception as exc:  # noqa: BLE001 - selector failure falls back deterministically
            error = str(exc)
            error_code = type(exc).__name__

        ranked = _ranked_candidate_indexes(
            "".join(text_parts),
            candidates,
            include_single=True,
        )
        by_index = {candidate.index: candidate for candidate in candidates}
        applied = bool(ranked) and got_done and not error and ranked[0] in by_index
        selected = by_index[ranked[0]] if applied else fallback
        trace: dict[str, Any] = {
            "enabled": True,
            "applied": applied,
            "selector_model": self.aggregator.provider_config.model,
            "ranked_candidate_indexes": ranked,
            "selected_candidate_index": selected.index,
            "request": request_trace,
        }
        if not applied:
            if error:
                trace["fallback_reason"] = error
            elif not got_done:
                trace["fallback_reason"] = "candidate selector stream ended before DoneEvent"
            else:
                trace["fallback_reason"] = "candidate selector did not return a parseable index"
        if error:
            trace["error"] = error
            trace["error_code"] = error_code
        return _SelectionResult(
            selected=selected,
            usage_rows=usage_rows,
            trace=trace,
            request_count=1,
        )

    def _collect_selector_event(
        self,
        event: StreamEvent,
        text_parts: list[str],
        usage_rows: list[dict[str, Any]],
        *,
        got_done: bool,
    ) -> bool:
        if isinstance(event, TextDeltaEvent):
            text_parts.append(event.text)
        elif isinstance(event, DoneEvent):
            got_done = True
            usage_rows.append(
                _done_usage_row(
                    event,
                    role="candidate_selector",
                    profile=self.profile_name,
                    label="candidate_selector",
                    provider=self.aggregator.provider_config.provider,
                    model=self.aggregator.provider_config.model,
                )
            )
        elif isinstance(event, ErrorEvent) and event.diagnostic_done is not None:
            usage_rows.append(
                _done_usage_row(
                    event.diagnostic_done,
                    role="candidate_selector",
                    profile=self.profile_name,
                    label="candidate_selector",
                    provider=self.aggregator.provider_config.provider,
                    model=self.aggregator.provider_config.model,
                )
            )
        return got_done

    async def _stream_selected_candidate(
        self,
        selection: _SelectionResult,
        *,
        prior_rows: list[dict[str, Any]],
        trace: dict[str, Any],
    ) -> AsyncIterator[StreamEvent]:
        selected = selection.selected
        if selected.tool_calls:
            yield ErrorEvent(
                message=(
                    "selected proposer tool calls require a fresh aggregator authorization request"
                ),
                code="ensemble_candidate_tool_reissue_required",
            )
            return
        text = selected.text
        if text:
            yield TextDeltaEvent(text=text)
        rows = [*prior_rows, *selection.usage_rows]
        yield DoneEvent(
            stop_reason="selected_candidate",
            input_tokens=_summed_int(rows, "input_tokens"),
            output_tokens=_summed_int(rows, "output_tokens"),
            reasoning_tokens=_summed_int(rows, "reasoning_tokens"),
            cached_tokens=_summed_int(rows, "cached_tokens"),
            cache_write_tokens=_summed_int(rows, "cache_write_tokens"),
            billed_cost=_summed_float(rows, "billed_cost"),
            model=selected.model,
            cost_source=_rollup_cost_source(rows),
            model_usage_breakdown=rows,
            ensemble_trace=trace,
        )

    async def _stream_aggregator_layers(
        self,
        *,
        provider: LLMProvider,
        base_messages: list[Message],
        first_layer_messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: ChatConfig,
        proposer_rows: list[dict[str, Any]],
        prefilter_rows: list[dict[str, Any]],
        trace: dict[str, Any],
    ) -> AsyncIterator[StreamEvent]:
        rows_before_aggregator = [*proposer_rows, *prefilter_rows]
        if self.moa_layers <= 1:
            async for event in self._stream_final_aggregator(
                provider=provider,
                messages=first_layer_messages,
                tools=tools,
                config=config,
                prior_rows=rows_before_aggregator,
                trace=trace,
                label="aggregator",
            ):
                yield event
            return

        previous_text = ""
        layer_rows: list[dict[str, Any]] = []
        for layer_index in range(1, self.moa_layers):
            yield ProviderHeartbeatEvent(
                phase="ensemble_moa",
                message=f"Running MoA layer {layer_index}/{self.moa_layers}",
            )
            layer_messages = (
                first_layer_messages
                if layer_index == 1
                else self._build_moa_refine_messages(
                    base_messages,
                    previous_text,
                    layer_index=layer_index,
                )
            )
            _append_request_trace(
                trace,
                _request_trace(
                    role=f"aggregator_layer_{layer_index}",
                    profile=self.profile_name,
                    member=self.aggregator,
                    messages=layer_messages,
                    tools=None,
                    config=config,
                    label=f"aggregator_layer_{layer_index}",
                    layer_index=layer_index,
                ),
            )
            text, usage_row, error_message, error_code = await self._collect_moa_text_layer(
                provider=provider,
                messages=layer_messages,
                config=config,
                layer_index=layer_index,
            )
            if usage_row is not None:
                layer_rows.append(usage_row)
            if error_message:
                diagnostic_rows = [*rows_before_aggregator, *layer_rows]
                yield ErrorEvent(
                    message=error_message,
                    code=error_code,
                    diagnostic_done=self._aggregator_diagnostic_done(
                        message=error_message,
                        code=error_code,
                        rows=diagnostic_rows,
                        trace=trace,
                    ),
                )
                return
            previous_text = text

        final_messages = self._build_moa_refine_messages(
            base_messages,
            previous_text,
            layer_index=self.moa_layers,
        )
        async for event in self._stream_final_aggregator(
            provider=provider,
            messages=final_messages,
            tools=tools,
            config=config,
            prior_rows=[*rows_before_aggregator, *layer_rows],
            trace=trace,
            label=f"aggregator_layer_{self.moa_layers}",
        ):
            yield event

    async def _stream_final_aggregator(
        self,
        *,
        provider: LLMProvider,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: ChatConfig,
        prior_rows: list[dict[str, Any]],
        trace: dict[str, Any],
        label: str,
    ) -> AsyncIterator[StreamEvent]:
        def _ensemble_done(event: DoneEvent) -> DoneEvent:
            acc = _AggregatorAccumulator(
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                reasoning_tokens=event.reasoning_tokens,
                cached_tokens=event.cached_tokens,
                cache_write_tokens=event.cache_write_tokens,
                billed_cost=event.billed_cost,
                cost_source=event.cost_source,
                provider_usage=event.provider_usage,
                model=event.model or self.aggregator.provider_config.model,
            )
            rows = [
                *prior_rows,
                acc.usage_row(
                    profile=self.profile_name,
                    member=self.aggregator,
                    role="aggregator",
                    label=label,
                ),
            ]
            return replace(
                event,
                input_tokens=_summed_int(rows, "input_tokens"),
                output_tokens=_summed_int(rows, "output_tokens"),
                reasoning_tokens=_summed_int(rows, "reasoning_tokens"),
                cached_tokens=_summed_int(rows, "cached_tokens"),
                cache_write_tokens=_summed_int(rows, "cache_write_tokens"),
                billed_cost=_summed_float(rows, "billed_cost"),
                model=acc.model,
                cost_source=_rollup_cost_source(rows),
                model_usage_breakdown=rows,
                ensemble_trace=trace,
            )

        yielded_done = False
        try:
            _append_request_trace(
                trace,
                _request_trace(
                    role=label,
                    profile=self.profile_name,
                    member=self.aggregator,
                    messages=messages,
                    tools=tools,
                    config=config,
                    label=label,
                ),
            )
            stream = provider.chat(messages, tools=tools, config=config)
            if self.aggregator_timeout_seconds > 0:
                async with asyncio.timeout(self.aggregator_timeout_seconds):
                    async for event in stream:
                        if isinstance(event, DoneEvent):
                            yielded_done = True
                            yield _ensemble_done(event)
                        else:
                            yield event
            else:
                async for event in stream:
                    if isinstance(event, DoneEvent):
                        yielded_done = True
                        yield _ensemble_done(event)
                    else:
                        yield event
        except TimeoutError:
            message = (
                "ensemble aggregator timed out after "
                f"{self.aggregator_timeout_seconds:g}s"
            )
            yield ErrorEvent(
                message=message,
                code="ensemble_aggregator_timeout",
                diagnostic_done=self._aggregator_diagnostic_done(
                    message=message,
                    code="ensemble_aggregator_timeout",
                    rows=prior_rows,
                    trace=trace,
                ),
            )
            return
        except Exception as exc:  # noqa: BLE001 - provider boundary returns ErrorEvent
            message = f"ensemble aggregator failed: {exc}"
            yield ErrorEvent(
                message=message,
                code="ensemble_aggregator_error",
                diagnostic_done=self._aggregator_diagnostic_done(
                    message=message,
                    code="ensemble_aggregator_error",
                    rows=prior_rows,
                    trace=trace,
                ),
            )
            return
        if not yielded_done:
            message = "ensemble aggregator stream ended before DoneEvent"
            yield ErrorEvent(
                message=message,
                code="ensemble_aggregator_incomplete",
                diagnostic_done=self._aggregator_diagnostic_done(
                    message=message,
                    code="ensemble_aggregator_incomplete",
                    rows=prior_rows,
                    trace=trace,
                ),
            )

    async def _collect_moa_text_layer(
        self,
        *,
        provider: LLMProvider,
        messages: list[Message],
        config: ChatConfig,
        layer_index: int,
    ) -> tuple[str, dict[str, Any] | None, str, str]:
        text_parts: list[str] = []
        usage_row: dict[str, Any] | None = None
        got_done = False
        try:
            stream = provider.chat(messages, tools=None, config=config)
            if self.aggregator_timeout_seconds > 0:
                async with asyncio.timeout(self.aggregator_timeout_seconds):
                    async for event in stream:
                        if isinstance(event, ErrorEvent):
                            usage_row = self._moa_layer_error_usage_row(
                                event,
                                layer_index=layer_index,
                            )
                            return "", usage_row, event.message, (
                                event.code or "ensemble_moa_layer_error"
                            )
                        usage_row, got_done = self._collect_moa_layer_event(
                            event,
                            text_parts,
                            layer_index=layer_index,
                            usage_row=usage_row,
                            got_done=got_done,
                        )
            else:
                async for event in stream:
                    if isinstance(event, ErrorEvent):
                        usage_row = self._moa_layer_error_usage_row(
                            event,
                            layer_index=layer_index,
                        )
                        return "", usage_row, event.message, (
                            event.code or "ensemble_moa_layer_error"
                        )
                    usage_row, got_done = self._collect_moa_layer_event(
                        event,
                        text_parts,
                        layer_index=layer_index,
                        usage_row=usage_row,
                        got_done=got_done,
                    )
        except TimeoutError:
            message = (
                "ensemble MoA layer "
                f"{layer_index} timed out after {self.aggregator_timeout_seconds:g}s"
            )
            return "", usage_row, message, "ensemble_moa_layer_timeout"
        except Exception as exc:  # noqa: BLE001 - provider boundary returns ErrorEvent
            return "", usage_row, f"ensemble MoA layer {layer_index} failed: {exc}", (
                "ensemble_moa_layer_error"
            )
        text = "".join(text_parts).strip()
        if not got_done:
            return text, usage_row, (
                f"ensemble MoA layer {layer_index} stream ended before DoneEvent"
            ), "ensemble_moa_layer_incomplete"
        if not text:
            return text, usage_row, (
                f"ensemble MoA layer {layer_index} produced no text"
            ), "ensemble_moa_layer_empty"
        return text, usage_row, "", ""

    def _collect_moa_layer_event(
        self,
        event: StreamEvent,
        text_parts: list[str],
        *,
        layer_index: int,
        usage_row: dict[str, Any] | None,
        got_done: bool,
    ) -> tuple[dict[str, Any] | None, bool]:
        if isinstance(event, TextDeltaEvent):
            text_parts.append(event.text)
        elif isinstance(event, ToolUseStartEvent):
            text_parts.append(f"\n[tool_use:{event.tool_name}]")
        elif isinstance(event, ToolUseDeltaEvent):
            if event.json_fragment:
                text_parts.append(event.json_fragment)
        elif isinstance(event, ToolUseEndEvent):
            if event.arguments:
                text_parts.append(f"\n[tool_args:{event.arguments}]")
        elif isinstance(event, DoneEvent):
            got_done = True
            usage_row = _done_usage_row(
                event,
                role=f"aggregator_layer_{layer_index}",
                profile=self.profile_name,
                label=f"aggregator_layer_{layer_index}",
                provider=self.aggregator.provider_config.provider,
                model=self.aggregator.provider_config.model,
            )
        return usage_row, got_done

    def _moa_layer_error_usage_row(
        self,
        event: ErrorEvent,
        *,
        layer_index: int,
    ) -> dict[str, Any] | None:
        if event.diagnostic_done is None:
            return None
        return _done_usage_row(
            event.diagnostic_done,
            role=f"aggregator_layer_{layer_index}",
            profile=self.profile_name,
            label=f"aggregator_layer_{layer_index}",
            provider=self.aggregator.provider_config.provider,
            model=self.aggregator.provider_config.model,
        )

    def _aggregator_diagnostic_done(
        self,
        *,
        message: str,
        code: str,
        rows: list[dict[str, Any]],
        trace: dict[str, Any],
    ) -> DoneEvent:
        failure_trace = {
            **trace,
            "aggregator_error": {
                "code": code,
                "message": message,
            },
        }
        return DoneEvent(
            stop_reason=code,
            input_tokens=_summed_int(rows, "input_tokens"),
            output_tokens=_summed_int(rows, "output_tokens"),
            reasoning_tokens=_summed_int(rows, "reasoning_tokens"),
            cached_tokens=_summed_int(rows, "cached_tokens"),
            cache_write_tokens=_summed_int(rows, "cache_write_tokens"),
            billed_cost=_summed_float(rows, "billed_cost"),
            model=self.aggregator.provider_config.model,
            cost_source=_rollup_cost_source(rows),
            model_usage_breakdown=rows,
            ensemble_trace=failure_trace,
        )

    async def _run_proposers(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None,
        config: ChatConfig | None,
    ) -> list[_CandidateResult]:
        tasks: list[asyncio.Task[_CandidateResult]] = []
        task_meta: dict[asyncio.Task[_CandidateResult], _CandidateTaskMeta] = {}
        index = 0
        for member in self.proposers:
            k = max(1, int(member.k or 1))
            for sample_index in range(k):
                started = time.monotonic()
                task = asyncio.create_task(
                    self._collect_candidate(
                        index=index,
                        sample_index=sample_index,
                        member=member,
                        messages=messages,
                        tools=tools if self.proposer_tools else None,
                        config=config,
                    )
                )
                task_meta[task] = _CandidateTaskMeta(
                    index=index,
                    sample_index=sample_index,
                    member=member,
                    started=started,
                    messages=messages,
                    tools=tools if self.proposer_tools else None,
                    config=config,
                )
                tasks.append(task)
                index += 1
        if not tasks:
            return []
        early_stop_target = self._proposer_early_stop_target(len(tasks))
        if early_stop_target <= 0:
            return [result for result in await asyncio.gather(*tasks)]

        pending = set(tasks)
        results: list[_CandidateResult] = []
        successful_count = 0
        started_all = time.monotonic()
        while pending:
            timeout: float | None = None
            if successful_count >= early_stop_target:
                remaining = self.proposer_early_stop_after_seconds - (
                    time.monotonic() - started_all
                )
                if remaining <= 0:
                    break
                timeout = remaining
            done, pending = await asyncio.wait(
                pending,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                break
            for task in done:
                result = self._candidate_result_from_task(task, task_meta[task])
                results.append(result)
                if result.ok:
                    successful_count += 1
            if (
                successful_count >= early_stop_target
                and time.monotonic() - started_all
                >= self.proposer_early_stop_after_seconds
            ):
                break

        if pending and successful_count >= early_stop_target:
            stopped_at = time.monotonic()
            for task in pending:
                task.cancel()
                results.append(
                    self._early_stopped_candidate_result(
                        task_meta[task],
                        stopped_at=stopped_at,
                        successful_count=successful_count,
                    )
                )
            await asyncio.gather(*pending, return_exceptions=True)
        elif pending:
            results.extend(await asyncio.gather(*pending))
        return sorted(results, key=lambda candidate: candidate.index)

    def _proposer_early_stop_target(self, total_candidates: int) -> int:
        if self.proposer_early_stop_success_count <= 0 or total_candidates <= 1:
            return 0
        target = max(
            self.proposer_early_stop_success_count,
            self.min_successful_proposers,
        )
        if self.candidate_prefilter_top_k > 0:
            target = max(target, min(self.candidate_prefilter_top_k, total_candidates))
        return target if target < total_candidates else 0

    def _candidate_result_from_task(
        self,
        task: asyncio.Task[_CandidateResult],
        meta: _CandidateTaskMeta,
    ) -> _CandidateResult:
        try:
            return task.result()
        except Exception as exc:  # noqa: BLE001 - defensive task wrapper
            cfg = meta.member.provider_config
            return _CandidateResult(
                index=meta.index,
                sample_index=meta.sample_index,
                label=meta.member.label or f"proposer_{meta.index + 1}",
                provider=cfg.provider,
                model=cfg.model,
                error=str(exc),
                error_code=type(exc).__name__,
                elapsed_ms=int((time.monotonic() - meta.started) * 1000),
            )

    def _early_stopped_candidate_result(
        self,
        meta: _CandidateTaskMeta,
        *,
        stopped_at: float,
        successful_count: int,
    ) -> _CandidateResult:
        cfg = meta.member.provider_config
        elapsed_s = max(0.0, stopped_at - meta.started)
        result = _CandidateResult(
            index=meta.index,
            sample_index=meta.sample_index,
            label=meta.member.label or f"proposer_{meta.index + 1}",
            provider=cfg.provider,
            model=cfg.model,
            cost_source="unknown_canceled",
            error=(
                f"proposer early-stopped after {elapsed_s:.3g}s "
                f"with {successful_count} successful candidate(s)"
            ),
            error_code="early_stopped",
            elapsed_ms=int(elapsed_s * 1000),
        )
        chat_cfg = _member_chat_config(meta.config, meta.member)
        if self.proposer_timeout_seconds > 0:
            chat_cfg = chat_cfg.model_copy(update={"timeout": self.proposer_timeout_seconds})
        result.request = _request_trace(
            role="proposer",
            profile=self.profile_name,
            member=meta.member,
            messages=meta.messages,
            tools=meta.tools,
            config=chat_cfg,
            label=result.label,
            sample_index=result.sample_index,
        )
        result.request["cancelled_before_done"] = True
        return result

    async def _collect_candidate(
        self,
        *,
        index: int,
        sample_index: int,
        member: EnsembleMemberConfig,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: ChatConfig | None,
    ) -> _CandidateResult:
        cfg = member.provider_config
        started = time.monotonic()
        result = _CandidateResult(
            index=index,
            sample_index=sample_index,
            label=member.label or f"proposer_{index + 1}",
            provider=cfg.provider,
            model=cfg.model,
        )
        try:
            return await asyncio.wait_for(
                self._collect_candidate_inner(
                    result=result,
                    member=member,
                    messages=messages,
                    tools=tools,
                    config=config,
                    started=started,
                ),
                timeout=(
                    self.proposer_timeout_seconds
                    if self.proposer_timeout_seconds > 0
                    else None
                ),
            )
        except TimeoutError:
            result.error = f"proposer timed out after {self.proposer_timeout_seconds:g}s"
            result.error_code = "timeout"
        except Exception as exc:  # noqa: BLE001 - candidate failures are diagnostic data
            result.error = str(exc)
            result.error_code = type(exc).__name__
        finally:
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    async def _prefilter_candidates(
        self,
        candidates: Sequence[_CandidateResult],
        messages: list[Message],
        *,
        config: ChatConfig | None,
    ) -> _PrefilterResult:
        top_k = self.candidate_prefilter_top_k
        if top_k <= 0:
            return _PrefilterResult(candidates=list(candidates))
        if len(candidates) <= top_k or self.candidate_scorer is None:
            return _PrefilterResult(
                candidates=list(candidates),
                trace={
                    "enabled": True,
                    "applied": False,
                    "top_k": top_k,
                    "selected_candidate_indexes": [candidate.index for candidate in candidates],
                },
            )

        provider = _build_provider(self.candidate_scorer.provider_config)
        scorer_cfg = _member_chat_config(config, self.candidate_scorer)
        if self.aggregator_timeout_seconds > 0:
            scorer_cfg = scorer_cfg.model_copy(update={"timeout": self.aggregator_timeout_seconds})

        text_parts: list[str] = []
        usage_rows: list[dict[str, Any]] = []
        error = ""
        error_code = ""
        prefilter_messages = self._build_prefilter_messages(messages, candidates, top_k=top_k)
        request_trace = _request_trace(
            role="candidate_scorer",
            profile=self.profile_name,
            member=self.candidate_scorer,
            messages=prefilter_messages,
            tools=None,
            config=scorer_cfg,
            label=self.candidate_scorer.label or "candidate_scorer",
        )
        try:
            stream = provider.chat(prefilter_messages, tools=None, config=scorer_cfg)
            if self.aggregator_timeout_seconds > 0:
                async with asyncio.timeout(self.aggregator_timeout_seconds):
                    async for event in stream:
                        self._collect_prefilter_event(event, text_parts, usage_rows)
            else:
                async for event in stream:
                    self._collect_prefilter_event(event, text_parts, usage_rows)
        except TimeoutError:
            error = f"candidate scorer timed out after {self.aggregator_timeout_seconds:g}s"
            error_code = "candidate_scorer_timeout"
        except Exception as exc:  # noqa: BLE001 - scorer failure falls back to no filtering
            error = str(exc)
            error_code = type(exc).__name__

        ranked = _ranked_candidate_indexes("".join(text_parts), candidates)
        by_index = {candidate.index: candidate for candidate in candidates}
        selected = [by_index[index] for index in ranked[:top_k] if index in by_index]
        applied = len(selected) == min(top_k, len(candidates))
        if not applied:
            selected = list(candidates)
        trace: dict[str, Any] = {
            "enabled": True,
            "applied": applied,
            "top_k": top_k,
            "scorer_model": self.candidate_scorer.provider_config.model,
            "ranked_candidate_indexes": ranked,
            "selected_candidate_indexes": [candidate.index for candidate in selected],
            "request": request_trace,
        }
        if not applied:
            trace["fallback_reason"] = (
                error or "candidate scorer did not return enough parseable indexes"
            )
        if error:
            trace["error"] = error
            trace["error_code"] = error_code
        return _PrefilterResult(
            candidates=selected,
            usage_rows=usage_rows,
            trace=trace,
            request_count=1,
        )

    def _collect_prefilter_event(
        self,
        event: StreamEvent,
        text_parts: list[str],
        usage_rows: list[dict[str, Any]],
    ) -> None:
        if isinstance(event, TextDeltaEvent):
            text_parts.append(event.text)
        elif isinstance(event, DoneEvent):
            if self.candidate_scorer is None:
                return
            usage_rows.append(
                _done_usage_row(
                    event,
                    role="candidate_scorer",
                    profile=self.profile_name,
                    label=self.candidate_scorer.label or "candidate_scorer",
                    provider=self.candidate_scorer.provider_config.provider,
                    model=self.candidate_scorer.provider_config.model,
                )
            )
        elif isinstance(event, ErrorEvent):
            if self.candidate_scorer is not None and event.diagnostic_done is not None:
                usage_rows.append(
                    _done_usage_row(
                        event.diagnostic_done,
                        role="candidate_scorer",
                        profile=self.profile_name,
                        label=self.candidate_scorer.label or "candidate_scorer",
                        provider=self.candidate_scorer.provider_config.provider,
                        model=self.candidate_scorer.provider_config.model,
                    )
                )
            text_parts.append(
                json.dumps(
                    {
                        "error": event.message,
                        "error_code": event.code,
                    }
                )
            )

    async def _collect_candidate_inner(
        self,
        *,
        result: _CandidateResult,
        member: EnsembleMemberConfig,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: ChatConfig | None,
        started: float,
    ) -> _CandidateResult:
        provider = _build_provider(member.provider_config)
        chat_cfg = _member_chat_config(config, member)
        if self.proposer_timeout_seconds > 0:
            chat_cfg = chat_cfg.model_copy(update={"timeout": self.proposer_timeout_seconds})
        result.request = _request_trace(
            role="proposer",
            profile=self.profile_name,
            member=member,
            messages=messages,
            tools=tools,
            config=chat_cfg,
            label=result.label,
            sample_index=result.sample_index,
        )
        text_parts: list[str] = []
        tool_parts: list[str] = []
        allowed_tool_names = {str(getattr(tool, "name", "") or "") for tool in (tools or [])}
        allowed_tool_names.discard("")
        pending_tool_calls: dict[str, _PendingProposerToolCall] = {}
        completed_tool_calls: dict[str, dict[str, Any]] = {}
        completed_tool_call_ids: set[str] = set()
        tool_call_order: list[str] = []
        pending_reported = False
        got_done = False

        def record_tool_error(code: str, tool_use_id: str = "") -> None:
            result.tool_call_error_total += 1
            if len(result.tool_call_errors) >= PROPOSER_TOOL_ERROR_MAX_ITEMS:
                return
            if tool_use_id:
                tool_id_digest = hashlib.sha256(
                    tool_use_id.encode("utf-8", errors="replace")
                ).hexdigest()[:16]
                diagnostic = f"{code}:id_sha256={tool_id_digest}"
            else:
                diagnostic = code
            if diagnostic not in result.tool_call_errors:
                result.tool_call_errors.append(diagnostic)

        async for event in provider.chat(messages, tools=tools, config=chat_cfg):
            if (
                self.proposer_tools
                and got_done
                and isinstance(
                    event,
                    (
                        TextDeltaEvent,
                        ReasoningDeltaEvent,
                        ToolUseStartEvent,
                        ToolUseDeltaEvent,
                        ToolUseEndEvent,
                        DoneEvent,
                    ),
                )
            ):
                record_tool_error(f"event_after_done:{event.kind}")
                continue
            if isinstance(event, TextDeltaEvent):
                if result.ttft_ms is None and event.text:
                    result.ttft_ms = int((time.monotonic() - started) * 1000)
                text_parts.append(event.text)
            elif isinstance(event, ReasoningDeltaEvent):
                continue
            elif isinstance(event, ToolUseStartEvent):
                if not self.proposer_tools:
                    tool_parts.append(f"\n[tool_use:{event.tool_name}]")
                    continue
                if result.ttft_ms is None:
                    result.ttft_ms = int((time.monotonic() - started) * 1000)
                tool_use_id = str(event.tool_use_id or "")
                if not tool_use_id:
                    record_tool_error("empty_tool_use_id")
                elif tool_use_id in pending_tool_calls or tool_use_id in completed_tool_call_ids:
                    record_tool_error("duplicate_tool_start", tool_use_id)
                else:
                    pending_tool_calls[tool_use_id] = _PendingProposerToolCall(
                        tool_use_id=tool_use_id,
                        tool_name=str(event.tool_name or ""),
                        synthetic_from_text=bool(event.synthetic_from_text),
                    )
                    tool_call_order.append(tool_use_id)
            elif isinstance(event, ToolUseDeltaEvent):
                if not self.proposer_tools:
                    if event.json_fragment:
                        tool_parts.append(event.json_fragment)
                    continue
                tool_use_id = str(event.tool_use_id or "")
                pending = pending_tool_calls.get(tool_use_id)
                if pending is None:
                    record_tool_error("orphan_tool_delta", tool_use_id)
                elif event.json_fragment:
                    pending.json_parts.append(str(event.json_fragment))
            elif isinstance(event, ToolUseEndEvent):
                if not self.proposer_tools:
                    if event.arguments:
                        tool_parts.append(f"\n[tool_args:{event.arguments}]")
                    continue
                if result.ttft_ms is None:
                    result.ttft_ms = int((time.monotonic() - started) * 1000)
                tool_use_id = str(event.tool_use_id or "")
                pending = pending_tool_calls.pop(tool_use_id, None)
                if pending is None:
                    code = (
                        "duplicate_tool_end"
                        if tool_use_id in completed_tool_call_ids
                        else "orphan_tool_end"
                    )
                    record_tool_error(code, tool_use_id)
                    continue

                completed_tool_call_ids.add(tool_use_id)
                call_error_count = result.tool_call_error_total
                end_name = str(event.tool_name or "")
                if pending.tool_name and end_name and pending.tool_name != end_name:
                    record_tool_error("tool_name_mismatch", tool_use_id)
                tool_name = end_name or pending.tool_name
                if not tool_name:
                    record_tool_error("empty_tool_name", tool_use_id)
                elif tool_name not in allowed_tool_names:
                    record_tool_error("unoffered_tool_name", tool_use_id)

                if not isinstance(event.arguments, dict):
                    record_tool_error("non_object_tool_arguments", tool_use_id)
                    arguments: dict[str, Any] = {}
                else:
                    try:
                        serialized_arguments = json.dumps(
                            event.arguments,
                            ensure_ascii=False,
                            allow_nan=False,
                            sort_keys=True,
                        )
                        normalized_arguments = json.loads(serialized_arguments)
                    except (TypeError, ValueError):
                        record_tool_error("non_json_tool_arguments", tool_use_id)
                        arguments = {}
                    else:
                        arguments = normalized_arguments

                if pending.json_parts:
                    try:
                        parsed_arguments = json.loads("".join(pending.json_parts))
                        json.dumps(parsed_arguments, allow_nan=False)
                    except (TypeError, ValueError):
                        record_tool_error("invalid_tool_argument_json", tool_use_id)
                    else:
                        if not isinstance(parsed_arguments, dict):
                            record_tool_error("non_object_tool_argument_json", tool_use_id)
                        elif arguments and parsed_arguments != arguments:
                            record_tool_error("tool_arguments_mismatch", tool_use_id)
                        elif not arguments:
                            arguments = parsed_arguments

                if set(arguments) == {"_raw"} and isinstance(
                    arguments.get("_raw"), str
                ):
                    record_tool_error("unparsed_raw_tool_arguments", tool_use_id)

                if result.tool_call_error_total == call_error_count:
                    completed_tool_calls[tool_use_id] = {
                        "tool_use_id": tool_use_id,
                        "name": tool_name,
                        "arguments": arguments,
                        "synthetic_from_text": bool(
                            event.synthetic_from_text or pending.synthetic_from_text
                        ),
                    }
            elif isinstance(event, DoneEvent):
                got_done = True
                if self.proposer_tools and pending_tool_calls:
                    for tool_use_id in pending_tool_calls:
                        record_tool_error("incomplete_tool_call", tool_use_id)
                    pending_reported = True
                result.input_tokens = event.input_tokens
                result.output_tokens = event.output_tokens
                result.reasoning_tokens = event.reasoning_tokens
                result.cached_tokens = event.cached_tokens
                result.cache_write_tokens = event.cache_write_tokens
                result.billed_cost = event.billed_cost
                result.cost_source = event.cost_source
                result.provider_usage = event.provider_usage
                result.stop_reason = event.stop_reason
                result.model = event.model or result.model
            elif isinstance(event, ErrorEvent):
                result.error = event.message
                result.error_code = event.code
                break
        if not self.proposer_tools:
            result.text = _truncate_text(
                "".join(text_parts + tool_parts),
                self.candidate_max_chars,
            )
            if not got_done and not result.error:
                result.error = "proposer stream ended before DoneEvent"
                result.error_code = "stream_incomplete"
            return result

        if pending_tool_calls and not pending_reported:
            for tool_use_id in pending_tool_calls:
                record_tool_error("incomplete_tool_call", tool_use_id)
        if result.tool_call_errors:
            result.tool_calls.clear()
            if not result.error:
                result.error = "malformed proposer tool stream: " + ", ".join(
                    result.tool_call_errors
                )
                result.error_code = "malformed_tool_stream"
        else:
            result.tool_calls = [
                completed_tool_calls[tool_use_id]
                for tool_use_id in tool_call_order
                if tool_use_id in completed_tool_calls
            ]

        raw_text = "".join(text_parts)
        synthetic_tool_names = [
            str(tool_call.get("name") or "")
            for tool_call in result.tool_calls
            if tool_call.get("synthetic_from_text")
        ]
        if synthetic_tool_names:
            # Import lazily: importing opensquilla.engine while the provider package
            # is initializing creates a provider -> engine -> provider cycle.
            from opensquilla.engine.tool_text_compat import (
                strip_synthetic_tool_call_suffix,
            )

            raw_text = strip_synthetic_tool_call_suffix(
                raw_text,
                synthetic_tool_names,
            )
        (
            result.prompt_tool_calls,
            tool_call_chars,
            result.tool_calls_truncated,
        ) = _bounded_candidate_tool_calls(result.tool_calls, self.candidate_max_chars)
        if self.candidate_max_chars > 0:
            remaining_text_chars = max(0, self.candidate_max_chars - tool_call_chars)
            result.text = (
                _truncate_text(
                    raw_text,
                    remaining_text_chars,
                    strict_budget=True,
                )
                if remaining_text_chars > 0
                else ""
            )
        else:
            result.text = raw_text
        if not got_done and not result.error:
            result.error = "proposer stream ended before DoneEvent"
            result.error_code = "stream_incomplete"
        return result

    @staticmethod
    def _candidate_prompt_content(candidate: _CandidateResult) -> str:
        text = candidate.text.strip()
        if not candidate.tool_calls:
            return text or "[empty]"
        proposed_calls = (
            _tool_calls_json(candidate.prompt_tool_calls) if candidate.prompt_tool_calls else ""
        )
        sections = [text] if text else []
        sections.extend(
            [
                (
                    '<PROPOSED_TOOL_CALLS status="not_executed"'
                    f' truncated="{str(candidate.tool_calls_truncated).lower()}"'
                    + (' omitted="true"' if not candidate.prompt_tool_calls else "")
                    + ">"
                ),
            ]
        )
        if proposed_calls:
            sections.append(proposed_calls)
        sections.append("</PROPOSED_TOOL_CALLS>")
        return "\n".join(sections)

    def _build_prefilter_messages(
        self,
        messages: list[Message],
        candidates: Sequence[_CandidateResult],
        *,
        top_k: int,
    ) -> list[Message]:
        ordered = sorted(candidates, key=lambda candidate: candidate.index)
        lines = [
            "Rank the candidate drafts for final answer quality.",
            "Use the original conversation as context, but judge only the candidate drafts.",
            f"Return JSON only with the best {top_k} zero-based candidate indexes, in order.",
            'Schema: {"ranked_candidate_indexes":[0],"scores":[{"index":0,"score":0.0}]}',
            "",
            "Candidate drafts:",
        ]
        for candidate in ordered:
            lines.append(f'\n<CANDIDATE index="{candidate.index}">')
            lines.append(self._candidate_prompt_content(candidate))
            lines.append(f"</CANDIDATE {candidate.index}>")
        return [*messages, Message(role="user", content="\n".join(lines))]

    def _build_selector_messages(
        self,
        messages: list[Message],
        candidates: Sequence[_CandidateResult],
    ) -> list[Message]:
        ordered = sorted(candidates, key=lambda candidate: candidate.index)
        lines = [
            "Select the single best candidate draft for the final answer.",
            "Use the original conversation as context, but do not synthesize, merge, "
            "or rewrite the drafts.",
            "Return JSON only with the zero-based candidate index.",
            'Schema: {"selected_candidate_index":0,"rationale":"brief reason"}',
            "",
            "Candidate drafts:",
        ]
        for candidate in ordered:
            lines.append(f'\n<CANDIDATE index="{candidate.index}">')
            lines.append(self._candidate_prompt_content(candidate))
            lines.append(f"</CANDIDATE {candidate.index}>")
        return [*messages, Message(role="user", content="\n".join(lines))]

    def _build_aggregator_messages(
        self,
        messages: list[Message],
        candidates: Sequence[_CandidateResult],
    ) -> list[Message]:
        ordered = list(candidates)
        if self.shuffle_candidates:
            random.shuffle(ordered)
        lines = [
            "You are the aggregator in a multi-model B5 fusion experiment.",
            "Synthesize the best answer or next tool call from the original "
            "conversation and the candidate drafts.",
            "Do not mention the ensemble, candidates, or model names unless the "
            "user explicitly asks.",
            "If tools are available and more evidence/action is needed, call "
            "exactly the appropriate tool(s).",
            "Otherwise, answer the user directly with the strongest fused result.",
            "",
            "Candidate drafts:",
        ]
        if any(candidate.tool_calls for candidate in ordered):
            lines.extend(
                [
                    "Candidate PROPOSED_TOOL_CALLS are structured suggestions that have "
                    "not been executed.",
                    "If one should run, issue a fresh structured call through the tools "
                    "available to you; never present the serialized tool-call JSON as "
                    "the final answer.",
                ]
            )
        for display_index, candidate in enumerate(ordered, start=1):
            lines.append(f"\n<CANDIDATE {display_index}>")
            lines.append(self._candidate_prompt_content(candidate))
            lines.append(f"</CANDIDATE {display_index}>")
        return [*messages, Message(role="user", content="\n".join(lines))]

    def _build_moa_refine_messages(
        self,
        messages: list[Message],
        previous_answer: str,
        *,
        layer_index: int,
    ) -> list[Message]:
        lines = [
            f"You are layer {layer_index} in a multi-layer MoA refinement.",
            "Use the original conversation as context and improve the previous "
            "fused answer for correctness, completeness, and clarity.",
            "Do not mention the ensemble, layers, candidates, or model names unless "
            "the user explicitly asks.",
            "If tools are available and more evidence/action is needed, call exactly "
            "the appropriate tool(s).",
            "Otherwise, answer the user directly with the strongest final result.",
            "",
            "Previous fused answer:",
            previous_answer.strip() or "[empty]",
        ]
        return [*messages, Message(role="user", content="\n".join(lines))]

    def _trace_payload(
        self,
        candidates: Sequence[_CandidateResult],
        *,
        successful_count: int,
        fallback_used: bool,
        fallback_reason: str,
        final_request_role: str = "",
        selected_candidates: Sequence[_CandidateResult] | None = None,
        prefilter_trace: dict[str, Any] | None = None,
        prefilter_request_count: int = 0,
        final_request_count: int | None = None,
        moa_layers: int = 1,
        output_strategy: str = "fusion",
        selection_trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected = list(selected_candidates or [])
        final_requests = (
            int(final_request_count)
            if final_request_count is not None
            else (1 if final_request_role else 0)
        )
        row = {
            "mode": "b5_fusion",
            "profile": self.profile_name,
            "successful_proposers": successful_count,
            "total_candidates": len(candidates),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "shuffle_candidates": self.shuffle_candidates,
            "proposer_tools_enabled": self.proposer_tools,
            "final_request_role": final_request_role,
            "llm_request_count": (
                len(candidates)
                + int(prefilter_request_count or 0)
                + final_requests
            ),
            "candidates": [
                candidate.trace_row(include_text=self.record_candidates)
                for candidate in candidates
            ],
        }
        if self.proposer_early_stop_success_count > 0:
            early_stopped_count = sum(
                1 for candidate in candidates if candidate.error_code == "early_stopped"
            )
            row["proposer_early_stop"] = {
                "enabled": True,
                "success_count": self.proposer_early_stop_success_count,
                "after_seconds": self.proposer_early_stop_after_seconds,
                "early_stopped_count": early_stopped_count,
                "usage_unknown_count": early_stopped_count,
                "cost_observed": early_stopped_count == 0,
            }
        requests = [candidate.request for candidate in candidates if candidate.request]
        if prefilter_trace and prefilter_trace.get("request"):
            requests.append(prefilter_trace["request"])
        if selection_trace and selection_trace.get("request"):
            requests.append(selection_trace["request"])
        if requests:
            row["requests"] = requests
        if moa_layers > 1:
            row["moa_layers"] = moa_layers
            row["moa_refine_count"] = moa_layers - 1
            row["moa_intermediate_layers"] = moa_layers - 1
        if output_strategy != "fusion":
            row["output_strategy"] = output_strategy
        if (
            self.candidate_prefilter_top_k > 0
            or prefilter_trace is not None
            or output_strategy != "fusion"
        ):
            row["selected_candidate_count"] = len(selected)
            row["selected_candidate_indexes"] = [candidate.index for candidate in selected]
        if selection_trace is not None:
            row["candidate_selection"] = selection_trace
        if self.candidate_prefilter_top_k > 0 or prefilter_trace is not None:
            row["candidate_prefilter"] = prefilter_trace or {
                "enabled": self.candidate_prefilter_top_k > 0,
                "applied": False,
                "top_k": self.candidate_prefilter_top_k,
            }
        return row

    async def _fallback_or_error(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None,
        config: ChatConfig | None,
        reason: str,
        code: str,
        candidates: Sequence[_CandidateResult],
    ) -> AsyncIterator[StreamEvent]:
        if self.all_failed_policy != "fallback_single" or self.fallback_provider is None:
            yield ErrorEvent(message=reason, code=code)
            return
        trace = self._trace_payload(
            candidates,
            successful_count=sum(1 for candidate in candidates if candidate.ok),
            fallback_used=True,
            fallback_reason=reason,
            final_request_role="fallback_single",
            selected_candidates=[candidate for candidate in candidates if candidate.ok],
        )
        _append_request_trace(
            trace,
            _fallback_request_trace(
                profile=self.profile_name,
                provider=self.fallback_provider,
                messages=messages,
                tools=tools,
                config=config,
            ),
        )
        proposer_rows = _candidate_usage_rows(candidates, profile=self.profile_name)
        async for event in self.fallback_provider.chat(messages, tools=tools, config=config):
            if isinstance(event, DoneEvent):
                _fill_last_request_model(
                    trace,
                    role="fallback_single",
                    model=event.model,
                )
                fallback_row = _done_usage_row(
                    event,
                    role="fallback_single",
                    profile=self.profile_name,
                    label="fallback",
                    provider=str(getattr(self.fallback_provider, "provider_name", "fallback")),
                    model=event.model,
                )
                rows = [*proposer_rows, fallback_row]
                yield replace(
                    event,
                    input_tokens=_summed_int(rows, "input_tokens"),
                    output_tokens=_summed_int(rows, "output_tokens"),
                    reasoning_tokens=_summed_int(rows, "reasoning_tokens"),
                    cached_tokens=_summed_int(rows, "cached_tokens"),
                    cache_write_tokens=_summed_int(rows, "cache_write_tokens"),
                    billed_cost=_summed_float(rows, "billed_cost"),
                    cost_source=_rollup_cost_source(rows),
                    model_usage_breakdown=rows,
                    ensemble_trace=trace,
                )
            else:
                yield event


def _secret_from_env(env_name: str) -> str:
    return os.environ.get(env_name, "").strip() if env_name else ""


def _member_provider_config(ref: Any, inherited: ProviderConfig) -> ProviderConfig:
    provider = str(getattr(ref, "provider", "") or inherited.provider).strip()
    model = str(getattr(ref, "model", "") or "").strip()
    if not model:
        raise ValueError("llm_ensemble model ref requires a non-empty model")
    same_provider = provider == inherited.provider
    api_key_env = str(getattr(ref, "api_key_env", "") or "").strip()
    api_key = _secret_from_env(api_key_env)
    if not api_key and same_provider:
        api_key = inherited.api_key
    if not api_key:
        api_key = _secret_from_env(get_provider_spec(provider).env_key)
    base_url = str(getattr(ref, "base_url", "") or "").strip()
    if not base_url:
        base_url = (
            inherited.base_url
            if same_provider
            else get_provider_spec(provider).default_base_url
        )
    proxy = str(getattr(ref, "proxy", "") or "").strip()
    if not proxy and same_provider:
        proxy = inherited.proxy
    provider_routing = inherited.provider_routing if same_provider else {}
    return ProviderConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        proxy=proxy,
        provider_routing=provider_routing,
    )


def _member_from_ref(ref: Any, inherited: ProviderConfig, *, label: str) -> EnsembleMemberConfig:
    return EnsembleMemberConfig(
        provider_config=_member_provider_config(ref, inherited),
        label=label,
        temperature=getattr(ref, "temperature", None),
        max_tokens=int(getattr(ref, "max_tokens", 0) or 0),
        thinking=getattr(ref, "thinking", None),
        k=max(1, int(getattr(ref, "k", 1) or 1)),
    )


def build_ensemble_provider_from_config(
    *,
    config: Any,
    inherited_provider_config: ProviderConfig,
    fallback_provider: LLMProvider,
) -> EnsembleProvider:
    ensemble_cfg = getattr(config, "llm_ensemble", None)
    if ensemble_cfg is None or not getattr(ensemble_cfg, "enabled", False):
        raise ValueError("llm_ensemble is not enabled")
    profile_name = str(getattr(ensemble_cfg, "active_profile", "") or "").strip()
    profiles = getattr(ensemble_cfg, "profiles", {}) or {}
    profile = profiles.get(profile_name)
    if profile is None:
        raise ValueError(f"llm_ensemble profile {profile_name!r} is not configured")
    proposers = [
        _member_from_ref(ref, inherited_provider_config, label=f"proposer_{index + 1}")
        for index, ref in enumerate(getattr(profile, "proposers", []) or [])
    ]
    aggregator = _member_from_ref(
        getattr(profile, "aggregator"),
        inherited_provider_config,
        label="aggregator",
    )
    scorer_ref = getattr(profile, "candidate_scorer", None)
    candidate_scorer = None
    if scorer_ref is not None and str(getattr(scorer_ref, "model", "") or "").strip():
        candidate_scorer = _member_from_ref(
            scorer_ref,
            inherited_provider_config,
            label="candidate_scorer",
        )
    return EnsembleProvider(
        profile_name=profile_name,
        proposers=proposers,
        aggregator=aggregator,
        fallback_provider=fallback_provider,
        min_successful_proposers=int(getattr(ensemble_cfg, "min_successful_proposers", 1) or 1),
        all_failed_policy=getattr(ensemble_cfg, "all_failed_policy", "fallback_single"),
        proposer_timeout_seconds=float(
            getattr(profile, "proposer_timeout_seconds", 120.0) or 120.0
        ),
        aggregator_timeout_seconds=float(
            getattr(profile, "aggregator_timeout_seconds", 120.0) or 120.0
        ),
        candidate_max_chars=int(getattr(profile, "candidate_max_chars", 24_000) or 0),
        shuffle_candidates=bool(getattr(profile, "shuffle_candidates", True)),
        record_candidates=bool(getattr(profile, "record_candidates", False)),
        proposer_tools=bool(getattr(ensemble_cfg, "proposer_tools", False)),
        candidate_scorer=candidate_scorer,
        candidate_prefilter_top_k=int(getattr(profile, "candidate_prefilter_top_k", 0) or 0),
        proposer_early_stop_success_count=int(
            getattr(profile, "proposer_early_stop_success_count", 0) or 0
        ),
        proposer_early_stop_after_seconds=float(
            getattr(profile, "proposer_early_stop_after_seconds", 0.0) or 0.0
        ),
        output_strategy=getattr(profile, "output_strategy", "fusion"),
        moa_layers=int(getattr(profile, "moa_layers", 1) or 1),
    )
