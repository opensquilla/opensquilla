"""G8 B5-style multi-model ensemble provider."""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from .protocol import LLMProvider, ProviderMetadata
from .model_catalog import ModelCatalog
from .registry import get_provider_spec
from .selector import ModelSelector, ProviderConfig, SelectorConfig
from .types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ModelCapabilities,
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

TRACE_CONTENT_MAX_CHARS = 8_000


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
    stop_reason: str = ""
    elapsed_ms: int = 0
    ttft_ms: int | None = None
    error: str = ""
    error_code: str = ""
    execution: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.text.strip())

    def usage_row(self, *, role: str, profile: str) -> dict[str, Any]:
        return {
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

    def trace_row(self, *, include_text: bool, content_max_chars: int) -> dict[str, Any]:
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
        if self.execution:
            row["execution"] = dict(self.execution)
        row["content"] = _trace_content(self.text, max_chars=content_max_chars)
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

    def usage_row(
        self,
        *,
        profile: str,
        member: EnsembleMemberConfig,
        role: str = "aggregator",
        label: str = "",
    ) -> dict[str, Any]:
        cfg = member.provider_config
        return {
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


def _normalize_thinking(value: str | None) -> tuple[bool | None, Any | None]:
    if value is None:
        return None, None
    normalized = str(value).strip().lower()
    if not normalized:
        return None, None
    if normalized == "off":
        return False, "off"
    return True, normalized


def _openrouter_static_capabilities(model: str) -> ModelCapabilities | None:
    model_l = model.strip().lower()
    reasoning_prefixes = (
        "deepseek/",
        "google/gemini",
        "moonshotai/kimi-k2",
        "qwen/qwen3",
        "z-ai/glm-",
    )
    if model_l.startswith(reasoning_prefixes):
        return ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            supports_vision=model_l.startswith("google/gemini"),
            reasoning_format="openrouter",
        )
    return None


def _member_model_capabilities(member: EnsembleMemberConfig) -> ModelCapabilities:
    cfg = member.provider_config
    provider = cfg.provider.strip().lower()
    if provider == "openrouter":
        static_caps = _openrouter_static_capabilities(cfg.model)
        if static_caps is not None:
            return static_caps
    try:
        return ModelCatalog().get_capabilities(
            cfg.model,
            provider_name=provider,
            base_url=cfg.base_url,
        )
    except Exception:
        return ModelCapabilities()


def _member_chat_config(base: ChatConfig | None, member: EnsembleMemberConfig) -> ChatConfig:
    cfg = base.model_copy(deep=True) if base is not None else ChatConfig()
    updates: dict[str, Any] = {"model_capabilities": _member_model_capabilities(member)}
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


def _done_usage_row(
    event: DoneEvent,
    *,
    role: str,
    profile: str,
    label: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    return {
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


class EnsembleProvider:
    """G8 fusion provider: proposer candidates first, one aggregator stream after."""

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

    def provider_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_name="ensemble",
            provider_kind="ensemble",
            model=f"ensemble/{self.profile_name}",
            base_url="",
        )

    async def list_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        for member in [*self.proposers, self.aggregator]:
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

        aggregator_cfg = _member_chat_config(config, self.aggregator)
        if self.aggregator_timeout_seconds > 0:
            aggregator_cfg = aggregator_cfg.model_copy(
                update={"timeout": self.aggregator_timeout_seconds}
            )
        provider = _build_provider(self.aggregator.provider_config)
        proposer_rows = _candidate_usage_rows(candidates, profile=self.profile_name)
        aggregator_messages = self._build_aggregator_messages(messages, successful)
        trace = self._trace_payload(
            candidates,
            successful_count=len(successful),
            fallback_used=False,
            fallback_reason="",
            final_request_role="aggregator",
            selected_candidates=successful,
            final_request_member=self.aggregator,
            final_request_config=aggregator_cfg,
            final_request_tools=tools,
            final_request_messages=aggregator_messages,
            final_request_timeout_seconds=self.aggregator_timeout_seconds,
        )
        async for event in self._stream_final_aggregator(
            provider=provider,
            messages=aggregator_messages,
            tools=tools,
            config=aggregator_cfg,
            prior_rows=proposer_rows,
            trace=trace,
        ):
            yield event

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
        result.execution = _member_execution_trace(
            member,
            role="proposer",
            chat_config=chat_cfg,
            tools=tools,
            timeout_seconds=self.proposer_timeout_seconds,
        )
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

    def _trace_payload(
        self,
        candidates: Sequence[_CandidateResult],
        *,
        successful_count: int,
        fallback_used: bool,
        fallback_reason: str,
        final_request_role: str,
        selected_candidates: Sequence[_CandidateResult] | None = None,
        final_request_member: EnsembleMemberConfig | None = None,
        final_request_config: ChatConfig | None = None,
        final_request_tools: list[ToolDefinition] | None = None,
        final_request_messages: Sequence[Message] | None = None,
        final_request_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        selected = list(selected_candidates or [])
        trace = {
            "mode": "b5_fusion",
            "profile": self.profile_name,
            "successful_proposers": successful_count,
            "total_candidates": len(candidates),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "shuffle_candidates": self.shuffle_candidates,
            "record_candidates": self.record_candidates,
            "proposer_tools": self.proposer_tools,
            "content_max_chars": TRACE_CONTENT_MAX_CHARS,
            "final_request_role": final_request_role,
            "llm_request_count": len(candidates) + (1 if final_request_role else 0),
            "selected_candidate_count": len(selected),
            "selected_candidate_indexes": [candidate.index for candidate in selected],
            "candidates": [
                candidate.trace_row(
                    include_text=self.record_candidates,
                    content_max_chars=TRACE_CONTENT_MAX_CHARS,
                )
                for candidate in candidates
            ],
        }
        final_request: dict[str, Any] = {"role": final_request_role}
        if final_request_member is not None:
            final_request["execution"] = _member_execution_trace(
                final_request_member,
                role=final_request_role,
                chat_config=final_request_config,
                tools=final_request_tools,
                timeout_seconds=final_request_timeout_seconds,
            )
        elif final_request_config is not None or final_request_tools is not None:
            final_request["execution"] = _request_execution_trace(
                role=final_request_role,
                chat_config=final_request_config,
                tools=final_request_tools,
                timeout_seconds=final_request_timeout_seconds,
            )
        if final_request_messages is not None:
            final_request["input"] = _messages_trace(
                final_request_messages,
                max_chars=TRACE_CONTENT_MAX_CHARS,
            )
        trace["final_request"] = final_request
        return trace

    async def _stream_final_aggregator(
        self,
        *,
        provider: LLMProvider,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: ChatConfig,
        prior_rows: list[dict[str, Any]],
        trace: dict[str, Any],
    ) -> AsyncIterator[StreamEvent]:
        final_text_parts: list[str] = []

        def ensemble_done(event: DoneEvent) -> DoneEvent:
            output_text = "".join(final_text_parts)
            _attach_final_request_output(trace, event=event, output_text=output_text)
            acc = _AggregatorAccumulator(
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                reasoning_tokens=event.reasoning_tokens,
                cached_tokens=event.cached_tokens,
                cache_write_tokens=event.cache_write_tokens,
                billed_cost=event.billed_cost,
                cost_source=event.cost_source,
                model=event.model or self.aggregator.provider_config.model,
            )
            rows = [
                *prior_rows,
                acc.usage_row(
                    profile=self.profile_name,
                    member=self.aggregator,
                    role="aggregator",
                    label="aggregator",
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
                            yield ensemble_done(event)
                        elif isinstance(event, ErrorEvent):
                            yield event
                            return
                        elif isinstance(event, TextDeltaEvent):
                            final_text_parts.append(event.text)
                            yield event
                        else:
                            yield event
            else:
                async for event in stream:
                    if isinstance(event, DoneEvent):
                        yielded_done = True
                        yield ensemble_done(event)
                    elif isinstance(event, ErrorEvent):
                        yield event
                        return
                    elif isinstance(event, TextDeltaEvent):
                        final_text_parts.append(event.text)
                        yield event
                    else:
                        yield event
        except TimeoutError:
            yield ErrorEvent(
                message=(
                    "ensemble aggregator timed out after "
                    f"{self.aggregator_timeout_seconds:g}s"
                ),
                code="ensemble_aggregator_timeout",
            )
            return
        except Exception as exc:  # noqa: BLE001 - provider boundary returns ErrorEvent
            yield ErrorEvent(
                message=f"ensemble aggregator failed: {exc}",
                code="ensemble_aggregator_error",
            )
            return
        if not yielded_done:
            yield ErrorEvent(
                message="ensemble aggregator stream ended before DoneEvent",
                code="ensemble_aggregator_incomplete",
            )

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
            final_request_config=config,
            final_request_tools=tools,
            final_request_messages=messages,
            final_request_timeout_seconds=(
                float(getattr(config, "timeout", 0.0) or 0.0) if config is not None else None
            ),
        )
        proposer_rows = _candidate_usage_rows(candidates, profile=self.profile_name)
        final_text_parts: list[str] = []
        async for event in self.fallback_provider.chat(messages, tools=tools, config=config):
            if isinstance(event, DoneEvent):
                output_text = "".join(final_text_parts)
                _attach_final_request_output(trace, event=event, output_text=output_text)
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
            elif isinstance(event, TextDeltaEvent):
                final_text_parts.append(event.text)
                yield event
            else:
                yield event


def _trace_content(text: str, *, max_chars: int = TRACE_CONTENT_MAX_CHARS) -> dict[str, Any]:
    value = text or ""
    if max_chars <= 0:
        clipped = value
    else:
        clipped = value[:max_chars]
    return {
        "text": clipped,
        "chars": len(value),
        "truncated": len(clipped) < len(value),
    }


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                item_type = str(item.get("type") or "")
                if item_type == "text":
                    parts.append(str(item.get("text") or ""))
                elif item_type == "tool_use":
                    parts.append(
                        f"[tool_use:{item.get('name') or ''} "
                        f"{item.get('input') or {}}]"
                    )
                elif item_type == "tool_result":
                    parts.append(f"[tool_result:{item.get('content') or ''}]")
                elif item_type == "image":
                    parts.append("[image]")
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _messages_trace(
    messages: Sequence[Message],
    *,
    max_chars: int = TRACE_CONTENT_MAX_CHARS,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total_chars = 0
    for index, message in enumerate(messages):
        text = _message_content_text(message.content)
        total_chars += len(text)
        rows.append(
            {
                "index": index,
                "role": message.role,
                "content": _trace_content(text, max_chars=max_chars),
            }
        )
    return {
        "message_count": len(rows),
        "total_chars": total_chars,
        # The final synthetic user message contains the candidate draft content
        # for the aggregator; keep full rows for small conversations and a
        # stable tail for larger ones.
        "messages": rows if len(rows) <= 4 else [rows[0], *rows[-3:]],
    }


def _member_execution_trace(
    member: EnsembleMemberConfig,
    *,
    role: str,
    chat_config: ChatConfig | None,
    tools: list[ToolDefinition] | None,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    cfg = member.provider_config
    payload = _request_execution_trace(
        role=role,
        chat_config=chat_config,
        tools=tools,
        timeout_seconds=timeout_seconds,
    )
    payload.update(
        {
            "label": member.label or role,
            "provider": cfg.provider,
            "model": cfg.model,
            "temperature_override": member.temperature,
            "max_tokens_override": member.max_tokens,
            "thinking_override": member.thinking,
            "k": member.k,
            "base_url": cfg.base_url,
            "proxy_configured": bool(cfg.proxy),
            "provider_routing": _json_safe(dict(cfg.provider_routing)),
        }
    )
    return payload


def _request_execution_trace(
    *,
    role: str,
    chat_config: ChatConfig | None,
    tools: list[ToolDefinition] | None,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    return {
        "role": role,
        "timeout_seconds": timeout_seconds,
        "tools_enabled": tools is not None,
        "tool_count": len(tools or []),
        "tool_names": [tool.name for tool in tools or []],
        "effective_max_tokens": getattr(chat_config, "max_tokens", None),
        "effective_temperature": getattr(chat_config, "temperature", None),
        "effective_thinking": getattr(chat_config, "thinking", None),
        "effective_thinking_level": _json_safe(getattr(chat_config, "thinking_level", None)),
        "effective_timeout": getattr(chat_config, "timeout", None),
        "effective_tool_choice": _json_safe(getattr(chat_config, "tool_choice", None)),
    }


def _attach_final_request_output(
    trace: dict[str, Any],
    *,
    event: DoneEvent,
    output_text: str,
) -> None:
    final_request = trace.setdefault("final_request", {})
    final_request["output"] = _trace_content(output_text, max_chars=TRACE_CONTENT_MAX_CHARS)
    final_request["usage"] = {
        "model": event.model,
        "stop_reason": event.stop_reason,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "reasoning_tokens": event.reasoning_tokens,
        "cached_tokens": event.cached_tokens,
        "cache_write_tokens": event.cache_write_tokens,
        "billed_cost": event.billed_cost,
        "cost_source": event.cost_source,
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _secret_from_env(env_name: str) -> str:
    return os.environ.get(env_name, "").strip() if env_name else ""


def _member_provider_config(ref: Any, inherited: ProviderConfig) -> ProviderConfig:
    provider = str(getattr(ref, "provider", "") or inherited.provider).strip().lower()
    model = str(getattr(ref, "model", "") or "").strip()
    if not model:
        raise ValueError("llm_ensemble model ref requires a non-empty model")
    same_provider = provider == str(inherited.provider or "").strip().lower()
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
        org_id=inherited.org_id if same_provider else "",
        proxy=proxy,
        provider_routing=dict(provider_routing),
    )


def _member_from_ref(
    ref: Any,
    *,
    inherited: ProviderConfig,
    label: str,
) -> EnsembleMemberConfig:
    return EnsembleMemberConfig(
        provider_config=_member_provider_config(ref, inherited),
        label=label,
        temperature=getattr(ref, "temperature", None),
        max_tokens=int(getattr(ref, "max_tokens", 0) or 0),
        thinking=getattr(ref, "thinking", None),
        k=int(getattr(ref, "k", 1) or 1),
    )


def build_ensemble_provider_from_config(
    *,
    config: Any,
    inherited_provider_config: ProviderConfig,
    fallback_provider: LLMProvider | None,
) -> EnsembleProvider:
    ensemble_cfg = getattr(config, "llm_ensemble", None)
    if ensemble_cfg is None:
        raise ValueError("config.llm_ensemble is required")
    profile_name = str(getattr(ensemble_cfg, "active_profile", "") or "").strip()
    profile = getattr(ensemble_cfg, "profiles", {}).get(profile_name)
    if profile is None:
        raise ValueError(f"llm_ensemble profile {profile_name!r} is not configured")
    proposers = [
        _member_from_ref(ref, inherited=inherited_provider_config, label=f"proposer_{index + 1}")
        for index, ref in enumerate(getattr(profile, "proposers", []) or [])
    ]
    aggregator = _member_from_ref(
        getattr(profile, "aggregator"),
        inherited=inherited_provider_config,
        label="aggregator",
    )
    return EnsembleProvider(
        profile_name=profile_name,
        proposers=proposers,
        aggregator=aggregator,
        fallback_provider=fallback_provider,
        min_successful_proposers=int(getattr(ensemble_cfg, "min_successful_proposers", 1) or 1),
        all_failed_policy=getattr(ensemble_cfg, "all_failed_policy", "fallback_single"),
        proposer_timeout_seconds=float(getattr(profile, "proposer_timeout_seconds", 120.0)),
        aggregator_timeout_seconds=float(getattr(profile, "aggregator_timeout_seconds", 120.0)),
        candidate_max_chars=int(getattr(profile, "candidate_max_chars", 24_000) or 0),
        shuffle_candidates=bool(getattr(profile, "shuffle_candidates", True)),
        record_candidates=bool(getattr(profile, "record_candidates", False)),
        proposer_tools=bool(getattr(ensemble_cfg, "proposer_tools", False)),
    )
