"""TurnRunner: shared agent orchestration layer.

Single convergence point for all entry points (Web UI, CLI, Channel).
Extracted from gateway/rpc_sessions.py:_run_agent_turn() closure.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextvars
import inspect
import json
import os
import platform
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, SupportsInt, TypeGuard, cast

import structlog

from opensquilla.artifacts import artifact_marker, artifact_payload
from opensquilla.attachment_refs import is_attachment_ref, read_attachment_ref_bytes
from opensquilla.bootstrap_types import BootstrapFileReport
from opensquilla.engine.agent import Agent, ToolHandler
from opensquilla.engine.cache_break_monitor import notify_compaction
from opensquilla.engine.pipeline import TurnContext
from opensquilla.engine.pricing import PriceEntry, lookup_price
from opensquilla.engine.tool_text_compat import strip_synthetic_tool_call_text
from opensquilla.engine.types import (
    AgentConfig,
    AgentEvent,
    ArtifactEvent,
    CompactionEvent,
    DoneEvent,
    ErrorEvent,
    TextDeltaEvent,
    ThinkingLevel,
    ToolResultEvent,
    ToolUseStartEvent,
    WarningEvent,
)
from opensquilla.memory.session_flush import SessionFlushService
from opensquilla.observability.decision_log import (
    DecisionEntry,
    PipelineStepRecord,
    SavingsTelemetry,
    compute_hashes,
    write_decision_entry,
)
from opensquilla.observability.prompt_report import PromptReport, build_prompt_report
from opensquilla.observability.trace import TraceContext, TraceEvent, write_trace_event
from opensquilla.observability.turn_call_log import TurnCallLogger, is_turn_call_log_enabled
from opensquilla.provider import (
    ErrorEvent as ProviderErrorEvent,
)
from opensquilla.provider import (
    LLMProvider,
    ProviderRecoveryAction,
    classify_provider_error,
    decide_recovery_action,
)
from opensquilla.safety import injection_guard, permission_matrix, sandbox, tool_tiers
from opensquilla.session.cost_rollup import (
    normalize_event_cost_source,
    rollup_cost_source,
)
from opensquilla.session.keys import (
    allows_private_memory_prompt_injection,
    canonicalize_session_key,
    is_subagent_key,
    normalize_agent_id,
)
from opensquilla.tools.types import CallerKind, ToolContext

# Stable user-facing envelope for LLM timeouts.
_LLM_TIMEOUT_ENVELOPE: dict[str, Any] = {
    "status": "error",
    "error_class": "llm_timeout",
    "user_message": "The model took too long to respond. Please try again.",
    "retry_allowed": True,
}
_DEFAULT_AGENT_RUNTIME_TIMEOUT_SECONDS: float = 48 * 60 * 60
_DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS: float = 120.0
_DEFAULT_LLM_TIMEOUT_SECONDS: float = _DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS
_ROUTER_PREV_ASSISTANT_MAX_CHARS: Final[int] = 8000
_ROUTER_HISTORY_USER_MAX_CHARS: Final[int] = 8000
_ROUTER_HISTORY_USER_MAX_TURNS: Final[int] = 4
_CONTEXT_SUMMARY_MARKER: Final[str] = "[Context Summary]"
_COMPACTION_SUMMARY_CONTEXT_HEADER: Final[str] = "[Compacted Session Summaries]"
_COMPACTION_SUMMARY_CONTEXT_MAX_CHARS: Final[int] = 16_000
_DEFAULT_PREFLIGHT_COMPACT_RATIO: Final[float] = 0.85
_COMPACTION_FAILURE_LIMIT: Final[int] = 3
_COMPACTION_CIRCUIT_COOLDOWN_SECONDS: Final[float] = 300.0
_T3_NOT_APPLICABLE: Final[str] = "not_applicable"
_T3_HANDLED: Final[str] = "handled"
_T3_FLUSH_FAILED: Final[str] = "flush_failed"
_T3_COMPACT_FAILED: Final[str] = "compact_failed"
_SAFE_FLUSH_OUTPUT_COVERAGE_STATUSES: Final[frozenset[str]] = frozenset(
    {"ok", "unverifiable"}
)
_SAFE_FLUSH_OBLIGATION_STATUSES: Final[frozenset[str]] = frozenset(
    {"ok", "backfilled", "unverifiable"}
)
_IMAGE_GENERATION_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {"image_generate"}
)


def _is_deepseek_model_id(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith("deepseek") or "/deepseek" in normalized


# Tools that are safe to run concurrently within a single LLM turn.
# Any tool name absent from this set is treated as mutex (serial dispatch).
# See docs/dev/tool-concurrency-spec.md for the dispatch contract.
_SAFE_TOOL_NAMES: frozenset[str] = frozenset({
    "agents_list",
    "git_diff",
    "git_log",
    "git_status",
    "glob_search",
    "grep_search",
    "image",
    "list_dir",
    "memory_get",
    "memory_search",
    "pdf",
    "read_file",
    "read_spreadsheet",
    "session_search",
    "session_status",
    "sessions_history",
    "sessions_list",
    "skill_list",
    "skill_view",
    "tts",
    "web_fetch",
})

# Per-call-chain owner tracking for session-lock re-entry detection.
# A ContextVar is copied into child asyncio Tasks created while a turn is
# running, which matters for stream wrappers such as heartbeat_stream. Treating
# the lock id as the ownership token lets those child tasks enter without
# self-deadlocking while unrelated tasks still see their own context values.
_SESSION_LOCK_OWNER: contextvars.ContextVar[dict[int, asyncio.Task[Any]]] = (
    contextvars.ContextVar("_session_lock_owner")
)


def _compute_route_input_savings_usd(
    max_price_per_m: float,
    routed_price_per_m: float,
    input_tokens: int,
) -> float:
    """49b7e08 squilla-router savings formula: input-price delta times input tokens."""
    return round(max(0.0, (max_price_per_m - routed_price_per_m) * input_tokens / 1_000_000), 6)


@dataclass(frozen=True)
class _SavingsBaseline:
    model: str = ""
    price: PriceEntry = field(default_factory=lambda: PriceEntry(0.0, 0.0))
    cost_usd: float = 0.0


@dataclass(frozen=True)
class _ComprehensiveTurnSavings:
    pct: float = 0.0
    usd: float = 0.0
    baseline_model: str = ""
    baseline_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0


@dataclass
class _CompactionFailureState:
    count: int = 0
    opened_at: float | None = None


def _non_negative_int(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, str | bytes | bytearray | SupportsInt):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _token_cost_usd(input_tokens: float, output_tokens: float, price: PriceEntry) -> float:
    return (
        max(0.0, float(input_tokens)) * price.input_per_m / 1_000_000
        + max(0.0, float(output_tokens)) * price.output_per_m / 1_000_000
    )


def _tier_value(tier: object, key: str, default: object = None) -> object:
    if isinstance(tier, Mapping):
        return tier.get(key, default)
    return getattr(tier, key, default)


def _iter_text_tier_models(tiers: object) -> list[str]:
    if not isinstance(tiers, Mapping):
        return []
    models: list[str] = []
    for tier in tiers.values():
        if bool(_tier_value(tier, "image_only", False)):
            continue
        model = str(_tier_value(tier, "model", "") or "").strip()
        if model:
            models.append(model)
    return models


def _select_savings_baseline_model(
    tiers: object,
    baseline_input_tokens: float,
    baseline_output_tokens: float,
) -> _SavingsBaseline:
    best = _SavingsBaseline(cost_usd=-1.0)
    for model in _iter_text_tier_models(tiers):
        price = lookup_price(model)
        cost_usd = _token_cost_usd(baseline_input_tokens, baseline_output_tokens, price)
        if cost_usd > best.cost_usd:
            best = _SavingsBaseline(model=model, price=price, cost_usd=cost_usd)
    if best.cost_usd < 0:
        return _SavingsBaseline()
    return best


def _short_output_savings_rate(metadata: Mapping[str, Any], estimated_pct: float) -> float:
    prompt_policy = str(metadata.get("prompt_policy") or "").strip().upper()
    active = prompt_policy == "P0" or bool(metadata.get("short_reply_active"))
    if not active:
        return 0.0
    try:
        rate = float(estimated_pct)
    except (TypeError, ValueError):
        return 0.0
    if rate <= 0.0 or rate >= 1.0:
        return 0.0
    return rate


def _restored_output_side_tokens(
    actual_output_side_tokens: int,
    metadata: Mapping[str, Any],
    estimated_output_savings_pct: float,
) -> float:
    rate = _short_output_savings_rate(metadata, estimated_output_savings_pct)
    if rate <= 0.0 or actual_output_side_tokens <= 0:
        return float(actual_output_side_tokens)
    return actual_output_side_tokens / (1.0 - rate)


def _compute_comprehensive_turn_savings(
    event: DoneEvent,
    metadata: Mapping[str, Any],
    tiers: object,
    routed_model: str,
    *,
    estimated_output_savings_pct: float = 0.03,
) -> _ComprehensiveTurnSavings:
    """Estimate per-turn savings from token counts and model prices only."""
    actual_input_tokens = _non_negative_int(event.input_tokens)
    actual_output_side_tokens = _non_negative_int(event.output_tokens) + _non_negative_int(
        event.reasoning_tokens
    )
    tool_tokens_saved = _non_negative_int(metadata.get("tool_compression_tokens_saved"))
    baseline_input_tokens = actual_input_tokens + tool_tokens_saved
    baseline_output_tokens = _restored_output_side_tokens(
        actual_output_side_tokens,
        metadata,
        estimated_output_savings_pct,
    )

    baseline = _select_savings_baseline_model(
        tiers,
        baseline_input_tokens,
        baseline_output_tokens,
    )
    routed_price = lookup_price(routed_model or event.model)
    actual_cost_usd = _token_cost_usd(
        actual_input_tokens,
        actual_output_side_tokens,
        routed_price,
    )

    if baseline.cost_usd <= 0.0:
        return _ComprehensiveTurnSavings(
            baseline_model=baseline.model,
            baseline_cost_usd=max(0.0, baseline.cost_usd),
            actual_cost_usd=actual_cost_usd,
        )

    savings_usd = round(max(0.0, baseline.cost_usd - actual_cost_usd), 6)
    savings_pct = 0.0
    if savings_usd > 0.0:
        savings_pct = round(max(0.0, min(99.9, (savings_usd / baseline.cost_usd) * 100)), 1)

    return _ComprehensiveTurnSavings(
        pct=savings_pct,
        usd=savings_usd,
        baseline_model=baseline.model,
        baseline_cost_usd=baseline.cost_usd,
        actual_cost_usd=actual_cost_usd,
    )


def _normalize_capture_kind(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(".", "_").replace(":", "_")


# Boot-path initialization of safety baseline (S-SAFETY). All four submodules
# are imported here so tool dispatch and ingress guards can consult them
# without late imports. See docs/architecture/module-contracts.md §safety.
#
# The tuple pins the imports to module scope so the linter does not drop them
# as "unused" — dispatch paths reach these modules via attribute lookup at
# call time, not through named references in this file. Keeping the reference
# explicit makes the load-time invariant legible to readers.
_SAFETY_MODULES: Final[tuple[Any, ...]] = (
    injection_guard,
    tool_tiers,
    permission_matrix,
    sandbox,
)

log = structlog.get_logger(__name__)


def _accepts_keyword_arg(callable_obj: Any, name: str) -> bool:
    """Return True when callable accepts `name` explicitly or via `**kwargs`."""
    params = inspect.signature(callable_obj).parameters
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _strip_context_summary_marker(content: str) -> str:
    """Return summary text from a legacy transcript summary marker."""
    if content.startswith(_CONTEXT_SUMMARY_MARKER):
        return content[len(_CONTEXT_SUMMARY_MARKER) :].lstrip("\r\n")
    return content


def _format_compaction_summary_context(summary_texts: list[str]) -> str | None:
    """Render durable summaries as request-scoped context, newest context preserved."""
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in summary_texts:
        text = raw.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    if not deduped:
        return None

    blocks = [f"[Summary {idx}]\n{text}" for idx, text in enumerate(deduped, start=1)]
    rendered = f"{_COMPACTION_SUMMARY_CONTEXT_HEADER}\n" + "\n\n".join(blocks)
    if len(rendered) <= _COMPACTION_SUMMARY_CONTEXT_MAX_CHARS:
        return rendered
    tail_budget = _COMPACTION_SUMMARY_CONTEXT_MAX_CHARS - len(
        _COMPACTION_SUMMARY_CONTEXT_HEADER
    ) - 80
    tail_budget = max(1000, tail_budget)
    return (
        f"{_COMPACTION_SUMMARY_CONTEXT_HEADER}\n"
        "[Earlier compaction summary context truncated to fit request budget.]\n"
        f"{rendered[-tail_budget:]}"
    )


def _prepend_request_context_prompt(
    existing_request_context: str | None,
    prepended_context: str | None,
) -> str | None:
    """Place session summary context before volatile per-turn context."""
    if not prepended_context or not prepended_context.strip():
        return existing_request_context
    if not existing_request_context or not existing_request_context.strip():
        return prepended_context.strip()
    return f"{prepended_context.strip()}\n\n{existing_request_context.strip()}"


_MAX_TOOL_RESULT_CHARS = 2000
_MAX_TOOL_RESULT_METADATA_VALUE_CHARS = 256
_TOOL_RESULT_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "provider",
        "query",
        "fallback_from",
        "error",
        "error_class",
        "error_kind",
    }
)
_SENTINELS: Final[frozenset[str]] = frozenset({"NO_REPLY", "HEARTBEAT_OK"})
_HEARTBEAT_ACK_TOKEN: Final[str] = "HEARTBEAT_OK"
_THINKING_ALIASES: Final[dict[str, str]] = {
    "x-high": "xhigh",
    "x_high": "xhigh",
    "extra-high": "xhigh",
    "extra_high": "xhigh",
    "extra high": "xhigh",
    "highest": "high",
    "max": "high",
    "on": "low",
    "true": "medium",
    "none": "off",
    "false": "off",
}


def _truncate_json_string(value: str, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    if max_chars == 1:
        return "…"
    return value[: max_chars - 1] + "…"


def _compact_json_for_tool_result_preview(
    value: Any,
    *,
    max_string_chars: int,
    max_list_items: int,
) -> Any:
    """Return a JSON-serializable preview that keeps structure bounded."""

    if isinstance(value, str):
        return _truncate_json_string(value, max_string_chars)
    if isinstance(value, list):
        return [
            _compact_json_for_tool_result_preview(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for item in value[:max_list_items]
        ]
    if isinstance(value, dict):
        return {
            str(key): _compact_json_for_tool_result_preview(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for key, item in value.items()
        }
    return value


def _bounded_tool_result_metadata(
    parsed: Mapping[str, Any],
) -> dict[str, str | int | float | bool | None]:
    """Return bounded scalar metadata safe to store beside capped result text."""

    metadata: dict[str, str | int | float | bool | None] = {}
    for key in _TOOL_RESULT_METADATA_KEYS:
        if key not in parsed:
            continue
        value = parsed[key]
        if isinstance(value, str):
            metadata[key] = _truncate_json_string(
                value,
                _MAX_TOOL_RESULT_METADATA_VALUE_CHARS,
            )
        elif isinstance(value, int | float | bool) or value is None:
            metadata[key] = value
    return metadata


def _json_tool_result_preview(parsed: Any, original_chars: int, max_chars: int) -> str:
    """Build a bounded, valid-JSON preview for persisted transcript display.

    Tool results are often structured JSON consumed by the web UI. A plain
    prefix slice can turn them into invalid JSON and hide top-level metadata
    such as the active search provider. This helper prefers a valid JSON
    preview with explicit truncation metadata while keeping the historical
    transcript size cap.
    """

    if isinstance(parsed, dict):
        base: dict[str, Any] = dict(parsed)
    else:
        base = {"value": parsed}
    base["result_truncated"] = True
    base["result_original_chars"] = original_chars

    for max_list_items in (5, 3, 2, 1, 0):
        for max_string_chars in (512, 256, 128, 64, 32, 16):
            compacted = _compact_json_for_tool_result_preview(
                base,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            rendered = json.dumps(compacted, ensure_ascii=False, indent=2)
            if len(rendered) <= max_chars:
                return rendered

    fallback: dict[str, Any] = {
        "result_truncated": True,
        "result_original_chars": original_chars,
    }
    if isinstance(parsed, dict):
        fallback.update(_bounded_tool_result_metadata(parsed))
    rendered = json.dumps(fallback, ensure_ascii=False, indent=2)
    if len(rendered) <= max_chars:
        return rendered
    return json.dumps({"result_truncated": True}, ensure_ascii=False)


def _persisted_tool_result_segment(
    event: ToolResultEvent,
    *,
    max_chars: int = _MAX_TOOL_RESULT_CHARS,
) -> dict[str, Any]:
    """Create the transcript `tool_result` segment for a streamed event."""

    result = event.result
    segment: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": event.tool_use_id,
        "name": event.tool_name,
        "result": result,
        "is_error": event.is_error,
    }
    if len(result) <= max_chars:
        return segment

    segment["result_truncated"] = True
    segment["result_original_chars"] = len(result)
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        segment["result"] = result[:max_chars]
        return segment

    if isinstance(parsed, dict):
        segment.update(_bounded_tool_result_metadata(parsed))
    segment["result"] = _json_tool_result_preview(parsed, len(result), max_chars)
    return segment

_SUBAGENT_TASK_PROTOCOL: Final[str] = (
    "You are a spawned subagent. Execute only the delegated task and return "
    "a compact result for the parent agent to use. Prefer a direct answer; "
    "call tools only when the task explicitly requires external state, files, "
    "network data, or tool output. If the delegated task asks you to reply with "
    "an exact phrase, only reply, output a sentinel token, or avoid explanation, "
    "Do not call tools and return exactly that requested text. Do not treat "
    "uppercase sentinel-like strings as shell commands, filenames, or config keys."
)


def _should_use_selector_fallback(provider_name: str, event: ProviderErrorEvent) -> bool:
    kind = classify_provider_error(
        provider_name=provider_name,
        status_code=int(event.code) if str(event.code).isdigit() else None,
        raw_code=event.code,
        message=event.message,
    )
    return decide_recovery_action(kind) in {
        ProviderRecoveryAction.FALLBACK_PROVIDER,
        ProviderRecoveryAction.RETRY_THEN_FALLBACK,
    }


def _normalize_heartbeat_text(
    text: str,
    *,
    run_kind: str,
    heartbeat_ack_max_chars: int,
) -> str:
    stripped = text.strip()
    if stripped in _SENTINELS:
        log.debug("turn_runner.sentinel_suppressed", sentinel=stripped)
        return ""
    if run_kind != "heartbeat":
        return text

    def _suppressed(payload: str) -> bool:
        return len(payload.strip()) <= heartbeat_ack_max_chars

    if stripped.startswith(_HEARTBEAT_ACK_TOKEN):
        remainder = stripped[len(_HEARTBEAT_ACK_TOKEN) :].strip()
        if _suppressed(remainder):
            return ""

    if stripped.endswith(_HEARTBEAT_ACK_TOKEN):
        remainder = stripped[: -len(_HEARTBEAT_ACK_TOKEN)].strip()
        if _suppressed(remainder):
            return ""

    return text


def _drop_unpaired_tool_use_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paired_ids = {
        segment.get("tool_use_id")
        for segment in segments
        if isinstance(segment, dict) and segment.get("type") == "tool_result"
    }
    return [
        segment
        for segment in segments
        if not (
            isinstance(segment, dict)
            and segment.get("type") == "tool_use"
            and segment.get("tool_use_id") not in paired_ids
        )
    ]


class _SelectorFallbackProvider:
    """Provider wrapper that switches to selector fallback on pre-content errors."""

    def __init__(self, provider: Any, selector: Any) -> None:
        self._provider = provider
        self._selector = selector

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "provider_name", "")

    def fallback_after_invalid_response(self, reason: str) -> bool:
        try:
            self._provider = self._selector.next_fallback_after_failure(RuntimeError(reason))
        except Exception:
            return False
        return True

    def chat(
        self,
        messages: list[Any],
        tools: Any = None,
        config: Any = None,
    ) -> AsyncIterator[Any]:
        return self._chat(messages, tools=tools, config=config)

    async def _chat(
        self,
        messages: list[Any],
        tools: Any = None,
        config: Any = None,
    ) -> AsyncIterator[Any]:
        emitted_user_visible_content = False
        pre_text_buffer: list[Any] = []

        def drain_pre_text_buffer() -> list[Any]:
            drained = list(pre_text_buffer)
            pre_text_buffer.clear()
            return drained

        async for event in self._provider.chat(messages, tools=tools, config=config):
            if emitted_user_visible_content:
                yield event
                continue

            if (
                isinstance(event, ProviderErrorEvent)
                and _should_use_selector_fallback(self.provider_name, event)
            ):
                try:
                    self._provider = self._selector.next_fallback_after_failure(
                        RuntimeError(event.message)
                    )
                except Exception:
                    for buffered_event in drain_pre_text_buffer():
                        yield buffered_event
                    yield event
                    return
                async for fallback_event in self._provider.chat(
                    messages,
                    tools=tools,
                    config=config,
                ):
                    yield fallback_event
                return

            if _is_non_empty_provider_text_delta(event):
                for buffered_event in drain_pre_text_buffer():
                    yield buffered_event
                emitted_user_visible_content = True
                yield event
                continue

            if getattr(event, "kind", "") == "done":
                for buffered_event in drain_pre_text_buffer():
                    yield buffered_event
                yield event
                continue

            if isinstance(event, ProviderErrorEvent):
                for buffered_event in drain_pre_text_buffer():
                    yield buffered_event
                yield event
                continue

            pre_text_buffer.append(event)

        for buffered_event in drain_pre_text_buffer():
            yield buffered_event

    async def list_models(self) -> list[Any]:
        return list(await self._provider.list_models())


def _is_non_empty_provider_text_delta(event: Any) -> bool:
    """Return True only once a provider event carries user-visible text."""
    return getattr(event, "kind", "") == "text_delta" and bool(getattr(event, "text", ""))


@dataclass
class MemorySnapshot:
    """Frozen memory content for stable system prompt prefixes."""

    memory_md: str | None = None
    daily_notes: dict[str, str] = field(default_factory=dict)


@dataclass
class BootstrapSnapshot:
    """Frozen workspace bootstrap files for stable per-session prompt prefixes."""

    workspace_files: dict[str, str] = field(default_factory=dict)
    report: list[BootstrapFileReport] = field(default_factory=list)


_MAX_ATTACHMENT_COUNT = 10
_MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
_MAX_TEXT_ATTACHMENT_BYTES = 2 * 1000 * 1000
_MAX_STAGED_ATTACHMENT_BYTES = 30 * 1024 * 1024
_PDF_ATTACHMENT_TEXT_LIMIT = 200_000
_TEXT_ATTACHMENT_TEXT_LIMIT = 200_000

# Image, PDF, and text-family allow-list. Mirrors
# gateway.rpc_sessions._ALLOWED_MEDIA_TYPES; intentionally duplicated to avoid
# an engine -> gateway import cycle. Provider-facing conversion is more
# conservative: images become image blocks; text-family and PDFs become text
# file-context blocks after local decoding/extraction.
_ALLOWED_ENGINE_MEDIA_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/html",
        "text/csv",
        "application/json",
    }
)
_ENGINE_TEXT_FAMILY_MIMES: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/html",
        "text/csv",
        "application/json",
    }
)

_XML_ATTR_ESCAPES = {
    "<": "&lt;",
    ">": "&gt;",
    "&": "&amp;",
    '"': "&quot;",
    "'": "&apos;",
}


def _xml_escape_attr(value: str) -> str:
    """XML-escape characters that would break an HTML/XML attribute value.

    Matches the file-context wrapper escaping contract.
    """

    return "".join(_XML_ATTR_ESCAPES.get(ch, ch) for ch in value)


def _sanitize_attachment_filename(value: Any, fallback: str = "attachment") -> str:
    """Strip newlines/tabs and trim; fall back if the result is empty."""

    if not isinstance(value, str):
        return fallback
    cleaned = value.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    return cleaned or fallback


def _escape_file_block_content(value: str) -> str:
    """Escape literal ``</file>`` and ``<file `` substrings inside payloads.

    Without this, a user-supplied CSV / markdown body containing the wrapper
    sentinel could be mis-parsed by the model as the boundary of a *different*
    attachment, enabling prompt-injection. The replacement is XML-entity
    style so the payload remains human-readable in the prompt.
    """

    import re as _re

    # Order matters: do the close-tag pattern first so we don't double-escape
    # the prefix it shares with the open-tag pattern.
    out = _re.sub(r"<\s*/\s*file\s*>", "&lt;/file&gt;", value, flags=_re.IGNORECASE)
    out = _re.sub(r"<\s*file\b", "&lt;file", out, flags=_re.IGNORECASE)
    return out


def _render_file_context_block(filename: str, mime: str, content: str) -> str:
    """Render a ``<file name="…" mime="…">\\n<content>\\n</file>`` envelope."""

    safe_name = _xml_escape_attr(_sanitize_attachment_filename(filename))
    safe_mime = _xml_escape_attr(mime)
    safe_content = _escape_file_block_content(content)
    return f'<file name="{safe_name}" mime="{safe_mime}">\n{safe_content}\n</file>'


def _truncate_attachment_text(text: str, *, limit: int = _PDF_ATTACHMENT_TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[attachment text truncated: {len(text)} chars total]"


def _extract_pdf_attachment_text(raw_bytes: bytes, filename: str) -> str:
    """Extract text from a PDF attachment before it reaches any provider.

    PDFs are converted into plain text context so provider-specific document
    block handling cannot silently drop files that an adapter does not know how
    to encode.
    """

    import io

    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ValueError("PDF text extraction requires pdfplumber") from exc

    try:
        page_texts: list[str] = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as doc:
            for index, page in enumerate(doc.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    page_texts.append(f"--- Page {index} ---\n{page_text}")
    except Exception as exc:  # noqa: BLE001 - pdfplumber raises several parser errors
        raise ValueError(f"PDF attachment {filename!r} could not be read: {exc}") from exc

    extracted = "\n\n".join(page_texts).strip()
    if not extracted:
        raise ValueError(f"PDF attachment {filename!r} has no extractable text")
    return _truncate_attachment_text(extracted)

# Strong past-tense / perfect-aspect phrases that signal the model is claiming
# to have produced an image. Only checked when ``image_generate`` is available
# and was not invoked. Future-tense ("I'll draw…", "给你画…") is intentionally
# excluded — those express intent and are often followed by an actual tool call
# in the same or next iteration; flagging them is noisy.
_IMAGE_CLAIM_PATTERNS = (
    # Chinese: perfect aspect / demonstrative past
    "已生成图片",
    "生成了图片",
    "画了一张",
    "这是生成的图",
    "已为您生成",
    "已经画好",
    "绘制好了",
    # English: past / perfect tense
    "generated an image",
    "i have created the image",
    "i've created the image",
    "i have generated the image",
    "i've generated the image",
    # Specific "here is/here's the image I …" — require the "I" pronoun to
    # avoid matching "here's the image you uploaded".
    "here is the image i",
    "here's the image i",
    # Markdown embed of a fake generated asset.
    "![generated",
)


def _claims_image_without_tool_use(
    final_text: str,
    tool_defs: list[Any],
    turn_segments: list[dict],
) -> bool:
    """Detect: model claimed image generation but never called image_generate.

    Returns True only when the tool was *available* (so we know the model had
    the option) and *not called* in this turn yet the final text matches a claim
    pattern. Used to surface a non-persistent UI warning; never writes to transcript.
    """
    tool_names = {getattr(td, "name", "") for td in tool_defs}
    if "image_generate" not in tool_names:
        return False
    had_image_call = any(
        isinstance(seg, dict)
        and seg.get("type") == "tool_use"
        and seg.get("name") == "image_generate"
        for seg in turn_segments
    )
    if had_image_call:
        return False
    if not final_text:
        return False
    lowered = final_text.lower()
    return any(p.lower() in lowered for p in _IMAGE_CLAIM_PATTERNS)


class TurnRunner:
    """Orchestrates a complete agent turn: provider → tools → prompt → pipeline → Agent.

    Owns per-session locking and transcript persistence.
    All entry points (Web RPC, CLI, Channel) converge here.

    Lock ordering invariant:
        TurnRunner no longer owns an internal lock dict.
        Per-session locks are supplied by an external ``session_lock_provider``
        (``Callable[[str], asyncio.Lock]``) injected at construction time.

        Gateway path: provider = ``TaskRuntime._get_session_lock_for_turn``,
        so TaskRuntime and TurnRunner share a single ``asyncio.Lock`` per
        session_key.  ``TaskRuntime._execute()`` holds the lock before calling
        the turn handler; ``TurnRunner.run()`` detects this and skips re-acquire
        (lock.locked() == True → bypass ``async with lock``).

        CLI / standalone path: provider = ``_standalone_lock_provider`` from
        ``build_turn_runner_from_services``, which maintains its own dict.

        The two-level OUTER→INNER hierarchy from Stories #5/#7a is eliminated.
        No reverse-acquire risk remains since there is only one lock per session.
    """

    def __init__(
        self,
        provider_selector: Any,
        tool_registry: Any | None = None,
        session_manager: Any | None = None,
        skill_loader: Any | None = None,
        usage_tracker: Any | None = None,
        config: Any | None = None,
        memory_sync_managers: dict[str, Any] | None = None,
        model_catalog: Any | None = None,
        memory_retrievers: dict[str, Any] | None = None,
        turn_capture_services: dict[str, Any] | None = None,
        session_flush_service: SessionFlushService | None = None,
        session_lock_provider: Callable[[str], asyncio.Lock] | None = None,
    ) -> None:
        self._provider_selector = provider_selector
        self._tool_registry = tool_registry
        self._session_manager = session_manager
        self._skill_loader = skill_loader
        self._usage_tracker = usage_tracker
        self._config = config
        self._memory_sync_managers = memory_sync_managers
        self._model_catalog = model_catalog
        self._memory_retrievers = memory_retrievers
        self._turn_capture_services = turn_capture_services
        self._session_flush_service = session_flush_service
        # Per-session lock provider.
        # Gateway path: task_runtime._get_session_lock_for_turn (wired in boot.py).
        # CLI/standalone path: _standalone_lock_provider from build_turn_runner_from_services.
        # Test/direct-construction path: fallback dict created here inside a closure.
        # TurnRunner no longer owns a named per-session lock dict as an instance attribute.
        # The lock dict lives entirely in the provider closure.
        if session_lock_provider is None:
            _fallback_locks: dict[str, asyncio.Lock] = {}

            def _fallback_provider(key: str) -> asyncio.Lock:
                return _fallback_locks.setdefault(key, asyncio.Lock())

            session_lock_provider = _fallback_provider
        self._session_lock_provider = session_lock_provider
        # Frozen memory snapshots keyed by (agent_id, session_key).
        # Captured at session start, refreshed on write/compaction.
        self._memory_snapshots: dict[tuple[str, str], MemorySnapshot] = {}
        # Frozen bootstrap snapshots keyed by (agent_id, session_key, context_mode).
        # Captured on first prompt assembly so USER.md/AGENTS.md edits do not
        # churn the cacheable prefix mid-session.
        self._bootstrap_snapshots: dict[tuple[str, str, str], BootstrapSnapshot] = {}
        self._compaction_failures: dict[str, _CompactionFailureState] = {}

    def refresh_memory_snapshot(self, agent_id: str) -> None:
        """Refresh frozen snapshots for all sessions of the given agent.

        Called by the on_memory_write callback when agent writes to
        MEMORY.md or daily notes via memory_save.
        """
        ws = self._resolve_memory_source_dir(agent_id)
        new_snap = MemorySnapshot(
            memory_md=self._load_memory_md(ws),
            daily_notes=self._load_daily_notes(ws),
        )
        for key in list(self._memory_snapshots):
            if key[0] == agent_id:
                self._memory_snapshots[key] = new_snap

    def _handle_memory_source_write(self, agent_id: str, path: str) -> None:
        """Refresh memory index/snapshots after a source Markdown file write."""
        sync_manager = (
            self._memory_sync_managers.get(agent_id) if self._memory_sync_managers else None
        )
        mark_dirty = getattr(sync_manager, "mark_dirty", None)
        if callable(mark_dirty):
            mark_dirty()
        self.refresh_memory_snapshot(agent_id)

    def _handle_bootstrap_source_write(self, agent_id: str, path: str) -> None:
        """Drop frozen bootstrap snapshots after a bootstrap workspace file write."""
        for key in list(self._bootstrap_snapshots):
            if key[0] == agent_id:
                del self._bootstrap_snapshots[key]

    def _with_runtime_write_callbacks(
        self, tool_context: ToolContext, agent_id: str
    ) -> ToolContext:
        """Attach runtime snapshot refresh callbacks without discarding caller hooks."""
        if not tool_context.memory_source_dir:
            try:
                tool_context = replace(
                    tool_context,
                    memory_source_dir=str(self._resolve_memory_source_dir(agent_id)),
                )
            except Exception:  # noqa: BLE001 - memory path should not block tool setup
                pass

        previous_memory_write = tool_context.on_memory_source_write
        if previous_memory_write is None:
            tool_context = replace(
                tool_context,
                on_memory_source_write=self._handle_memory_source_write,
            )
        else:

            def _on_memory_source_write(agent_id: str, path: str) -> None:
                previous_memory_write(agent_id, path)
                self._handle_memory_source_write(agent_id, path)

            tool_context = replace(
                tool_context,
                on_memory_source_write=_on_memory_source_write,
            )

        previous_bootstrap_write = tool_context.on_bootstrap_source_write
        if previous_bootstrap_write is None:
            return replace(
                tool_context,
                on_bootstrap_source_write=self._handle_bootstrap_source_write,
            )

        def _on_bootstrap_source_write(agent_id: str, path: str) -> None:
            previous_bootstrap_write(agent_id, path)
            self._handle_bootstrap_source_write(agent_id, path)

        return replace(
            tool_context,
            on_bootstrap_source_write=_on_bootstrap_source_write,
        )

    async def _with_artifact_context(
        self,
        tool_context: ToolContext,
        session_key: str,
    ) -> ToolContext:
        attachments_cfg = getattr(self._config, "attachments", None)
        media_root = self._attachment_media_root()
        session_id = await self._resolve_session_id_for_log(session_key)
        if not session_id:
            session_id = session_key.split(":")[-1] or session_key
        return replace(
            tool_context,
            artifact_media_root=str(media_root),
            artifact_session_id=session_id,
            artifact_max_bytes=getattr(attachments_cfg, "artifact_max_bytes", None),
            artifact_disk_budget_bytes=getattr(
                attachments_cfg,
                "artifact_disk_budget_bytes",
                None,
            ),
        )

    async def _capture_turn_memory(
        self,
        *,
        agent_id: str,
        session_key: str,
        runtime_message: str,
        final_text: str,
        input_mode: str,
        tool_context: ToolContext | None,
        input_provenance: dict[str, Any] | None,
        run_kind: str = "default",
        no_memory_capture: bool = False,
    ) -> None:
        memory_cfg = getattr(self._config, "memory", None)
        if not self._turn_memory_capture_allowed(
            no_memory_capture=no_memory_capture,
            input_mode=input_mode,
            run_kind=run_kind,
            input_provenance=input_provenance,
            memory_config=memory_cfg,
        ):
            return
        if self._session_manager is None or not self._turn_capture_services:
            return
        capture_service = self._turn_capture_services.get(
            agent_id
        ) or self._turn_capture_services.get("main")
        if capture_service is None:
            return
        session = await self._session_manager.get_session(session_key)
        if session is None:
            return
        captured_path = await capture_service.capture_turn(
            session_key=session_key,
            session_id=getattr(session, "session_id", ""),
            user_text=runtime_message,
            assistant_text=final_text,
            source=self._build_turn_call_source(
                tool_context,
                input_provenance,
                run_kind=run_kind,
            ),
            captured_at=datetime.now(tz=UTC),
            index_immediately=False,
            no_memory_capture=no_memory_capture,
        )
        if (
            captured_path
            and self._memory_sync_managers
            and bool(getattr(memory_cfg, "index_captured_turns", False))
        ):
            sync_manager = self._memory_sync_managers.get(
                agent_id
            ) or self._memory_sync_managers.get("main")
            mark_dirty = getattr(sync_manager, "mark_dirty", None)
            if callable(mark_dirty):
                mark_dirty()

    @staticmethod
    def _capture_filter_matches(value: str | None, excluded_values: Any) -> bool:
        if not value:
            return False
        if isinstance(excluded_values, str):
            raw_patterns = [excluded_values]
        else:
            raw_patterns = list(excluded_values or [])
        normalized_value = _normalize_capture_kind(value)
        value_parts = {part for part in normalized_value.split("_") if part}
        for pattern in raw_patterns:
            if pattern is None:
                continue
            normalized_pattern = _normalize_capture_kind(str(pattern))
            if not normalized_pattern:
                continue
            if normalized_value == normalized_pattern or normalized_pattern in value_parts:
                return True
        return False

    @staticmethod
    def _input_provenance_kind(input_provenance: dict[str, Any] | None) -> str | None:
        if not isinstance(input_provenance, dict):
            return None
        kind = input_provenance.get("kind")
        return str(kind) if kind is not None and str(kind) else None

    @classmethod
    def _turn_memory_capture_allowed(
        cls,
        *,
        no_memory_capture: bool,
        input_mode: str,
        run_kind: str | None,
        input_provenance: dict[str, Any] | None,
        memory_config: Any | None,
    ) -> bool:
        if no_memory_capture or input_mode != "user":
            return False
        if memory_config is None:
            return True
        if cls._capture_filter_matches(
            run_kind,
            getattr(memory_config, "capture_excluded_run_kinds", []),
        ):
            return False
        provenance_kind = cls._input_provenance_kind(input_provenance)
        if cls._capture_filter_matches(
            provenance_kind,
            getattr(memory_config, "capture_excluded_provenance_kinds", []),
        ):
            return False
        return True

    def _get_session_lock(self, session_key: str) -> asyncio.Lock:
        """Return the per-session lock for *session_key* from the external provider.

        TurnRunner no longer owns an internal lock dict.  All per-session
        locks are managed by the provider supplied at construction
        (TaskRuntime._get_session_lock_for_turn for the gateway path, or the
        standalone provider for CLI paths).

        External callers (rpc_sessions.py, channel_dispatch.py) that call this
        directly will now receive the same lock object as
        TaskRuntime._execute(), ensuring they serialize against the unified lock.
        """
        return self._session_lock_provider(session_key)

    def get_session_lock(self, session_key: str) -> asyncio.Lock:
        """Public lock-provider seam for RPC/session services."""
        return self._get_session_lock(session_key)

    def set_session_lock_provider(self, provider: Callable[[str], asyncio.Lock]) -> None:
        """Replace the lock provider at the gateway composition root."""
        self._session_lock_provider = provider

    async def run(
        self,
        message: str,
        session_key: str,
        tool_context: ToolContext,
        agent_id: str = "main",
        model: str | None = None,
        attachments: list[dict] | None = None,
        timeout: float | None = None,
        max_iterations: int | None = None,
        input_mode: str = "user",
        persist_input: bool = False,
        input_provenance: dict[str, Any] | None = None,
        history_has_persisted_user: bool = True,
        session_intent: str | None = None,
        semantic_message: str | None = None,
        run_kind: str = "default",
        heartbeat_ack_max_chars: int = 300,
        bootstrap_context_mode: str | None = None,
        no_memory_capture: bool = False,
        ingress_pipeline_steps: list[PipelineStepRecord] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one agent turn with full orchestration.

        Acquires per-session lock, then:
        1. Resolve provider (cloned selector — no shared state mutation)
        2. Build tools + handler from registry (filtered by tool_context)
        3. Assemble identity system prompt
        4. Run pre-turn pipeline (model routing, squilla router, skills, prompt cache)
        5. Load session history
        6. Construct and run Agent
        7. Persist assistant response to transcript
        """
        session_key = canonicalize_session_key(session_key)
        agent_id = normalize_agent_id(agent_id)
        lock = self.get_session_lock(session_key)
        effective_tool_context = replace(tool_context, session_key=session_key)
        # Re-entry detection: check whether this call chain already owns the
        # session lock (gateway path: TaskRuntime._execute holds the shared
        # lock before calling run()). We use a ContextVar keyed by lock id so
        # child Tasks spawned by stream wrappers inherit ownership for this
        # call chain. lock.locked() is intentionally NOT used because it cannot
        # distinguish owners under concurrent turns.
        current_task = asyncio.current_task()
        owner_map = _SESSION_LOCK_OWNER.get(None)
        _caller_holds_lock = owner_map is not None and id(lock) in owner_map
        if _caller_holds_lock:
            # Same call chain already holds the lock (re-entrant call).
            async for event in self._run_turn(
                message,
                session_key,
                agent_id,
                model,
                attachments or [],
                effective_tool_context,
                timeout=timeout,
                max_iterations=max_iterations,
                input_mode=input_mode,
                persist_input=persist_input,
                input_provenance=input_provenance,
                history_has_persisted_user=history_has_persisted_user,
                session_intent=session_intent,
                semantic_message=semantic_message,
                run_kind=run_kind,
                heartbeat_ack_max_chars=heartbeat_ack_max_chars,
                bootstrap_context_mode=bootstrap_context_mode,
                no_memory_capture=no_memory_capture,
                ingress_pipeline_steps=ingress_pipeline_steps,
            ):
                yield event
        else:
            async with lock:
                # Record this Task as the lock owner in the ContextVar so that
                # any nested call to run() within the same Task can detect re-entry.
                _map: dict[int, asyncio.Task[Any]] = dict(owner_map or {})
                if current_task is not None:
                    _map[id(lock)] = current_task
                _token = _SESSION_LOCK_OWNER.set(_map)
                try:
                    async for event in self._run_turn(
                        message,
                        session_key,
                        agent_id,
                        model,
                        attachments or [],
                        effective_tool_context,
                        timeout=timeout,
                        max_iterations=max_iterations,
                        input_mode=input_mode,
                        persist_input=persist_input,
                        input_provenance=input_provenance,
                        history_has_persisted_user=history_has_persisted_user,
                        session_intent=session_intent,
                        semantic_message=semantic_message,
                        run_kind=run_kind,
                        heartbeat_ack_max_chars=heartbeat_ack_max_chars,
                        bootstrap_context_mode=bootstrap_context_mode,
                        no_memory_capture=no_memory_capture,
                        ingress_pipeline_steps=ingress_pipeline_steps,
                    ):
                        yield event
                finally:
                    _SESSION_LOCK_OWNER.reset(_token)

    async def _run_turn(
        self,
        message: str,
        session_key: str,
        agent_id: str,
        model: str | None,
        attachments: list[dict],
        tool_context: ToolContext | None = None,
        timeout: float | None = None,
        max_iterations: int | None = None,
        input_mode: str = "user",
        persist_input: bool = False,
        input_provenance: dict[str, Any] | None = None,
        history_has_persisted_user: bool = True,
        session_intent: str | None = None,
        semantic_message: str | None = None,
        run_kind: str = "default",
        heartbeat_ack_max_chars: int = 300,
        bootstrap_context_mode: str | None = None,
        no_memory_capture: bool = False,
        ingress_pipeline_steps: list[PipelineStepRecord] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        # Observability: bracket turn setup + stream loop with monotonic clock
        # so latency_ms reflects the full turn.
        turn_started_at = time.monotonic()
        turn_id = uuid.uuid4().hex
        resolved_model = ""
        final_prompt_str = ""
        turn_obj: Any | None = None
        tool_defs_for_log: list[Any] = []
        provider_for_log: Any | None = None
        turn_call_logger: TurnCallLogger | None = None
        trace_context = TraceContext.new(
            session_key=session_key,
            turn_id=turn_id,
            agent_id=agent_id,
        )
        session_id_for_log: str | None = None
        prompt_report_for_log: PromptReport | None = None
        # Declared up-front so the CancelledError handler below can always
        # access them, even if cancellation fires before the stream loop.
        final_text_parts: list[str] = []
        turn_segments: list[dict] = []
        turn_artifacts: list[dict[str, Any]] = []
        self._write_trace_event(
            "turn_start",
            trace_context,
            seq=1,
            attrs={"input_mode": input_mode, "run_kind": run_kind},
            payload={
                "message_chars": len(message),
                "attachment_count": len(attachments),
            },
        )
        try:
            runtime_message = message
            semantic_input = semantic_message if semantic_message is not None else message
            extra_prompt_context: dict[str, str] | None = None
            if input_mode == "system_event":
                runtime_message = f"[INTERNAL SYSTEM EVENT]\n{message}"
                semantic_input = message
                extra_prompt_context = {
                    "Internal Event Mode": (
                        "The next input is an internal scheduler event, not a human user"
                        " message. Treat it as system-originated context."
                    )
                }
            extra_prompt_context = self._merge_extra_prompt_context(
                extra_prompt_context,
                self._extra_context_for_tool_context(tool_context),
            )

            if persist_input and self._session_manager is not None and message:
                input_role = "system" if input_mode == "system_event" else "user"
                persisted_entry = await self._session_manager.append_message(
                    session_key,
                    role=input_role,
                    content=message,
                    provenance=input_provenance,
                )
                # Pick up any stamp SessionManager applied (user role only).
                if (
                    input_mode != "system_event"
                    and persisted_entry is not None
                    and isinstance(persisted_entry.content, str)
                    and persisted_entry.content != message
                ):
                    runtime_message = persisted_entry.content

            # 1. Resolve provider (clone to avoid shared state race)
            provider, cloned_selector = self._resolve_provider()
            if provider is None:
                log.error("turn_runner.no_provider", session_key=session_key)
                provider_error_event = ErrorEvent(
                    message="No provider available",
                    code="no_provider",
                )
                self._write_trace_event(
                    "turn_error",
                    trace_context,
                    seq=2,
                    payload={
                        "error_type": "ProviderResolutionError",
                        "error_code": provider_error_event.code,
                        "error_chars": len(provider_error_event.message),
                    },
                )
                await self._persist_turn_error(session_key, provider_error_event)
                yield provider_error_event
                return

            # 2. Build tools (filtered by tool_context)
            if tool_context is not None:
                tool_context = await self._with_artifact_context(tool_context, session_key)
                tool_context = self._with_runtime_write_callbacks(tool_context, agent_id)

            tool_metadata: dict[str, Any] = {}
            if "metadata" in inspect.signature(self._build_tools).parameters:
                tool_defs, tool_handler = self._build_tools(tool_context, metadata=tool_metadata)
            else:
                tool_defs, tool_handler = self._build_tools(tool_context)

            # 4. Assemble identity prompt
            prompt_metadata: dict[str, Any] = {}
            base_prompt = self._assemble_prompt(
                agent_id,
                tool_defs,
                session_key=session_key,
                semantic_message=semantic_input,
                extra_context=extra_prompt_context,
                prompt_metadata=prompt_metadata,
                bootstrap_context_mode=bootstrap_context_mode,
            )

            # 4. Run pipeline
            pipeline_kwargs: dict[str, Any] = {}
            if _accepts_keyword_arg(self._run_pipeline, "ingress_pipeline_steps"):
                pipeline_kwargs["ingress_pipeline_steps"] = ingress_pipeline_steps
            if _accepts_keyword_arg(self._run_pipeline, "semantic_message"):
                pipeline_kwargs["semantic_message"] = semantic_input
            router_context = await self._router_previous_assistant_context(
                session_key,
                exclude_last_user=history_has_persisted_user or persist_input,
            )
            if _accepts_keyword_arg(self._run_pipeline, "prev_assistant_text"):
                pipeline_kwargs["prev_assistant_text"] = router_context.get("prev_assistant_text")
            if _accepts_keyword_arg(self._run_pipeline, "prev_assistant_usage"):
                pipeline_kwargs["prev_assistant_usage"] = router_context.get(
                    "prev_assistant_usage"
                )
            if _accepts_keyword_arg(self._run_pipeline, "history_user_texts"):
                pipeline_kwargs["history_user_texts"] = router_context.get("history_user_texts")
            if _accepts_keyword_arg(self._run_pipeline, "flags_text_override"):
                pipeline_kwargs["flags_text_override"] = semantic_input
            if _accepts_keyword_arg(self._run_pipeline, "tool_context"):
                pipeline_kwargs["tool_context"] = tool_context
            turn, provider = await self._run_pipeline(
                runtime_message,
                session_key,
                provider,
                cloned_selector,
                tool_defs,
                base_prompt,
                attachments,
                **pipeline_kwargs,
            )
            turn.metadata.update(prompt_metadata)
            turn.metadata.update(tool_metadata)
            if self._config is not None and hasattr(self._config, "memory_mode_fingerprint"):
                try:
                    turn.metadata["memory_mode_fingerprint"] = (
                        self._config.memory_mode_fingerprint()
                    )
                except Exception:
                    pass
            effective_runtime_message = getattr(turn, "message", runtime_message)
            if model and cloned_selector is not None:
                cloned_selector.override_model(model)
                provider = cloned_selector.resolve()
            if cloned_selector is not None:
                provider = _SelectorFallbackProvider(provider, cloned_selector)
            turn_obj = turn
            tool_defs_for_log = tool_defs
            provider_for_log = provider

            # 5. Resolve final prompt and config
            final_prompt, cache_breakpoints, request_context_prompt = self._resolve_prompt_config(
                turn
            )
            final_prompt_str = final_prompt
            session_id_for_log = await self._resolve_session_id_for_log(session_key)
            prompt_report_for_log = build_prompt_report(
                turn_id=turn_id,
                session_key=session_key,
                session_id=session_id_for_log,
                agent_id=agent_id,
                system_prompt=final_prompt_str,
                tool_defs=turn.tool_defs,
                metadata=turn.metadata,
                tool_profile=turn.metadata.get("tool_profile"),
            )

            # Resolve model_id: explicit param > pipeline-routed > selector current config
            selector_model = ""
            if cloned_selector is not None:
                try:
                    selector_model = getattr(cloned_selector.current_config, "model", "") or ""
                except Exception:
                    selector_model = ""
            resolved_model = model or turn.model or selector_model
            provider_name = getattr(provider, "provider_name", "") or type(provider).__name__
            trace_context = replace(
                trace_context,
                session_id=session_id_for_log,
            )
            if is_turn_call_log_enabled():
                turn_call_logger = TurnCallLogger(
                    trace_id=trace_context.trace_id,
                    turn_id=turn_id,
                    session_key=session_key,
                    session_id=session_id_for_log,
                    session_intent=session_intent,
                    agent_id=agent_id,
                    provider=provider_name,
                    model=resolved_model,
                    source=self._build_turn_call_source(
                        tool_context,
                        input_provenance,
                        run_kind=run_kind,
                    ),
                )
                turn_call_logger.write(
                    "prompt_report",
                    asdict(prompt_report_for_log),
                )
                turn_call_logger.write(
                    "turn_start",
                        {
                            "input_mode": input_mode,
                            "message": effective_runtime_message,
                            "attachment_count": len(attachments),
                            "tool_names": [getattr(td, "name", "") for td in turn.tool_defs],
                        },
                )
            log.debug(
                "turn_runner.model_resolved",
                explicit_model=model,
                pipeline_model=turn.model,
                selector_model=selector_model,
                resolved=resolved_model,
                squilla_router_tier=turn.metadata.get("routed_tier"),
            )
            # Runtime timeout is the whole agent turn lifecycle. Provider
            # request timeout remains separate and is passed as request_timeout.
            effective_runtime_timeout = (
                float(timeout)
                if timeout is not None
                else self._resolve_agent_runtime_timeout(session_key)
            )
            effective_max_iterations = self._resolve_agent_max_iterations(
                session_key,
                max_iterations,
            )
            effective_request_timeout = self._resolve_llm_timeout(session_key)

            # Resolve max_tokens & context_window from model catalog
            user_max_tokens = getattr(getattr(self._config, "llm", None), "max_tokens", 0)
            if self._model_catalog is not None:
                max_tokens = self._model_catalog.resolve_max_tokens(
                    resolved_model, user_override=user_max_tokens
                )
                context_window = self._model_catalog.resolve_context_window(resolved_model)
            else:
                max_tokens = user_max_tokens if user_max_tokens > 0 else 8192
                context_window = 200_000

            # Resolve model capabilities for reasoning support
            model_caps = None
            if self._model_catalog is not None:
                provider_name = getattr(
                    getattr(self._config, "llm", None), "provider", "openrouter"
                )
                base_url = getattr(getattr(self._config, "llm", None), "base_url", "")
                model_caps = self._model_catalog.get_capabilities(
                    resolved_model, provider_name=provider_name, base_url=base_url
                )

            _mem_cfg = getattr(self._config, "memory", None) if self._config else None
            _agent_token_cfg = (
                getattr(self._config, "agent_token_saving", None) if self._config else None
            )
            thinking = self._resolve_turn_thinking(turn)
            tool_result_compression_mode = self._resolve_tool_result_compression_mode(
                _agent_token_cfg
            )
            tool_result_summary_model = getattr(
                _agent_token_cfg,
                "tool_result_compression_summary_model",
                None,
            )
            agent_config = AgentConfig(
                max_iterations=effective_max_iterations,
                system_prompt=final_prompt,
                cache_breakpoints=cache_breakpoints,
                request_context_prompt=request_context_prompt,
                cache_mode=turn.metadata.get("cache_mode", "off"),
                skills_context_prompt=turn.metadata.get("skills_context_prompt"),
                model_id=resolved_model,
                timeout=effective_runtime_timeout,
                request_timeout=effective_request_timeout,
                max_tokens=max_tokens,
                context_window_tokens=context_window,
                flush_enabled=getattr(_mem_cfg, "flush_enabled", True),
                flush_timeout_seconds=getattr(_mem_cfg, "flush_timeout_seconds", 5.0),
                flush_backoff_initial_seconds=getattr(
                    _mem_cfg,
                    "flush_backoff_initial_seconds",
                    30.0,
                ),
                flush_backoff_max_seconds=getattr(_mem_cfg, "flush_backoff_max_seconds", 300.0),
                flush_archive_max_bytes=getattr(_mem_cfg, "flush_archive_max_bytes", 800_000),
                flush_workspace_dir=str(self._resolve_memory_source_dir(agent_id)),
                model_capabilities=model_caps,
                thinking=thinking,
                tool_result_compression_enabled=getattr(
                    _agent_token_cfg,
                    "tool_result_compression_enabled",
                    True,
                ),
                tool_result_compression_mode=tool_result_compression_mode,  # type: ignore[arg-type]
                tool_result_compression_max_share=getattr(
                    _agent_token_cfg,
                    "tool_result_compression_max_share",
                    0.25,
                ),
                tool_result_compression_summary_model=tool_result_summary_model,
                tool_result_compression_summary_max_tokens=getattr(
                    _agent_token_cfg,
                    "tool_result_compression_summary_max_tokens",
                    1024,
                ),
                tool_result_compression_summary_timeout_seconds=getattr(
                    _agent_token_cfg,
                    "tool_result_compression_summary_timeout_seconds",
                    20.0,
                ),
                tool_result_compression_summary_input_max_chars=getattr(
                    _agent_token_cfg,
                    "tool_result_compression_summary_input_max_chars",
                    60_000,
                ),
                metadata=turn.metadata,
            )
            tool_result_summarizer_provider = self._resolve_tool_result_summarizer_provider(
                mode=tool_result_compression_mode,
                cloned_selector=cloned_selector,
                current_provider=provider,
                summary_model=tool_result_summary_model,
            )

            # Resolve per-agent memory sync manager (Trigger 1: warm session)
            sync_manager = (
                self._memory_sync_managers.get(agent_id) if self._memory_sync_managers else None
            )
            if sync_manager is not None:
                await sync_manager.warm_session(session_key)

            # Capture frozen memory snapshot on first turn of this session
            private_memory_allowed = allows_private_memory_prompt_injection(session_key)
            snap_key = (agent_id, session_key)
            if private_memory_allowed and snap_key not in self._memory_snapshots:
                _ws = self._resolve_memory_source_dir(agent_id)
                self._memory_snapshots[snap_key] = MemorySnapshot(
                    memory_md=self._load_memory_md(_ws),
                    daily_notes=self._load_daily_notes(_ws),
                )

            agent = Agent(
                provider=cast(LLMProvider, provider),
                config=agent_config,
                tool_definitions=turn.tool_defs,
                tool_handler=tool_handler,
                usage_tracker=self._usage_tracker,
                session_key=session_key,
                turn_call_logger=turn_call_logger,
                tool_result_summarizer_provider=cast(
                    LLMProvider | None,
                    tool_result_summarizer_provider,
                ),
            )
            agent._memory_sync_manager = sync_manager
            cast(Any, agent)._session_flush_service = self._session_flush_service

            # 6. Pre-flight compaction (before loading history into Agent)
            t3_upgrade_result = await self._maybe_compact_on_t3_upgrade(
                session_key,
                turn,
                agent_config.context_window_tokens,
                compaction_provider=provider,
                compaction_model=resolved_model,
            )
            if t3_upgrade_result in {_T3_NOT_APPLICABLE, _T3_FLUSH_FAILED}:
                await self._maybe_preflight_compact(
                    session_key,
                    agent_config.context_window_tokens,
                    compaction_provider=provider,
                    compaction_model=resolved_model,
                )

            # 7. Load history. Compaction summaries are composed after
            # preflight compaction and before Agent.run_turn so summaries
            # created during preflight are visible on the same turn without
            # mutating the cacheable system prompt.
            compaction_summary_context = await self._load_history(
                agent,
                session_key,
                trim_last_user=history_has_persisted_user,
            )
            agent.config.request_context_prompt = _prepend_request_context_prompt(
                agent.config.request_context_prompt,
                compaction_summary_context,
            )

            # 8. Build extra messages for attachments
            extra_msgs = self._build_attachment_messages(
                effective_runtime_message,
                attachments,
                media_root=self._attachment_media_root(),
            )

            # 9. Stream events (final_text_parts/turn_segments are declared
            # up-front above so the CancelledError handler can read them)
            current_text_parts: list[str] = []
            error_message: str | None = None
            pending_error_event: ErrorEvent | None = None
            done_event: DoneEvent | None = None
            turn_input = effective_runtime_message if extra_msgs is None else ""
            agent_run_kwargs: dict[str, Any] = {}
            if _accepts_keyword_arg(agent.run_turn, "semantic_message"):
                agent_run_kwargs["semantic_message"] = semantic_input
            async for event in agent.run_turn(
                turn_input,
                extra_messages=extra_msgs,
                **agent_run_kwargs,
            ):
                if isinstance(event, TextDeltaEvent):
                    final_text_parts.append(event.text)
                    current_text_parts.append(event.text)
                elif isinstance(event, ToolUseStartEvent):
                    if event.synthetic_from_text and current_text_parts:
                        raw_current_text = "".join(current_text_parts)
                        cleaned_current_text = strip_synthetic_tool_call_text(
                            raw_current_text,
                            event.tool_name,
                        )
                        if cleaned_current_text != raw_current_text:
                            full_text = "".join(final_text_parts)
                            if full_text.endswith(raw_current_text):
                                prefix = full_text[: -len(raw_current_text)]
                                final_text_parts = [prefix + cleaned_current_text]
                            else:
                                final_text_parts = [
                                    strip_synthetic_tool_call_text(
                                        full_text,
                                        event.tool_name,
                                    )
                                ]
                            current_text_parts = (
                                [cleaned_current_text] if cleaned_current_text else []
                            )
                    if current_text_parts:
                        turn_segments.append({"type": "text", "text": "".join(current_text_parts)})
                        current_text_parts = []
                    turn_segments.append(
                        {
                            "type": "tool_use",
                            "tool_use_id": event.tool_use_id,
                            "name": event.tool_name,
                            "input": "",
                        }
                    )
                elif isinstance(event, ToolResultEvent):
                    if event.arguments is not None:
                        for segment in reversed(turn_segments):
                            if (
                                segment.get("type") == "tool_use"
                                and segment.get("tool_use_id") == event.tool_use_id
                            ):
                                segment["input"] = event.arguments
                                break
                    turn_segments.append(_persisted_tool_result_segment(event))
                elif isinstance(event, ArtifactEvent):
                    turn_artifacts.append(artifact_payload(event))
                elif isinstance(event, ErrorEvent):
                    # Agent emits ErrorEvent(code="timeout") when
                    # asyncio.timeout() fires. Rewrite to the stable user
                    # envelope so every downstream renderer (UI, CLI, channel)
                    # sees the same shape as the tool-failure envelope.
                    if event.code == "timeout":
                        event = ErrorEvent(
                            message=_LLM_TIMEOUT_ENVELOPE["user_message"],
                            code=_LLM_TIMEOUT_ENVELOPE["error_class"],
                        )
                    if event.code == "incomplete_tool_stream":
                        turn_segments = _drop_unpaired_tool_use_segments(turn_segments)
                    error_message = event.message or "Unknown error"
                    pending_error_event = event
                    continue
                elif isinstance(event, WarningEvent):
                    event = self._handle_runtime_warning(event)
                elif isinstance(event, DoneEvent):
                    normalized_text = _normalize_heartbeat_text(
                        event.text,
                        run_kind=run_kind,
                        heartbeat_ack_max_chars=heartbeat_ack_max_chars,
                    )
                    metadata = turn.metadata
                    routed_tier = metadata.get("routed_tier")
                    routing_source = metadata.get("routing_source", "none")
                    routing_confidence = float(metadata.get("routing_confidence") or 0.0)
                    baseline_model = metadata.get("baseline_model", "")
                    routed_model = metadata.get("routed_model", "") or event.model
                    savings_pct = float(metadata.get("savings_pct") or 0.0)
                    _max_p = float(metadata.get("savings_max_price_per_m") or 0.0)
                    _rte_p = float(metadata.get("savings_routed_price_per_m") or 0.0)
                    savings_usd = _compute_route_input_savings_usd(
                        _max_p,
                        _rte_p,
                        event.input_tokens,
                    )
                    router_cfg = getattr(self._config, "squilla_router", None)
                    squilla_router_tiers = getattr(router_cfg, "tiers", {})
                    estimated_output_savings_pct = getattr(
                        router_cfg,
                        "estimated_output_savings_pct",
                        0.03,
                    )
                    comprehensive = _compute_comprehensive_turn_savings(
                        event,
                        metadata,
                        squilla_router_tiers,
                        routed_model,
                        estimated_output_savings_pct=estimated_output_savings_pct,
                    )
                    provider_cache_hit = (event.cached_tokens or 0) > 0
                    opensquilla_cache_hit = metadata.get("cache_mode") == "hit"
                    event = replace(
                        event,
                        text=normalized_text,
                        routed_tier=routed_tier,
                        routing_source=routing_source or "none",
                        routing_confidence=routing_confidence,
                        baseline_model=baseline_model,
                        routed_model=routed_model,
                        savings_pct=savings_pct,
                        savings_usd=savings_usd,
                        cache_hit_active=provider_cache_hit or opensquilla_cache_hit,
                        total_savings_pct=comprehensive.pct,
                        total_savings_usd=comprehensive.usd,
                    )
                    done_event = event
                    if normalized_text and not final_text_parts:
                        final_text_parts.append(normalized_text)
                        if turn_segments:
                            current_text_parts.append(normalized_text)
                    # Hallucination check: emit Warning BEFORE yielding Done
                    # so CLI/SDK consumers that stop reading on terminal events
                    # still see it.
                    accumulated_text = "".join(final_text_parts)
                    if _claims_image_without_tool_use(
                        accumulated_text, turn.tool_defs, turn_segments
                    ):
                        yield WarningEvent(
                            code="image_generate_claimed_without_call",
                            message=(
                                "The assistant described a generated image but did not "
                                "call an image-generation tool. No image was produced."
                            ),
                        )
                elif isinstance(event, CompactionEvent):
                    if self._session_manager is not None:
                        try:
                            await self._session_manager.persist_compaction_result(
                                session_key,
                                event.summary,
                                event.kept_entries,
                            )
                            notify_compaction(session_key)
                        except Exception as exc:
                            log.warning("compaction_persist_failed", error=str(exc))
                    # Refresh frozen snapshot and system prompt after compaction
                    _ws2 = self._resolve_memory_source_dir(agent_id)
                    if private_memory_allowed:
                        self._memory_snapshots[(agent_id, session_key)] = MemorySnapshot(
                            memory_md=self._load_memory_md(_ws2),
                            daily_notes=self._load_daily_notes(_ws2),
                        )
                    # Compaction-refresh resets the agent to a clean cacheable
                    # base; the next turn's normal pre-turn pipeline will
                    # rebuild the volatile suffix (memory / workspace)
                    # from fresh state. ``_assemble_prompt`` may still return a
                    # ``(base, dynamic_suffix)`` tuple here — daily_notes,
                    # workspace_files, and extra_context now live in that
                    # suffix — so extract just the base. Feeding the
                    # tuple straight to ``agent.refresh_system_prompt`` would
                    # smuggle volatile bytes into ``ChatConfig.system`` and
                    # raise ValidationError on the next turn.
                    assembled = self._assemble_prompt(
                        agent_id,
                        tool_defs,
                        session_key=session_key,
                        bootstrap_context_mode=bootstrap_context_mode,
                    )
                    refreshed_prompt = assembled[0] if isinstance(assembled, tuple) else assembled
                    agent.refresh_system_prompt(refreshed_prompt)
                    continue  # internal event, don't yield to caller
                yield event

            # Flush any remaining text segment
            if current_text_parts:
                turn_segments.append({"type": "text", "text": "".join(current_text_parts)})

            # Trigger 5: notify memory sync of message bytes
            if sync_manager is not None:
                byte_count = len(effective_runtime_message.encode("utf-8"))
                sync_manager.notify_message(byte_count)

            # 10. Persist assistant response (filter sentinel tokens)
            final_text = "".join(final_text_parts)
            original_final_text = final_text
            final_text = _normalize_heartbeat_text(
                final_text,
                run_kind=run_kind,
                heartbeat_ack_max_chars=heartbeat_ack_max_chars,
            )
            if (
                original_final_text
                and not final_text
                and turn_segments
                and all(
                    isinstance(segment, dict) and segment.get("type") == "text"
                    for segment in turn_segments
                )
            ):
                turn_segments = []
            # (Hallucination warning is emitted inside the DoneEvent branch
            # above so it precedes the terminal done event for all consumers.)

            if (
                final_text or turn_segments or turn_artifacts
            ) and self._session_manager is not None:
                persisted_content = (
                    json.dumps(
                        {"text": final_text, "artifacts": turn_artifacts},
                        ensure_ascii=False,
                    )
                    if turn_artifacts
                    else final_text
                )
                append_kwargs: dict[str, Any] = {
                    "role": "assistant",
                    "content": persisted_content,
                    "tool_calls": turn_segments if turn_segments else None,
                }
                if (
                    done_event is not None
                    and done_event.reasoning_content
                    and _is_deepseek_model_id(done_event.model or resolved_model or "")
                ):
                    append_kwargs["reasoning_content"] = done_event.reasoning_content
                if _accepts_keyword_arg(self._session_manager.append_message, "token_count"):
                    append_kwargs["token_count"] = (
                        done_event.output_tokens if done_event is not None else None
                    )
                await self._session_manager.append_message(session_key, **append_kwargs)
                try:
                    await self._capture_turn_memory(
                        agent_id=agent_id,
                        session_key=session_key,
                        runtime_message=runtime_message,
                        final_text=final_text,
                        input_mode=input_mode,
                        tool_context=tool_context,
                        input_provenance=input_provenance,
                        run_kind=run_kind,
                        no_memory_capture=no_memory_capture,
                    )
                except Exception as exc:
                    log.warning(
                        "turn_runner.capture_failed",
                        session_key=session_key,
                        agent_id=agent_id,
                        error=str(exc),
                    )
            if error_message and self._session_manager is not None:
                await self._persist_turn_error(session_key, pending_error_event)
            if done_event is not None and self._session_manager is not None:
                try:
                    current_session = await self._session_manager.get_session(session_key)
                    if current_session is not None:
                        done_total_tokens = done_event.input_tokens + done_event.output_tokens
                        event_cost_source = normalize_event_cost_source(
                            done_event.cost_source,
                            input_tokens=done_event.input_tokens,
                            output_tokens=done_event.output_tokens,
                            cache_read_tokens=done_event.cached_tokens,
                            cache_write_tokens=done_event.cache_write_tokens,
                            cost_usd=done_event.cost_usd,
                            billed_cost_usd=done_event.billed_cost,
                        )
                        next_total_cost = (
                            getattr(current_session, "total_cost_usd", 0.0) or 0.0
                        ) + done_event.cost_usd
                        next_billed_cost = (
                            getattr(current_session, "billed_cost_usd", 0.0) or 0.0
                        ) + done_event.billed_cost
                        next_estimated_component = (
                            getattr(current_session, "estimated_cost_component_usd", 0.0)
                            or 0.0
                        )
                        if event_cost_source == "opensquilla_estimate":
                            next_estimated_component += done_event.cost_usd
                        next_missing_entries = (
                            getattr(current_session, "missing_cost_entries", 0) or 0
                        )
                        if event_cost_source == "unavailable":
                            next_missing_entries += 1
                        next_cost_source = rollup_cost_source(
                            billed_cost_usd=next_billed_cost,
                            estimated_cost_component_usd=next_estimated_component,
                            missing_cost_entries=next_missing_entries,
                        )
                        # Persist the last actual model into usage metadata only.
                        # Writing it to session.model would pin future turns and
                        # silently bypass squilla-router routing.
                        await self._session_manager.update(
                            session_key,
                            input_tokens=(getattr(current_session, "input_tokens", 0) or 0)
                            + done_event.input_tokens,
                            output_tokens=(getattr(current_session, "output_tokens", 0) or 0)
                            + done_event.output_tokens,
                            total_tokens=(getattr(current_session, "total_tokens", 0) or 0)
                            + done_total_tokens,
                            total_tokens_fresh=True,
                            estimated_cost_usd=(
                                getattr(current_session, "estimated_cost_usd", 0.0) or 0.0
                            )
                            + done_event.cost_usd,
                            total_cost_usd=next_total_cost,
                            billed_cost_usd=next_billed_cost,
                            estimated_cost_component_usd=next_estimated_component,
                            cost_source=next_cost_source,
                            missing_cost_entries=next_missing_entries,
                            cache_read=(getattr(current_session, "cache_read", 0) or 0)
                            + done_event.cached_tokens,
                            cache_write=(getattr(current_session, "cache_write", 0) or 0)
                            + done_event.cache_write_tokens,
                            model_override=done_event.model
                            or getattr(current_session, "model_override", None),
                        )
                except Exception as exc:
                    log.warning(
                        "turn_runner.session_usage_persist_failed",
                        session_key=session_key,
                        error=str(exc),
                    )

            if turn_call_logger is not None:
                turn_call_logger.write(
                    "turn_end",
                    {
                        "final_text": final_text,
                        "segments": turn_segments,
                        "error": error_message,
                    },
                )
            if trace_context is not None:
                self._write_trace_event(
                    "turn_end",
                    trace_context,
                    seq=2,
                    attrs={"provider": provider_name, "model": resolved_model},
                    payload={
                        "final_text_chars": len(final_text),
                        "segment_count": len(turn_segments),
                        "artifact_count": len(turn_artifacts),
                        "error": bool(error_message),
                    },
                )

            # 11. Observability: best-effort DecisionEntry for this turn.
            #     Must never break turn execution — wrap in try/except.
            turn.metadata.update(
                self._collect_session_flush_metadata(agent_id, session_key=session_key)
            )
            prompt_report_for_decision = build_prompt_report(
                turn_id=turn_id,
                session_key=session_key,
                session_id=session_id_for_log,
                agent_id=agent_id,
                system_prompt=final_prompt_str,
                tool_defs=turn.tool_defs,
                metadata=turn.metadata,
                tool_profile=turn.metadata.get("tool_profile"),
            )
            self._emit_decision_entry(
                turn_id=turn_id,
                session_key=session_key,
                session_id=session_id_for_log,
                message=message,
                final_prompt=final_prompt_str,
                tool_defs=tool_defs_for_log,
                turn_obj=turn_obj,
                provider=provider_for_log,
                resolved_model=resolved_model,
                turn_started_at=turn_started_at,
                prompt_report=prompt_report_for_decision,
                session_intent=session_intent,
                done_event=done_event,
                trace_id=trace_context.trace_id if trace_context is not None else None,
            )
            if pending_error_event is not None:
                yield pending_error_event

        except asyncio.CancelledError:
            # Bug 2 partial-persistence: preserve whatever assistant text has
            # already streamed back so a cancelled turn does not leave the
            # transcript with an orphan user message. Marker `[interrupted]`
            # lets future turns (and users reading history) recognise the
            # response is incomplete.
            partial_text = "".join(final_text_parts).rstrip()
            if (
                partial_text or turn_segments or turn_artifacts
            ) and self._session_manager is not None:
                try:
                    # Neutral marker: under Proposal C, new user input does not
                    # cancel a turn (it queues). Cancellation now means ESC /
                    # Stop / idle timeout. "[interrupted]" is accurate for all.
                    body = f"{partial_text}\n\n[interrupted]" if partial_text else "[interrupted]"
                    if turn_artifacts:
                        body = json.dumps(
                            {"text": body, "artifacts": turn_artifacts},
                            ensure_ascii=False,
                        )
                    await self._session_manager.append_message(
                        session_key,
                        role="assistant",
                        content=body,
                        tool_calls=turn_segments if turn_segments else None,
                    )
                    log.info(
                        "turn_runner.cancelled_partial_persisted",
                        session_key=session_key,
                        text_chars=len(partial_text),
                        segment_count=len(turn_segments),
                    )
                except Exception:  # pragma: no cover — defensive: don't swallow the cancel
                    log.warning(
                        "turn_runner.cancelled_persist_failed",
                        session_key=session_key,
                        exc_info=True,
                    )
            if turn_call_logger is not None:
                try:
                    turn_call_logger.write(
                        "turn_cancelled",
                        {"partial_text_chars": len(partial_text)},
                    )
                except Exception:
                    pass
            if trace_context is not None:
                self._write_trace_event(
                    "turn_cancelled",
                    trace_context,
                    seq=2,
                    payload={"partial_text_chars": len(partial_text)},
                )
            raise

        except Exception as exc:
            log.error(
                "turn_runner.failed",
                session_key=session_key,
                error=str(exc),
                exc_info=True,
            )
            if self._session_manager is not None:
                await self._session_manager.append_message(
                    session_key, role="system", content=f"Error: {exc}"
                )
            if turn_call_logger is not None:
                turn_call_logger.write(
                    "turn_error",
                    {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            if trace_context is not None:
                self._write_trace_event(
                    "turn_error",
                    trace_context,
                    seq=2,
                    payload={
                        "error_type": type(exc).__name__,
                        "error_chars": len(str(exc)),
                    },
                )
            yield ErrorEvent(message=str(exc), code="agent_error")

    @staticmethod
    def _write_trace_event(
        kind: str,
        context: TraceContext,
        *,
        seq: int | None = None,
        attrs: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        try:
            write_trace_event(
                TraceEvent(
                    kind=kind,
                    context=context,
                    privacy="operational",
                    seq=seq,
                    attrs=attrs or {},
                    payload=payload or {},
                )
            )
        except Exception as exc:  # pragma: no cover - observability must not break turns
            log.debug("trace_event.write_failed", kind=kind, error=str(exc))

    @staticmethod
    def _build_turn_call_source(
        tool_context: ToolContext | None,
        input_provenance: dict[str, Any] | None,
        *,
        run_kind: str | None = None,
    ) -> dict[str, Any]:
        """Build stable source metadata for raw call-log filtering."""

        source: dict[str, Any] = {}
        if tool_context is not None:
            source.update(
                {
                    "caller_kind": str(tool_context.caller_kind),
                    "channel_kind": tool_context.channel_kind,
                    "channel_id": tool_context.channel_id,
                    "sender_id": tool_context.sender_id,
                    "source_kind": tool_context.source_kind,
                    "source_name": tool_context.source_name,
                }
            )
        if run_kind:
            source["run_kind"] = run_kind
        if input_provenance:
            source["input_provenance"] = input_provenance
            provenance_kind = TurnRunner._input_provenance_kind(input_provenance)
            if provenance_kind:
                source["input_provenance_kind"] = provenance_kind
        return source

    async def _resolve_session_id_for_log(self, session_key: str) -> str | None:
        """Best-effort lookup of the transcript identity for observability."""

        if self._session_manager is None:
            return None
        try:
            if hasattr(self._session_manager, "get_session"):
                node = await self._session_manager.get_session(session_key)
            else:
                from opensquilla.gateway.session_services import get_session_storage

                storage = get_session_storage(self._session_manager)
                node = await storage.get_session(session_key) if storage is not None else None
        except Exception:
            return None
        session_id = getattr(node, "session_id", None)
        return session_id if isinstance(session_id, str) and session_id else None

    def _resolve_provider(self) -> tuple[Any | None, Any | None]:
        """Clone the selector and resolve provider (no shared state mutation)."""
        if self._provider_selector is None:
            return None, None
        cloned = self._provider_selector.clone()
        return cloned.resolve(), cloned

    @staticmethod
    def _resolve_tool_result_compression_mode(agent_token_cfg: Any | None) -> str:
        if agent_token_cfg is None:
            return "truncate"
        mode = getattr(agent_token_cfg, "tool_result_compression_mode", None)
        if mode in {"off", "truncate", "summarize"}:
            return str(mode)
        return (
            "truncate"
            if getattr(agent_token_cfg, "tool_result_compression_enabled", True)
            else "off"
        )

    def _handle_runtime_warning(self, event: WarningEvent) -> WarningEvent:
        if event.code != "tool_result_summary_failed":
            return event
        return self._disable_tool_result_compression_after_summary_failure(event)

    async def _persist_turn_error(
        self,
        session_key: str,
        event: ErrorEvent | None,
    ) -> None:
        """Best-effort durable transcript record for terminal turn errors."""
        if self._session_manager is None or event is None:
            return
        message = event.message or "Unknown error"
        try:
            await self._session_manager.append_message(
                session_key,
                role="system",
                content=f"Error: {message}",
            )
        except Exception as exc:  # noqa: BLE001 - persistence must not mask the original error
            log.warning(
                "turn_runner.error_persist_failed",
                session_key=session_key,
                code=event.code,
                error=str(exc),
            )

    def _disable_tool_result_compression_after_summary_failure(
        self, event: WarningEvent
    ) -> WarningEvent:
        cfg = self._config
        agent_token_cfg = getattr(cfg, "agent_token_saving", None) if cfg is not None else None
        summary_model = (
            getattr(agent_token_cfg, "tool_result_compression_summary_model", None)
            if agent_token_cfg is not None
            else None
        )
        model_label = summary_model or "the active model"

        disabled = False
        if agent_token_cfg is not None:
            try:
                setattr(agent_token_cfg, "tool_result_compression_enabled", False)
                setattr(agent_token_cfg, "tool_result_compression_mode", "off")
                disabled = True
            except Exception as exc:  # noqa: BLE001 - warning should still surface
                log.warning(
                    "tool_result_summary_disable_failed",
                    model=model_label,
                    error=str(exc),
                )

        if disabled and cfg is not None:
            try:
                from opensquilla.gateway.rpc_config import _persist_config

                _persist_config(cfg)
            except Exception as exc:  # noqa: BLE001 - runtime config already disabled
                log.warning(
                    "tool_result_summary_disable_persist_failed",
                    model=model_label,
                    error=str(exc),
                )

        base_message = event.message.strip() if event.message else (
            f"Tool result summarization failed for model {model_label!r}."
        )
        suffix = " Tool Compress has been turned OFF." if disabled else ""
        return WarningEvent(
            code="tool_result_summary_disabled" if disabled else event.code,
            message=f"{base_message}{suffix}",
        )

    @staticmethod
    def _resolve_tool_result_summarizer_provider(
        *,
        mode: str,
        cloned_selector: Any | None,
        current_provider: Any,
        summary_model: str | None,
    ) -> Any | None:
        if mode != "summarize":
            return None
        if not summary_model:
            return current_provider
        if cloned_selector is None or not hasattr(cloned_selector, "clone"):
            return current_provider
        try:
            summary_selector = cloned_selector.clone()
            summary_selector.override_model(summary_model)
            provider = summary_selector.resolve()
            return _SelectorFallbackProvider(provider, summary_selector)
        except Exception as exc:  # noqa: BLE001 - summarization falls back to truncation
            log.warning(
                "turn_runner.tool_result_summary_provider_failed",
                model=summary_model,
                error=str(exc),
            )
            return current_provider

    @staticmethod
    def _non_bool_number(value: Any) -> TypeGuard[int | float]:
        return not isinstance(value, bool) and isinstance(value, int | float)

    @staticmethod
    def _non_bool_int(value: Any) -> TypeGuard[int]:
        return not isinstance(value, bool) and isinstance(value, int)

    def _resolve_agent_runtime_timeout(self, session_key: str) -> float:
        """Resolve whole-turn runtime timeout.

        ``0`` is intentional and disables the runtime budget. The old
        ``llm_timeout_seconds`` setting remains a legacy runtime alias.
        """

        sm = self._session_manager
        if sm is not None and hasattr(sm, "get_session_config"):
            try:
                session_cfg = sm.get_session_config(session_key)
                if session_cfg is not None:
                    for attr in ("agent_runtime_timeout_seconds", "llm_timeout_seconds"):
                        value = getattr(session_cfg, attr, None)
                        if self._non_bool_number(value) and value >= 0:
                            return float(value)
            except Exception:  # noqa: BLE001
                pass

        env_timeout = os.environ.get("OPENSQUILLA_TURN_TIMEOUT")
        if env_timeout is not None and env_timeout.strip():
            raw = env_timeout.strip()
            try:
                value = float(raw)
            except ValueError:
                log.warning("turn_runner.invalid_runtime_timeout", raw=raw)
            else:
                if value >= 0:
                    return value
                log.warning("turn_runner.negative_runtime_timeout", value=value)

        for attr in ("agent_runtime_timeout_seconds", "llm_timeout_seconds"):
            value = getattr(self._config, attr, None)
            if self._non_bool_number(value) and value >= 0:
                return float(value)

        return _DEFAULT_AGENT_RUNTIME_TIMEOUT_SECONDS

    def _resolve_agent_max_iterations(
        self,
        session_key: str,
        explicit: int | None = None,
    ) -> int:
        """Resolve model/tool loop budget for this turn."""

        if explicit is not None:
            if self._non_bool_int(explicit) and explicit >= 1:
                return int(explicit)
            raise ValueError("max_iterations must be an integer >= 1")

        sm = self._session_manager
        if sm is not None and hasattr(sm, "get_session_config"):
            try:
                session_cfg = sm.get_session_config(session_key)
                if session_cfg is not None:
                    value = getattr(session_cfg, "agent_max_iterations", None)
                    if self._non_bool_int(value) and value >= 1:
                        return int(value)
                    if value is not None:
                        log.warning(
                            "turn_runner.invalid_agent_max_iterations",
                            source="session",
                            value=value,
                        )
            except Exception:  # noqa: BLE001
                pass

        env_value = os.environ.get("OPENSQUILLA_AGENT_MAX_ITERATIONS")
        if env_value is not None and env_value.strip():
            raw = env_value.strip()
            try:
                value = int(raw)
            except ValueError:
                log.warning("turn_runner.invalid_agent_max_iterations", source="env", raw=raw)
            else:
                if value >= 1:
                    return value
                log.warning("turn_runner.invalid_agent_max_iterations", source="env", value=value)

        value = getattr(self._config, "agent_max_iterations", None)
        if self._non_bool_int(value) and value >= 1:
            return int(value)
        if value is not None:
            log.warning(
                "turn_runner.invalid_agent_max_iterations",
                source="config",
                value=value,
            )

        return AgentConfig().max_iterations

    def _resolve_turn_thinking(self, turn: Any) -> bool | ThinkingLevel:
        """Resolve explicit config thinking before squilla-router suggestions."""

        llm_cfg = getattr(self._config, "llm", None) if self._config else None
        explicit = getattr(llm_cfg, "thinking", None)
        parsed = self._parse_thinking_level(
            explicit,
            source="config",
        )
        if parsed is not None:
            return parsed
        if explicit is not None and str(explicit).strip():
            return False

        metadata = getattr(turn, "metadata", {}) or {}
        if not metadata.get("thinking_requested"):
            return False

        parsed = self._parse_thinking_level(
            metadata.get("thinking_level", "medium"),
            source="squilla_router",
        )
        return parsed if parsed is not None else False

    @staticmethod
    def _parse_thinking_level(value: Any, *, source: str) -> bool | ThinkingLevel | None:
        if value is None:
            return None
        if isinstance(value, ThinkingLevel):
            return value
        if isinstance(value, bool):
            return value

        raw = str(value).strip().lower()
        if not raw:
            return None
        normalized = _THINKING_ALIASES.get(raw.replace("_", "-"), raw)
        try:
            return ThinkingLevel(normalized)
        except ValueError:
            log.warning("turn_runner.invalid_thinking_level", source=source, value=value)
            return None

    def _resolve_llm_timeout(self, session_key: str) -> float:
        """Resolve single provider-request timeout for this turn."""

        sm = self._session_manager
        if sm is not None and hasattr(sm, "get_session_config"):
            try:
                session_cfg = sm.get_session_config(session_key)
                if session_cfg is not None:
                    per_session = getattr(session_cfg, "llm_request_timeout_seconds", None)
                    if isinstance(per_session, int | float) and per_session > 0:
                        return float(per_session)
            except Exception:  # noqa: BLE001
                pass

        gw_timeout = getattr(self._config, "llm_request_timeout_seconds", None)
        if isinstance(gw_timeout, int | float) and gw_timeout > 0:
            return float(gw_timeout)
        return _DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS

    def _build_tools(
        self,
        ctx: ToolContext | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[list, ToolHandler | None]:
        """Build tool definitions and handler from registry, filtered by ToolContext."""
        if self._tool_registry is None:
            return [], None
        from opensquilla.tools.dispatch import build_tool_handler
        from opensquilla.tools.policy import apply_tool_policy_from_config
        from opensquilla.tools.registry import filter_by_profile, resolve_profile

        if ctx is not None:
            ctx = apply_tool_policy_from_config(
                ctx,
                available_tools=self._tool_registry.list_names(),
                config=self._config,
            )
            ctx = self._apply_runtime_capability_denies(ctx)
            log.debug(
                "tool_policy.policy_pre",
                allowed_tool_count=len(self._tool_registry.to_tool_definitions(ctx)),
                denied_count=len(ctx.denied_tools),
                profile=resolve_profile(ctx).value,
            )
        log.info(
            "tool_context_created",
            caller_kind=ctx.caller_kind if ctx else "none",
            denied_count=len(ctx.denied_tools) if ctx else 0,
        )
        tool_defs = self._tool_registry.to_tool_definitions(ctx)
        profile = resolve_profile(ctx)
        tool_defs = filter_by_profile(tool_defs, profile)
        # layered intentionally — policy first, profile second.
        log.debug(
            "tool_policy.profile_post",
            allowed_tool_count=len(tool_defs),
            denied_count=len(ctx.denied_tools) if ctx else 0,
            profile=profile.value,
        )
        if metadata is not None:
            metadata["tool_profile"] = profile.value
        known_skill_names: set[str] = set()
        if self._skill_loader is not None:
            try:
                known_skill_names = {
                    skill.name
                    for skill in self._skill_loader.load_all()
                    if not getattr(skill, "disable_model_invocation", False)
                }
            except Exception:
                known_skill_names = set()
        tool_handler = build_tool_handler(
            self._tool_registry,
            ctx,
            known_skill_names=known_skill_names,
        )
        return tool_defs, tool_handler

    def _filter_tool_defs_by_capability(self, tool_defs: list) -> list:
        """Compatibility shim; runtime capability filtering is resolved in ToolContext."""
        return tool_defs

    def _apply_runtime_capability_denies(self, ctx: ToolContext) -> ToolContext:
        from opensquilla.tools.policy import (
            ToolSurfaceCapabilities,
            detect_runtime_tool_surface_capabilities,
            resolve_runtime_tool_surface,
        )

        detected = detect_runtime_tool_surface_capabilities(
            channel_backing=(
                ctx.caller_kind in {CallerKind.CHANNEL, CallerKind.WEB}
                and bool(ctx.channel_id)
            )
        )
        capabilities = ToolSurfaceCapabilities(
            session_manager=getattr(self, "_session_manager", None) is not None,
            task_runtime=detected.task_runtime,
            scheduler=detected.scheduler,
            gateway_config=getattr(self, "_config", None) is not None,
            channel_backing=detected.channel_backing,
            image_generation=detected.image_generation,
        )
        return resolve_runtime_tool_surface(ctx, capabilities=capabilities)

    @staticmethod
    def _extra_context_for_tool_context(ctx: ToolContext | None) -> dict[str, str]:
        if ctx is None or ctx.caller_kind is not CallerKind.SUBAGENT:
            return {}
        return {"Subagent Task Protocol": _SUBAGENT_TASK_PROTOCOL}

    @staticmethod
    def _merge_extra_prompt_context(
        base: dict[str, str] | None,
        extra: dict[str, str],
    ) -> dict[str, str] | None:
        if not extra:
            return base
        if base is None:
            return dict(extra)
        merged = dict(base)
        merged.update(extra)
        return merged

    @staticmethod
    def _render_volatile_block(
        daily_notes: dict[str, str] | None,
        workspace_files: dict[str, str] | None,
        extra_context: dict[str, str] | None,
        prompt_mode: str = "full",
        wrap_untrusted_workspace: bool = True,
    ) -> str:
        """Render per-turn / per-day volatile content as the dynamic suffix.

        Replaces three previously-cacheable blocks once carried by
        the prior ``identity/templates/system_prompt.j2`` template:

        1. ``## Recent Notes`` (daily_notes) — gated on prompt_mode != minimal.
        2. ``## Workspace Files (injected)`` — gated on prompt_mode != minimal,
           with SOUL.md / IDENTITY.md filtered out (parsed elsewhere into
           AgentProfile.identity).
        3. ``## <key>`` blocks for each ``extra_context`` entry (no gating).

        Each section's bytes match what the prior Jinja render produced for
        the same inputs (verified in
        ``tests/test_engine/test_prompt_cache.py::TestVolatileFieldsInSuffix``).
        Sections are joined directly with no separator — adjacent ``\\n\\n``
        terminators in each section already provide the visual break, the
        same way the prior template rendered them inline. The final result
        is right-stripped of newlines so it slots cleanly into the dynamic
        suffix (``base + "\\n\\n" + suffix`` is reassembled downstream).
        """
        sections: list[str] = []

        # 1. ## Recent Notes (daily_notes), suppressed in minimal mode.
        if daily_notes and prompt_mode != "minimal":
            buf = "## Recent Notes\n\n"
            for filename, content in daily_notes.items():
                buf += f"### {filename}\n\n{content}\n\n"
            sections.append(buf)

        # 2. ## Workspace Files (injected), suppressed in minimal mode.
        # SOUL.md / IDENTITY.md are filtered (parsed elsewhere into
        # AgentProfile.identity); if every entry is filtered out, no header
        # is emitted at all so the volatile suffix doesn't carry a stranded
        # bare heading whose tuple-return would later trip downstream
        # consumers (empty-suffix invariant).
        if workspace_files and prompt_mode != "minimal":
            visible = {
                filename: content
                for filename, content in workspace_files.items()
                if filename not in ("SOUL.md", "IDENTITY.md")
            }
            if visible:
                buf = "## Workspace Files (injected)\n\n"
                # Filenames are masked as ``### Workspace Context N`` so the
                # template surface mirrors pilot's filename-non-exposure
                # convention (commit 93dfb8a). BOOTSTRAP.md is the exception:
                # it gets a named heading so the model recognizes it as a
                # one-shot setup ritual and removes the file on completion
                # (see identity/templates/bootstrap/BOOTSTRAP.md).
                context_index = 0
                for filename, content in visible.items():
                    if filename == "BOOTSTRAP.md":
                        buf += f"### One-Shot Workspace Bootstrap\n\n{content}\n\n"
                        continue
                    context_index += 1
                    rendered_content = (
                        injection_guard.wrap_untrusted(content, source=f"workspace:{filename}")
                        if wrap_untrusted_workspace
                        else content
                    )
                    buf += f"### Workspace Context {context_index}\n\n{rendered_content}\n\n"
                sections.append(buf)

        # 3. extra_context — emitted as ## <key> blocks regardless of mode.
        if extra_context:
            buf = ""
            for key, value in extra_context.items():
                buf += f"## {key}\n\n{value}\n\n"
            if buf:
                sections.append(buf)

        if not sections:
            return ""
        return "".join(sections).rstrip("\n")

    def _assemble_prompt(
        self,
        agent_id: str,
        tool_defs: list,
        session_key: str | None = None,
        semantic_message: str | None = None,
        extra_context: dict[str, str] | None = None,
        prompt_metadata: dict[str, Any] | None = None,
        bootstrap_context_mode: str | None = None,
    ) -> str | tuple[str, str]:
        """Assemble identity system prompt via Jinja2 template.

        Uses frozen snapshot when available (keyed by agent_id + session_key),
        falls back to live disk reads for backwards compatibility.

        Returns ``str`` for the prompt-cache-stable case; returns
        ``(base, dynamic_context)`` only when daily notes, workspace files, or
        tool-context blocks need to stay outside the cacheable prefix.
        """
        from opensquilla.identity.parser import parse_agents, parse_identity, parse_soul
        from opensquilla.identity.prompt import assemble_system_prompt
        from opensquilla.identity.types import AgentIdentity, AgentProfile
        from opensquilla.identity.workspace import (
            filter_workspace_filenames_for_session,
            filter_workspace_files_for_session,
            load_workspace_files_budgeted_with_report,
        )

        configured_agent_name = getattr(self._config, "agent_name", None) if self._config else None
        agent_name = (
            configured_agent_name.strip()
            if isinstance(configured_agent_name, str) and configured_agent_name.strip()
            else None
        )
        bootstrap_workspace_dir = self._resolve_bootstrap_workspace_dir(agent_id)
        bootstrap_context_key = bootstrap_context_mode or "full"
        bootstrap_snap_key = (agent_id, session_key, bootstrap_context_key) if session_key else None
        bootstrap_snap = (
            self._bootstrap_snapshots.get(bootstrap_snap_key)
            if bootstrap_snap_key is not None
            else None
        )
        if bootstrap_snap is not None:
            workspace_files = dict(bootstrap_snap.workspace_files)
            visible_bootstrap_report = list(bootstrap_snap.report)
        else:
            safety_cfg = getattr(self._config, "safety", None) if self._config else None
            bootstrap_filenames = (
                ("HEARTBEAT.md",)
                if bootstrap_context_mode == "heartbeat_light"
                else filter_workspace_filenames_for_session(None, session_key)
            )
            if bootstrap_context_mode == "unattended":
                bootstrap_filenames = tuple(
                    name for name in bootstrap_filenames if name != "BOOTSTRAP.md"
                )
            loaded_workspace_files, bootstrap_report = load_workspace_files_budgeted_with_report(
                str(bootstrap_workspace_dir),
                per_file_max_chars=self._resolve_bootstrap_max_chars(),
                total_max_chars=self._resolve_bootstrap_total_max_chars(),
                filenames=bootstrap_filenames,
                injection_scan_mode=getattr(safety_cfg, "injection_scan_mode", "report"),
            )
            workspace_files = filter_workspace_files_for_session(
                loaded_workspace_files,
                session_key,
            )
            subagents_cfg = getattr(self._config, "subagents", None) if self._config else None
            if (
                session_key
                and is_subagent_key(session_key)
                and getattr(subagents_cfg, "prompt_compact", False)
            ):
                workspace_files = {
                    name: content
                    for name, content in workspace_files.items()
                    if name in {"AGENTS.md", "TOOLS.md"}
                }
            visible_bootstrap_report = [
                report for report in bootstrap_report if report.filename in workspace_files
            ]
            if bootstrap_snap_key is not None:
                self._bootstrap_snapshots[bootstrap_snap_key] = BootstrapSnapshot(
                    workspace_files=dict(workspace_files),
                    report=list(visible_bootstrap_report),
                )
        memory_source_dir = self._resolve_memory_source_dir(agent_id)
        private_memory_allowed = allows_private_memory_prompt_injection(session_key)

        # Use frozen snapshot if available, otherwise read from disk
        snap_key = (agent_id, session_key) if session_key else None
        snap = self._memory_snapshots.get(snap_key) if snap_key else None
        if not private_memory_allowed:
            memory_text = None
            daily = {}
        elif snap is not None:
            memory_text = snap.memory_md
            daily = snap.daily_notes
        else:
            daily = self._load_daily_notes(memory_source_dir)
            memory_text = self._load_memory_md(memory_source_dir)
        if prompt_metadata is not None:
            prompt_metadata["memory_md_present"] = memory_text is not None
            prompt_metadata["injected_workspace_files_count"] = len(workspace_files)
            prompt_metadata["bootstrap_files"] = visible_bootstrap_report
            if not private_memory_allowed:
                prompt_metadata["memory_prompt_injection_skipped"] = "session-scope"
            prompt_metadata["retrieval_mode"] = "fts_only"

        soul_doc = parse_soul(workspace_files["SOUL.md"]) if "SOUL.md" in workspace_files else None
        identity_fields = (
            parse_identity(workspace_files["IDENTITY.md"])
            if "IDENTITY.md" in workspace_files
            else None
        )
        agents_doc = (
            parse_agents(workspace_files["AGENTS.md"]) if "AGENTS.md" in workspace_files else None
        )
        if agent_name is None and identity_fields is not None:
            agent_name = identity_fields.name
        prompt_mode = "full"
        tools_cfg = getattr(self._config, "tools", None)
        if getattr(tools_cfg, "profile", None) == "memory_only":
            prompt_mode = "minimal"

        agent_profile = AgentProfile(
            agent_id=agent_id,
            identity=AgentIdentity(
                name=agent_name,
                emoji=identity_fields.emoji if identity_fields else None,
                theme=identity_fields.theme if identity_fields else None,
                avatar=identity_fields.avatar if identity_fields else None,
                soul=soul_doc,
                identity_fields=identity_fields,
            ),
            agents_doc=agents_doc,
            workspace_files=workspace_files,
            prompt_mode=prompt_mode,
        )
        os_name = os.uname().sysname if hasattr(os, "uname") else platform.system()
        runtime_info = {
            "os": os_name,
            "shell": os.environ.get("SHELL", ""),
            "workspace_dir": str(bootstrap_workspace_dir),
        }
        base_prompt = assemble_system_prompt(
            agent_profile,
            tools=[td.name for td in tool_defs] if tool_defs else None,
            memory=memory_text,
            runtime_info=runtime_info,
            docs_path=self._resolve_docs_path(),
            heartbeat_prompt=getattr(self._config, "heartbeat_prompt", None),
        )
        # daily_notes, workspace_files, and extra_context are per-turn /
        # per-day volatile content. Keeping them in the cacheable base
        # invalidates the prompt-cache prefix every time any of them
        # changes (every day for daily_notes, every workspace edit for
        # workspace_files, every tool_context shift for extra_context).
        # Render them into the dynamic suffix instead so the base hash
        # stays stable across those rotations.
        dynamic_blocks: list[str] = []
        volatile_block = self._render_volatile_block(
            daily_notes=daily,
            workspace_files=workspace_files,
            extra_context=extra_context,
            prompt_mode=prompt_mode,
            wrap_untrusted_workspace=getattr(
                getattr(self._config, "safety", None),
                "wrap_untrusted_workspace",
                True,
            ),
        )
        if volatile_block:
            dynamic_blocks.append(volatile_block)

        if dynamic_blocks:
            return base_prompt, "\n\n".join(dynamic_blocks)
        return base_prompt

    @staticmethod
    def _resolve_docs_path() -> str | None:
        return None

    def _resolve_memory_source_dir(self, agent_id: str):
        from opensquilla.agents.scope import resolve_agent_memory_source_dir

        source = getattr(getattr(self._config, "memory", None), "source", "state")
        return resolve_agent_memory_source_dir(agent_id, self._config, source=source)

    def _resolve_bootstrap_workspace_dir(self, agent_id: str):
        from opensquilla.agents.scope import resolve_agent_workspace_dir

        return resolve_agent_workspace_dir(agent_id, self._config)

    def _resolve_bootstrap_max_chars(self) -> int:
        value = getattr(self._config, "bootstrap_max_chars", None) if self._config else None
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return int(value)
        return 20_000

    def _resolve_bootstrap_total_max_chars(self) -> int:
        value = getattr(self._config, "bootstrap_total_max_chars", None) if self._config else None
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return int(value)
        return 50_000

    def _load_memory_md(self, workspace_dir: Any, max_chars: int | None = None) -> str | None:
        """Load MEMORY.md from agent workspace for system prompt injection."""
        from pathlib import Path

        if max_chars is None:
            max_chars = getattr(getattr(self._config, "memory", None), "inject_limit", 4000)
        root = Path(workspace_dir)
        memory_file = root / "MEMORY.md"
        if not memory_file.is_file():
            memory_file = root / "memory.md"
        if not memory_file.is_file():
            return None
        try:
            content = memory_file.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        if not content:
            return None
        if len(content) > max_chars:
            return content[:max_chars] + "\n..."
        return content

    def _load_daily_notes(self, workspace_dir: Any) -> dict[str, str]:
        from opensquilla.identity.workspace import load_daily_notes

        memory_cfg = getattr(self._config, "memory", None)
        return load_daily_notes(
            str(workspace_dir),
            per_note_max_chars=getattr(memory_cfg, "daily_note_max_chars", 4000),
            total_max_chars=getattr(memory_cfg, "daily_notes_total_max_chars", 8000),
        )

    async def _run_pipeline(
        self,
        message: str,
        session_key: str,
        provider: Any,
        cloned_selector: Any,
        tool_defs: list,
        base_prompt: str | tuple[str, str],
        attachments: list[dict],
        semantic_message: str | None = None,
        ingress_pipeline_steps: list[PipelineStepRecord] | None = None,
        prev_assistant_text: str | None = None,
        prev_assistant_usage: dict[str, Any] | None = None,
        history_user_texts: list[str] | None = None,
        flags_text_override: str | None = None,
        tool_context: ToolContext | None = None,
    ) -> tuple[Any, Any]:
        """Run the pre-turn pipeline and re-resolve provider if model changed.

        Pre-seeds ``turn.metadata['pipeline_steps']`` with any
        ``ingress_pipeline_steps`` recorded by the turn-ingress helper
        (under DecisionLog ownership). The engine pipeline's
        ``setdefault`` then appends step records to the same list, so
        ``DecisionEntry`` ends up with ingress records first followed by
        engine pipeline records.
        """
        from opensquilla.engine.pipeline import TurnContext, run_pipeline
        from opensquilla.engine.steps import (
            apply_prompt_cache,
            apply_squilla_router,
            filter_skills,
            inject_platform_hint,
            inject_subagent_grounding,
            observe_reasoning_hint,
            resolve_model,
        )

        initial_metadata: dict[str, Any] = {"skill_loader": self._skill_loader}
        if ingress_pipeline_steps:
            initial_metadata["pipeline_steps"] = list(ingress_pipeline_steps)
        if prev_assistant_text:
            initial_metadata["router_prev_assistant_text"] = prev_assistant_text
        if prev_assistant_usage:
            initial_metadata["router_prev_assistant_usage"] = dict(prev_assistant_usage)
        if history_user_texts:
            initial_metadata["router_history_user_texts"] = list(history_user_texts)
        if flags_text_override:
            initial_metadata["router_flags_text_override"] = flags_text_override
        if tool_context is not None:
            initial_metadata["channel_kind"] = tool_context.channel_kind
            initial_metadata["channel_id"] = tool_context.channel_id

        turn = TurnContext(
            message=message,
            session_key=session_key,
            config=self._config,
            provider=provider,
            model="",
            tool_defs=tool_defs,
            system_prompt=base_prompt,
            attachments=attachments,
            metadata=initial_metadata,
            raw_message=semantic_message,
        )
        turn = await run_pipeline(
            turn,
            [
                resolve_model,
                apply_squilla_router,
                observe_reasoning_hint,
                filter_skills,
                inject_subagent_grounding,
                inject_platform_hint,
                apply_prompt_cache,
            ],
        )

        # Apply routed model back to cloned selector (local, not shared)
        if turn.model and cloned_selector is not None:
            cloned_selector.override_model(turn.model)
            provider = cloned_selector.resolve()

        return turn, provider

    async def _router_previous_assistant_context(
        self,
        session_key: str,
        *,
        exclude_last_user: bool = False,
    ) -> dict[str, Any]:
        """Return transcript context for the V4 router, excluding the current user turn."""
        if self._session_manager is None:
            return {}
        get_transcript = getattr(self._session_manager, "get_transcript", None)
        if not callable(get_transcript):
            return {}
        try:
            transcript = get_transcript(session_key)
            if inspect.isawaitable(transcript):
                transcript = await transcript
        except Exception:  # noqa: BLE001 - router context must never block a turn
            log.debug("turn_runner.router_context_failed", session_key=session_key)
            return {}
        entries = list(transcript or [])
        user_texts: list[str] = []
        for index, entry in enumerate(entries):
            if getattr(entry, "role", None) != "user":
                continue
            if exclude_last_user and index == len(entries) - 1:
                continue
            content = getattr(entry, "content", None)
            if not isinstance(content, str) or not content.strip():
                continue
            unpacked = self._maybe_unpack_attachments(content)
            text = unpacked.strip() if isinstance(unpacked, str) else content.strip()
            if len(text) > _ROUTER_HISTORY_USER_MAX_CHARS:
                text = text[-_ROUTER_HISTORY_USER_MAX_CHARS:]
            user_texts.append(text)

        context: dict[str, Any] = {}
        if user_texts:
            context["history_user_texts"] = user_texts[-_ROUTER_HISTORY_USER_MAX_TURNS:]

        for entry in reversed(entries):
            if getattr(entry, "role", None) != "assistant":
                continue
            content = getattr(entry, "content", None)
            if not isinstance(content, str) or not content.strip():
                continue
            text = content.strip()
            if len(text) > _ROUTER_PREV_ASSISTANT_MAX_CHARS:
                text = text[-_ROUTER_PREV_ASSISTANT_MAX_CHARS:]
            context["prev_assistant_text"] = text
            token_count = getattr(entry, "token_count", None)
            if (
                isinstance(token_count, int)
                and not isinstance(token_count, bool)
                and token_count > 0
            ):
                context["prev_assistant_usage"] = {"output_tokens": token_count}
            return context
        return context

    def _resolve_prompt_config(self, turn: Any) -> tuple[str, list | None, str | None]:
        """Resolve final system prompt and cache breakpoints from pipeline output."""
        final_prompt = turn.system_prompt
        cache_breakpoints = None
        request_context_prompt = None

        if turn.metadata.get("cache_enabled") and isinstance(final_prompt, tuple):
            base, dynamic = final_prompt
            cache_breakpoints = [{"text": base, "cache": "true"}]
            final_prompt = base
            request_context_prompt = dynamic
        elif turn.metadata.get("cache_enabled") and isinstance(final_prompt, str):
            base = turn.metadata.get("cache_base_prompt") or final_prompt
            if isinstance(base, str) and base:
                cache_breakpoints = [{"text": base, "cache": "true"}]
        elif isinstance(final_prompt, tuple):
            final_prompt = "\n\n".join(final_prompt)

        return final_prompt, cache_breakpoints, request_context_prompt

    def _collect_session_flush_metadata(
        self,
        agent_id: str,
        *,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        """Collect last SessionFlush extraction attribution for decision logs."""

        svc = self._session_flush_service
        get_stats = getattr(svc, "last_extraction_stats", None)
        if not callable(get_stats):
            return {}
        try:
            try:
                stats = get_stats(agent_id, session_key) if session_key is not None else get_stats()
            except TypeError:
                stats = get_stats()
        except Exception:
            return {}
        if not isinstance(stats, dict) or not stats:
            return {}
        stat_agent = stats.get("agent_id")
        if stat_agent and str(stat_agent) != agent_id:
            return {}
        stat_session_key = stats.get("session_key")
        if session_key and stat_session_key and str(stat_session_key) != session_key:
            return {}
        fallback_reason = str(stats.get("fallback_reason") or "")
        return {
            "session_flush_extraction_model": str(stats.get("extraction_model") or ""),
            "session_flush_fallback_used": bool(fallback_reason),
            "session_flush_fallback_reason": fallback_reason,
        }

    def _emit_decision_entry(
        self,
        *,
        turn_id: str,
        session_key: str,
        session_id: str | None = None,
        message: str,
        final_prompt: str,
        tool_defs: list[Any],
        turn_obj: Any | None,
        provider: Any | None,
        resolved_model: str,
        turn_started_at: float,
        prompt_report: PromptReport | None = None,
        session_intent: str | None = None,
        done_event: DoneEvent | None = None,
        trace_id: str | None = None,
    ) -> None:
        """Write one DecisionEntry for this turn (best-effort, never raises).

        Pipeline steps are read off ``turn_obj.metadata['pipeline_steps']``
        (populated by :func:`pipeline.run_pipeline`). Token counts are pulled
        from ``usage_tracker`` when available; otherwise default to 0.
        """

        try:
            tool_names = [getattr(td, "name", "") for td in tool_defs]
            prompt_hash, system_prompt_hash, tool_list_hash = compute_hashes(
                message, final_prompt, [n for n in tool_names if n]
            )

            pipeline_steps: list[PipelineStepRecord] = []
            if turn_obj is not None:
                pipeline_steps = list(turn_obj.metadata.get("pipeline_steps", []))

            # Per-turn token counts come from the final DoneEvent (which carries
            # cumulative input_tokens / output_tokens for the whole turn). The
            # legacy code looked up `usage_tracker.last_input_tokens`, but
            # UsageTracker exposes only per-session aggregates and never had
            # `last_input_tokens` / `last_output_tokens` attributes — the
            # getattr defaults silently produced zero on every turn. See
            # engine/usage.py for the actual UsageTracker surface.
            if done_event is not None:
                tokens_input = int(done_event.input_tokens or 0)
                tokens_output = int(done_event.output_tokens or 0)
            else:
                tokens_input = 0
                tokens_output = 0

            latency_ms = int((time.monotonic() - turn_started_at) * 1000)
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            tool_choice = "auto" if tool_defs else "none"
            provider_name = type(provider).__name__ if provider is not None else ""

            # Populate SavingsTelemetry
            savings_telemetry = SavingsTelemetry()
            if turn_obj is not None:
                metadata = turn_obj.metadata
                router_cfg = getattr(self._config, "squilla_router", None)
                squilla_router_tiers = getattr(router_cfg, "tiers", {})

                # Squilla router
                savings_telemetry.routed_model = metadata.get("routed_model")
                savings_telemetry.baseline_model = metadata.get("baseline_model")
                savings_telemetry.routing_confidence = metadata.get("routing_confidence")
                savings_telemetry.routing_savings_pct = metadata.get("savings_pct")

                _max_p = float(metadata.get("savings_max_price_per_m") or 0.0)
                _rte_p = float(metadata.get("savings_routed_price_per_m") or 0.0)
                if done_event is not None:
                    savings_telemetry.routing_savings_usd_estimated_vs_baseline = (
                        _compute_route_input_savings_usd(
                            _max_p,
                            _rte_p,
                            done_event.input_tokens,
                        )
                    )

                # Tool-result compression (values will be set in agent.py)
                savings_telemetry.tool_compression_applied = metadata.get(
                    "tool_compression_applied",
                    False,
                )
                savings_telemetry.tool_compression_calls = metadata.get("tool_compression_calls", 0)
                savings_telemetry.tool_compression_tokens_before = metadata.get(
                    "tool_compression_tokens_before",
                    0,
                )
                savings_telemetry.tool_compression_tokens_after = metadata.get(
                    "tool_compression_tokens_after",
                    0,
                )
                savings_telemetry.tool_compression_tokens_saved = metadata.get(
                    "tool_compression_tokens_saved",
                    0,
                )

                # Thinking mode
                savings_telemetry.thinking_mode = metadata.get("thinking_mode")

                # Short-reply prompt enforcement
                savings_telemetry.short_reply_active = metadata.get("prompt_policy") == "P0"
                if savings_telemetry.short_reply_active and done_event is not None:
                    estimated_output_savings_pct = getattr(
                        router_cfg,
                        "estimated_output_savings_pct",
                        0.03,
                    )
                    output_side_tokens = _non_negative_int(
                        done_event.output_tokens
                    ) + _non_negative_int(done_event.reasoning_tokens)
                    restored_output_tokens = _restored_output_side_tokens(
                        output_side_tokens,
                        metadata,
                        estimated_output_savings_pct,
                    )
                    savings_telemetry.short_reply_savings_tokens_estimated = round(
                        max(0.0, restored_output_tokens - output_side_tokens)
                    )
                    baseline = _select_savings_baseline_model(
                        squilla_router_tiers,
                        _non_negative_int(done_event.input_tokens)
                        + _non_negative_int(
                            metadata.get("tool_compression_tokens_saved"),
                        ),
                        restored_output_tokens,
                    )
                    if baseline.price.output_per_m > 0:
                        savings_telemetry.short_reply_savings_usd_estimated_vs_baseline = round(
                            (
                                savings_telemetry.short_reply_savings_tokens_estimated
                                / 1_000_000
                            )
                            * baseline.price.output_per_m,
                            6,
                        )

                # Cache Hit — fires when EITHER OpenSquilla's prompt-cache split
                # infra reports a hit OR the upstream provider returns
                # `cached_tokens > 0` (OpenRouter prompt-cache passthrough).
                # Without the OR, provider-side cache hits were silently
                # losing the active flag while still recording tokens_saved.
                provider_cache_hit = done_event is not None and (done_event.cached_tokens or 0) > 0
                opensquilla_cache_hit = metadata.get("cache_mode") == "hit"
                event_cache_hit = bool(getattr(done_event, "cache_hit_active", False))
                savings_telemetry.cache_hit_active = (
                    event_cache_hit or provider_cache_hit or opensquilla_cache_hit
                )
                if done_event is not None:
                    savings_telemetry.cache_hit_tokens_saved = done_event.cached_tokens
                    if savings_telemetry.cache_hit_tokens_saved > 0 and _max_p > 0:
                        savings_telemetry.cache_hit_usd_estimated_vs_baseline = round(
                            (savings_telemetry.cache_hit_tokens_saved / 1_000_000) * _max_p, 6
                        )

                savings_telemetry.billed_cost_usd = (
                    done_event.billed_cost if done_event is not None else None
                )
                savings_telemetry.cost_usd = (
                    done_event.cost_usd if done_event is not None else None
                )
                savings_telemetry.cost_source = (
                    normalize_event_cost_source(
                        done_event.cost_source,
                        input_tokens=done_event.input_tokens,
                        output_tokens=done_event.output_tokens,
                        cache_read_tokens=done_event.cached_tokens,
                        cache_write_tokens=done_event.cache_write_tokens,
                        cost_usd=done_event.cost_usd,
                        billed_cost_usd=done_event.billed_cost,
                    )
                    if done_event is not None
                    else None
                )

                # Total savings is the comprehensive per-turn estimate used by
                # the popup. It intentionally excludes billed-cost and cache-hit
                # effects so it remains a token/price estimate.
                if done_event is not None:
                    savings_telemetry.total_savings_pct = done_event.total_savings_pct
                    savings_telemetry.total_savings_usd = done_event.total_savings_usd

            entry = DecisionEntry(
                turn_id=turn_id,
                session_key=session_key,
                session_id=session_id,
                session_intent=session_intent,
                trace_id=trace_id or turn_id,
                tool_profile=prompt_report.tool_profile if prompt_report else None,
                prompt_hash=prompt_hash,
                system_prompt_hash=system_prompt_hash,
                tool_list_hash=tool_list_hash,
                tool_choice=tool_choice,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                model=resolved_model,
                provider=provider_name,
                latency_ms=latency_ms,
                ts=ts,
                pipeline_steps=pipeline_steps,
                savings=savings_telemetry,
                system_chars=prompt_report.system_chars if prompt_report else 0,
                tool_count=prompt_report.tool_count if prompt_report else 0,
                tools_schema_chars=prompt_report.tools_schema_chars if prompt_report else 0,
                skill_count=prompt_report.skill_count if prompt_report else 0,
                skills_prompt_chars=prompt_report.skills_prompt_chars if prompt_report else 0,
                memory_md_present=prompt_report.memory_md_present if prompt_report else False,
                injected_workspace_files_count=(
                    prompt_report.injected_workspace_files_count if prompt_report else 0
                ),
                bootstrap_files=prompt_report.bootstrap_files if prompt_report else [],
                memory_mode_fingerprint=(
                    prompt_report.memory_mode_fingerprint if prompt_report else {}
                ),
                retrieval_mode=prompt_report.retrieval_mode if prompt_report else None,
                cache_mode=prompt_report.cache_mode if prompt_report else None,
                cache_base_hash=prompt_report.cache_base_hash if prompt_report else None,
                cache_dynamic_hash=(
                    prompt_report.cache_dynamic_hash if prompt_report else None
                ),
                cache_read_input_tokens=(
                    int(done_event.cached_tokens or 0) if done_event is not None else 0
                ),
                cache_creation_input_tokens=(
                    int(done_event.cache_write_tokens or 0) if done_event is not None else 0
                ),
                resolved_model=(
                    prompt_report.resolved_model if prompt_report else None
                )
                or resolved_model,
                alias_resolution_chain=(
                    prompt_report.alias_resolution_chain
                    if prompt_report and prompt_report.alias_resolution_chain
                    else ([resolved_model] if resolved_model else [])
                ),
                provider_after_rewrite=(
                    prompt_report.provider_after_rewrite if prompt_report else None
                )
                or provider_name,
                cache_legacy_hash=prompt_report.cache_legacy_hash if prompt_report else None,
                cache_shadow_final_hash=(
                    prompt_report.cache_shadow_final_hash if prompt_report else None
                ),
                cache_key_collision=(
                    prompt_report.cache_key_collision if prompt_report else False
                ),
                reasoning_hint_resolved=(
                    prompt_report.reasoning_hint_resolved if prompt_report else None
                ),
                cache_base_chars=prompt_report.cache_base_chars if prompt_report else 0,
                cache_dynamic_chars=prompt_report.cache_dynamic_chars if prompt_report else 0,
                runtime_context_hash=(
                    done_event.runtime_context_hash if done_event is not None else None
                ),
                runtime_context_chars=(
                    done_event.runtime_context_chars if done_event is not None else 0
                ),
                session_flush_extraction_model=(
                    prompt_report.session_flush_extraction_model if prompt_report else None
                ),
                session_flush_fallback_used=(
                    prompt_report.session_flush_fallback_used if prompt_report else False
                ),
                session_flush_fallback_reason=(
                    prompt_report.session_flush_fallback_reason if prompt_report else None
                ),
            )
            write_decision_entry(entry)
        except Exception as exc:  # pragma: no cover — observability must not break turns
            log.warning("decision_log.write_failed", error=str(exc))

    async def _maybe_compact_on_t3_upgrade(
        self,
        session_key: str,
        turn: TurnContext,
        context_window_tokens: int,
        *,
        compaction_provider: Any | None = None,
        compaction_model: str | None = None,
    ) -> str:
        """Flush memory and compact transcript when the router upgrades into t3.

        Returns a status string so the caller can distinguish non-applicable
        routes, flush failures that may still fall back to generic preflight,
        and compact failures that should trip the circuit without retrying.
        """
        router_cfg = getattr(self._config, "squilla_router", None)
        if not getattr(router_cfg, "upgrade_to_t3_compaction_enabled", False):
            return _T3_NOT_APPLICABLE

        routed_tier = turn.metadata.get("routed_tier")
        if routed_tier != "t3":
            return _T3_NOT_APPLICABLE

        if not turn.metadata.get("routing_applied", False):
            return _T3_NOT_APPLICABLE

        routing_extra = turn.metadata.get("routing_extra", {})
        previous = routing_extra.get("previous_tier")
        if previous is None:
            final = routing_extra.get("final_tier")
            base = routing_extra.get("base_tier")
            if final == "t3" and base in {"t0", "t1", "t2"}:
                previous = base
            else:
                return _T3_NOT_APPLICABLE

        if previous not in {"t0", "t1", "t2"}:
            return _T3_NOT_APPLICABLE

        if session_key.startswith(("cron:", "subagent:")):
            return _T3_NOT_APPLICABLE

        if self._session_manager is None:
            return _T3_NOT_APPLICABLE

        if self._compaction_circuit_open(session_key):
            return _T3_HANDLED

        try:
            transcript = await self._session_manager.get_transcript(session_key)
        except KeyError:
            return _T3_HANDLED
        if not transcript:
            return _T3_HANDLED

        log.info(
            "t3_upgrade_compaction.triggered",
            session_key=session_key,
            previous_tier=previous,
            final_tier="t3",
            context_window_tokens=context_window_tokens,
        )

        if self._pre_compaction_flush_enabled():
            if self._session_flush_service is None:
                log.warning(
                    "t3_upgrade_compaction.flush_failed",
                    session_key=session_key,
                    error="flush_service_unavailable",
                )
                self._record_compaction_failure(session_key)
                return _T3_FLUSH_FAILED

            flush_t0 = time.monotonic()
            try:
                from opensquilla.session.keys import parse_agent_id

                receipt = await self._session_flush_service.execute(
                    transcript,
                    session_key,
                    agent_id=parse_agent_id(session_key),
                    message_window=0,
                    segment_mode="auto",
                    timeout=self._pre_compaction_flush_timeout_seconds(),
                )
                if not self._flush_receipt_allows_destructive_compaction(receipt):
                    log.warning(
                        "t3_upgrade_compaction.flush_failed",
                        session_key=session_key,
                        error=getattr(receipt, "error", None) or "degraded_flush_receipt",
                        mode=getattr(receipt, "mode", "unknown"),
                        integrity_status=getattr(receipt, "integrity_status", None),
                        indexed_chunk_count=getattr(receipt, "indexed_chunk_count", None),
                        output_coverage_status=getattr(
                            receipt,
                            "output_coverage_status",
                            None,
                        ),
                        invalid_candidate_count=getattr(
                            receipt,
                            "invalid_candidate_count",
                            None,
                        ),
                        candidate_missing_ids=getattr(receipt, "candidate_missing_ids", None),
                        obligation_status=getattr(receipt, "obligation_status", None),
                        obligation_missing_ids=getattr(receipt, "obligation_missing_ids", None),
                    )
                    self._record_compaction_failure(session_key)
                    return _T3_FLUSH_FAILED
                log.info(
                    "t3_upgrade_compaction.flush_done",
                    session_key=session_key,
                    mode=getattr(receipt, "mode", "unknown"),
                    message_count=getattr(receipt, "message_count", 0),
                    duration_ms=int((time.monotonic() - flush_t0) * 1000),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "t3_upgrade_compaction.flush_failed",
                    session_key=session_key,
                    error=str(exc),
                )
                self._record_compaction_failure(session_key)
                return _T3_FLUSH_FAILED

        try:
            compaction_config = None
            if compaction_provider is not None or compaction_model:
                from opensquilla.session.compaction import build_compaction_config_from_provider

                compaction_config = build_compaction_config_from_provider(
                    compaction_provider,
                    model_override=compaction_model,
                    compaction_config=getattr(getattr(self, "_config", None), "compaction", None),
                )
            from opensquilla.session.compaction import call_compact_with_optional_config

            result = await call_compact_with_optional_config(
                self._session_manager.compact,
                session_key,
                context_window_tokens,
                compaction_config,
            )
            self._record_compaction_success(session_key)
            if result:
                notify_compaction(session_key)
            log.info(
                "t3_upgrade_compaction.compact_done",
                session_key=session_key,
                summary_produced=bool(result),
                summary_length=len(result) if result else 0,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "t3_upgrade_compaction.compact_failed",
                session_key=session_key,
                error=str(exc),
            )
            self._record_compaction_failure(session_key)
            return _T3_COMPACT_FAILED

        return _T3_HANDLED

    async def _maybe_preflight_compact(
        self,
        session_key: str,
        context_window_tokens: int,
        *,
        compaction_provider: Any | None = None,
        compaction_model: str | None = None,
    ) -> None:
        """Compact proactively if session history exceeds token budget.

        Called before _load_history(). Uses SessionManager.compact() directly
        because no Agent state exists yet — the DB is the sole source of truth.
        Safe to re-compact from DB at this point (no double-compaction risk).
        """
        if self._session_manager is None:
            return
        # Skip ephemeral sessions
        if session_key.startswith(("cron:", "subagent:")):
            return
        if self._compaction_circuit_open(session_key):
            return
        try:
            transcript = await self._session_manager.get_transcript(session_key)
        except KeyError:
            return  # session doesn't exist yet
        if not transcript:
            return

        from opensquilla.session.tokenizer import estimate_tokens

        total_tokens = sum(estimate_tokens(e.content or "") for e in transcript)
        ratio = self._preflight_compact_ratio()
        threshold = int(context_window_tokens * ratio)
        if total_tokens <= threshold:
            return

        log.info(
            "preflight_compaction.triggered",
            session_key=session_key,
            total_tokens=total_tokens,
            threshold=threshold,
            ratio=ratio,
        )
        if self._pre_compaction_flush_enabled():
            if self._session_flush_service is None:
                log.warning(
                    "preflight_compaction.flush_failed",
                    session_key=session_key,
                    error="flush_service_unavailable",
                )
                self._record_compaction_failure(session_key)
                return

            try:
                from opensquilla.session.keys import parse_agent_id

                receipt = await self._session_flush_service.execute(
                    transcript,
                    session_key,
                    agent_id=parse_agent_id(session_key),
                    message_window=0,
                    segment_mode="auto",
                    timeout=self._pre_compaction_flush_timeout_seconds(),
                )
                if not self._flush_receipt_allows_destructive_compaction(receipt):
                    log.warning(
                        "preflight_compaction.flush_failed",
                        session_key=session_key,
                        error=getattr(receipt, "error", None) or "degraded_flush_receipt",
                        mode=getattr(receipt, "mode", "unknown"),
                        integrity_status=getattr(receipt, "integrity_status", None),
                        indexed_chunk_count=getattr(receipt, "indexed_chunk_count", None),
                        output_coverage_status=getattr(
                            receipt,
                            "output_coverage_status",
                            None,
                        ),
                        invalid_candidate_count=getattr(
                            receipt,
                            "invalid_candidate_count",
                            None,
                        ),
                        candidate_missing_ids=getattr(receipt, "candidate_missing_ids", None),
                        obligation_status=getattr(receipt, "obligation_status", None),
                        obligation_missing_ids=getattr(receipt, "obligation_missing_ids", None),
                    )
                    self._record_compaction_failure(session_key)
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "preflight_compaction.flush_failed",
                    session_key=session_key,
                    error=str(exc),
                )
                self._record_compaction_failure(session_key)
                return
        compaction_config = None
        if compaction_provider is not None or compaction_model:
            from opensquilla.session.compaction import build_compaction_config_from_provider

            compaction_config = build_compaction_config_from_provider(
                compaction_provider,
                model_override=compaction_model,
                compaction_config=getattr(getattr(self, "_config", None), "compaction", None),
            )
        from opensquilla.session.compaction import call_compact_with_optional_config

        try:
            result = await call_compact_with_optional_config(
                self._session_manager.compact,
                session_key,
                context_window_tokens,
                compaction_config,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "preflight_compaction.compact_failed",
                session_key=session_key,
                error=str(exc),
            )
            self._record_compaction_failure(session_key)
            return
        self._record_compaction_success(session_key)
        if result:
            notify_compaction(session_key)

    def _pre_compaction_flush_enabled(self) -> bool:
        from opensquilla.memory.flush_config import is_session_flush_enabled

        if not is_session_flush_enabled():
            return False

        memory_cfg = getattr(self._config, "memory", None)
        if memory_cfg is None:
            return self._session_flush_service is not None

        raw_enabled = getattr(memory_cfg, "flush_enabled", True)
        if isinstance(raw_enabled, str):
            return raw_enabled.strip().lower() not in {"0", "false", "no", "off"}
        return bool(raw_enabled)

    def _pre_compaction_flush_timeout_seconds(self) -> float:
        memory_cfg = getattr(self._config, "memory", None)
        raw_timeout = getattr(memory_cfg, "flush_timeout_seconds", 5.0)
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            return 5.0
        return max(timeout, 0.0)

    @staticmethod
    def _receipt_value(receipt: Any, name: str, default: Any) -> Any:
        if isinstance(receipt, Mapping):
            return receipt.get(name, default)
        return getattr(receipt, name, default)

    @staticmethod
    def _receipt_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _flush_receipt_allows_destructive_compaction(self, receipt: Any) -> bool:
        if self._receipt_value(receipt, "mode", None) != "llm":
            return False
        if self._receipt_int(self._receipt_value(receipt, "indexed_chunk_count", 0)) <= 0:
            return False
        integrity_status = str(
            self._receipt_value(receipt, "integrity_status", "unverified") or "unverified"
        )
        if integrity_status != "ok":
            return False
        output_coverage_status = str(
            self._receipt_value(receipt, "output_coverage_status", "unverified")
            or "unverified"
        )
        if output_coverage_status not in _SAFE_FLUSH_OUTPUT_COVERAGE_STATUSES:
            return False
        if self._receipt_int(self._receipt_value(receipt, "invalid_candidate_count", 0)) > 0:
            return False
        if self._receipt_value(receipt, "candidate_missing_ids", []):
            return False
        obligation_status = str(
            self._receipt_value(receipt, "obligation_status", "unverified") or "unverified"
        )
        if obligation_status not in _SAFE_FLUSH_OBLIGATION_STATUSES:
            return False
        return not self._receipt_value(receipt, "obligation_missing_ids", [])

    def _compaction_circuit_open(self, session_key: str) -> bool:
        state = getattr(self, "_compaction_failures", {}).get(session_key)
        if state is None or state.count < _COMPACTION_FAILURE_LIMIT:
            return False
        opened_at = state.opened_at if state.opened_at is not None else time.monotonic()
        cooldown_elapsed = time.monotonic() - opened_at
        if cooldown_elapsed >= _COMPACTION_CIRCUIT_COOLDOWN_SECONDS:
            log.info(
                "compaction_circuit.half_open",
                session_key=session_key,
                consecutive_failures=state.count,
                cooldown_elapsed_s=round(cooldown_elapsed, 1),
            )
            return False
        log.warning(
            "compaction_circuit.open",
            session_key=session_key,
            consecutive_failures=state.count,
            cooldown_remaining_s=round(
                _COMPACTION_CIRCUIT_COOLDOWN_SECONDS - cooldown_elapsed,
                1,
            ),
        )
        return True

    def _record_compaction_failure(self, session_key: str) -> None:
        if not hasattr(self, "_compaction_failures"):
            self._compaction_failures = {}
        state = self._compaction_failures.setdefault(session_key, _CompactionFailureState())
        state.count += 1
        state.opened_at = time.monotonic() if state.count >= _COMPACTION_FAILURE_LIMIT else None

    def _record_compaction_success(self, session_key: str) -> None:
        if not hasattr(self, "_compaction_failures"):
            self._compaction_failures = {}
        self._compaction_failures.pop(session_key, None)

    def _preflight_compact_ratio(self) -> float:
        raw_ratio = getattr(self._config, "preflight_compact_ratio", None)
        if raw_ratio is None:
            return _DEFAULT_PREFLIGHT_COMPACT_RATIO
        try:
            ratio = float(raw_ratio)
        except (TypeError, ValueError):
            return _DEFAULT_PREFLIGHT_COMPACT_RATIO
        if ratio <= 0.0 or ratio > 1.0:
            return _DEFAULT_PREFLIGHT_COMPACT_RATIO
        return ratio

    async def _load_history(
        self,
        agent: Agent,
        session_key: str,
        *,
        trim_last_user: bool = True,
    ) -> str | None:
        """Load existing transcript as agent history."""
        if self._session_manager is None:
            return None

        transcript = await self._session_manager.get_transcript(session_key)

        from opensquilla.engine.history import reconstruct_messages_from_entry
        from opensquilla.provider import Message

        history: list[Message] = []
        summary_markers: list[str] = []
        last_entry_was_user = False
        for entry in transcript:
            if (
                entry.role == "system"
                and entry.content
                and entry.content.startswith(_CONTEXT_SUMMARY_MARKER)
            ):
                summary_markers.append(_strip_context_summary_marker(entry.content))
                continue
            if entry.role not in ("user", "assistant"):
                continue
            raw_content = entry.content or ""
            # User messages may carry attachment envelopes; assistant messages
            # may carry artifact metadata. Both become text-only safe markers
            # for model-context replay.
            if raw_content and entry.role == "user":
                content: Any = self._maybe_unpack_attachments(raw_content)
            elif raw_content and entry.role == "assistant":
                content = self._maybe_unpack_assistant_artifacts(raw_content)
            else:
                content = raw_content
            history.extend(
                reconstruct_messages_from_entry(
                    entry.role,
                    content,
                    entry.tool_calls,
                    getattr(entry, "reasoning_content", None),
                )
            )
            last_entry_was_user = entry.role == "user"
        # Strip the caller-appended user turn only when the transcript really
        # ended on a user entry; an assistant entry that reconstructs into
        # assistant + user(tool_result) must keep its tool_result tail.
        if trim_last_user and last_entry_was_user and history and history[-1].role == "user":
            history.pop()
        if history:
            agent.set_history(history)
        return await self._compaction_summary_context(session_key, summary_markers)

    async def _compaction_summary_context(
        self,
        session_key: str,
        legacy_summary_markers: list[str],
    ) -> str | None:
        """Return durable compaction summaries as request-scoped context."""
        summary_texts: list[str] = []
        get_summaries = getattr(self._session_manager, "get_summaries", None)
        if callable(get_summaries):
            try:
                summaries = await get_summaries(session_key)
            except KeyError:
                summaries = []
            except Exception as exc:  # pragma: no cover - summary context is best-effort
                log.warning(
                    "compaction_summary_context.load_failed",
                    session_key=session_key,
                    error=str(exc),
                )
                summaries = []
            for summary in summaries:
                text = getattr(summary, "summary_text", "")
                if isinstance(text, str) and text.strip():
                    summary_texts.append(text)
        summary_texts.extend(legacy_summary_markers)
        return _format_compaction_summary_context(summary_texts)

    @staticmethod
    def _maybe_unpack_attachments(content: str) -> Any:
        """Reduce persisted attachment envelopes to text-only history.

        User messages with attachments are persisted as a JSON envelope
        ``{"text": "...", "attachments": [{"type": "image/png", "data": "<b64>"}...]}``
        in ``transcript_entries.content`` (see rpc_sessions._persist_user_message).
        Historical images must not be sent again on later turns: OpenRouter can
        route a text follow-up to a text model, and replaying an old image block
        then fails with "No endpoints found that support image input". Keep the
        original text and a compact non-image marker so the model knows an
        attachment existed without receiving its bytes.

        Returns the original string for non-envelope content so non-attachment
        history (assistant text, tool results) is unaffected. On any parse error,
        missing key, or invalid attachment entry, fall back to the original string
        to keep history loading crash-proof.
        """
        if not content or not content.lstrip().startswith("{"):
            return content
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return content
        if not isinstance(parsed, dict) or "text" not in parsed:
            return content
        text = parsed.get("text")
        if not isinstance(text, str):
            return content
        atts = parsed.get("attachments") or []
        if not isinstance(atts, list) or not atts:
            return text

        omitted: list[str] = []
        for att in atts:
            if not isinstance(att, dict):
                continue
            media_type = att.get("type") or att.get("mime") or att.get("media_type")
            if not (
                isinstance(media_type, str) and media_type in _ALLOWED_ENGINE_MEDIA_TYPES
            ):
                continue
            # Persisted attachment envelope: ``sha256_ref`` indicates the bytes live on
            # disk under media/transcripts/<session>/<sha>; for replay we
            # emit a marker (the engine never re-sends the bytes anyway).
            data = att.get("data")
            sha_ref = att.get("sha256_ref")
            missing_reason = att.get("missing_reason")
            if not (
                (isinstance(data, str) and data) or (isinstance(sha_ref, str) and sha_ref)
                or (isinstance(missing_reason, str) and missing_reason)
            ):
                continue
            name = att.get("name")
            fallback = "image" if media_type.startswith("image/") else "attachment"
            label = name if isinstance(name, str) and name.strip() else fallback
            omitted.append(f"[historical attachment omitted: {label} ({media_type})]")
        if not omitted:
            return text
        return "\n".join([text, *omitted]).strip()

    @staticmethod
    def _maybe_unpack_assistant_artifacts(content: str) -> str:
        if not content or not content.lstrip().startswith("{"):
            return content
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return content
        if not isinstance(parsed, dict) or "artifacts" not in parsed:
            return content
        text = parsed.get("text")
        artifacts = parsed.get("artifacts")
        if not isinstance(text, str) or not isinstance(artifacts, list):
            return content
        markers = [
            artifact_marker(artifact)
            for artifact in artifacts
            if isinstance(artifact, dict)
        ]
        if not markers:
            return text
        return "\n".join([text, *markers]).strip()

    @staticmethod
    def _attachment_media_root_from_config(config: Any | None) -> Path:
        attachments_cfg = getattr(config, "attachments", None)
        media_root_raw = getattr(attachments_cfg, "media_root", None)
        return Path(media_root_raw) if media_root_raw else Path(".opensquilla") / "media"

    def _attachment_media_root(self) -> Path:
        return self._attachment_media_root_from_config(self._config)

    @staticmethod
    def _build_attachment_messages(
        message: str,
        attachments: list[dict],
        *,
        media_root: Path | None = None,
    ) -> list | None:
        """Build a multimodal user message that carries the attachments.

        The engine sees one normalised attachment shape. Provider
        conversion is deliberately narrow:

          * ``image/*``           -> ``ContentBlockImage``
          * ``application/pdf``   -> local text extraction, then ``ContentBlockText``
          * text-family / json    -> ``ContentBlockText`` wrapped in an
                                     ``<file name="…" mime="…">…</file>``
                                     envelope with escaped filename and content
                                     boundaries.
        """

        if not attachments:
            return None
        if len(attachments) > _MAX_ATTACHMENT_COUNT:
            raise ValueError(f"attachments supports at most {_MAX_ATTACHMENT_COUNT} items")

        from opensquilla.provider.types import (
            ContentBlockImage,
            ContentBlockText,
            Message,
        )

        prompt_block = ContentBlockText(text=message)
        attachment_blocks: list[Any] = []
        for index, att in enumerate(attachments, start=1):
            att_type = att.get("type")
            media_type: str | None = att_type if isinstance(att_type, str) else None
            if media_type is None or media_type not in _ALLOWED_ENGINE_MEDIA_TYPES:
                mime = att.get("mime") or att.get("media_type")
                if isinstance(mime, str) and mime in _ALLOWED_ENGINE_MEDIA_TYPES:
                    media_type = mime
            if media_type is None or media_type not in _ALLOWED_ENGINE_MEDIA_TYPES:
                raise ValueError(
                    f"attachments[{index}] media type {att_type!r} is not allowed"
                )
            if is_attachment_ref(att):
                missing_ref_marker = ""
                if media_root is None:
                    raise ValueError(f"attachments[{index}] media_root is required")
                try:
                    raw_bytes = read_attachment_ref_bytes(att, media_root=media_root)
                except FileNotFoundError:
                    raw_bytes = b""
                    missing_ref_marker = "[attachment unavailable: material file is missing]"
                except ValueError as exc:
                    raw_bytes = b""
                    missing_ref_marker = f"[attachment unavailable: {exc}]"
                data = base64.b64encode(raw_bytes).decode("ascii") if raw_bytes else ""
            else:
                missing_ref_marker = ""
                data_raw = att.get("data")
                if not isinstance(data_raw, str) or not data_raw:
                    raise ValueError(f"attachments[{index}].data is required")
                data = data_raw
                try:
                    raw_bytes = base64.b64decode(data, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError(f"attachments[{index}].data must be valid base64") from exc
            if media_type in _ENGINE_TEXT_FAMILY_MIMES:
                max_bytes = _MAX_TEXT_ATTACHMENT_BYTES
            elif media_type == "application/pdf" and att.get("_was_staged") is True:
                max_bytes = _MAX_STAGED_ATTACHMENT_BYTES
            else:
                max_bytes = _MAX_ATTACHMENT_BYTES
            if len(raw_bytes) > max_bytes:
                raise ValueError(
                    f"attachments[{index}] exceeds the {max_bytes} byte limit"
                )

            name_raw = att.get("name")
            filename = _sanitize_attachment_filename(name_raw)
            if missing_ref_marker:
                wrapped = _render_file_context_block(filename, media_type, missing_ref_marker)
                attachment_blocks.append(ContentBlockText(text=wrapped))
                continue

            if media_type.startswith("image/"):
                attachment_blocks.append(
                    ContentBlockImage(media_type=media_type, data=data)
                )
            elif media_type == "application/pdf":
                try:
                    extracted_pdf_text = _extract_pdf_attachment_text(raw_bytes, filename)
                except ValueError as exc:
                    extracted_pdf_text = (
                        "[attachment unavailable: PDF text could not be extracted: "
                        f"{exc}]"
                    )
                wrapped = _render_file_context_block(filename, media_type, extracted_pdf_text)
                attachment_blocks.append(ContentBlockText(text=wrapped))
            elif media_type in _ENGINE_TEXT_FAMILY_MIMES:
                try:
                    decoded_text = _truncate_attachment_text(
                        raw_bytes.decode("utf-8"),
                        limit=_TEXT_ATTACHMENT_TEXT_LIMIT,
                    )
                except UnicodeDecodeError:
                    decoded_text = (
                        "[attachment unavailable: declared text content is not valid UTF-8]"
                    )
                wrapped = _render_file_context_block(filename, media_type, decoded_text)
                attachment_blocks.append(ContentBlockText(text=wrapped))
            else:  # pragma: no cover - guarded by allow-list above
                raise ValueError(
                    f"attachments[{index}] media type {media_type!r} is not handled"
                )

        return [
            Message(
                role="user",
                content=[prompt_block] + attachment_blocks,  # type: ignore[arg-type]
            )
        ]
