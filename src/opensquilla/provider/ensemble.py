"""Experimental B5 multi-model ensemble provider."""

from __future__ import annotations

import asyncio
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

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.text.strip())

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
        if include_text:
            row["text"] = self.text
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


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker = "\n\n[truncated]"
    return text[: max(0, max_chars - len(marker))] + marker


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
) -> list[int]:
    allowed = {candidate.index for candidate in candidates}
    payload = _extract_json_payload(text)
    ranked: list[int] = []

    def append(value: Any) -> None:
        index = _candidate_index(value, allowed)
        if index is not None and index not in ranked:
            ranked.append(index)

    if isinstance(payload, dict):
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
        aggregator_messages = self._build_aggregator_messages(messages, prefilter.candidates)
        aggregator_cfg = _member_chat_config(config, self.aggregator)
        if self.aggregator_timeout_seconds > 0:
            aggregator_cfg = aggregator_cfg.model_copy(
                update={"timeout": self.aggregator_timeout_seconds}
            )
        provider = _build_provider(self.aggregator.provider_config)
        proposer_rows = _candidate_usage_rows(candidates, profile=self.profile_name)
        prefilter_rows = prefilter.usage_rows
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
        index = 0
        for member in self.proposers:
            k = max(1, int(member.k or 1))
            for sample_index in range(k):
                tasks.append(
                    asyncio.create_task(
                        self._collect_candidate(
                            index=index,
                            sample_index=sample_index,
                            member=member,
                            messages=messages,
                            tools=tools if self.proposer_tools else None,
                            config=config,
                        )
                    )
                )
                index += 1
        if not tasks:
            return []
        return [result for result in await asyncio.gather(*tasks)]

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
        try:
            stream = provider.chat(
                self._build_prefilter_messages(messages, candidates, top_k=top_k),
                tools=None,
                config=scorer_cfg,
            )
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
        text_parts: list[str] = []
        tool_parts: list[str] = []
        got_done = False
        async for event in provider.chat(messages, tools=tools, config=chat_cfg):
            if isinstance(event, TextDeltaEvent):
                if result.ttft_ms is None and event.text:
                    result.ttft_ms = int((time.monotonic() - started) * 1000)
                text_parts.append(event.text)
            elif isinstance(event, ReasoningDeltaEvent):
                continue
            elif isinstance(event, ToolUseStartEvent):
                tool_parts.append(f"\n[tool_use:{event.tool_name}]")
            elif isinstance(event, ToolUseDeltaEvent):
                if event.json_fragment:
                    tool_parts.append(event.json_fragment)
            elif isinstance(event, ToolUseEndEvent):
                if event.arguments:
                    tool_parts.append(f"\n[tool_args:{event.arguments}]")
            elif isinstance(event, DoneEvent):
                got_done = True
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
        result.text = _truncate_text("".join(text_parts + tool_parts), self.candidate_max_chars)
        if not got_done and not result.error:
            result.error = "proposer stream ended before DoneEvent"
            result.error_code = "stream_incomplete"
        return result

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
            lines.append(candidate.text.strip() or "[empty]")
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
        for display_index, candidate in enumerate(ordered, start=1):
            lines.append(f"\n<CANDIDATE {display_index}>")
            lines.append(candidate.text.strip() or "[empty]")
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
        if moa_layers > 1:
            row["moa_layers"] = moa_layers
            row["moa_refine_count"] = moa_layers - 1
            row["moa_intermediate_layers"] = moa_layers - 1
        if self.candidate_prefilter_top_k > 0 or prefilter_trace is not None:
            row["selected_candidate_count"] = len(selected)
            row["selected_candidate_indexes"] = [candidate.index for candidate in selected]
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
        proposer_rows = _candidate_usage_rows(candidates, profile=self.profile_name)
        async for event in self.fallback_provider.chat(messages, tools=tools, config=config):
            if isinstance(event, DoneEvent):
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
        moa_layers=int(getattr(profile, "moa_layers", 1) or 1),
    )
