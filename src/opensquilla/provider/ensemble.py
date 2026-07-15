"""G8 B5-style multi-model ensemble provider."""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import structlog

from opensquilla.context_budget import ContextBudgetGovernor

from .model_catalog import resolve_effective_context_window, shared_catalog
from .protocol import (
    LLMProvider,
    ProviderMetadata,
    project_provider_message_count,
)
from .registry import get_provider_spec
from .selector import ModelSelector, ProviderConfig, SelectorConfig
from .types import (
    ChatConfig,
    DoneEvent,
    EnsembleProgressEvent,
    ErrorEvent,
    Message,
    ModelCapabilities,
    ModelInfo,
    ProviderHeartbeatEvent,
    ProviderMessageCountProjection,
    ProviderMessageLimitProof,
    ReasoningDeltaEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)

TRACE_CONTENT_MAX_CHARS = 8_000
_ENSEMBLE_HEARTBEAT_INTERVAL_SECONDS = 15.0
log = structlog.get_logger(__name__)


def _ensemble_heartbeat_interval() -> float:
    return max(0.001, float(_ENSEMBLE_HEARTBEAT_INTERVAL_SECONDS))


async def _stream_with_heartbeats(
    stream: AsyncIterator[StreamEvent],
    *,
    phase: str,
    message: str,
    timeout_seconds: float | None,
) -> AsyncIterator[StreamEvent]:
    stream_iter = stream.__aiter__()
    pending: asyncio.Future[StreamEvent] = asyncio.ensure_future(stream_iter.__anext__())
    deadline = (
        time.monotonic() + timeout_seconds
        if timeout_seconds is not None and timeout_seconds > 0
        else None
    )
    try:
        while True:
            wait_seconds = _ensemble_heartbeat_interval()
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                wait_seconds = min(wait_seconds, remaining)
            done, _ = await asyncio.wait({pending}, timeout=wait_seconds)
            if not done:
                yield ProviderHeartbeatEvent(phase=phase, message=message)
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            yield event
            pending = asyncio.ensure_future(stream_iter.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        aclose = getattr(stream_iter, "aclose", None)
        if callable(aclose):
            with contextlib.suppress(Exception):
                await aclose()


@dataclass(frozen=True)
class EnsembleMemberConfig:
    """A provider plus per-call generation overrides for one ensemble member."""

    provider_config: ProviderConfig
    label: str = ""
    temperature: float | None = None
    max_tokens: int = 0
    thinking: str | None = None
    k: int = 1


@dataclass(frozen=True)
class _MemberRequestBudgetBinding:
    """Private runtime provenance for one ensemble member's request cap."""

    context_window_tokens: int | None
    context_window_source: str
    context_overflow_threshold: float
    cap_source: str
    rederive: bool


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
    message_limit_proof: ProviderMessageLimitProof | None = None
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
            # Preserve the already-measured lifecycle duration when the final
            # done payload replaces the live progress rows in WebUI.
            "elapsed_ms": self.elapsed_ms,
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
        elapsed_ms: int = 0,
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
            "elapsed_ms": max(0, int(elapsed_ms)),
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
        return shared_catalog().get_capabilities(
            cfg.model,
            provider_name=provider,
            base_url=cfg.base_url,
        )
    except Exception:
        return ModelCapabilities()


def _member_max_tokens(member: EnsembleMemberConfig) -> int:
    if member.max_tokens and member.max_tokens > 0:
        return member.max_tokens
    cfg = member.provider_config
    try:
        return shared_catalog().resolve_max_tokens(
            cfg.model,
            user_override=0,
            provider=cfg.provider,
        )
    except Exception:
        return ChatConfig().max_tokens


def _member_budget_key(member: EnsembleMemberConfig) -> tuple[str, str, str]:
    cfg = member.provider_config
    return (
        str(cfg.provider or "").strip().lower(),
        str(cfg.model or "").strip().lower(),
        str(cfg.base_url or "").strip().rstrip("/").lower(),
    )


def _effective_request_cap_source(
    binding: _MemberRequestBudgetBinding | None,
    chat_config: ChatConfig | None,
) -> str:
    cap = int(getattr(chat_config, "provider_request_max_chars", 0) or 0)
    if cap <= 0 or binding is None:
        return "inherited"
    if binding.cap_source == "explicit":
        return "explicit"
    if binding.rederive:
        return "member_context"
    return "inherited"


def _member_chat_config(
    base: ChatConfig | None,
    member: EnsembleMemberConfig,
    *,
    request_budget_binding: _MemberRequestBudgetBinding | None = None,
    role: str = "member",
    record_budget_rebound: bool = True,
) -> ChatConfig:
    cfg = base.model_copy(deep=True) if base is not None else ChatConfig()
    updates: dict[str, Any] = {
        "max_tokens": _member_max_tokens(member),
        "model_capabilities": _member_model_capabilities(member),
    }
    if member.temperature is not None:
        updates["temperature"] = member.temperature
    thinking, thinking_level = _normalize_thinking(member.thinking)
    if thinking is not None:
        updates["thinking"] = thinking
    if thinking_level is not None:
        updates["thinking_level"] = thinking_level
    effective = cfg.model_copy(update=updates)
    inherited_cap = int(getattr(cfg, "provider_request_max_chars", 0) or 0)
    if (
        base is not None
        and inherited_cap > 0
        and request_budget_binding is not None
        and request_budget_binding.rederive
        and request_budget_binding.context_window_tokens is not None
        and request_budget_binding.context_window_tokens > 0
    ):
        thinking_budget_tokens = (
            max(0, int(effective.thinking_budget_tokens or 0))
            if effective.thinking
            else 0
        )
        rebound_cap = ContextBudgetGovernor.from_values(
            context_window_tokens=request_budget_binding.context_window_tokens,
            max_output_tokens=effective.max_tokens,
            thinking_budget_tokens=thinking_budget_tokens,
            context_overflow_threshold=(
                request_budget_binding.context_overflow_threshold
            ),
        ).snapshot().provider_request_max_chars
        effective = effective.model_copy(
            update={"provider_request_max_chars": rebound_cap}
        )
        member_cfg = member.provider_config
        if record_budget_rebound:
            log.info(
                "ensemble_member_request_budget_rebound",
                role=role,
                label=member.label or role,
                provider=member_cfg.provider,
                model=member_cfg.model,
                inherited_request_max_chars=inherited_cap,
                effective_request_max_chars=rebound_cap,
                effective_context_window_tokens=(
                    request_budget_binding.context_window_tokens
                ),
                effective_context_window_source=(
                    request_budget_binding.context_window_source
                ),
            )
    return effective


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


def _uniform_message_limit_proof(
    candidates: Sequence[_CandidateResult],
) -> ProviderMessageLimitProof | None:
    """Return a proof only when every failed proposer has the same exact class."""

    if not candidates:
        return None
    proofs: list[ProviderMessageLimitProof] = []
    for candidate in candidates:
        if candidate.ok or candidate.error_code != "400":
            return None
        if candidate.message_limit_proof is None:
            return None
        proofs.append(candidate.message_limit_proof)
    provider_identities = {
        (proof.provider_kind, proof.base_host) for proof in proofs
    }
    if len(provider_identities) != 1:
        return None
    # Limits can differ across mirrored endpoints/models.  The strictest exact
    # proof is safe for a retry that must satisfy every relevant member.
    return min(proofs, key=lambda proof: proof.limit)


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
        proposer_timeout_seconds: float = 3600.0,
        aggregator_timeout_seconds: float = 3600.0,
        candidate_max_chars: int = 24_000,
        shuffle_candidates: bool = True,
        record_candidates: bool = False,
        proposer_tools: bool = False,
        quorum_grace_seconds: float = 0.0,
        selection_plan: Mapping[str, Any] | None = None,
        _member_request_budget_bindings: Mapping[
            tuple[str, str, str], _MemberRequestBudgetBinding
        ]
        | None = None,
    ) -> None:
        self.profile_name = profile_name
        self.proposers = list(proposers)
        self.aggregator = aggregator
        self.fallback_provider = fallback_provider
        self.min_successful_proposers = max(1, int(min_successful_proposers or 1))
        self.all_failed_policy = all_failed_policy
        self.proposer_timeout_seconds = float(proposer_timeout_seconds or 3600.0)
        self.aggregator_timeout_seconds = float(aggregator_timeout_seconds or 3600.0)
        self.candidate_max_chars = int(candidate_max_chars or 0)
        self.shuffle_candidates = bool(shuffle_candidates)
        self.record_candidates = bool(record_candidates)
        self.proposer_tools = bool(proposer_tools)
        self.quorum_grace_seconds = max(0.0, float(quorum_grace_seconds or 0.0))
        self.selection_plan = dict(selection_plan or {})
        self._member_request_budget_bindings = dict(
            _member_request_budget_bindings or {}
        )

    def _member_request_budget_binding(
        self,
        member: EnsembleMemberConfig,
    ) -> _MemberRequestBudgetBinding | None:
        return self._member_request_budget_bindings.get(_member_budget_key(member))

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

    def project_message_count(
        self,
        messages: list[Message],
        config: ChatConfig | None = None,
        *,
        additional_messages: int = 0,
    ) -> ProviderMessageCountProjection:
        """Project every possible ensemble request and return the largest.

        Proposers receive the base conversation.  The aggregator receives the
        same conversation plus exactly one synthetic candidate-bundle message.
        A configured single-provider fallback is included because proposer
        failure can select it without changing the outer request.
        """

        if (
            not isinstance(additional_messages, int)
            or isinstance(additional_messages, bool)
            or additional_messages < 0
        ):
            raise ValueError("additional_messages must be a non-negative integer")

        projections: list[ProviderMessageCountProjection] = []

        def _require_projection(
            provider: LLMProvider,
            request_config: ChatConfig | None,
            *,
            synthetic_messages: int,
        ) -> None:
            projection = project_provider_message_count(
                provider,
                messages,
                request_config,
                additional_messages=synthetic_messages,
            )
            if projection is None:
                raise RuntimeError("ensemble member message-count projection unavailable")
            projections.append(projection)

        for member in self.proposers:
            member_config = _member_chat_config(config, member)
            _require_projection(
                _build_provider(member.provider_config),
                member_config,
                synthetic_messages=additional_messages,
            )

        if self.proposers:
            aggregator_config = _member_chat_config(config, self.aggregator)
            _require_projection(
                _build_provider(self.aggregator.provider_config),
                aggregator_config,
                synthetic_messages=additional_messages + 1,
            )

        if self.all_failed_policy == "fallback_single" and self.fallback_provider is not None:
            _require_projection(
                self.fallback_provider,
                config,
                synthetic_messages=additional_messages,
            )

        if not projections:
            raise RuntimeError("ensemble message-count projection unavailable")
        return max(projections, key=lambda projection: projection.actual_wire_messages)

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
        # Run proposers concurrently; stream their lifecycle deltas LIVE (so the
        # UI reveals each member the moment it starts/finishes) while still emitting
        # a keep-alive heartbeat during the wait, so a slow proposer batch never
        # looks stalled. Drain a progress queue: a real delta -> yield immediately,
        # a heartbeat-interval gap -> yield a keep-alive, the sentinel -> done.
        progress_queue: asyncio.Queue[EnsembleProgressEvent | None] = asyncio.Queue()

        async def _drain_proposers() -> list[_CandidateResult]:
            try:
                return await self._run_proposers(
                    messages, tools=tools, config=config, progress=progress_queue.put_nowait
                )
            finally:
                progress_queue.put_nowait(None)  # sentinel: proposers finished

        proposer_task = asyncio.create_task(_drain_proposers())
        try:
            while True:
                try:
                    progress_event = await asyncio.wait_for(
                        progress_queue.get(),
                        timeout=_ensemble_heartbeat_interval(),
                    )
                except TimeoutError:
                    yield ProviderHeartbeatEvent(
                        phase="ensemble_proposers_wait",
                        message=(
                            "Still waiting for "
                            f"{len(self.proposers)} proposer model(s)"
                        ),
                    )
                    continue
                if progress_event is None:
                    break
                yield progress_event
            candidates = await proposer_task
        finally:
            if not proposer_task.done():
                proposer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await proposer_task
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

        aggregator_cfg = _member_chat_config(
            config,
            self.aggregator,
            request_budget_binding=self._member_request_budget_binding(self.aggregator),
            role="aggregator",
        )
        if self.aggregator_timeout_seconds > 0:
            aggregator_cfg = aggregator_cfg.model_copy(
                update={"timeout": self.aggregator_timeout_seconds}
            )
        provider = _build_provider(self.aggregator.provider_config)
        proposer_rows = _candidate_usage_rows(candidates, profile=self.profile_name)
        candidate_order_seed = (
            random.SystemRandom().getrandbits(64) if self.shuffle_candidates else None
        )
        ordered_candidates = self._ordered_candidates(
            successful,
            candidate_order_seed=candidate_order_seed,
        )
        aggregator_messages = self._build_aggregator_messages(
            messages,
            successful,
            candidate_order_seed=candidate_order_seed,
        )
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
            candidate_order_seed=candidate_order_seed,
            candidate_display_order=[candidate.index for candidate in ordered_candidates],
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
        progress: Callable[[EnsembleProgressEvent], None] | None = None,
    ) -> list[_CandidateResult]:
        tasks: list[asyncio.Task[_CandidateResult]] = []
        task_meta: dict[
            asyncio.Task[_CandidateResult],
            tuple[int, int, EnsembleMemberConfig],
        ] = {}
        index = 0
        for member in self.proposers:
            k = max(1, int(member.k or 1))
            for sample_index in range(k):
                task = asyncio.create_task(
                    self._collect_candidate(
                        index=index,
                        sample_index=sample_index,
                        member=member,
                        messages=messages,
                        tools=tools if self.proposer_tools else None,
                        config=config,
                        progress=progress,
                    )
                )
                tasks.append(task)
                task_meta[task] = (index, sample_index, member)
                index += 1
        if not tasks:
            return []
        if (
            self.quorum_grace_seconds <= 0
            or self.min_successful_proposers >= len(tasks)
        ):
            return sorted(
                await asyncio.gather(*tasks),
                key=lambda result: (result.index, result.sample_index),
            )

        results: list[_CandidateResult] = []
        pending: set[asyncio.Task[_CandidateResult]] = set(tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    results.append(await task)
                if sum(1 for result in results if result.ok) >= self.min_successful_proposers:
                    break

            if pending:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=self.quorum_grace_seconds,
                )
                for task in done:
                    results.append(await task)

            if pending:
                for task in pending:
                    setattr(task, "_opensquilla_ensemble_cancel_code", "quorum_cancelled")
                    setattr(
                        task,
                        "_opensquilla_ensemble_cancel_message",
                        (
                            "proposer cancelled after "
                            f"{self.quorum_grace_seconds:g}s ensemble quorum grace"
                        ),
                    )
                    task.cancel()
                remaining = list(pending)
                cancelled_results = await asyncio.gather(*remaining, return_exceptions=True)
                for task, item in zip(remaining, cancelled_results, strict=True):
                    if isinstance(item, _CandidateResult):
                        results.append(item)
                    else:
                        index, sample_index, member = task_meta[task]
                        cfg = member.provider_config
                        results.append(
                            _CandidateResult(
                                index=index,
                                sample_index=sample_index,
                                label=member.label or f"proposer_{index + 1}",
                                provider=cfg.provider,
                                model=cfg.model,
                                error=str(item),
                                error_code=type(item).__name__,
                            )
                        )
            return sorted(results, key=lambda result: (result.index, result.sample_index))
        except BaseException:
            for task in pending:
                if not task.done():
                    task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            raise

    async def _collect_candidate(
        self,
        *,
        index: int,
        sample_index: int,
        member: EnsembleMemberConfig,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: ChatConfig | None,
        progress: Callable[[EnsembleProgressEvent], None] | None = None,
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
        if progress is not None:
            progress(
                EnsembleProgressEvent(
                    event_type="proposer_start",
                    proposer_index=index,
                    proposer_label=result.label,
                    proposer_model=result.model,
                    proposer_provider=result.provider,
                    sample_index=sample_index,
                )
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
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            code = str(getattr(current_task, "_opensquilla_ensemble_cancel_code", "") or "")
            if not code:
                raise
            result.error_code = code
            result.error = str(
                getattr(
                    current_task,
                    "_opensquilla_ensemble_cancel_message",
                    "proposer cancelled after ensemble quorum was reached",
                )
                or "proposer cancelled after ensemble quorum was reached"
            )
        except TimeoutError:
            result.error = f"proposer timed out after {self.proposer_timeout_seconds:g}s"
            result.error_code = "timeout"
        except Exception as exc:  # noqa: BLE001 - candidate failures are diagnostic data
            result.error = str(exc)
            result.error_code = type(exc).__name__
        finally:
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            if progress is not None:
                progress(
                    EnsembleProgressEvent(
                        event_type="proposer_finish",
                        proposer_index=index,
                        proposer_label=result.label,
                        proposer_model=result.model,
                        proposer_provider=result.provider,
                        sample_index=sample_index,
                        elapsed_ms=result.elapsed_ms,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        cost_usd=result.billed_cost,
                        error=result.error,
                    )
                )
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
        chat_cfg = _member_chat_config(
            config,
            member,
            request_budget_binding=self._member_request_budget_binding(member),
            role="proposer",
        )
        if self.proposer_timeout_seconds > 0:
            chat_cfg = chat_cfg.model_copy(update={"timeout": self.proposer_timeout_seconds})
        result.execution = _member_execution_trace(
            member,
            role="proposer",
            chat_config=chat_cfg,
            tools=tools,
            timeout_seconds=self.proposer_timeout_seconds,
            request_budget_binding=self._member_request_budget_binding(member),
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
                result.message_limit_proof = event.message_limit_proof
                break
        result.text = _truncate_text("".join(text_parts + tool_parts), self.candidate_max_chars)
        if not got_done and not result.error:
            result.error = "proposer stream ended before DoneEvent"
            result.error_code = "stream_incomplete"
        return result

    def _ordered_candidates(
        self,
        candidates: Sequence[_CandidateResult],
        *,
        candidate_order_seed: int | None,
    ) -> list[_CandidateResult]:
        ordered = list(candidates)
        if self.shuffle_candidates:
            seed = (
                candidate_order_seed
                if candidate_order_seed is not None
                else random.SystemRandom().getrandbits(64)
            )
            random.Random(seed).shuffle(ordered)
        return ordered

    def _build_aggregator_messages(
        self,
        messages: list[Message],
        candidates: Sequence[_CandidateResult],
        *,
        candidate_order_seed: int | None = None,
    ) -> list[Message]:
        ordered = self._ordered_candidates(
            candidates,
            candidate_order_seed=candidate_order_seed,
        )
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
        candidate_order_seed: int | None = None,
        candidate_display_order: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        selected = list(selected_candidates or [])
        trace = {
            "mode": "b5_fusion",
            "profile": self.profile_name,
            "selection_strategy": self.selection_plan.get("strategy", "router_dynamic"),
            "successful_proposers": successful_count,
            "total_candidates": len(candidates),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "shuffle_candidates": self.shuffle_candidates,
            "record_candidates": self.record_candidates,
            "proposer_tools": self.proposer_tools,
            "proposer_timeout_seconds": self.proposer_timeout_seconds,
            "aggregator_timeout_seconds": self.aggregator_timeout_seconds,
            "quorum_grace_seconds": self.quorum_grace_seconds,
            "content_max_chars": TRACE_CONTENT_MAX_CHARS,
            "final_request_role": final_request_role,
            "llm_request_count": len(candidates) + (1 if final_request_role else 0),
            "selected_candidate_count": len(selected),
            "selected_candidate_indexes": [candidate.index for candidate in selected],
            "candidate_order_seed": candidate_order_seed,
            "candidate_display_order": list(candidate_display_order or []),
            "candidates": [
                candidate.trace_row(
                    include_text=self.record_candidates,
                    content_max_chars=TRACE_CONTENT_MAX_CHARS,
                )
                for candidate in candidates
            ],
        }
        if self.selection_plan:
            trace["selection_plan"] = _json_safe(self.selection_plan)
        final_request: dict[str, Any] = {"role": final_request_role}
        if final_request_member is not None:
            final_request["execution"] = _member_execution_trace(
                final_request_member,
                role=final_request_role,
                chat_config=final_request_config,
                tools=final_request_tools,
                timeout_seconds=final_request_timeout_seconds,
                request_budget_binding=self._member_request_budget_binding(
                    final_request_member
                ),
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
        aggregator_started = time.monotonic()

        def aggregator_progress(
            event_type: str,
            *,
            usage: Mapping[str, Any] | None = None,
            error: str = "",
        ) -> EnsembleProgressEvent:
            row = usage or {}
            cfg = self.aggregator.provider_config
            return EnsembleProgressEvent(
                event_type=event_type,
                proposer_index=-1,
                proposer_label="aggregator",
                proposer_model=str(row.get("model") or cfg.model),
                proposer_provider=str(row.get("provider") or cfg.provider),
                sample_index=0,
                elapsed_ms=(
                    0
                    if event_type == "aggregator_start"
                    else int((time.monotonic() - aggregator_started) * 1000)
                ),
                input_tokens=int(row.get("input_tokens") or 0),
                output_tokens=int(row.get("output_tokens") or 0),
                cost_usd=float(row.get("billed_cost") or 0.0),
                error=error,
            )

        def ensemble_done(event: DoneEvent, *, aggregator_elapsed_ms: int) -> DoneEvent:
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
                    elapsed_ms=aggregator_elapsed_ms,
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

        yield aggregator_progress("aggregator_start")
        try:
            stream = provider.chat(messages, tools=tools, config=config)
            timeout_seconds = (
                self.aggregator_timeout_seconds
                if self.aggregator_timeout_seconds > 0
                else None
            )
            async for event in _stream_with_heartbeats(
                stream,
                phase="ensemble_aggregator_wait",
                message="Still waiting for ensemble aggregator response",
                timeout_seconds=timeout_seconds,
            ):
                if isinstance(event, DoneEvent):
                    aggregator_elapsed_ms = int(
                        (time.monotonic() - aggregator_started) * 1000
                    )
                    done_event = ensemble_done(
                        event,
                        aggregator_elapsed_ms=aggregator_elapsed_ms,
                    )
                    usage_rows = done_event.model_usage_breakdown or []
                    aggregator_usage = next(
                        (
                            row
                            for row in reversed(usage_rows)
                            if isinstance(row, Mapping) and row.get("role") == "aggregator"
                        ),
                        {},
                    )
                    yield aggregator_progress(
                        "aggregator_finish",
                        usage=aggregator_usage,
                    )
                    yield done_event
                    return
                elif isinstance(event, ErrorEvent):
                    yield aggregator_progress(
                        "aggregator_finish",
                        error=event.message,
                    )
                    yield event
                    return
                elif isinstance(event, TextDeltaEvent):
                    final_text_parts.append(event.text)
                    yield event
                else:
                    yield event
        except TimeoutError:
            error = ErrorEvent(
                message=(
                    "ensemble aggregator timed out after "
                    f"{self.aggregator_timeout_seconds:g}s"
                ),
                code="ensemble_aggregator_timeout",
            )
            yield aggregator_progress("aggregator_finish", error=error.message)
            yield error
            return
        except Exception as exc:  # noqa: BLE001 - provider boundary returns ErrorEvent
            error = ErrorEvent(
                message=f"ensemble aggregator failed: {exc}",
                code="ensemble_aggregator_error",
            )
            yield aggregator_progress("aggregator_finish", error=error.message)
            yield error
            return
        error = ErrorEvent(
            message="ensemble aggregator stream ended before DoneEvent",
            code="ensemble_aggregator_incomplete",
        )
        yield aggregator_progress("aggregator_finish", error=error.message)
        yield error

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
            message_limit_proof = _uniform_message_limit_proof(candidates)
            if message_limit_proof is not None:
                first_error = next(
                    (candidate.error for candidate in candidates if candidate.error),
                    reason,
                )
                yield ErrorEvent(
                    message=first_error,
                    code="400",
                    message_limit_proof=message_limit_proof,
                )
            else:
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
    request_budget_binding: _MemberRequestBudgetBinding | None = None,
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
            "effective_context_window_tokens": (
                request_budget_binding.context_window_tokens
                if request_budget_binding is not None
                else None
            ),
            "effective_context_window_source": (
                request_budget_binding.context_window_source
                if request_budget_binding is not None
                else "unbound"
            ),
            "effective_provider_request_max_chars": getattr(
                chat_config,
                "provider_request_max_chars",
                None,
            ),
            "provider_request_max_chars_source": _effective_request_cap_source(
                request_budget_binding,
                chat_config,
            ),
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


_STATIC_OPENROUTER_B5_PROFILE_NAME = "static_openrouter_b5"
_STATIC_OPENROUTER_B5_PROPOSER_MODELS = (
    "deepseek/deepseek-v4-pro",
    "z-ai/glm-5.2",
    "moonshotai/kimi-k2.7-code",
    "qwen/qwen3.7-max",
)
_STATIC_OPENROUTER_B5_AGGREGATOR_MODEL = "z-ai/glm-5.2"
_STATIC_TOKENRHYTHM_B5_PROFILE_NAME = "static_tokenrhythm_b5"
# The TokenRhythm mirror of the static OpenRouter B5 lineup: same aggregation
# shape and defaults, model ids in TokenRhythm's bare naming.
_STATIC_TOKENRHYTHM_B5_PROPOSER_MODELS = (
    "deepseek-v4-pro",
    "glm-5.2",
    "kimi-k2.7-code",
    "qwen3.7-max",
)
_STATIC_TOKENRHYTHM_B5_AGGREGATOR_MODEL = "glm-5.2"


@dataclass(frozen=True)
class StaticB5Profile:
    """One static B5 lineup: four fixed proposers + one aggregator on a
    single provider. All static profiles share the aggregation logic and
    the static-B5 defaults (quorum, timeouts, no shuffle)."""

    profile_name: str
    provider_id: str
    proposer_models: tuple[str, ...]
    aggregator_model: str


STATIC_B5_PROFILES: dict[str, StaticB5Profile] = {
    _STATIC_OPENROUTER_B5_PROFILE_NAME: StaticB5Profile(
        profile_name=_STATIC_OPENROUTER_B5_PROFILE_NAME,
        provider_id="openrouter",
        proposer_models=_STATIC_OPENROUTER_B5_PROPOSER_MODELS,
        aggregator_model=_STATIC_OPENROUTER_B5_AGGREGATOR_MODEL,
    ),
    _STATIC_TOKENRHYTHM_B5_PROFILE_NAME: StaticB5Profile(
        profile_name=_STATIC_TOKENRHYTHM_B5_PROFILE_NAME,
        provider_id="tokenrhythm",
        proposer_models=_STATIC_TOKENRHYTHM_B5_PROPOSER_MODELS,
        aggregator_model=_STATIC_TOKENRHYTHM_B5_AGGREGATOR_MODEL,
    ),
}


def static_b5_profile(selection_mode: str) -> StaticB5Profile | None:
    """Return the static B5 profile for a selection mode (None when dynamic)."""

    return STATIC_B5_PROFILES.get(str(selection_mode or ""))


CUSTOM_B5_SELECTION_MODE = "custom_b5"

# Advisory proposer roles for the explicit custom lineup, in display order.
# They label what each member contributes and ride the selection plan into
# the decision trace; "aggregator" is structural and handled separately.
CUSTOM_B5_PROPOSER_ROLES = ("primary", "contrast", "fast_check", "critic")


_LEGACY_OPENROUTER_MODEL_OPTIONS = (
    "deepseek/deepseek-v4-pro",
    "z-ai/glm-5.2",
    "qwen/qwen3.7-plus",
    "deepseek/deepseek-v4-flash",
    "qwen/qwen3.7-max",
    "moonshotai/kimi-k2.6",
    "moonshotai/kimi-k2.7-code",
    "minimax/minimax-m3",
)
_LEGACY_ENSEMBLE_MIN_SUCCESSFUL_PROPOSERS = 1
_LEGACY_ENSEMBLE_TIMEOUT_SECONDS = 3600.0
_LEGACY_ENSEMBLE_SHUFFLE_CANDIDATES = True
# Shared defaults for every static B5 profile (openrouter and tokenrhythm
# lineups run the same aggregation logic).
_STATIC_B5_DEFAULT_MIN_SUCCESSFUL_PROPOSERS = 3
_STATIC_B5_DEFAULT_PROPOSER_TIMEOUT_SECONDS = 300.0
_STATIC_B5_DEFAULT_AGGREGATOR_TIMEOUT_SECONDS = 480.0
_STATIC_B5_DEFAULT_SHUFFLE_CANDIDATES = False
_STATIC_B5_QUORUM_GRACE_SECONDS = 30.0


@dataclass(frozen=True)
class _EnsembleModelRef:
    provider: str
    model: str
    api_key_env: str = ""
    base_url: str = ""
    proxy: str = ""
    temperature: float | None = None
    max_tokens: int = 0
    thinking: str | None = "xhigh"
    k: int = 1


def _normalize_dynamic_tier(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in {"c0", "c1", "c2", "c3"}:
        return raw
    if raw.startswith("t") and raw[1:].isdigit():
        converted = f"c{int(raw[1:]) - 1}"
        if converted in {"c0", "c1", "c2", "c3"}:
            return converted
    return None


def _build_router_dynamic_members(
    *,
    config: Any,
    inherited_provider_config: ProviderConfig,
    turn_metadata: Mapping[str, Any] | None,
    ranking_inputs: Mapping[str, Any] | None = None,
) -> tuple[str, list[EnsembleMemberConfig], EnsembleMemberConfig, dict[str, Any]]:
    """Build members from the profile-driven Step2 ranking decision."""

    from .ranking_router import (
        TaskAnalysisResult,
        build_model_registry_snapshot,
        build_request_context,
        dynamic_output_token_budgets,
        fallback_task_profile,
        mock_user_profile,
        rank_models,
        ranking_config_snapshot,
    )

    metadata = dict(turn_metadata or {})
    extra = metadata.get("routing_extra")
    extra_map = extra if isinstance(extra, Mapping) else {}
    routed_tier = (
        _normalize_dynamic_tier(metadata.get("routed_tier"))
        or _normalize_dynamic_tier(extra_map.get("final_tier"))
        or _normalize_dynamic_tier(extra_map.get("base_tier"))
        or "c1"
    )
    try:
        routing_confidence = float(metadata.get("routing_confidence") or 0.0)
    except (TypeError, ValueError):
        routing_confidence = 0.0

    inputs = dict(ranking_inputs or {})
    ranking_config = inputs.get("ranking_config")
    if not isinstance(ranking_config, Mapping):
        ranking_config = ranking_config_snapshot()
    ensemble_cfg = getattr(config, "llm_ensemble", None)
    llm_cfg = getattr(config, "llm", None)
    configured_output_tokens = int(getattr(llm_cfg, "max_tokens", 0) or 0)
    candidate_max_chars = int(getattr(ensemble_cfg, "candidate_max_chars", 24_000) or 0)
    candidate_output_tokens, aggregator_output_tokens = dynamic_output_token_budgets(
        configured_output_tokens=configured_output_tokens,
        candidate_max_chars=candidate_max_chars,
        ranking_config=ranking_config,
    )
    request_context = inputs.get("request_context")
    if not isinstance(request_context, Mapping):
        request_context = build_request_context(
            message=str(metadata.get("router_dynamic_task_text") or ""),
            turn_metadata=metadata,
            attachments=[],
            candidate_output_tokens=candidate_output_tokens,
            aggregator_output_tokens=aggregator_output_tokens,
            ranking_config=ranking_config,
        )
    user_profile = inputs.get("user_profile")
    if not isinstance(user_profile, Mapping):
        user_profile = mock_user_profile(ranking_config)
    task_analysis = inputs.get("task_analysis")
    if not isinstance(task_analysis, TaskAnalysisResult):
        fallback_profile = fallback_task_profile(
            routed_tier=routed_tier,
            request_context=request_context,
            ranking_config=ranking_config,
        )
        task_analysis = TaskAnalysisResult(
            profile=fallback_profile,
            source="router_fallback",
            schema_valid=False,
            confidence=max(0.0, min(1.0, routing_confidence)),
            fallback_reason="task_analysis_not_supplied",
        )

    operator_candidates = [
        {
            "provider": str(getattr(candidate, "provider", "") or ""),
            "model": str(getattr(candidate, "model", "") or ""),
            "source": str(getattr(candidate, "source", "") or "custom"),
            "enabled": bool(getattr(candidate, "enabled", True)),
            "role": str(getattr(candidate, "role", "") or ""),
        }
        for candidate in getattr(ensemble_cfg, "candidates", []) or []
    ]
    legacy_model_options = list(getattr(ensemble_cfg, "model_options", []) or [])
    if tuple(legacy_model_options) == _LEGACY_OPENROUTER_MODEL_OPTIONS:
        legacy_model_options = []
    router_cfg = getattr(config, "squilla_router", None)
    router_tiers = getattr(router_cfg, "tiers", {}) or {}
    anchor_modalities = ["text"]
    try:
        anchor_member = _member_from_ref(
            _EnsembleModelRef(
                provider=inherited_provider_config.provider,
                model=inherited_provider_config.model,
                thinking=None,
            ),
            inherited=inherited_provider_config,
            label="router_anchor_capability_probe",
        )
        if _member_model_capabilities(anchor_member).supports_vision:
            anchor_modalities.append("image")
    except Exception:  # noqa: BLE001 - the availability pass records invalid anchors
        pass
    snapshot = build_model_registry_snapshot(
        inherited_provider=inherited_provider_config.provider,
        inherited_model=inherited_provider_config.model,
        routed_tier=routed_tier,
        anchor_modalities=anchor_modalities,
        operator_candidates=operator_candidates,
        legacy_model_options=legacy_model_options,
        router_tiers=router_tiers if isinstance(router_tiers, Mapping) else {},
        ranking_config=ranking_config,
    )

    # Credential presence is part of availability.  Keep every deployment in
    # the replay snapshot, but let chapter-6 hard filtering remove calls that
    # could never authenticate.
    for row in snapshot["models"]:
        facts = row.get("registry_facts")
        if not isinstance(facts, dict):
            continue
        provider_id = str(facts.get("provider") or "")
        model_id = str(facts.get("model_id") or "")
        try:
            member_config = _member_provider_config(
                _EnsembleModelRef(provider=provider_id, model=model_id),
                inherited_provider_config,
            )
            provider_spec = get_provider_spec(member_config.provider)
            credential_available = not provider_spec.requires_api_key() or bool(
                member_config.api_key.strip()
            )
        except Exception:  # noqa: BLE001 - invalid deployments remain traceable and filtered
            credential_available = False
        facts["credential_available"] = credential_available

    decision = rank_models(
        task_analysis=task_analysis,
        user_profile=user_profile,
        request_context=request_context,
        registry_snapshot=snapshot,
        routed_tier=routed_tier,
        routing_confidence=routing_confidence,
        ranking_config=ranking_config,
    )
    proposers = [
        _member_from_ref(
            _EnsembleModelRef(
                provider=model.provider,
                model=model.model_id,
                thinking=model.thinking,
            ),
            inherited=inherited_provider_config,
            label=f"proposer_{index + 1}",
        )
        for index, model in enumerate(decision.proposers)
    ]
    aggregator = _member_from_ref(
        _EnsembleModelRef(
            provider=decision.aggregator.provider,
            model=decision.aggregator.model_id,
            thinking=decision.aggregator.thinking,
        ),
        inherited=inherited_provider_config,
        label="aggregator",
    )
    profile_tier = f"c{decision.effective_tier - 1}"
    return f"router_dynamic/{profile_tier}", proposers, aggregator, decision.trace


def _static_b5_ref(provider_id: str, model: str) -> _EnsembleModelRef:
    return _EnsembleModelRef(provider=provider_id, model=model, thinking=None)


def _static_default_if_legacy(
    *,
    is_static: bool,
    value: float,
    legacy: float,
    static_default: float,
) -> float:
    if is_static and value == legacy:
        return static_default
    return value


def _build_static_b5_members(
    profile: StaticB5Profile,
    *,
    inherited_provider_config: ProviderConfig,
) -> tuple[str, list[EnsembleMemberConfig], EnsembleMemberConfig, dict[str, Any]]:
    proposers = [
        _member_from_ref(
            _static_b5_ref(profile.provider_id, model),
            inherited=inherited_provider_config,
            label=f"proposer_{index + 1}",
        )
        for index, model in enumerate(profile.proposer_models)
    ]
    aggregator = _member_from_ref(
        _static_b5_ref(profile.provider_id, profile.aggregator_model),
        inherited=inherited_provider_config,
        label="aggregator",
    )
    plan = {
        "strategy": profile.profile_name,
        "profile": profile.profile_name,
        "proposer_models": list(profile.proposer_models),
        "aggregator_model": profile.aggregator_model,
        "proposer_count": len(proposers),
    }
    return profile.profile_name, proposers, aggregator, plan


@dataclass(frozen=True)
class _CustomB5Candidate:
    """One enabled custom-lineup row, normalized from config."""

    provider: str
    model: str
    role: str


def _custom_b5_candidates(config: Any) -> list[_CustomB5Candidate]:
    ensemble_cfg = getattr(config, "llm_ensemble", None)
    rows: list[_CustomB5Candidate] = []
    seen: set[tuple[str, str]] = set()
    for entry in getattr(ensemble_cfg, "candidates", []) or []:
        if getattr(entry, "enabled", True) is False:
            continue
        provider = str(getattr(entry, "provider", "") or "").strip().lower()
        model = str(getattr(entry, "model", "") or "").strip()
        if not provider or not model:
            continue
        role = str(getattr(entry, "role", "") or "").strip().lower()
        identity = (provider, model)
        # The aggregator row may legitimately duplicate a proposer row
        # (same model both drafts and fuses); proposer rows dedupe.
        if role != "aggregator":
            if identity in seen:
                continue
            seen.add(identity)
        rows.append(_CustomB5Candidate(provider=provider, model=model, role=role))
    return rows


def _build_custom_b5_members(
    *,
    config: Any,
    inherited_provider_config: ProviderConfig,
) -> tuple[str, list[EnsembleMemberConfig], EnsembleMemberConfig, dict[str, Any]]:
    """Build the explicit user-authored lineup.

    Every enabled candidate without role='aggregator' runs as a proposer;
    the single 'aggregator' row fuses. When no aggregator row exists the
    lineup falls back to the currently routed model — the same model the
    user would have gotten without the ensemble — so a proposer-only config
    still runs instead of erroring at turn time.
    """
    rows = _custom_b5_candidates(config)
    proposer_rows = [row for row in rows if row.role != "aggregator"]
    aggregator_rows = [row for row in rows if row.role == "aggregator"]
    if not proposer_rows:
        raise ValueError("llm_ensemble custom_b5 lineup has no enabled proposers")
    proposers = [
        _member_from_ref(
            _EnsembleModelRef(provider=row.provider, model=row.model, thinking=None),
            inherited=inherited_provider_config,
            label=row.role or f"proposer_{index + 1}",
        )
        for index, row in enumerate(proposer_rows)
    ]
    if aggregator_rows:
        aggregator_row = aggregator_rows[0]
        aggregator_source = "candidate_role"
    else:
        aggregator_row = _CustomB5Candidate(
            provider=str(inherited_provider_config.provider or ""),
            model=str(inherited_provider_config.model or ""),
            role="aggregator",
        )
        aggregator_source = "inherited_model"
    aggregator = _member_from_ref(
        _EnsembleModelRef(
            provider=aggregator_row.provider,
            model=aggregator_row.model,
            thinking=None,
        ),
        inherited=inherited_provider_config,
        label="aggregator",
    )
    plan = {
        "strategy": CUSTOM_B5_SELECTION_MODE,
        "profile": CUSTOM_B5_SELECTION_MODE,
        "proposer_count": len(proposers),
        "proposers": [
            {"provider": row.provider, "model": row.model, "role": row.role or ""}
            for row in proposer_rows
        ],
        "aggregator": {
            "provider": aggregator_row.provider,
            "model": aggregator_row.model,
            "source": aggregator_source,
        },
    }
    return CUSTOM_B5_SELECTION_MODE, proposers, aggregator, plan


def custom_b5_lineup_ready(
    config: Any,
    inherited_provider_config: Any | None = None,
) -> tuple[bool, str]:
    """Pre-wrap readiness gate for the custom lineup.

    Returns (ready, reason). Mirrors the member key-resolution order of
    ``_member_provider_config`` per member — a member whose provider cannot
    resolve any API key would post the conversation upstream with an empty
    bearer token, so the wrap must be skipped, same as the static-B5 gate.
    ``inherited_provider_config`` should be the selector's current config
    when available (session-scoped provider overrides); it falls back to
    ``config.llm``.
    """
    inherited = (
        inherited_provider_config
        if inherited_provider_config is not None
        else getattr(config, "llm", None)
    )
    inherited_cfg = ProviderConfig(
        provider=str(getattr(inherited, "provider", "") or ""),
        model=str(getattr(inherited, "model", "") or ""),
        api_key=str(getattr(inherited, "api_key", "") or ""),
        base_url=str(getattr(inherited, "base_url", "") or ""),
        proxy=str(getattr(inherited, "proxy", "") or ""),
    )
    rows = _custom_b5_candidates(config)
    if not [row for row in rows if row.role != "aggregator"]:
        return False, "no_proposers"
    for row in rows:
        try:
            member = _member_provider_config(
                _EnsembleModelRef(provider=row.provider, model=row.model),
                inherited_cfg,
            )
        except Exception:
            return False, f"unknown_provider:{row.provider}"
        spec = get_provider_spec(member.provider)
        if spec.requires_api_key() and not member.api_key.strip():
            return False, f"missing_credential:{member.provider}"
    return True, ""


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


def static_b5_credential_available(
    config: Any,
    inherited_provider_config: Any,
    selection_mode: str = _STATIC_OPENROUTER_B5_PROFILE_NAME,
) -> bool:
    """Return True when every static-B5 member resolves a non-empty API key.

    Mirrors the ``_member_provider_config`` key-resolution order for the
    selected static B5 profile's members (all refs bound to the profile's
    provider with no member-level ``api_key_env``): the inherited provider
    key when the active provider matches the profile provider, then the
    registry env key for that provider (e.g. ``OPENROUTER_API_KEY``,
    ``TOKENRHYTHM_API_KEY``). A user whose active provider differs but whose
    environment carries the profile provider's env key is treated as opted
    in: the members resolve a key and the ensemble runs. Read-only and
    side-effect-free; ``config`` is accepted for call-site symmetry (static
    profiles have no config-level member overrides today). An unknown
    ``selection_mode`` returns False.
    """
    profile = static_b5_profile(selection_mode)
    if profile is None:
        return False
    if isinstance(inherited_provider_config, ProviderConfig):
        inherited = inherited_provider_config
    else:
        inherited = ProviderConfig(
            provider=str(getattr(inherited_provider_config, "provider", "") or ""),
            model=str(getattr(inherited_provider_config, "model", "") or ""),
            api_key=str(getattr(inherited_provider_config, "api_key", "") or ""),
            base_url=str(getattr(inherited_provider_config, "base_url", "") or ""),
            org_id=str(getattr(inherited_provider_config, "org_id", "") or ""),
            proxy=str(getattr(inherited_provider_config, "proxy", "") or ""),
            provider_routing=dict(
                getattr(inherited_provider_config, "provider_routing", {}) or {}
            ),
        )
    member_models = (*profile.proposer_models, profile.aggregator_model)
    return all(
        bool(
            _member_provider_config(
                _static_b5_ref(profile.provider_id, model), inherited
            ).api_key.strip()
        )
        for model in member_models
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


def _runtime_member_request_budget_bindings(
    *,
    config: Any,
    members: Sequence[EnsembleMemberConfig],
    model_catalog: Any | None,
    context_overflow_threshold: float,
) -> dict[tuple[str, str, str], _MemberRequestBudgetBinding]:
    """Resolve member windows only for the production runtime opt-in path."""

    llm_cfg = getattr(config, "llm", None)
    try:
        explicit_cap = int(
            getattr(llm_cfg, "provider_request_proof_max_chars", 0) or 0
        )
    except (TypeError, ValueError):
        explicit_cap = 0
    try:
        global_context_override = int(
            getattr(llm_cfg, "context_window_tokens", 0) or 0
        )
    except (TypeError, ValueError):
        global_context_override = 0

    bindings: dict[tuple[str, str, str], _MemberRequestBudgetBinding] = {}
    for member in members:
        key = _member_budget_key(member)
        if key in bindings:
            continue
        member_cfg = member.provider_config
        context_window: int | None = None
        context_source = "error" if model_catalog is None else "default"
        if model_catalog is None and global_context_override > 0:
            # The global override is independently authoritative; catalog
            # availability is only required for per-model/catalog resolution.
            context_window = global_context_override
            context_source = "config"
        elif model_catalog is not None:
            try:
                resolved_window, resolved_source = resolve_effective_context_window(
                    model_catalog,
                    member_cfg.model,
                    provider=member_cfg.provider,
                    global_override=global_context_override,
                )
                context_window = int(resolved_window)
                context_source = str(resolved_source or "default")
            except Exception:  # noqa: BLE001 - an unknown member keeps the outer cap
                context_window = None
                context_source = "error"

        reliable_context = (
            context_window is not None
            and context_window > 0
            and context_source in {"override", "config", "catalog"}
        )
        bindings[key] = _MemberRequestBudgetBinding(
            context_window_tokens=context_window,
            context_window_source=context_source,
            context_overflow_threshold=context_overflow_threshold,
            cap_source="explicit" if explicit_cap > 0 else "inherited",
            rederive=explicit_cap <= 0 and reliable_context,
        )
    return bindings


def build_ensemble_provider_from_config(
    *,
    config: Any,
    inherited_provider_config: ProviderConfig,
    fallback_provider: LLMProvider | None,
    turn_metadata: Mapping[str, Any] | None = None,
    ranking_inputs: Mapping[str, Any] | None = None,
    _enable_member_request_budget_rebinding: bool = False,
    _model_catalog: Any | None = None,
    _context_overflow_threshold: float = 0.85,
) -> EnsembleProvider:
    ensemble_cfg = getattr(config, "llm_ensemble", None)
    if ensemble_cfg is None:
        raise ValueError("config.llm_ensemble is required")
    selection_mode = str(getattr(ensemble_cfg, "selection_mode", "router_dynamic") or "")
    static_profile = static_b5_profile(selection_mode)
    if static_profile is not None:
        profile_name, proposers, aggregator, selection_plan = _build_static_b5_members(
            static_profile,
            inherited_provider_config=inherited_provider_config,
        )
    elif selection_mode == CUSTOM_B5_SELECTION_MODE:
        profile_name, proposers, aggregator, selection_plan = _build_custom_b5_members(
            config=config,
            inherited_provider_config=inherited_provider_config,
        )
    elif selection_mode == "router_dynamic":
        profile_name, proposers, aggregator, selection_plan = _build_router_dynamic_members(
            config=config,
            inherited_provider_config=inherited_provider_config,
            turn_metadata=turn_metadata,
            ranking_inputs=ranking_inputs,
        )
    else:
        raise ValueError(f"unknown llm_ensemble.selection_mode {selection_mode!r}")
    is_custom_b5 = selection_mode == CUSTOM_B5_SELECTION_MODE
    # Static and custom lineups share the fixed-lineup defaults family
    # (quorum replacement, 300/480s timeouts, no shuffle, quorum grace);
    # router_dynamic keeps the legacy defaults untouched.
    is_static_b5 = static_profile is not None or is_custom_b5
    configured_min_success = int(getattr(ensemble_cfg, "min_successful_proposers", 1) or 1)
    requested_min_success = configured_min_success
    if (
        is_static_b5
        and configured_min_success == _LEGACY_ENSEMBLE_MIN_SUCCESSFUL_PROPOSERS
    ):
        requested_min_success = (
            # Custom lineups size freely (2–6): quorum defaults to N-1, the
            # same "all but one" shape the 3-of-4 static default encodes.
            max(1, len(proposers) - 1)
            if is_custom_b5
            else _STATIC_B5_DEFAULT_MIN_SUCCESSFUL_PROPOSERS
        )
    elif (
        selection_mode == "router_dynamic"
        and configured_min_success == _LEGACY_ENSEMBLE_MIN_SUCCESSFUL_PROPOSERS
    ):
        requested_min_success = int(selection_plan.get("N_min") or 1)
    min_successful_proposers = min(requested_min_success, max(1, len(proposers)))
    configured_proposer_timeout_seconds = float(
        getattr(ensemble_cfg, "proposer_timeout_seconds", _LEGACY_ENSEMBLE_TIMEOUT_SECONDS)
    )
    proposer_timeout_seconds = _static_default_if_legacy(
        is_static=is_static_b5,
        value=configured_proposer_timeout_seconds,
        legacy=_LEGACY_ENSEMBLE_TIMEOUT_SECONDS,
        static_default=_STATIC_B5_DEFAULT_PROPOSER_TIMEOUT_SECONDS,
    )
    configured_aggregator_timeout_seconds = float(
        getattr(ensemble_cfg, "aggregator_timeout_seconds", _LEGACY_ENSEMBLE_TIMEOUT_SECONDS)
    )
    aggregator_timeout_seconds = _static_default_if_legacy(
        is_static=is_static_b5,
        value=configured_aggregator_timeout_seconds,
        legacy=_LEGACY_ENSEMBLE_TIMEOUT_SECONDS,
        static_default=_STATIC_B5_DEFAULT_AGGREGATOR_TIMEOUT_SECONDS,
    )
    configured_shuffle_candidates = bool(
        getattr(ensemble_cfg, "shuffle_candidates", _LEGACY_ENSEMBLE_SHUFFLE_CANDIDATES)
    )
    shuffle_candidates = configured_shuffle_candidates
    if (
        is_static_b5
        and configured_shuffle_candidates == _LEGACY_ENSEMBLE_SHUFFLE_CANDIDATES
    ):
        shuffle_candidates = _STATIC_B5_DEFAULT_SHUFFLE_CANDIDATES
    if selection_mode == "router_dynamic" and bool(
        (selection_plan.get("aggregator") or {}).get("requires_order_randomization")
    ):
        shuffle_candidates = True
    quorum_grace_seconds = _STATIC_B5_QUORUM_GRACE_SECONDS if is_static_b5 else 0.0
    selection_plan["configured_min_successful_proposers"] = configured_min_success
    selection_plan["effective_min_successful_proposers"] = min_successful_proposers
    selection_plan["configured_proposer_timeout_seconds"] = configured_proposer_timeout_seconds
    selection_plan["effective_proposer_timeout_seconds"] = proposer_timeout_seconds
    selection_plan["configured_aggregator_timeout_seconds"] = configured_aggregator_timeout_seconds
    selection_plan["effective_aggregator_timeout_seconds"] = aggregator_timeout_seconds
    selection_plan["configured_shuffle_candidates"] = configured_shuffle_candidates
    selection_plan["effective_shuffle_candidates"] = shuffle_candidates
    selection_plan["quorum_grace_seconds"] = quorum_grace_seconds
    request_budget_bindings = (
        _runtime_member_request_budget_bindings(
            config=config,
            members=[*proposers, aggregator],
            model_catalog=_model_catalog,
            context_overflow_threshold=_context_overflow_threshold,
        )
        if _enable_member_request_budget_rebinding
        else {}
    )
    return EnsembleProvider(
        profile_name=profile_name,
        proposers=proposers,
        aggregator=aggregator,
        fallback_provider=fallback_provider,
        min_successful_proposers=min_successful_proposers,
        all_failed_policy=getattr(ensemble_cfg, "all_failed_policy", "fallback_single"),
        proposer_timeout_seconds=proposer_timeout_seconds,
        aggregator_timeout_seconds=aggregator_timeout_seconds,
        candidate_max_chars=int(getattr(ensemble_cfg, "candidate_max_chars", 24_000) or 0),
        shuffle_candidates=shuffle_candidates,
        record_candidates=bool(getattr(ensemble_cfg, "record_candidates", False)),
        proposer_tools=bool(getattr(ensemble_cfg, "proposer_tools", False)),
        quorum_grace_seconds=quorum_grace_seconds,
        selection_plan=selection_plan,
        _member_request_budget_bindings=request_budget_bindings,
    )
