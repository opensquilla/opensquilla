"""Agent core — explicit state machine + tool loop.

Core loop is under 500 lines. No recursive calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import structlog

from opensquilla.artifacts import artifact_payload
from opensquilla.context_budget import ContextBudgetClass, ContextBudgetGovernor
from opensquilla.engine.cache_break_monitor import (
    check_response_for_cache_break,
    notify_compaction,
    record_prompt_state,
)
from opensquilla.engine.fallback import FallbackPolicy, backoff_sleep
from opensquilla.engine.history import limit_turns, repair_tool_pairing
from opensquilla.engine.progress_watchdog import ProgressObservation, ProgressWatchdog
from opensquilla.engine.session_sanitize import (
    SessionSanitizeResult,
    project_historical_tool_payloads,
    sanitize_session_messages,
    session_payload_chars,
)
from opensquilla.engine.thinking import drop_reasoning
from opensquilla.engine.tokenjuice_adapter import reduce_tool_result_with_tokenjuice
from opensquilla.engine.tool_result_store import (
    ToolResultRecord,
    ToolResultStore,
    ToolResultStoreBudgetError,
)
from opensquilla.engine.tool_text_compat import strip_synthetic_tool_call_suffix
from opensquilla.engine.tool_token_estimate import estimate_tokens as get_approx_tokens
from opensquilla.execution_status import (
    mark_execution_status_truncated,
    runtime_execution_status,
)
from opensquilla.observability.turn_call_log import TurnCallLogger
from opensquilla.provider import (
    ChatConfig,
    ContentBlockText,
    ContentBlockThinking,
    ContentBlockToolResult,
    ContentBlockToolUse,
    LLMProvider,
    Message,
    ProviderHeartbeatEvent,
    ToolDefinition,
    ToolUseEndEvent,
)
from opensquilla.provider import (
    DoneEvent as ProviderDoneEvent,
)
from opensquilla.provider import (
    ErrorEvent as ProviderErrorEvent,
)
from opensquilla.provider import (
    TextDeltaEvent as ProviderTextDelta,
)
from opensquilla.provider import (
    ToolUseStartEvent as ProviderToolUseStart,
)
from opensquilla.provider.failures import ProviderFailureKind, classify_provider_error
from opensquilla.provider.types import ContentBlockImage
from opensquilla.result_budget import (
    ToolResultBudgetClass,
    compact_tool_result_content,
    resolve_budget_class,
)
from opensquilla.router_control import router_control_replay_event_from_payload
from opensquilla.session.compaction import (
    CompactionConfig,
    CompactionRequest,
    build_compaction_config_from_provider,
    compact_context,
)
from opensquilla.session.compaction_lifecycle import (
    COMPACTION_CHUNK_SUMMARIZED_EVENT,
    COMPACTION_SUMMARY_VERIFIED_EVENT,
    COMPACTION_TRIGGERED_EVENT,
    compaction_effect_payload,
    compaction_lifecycle_payload,
    compaction_result_payload,
    flush_receipt_allows_destructive_compaction,
    flush_receipt_is_successful_flush,
    new_compaction_id,
)
from opensquilla.session.terminal_reply import build_terminal_reply
from opensquilla.skills.meta.semantic_guards import semantic_meta_skill_allowed
from opensquilla.tool_boundary import AgentToolHandler as ToolHandler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolContext, current_tool_context

from .context import ContextAssembly
from .subagent import SubagentManager, SubagentSpec
from .types import (
    AgentConfig,
    AgentEvent,
    AgentState,
    ArtifactEvent,
    CompactionEvent,
    CompactionOutcome,
    DoneEvent,
    ErrorEvent,
    RunHeartbeatEvent,
    StateChangeEvent,
    TextDeltaEvent,
    ThinkingLevel,
    ToolCall,
    ToolResult,
    ToolResultEvent,
    ToolUseStartEvent,
    WarningEvent,
)

logger = structlog.get_logger("opensquilla.engine.agent")

_PROVIDER_OUTPUT_TRUNCATED_REPLY = build_terminal_reply(
    {
        "status": "failed",
        "terminal_reason": "output_truncated",
        "error_class": "provider_output_truncated",
        "error_message": "Provider output limit reached before completion",
    }
)
_PROVIDER_OUTPUT_CONTINUE_PROMPT = (
    "The previous provider response reached its output limit before the task finished. "
    "Continue from the exact point where it stopped. Do not repeat text that has already "
    "been written. If a tool call was interrupted or incomplete, regenerate a complete "
    "tool call from scratch."
)

_meta_invoke_depth: ContextVar[int] = ContextVar(
    "opensquilla_meta_invoke_depth", default=0
)
_meta_invoke_turn_count: ContextVar[int] = ContextVar(
    "opensquilla_meta_invoke_turn_count", default=0
)


def _cost_source_for_usage(cost_usd: float, billed_cost: float) -> str:
    if billed_cost > 0.0 and abs(cost_usd - billed_cost) <= 1e-9:
        return "provider_billed"
    if billed_cost > 0.0:
        return "mixed"
    if cost_usd > 0.0:
        return "opensquilla_estimate"
    return "unavailable"

MAX_META_INVOKE_DEPTH = 3
MAX_META_INVOKE_PER_TURN = 8


def _is_deepseek_model_id(model_id: str | None) -> bool:
    normalized = (model_id or "").strip().lower()
    return normalized.startswith("deepseek") or "/deepseek" in normalized


def _is_direct_deepseek_v4_model_id(model_id: str | None) -> bool:
    normalized = (model_id or "").strip().lower()
    return normalized in {"deepseek-v4-flash", "deepseek-v4-pro"}


_LARGE_JSON_TOOL_FIELD_KEYS: frozenset[str] = frozenset({"body", "body_base64"})
_LARGE_JSON_TOOL_FIELD_CHARS = 20_000
_TOOL_ARGUMENT_PROJECTION_PREFIX = "[tool_use_argument_projection]\n"
_HISTORICAL_TOOL_ARGUMENT_PROJECTION_PREFIX = "[historical_tool_argument_omitted]\n"
_INVALID_PROVIDER_CONTEXT_PROJECTION_PREFIX = "[invalid_provider_context_projection:"
_INVALID_PROVIDER_CONTEXT_ARGUMENTS_KEY = "_invalid_provider_context_arguments"
_AGGREGATE_TOOL_RESULT_MAX_SHARE = 0.25
_TOOL_ARGUMENT_HEARTBEAT_CHARS = 4096
_PROVIDER_CONTEXT_PROJECTION_REUSED_REASON = "provider_context_projection_reused"
_PROVIDER_CONTEXT_REPAIR_PROMPT = (
    "A previous tool call was rejected because it reused provider-only compacted "
    "tool arguments. Regenerate the complete tool arguments from the available "
    "source context and retry the tool call. Do not copy compacted placeholders."
)
_LARGE_CONTEXT_INVALID_RESPONSE_INPUT_TOKENS = 30_000
_COMPACTED_TOOL_ARGUMENT_MARKERS = frozenset(
    {
        "_opensquilla_compacted_tool_arguments",
        "_opensquilla_compacted_tool_input",
    }
)


def _large_json_field_replacement(value: str) -> dict[str, object]:
    return {
        "omitted": True,
        "omitted_chars": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "reason": "large_tool_result_field",
    }


def _omit_large_json_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        changed = False
        sanitized_dict: dict[str, Any] = {}
        for key, item in value.items():
            if (
                key in _LARGE_JSON_TOOL_FIELD_KEYS
                and isinstance(item, str)
                and len(item) > _LARGE_JSON_TOOL_FIELD_CHARS
            ):
                sanitized_dict[key] = _large_json_field_replacement(item)
                changed = True
                continue
            sanitized, child_changed = _omit_large_json_value(item)
            sanitized_dict[key] = sanitized
            changed = changed or child_changed
        return sanitized_dict, changed
    if isinstance(value, list):
        changed = False
        sanitized_list: list[Any] = []
        for item in value:
            sanitized, child_changed = _omit_large_json_value(item)
            sanitized_list.append(sanitized)
            changed = changed or child_changed
        return sanitized_list, changed
    return value, False


def _omit_large_json_tool_fields(content: str) -> tuple[str, bool]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content, False
    sanitized, changed = _omit_large_json_value(parsed)
    if not changed:
        return content, False
    return json.dumps(sanitized, ensure_ascii=False, indent=2), True


def _is_threshold_denial(result: ToolResult) -> bool:
    try:
        payload = json.loads(result.content)
    except Exception:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("status") == "denied"
        and payload.get("reason") == "threshold_exceeded"
    )


_PENDING_APPROVAL_STATUSES: frozenset[str] = frozenset({"approval_required", "approval_pending"})


def _pending_approval_payload(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("status") not in _PENDING_APPROVAL_STATUSES:
        return None
    approval_id = payload.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        return None
    return payload


async def _wait_for_pending_approval_resolution(
    payload: dict[str, Any],
    *,
    timeout: float,
) -> None:
    approval_id = payload.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        return
    try:
        from opensquilla.gateway.approval_queue import get_approval_queue

        await get_approval_queue().wait(approval_id, timeout=timeout)
    except KeyError:
        return


def _tool_result_content_has_artifact(content: str) -> bool:
    try:
        payload = json.loads(content)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("artifact"), dict) or isinstance(payload.get("artifacts"), list):
        return True
    return payload.get("status") in {"published", "already_published"}


def _tool_result_budget_tokens(content: str) -> int:
    return max(get_approx_tokens(content), len(content) // 4)


def _artifact_event_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "kind",
        "id",
        "sha256",
        "name",
        "mime",
        "size",
        "session_id",
        "session_key",
        "source",
        "created_at",
        "download_url",
        "store",
    }
    return {key: value for key, value in artifact_payload(payload).items() if key in allowed}


def _flatten_content_blocks(blocks: list[Any]) -> str:
    """Convert a list of content-block Pydantic models to a plain string for compaction.

    Extracts text from ContentBlockText, summarises tool_use/tool_result blocks,
    and drops thinking/image blocks to avoid leaking Python repr strings.
    """
    parts: list[str] = []
    for b in blocks:
        if isinstance(b, ContentBlockText):
            parts.append(b.text)
        elif isinstance(b, ContentBlockToolUse):
            parts.append(f"[Used tool: {b.name}]")
        elif isinstance(b, ContentBlockToolResult):
            snippet = b.content if isinstance(b.content, str) else str(b.content)
            if len(snippet) > 200:
                snippet = snippet[:200] + "…"
            parts.append(f"[Tool result ({b.tool_use_id}): {snippet}]")
        # Skip thinking / image blocks — not useful for compaction
    return "\n".join(parts)


def _message_has_tool_result(message: Message | None) -> bool:
    if message is None or not isinstance(message.content, list):
        return False
    return any(getattr(block, "type", None) == "tool_result" for block in message.content)


def _append_length_capped_continuation(
    turn_messages: list[Message],
    *,
    response_text: str,
    tool_calls: list[ToolCall],
) -> str:
    visible_text = strip_synthetic_tool_call_suffix(
        response_text,
        [tc.tool_name for tc in tool_calls if tc.synthetic_from_text],
    )
    if visible_text:
        turn_messages.append(
            Message(role="assistant", content=[ContentBlockText(text=visible_text)])
        )
    turn_messages.append(Message(role="user", content=_PROVIDER_OUTPUT_CONTINUE_PROMPT))
    return visible_text


class _ProviderAttemptKind(StrEnum):
    OK = "ok"
    REASONING_ONLY = "reasoning_only"
    MALFORMED_EMPTY = "malformed_empty"
    INCOMPLETE_TOOLS = "incomplete_tools"
    STREAM_INCOMPLETE = "stream_incomplete"
    LENGTH_CAPPED = "length_capped"


class _IterationStreamTimeoutError(TimeoutError):
    """Raised when provider streaming exceeds the active Agent iteration budget."""


def _is_large_context_invalid_response(
    kind: _ProviderAttemptKind,
    *,
    input_tokens: int,
) -> bool:
    return (
        kind
        in {
            _ProviderAttemptKind.REASONING_ONLY,
            _ProviderAttemptKind.MALFORMED_EMPTY,
        }
        and input_tokens >= _LARGE_CONTEXT_INVALID_RESPONSE_INPUT_TOKENS
    )


@dataclass(frozen=True)
class _ProviderAttemptClassification:
    kind: _ProviderAttemptKind
    stop_reason: str | None = None
    user_visible_emitted: bool = False


@dataclass(frozen=True)
class _ProviderRetryPolicy:
    max_provider_retries: int
    attempt_budgets: dict[_ProviderAttemptKind, int]
    provider_failure_budgets: dict[ProviderFailureKind, int]

    @classmethod
    def from_provider_budget(
        cls,
        max_provider_retries: int,
        *,
        length_capped_continuations: int = 1,
    ) -> _ProviderRetryPolicy:
        length_capped_continuations = max(1, length_capped_continuations)
        return cls(
            max_provider_retries=max_provider_retries,
            attempt_budgets={
                _ProviderAttemptKind.REASONING_ONLY: 1,
                _ProviderAttemptKind.MALFORMED_EMPTY: 1,
                _ProviderAttemptKind.STREAM_INCOMPLETE: 1,
                _ProviderAttemptKind.LENGTH_CAPPED: length_capped_continuations,
            },
            provider_failure_budgets={ProviderFailureKind.EMPTY_RESPONSE: 1},
        )

    def used_attempts(self) -> dict[_ProviderAttemptKind, int]:
        return {kind: 0 for kind in self.attempt_budgets}

    def can_retry_attempt(
        self,
        kind: _ProviderAttemptKind,
        used: dict[_ProviderAttemptKind, int],
    ) -> bool:
        return self.max_provider_retries > 0 and used.get(kind, 0) < self.attempt_budgets.get(
            kind, 0
        )

    def can_retry_provider_failure(
        self,
        failure_kind: ProviderFailureKind,
        *,
        post_tool_turn: bool,
        provider_retry_attempt: int,
    ) -> bool:
        if failure_kind is ProviderFailureKind.EMPTY_RESPONSE:
            return (
                post_tool_turn
                and self.max_provider_retries > 0
                and provider_retry_attempt
                < self.provider_failure_budgets.get(failure_kind, self.max_provider_retries)
            )
        return provider_retry_attempt < self.max_provider_retries


def _classify_provider_attempt(
    *,
    text: str,
    tool_calls: list[ToolCall],
    pending_tools: dict[str, _StreamAccumulator],
    got_done_event: bool,
    stop_reason: str | None,
    reasoning_content: str | None,
    reasoning_tokens: int,
    user_visible_emitted: bool,
) -> _ProviderAttemptClassification:
    visible_text = bool(text.strip())
    if pending_tools:
        return _ProviderAttemptClassification(
            _ProviderAttemptKind.INCOMPLETE_TOOLS,
            stop_reason=stop_reason,
            user_visible_emitted=user_visible_emitted,
        )
    if not got_done_event:
        return _ProviderAttemptClassification(
            _ProviderAttemptKind.STREAM_INCOMPLETE,
            stop_reason=stop_reason,
            user_visible_emitted=user_visible_emitted,
        )
    if (stop_reason or "").lower() == "length":
        return _ProviderAttemptClassification(
            _ProviderAttemptKind.LENGTH_CAPPED,
            stop_reason=stop_reason,
            user_visible_emitted=user_visible_emitted,
        )
    if visible_text or tool_calls:
        return _ProviderAttemptClassification(
            _ProviderAttemptKind.OK,
            stop_reason=stop_reason,
            user_visible_emitted=user_visible_emitted,
        )
    if (reasoning_content and reasoning_content.strip()) or reasoning_tokens > 0:
        return _ProviderAttemptClassification(
            _ProviderAttemptKind.REASONING_ONLY,
            stop_reason=stop_reason,
            user_visible_emitted=user_visible_emitted,
        )
    return _ProviderAttemptClassification(
        _ProviderAttemptKind.MALFORMED_EMPTY,
        stop_reason=stop_reason,
        user_visible_emitted=user_visible_emitted,
    )


def _chat_config_with_thinking_disabled(chat_cfg: ChatConfig) -> ChatConfig:
    return ChatConfig(
        max_tokens=chat_cfg.max_tokens,
        temperature=chat_cfg.temperature,
        system=chat_cfg.system,
        thinking=False,
        thinking_budget_tokens=0,
        timeout=chat_cfg.timeout,
        stop_sequences=chat_cfg.stop_sequences,
        cache_breakpoints=chat_cfg.cache_breakpoints,
        cache_mode=chat_cfg.cache_mode,
        model_capabilities=chat_cfg.model_capabilities,
        thinking_level=None,
        provider_request_max_chars=chat_cfg.provider_request_max_chars,
        tool_choice=chat_cfg.tool_choice,
    )


def _strip_historical_image_blocks(messages: list[Message]) -> list[Message]:
    """Remove image payload blocks from history before provider calls.

    Current-turn uploads are passed through ``extra_messages`` and are not part
    of the history list sanitized here. This prevents a later text follow-up
    from replaying stale image input to a text-only route.
    """
    sanitized: list[Message] = []
    for msg in messages:
        content = msg.content
        if not isinstance(content, list):
            sanitized.append(msg)
            continue

        kept: list[Any] = []
        omitted: list[str] = []
        for block in content:
            if isinstance(block, ContentBlockImage):
                media_type = block.media_type or "image"
                omitted.append(f"[historical image omitted: {media_type}]")
                continue
            kept.append(block)

        if not omitted:
            sanitized.append(msg)
            continue

        kept.extend(ContentBlockText(text=marker) for marker in omitted)
        sanitized.append(Message(role=msg.role, content=kept))
    return sanitized


@dataclass
class _StreamAccumulator:
    """Accumulates streaming fragments for a single tool call."""

    tool_use_id: str
    tool_name: str
    synthetic_from_text: bool = False
    json_buf: list[str] = field(default_factory=list)
    json_chars: int = 0

    def finish(self) -> dict[str, Any]:
        raw = "".join(self.json_buf)
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return {"_raw": raw}


class Agent:
    """Explicit state-machine agent.

    Lifecycle per turn:
      IDLE -> THINKING -> STREAMING -> [TOOL_CALLING -> THINKING -> ...] -> DONE
      Any step can transition to ERROR.
    """

    def __init__(
        self,
        provider: LLMProvider,
        config: AgentConfig | None = None,
        tool_definitions: list[ToolDefinition] | None = None,
        tool_handler: ToolHandler | None = None,
        subagent_manager: SubagentManager | None = None,
        usage_tracker: Any | None = None,
        session_key: str | None = None,
        turn_call_logger: TurnCallLogger | None = None,
        memory_sync_manager: Any | None = None,
        session_flush_service: Any | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_context: ToolContext | None = None,
    ) -> None:
        self.provider = provider
        self.config = config or AgentConfig()
        self.tool_definitions = tool_definitions or []
        self._tool_definition_by_name = {tool.name: tool for tool in self.tool_definitions}
        self.tool_handler = tool_handler
        self.subagent_manager = subagent_manager or SubagentManager()
        self._usage_tracker = usage_tracker
        self._session_key = session_key
        self._turn_call_logger = turn_call_logger
        self._tool_registry: ToolRegistry | None = tool_registry
        self._tool_context: ToolContext | None = tool_context
        self._meta_run_writer = (self.config.metadata or {}).get("meta_run_writer")
        self._pending_warnings: list[WarningEvent] = []

        self._state: AgentState = AgentState.IDLE
        self._history: list[Message] = []
        self._context: ContextAssembly | None = None
        # Typed dependency surface. Either constructor injection or legacy
        # attribute assignment from the runtime is accepted; both reach the same
        # internal slot.
        self._memory_sync_manager: Any | None = memory_sync_manager

        # Memory flush state (sub-agent based, re-entrant per compaction cycle)
        self._flush_done_this_cycle: bool = False
        self._active_flush_task: asyncio.Task | None = None
        self._flush_wait_timed_out_task: asyncio.Task | None = None
        self._flush_backoff_until: float = 0.0
        self._flush_backoff_seconds: float = 0.0
        self._session_flush_service = session_flush_service
        self._last_compaction_refusal_reason: str | None = None
        self._tool_failure_loop_counts: dict[tuple[str, str], int] = {}
        self._provider_tool_result_overrides: dict[str, ContentBlockToolResult] = {}

    def _context_overflow_error(self) -> ErrorEvent:
        reason = self._last_compaction_refusal_reason
        if reason == "memory_flush_timeout_before_compaction":
            return ErrorEvent(
                message=(
                    "Context compaction could not run because the pre-compaction "
                    "memory flush timed out."
                ),
                code="compaction_refused_flush_timeout",
            )
        if reason == "memory_flush_degraded_before_compaction":
            return ErrorEvent(
                message=(
                    "Context compaction could not run because the pre-compaction "
                    "memory flush did not produce a verified summary."
                ),
                code="compaction_refused_memory_flush",
            )
        if reason == "empty_summary_rejected":
            return ErrorEvent(
                message="Context compaction produced no replacement summary.",
                code="compaction_refused_empty_summary",
            )
        if reason == "compaction_failed":
            return ErrorEvent(
                message="Context compaction failed before the provider request could be retried.",
                code="compaction_failed",
            )
        if reason == "compaction_not_smaller":
            return ErrorEvent(
                message="Context compaction did not reduce the provider request.",
                code="compaction_not_smaller",
            )
        if reason == "provider_recent_tail_too_large":
            return ErrorEvent(
                message=(
                    "The request is too large for the provider context window after "
                    "automatic context compaction and payload reduction. OpenSquilla "
                    "preserved the recoverable state; retry with a narrower request "
                    "or a larger-context model."
                ),
                code="provider_request_too_large",
            )
        if reason == "provider_request_budget_exhausted":
            return ErrorEvent(
                message=(
                    "The request is too large for the provider context window after "
                    "automatic context compaction and payload reduction. OpenSquilla "
                    "preserved the recoverable state; retry with a narrower request "
                    "or a larger-context model."
                ),
                code="provider_request_too_large",
            )
        return ErrorEvent(
            message="Context overflow persists after compaction",
            code="compaction_exhausted",
        )

    def _record_provider_context_overflow_reason(
        self,
        provider_error: ProviderErrorEvent,
    ) -> None:
        if provider_error.code != "provider_request_budget_exhausted":
            return
        proof = self._provider_request_budget_proof(provider_error)
        if proof is None:
            self._last_compaction_refusal_reason = "provider_request_budget_exhausted"
            return
        if proof.get("recent_tail_too_large") is True:
            self._last_compaction_refusal_reason = "provider_recent_tail_too_large"
            return
        if proof.get("compaction_not_smaller") is True:
            self._last_compaction_refusal_reason = "compaction_not_smaller"
            return
        fallback_reason = proof.get("fallback_reason")
        if fallback_reason == "provider_request_budget_exhausted":
            self._last_compaction_refusal_reason = "provider_request_budget_exhausted"

    @staticmethod
    def _provider_request_budget_proof(
        provider_error: ProviderErrorEvent,
    ) -> dict[str, Any] | None:
        if provider_error.code != "provider_request_budget_exhausted":
            return None
        try:
            proof = json.loads(provider_error.message)
        except (TypeError, ValueError):
            return None
        return proof if isinstance(proof, dict) else None

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _provider_budget_compaction_window_tokens(
        self,
        provider_error: ProviderErrorEvent,
    ) -> int | None:
        proof = self._provider_request_budget_proof(provider_error)
        if proof is None:
            return None
        proof_budget = self._positive_int(
            proof.get("effective_proof_budget") or proof.get("proof_budget")
        )
        if proof_budget is None:
            return None
        estimated_chars = self._positive_int(proof.get("estimated_chars"))
        estimated_tokens = self._positive_int(proof.get("estimated_tokens"))
        if estimated_chars and estimated_tokens:
            window_tokens = int(proof_budget * (estimated_tokens / estimated_chars))
        else:
            window_tokens = proof_budget // 4
        if window_tokens <= 0:
            return None
        return min(self.config.context_window_tokens, window_tokens)

    def _provider_budget_estimated_tokens(
        self,
        provider_error: ProviderErrorEvent,
    ) -> int | None:
        proof = self._provider_request_budget_proof(provider_error)
        if proof is None:
            return None
        return self._positive_int(proof.get("estimated_tokens"))

    def _provider_request_proof_max_chars(self) -> int:
        return self._context_budget_governor().snapshot().provider_request_max_chars

    def _context_budget_governor(self) -> ContextBudgetGovernor:
        return ContextBudgetGovernor.from_config(self.config)

    @staticmethod
    def _context_budget_class(
        budget_class: ToolResultBudgetClass | None,
    ) -> ContextBudgetClass:
        if budget_class is ToolResultBudgetClass.EXTERNAL:
            return ContextBudgetClass.EXTERNAL
        if budget_class is ToolResultBudgetClass.ARTIFACT:
            return ContextBudgetClass.ARTIFACT
        if budget_class is ToolResultBudgetClass.ERROR:
            return ContextBudgetClass.ERROR
        if budget_class is ToolResultBudgetClass.CONTROL:
            return ContextBudgetClass.CONTROL
        return ContextBudgetClass.LOCAL

    def _tool_use_argument_provider_request_max_chars(self, tool_name: str) -> int:
        budget_class = self._context_budget_class(resolve_budget_class(tool_name))
        return self._context_budget_governor().tool_argument_chars_for(budget_class)

    def _tool_result_provider_request_max_chars(
        self,
        budget_class: ToolResultBudgetClass | None = None,
    ) -> int:
        return self._context_budget_governor().tool_result_provider_chars_for(
            self._context_budget_class(budget_class)
        )

    def _tool_execution_timeout(self, tool_call: ToolCall) -> float:
        timeout = float(self.config.tool_timeout)
        tool_def = self._tool_definition_by_name.get(tool_call.tool_name)
        if tool_def is None:
            return timeout
        static_timeout = getattr(tool_def, "execution_timeout_seconds", None)
        if static_timeout is not None:
            try:
                timeout = max(timeout, float(static_timeout))
            except (TypeError, ValueError):
                pass
        argument_name = getattr(tool_def, "execution_timeout_argument", None)
        if not argument_name:
            return timeout
        raw_value = tool_call.arguments.get(str(argument_name))
        if raw_value is None:
            return timeout
        try:
            argument_timeout = float(raw_value)
        except (TypeError, ValueError):
            return timeout
        if argument_timeout < 0:
            return timeout
        padding = getattr(tool_def, "execution_timeout_padding", 0.0) or 0.0
        try:
            timeout = max(timeout, argument_timeout + float(padding))
        except (TypeError, ValueError):
            timeout = max(timeout, argument_timeout)
        return timeout

    def _tool_activity_heartbeat_interval(self) -> float:
        raw_interval = self.config.metadata.get("tool_activity_heartbeat_interval", 15.0)
        try:
            return float(raw_interval)
        except (TypeError, ValueError):
            return 15.0

    def _approval_wait_timeout(self) -> float:
        raw_timeout = self.config.metadata.get("approval_wait_timeout_seconds", 180.0)
        try:
            return max(0.0, float(raw_timeout))
        except (TypeError, ValueError):
            return 180.0

    def _max_safe_tool_concurrency(self) -> int:
        try:
            value = int(self.config.max_safe_tool_concurrency)
        except (TypeError, ValueError):
            return 6
        return max(1, value)

    def _write_turn_call_log(self, kind: str, **payload: Any) -> None:
        if self._turn_call_logger is not None:
            self._turn_call_logger.write(kind, payload)

    def _write_context_stage(
        self,
        stage: str,
        messages: list[Message],
        **payload: Any,
    ) -> None:
        if self._turn_call_logger is None:
            return
        self._write_turn_call_log(
            "context_stage",
            stage=stage,
            message_count=len(messages),
            payload_chars=session_payload_chars(messages),
            messages=messages,
            **payload,
        )

    def _switch_to_invalid_response_fallback(self, reason: str) -> bool:
        fallback = getattr(self.provider, "fallback_after_invalid_response", None)
        if not callable(fallback):
            return False
        try:
            return bool(fallback(reason))
        except Exception as exc:  # noqa: BLE001 - fallback support is optional
            logger.warning(
                "provider.invalid_response_fallback_failed",
                session_key=self._session_key,
                reason=reason,
                error=str(exc),
            )
            return False

    @staticmethod
    def _tool_call_string_arg(
        tool_call: ToolCall | None,
        *names: str,
    ) -> str | None:
        if tool_call is None:
            return None
        for name in names:
            value = tool_call.arguments.get(name)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _tokenjuice_max_inline_chars(self, fallback: int | None = None) -> int:
        if fallback is not None and fallback > 0:
            return max(1, int(fallback))
        return max(1, int(self.config.tool_result_projection_max_inline_chars))

    def _tokenjuice_tool_reduction(
        self,
        *,
        tool_name: str,
        content: str,
        is_error: bool,
        tool_use_id: str,
        arguments: dict[str, Any] | None = None,
        command: str | None = None,
        cwd: str | None = None,
        max_inline_chars: int | None = None,
    ) -> str | None:
        reduction = reduce_tool_result_with_tokenjuice(
            tool_name=tool_name,
            content=content,
            is_error=is_error,
            tool_use_id=tool_use_id,
            arguments=arguments,
            command=command,
            cwd=cwd,
            max_inline_chars=self._tokenjuice_max_inline_chars(max_inline_chars),
        )
        if reduction is None:
            return None
        self.config.metadata["tool_projection_backend"] = "tokenjuice"
        if reduction.reducer:
            self.config.metadata["tool_projection_tokenjuice_reducer"] = reduction.reducer
        return reduction.inline_text

    @staticmethod
    def _count_image_blocks(messages: list[Message]) -> int:
        count = 0
        for message in messages:
            if not isinstance(message.content, list):
                continue
            count += sum(1 for block in message.content if isinstance(block, ContentBlockImage))
        return count

    def _compact_aggregate_tool_results_for_provider(
        self,
        messages: list[Message],
    ) -> list[Message]:
        """Compact old bulky tool results in the provider request view only.

        This pass handles both single oversized tool results and the aggregate
        case where many under-threshold results accumulate across iterations.
        It never mutates persisted history and it preserves recent, error, and
        artifact-producing results unless a successful single result alone
        exceeds the provider request cap.
        """

        tool_name_by_use_id: dict[str, str] = {}
        tool_result_refs: list[tuple[int, int, ContentBlockToolResult]] = []
        for message_index, message in enumerate(messages):
            if not isinstance(message.content, list):
                continue
            for block_index, block in enumerate(message.content):
                if isinstance(block, ContentBlockToolUse):
                    tool_name_by_use_id[block.id] = block.name
                elif isinstance(block, ContentBlockToolResult):
                    tool_result_refs.append((message_index, block_index, block))

        messages = self._compact_absolute_tool_results_for_provider(
            messages,
            tool_result_refs,
            tool_name_by_use_id,
        )
        tool_result_refs = []
        for message_index, message in enumerate(messages):
            if not isinstance(message.content, list):
                continue
            for block_index, block in enumerate(message.content):
                if isinstance(block, ContentBlockToolResult):
                    tool_result_refs.append((message_index, block_index, block))

        if len(tool_result_refs) <= 2:
            return messages

        recent_ids = {id(block) for _message_index, _block_index, block in tool_result_refs[-2:]}
        budget_tokens = int(
            self.config.context_window_tokens * _AGGREGATE_TOOL_RESULT_MAX_SHARE
        )
        eligible_refs: list[tuple[int, int, ContentBlockToolResult, str, int]] = []
        total_tool_result_tokens = 0
        for message_index, block_index, block in tool_result_refs:
            content = block.content if isinstance(block.content, str) else str(block.content)
            tokens = _tool_result_budget_tokens(content)
            total_tool_result_tokens += tokens
            if (
                id(block) in recent_ids
                or block.is_error
                or _tool_result_content_has_artifact(content)
            ):
                continue
            eligible_refs.append((message_index, block_index, block, content, tokens))

        if total_tool_result_tokens <= budget_tokens or not eligible_refs:
            return messages

        replacements: dict[tuple[int, int], ContentBlockToolResult] = {}
        stored_handles: list[str] = []

        for message_index, block_index, block, content, original_tokens in eligible_refs:
            if total_tool_result_tokens <= budget_tokens:
                break
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            stored = self._store_tool_result_snapshot(
                content,
                tool_use_id=block.tool_use_id,
                tool_name=tool_name_by_use_id.get(block.tool_use_id, "tool"),
            )
            if stored is not None:
                stored_handles.append(stored.handle)
            head = content[:240]
            tail = content[-240:] if len(content) > 240 else ""
            omitted = max(0, len(content) - len(head) - len(tail))
            handle_line = f"tool_result_handle: {stored.handle}\n" if stored is not None else ""
            compacted = (
                "[aggregate_tool_result_compacted]\n"
                f"tool_use_id: {block.tool_use_id}\n"
                f"original_chars: {len(content)}\n"
                f"original_tokens_estimate: {_tool_result_budget_tokens(content)}\n"
                f"sha256: {digest}\n"
                f"{handle_line}"
                f"omitted_chars: {omitted}\n"
                "reason: older non-error tool result compacted for provider context budget.\n"
                f"head:\n{head}"
            )
            if tail and tail != head:
                compacted += f"\n...\ntail:\n{tail}"
            replacements[(message_index, block_index)] = ContentBlockToolResult(
                tool_use_id=block.tool_use_id,
                content=compacted,
                is_error=block.is_error,
            )
            replacement_tokens = _tool_result_budget_tokens(compacted)
            total_tool_result_tokens -= max(0, original_tokens - replacement_tokens)

        if not replacements:
            return messages

        compacted_messages: list[Message] = []
        for message_index, message in enumerate(messages):
            if not isinstance(message.content, list):
                compacted_messages.append(message)
                continue
            next_content: list[Any] = []
            message_changed = False
            for block_index, block in enumerate(message.content):
                replacement = replacements.get((message_index, block_index))
                if replacement is None:
                    next_content.append(block)
                    continue
                next_content.append(replacement)
                message_changed = True
            if not message_changed:
                compacted_messages.append(message)
                continue
            compacted_messages.append(
                Message(
                    role=message.role,
                    content=next_content,
                    reasoning_content=getattr(message, "reasoning_content", None),
                )
            )

        before_tokens = sum(
            _tool_result_budget_tokens(
                block.content if isinstance(block.content, str) else str(block.content)
            )
            for _message_index, _block_index, block in tool_result_refs
        )
        after_tokens = 0
        for message in compacted_messages:
            if not isinstance(message.content, list):
                continue
            for block in message.content:
                if isinstance(block, ContentBlockToolResult):
                    content = (
                        block.content if isinstance(block.content, str) else str(block.content)
                    )
                    after_tokens += _tool_result_budget_tokens(content)
        saved_tokens = max(0, before_tokens - after_tokens)
        if saved_tokens == 0 and replacements:
            saved_tokens = 1

        self.config.metadata["tool_aggregate_projection_applied"] = True
        self.config.metadata["tool_aggregate_projection_calls"] = (
            self.config.metadata.get("tool_aggregate_projection_calls", 0) + 1
        )
        self.config.metadata["tool_aggregate_projection_tokens_before"] = before_tokens
        self.config.metadata["tool_aggregate_projection_tokens_after"] = after_tokens
        self.config.metadata["tool_aggregate_projection_tokens_saved"] = saved_tokens
        self.config.metadata["tool_projection_applied"] = True
        self.config.metadata["tool_projection_calls"] = self.config.metadata.get(
            "tool_projection_calls", 0
        ) + len(replacements)
        self.config.metadata["tool_projection_tokens_before"] = (
            self.config.metadata.get("tool_projection_tokens_before", 0) + before_tokens
        )
        self.config.metadata["tool_projection_tokens_after"] = (
            self.config.metadata.get("tool_projection_tokens_after", 0) + after_tokens
        )
        self.config.metadata["tool_projection_tokens_saved"] = (
            self.config.metadata.get("tool_projection_tokens_saved", 0) + saved_tokens
        )
        self._write_turn_call_log(
            "tool_aggregate_projection",
            original_tool_results=len(tool_result_refs),
            compacted_tool_results=len(replacements),
            tool_result_handles=stored_handles,
            tokens_before=before_tokens,
            tokens_after=after_tokens,
        )
        return compacted_messages

    def _compact_absolute_tool_results_for_provider(
        self,
        messages: list[Message],
        tool_result_refs: list[tuple[int, int, ContentBlockToolResult]],
        tool_name_by_use_id: dict[str, str],
    ) -> list[Message]:
        cap = self._tool_result_provider_request_max_chars(ToolResultBudgetClass.LOCAL)
        if cap <= 0 or not tool_result_refs:
            return messages

        def _content(block: ContentBlockToolResult) -> str:
            return block.content if isinstance(block.content, str) else str(block.content)

        total_chars = sum(len(_content(block)) for _m, _b, block in tool_result_refs)
        external_cap = self._tool_result_provider_request_max_chars(ToolResultBudgetClass.EXTERNAL)
        external_chars = sum(
            len(_content(block))
            for _m, _b, block in tool_result_refs
            if resolve_budget_class(tool_name_by_use_id.get(block.tool_use_id, ""))
            is ToolResultBudgetClass.EXTERNAL
        )
        if total_chars <= cap and external_chars <= external_cap:
            return messages

        def _over_budget() -> bool:
            return total_chars > cap or external_chars > external_cap

        keep_recent = max(0, int(getattr(self.config, "tool_result_external_keep_recent", 2)))
        recent_refs = tool_result_refs[-keep_recent:] if keep_recent else []
        recent_ids = {id(block) for _m, _b, block in recent_refs}
        external_refs = [
            (message_index, block_index, block)
            for message_index, block_index, block in tool_result_refs
            if resolve_budget_class(tool_name_by_use_id.get(block.tool_use_id, ""))
            is ToolResultBudgetClass.EXTERNAL
        ]
        recent_external_refs = external_refs[-keep_recent:] if keep_recent else []
        recent_external_ids = {id(block) for _m, _b, block in recent_external_refs}
        replacements: dict[tuple[int, int], ContentBlockToolResult] = {}

        for message_index, block_index, block in tool_result_refs:
            if not _over_budget():
                break
            content = _content(block)
            tool_name = tool_name_by_use_id.get(block.tool_use_id, "")
            budget_class = resolve_budget_class(tool_name)
            result_cap = self._tool_result_provider_request_max_chars(budget_class)
            single_over_budget = result_cap > 0 and len(content) > result_cap
            replacement_content: str | None = None
            if budget_class is ToolResultBudgetClass.CONTROL:
                replacement_content = compact_tool_result_content(
                    tool_name=tool_name,
                    content=content,
                    max_preview_chars=160,
                    budget_class=budget_class,
                    is_error=block.is_error,
                )
            elif (
                budget_class is ToolResultBudgetClass.EXTERNAL
                and not block.is_error
                and not _tool_result_content_has_artifact(content)
                and (single_over_budget or id(block) not in recent_external_ids)
            ):
                replacement_content = self._tool_result_projection_for_provider(
                    content,
                    tool_use_id=block.tool_use_id,
                    tool_name=tool_name or "tool",
                    reason="external tool result compacted for provider request context",
                    max_preview_chars=min(result_cap, 4_000),
                )
            elif (
                not block.is_error
                and not _tool_result_content_has_artifact(content)
                and (
                    single_over_budget
                    or (self.config.context_window_tokens >= 64_000 and id(block) not in recent_ids)
                )
            ):
                replacement_content = self._tool_result_projection_for_provider(
                    content=content,
                    tool_use_id=block.tool_use_id,
                    tool_name=tool_name or "tool",
                    reason="tool result compacted for provider request context",
                    max_preview_chars=min(result_cap, 4_000),
                )

            if replacement_content is None or len(replacement_content) >= len(content):
                continue
            replacements[(message_index, block_index)] = ContentBlockToolResult(
                tool_use_id=block.tool_use_id,
                content=replacement_content,
                is_error=block.is_error,
            )
            saved_chars = len(content) - len(replacement_content)
            total_chars -= saved_chars
            if budget_class is ToolResultBudgetClass.EXTERNAL:
                external_chars -= saved_chars

        if not replacements:
            return messages

        compacted_messages: list[Message] = []
        for message_index, message in enumerate(messages):
            if not isinstance(message.content, list):
                compacted_messages.append(message)
                continue
            next_content: list[Any] = []
            message_changed = False
            for block_index, content_block in enumerate(message.content):
                replacement = replacements.get((message_index, block_index))
                if replacement is None:
                    next_content.append(content_block)
                    continue
                next_content.append(replacement)
                message_changed = True
            if not message_changed:
                compacted_messages.append(message)
                continue
            compacted_messages.append(
                Message(
                    role=message.role,
                    content=next_content,
                    reasoning_content=getattr(message, "reasoning_content", None),
                )
            )

        self.config.metadata["tool_provider_guard_projection_applied"] = True
        self.config.metadata["tool_provider_guard_projection_calls"] = (
            self.config.metadata.get("tool_provider_guard_projection_calls", 0) + 1
        )
        self.config.metadata["tool_projection_applied"] = True
        self.config.metadata["tool_projection_calls"] = self.config.metadata.get(
            "tool_projection_calls", 0
        ) + len(replacements)
        return compacted_messages

    def _tool_result_projection_for_provider(
        self,
        content: str,
        *,
        tool_use_id: str,
        tool_name: str,
        reason: str,
        max_preview_chars: int,
    ) -> str:
        max_preview_chars = max(0, int(max_preview_chars))
        if max_preview_chars > 0:
            max_preview_chars = max(1, min(max_preview_chars, 4_000))
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        stored = self._store_tool_result_snapshot(
            content,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
        )
        handle_line = f"tool_result_handle: {stored.handle}\n" if stored is not None else ""
        if max_preview_chars <= 0:
            head = ""
            tail = ""
        elif len(content) <= max_preview_chars:
            head = content
            tail = ""
        else:
            head_chars = max(1, int(max_preview_chars * 0.65))
            tail_chars = max(0, max_preview_chars - head_chars)
            head = content[:head_chars]
            tail = content[-tail_chars:] if tail_chars else ""
        omitted = max(0, len(content) - len(head) - len(tail))
        projection = (
            "[tool_result_projection]\n"
            f"tool: {tool_name}\n"
            f"tool_use_id: {tool_use_id}\n"
            f"original_chars: {len(content)}\n"
            f"sha256: {digest}\n"
            f"{handle_line}"
            f"omitted_chars: {omitted}\n"
            f"reason: {reason}.\n"
            f"head:\n{head}"
        )
        if tail:
            projection += f"\n...\ntail:\n{tail}"
        return projection

    def _sanitize_projected_tool_use_arguments_for_provider(
        self,
        messages: list[Message],
    ) -> list[Message]:
        cap = self._tool_use_argument_provider_request_max_chars("")
        replacements: dict[tuple[int, int], ContentBlockToolUse] = {}

        for message_index, message in enumerate(messages):
            if not isinstance(message.content, list):
                continue
            for block_index, block in enumerate(message.content):
                if not isinstance(block, ContentBlockToolUse):
                    continue
                if self._has_provider_context_argument_marker(block.input):
                    replacements[(message_index, block_index)] = ContentBlockToolUse(
                        id=block.id,
                        name=block.name,
                        input=self._provider_compacted_arguments_placeholder(
                            block.name,
                            block.input,
                        ),
                    )
                    continue

                legacy_projected_input = dict(block.input)
                legacy_projection_scrubbed = False
                for key, value in block.input.items():
                    if not isinstance(value, str) or not value.startswith(
                        (
                            _TOOL_ARGUMENT_PROJECTION_PREFIX,
                            _HISTORICAL_TOOL_ARGUMENT_PROJECTION_PREFIX,
                            _INVALID_PROVIDER_CONTEXT_PROJECTION_PREFIX,
                        )
                    ):
                        continue
                    legacy_projected_input[key] = self._provider_projection_placeholder(
                        block.name,
                        key,
                    )
                    legacy_projection_scrubbed = True
                if legacy_projection_scrubbed:
                    replacements[(message_index, block_index)] = ContentBlockToolUse(
                        id=block.id,
                        name=block.name,
                        input=legacy_projected_input,
                    )

        if not replacements:
            return messages

        sanitized_messages: list[Message] = []
        for message_index, message in enumerate(messages):
            if not isinstance(message.content, list):
                sanitized_messages.append(message)
                continue
            next_content: list[Any] = []
            changed = False
            for block_index, block in enumerate(message.content):
                replacement = replacements.get((message_index, block_index))
                if replacement is None:
                    next_content.append(block)
                    continue
                next_content.append(replacement)
                changed = True
            if not changed:
                sanitized_messages.append(message)
                continue
            if not next_content:
                continue
            sanitized_messages.append(
                Message(
                    role=message.role,
                    content=next_content,
                    reasoning_content=getattr(message, "reasoning_content", None),
                )
            )

        self.config.metadata["tool_argument_provider_view_summaries_applied"] = True
        metadata_key = "tool_argument_provider_view_summaries"
        self.config.metadata[metadata_key] = self.config.metadata.get(metadata_key, 0) + len(
            replacements
        )
        self._write_turn_call_log(
            "tool_argument_provider_view_summary",
            sanitized_tool_uses=len(replacements),
            max_chars=cap,
        )
        return sanitized_messages

    def _store_tool_result_snapshot(
        self,
        content: str,
        *,
        tool_use_id: str,
        tool_name: str,
    ) -> ToolResultRecord | None:
        if not self.config.tool_result_store_dir:
            return None
        session_id = self.config.tool_result_store_session_id or self._session_key
        session_key = self.config.tool_result_store_session_key or self._session_key
        agent_id = self.config.tool_result_store_agent_id
        if not agent_id and session_key:
            from opensquilla.session.keys import parse_agent_id

            agent_id = parse_agent_id(session_key)
        if not session_id or not session_key or not agent_id:
            self.config.metadata["tool_result_store_skips"] = (
                self.config.metadata.get("tool_result_store_skips", 0) + 1
            )
            return None
        try:
            record = ToolResultStore(self.config.tool_result_store_dir).write(
                content,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                session_id=session_id,
                session_key=session_key,
                agent_id=agent_id,
                max_bytes=self.config.tool_result_store_max_bytes,
                disk_budget_bytes=self.config.tool_result_store_disk_budget_bytes,
                retention_seconds=self.config.tool_result_store_retention_seconds,
            )
        except ToolResultStoreBudgetError as exc:
            self.config.metadata["tool_result_store_skips"] = (
                self.config.metadata.get("tool_result_store_skips", 0) + 1
            )
            logger.info(
                "tool_result_store.skipped",
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                reason=str(exc),
            )
            return None
        except Exception as exc:  # pragma: no cover - storage must not break turns
            logger.warning(
                "tool_result_store.write_failed",
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                error=str(exc),
            )
            return None
        self.config.metadata["tool_result_store_writes"] = (
            self.config.metadata.get("tool_result_store_writes", 0) + 1
        )
        return record

    async def _project_tool_result_for_llm(
        self,
        result: ToolResult,
        *,
        tool_call: ToolCall | None = None,
    ) -> ToolResult:
        guarded_content, guarded = _omit_large_json_tool_fields(result.content)
        if guarded:
            result = ToolResult(
                tool_use_id=result.tool_use_id,
                tool_name=result.tool_name,
                content=guarded_content,
                is_error=result.is_error,
                artifacts=list(result.artifacts),
                execution_status=(
                    mark_execution_status_truncated(result.execution_status)
                    if result.execution_status is not None
                    else None
                ),
                terminates_turn=result.terminates_turn,
            )
            self.config.metadata["tool_json_guard_applied"] = True
            self.config.metadata["tool_json_guard_calls"] = (
                self.config.metadata.get("tool_json_guard_calls", 0) + 1
            )

        self.config.metadata["tool_projection_attempts"] = (
            self.config.metadata.get("tool_projection_attempts", 0) + 1
        )
        projected_content = self._tokenjuice_tool_reduction(
            tool_name=result.tool_name,
            content=result.content,
            is_error=result.is_error,
            tool_use_id=result.tool_use_id,
            arguments=tool_call.arguments if tool_call is not None else None,
            command=self._tool_call_string_arg(tool_call, "command"),
            cwd=self._tool_call_string_arg(tool_call, "workdir", "cwd"),
        )
        if projected_content is None:
            self.config.metadata["tool_projection_noops"] = (
                self.config.metadata.get("tool_projection_noops", 0) + 1
            )
            self._write_turn_call_log(
                "tool_projection_noop",
                tool_use_id=result.tool_use_id,
                name=result.tool_name,
                original_chars=len(result.content),
            )
            return result

        stored = self._store_tool_result_snapshot(
            result.content,
            tool_use_id=result.tool_use_id,
            tool_name=result.tool_name,
        )
        stored_handle = stored.handle if stored is not None else None
        if stored is not None:
            projected_content = (
                "[tool_result_projection]\n"
                f"tool_result_handle: {stored.handle}\n"
                f"sha256: {stored.sha256}\n"
                f"original_chars: {stored.chars}\n"
                f"{projected_content}"
            )

        tokens_before = get_approx_tokens(result.content)
        tokens_after = get_approx_tokens(projected_content)
        self.config.metadata["tool_projection_applied"] = True
        self.config.metadata["tool_projection_calls"] = (
            self.config.metadata.get("tool_projection_calls", 0) + 1
        )
        self.config.metadata["tool_projection_tokens_before"] = (
            self.config.metadata.get("tool_projection_tokens_before", 0) + tokens_before
        )
        self.config.metadata["tool_projection_tokens_after"] = (
            self.config.metadata.get("tool_projection_tokens_after", 0) + tokens_after
        )
        self.config.metadata["tool_projection_tokens_saved"] = self.config.metadata.get(
            "tool_projection_tokens_saved", 0
        ) + max(0, tokens_before - tokens_after)

        self._write_turn_call_log(
            "tool_projection_applied",
            tool_use_id=result.tool_use_id,
            name=result.tool_name,
            tool_result_handle=stored_handle,
            original_chars=len(result.content),
            projected_chars=len(projected_content),
        )
        return ToolResult(
            tool_use_id=result.tool_use_id,
            tool_name=result.tool_name,
            content=projected_content,
            is_error=result.is_error,
            artifacts=list(result.artifacts),
            execution_status=result.execution_status,
            terminates_turn=result.terminates_turn,
        )

    async def _canonicalize_tool_result(
        self,
        result: ToolResult,
        *,
        tool_call: ToolCall | None = None,
    ) -> ToolResult:
        return await self._project_tool_result_for_llm(result, tool_call=tool_call)

    def _record_provider_tool_result_projection(
        self,
        result: ToolResult,
        projected_result: ToolResult,
    ) -> None:
        if projected_result.content != result.content:
            self._provider_tool_result_overrides[result.tool_use_id] = ContentBlockToolResult(
                tool_use_id=projected_result.tool_use_id,
                content=projected_result.content,
                is_error=projected_result.is_error,
                execution_status=projected_result.execution_status,
            )
            return
        self._provider_tool_result_overrides.pop(result.tool_use_id, None)

    async def _project_tool_result_for_delivery(
        self,
        result: ToolResult,
        *,
        tool_call: ToolCall | None = None,
    ) -> ToolResult:
        if _pending_approval_payload(result.content) is not None:
            self._provider_tool_result_overrides.pop(result.tool_use_id, None)
            return result
        projected_result = await self._project_tool_result_for_llm(
            result,
            tool_call=tool_call,
        )
        self._record_provider_tool_result_projection(result, projected_result)
        return projected_result

    def _tool_result_compression_mode(self) -> str:
        mode = self.config.tool_result_compression_mode
        if mode in {"off", "truncate", "summarize"}:
            return mode
        return "truncate" if self.config.tool_result_compression_enabled else "off"

    def _tool_result_over_budget(self, text: str) -> bool:
        budget_tokens = int(
            self.config.context_window_tokens * self.config.tool_result_compression_max_share
        )
        return get_approx_tokens(text) > budget_tokens

    async def _compress_tool_result(self, result: ToolResult) -> ToolResult:
        """Compatibility wrapper for legacy compression callers.

        The current runtime projects tool results with Tokenjuice. This helper
        remains for embedded tests and callers that exercise the older
        compression API directly.
        """
        guarded_content, guarded = _omit_large_json_tool_fields(result.content)
        if guarded:
            result = ToolResult(
                tool_use_id=result.tool_use_id,
                tool_name=result.tool_name,
                content=guarded_content,
                is_error=result.is_error,
                artifacts=list(result.artifacts),
                execution_status=(
                    mark_execution_status_truncated(result.execution_status)
                    if result.execution_status is not None
                    else None
                ),
                terminates_turn=result.terminates_turn,
            )
        mode = self._tool_result_compression_mode()
        if mode == "off" or not self._tool_result_over_budget(result.content):
            return result

        budget_tokens = int(
            self.config.context_window_tokens * self.config.tool_result_compression_max_share
        )
        max_preview_chars = max(0, budget_tokens * 4)
        compressed_content = compact_tool_result_content(
            tool_name=result.tool_name,
            content=result.content,
            max_preview_chars=max_preview_chars,
            budget_class=resolve_budget_class(result.tool_name),
            is_error=result.is_error,
        )
        return ToolResult(
            tool_use_id=result.tool_use_id,
            tool_name=result.tool_name,
            content=compressed_content,
            is_error=result.is_error,
            artifacts=list(result.artifacts),
            execution_status=(
                mark_execution_status_truncated(result.execution_status)
                if result.execution_status is not None
                else None
            ),
            terminates_turn=result.terminates_turn,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> AgentState:
        return self._state

    def refresh_system_prompt(self, new_prompt: str) -> None:
        """Update system prompt mid-turn (called after compaction to reflect fresh memory)."""
        # Invariant: this mutates `_context.system_prompt`, but
        # `chat_cfg.system` passed to the provider is snapshotted at
        # turn-start (see run_turn below). Refreshes therefore only take
        # effect on subsequent turns — never mid-turn — so memory_save
        # cannot swap the system prompt under an in-flight provider call.
        if self.config.system_prompt is not None:
            self.config.system_prompt = new_prompt
            if self._context is not None:
                self._context.system_prompt = new_prompt
            # cache_breakpoints carry the previous base's
            # text and would mismatch the refreshed prompt on the next
            # provider call (chat_cfg.system would be new_prompt while
            # chat_cfg.cache_breakpoints[0]['text'] still pointed at the
            # pre-compaction base). Re-anchor breakpoints on the new prompt.
            # Callers (TurnRunner compaction-refresh) MUST pass only the
            # cacheable base here — if ``_assemble_prompt`` returns a
            # tuple, the dynamic suffix is dropped before this call so
            # ``new_prompt`` is byte-identical to the next turn's base.
            if self.config.cache_breakpoints:
                self.config.cache_breakpoints = [{"text": new_prompt, "cache": "true"}]

    def clear_history(self) -> None:
        self._history = []

    def set_history(self, messages: list[Message]) -> None:
        self._history = list(messages)

    async def run_turn(
        self,
        message: str,
        extra_messages: list[Message] | None = None,
        semantic_message: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one agent turn, yielding AgentEvents.

        Explicit state machine — no recursion. Tool loop iterates until
        the model finishes, unless config.max_iterations is a positive cap.
        """
        async for event in self._turn_generator(message, extra_messages, semantic_message):
            yield event

    async def _turn_generator(
        self,
        message: str,
        extra_messages: list[Message] | None = None,
        semantic_message: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Async generator that drives the state machine."""
        self._provider_tool_result_overrides = {}
        self._current_turn_message = message
        _meta_invoke_turn_count.set(0)

        # ------ IDLE → THINKING ------
        yield self._transition(AgentState.THINKING)

        # PR7/9 E2E fix — consume meta_resolution's awaiting-branch
        # outcomes. meta_resolution stages six distinct outcomes on
        # ctx.metadata (resume / errors / cancelled / expired /
        # race_lost / [trigger match for fresh turn]) and returns; the
        # runtime owns the user-visible feedback for the first five so
        # the turn terminates cleanly instead of falling through to the
        # LLM (which would re-trigger meta_invoke and hit the
        # awaiting-guard with an opaque message).
        metadata = self.config.metadata or {}
        meta_resume = metadata.get("meta_resume")
        if meta_resume is not None:
            async for ev in self._run_meta_resume(meta_resume):
                yield ev
            return
        clarify_outcome = self._read_clarify_outcome(metadata)
        if clarify_outcome is not None:
            text, terminates = clarify_outcome
            async for ev in self._emit_terminal_text(text, iterations=0):
                yield ev
            _ = terminates  # always terminates today; reserved for future
            return

        # Use the system prompt from config (wired by gateway via identity.prompt)
        if self._context is None:
            self._context = ContextAssembly(
                system_prompt=self.config.system_prompt or "",
                workspace_dir=self.config.workspace_dir,
            )

        thinking_prompt = semantic_message if semantic_message is not None else message
        thinking_enabled, thinking_budget = self.config.resolve_thinking(prompt=thinking_prompt)

        # Preprocess history for the provider request view. This does not
        # mutate persisted transcript rows or tool result content.
        # Some reasoning tool-call providers require the prior assistant
        # tool-call message to carry its reasoning_content while reasoning is
        # enabled, so keep that narrow field only for tool-call history.
        caps_reasoning_format = (
            getattr(self.config.model_capabilities, "reasoning_format", "")
            if self.config.model_capabilities is not None
            else ""
        )
        preserve_reasoning_content = bool(
            _is_direct_deepseek_v4_model_id(self.config.model_id)
            or (
                thinking_enabled
                and caps_reasoning_format == "deepseek"
                and _is_deepseek_model_id(self.config.model_id)
            )
        )
        loaded_history = list(self._history)
        self._write_context_stage("session:loaded", loaded_history)
        sanitized_history, sanitize_result = sanitize_session_messages(loaded_history)
        sanitized_history, historical_projection_result = project_historical_tool_payloads(
            sanitized_history,
            preserve_reasoning_content=preserve_reasoning_content,
        )
        sanitized_history = repair_tool_pairing(sanitized_history)
        sanitized_history = drop_reasoning(
            sanitized_history,
            preserve_tool_call_reasoning=thinking_enabled,
            preserve_reasoning_content=preserve_reasoning_content,
        )
        sanitized_history = _strip_historical_image_blocks(sanitized_history)
        self._write_context_stage(
            "session:sanitized",
            sanitized_history,
            sanitize=sanitize_result,
            historical_projection=historical_projection_result.__dict__,
        )
        history = limit_turns(sanitized_history, self.config.max_history_turns)
        history = repair_tool_pairing(history)
        self._write_context_stage(
            "session:limited",
            history,
            removed_messages=max(len(sanitized_history) - len(history), 0),
        )

        # Build initial message list
        turn_messages: list[Message] = list(history)
        # Insert this turn's skills context BEFORE the user content so it
        # joins turn_messages permanently (persists into self._history at
        # turn end). Re-inserting a fresh skills_ctx into request_messages
        # every turn — the previous design — broke the KV-cache prefix:
        # past skills_ctx vanished while a new one slid in at a moving
        # position, so providers couldn't cache the conversation prefix.
        # Now each turn's skills list lands in history once and stays there;
        # only the runtime context (timestamp) remains transient.
        skills_context_message = self._skills_context_message()
        if skills_context_message is not None:
            turn_messages.append(skills_context_message)
        # Keep persisted history and persisted skills as the provider-visible
        # prefix. Request-scoped context can change every turn, so keep it near
        # the current turn instead of letting it invalidate implicit prefix
        # caches from messages[0].
        request_context_insert_index = len(turn_messages)
        runtime_context_insert_index = len(turn_messages)
        if extra_messages:
            turn_messages.extend(extra_messages)
        # Only append text message if non-empty (multimodal may use extra_messages instead)
        if message:
            if not extra_messages:
                runtime_context_insert_index = len(turn_messages)
            turn_messages.append(Message(role="user", content=message))
        self._write_context_stage("prompt:before", turn_messages)
        self._write_context_stage(
            "prompt:images",
            turn_messages,
            image_blocks=self._count_image_blocks(turn_messages),
        )
        runtime_context = self._runtime_context_block()
        runtime_context_message = self._runtime_context_message(runtime_context)
        request_context_message = self._request_context_message(self.config.request_context_prompt)
        runtime_context_hash = hashlib.sha256(runtime_context.encode("utf-8")).hexdigest()[:16]

        chat_cfg = ChatConfig(
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=self._context.system_prompt,
            thinking=thinking_enabled,
            thinking_budget_tokens=thinking_budget,
            timeout=self.config.request_timeout,
            stop_sequences=self.config.stop_sequences,
            cache_breakpoints=self._cache_breakpoints_without_runtime_context(
                self.config.cache_breakpoints
            ),
            cache_mode=self.config.cache_mode,
            model_capabilities=self.config.model_capabilities,
            thinking_level=(
                self.config.thinking if isinstance(self.config.thinking, ThinkingLevel) else None
            ),
            provider_request_max_chars=self._provider_request_proof_max_chars(),
            tool_choice=None,
        )
        _thinking_fallback_done = False

        _log = structlog.get_logger("opensquilla.engine.agent")
        iterations = 0
        overflow_retries = 0
        # Keep lifetime usage separate from the live context-window gauge.
        # Compaction shrinks what the model sees next; it must not erase the
        # turn's already-spent provider tokens from the final DoneEvent.
        total_input_tokens = 0
        total_output_tokens = 0
        total_reasoning_tokens = 0
        total_cached_tokens = 0
        total_cache_write_tokens = 0
        total_billed_cost = 0.0
        usage_turn_baseline = (
            self._usage_tracker.session_checkpoint(self._session_key)
            if self._usage_tracker and self._session_key
            else None
        )
        turn_llm_calls = 0
        turn_tool_errors = 0
        last_actual_model = ""
        terminal_error: ErrorEvent | None = None
        final_text_parts: list[str] = []
        final_reasoning_parts: list[str] = []
        artifact_delivery_final_response_pending = False
        artifact_delivery_degraded_final_response = False
        artifact_delivery_final_response_artifacts: list[dict[str, Any]] = []
        max_iterations_finalization_attempted = False
        max_iterations_finalization_pending = False
        max_iterations_finalization_message: Message | None = None
        progress_watchdog = ProgressWatchdog(observe_only=True)
        _fallback = FallbackPolicy(
            max_retries=self.config.max_provider_retries,
            base_backoff_ms=self.config.retry_base_backoff_ms,
            max_backoff_ms=self.config.retry_max_backoff_ms,
        )

        # Timeout budgets: optional total turn budget, idle LLM stream budget,
        # and per-tool execution budget.
        _loop = asyncio.get_running_loop()
        _total_deadline = _loop.time() + self.config.timeout if self.config.timeout > 0 else None
        tools_supported = True
        if self.config.model_capabilities is not None:
            tools_supported = bool(getattr(self.config.model_capabilities, "supports_tools", True))
        provider_tool_definitions = self.tool_definitions or None
        if not tools_supported:
            provider_tool_definitions = None

        def _positive_float(value: Any) -> float | None:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return None
            return parsed if parsed > 0 else None

        def _turn_budget_error() -> ErrorEvent | None:
            max_llm_calls = self._positive_int(getattr(self.config, "max_turn_llm_calls", 0))
            if max_llm_calls is not None and turn_llm_calls > max_llm_calls:
                return ErrorEvent(
                    message=(
                        f"Turn stopped after {turn_llm_calls} LLM calls "
                        f"(max_turn_llm_calls={max_llm_calls})."
                    ),
                    code="turn_llm_call_budget_exceeded",
                )
            max_input = self._positive_int(getattr(self.config, "max_turn_input_tokens", 0))
            if max_input is not None and total_input_tokens > max_input:
                return ErrorEvent(
                    message=(
                        f"Turn stopped after {total_input_tokens} input tokens "
                        f"(max_turn_input_tokens={max_input})."
                    ),
                    code="turn_input_token_budget_exceeded",
                )
            max_output = self._positive_int(getattr(self.config, "max_turn_output_tokens", 0))
            if max_output is not None and total_output_tokens > max_output:
                return ErrorEvent(
                    message=(
                        f"Turn stopped after {total_output_tokens} output tokens "
                        f"(max_turn_output_tokens={max_output})."
                    ),
                    code="turn_output_token_budget_exceeded",
                )
            max_cost = _positive_float(getattr(self.config, "max_turn_billed_cost_usd", 0.0))
            if max_cost is not None and total_billed_cost > max_cost:
                return ErrorEvent(
                    message=(
                        f"Turn stopped after ${total_billed_cost:.6f} billed cost "
                        f"(max_turn_billed_cost_usd=${max_cost:.6f})."
                    ),
                    code="turn_billed_cost_budget_exceeded",
                )
            max_tool_errors = self._positive_int(getattr(self.config, "max_turn_tool_errors", 0))
            if max_tool_errors is not None and turn_tool_errors >= max_tool_errors:
                return ErrorEvent(
                    message=(
                        f"Turn stopped after {turn_tool_errors} tool errors "
                        f"(max_turn_tool_errors={max_tool_errors})."
                    ),
                    code="turn_tool_error_budget_exceeded",
                )
            return None

        def _turn_llm_call_budget_error(next_call_number: int) -> ErrorEvent | None:
            max_llm_calls = self._positive_int(getattr(self.config, "max_turn_llm_calls", 0))
            if max_llm_calls is None or next_call_number <= max_llm_calls:
                return None
            return ErrorEvent(
                message=(
                    f"Turn stopped before LLM call {next_call_number} "
                    f"(max_turn_llm_calls={max_llm_calls})."
                ),
                code="turn_llm_call_budget_exceeded",
            )

        def _finish_artifact_delivery_degraded(
            *,
            reason: str,
            code: str,
        ) -> WarningEvent:
            nonlocal artifact_delivery_degraded_final_response
            nonlocal artifact_delivery_final_response_pending
            if not "".join(final_text_parts).strip():
                final_text_parts.append(
                    self._artifact_delivery_final_response_text(
                        artifact_delivery_final_response_artifacts
                    )
                )
            artifact_delivery_degraded_final_response = True
            artifact_delivery_final_response_pending = False
            self._write_turn_call_log(
                "artifact_final_response_degraded",
                reason=reason,
                code=code,
                artifact_count=len(artifact_delivery_final_response_artifacts),
            )
            return WarningEvent(
                code="artifact_delivery_final_response_degraded",
                message=(
                    "Artifact delivery completed, but the model could not generate "
                    "the final explanatory response. Returning a deterministic "
                    "completion message instead."
                ),
            )

        def _finish_artifact_delivery_without_provider() -> None:
            final_response_text = self._artifact_delivery_final_response_text(
                artifact_delivery_final_response_artifacts
            )
            current_text = "".join(final_text_parts)
            if final_response_text not in current_text:
                prefix = "\n\n" if current_text.strip() else ""
                final_text_parts.append(prefix + final_response_text)
            self._write_turn_call_log(
                "artifact_final_response_synthesized",
                reason="publish_artifact_completed",
                artifact_count=len(artifact_delivery_final_response_artifacts),
            )

        try:
            while True:
                if (
                    self.config.max_iterations > 0
                    and iterations >= self.config.max_iterations
                ):
                    max_iterations_source = str(
                        self.config.metadata.get(
                            "agent_max_iterations_source", "agent_config"
                        )
                    )
                    if max_iterations_source == "session config":
                        max_iterations_guidance = (
                            "Set session agent_max_iterations=0 for unlimited tasks."
                        )
                    elif max_iterations_source == "gateway config":
                        max_iterations_guidance = (
                            "Set gateway agent_max_iterations=0 for unlimited tasks."
                        )
                    elif max_iterations_source.startswith("env "):
                        max_iterations_guidance = (
                            "Set OPENSQUILLA_AGENT_MAX_ITERATIONS=0 "
                            "for unlimited tasks."
                        )
                    elif max_iterations_source == "explicit argument":
                        max_iterations_guidance = (
                            "Pass --max-iterations 0 or max_iterations=0 "
                            "for unlimited tasks."
                        )
                    else:
                        max_iterations_guidance = (
                            "Set AgentConfig.max_iterations=0 for unlimited tasks."
                        )
                    if not max_iterations_finalization_attempted:
                        max_iterations_finalization_attempted = True
                        max_iterations_finalization_pending = True
                        max_iterations_finalization_message = Message(
                            role="user",
                            content=(
                                "The configured iteration limit has been reached. "
                                "Do not call tools. Provide the best concise final "
                                "answer from the work completed so far."
                            ),
                        )
                        self._write_turn_call_log(
                            "turn_policy_decision",
                            action="finalize_partial",
                            reason="max_iterations",
                            code="max_iterations",
                            iteration=iterations,
                            max_iterations=self.config.max_iterations,
                            max_iterations_source=max_iterations_source,
                        )
                    else:
                        self._write_turn_call_log(
                            "turn_policy_decision",
                            action="partial",
                            reason="max_iterations",
                            code="max_iterations",
                            iteration=iterations,
                            max_iterations=self.config.max_iterations,
                            max_iterations_source=max_iterations_source,
                        )
                        terminal_error = ErrorEvent(
                            message=(
                                f"Reached max_iterations={self.config.max_iterations} "
                                f"from {max_iterations_source} after a finalization attempt. "
                                f"{max_iterations_guidance}"
                            ),
                            code="max_iterations",
                        )
                        yield terminal_error
                        break

                # Check total turn deadline (if configured)
                if _total_deadline is not None and _loop.time() > _total_deadline:
                    raise TimeoutError(f"Agent total timeout after {self.config.timeout}s")

                iterations += 1

                # ------ THINKING → STREAMING ------
                yield self._transition(AgentState.STREAMING)

                # Collect this LLM response
                assistant_text_parts: list[str] = []
                tool_calls: list[ToolCall] = []
                pending_tools: dict[str, _StreamAccumulator] = {}
                tool_argument_heartbeat_chars: dict[str, int] = {}
                iter_input_tokens = 0
                iter_output_tokens = 0
                iter_reasoning_tokens = 0
                iter_reasoning_content: str | None = None
                iter_thinking_signature: str | None = None
                provider_error: ProviderErrorEvent | None = None

                _retry_attempt = 0
                _call_attempt = 0
                _retry_policy = _ProviderRetryPolicy.from_provider_budget(
                    _fallback.max_retries,
                    length_capped_continuations=self.config.length_capped_continuations,
                )
                _attempt_retries_used = _retry_policy.used_attempts()
                _invalid_response_fallback_done = False
                while _retry_attempt <= _fallback.max_retries:
                    provider_error = None
                    assistant_text_parts = []
                    tool_calls = []
                    pending_tools = {}
                    tool_argument_heartbeat_chars = {}
                    iter_input_tokens = 0
                    iter_output_tokens = 0
                    iter_reasoning_tokens = 0
                    iter_reasoning_content = None
                    iter_thinking_signature = None
                    _got_error = False
                    provider_done_for_log: ProviderDoneEvent | None = None
                    provider_error_for_log: ProviderErrorEvent | None = None
                    call_id = f"{iterations}.{_call_attempt}"
                    call_started_at = time.monotonic()
                    provider_tools_for_call = (
                        None
                        if (
                            artifact_delivery_final_response_pending
                            or max_iterations_finalization_pending
                        )
                        else provider_tool_definitions
                    )
                    tools_supported_for_call = (
                        tools_supported
                        and not artifact_delivery_final_response_pending
                        and not max_iterations_finalization_pending
                    )
                    ignored_post_delivery_tool_use = False
                    request_turn_messages = (
                        [*turn_messages, max_iterations_finalization_message]
                        if (
                            max_iterations_finalization_pending
                            and max_iterations_finalization_message is not None
                        )
                        else turn_messages
                    )
                    (
                        request_messages,
                        request_sanitize_result,
                    ) = self._provider_request_messages_with_sanitize(
                        request_turn_messages,
                        request_context_message=request_context_message,
                        request_context_insert_index=request_context_insert_index,
                        runtime_context_message=runtime_context_message,
                        runtime_context_insert_index=runtime_context_insert_index,
                    )
                    self._write_context_stage(
                        "stream:context",
                        request_messages,
                        call_id=call_id,
                        iteration=iterations,
                        attempt=_call_attempt,
                        sanitize=request_sanitize_result,
                    )

                    terminal_error = _turn_llm_call_budget_error(turn_llm_calls + 1)
                    if terminal_error is not None:
                        self._write_turn_call_log(
                            "turn_policy_decision",
                            action=(
                                "artifact_degraded_finish"
                                if artifact_delivery_final_response_pending
                                else "stop"
                            ),
                            reason=terminal_error.message,
                            code=terminal_error.code,
                            sent_llm_calls=turn_llm_calls,
                            attempted_llm_call=turn_llm_calls + 1,
                            iteration=iterations,
                            attempt=_call_attempt,
                        )
                        if artifact_delivery_final_response_pending:
                            yield _finish_artifact_delivery_degraded(
                                reason=terminal_error.message,
                                code=terminal_error.code,
                            )
                            terminal_error = None
                        else:
                            yield self._transition(AgentState.ERROR)
                            yield terminal_error
                        break

                    call_chat_cfg = chat_cfg
                    forced_tool_choice = self.config.metadata.get("meta_match_tool_choice")
                    if (
                        forced_tool_choice is not None
                        and provider_tools_for_call
                        and request_messages
                        and not _message_has_tool_result(request_messages[-1])
                    ):
                        call_chat_cfg = chat_cfg.model_copy(
                            update={"tool_choice": forced_tool_choice}
                        )

                    self._write_turn_call_log(
                        "llm_request",
                        call_id=call_id,
                        iteration=iterations,
                        attempt=_call_attempt,
                        messages=request_messages,
                        tools=provider_tools_for_call,
                        config=call_chat_cfg,
                    )
                    turn_llm_calls += 1
                    cache_prompt_snapshot = None
                    if self._session_key:
                        cache_prompt_snapshot = record_prompt_state(
                            messages=request_messages,
                            tools=provider_tools_for_call,
                            config=call_chat_cfg,
                            model=self.config.model_id or "",
                        )

                    _got_done_event = False
                    attempt_user_visible_emitted = False
                    try:
                        raw_stream = self.provider.chat(
                            request_messages,
                            tools=provider_tools_for_call,
                            config=call_chat_cfg,
                        )
                        async for raw_ev in self._stream_provider_events_with_deadline(
                            raw_stream,
                            loop=_loop,
                            total_deadline=_total_deadline,
                        ):
                            if isinstance(raw_ev, ProviderTextDelta):
                                assistant_text_parts.append(raw_ev.text)
                                if raw_ev.text:
                                    attempt_user_visible_emitted = True
                                yield TextDeltaEvent(text=raw_ev.text)

                            elif isinstance(raw_ev, ProviderToolUseStart):
                                if not tools_supported_for_call:
                                    if (
                                        artifact_delivery_final_response_pending
                                        or max_iterations_finalization_pending
                                    ):
                                        ignored_post_delivery_tool_use = True
                                    continue
                                pending_tools[raw_ev.tool_use_id] = _StreamAccumulator(
                                    tool_use_id=raw_ev.tool_use_id,
                                    tool_name=raw_ev.tool_name,
                                    synthetic_from_text=raw_ev.synthetic_from_text,
                                )
                                tool_argument_heartbeat_chars[raw_ev.tool_use_id] = 0
                                attempt_user_visible_emitted = True
                                yield ToolUseStartEvent(
                                    tool_use_id=raw_ev.tool_use_id,
                                    tool_name=raw_ev.tool_name,
                                    synthetic_from_text=raw_ev.synthetic_from_text,
                                )

                            elif raw_ev.kind == "tool_use_delta":
                                if not tools_supported_for_call:
                                    continue
                                acc = pending_tools.get(raw_ev.tool_use_id)  # type: ignore[union-attr]
                                if acc:
                                    json_fragment = raw_ev.json_fragment  # type: ignore[union-attr]
                                    acc.json_buf.append(json_fragment)
                                    acc.json_chars += len(json_fragment)
                                    last_heartbeat_chars = tool_argument_heartbeat_chars.get(
                                        raw_ev.tool_use_id, 0
                                    )
                                    if (
                                        acc.json_chars - last_heartbeat_chars
                                        >= _TOOL_ARGUMENT_HEARTBEAT_CHARS
                                    ):
                                        tool_argument_heartbeat_chars[raw_ev.tool_use_id] = (
                                            acc.json_chars
                                        )
                                        yield RunHeartbeatEvent(
                                            phase="llm_tool_arguments",
                                            elapsed_ms=int(
                                                (time.monotonic() - call_started_at) * 1000
                                            ),
                                            idle_ms=0,
                                            message=(f"Receiving {acc.tool_name} arguments"),
                                        )

                            elif isinstance(raw_ev, ToolUseEndEvent):
                                if not tools_supported_for_call:
                                    if (
                                        artifact_delivery_final_response_pending
                                        or max_iterations_finalization_pending
                                    ):
                                        ignored_post_delivery_tool_use = True
                                    continue
                                acc = pending_tools.pop(raw_ev.tool_use_id, None)
                                tool_argument_heartbeat_chars.pop(raw_ev.tool_use_id, None)
                                if acc and acc.json_buf:
                                    arguments = acc.finish()
                                else:
                                    arguments = raw_ev.arguments
                                synthetic_from_text = (
                                    acc.synthetic_from_text
                                    if acc is not None
                                    else raw_ev.synthetic_from_text
                                )
                                tool_calls.append(
                                    ToolCall(
                                        tool_use_id=raw_ev.tool_use_id,
                                        tool_name=raw_ev.tool_name,
                                        arguments=arguments,
                                        synthetic_from_text=synthetic_from_text,
                                    )
                                )

                            elif isinstance(raw_ev, ProviderDoneEvent):
                                provider_done_for_log = raw_ev
                                _got_done_event = True
                                iter_input_tokens = raw_ev.input_tokens
                                iter_output_tokens = raw_ev.output_tokens
                                iter_reasoning_tokens = raw_ev.reasoning_tokens
                                iter_reasoning_content = raw_ev.reasoning_content
                                iter_thinking_signature = raw_ev.thinking_signature
                                total_billed_cost += raw_ev.billed_cost
                                total_input_tokens += raw_ev.input_tokens
                                total_output_tokens += raw_ev.output_tokens
                                total_reasoning_tokens += raw_ev.reasoning_tokens
                                total_cached_tokens += raw_ev.cached_tokens
                                total_cache_write_tokens += raw_ev.cache_write_tokens
                                if raw_ev.model:
                                    last_actual_model = raw_ev.model
                                # Usage/cost accounting is billed-attempt based: discarded
                                # invalid responses still consumed provider tokens, but
                                # they must not be appended to conversation history or the
                                # live context-window gauge below.
                                if self._usage_tracker and self._session_key:
                                    # Forward the provider's real per-call billed_cost so
                                    # the per-model breakdown can show actual numbers
                                    # instead of the cache-blind pricing-table estimate.
                                    # See engine/usage.py:ModelUsage.billed_cost and
                                    # gateway/rpc_usage.py:_reconcile_breakdown_to_row
                                    # (the pro-rate fallback now skips when items
                                    # already carry real billed totals).
                                    self._usage_tracker.add(
                                        self._session_key,
                                        input_tokens=raw_ev.input_tokens,
                                        output_tokens=raw_ev.output_tokens,
                                        model_id=raw_ev.model or self.config.model_id or "",
                                        cache_read_tokens=raw_ev.cached_tokens,
                                        cache_write_tokens=raw_ev.cache_write_tokens,
                                        billed_cost=raw_ev.billed_cost,
                                    )

                            elif isinstance(raw_ev, ProviderErrorEvent):
                                provider_error_for_log = raw_ev
                                # One-shot thinking/reasoning fallback
                                _err_lower = raw_ev.message.lower()
                                if (
                                    thinking_enabled
                                    and not _thinking_fallback_done
                                    and ("thinking" in _err_lower or "reasoning" in _err_lower)
                                ):
                                    _thinking_fallback_done = True
                                    thinking_enabled = False
                                    thinking_budget = 0
                                    chat_cfg = _chat_config_with_thinking_disabled(chat_cfg)
                                    _got_error = True
                                    break  # break stream, retry

                                provider_error = raw_ev
                                _got_error = True
                                break  # break stream loop

                            elif isinstance(raw_ev, ProviderHeartbeatEvent):
                                yield RunHeartbeatEvent(
                                    phase=raw_ev.phase,
                                    message=raw_ev.message,
                                )
                    except _IterationStreamTimeoutError:
                        if artifact_delivery_final_response_pending:
                            yield _finish_artifact_delivery_degraded(
                                reason=(
                                    f"Iteration {iterations} exceeded "
                                    f"iteration_timeout ({self.config.iteration_timeout}s) "
                                    "during final artifact response generation"
                                ),
                                code="iteration_timeout",
                            )
                            break
                        yield self._transition(AgentState.ERROR)
                        terminal_error = ErrorEvent(
                            message=(
                                f"Iteration {iterations} exceeded iteration_timeout"
                                f" ({self.config.iteration_timeout}s) during LLM streaming"
                            ),
                            code="iteration_timeout",
                        )
                        yield terminal_error
                        break

                    call_duration_ms = int((time.monotonic() - call_started_at) * 1000)
                    response_payload = {
                        "call_id": call_id,
                        "iteration": iterations,
                        "attempt": _call_attempt,
                        "duration_ms": call_duration_ms,
                        "text": "".join(assistant_text_parts),
                        "tool_calls": [
                            {
                                "tool_use_id": tc.tool_use_id,
                                "name": tc.tool_name,
                                "arguments": tc.arguments,
                            }
                            for tc in tool_calls
                        ],
                        "got_done_event": _got_done_event,
                    }
                    if provider_done_for_log is not None:
                        response_payload["usage"] = {
                            "stop_reason": provider_done_for_log.stop_reason,
                            "input_tokens": provider_done_for_log.input_tokens,
                            "output_tokens": provider_done_for_log.output_tokens,
                            "reasoning_tokens": provider_done_for_log.reasoning_tokens,
                            "cached_tokens": provider_done_for_log.cached_tokens,
                            "cache_write_tokens": provider_done_for_log.cache_write_tokens,
                            "billed_cost": provider_done_for_log.billed_cost,
                            "cost_source": getattr(provider_done_for_log, "cost_source", "none"),
                            "model": provider_done_for_log.model,
                        }
                    if provider_error_for_log is not None:
                        response_payload["error"] = {
                            "message": provider_error_for_log.message,
                            "code": provider_error_for_log.code,
                        }
                        self._write_turn_call_log("llm_error", **response_payload)
                    else:
                        self._write_turn_call_log("llm_response", **response_payload)

                    # -- after async for (retry loop level) --
                    terminal_error = _turn_budget_error()
                    if terminal_error is not None:
                        if artifact_delivery_final_response_pending:
                            yield _finish_artifact_delivery_degraded(
                                reason=terminal_error.message,
                                code=terminal_error.code,
                            )
                            terminal_error = None
                        else:
                            yield self._transition(AgentState.ERROR)
                            yield terminal_error
                        break
                    response_text = "".join(assistant_text_parts)
                    if ignored_post_delivery_tool_use and not response_text.strip():
                        if artifact_delivery_final_response_pending:
                            response_text = self._artifact_delivery_final_response_text(
                                artifact_delivery_final_response_artifacts
                            )
                        elif max_iterations_finalization_pending:
                            response_text = (
                                "I reached the configured iteration limit after completing "
                                "the available tool step. Here is the best partial result so far."
                            )
                        if response_text:
                            assistant_text_parts.append(response_text)
                            attempt_user_visible_emitted = True
                            yield TextDeltaEvent(text=response_text)
                    last_request_msg = request_messages[-1] if request_messages else None
                    post_tool_turn = _message_has_tool_result(last_request_msg)
                    stop_reason = (
                        getattr(provider_done_for_log, "stop_reason", None)
                        if provider_done_for_log is not None
                        else None
                    )
                    attempt_classification = _classify_provider_attempt(
                        text=response_text,
                        tool_calls=tool_calls,
                        pending_tools=pending_tools,
                        got_done_event=_got_done_event,
                        stop_reason=stop_reason,
                        reasoning_content=iter_reasoning_content,
                        reasoning_tokens=iter_reasoning_tokens,
                        user_visible_emitted=attempt_user_visible_emitted,
                    )
                    if not _got_error and attempt_classification.kind != _ProviderAttemptKind.OK:
                        logger.warning(
                            "provider.invalid_response",
                            session_key=self._session_key,
                            model=last_actual_model or self.config.model_id or "",
                            provider=type(self.provider).__name__,
                            classification=attempt_classification.kind.value,
                            iteration=iterations,
                            call_attempt=_call_attempt,
                            provider_retry_attempt=_retry_attempt,
                            post_tool_turn=post_tool_turn,
                            got_done_event=_got_done_event,
                            stop_reason=stop_reason,
                            iter_input_tokens=iter_input_tokens,
                            iter_output_tokens=iter_output_tokens,
                            iter_reasoning_tokens=iter_reasoning_tokens,
                            reasoning_chars=len(iter_reasoning_content or ""),
                        )

                        large_context_invalid = _is_large_context_invalid_response(
                            attempt_classification.kind,
                            input_tokens=iter_input_tokens,
                        )
                        if large_context_invalid:
                            if (
                                not _invalid_response_fallback_done
                                and self._switch_to_invalid_response_fallback(
                                    attempt_classification.kind.value
                                )
                            ):
                                _invalid_response_fallback_done = True
                                yield WarningEvent(
                                    code="provider_large_context_fallback",
                                    message=(
                                        "The provider returned no visible response for a "
                                        "large input; trying a fallback provider once."
                                    ),
                                )
                                _call_attempt += 1
                                continue

                            yield self._transition(AgentState.ERROR)
                            terminal_error = ErrorEvent(
                                message=(
                                    "Provider returned no visible response for a large input. "
                                    "Send the material as an attachment, summarize or shorten "
                                    "the prompt, or use a stronger model."
                                ),
                                code="empty_response",
                            )
                            yield terminal_error
                            break

                        if (
                            attempt_classification.kind == _ProviderAttemptKind.REASONING_ONLY
                            and thinking_enabled
                            and _retry_policy.can_retry_attempt(
                                _ProviderAttemptKind.REASONING_ONLY,
                                _attempt_retries_used,
                            )
                        ):
                            _attempt_retries_used[_ProviderAttemptKind.REASONING_ONLY] += 1
                            _thinking_fallback_done = True
                            thinking_enabled = False
                            thinking_budget = 0
                            chat_cfg = _chat_config_with_thinking_disabled(chat_cfg)
                            yield WarningEvent(
                                code="provider_reasoning_only_retry",
                                message=(
                                    "The provider returned reasoning without visible content; "
                                    "retrying once with thinking disabled."
                                ),
                            )
                            _call_attempt += 1
                            continue

                        if (
                            attempt_classification.kind == _ProviderAttemptKind.MALFORMED_EMPTY
                            and _retry_policy.can_retry_attempt(
                                _ProviderAttemptKind.MALFORMED_EMPTY,
                                _attempt_retries_used,
                            )
                        ):
                            _attempt_retries_used[_ProviderAttemptKind.MALFORMED_EMPTY] += 1
                            delay = backoff_sleep(
                                0,
                                _fallback.base_backoff_ms,
                                _fallback.max_backoff_ms,
                                _fake=True,
                            )
                            yield WarningEvent(
                                code="provider_empty_retry",
                                message="The provider returned an empty response; retrying once.",
                            )
                            await asyncio.sleep(delay)
                            _call_attempt += 1
                            continue

                        if (
                            attempt_classification.kind == _ProviderAttemptKind.STREAM_INCOMPLETE
                            and not attempt_classification.user_visible_emitted
                            and _retry_policy.can_retry_attempt(
                                _ProviderAttemptKind.STREAM_INCOMPLETE,
                                _attempt_retries_used,
                            )
                        ):
                            _attempt_retries_used[_ProviderAttemptKind.STREAM_INCOMPLETE] += 1
                            delay = backoff_sleep(
                                0,
                                _fallback.base_backoff_ms,
                                _fallback.max_backoff_ms,
                                _fake=True,
                            )
                            yield WarningEvent(
                                code="provider_empty_retry",
                                message=(
                                    "The provider stream ended before completion; retrying once."
                                ),
                            )
                            await asyncio.sleep(delay)
                            _call_attempt += 1
                            continue

                        if (
                            attempt_classification.kind == _ProviderAttemptKind.LENGTH_CAPPED
                            and _retry_policy.can_retry_attempt(
                                _ProviderAttemptKind.LENGTH_CAPPED,
                                _attempt_retries_used,
                            )
                        ):
                            _attempt_retries_used[_ProviderAttemptKind.LENGTH_CAPPED] += 1
                            visible_text = _append_length_capped_continuation(
                                turn_messages,
                                response_text=response_text,
                                tool_calls=tool_calls,
                            )
                            if visible_text:
                                final_text_parts.append(visible_text)
                            logger.warning(
                                "provider.output_truncated_continue",
                                session_key=self._session_key,
                                model=last_actual_model or self.config.model_id or "",
                                provider=type(self.provider).__name__,
                                iteration=iterations,
                                call_attempt=_call_attempt,
                                tool_calls=len(tool_calls),
                                visible_chars=len(visible_text),
                            )
                            yield WarningEvent(
                                code="provider_output_continue",
                                message=(
                                    "The provider reached its output limit; continuing "
                                    "the response automatically."
                                ),
                            )
                            _call_attempt += 1
                            continue

                        if (
                            attempt_classification.kind
                            in {
                                _ProviderAttemptKind.REASONING_ONLY,
                                _ProviderAttemptKind.MALFORMED_EMPTY,
                            }
                            and not _invalid_response_fallback_done
                            and self._switch_to_invalid_response_fallback(
                                attempt_classification.kind.value
                            )
                        ):
                            _invalid_response_fallback_done = True
                            yield WarningEvent(
                                code="provider_empty_retry",
                                message=(
                                    "The provider returned no visible response; "
                                    "retrying on a fallback provider."
                                ),
                            )
                            _call_attempt += 1
                            continue

                        yield self._transition(AgentState.ERROR)
                        if attempt_classification.kind == _ProviderAttemptKind.INCOMPLETE_TOOLS:
                            terminal_error = ErrorEvent(
                                message="Provider stream ended with an incomplete tool call",
                                code="incomplete_tool_stream",
                            )
                            yield terminal_error
                            break
                        if attempt_classification.kind == _ProviderAttemptKind.STREAM_INCOMPLETE:
                            terminal_error = ErrorEvent(
                                message="Provider stream ended before a done event",
                                code="provider_stream_incomplete",
                            )
                            yield terminal_error
                            break
                        if attempt_classification.kind == _ProviderAttemptKind.LENGTH_CAPPED:
                            visible_text = strip_synthetic_tool_call_suffix(
                                response_text,
                                [tc.tool_name for tc in tool_calls if tc.synthetic_from_text],
                            )
                            logger.warning(
                                "provider.output_truncated_exhausted",
                                session_key=self._session_key,
                                model=last_actual_model or self.config.model_id or "",
                                provider=type(self.provider).__name__,
                                iteration=iterations,
                                call_attempt=_call_attempt,
                                attempt=_attempt_retries_used.get(
                                    _ProviderAttemptKind.LENGTH_CAPPED, 0
                                ),
                                budget=_retry_policy.attempt_budgets.get(
                                    _ProviderAttemptKind.LENGTH_CAPPED, 0
                                ),
                                tool_calls=len(tool_calls),
                                visible_chars=len(visible_text),
                                partial_preserved=bool(visible_text or final_text_parts),
                            )
                            yield WarningEvent(
                                code="provider_output_truncated",
                                message=(
                                    "The provider stopped because the output limit was reached."
                                ),
                            )
                            terminal_error = ErrorEvent(
                                message=_PROVIDER_OUTPUT_TRUNCATED_REPLY,
                                code="provider_output_truncated",
                            )
                            yield terminal_error
                            break
                        logger.warning(
                            "provider.empty_response",
                            session_key=self._session_key,
                            model=last_actual_model or self.config.model_id or "",
                            provider=type(self.provider).__name__,
                            iteration=iterations,
                            retry_attempt=_call_attempt,
                            post_tool_turn=post_tool_turn,
                            got_done_event=_got_done_event,
                            stop_reason=stop_reason,
                            iter_input_tokens=iter_input_tokens,
                            iter_output_tokens=iter_output_tokens,
                            iter_reasoning_tokens=iter_reasoning_tokens,
                            reasoning_chars=len(iter_reasoning_content or ""),
                        )
                        terminal_error = ErrorEvent(
                            message="Provider returned an empty response",
                            code="empty_response",
                        )
                        yield terminal_error
                        break

                    if (
                        not _got_error
                        and attempt_classification.kind == _ProviderAttemptKind.OK
                        and (stop_reason or "").lower() == "length"
                    ):
                        yield WarningEvent(
                            code="provider_output_truncated",
                            message="The provider stopped because the output limit was reached.",
                        )

                    if (
                        not _got_error
                        and self._session_key
                        and cache_prompt_snapshot is not None
                        and provider_done_for_log is not None
                    ):
                        cache_report = check_response_for_cache_break(
                            self._session_key,
                            cache_prompt_snapshot,
                            provider_done_for_log.cached_tokens,
                        )
                        if cache_report.break_detected:
                            logger.warning(
                                "prompt_cache.break_detected",
                                session_key=self._session_key,
                                **cache_report.to_log_dict(),
                            )

                    if not _got_error:
                        break  # stream OK, exit retry loop

                    if provider_error is None:
                        _call_attempt += 1
                        continue

                    if provider_error is not None:
                        provider_error_status_code = (
                            int(provider_error.code)
                            if str(provider_error.code).isdigit()
                            else None
                        )
                        failure_kind = classify_provider_error(
                            provider_name=getattr(self.provider, "provider_name", ""),
                            status_code=provider_error_status_code,
                            raw_code=provider_error.code,
                            message=provider_error.message,
                        )
                        kind = _fallback.classify_error(
                            provider_error.message,
                            provider_name=getattr(self.provider, "provider_name", ""),
                            status_code=provider_error_status_code,
                            raw_code=provider_error.code,
                        )
                        if artifact_delivery_final_response_pending:
                            yield _finish_artifact_delivery_degraded(
                                reason=provider_error.message,
                                code=provider_error.code,
                            )
                            break
                        if max_iterations_finalization_pending:
                            response_text = (
                                "I reached the configured iteration limit, and the "
                                "provider could not generate an additional wrap-up. "
                                "Returning the best partial result from completed work."
                            )
                            assistant_text_parts.append(response_text)
                            provider_done_for_log = ProviderDoneEvent(stop_reason="stop")
                            _got_done_event = True
                            _got_error = False
                            max_iterations_finalization_pending = False
                            self._write_turn_call_log(
                                "turn_policy_decision",
                                action="partial_after_finalization_provider_error",
                                reason="max_iterations",
                                code="max_iterations",
                                provider_error_code=provider_error.code,
                            )
                            yield TextDeltaEvent(text=response_text)
                            break
                        if (
                            failure_kind == ProviderFailureKind.EMPTY_RESPONSE
                            and _retry_policy.can_retry_provider_failure(
                                failure_kind,
                                post_tool_turn=post_tool_turn,
                                provider_retry_attempt=_retry_attempt,
                            )
                        ):
                            delay = backoff_sleep(
                                _retry_attempt,
                                _fallback.base_backoff_ms,
                                _fallback.max_backoff_ms,
                                _fake=True,
                            )
                            _log.warning(
                                "provider.empty_response_retry",
                                attempt=_retry_attempt + 1,
                                delay_s=round(delay, 2),
                                post_tool_turn=True,
                            )
                            yield WarningEvent(
                                code="provider_empty_retry",
                                message=(
                                    "The provider returned an empty response after tool "
                                    "execution; retrying once."
                                ),
                            )
                            await asyncio.sleep(delay)
                            _retry_attempt += 1
                            _call_attempt += 1
                            continue
                        if failure_kind == ProviderFailureKind.CONTEXT_OVERFLOW:
                            self._record_provider_context_overflow_reason(provider_error)
                            provider_compaction_window_tokens = (
                                self._provider_budget_compaction_window_tokens(provider_error)
                            )
                            provider_estimated_tokens = self._provider_budget_estimated_tokens(
                                provider_error
                            )
                            provider_compaction_refusal_reason = (
                                self._last_compaction_refusal_reason
                            )
                            overflow_total_tokens = provider_estimated_tokens
                            if overflow_total_tokens is None:
                                overflow_total_tokens = (
                                    provider_compaction_window_tokens
                                    or self.config.context_window_tokens
                                ) + 1
                            if overflow_retries >= self.config.max_overflow_retries:
                                yield self._transition(AgentState.ERROR)
                                terminal_error = self._context_overflow_error()
                                yield terminal_error
                                break
                            overflow_retries += 1
                            yield WarningEvent(
                                code="context_auto_compaction_start",
                                message=(
                                    "Provider context limit reached; compacting older "
                                    "context before retrying."
                                ),
                            )
                            overflow_outcome = await self._check_context_overflow(
                                turn_messages,
                                overflow_total_tokens,
                                request_context_insert_index=request_context_insert_index,
                                runtime_context_insert_index=runtime_context_insert_index,
                                compaction_window_tokens=provider_compaction_window_tokens,
                            )
                            if overflow_outcome is None:
                                yield self._transition(AgentState.ERROR)
                                terminal_error = self._context_overflow_error()
                                yield terminal_error
                                break
                            if (
                                provider_compaction_refusal_reason
                                and self._last_compaction_refusal_reason is None
                            ):
                                self._last_compaction_refusal_reason = (
                                    provider_compaction_refusal_reason
                                )
                            next_request_context_insert_index = (
                                overflow_outcome.request_context_insert_index
                                if overflow_outcome.request_context_insert_index is not None
                                else request_context_insert_index
                            )
                            next_runtime_context_insert_index = (
                                overflow_outcome.runtime_context_insert_index
                                if overflow_outcome.runtime_context_insert_index is not None
                                else runtime_context_insert_index
                            )
                            next_request_messages = self._provider_request_messages(
                                overflow_outcome.messages,
                                request_context_message=request_context_message,
                                request_context_insert_index=next_request_context_insert_index,
                                runtime_context_message=runtime_context_message,
                                runtime_context_insert_index=next_runtime_context_insert_index,
                            )
                            if not self._provider_request_is_smaller(
                                request_messages,
                                next_request_messages,
                            ):
                                yield self._transition(AgentState.ERROR)
                                if (
                                    self._last_compaction_refusal_reason
                                    != "provider_recent_tail_too_large"
                                ):
                                    self._last_compaction_refusal_reason = "compaction_not_smaller"
                                terminal_error = self._context_overflow_error()
                                yield terminal_error
                                break
                            turn_messages = overflow_outcome.messages
                            request_context_insert_index = next_request_context_insert_index
                            runtime_context_insert_index = next_runtime_context_insert_index
                            yield WarningEvent(
                                code="context_auto_compaction_retry",
                                message="Context compacted; retrying the provider request.",
                            )
                            yield CompactionEvent(
                                compaction_id=overflow_outcome.compaction_id,
                                summary=overflow_outcome.summary,
                                kept_entries=overflow_outcome.kept_entries,
                                kept_count=len(overflow_outcome.messages),
                                removed_count=overflow_outcome.removed_count,
                            )
                            _call_attempt += 1
                            continue
                        if not _fallback.should_retry(kind, _retry_attempt):
                            yield self._transition(AgentState.ERROR)
                            terminal_error = ErrorEvent(
                                message=provider_error.message,
                                code=provider_error.code,
                            )
                            yield terminal_error
                            break
                        delay = backoff_sleep(
                            _retry_attempt,
                            _fallback.base_backoff_ms,
                            _fallback.max_backoff_ms,
                            _fake=True,
                        )
                        _log.warning(
                            "provider.retry",
                            attempt=_retry_attempt + 1,
                            kind=kind.value,
                            delay_s=round(delay, 2),
                        )
                        await asyncio.sleep(delay)
                        _retry_attempt += 1
                        _call_attempt += 1

                if terminal_error is not None:
                    break
                if artifact_delivery_degraded_final_response:
                    break

                response_text = "".join(assistant_text_parts)
                final_stop_reason = (
                    getattr(provider_done_for_log, "stop_reason", None)
                    if provider_done_for_log is not None
                    else None
                )
                final_classification = _classify_provider_attempt(
                    text=response_text,
                    tool_calls=tool_calls,
                    pending_tools=pending_tools,
                    got_done_event=_got_done_event,
                    stop_reason=final_stop_reason,
                    reasoning_content=iter_reasoning_content,
                    reasoning_tokens=iter_reasoning_tokens,
                    user_visible_emitted=attempt_user_visible_emitted,
                )
                if final_classification.kind != _ProviderAttemptKind.OK:
                    logger.warning(
                        "provider.invalid_response_unhandled",
                        session_key=self._session_key,
                        model=last_actual_model or self.config.model_id or "",
                        provider=type(self.provider).__name__,
                        classification=final_classification.kind.value,
                        iteration=iterations,
                        call_attempt=_call_attempt,
                        got_done_event=_got_done_event,
                        stop_reason=final_stop_reason,
                        iter_input_tokens=iter_input_tokens,
                        iter_output_tokens=iter_output_tokens,
                        iter_reasoning_tokens=iter_reasoning_tokens,
                        reasoning_chars=len(iter_reasoning_content or ""),
                    )
                    yield self._transition(AgentState.ERROR)
                    if final_classification.kind == _ProviderAttemptKind.INCOMPLETE_TOOLS:
                        terminal_error = ErrorEvent(
                            message="Provider stream ended with an incomplete tool call",
                            code="incomplete_tool_stream",
                        )
                        yield terminal_error
                        break
                    if final_classification.kind == _ProviderAttemptKind.STREAM_INCOMPLETE:
                        terminal_error = ErrorEvent(
                            message="Provider stream ended before a done event",
                            code="provider_stream_incomplete",
                        )
                        yield terminal_error
                        break
                    if final_classification.kind == _ProviderAttemptKind.LENGTH_CAPPED:
                        terminal_error = ErrorEvent(
                            message=_PROVIDER_OUTPUT_TRUNCATED_REPLY,
                            code="provider_output_truncated",
                        )
                        yield terminal_error
                        break
                    terminal_error = ErrorEvent(
                        message="Provider returned an empty response",
                        code="empty_response",
                    )
                    yield terminal_error
                    break

                if iter_reasoning_content:
                    final_reasoning_parts.append(iter_reasoning_content)

                # Check overflow against the live provider request, not
                # cumulative billable usage for the whole turn.
                estimated_context_tokens = self._estimate_live_request_tokens(
                    request_messages,
                    tools=provider_tools_for_call,
                    config=call_chat_cfg,
                )
                overflow_outcome = await self._check_context_overflow(
                    turn_messages,
                    estimated_context_tokens,
                    request_context_insert_index=request_context_insert_index,
                    runtime_context_insert_index=runtime_context_insert_index,
                )
                if overflow_outcome is None:
                    if overflow_retries >= self.config.max_overflow_retries:
                        yield self._transition(AgentState.ERROR)
                        terminal_error = self._context_overflow_error()
                        yield terminal_error
                        break
                    overflow_retries += 1
                    _log.warning(
                        "compaction.retry",
                        attempt=overflow_retries,
                        max=self.config.max_overflow_retries,
                    )
                    continue  # retry the tool loop iteration
                if overflow_outcome.compacted:
                    # Compaction happened — replace message list. Lifetime
                    # counters keep feeding DoneEvent usage/cost accounting for
                    # this turn.
                    turn_messages = overflow_outcome.messages
                    if overflow_outcome.request_context_insert_index is not None:
                        request_context_insert_index = overflow_outcome.request_context_insert_index
                    if overflow_outcome.runtime_context_insert_index is not None:
                        runtime_context_insert_index = overflow_outcome.runtime_context_insert_index
                    yield CompactionEvent(
                        compaction_id=overflow_outcome.compaction_id,
                        summary=overflow_outcome.summary,
                        kept_entries=overflow_outcome.kept_entries,
                        kept_count=len(overflow_outcome.messages),
                        removed_count=overflow_outcome.removed_count,
                    )
                    overflow_retries = 0  # reset on success
                    # Rebuild chat_cfg so next LLM call uses refreshed system
                    # prompt. Read cache_breakpoints from the
                    # refreshed self.config (re-anchored by
                    # refresh_system_prompt) — chat_cfg.cache_breakpoints
                    # would still hold pre-compaction base text and miss the
                    # cache on the next provider call.
                    chat_cfg = ChatConfig(
                        max_tokens=chat_cfg.max_tokens,
                        temperature=chat_cfg.temperature,
                        system=self._context.system_prompt,
                        thinking=thinking_enabled,
                        thinking_budget_tokens=thinking_budget,
                        timeout=chat_cfg.timeout,
                        stop_sequences=chat_cfg.stop_sequences,
                        cache_breakpoints=self._cache_breakpoints_without_runtime_context(
                            self.config.cache_breakpoints
                        ),
                        cache_mode=chat_cfg.cache_mode,
                        model_capabilities=self.config.model_capabilities,
                        thinking_level=(
                            self.config.thinking
                            if isinstance(self.config.thinking, ThinkingLevel)
                            else None
                        ),
                        provider_request_max_chars=(self._provider_request_proof_max_chars()),
                        tool_choice=chat_cfg.tool_choice,
                    )

                assembled_text = "".join(assistant_text_parts)
                visible_text = strip_synthetic_tool_call_suffix(
                    assembled_text,
                    [tc.tool_name for tc in tool_calls if tc.synthetic_from_text],
                )
                if visible_text:
                    final_text_parts.append(visible_text)

                preflight_tool_results: dict[str, ToolResult] = {}
                terminal_projection_preflight_error = False
                resolved_tool_calls: list[ToolCall] = []
                for tc in tool_calls:
                    resolved = self._rehydrate_projected_tool_arguments(tc)
                    if isinstance(resolved, ToolResult):
                        preflight_tool_results[tc.tool_use_id] = resolved
                        if self._is_provider_context_projection_reuse_result(resolved):
                            terminal_projection_preflight_error = True
                        resolved_tool_calls.append(self._sanitize_projected_tool_call_arguments(tc))
                        continue
                    resolved_tool_calls.append(resolved)
                tool_calls = resolved_tool_calls

                # Build assistant message for history
                assistant_content: list[Any] = []
                if iter_reasoning_content and iter_thinking_signature:
                    assistant_content.append(
                        ContentBlockThinking(
                            thinking=iter_reasoning_content,
                            signature=iter_thinking_signature,
                        )
                    )
                if visible_text:
                    assistant_content.append(ContentBlockText(text=visible_text))
                for tc in tool_calls:
                    assistant_content.append(
                        ContentBlockToolUse(
                            id=tc.tool_use_id,
                            name=tc.tool_name,
                            input=tc.arguments,
                        )
                    )
                if assistant_content:
                    turn_messages.append(
                        Message(
                            role="assistant",
                            content=assistant_content,
                            reasoning_content=iter_reasoning_content,
                        )
                    )

                # Detect incomplete tool calls (stream interrupted mid-generation)
                if pending_tools and not tool_calls:
                    _log.warning(
                        "agent.stream_interrupted",
                        session_key=self._session_key,
                        pending_tool_ids=list(pending_tools.keys()),
                        pending_tool_names=[acc.tool_name for acc in pending_tools.values()],
                        got_done_event=_got_done_event,
                        text_len=len(assembled_text),
                        iteration=iterations,
                    )
                if not _got_done_event and (assembled_text or pending_tools):
                    _log.warning(
                        "agent.provider_stream_incomplete",
                        session_key=self._session_key,
                        got_text=bool(assembled_text),
                        pending_tools=len(pending_tools),
                        tool_calls=len(tool_calls),
                    )

                # No tool calls → we're done
                if not tool_calls:
                    max_iterations_finalization_pending = False
                    break
                tool_calls = [self._coerce_meta_tool_call(tc) for tc in tool_calls]
                tool_calls = self._force_matched_meta_invoke_tool_calls(tool_calls)

                tool_deadline = _loop.time() + self.config.iteration_timeout

                # ------ STREAMING → TOOL_CALLING ------
                yield self._transition(AgentState.TOOL_CALLING)

                # Execute tools and collect results. Concurrent/keyed tools run
                # in bounded batches; mutex tools run serially. Results are
                # emitted in the original tool_calls arrival order regardless
                # of completion order.
                from opensquilla.engine.runtime import (  # noqa: PLC0415
                    _get_tool_concurrency_policy,
                )

                tool_result_blocks: list[ContentBlockToolResult] = []
                executed_results: list[ToolResult] = []
                turn_yielded = False

                # Map tool_use_id -> ToolResult built up below.
                results_by_id: dict[str, ToolResult] = {}

                def _cap_timeout_by_deadlines(timeout: float) -> float:
                    remaining = min(timeout, max(0.0, tool_deadline - _loop.time()))
                    if _total_deadline is not None:
                        remaining = min(remaining, max(0.0, _total_deadline - _loop.time()))
                    return max(0.001, remaining)

                async def _run_one(tc: ToolCall) -> ToolResult:
                    started = time.monotonic()
                    self._write_turn_call_log(
                        "tool_request",
                        iteration=iterations,
                        tool_use_id=tc.tool_use_id,
                        name=tc.tool_name,
                        arguments=tc.arguments,
                    )
                    tool_timeout = _cap_timeout_by_deadlines(self._tool_execution_timeout(tc))
                    preflight_result = preflight_tool_results.get(tc.tool_use_id)
                    if preflight_result is not None:
                        res = preflight_result
                    else:
                        try:
                            res = await asyncio.wait_for(
                                self._execute_tool(tc), timeout=tool_timeout
                            )
                        except TimeoutError:
                            res = ToolResult(
                                tool_use_id=tc.tool_use_id,
                                tool_name=tc.tool_name,
                                content=(f"Tool '{tc.tool_name}' timed out after {tool_timeout}s"),
                                is_error=True,
                                execution_status=runtime_execution_status(
                                    "timeout",
                                    reason="runtime_timeout",
                                    timed_out=True,
                                ),
                            )
                    self._write_turn_call_log(
                        "tool_response",
                        iteration=iterations,
                        tool_use_id=res.tool_use_id,
                        name=res.tool_name,
                        result=res.content,
                        result_chars=len(res.content),
                        is_error=res.is_error,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
                    return res

                async def _collect_tool_tasks(
                    task_to_tool_call: dict[asyncio.Task[ToolResult], ToolCall],
                ) -> AsyncIterator[RunHeartbeatEvent]:
                    pending = set(task_to_tool_call)
                    if not pending:
                        return

                    interval = self._tool_activity_heartbeat_interval()
                    started = time.monotonic()
                    last_event_at = started
                    try:
                        while pending:
                            remaining = max(0.0, tool_deadline - _loop.time())
                            if _total_deadline is not None:
                                remaining = min(
                                    remaining,
                                    max(0.0, _total_deadline - _loop.time()),
                                )
                            if remaining <= 0:
                                for task, tc in list(task_to_tool_call.items()):
                                    if task in pending:
                                        task.cancel()
                                        results_by_id[tc.tool_use_id] = ToolResult(
                                            tool_use_id=tc.tool_use_id,
                                            tool_name=tc.tool_name,
                                            content=(
                                                f"Tool '{tc.tool_name}' timed out after "
                                                f"{self.config.iteration_timeout}s"
                                            ),
                                            is_error=True,
                                            execution_status=runtime_execution_status(
                                                "timeout",
                                                reason="runtime_timeout",
                                                timed_out=True,
                                            ),
                                        )
                                return
                            wait_timeout = remaining if interval <= 0 else min(interval, remaining)
                            done, pending = await asyncio.wait(
                                pending,
                                timeout=max(0.001, wait_timeout),
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if not done:
                                if _loop.time() >= tool_deadline or (
                                    _total_deadline is not None and _loop.time() >= _total_deadline
                                ):
                                    for task, tc in list(task_to_tool_call.items()):
                                        if task in pending:
                                            task.cancel()
                                            results_by_id[tc.tool_use_id] = ToolResult(
                                                tool_use_id=tc.tool_use_id,
                                                tool_name=tc.tool_name,
                                                content=(
                                                    f"Tool '{tc.tool_name}' timed out after "
                                                    f"{self.config.iteration_timeout}s"
                                                ),
                                                is_error=True,
                                                execution_status=runtime_execution_status(
                                                    "timeout",
                                                    reason="runtime_timeout",
                                                    timed_out=True,
                                                ),
                                            )
                                    return
                                now = time.monotonic()
                                yield RunHeartbeatEvent(
                                    phase="tool",
                                    elapsed_ms=int((now - started) * 1000),
                                    idle_ms=int((now - last_event_at) * 1000),
                                    message="Tool still running",
                                )
                                continue

                            last_event_at = time.monotonic()
                            for task in done:
                                tc = task_to_tool_call[task]
                                try:
                                    outcome = task.result()
                                except asyncio.CancelledError:
                                    outcome = ToolResult(
                                        tool_use_id=tc.tool_use_id,
                                        tool_name=tc.tool_name,
                                        content=f"Tool '{tc.tool_name}' was cancelled",
                                        is_error=True,
                                        execution_status=runtime_execution_status(
                                            "cancelled",
                                            reason="cancelled",
                                        ),
                                    )
                                except Exception as exc:  # noqa: BLE001
                                    outcome = ToolResult(
                                        tool_use_id=tc.tool_use_id,
                                        tool_name=tc.tool_name,
                                        content=f"Tool '{tc.tool_name}' raised: {exc}",
                                        is_error=True,
                                        execution_status=runtime_execution_status(
                                            "error",
                                            reason="runtime_error",
                                        ),
                                    )
                                results_by_id[tc.tool_use_id] = outcome
                    finally:
                        for task in pending:
                            if not task.done():
                                task.cancel()
                        for task in pending:
                            with contextlib.suppress(asyncio.CancelledError):
                                await task

                # Dispatch preserving original order: accumulate consecutive
                # concurrent/keyed tools into a batch and flush before each
                # mutex tool, then run the mutex tool serially. This ensures
                # that a parallel tool appearing after a mutex tool cannot start
                # until that mutex tool has completed.
                parallel_batch: list[ToolCall] = []

                async def _flush_parallel_batch(
                    batch: list[ToolCall],
                ) -> AsyncIterator[RunHeartbeatEvent]:
                    if not batch:
                        return
                    semaphore = asyncio.Semaphore(self._max_safe_tool_concurrency())
                    keyed_locks: dict[Any, asyncio.Lock] = {}
                    limiters: dict[Any, asyncio.Semaphore] = {}

                    async def _run_limited(tc: ToolCall) -> ToolResult:
                        policy = _get_tool_concurrency_policy(
                            tc.tool_name,
                            tc.arguments,
                            parent_session_key=self._session_key,
                        )
                        key_lock = (
                            keyed_locks.setdefault(policy.key, asyncio.Lock())
                            if policy.key is not None
                            else None
                        )
                        limiter = None
                        if policy.max_inflight is not None:
                            limit_key = policy.limit_key or tc.tool_name
                            limiter = limiters.setdefault(
                                limit_key,
                                asyncio.Semaphore(max(1, int(policy.max_inflight))),
                            )

                        async def _run_after_policy_locks() -> ToolResult:
                            async with semaphore:
                                return await _run_one(tc)

                        async def _run_after_key_lock() -> ToolResult:
                            if limiter is None:
                                return await _run_after_policy_locks()
                            async with limiter:
                                return await _run_after_policy_locks()

                        if key_lock is None:
                            return await _run_after_key_lock()
                        async with key_lock:
                            return await _run_after_key_lock()

                    task_to_tool_call = {asyncio.create_task(_run_limited(tc)): tc for tc in batch}
                    async for event in _collect_tool_tasks(task_to_tool_call):
                        yield event

                for tc in tool_calls:
                    if tc.tool_name == "meta_invoke":
                        async for event in _flush_parallel_batch(parallel_batch):
                            yield event
                        parallel_batch = []
                        active_ctx = (
                            current_tool_context.get()
                            or self._tool_context
                            or ToolContext()
                        )
                        async for ev in self._run_one_streaming(tc, active_ctx):
                            if isinstance(ev, ToolResult):
                                results_by_id[tc.tool_use_id] = ev
                            else:
                                yield ev
                        continue
                    policy = _get_tool_concurrency_policy(
                        tc.tool_name,
                        tc.arguments,
                        parent_session_key=self._session_key,
                    )
                    if policy.mode != "mutex":
                        parallel_batch.append(tc)
                    else:
                        async for event in _flush_parallel_batch(parallel_batch):
                            yield event
                        parallel_batch = []
                        async for event in _collect_tool_tasks(
                            {asyncio.create_task(_run_one(tc)): tc}
                        ):
                            yield event

                async for event in _flush_parallel_batch(parallel_batch):
                    yield event

                # Emit results in original tool_calls order.
                for tc in tool_calls:
                    result = results_by_id[tc.tool_use_id]
                    result_tool_call = tc
                    for artifact in result.artifacts:
                        yield ArtifactEvent(**_artifact_event_kwargs(artifact))
                    projected_result = await self._project_tool_result_for_delivery(
                        result,
                        tool_call=result_tool_call,
                    )
                    yield ToolResultEvent(
                        tool_use_id=projected_result.tool_use_id,
                        tool_name=projected_result.tool_name,
                        result=projected_result.content,
                        is_error=projected_result.is_error,
                        arguments=tc.arguments,
                        execution_status=projected_result.execution_status,
                    )
                    replay_event = router_control_replay_event_from_payload(result.content)
                    if replay_event is not None:
                        yield replay_event
                    pending_approval = _pending_approval_payload(result.content)
                    if pending_approval is not None and not tc.arguments.get("approval_id"):
                        await _wait_for_pending_approval_resolution(
                            pending_approval,
                            timeout=_cap_timeout_by_deadlines(self._approval_wait_timeout()),
                        )
                        retry_arguments = dict(tc.arguments)
                        retry_arguments["approval_id"] = pending_approval["approval_id"]
                        retry_call = ToolCall(
                            tool_use_id=tc.tool_use_id,
                            tool_name=tc.tool_name,
                            arguments=retry_arguments,
                            synthetic_from_text=tc.synthetic_from_text,
                            origin_trace=tc.origin_trace,
                        )
                        result = await _run_one(retry_call)
                        result_tool_call = retry_call
                        for artifact in result.artifacts:
                            yield ArtifactEvent(**_artifact_event_kwargs(artifact))
                        projected_result = await self._project_tool_result_for_delivery(
                            result,
                            tool_call=result_tool_call,
                        )
                        yield ToolResultEvent(
                            tool_use_id=projected_result.tool_use_id,
                            tool_name=projected_result.tool_name,
                            result=projected_result.content,
                            is_error=projected_result.is_error,
                            arguments=retry_arguments,
                            execution_status=projected_result.execution_status,
                        )
                        replay_event = router_control_replay_event_from_payload(result.content)
                        if replay_event is not None:
                            yield replay_event
                    executed_results.append(result)
                    while self._pending_warnings:
                        yield self._pending_warnings.pop(0)
                    if self._is_turn_yield_result(result) or result.terminates_turn:
                        turn_yielded = True
                    tool_result_blocks.append(
                        ContentBlockToolResult(
                            tool_use_id=projected_result.tool_use_id,
                            content=projected_result.content,
                            is_error=projected_result.is_error,
                            execution_status=projected_result.execution_status,
                        )
                    )

                terminal_artifacts = self._terminal_artifact_delivery_artifacts(executed_results)
                if terminal_artifacts:
                    artifact_delivery_final_response_artifacts = terminal_artifacts

                turn_tool_errors += sum(1 for result in executed_results if result.is_error)
                first_tool_error = next(
                    (result for result in executed_results if result.is_error),
                    None,
                )
                watchdog_decision = progress_watchdog.observe(
                    ProgressObservation(
                        iteration=iterations,
                        provider_call_count=turn_llm_calls,
                        successful_tool_result=any(
                            not result.is_error for result in executed_results
                        ),
                        user_visible_output=bool("".join(final_text_parts).strip()),
                        artifact_completed=bool(terminal_artifacts),
                        tool_error_signature=(
                            None
                            if first_tool_error is None
                            else (
                                f"{first_tool_error.tool_name}:"
                                f"{str(first_tool_error.content)[:160]}"
                            )
                        ),
                    )
                )
                if watchdog_decision.action != "observe":
                    self._write_turn_call_log(
                        "progress_watchdog",
                        action=watchdog_decision.action,
                        reason=watchdog_decision.reason,
                        details=watchdog_decision.details,
                    )
                terminal_error = _turn_budget_error()
                if terminal_error is not None:
                    if artifact_delivery_final_response_pending:
                        yield _finish_artifact_delivery_degraded(
                            reason=terminal_error.message,
                            code=terminal_error.code,
                        )
                        terminal_error = None
                    else:
                        yield self._transition(AgentState.ERROR)
                        yield terminal_error
                    break

                if any(_is_threshold_denial(result) for result in executed_results):
                    yield self._transition(AgentState.ERROR)
                    terminal_error = ErrorEvent(
                        message=(
                            "Autonomous execution paused after repeated sandbox denials. "
                            "Human intervention is required before continuing."
                        ),
                        code="sandbox_threshold_exceeded",
                    )
                    yield terminal_error
                    break

                # Per-iteration deadline check after tool execution
                if _loop.time() > tool_deadline:
                    yield self._transition(AgentState.ERROR)
                    terminal_error = ErrorEvent(
                        message=(
                            f"Iteration {iterations} exceeded iteration_timeout"
                            f" ({self.config.iteration_timeout}s) during tool execution"
                        ),
                        code="iteration_timeout",
                    )
                    yield terminal_error
                    break

                # Feed tool results back as user message
                turn_messages.append(
                    Message(role="user", content=tool_result_blocks)  # type: ignore[arg-type]
                )
                if terminal_projection_preflight_error:
                    self._write_turn_call_log(
                        "tool_argument_projection_rehydrate_recovery",
                        iteration=iterations,
                        tool_use_ids=sorted(preflight_tool_results),
                    )
                if terminal_artifacts:
                    _finish_artifact_delivery_without_provider()
                    break
                if turn_yielded:
                    break

                # ------ TOOL_CALLING → THINKING ------
                yield self._transition(AgentState.THINKING)
                # Loop continues

        except TimeoutError:
            if artifact_delivery_final_response_pending:
                yield _finish_artifact_delivery_degraded(
                    reason=f"Agent turn timed out after {self.config.timeout}s",
                    code="agent_runtime_timeout",
                )
            else:
                # Total turn deadline exceeded (raised by manual check above)
                yield self._transition(AgentState.ERROR)
                terminal_error = ErrorEvent(
                    message=f"Agent turn timed out after {self.config.timeout}s",
                    code="agent_runtime_timeout",
                )
                yield terminal_error

        if terminal_error is None:
            # Persist successful turns into in-memory history. Error turns are
            # persisted by TurnRunner as system errors, while their usage still
            # flows through the final DoneEvent below when provider usage exists.
            self._history = list(turn_messages)
            self._write_context_stage("session:after", self._history)

        # ------ → DONE ------
        # Compute per-turn cost from pricing table
        done_model = last_actual_model
        if not done_model and self._usage_tracker and self._session_key:
            su = self._usage_tracker.get(self._session_key)
            if su and su.model_id:
                done_model = su.model_id
        if not done_model:
            done_model = self.config.model_id or ""
        from opensquilla.engine.pricing import lookup_price

        price = lookup_price(done_model)
        estimated_cost = (
            total_input_tokens * price.input_per_m + total_output_tokens * price.output_per_m
        ) / 1_000_000
        if total_billed_cost > 0.0:
            done_cost = total_billed_cost
            cost_source = "provider_billed"
        elif estimated_cost > 0.0:
            done_cost = estimated_cost
            cost_source = "opensquilla_static_estimate"
        else:
            done_cost = 0.0
            cost_source = "unavailable"

        session_totals = (
            self._usage_tracker.session_snapshot(self._session_key)
            if self._usage_tracker and self._session_key
            else None
        )
        turn_usage_delta = (
            self._usage_tracker.session_delta_snapshot(self._session_key, usage_turn_baseline)
            if self._usage_tracker and self._session_key
            else None
        )
        done_input_tokens = total_input_tokens
        done_output_tokens = total_output_tokens
        done_cached_tokens = total_cached_tokens
        done_cache_write_tokens = total_cache_write_tokens
        done_billed_cost = total_billed_cost
        if turn_usage_delta and (
            turn_usage_delta.input_tokens
            or turn_usage_delta.output_tokens
            or turn_usage_delta.cache_read_tokens
            or turn_usage_delta.cache_write_tokens
            or turn_usage_delta.cost_usd
            or turn_usage_delta.billed_cost
        ):
            done_input_tokens = turn_usage_delta.input_tokens
            done_output_tokens = turn_usage_delta.output_tokens
            done_cached_tokens = turn_usage_delta.cache_read_tokens
            done_cache_write_tokens = turn_usage_delta.cache_write_tokens
            done_cost = turn_usage_delta.cost_usd
            done_billed_cost = turn_usage_delta.billed_cost
            cost_source = _cost_source_for_usage(done_cost, done_billed_cost)

        has_usage = bool(
            done_input_tokens
            or done_output_tokens
            or total_reasoning_tokens
            or done_cached_tokens
            or done_cache_write_tokens
            or done_billed_cost
        )
        if terminal_error is None or has_usage:
            if terminal_error is None:
                yield self._transition(AgentState.DONE)
            yield DoneEvent(
                text="".join(final_text_parts),
                input_tokens=done_input_tokens,
                output_tokens=done_output_tokens,
                reasoning_tokens=total_reasoning_tokens,
                cached_tokens=done_cached_tokens,
                cache_write_tokens=done_cache_write_tokens,
                iterations=iterations,
                cost_usd=done_cost,
                billed_cost=done_billed_cost,
                cost_source=cost_source,
                model=done_model,
                runtime_context_hash=runtime_context_hash,
                runtime_context_chars=len(runtime_context),
                reasoning_content=(
                    "\n".join(final_reasoning_parts) if final_reasoning_parts else None
                ),
                session_totals=session_totals,
            )
        # Reset for next turn
        self._state = AgentState.IDLE

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _stream_provider_events_with_deadline(
        self,
        stream: AsyncIterator[Any],
        *,
        loop: asyncio.AbstractEventLoop,
        total_deadline: float | None,
    ) -> AsyncIterator[Any]:
        stream_iter = stream.__aiter__()
        while True:
            wait_budget = max(0.001, self.config.iteration_timeout)
            if total_deadline is not None:
                remaining_total = total_deadline - loop.time()
                if remaining_total <= 0:
                    await self._close_provider_stream(stream_iter)
                    raise TimeoutError(f"Agent total timeout after {self.config.timeout}s")
                wait_budget = min(wait_budget, remaining_total)

            next_event: asyncio.Future[Any] = asyncio.ensure_future(stream_iter.__anext__())
            done, _ = await asyncio.wait({next_event}, timeout=wait_budget)
            if not done:
                next_event.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                    await next_event
                if total_deadline is not None and loop.time() >= total_deadline:
                    raise TimeoutError(f"Agent total timeout after {self.config.timeout}s")
                raise _IterationStreamTimeoutError
            try:
                yield next_event.result()
            except StopAsyncIteration:
                return

    @staticmethod
    async def _close_provider_stream(stream_iter: AsyncIterator[Any]) -> None:
        aclose = getattr(stream_iter, "aclose", None)
        if not callable(aclose):
            return
        try:
            await aclose()
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask timeout
            logger.debug("provider_stream.close_failed", error=str(exc))

    def _provider_request_messages(
        self,
        messages: list[Message],
        *,
        request_context_message: Message | None,
        request_context_insert_index: int,
        runtime_context_message: Message,
        runtime_context_insert_index: int,
    ) -> list[Message]:
        request_messages, _ = self._provider_request_messages_with_sanitize(
            messages,
            request_context_message=request_context_message,
            request_context_insert_index=request_context_insert_index,
            runtime_context_message=runtime_context_message,
            runtime_context_insert_index=runtime_context_insert_index,
        )
        return request_messages

    def _provider_request_messages_with_sanitize(
        self,
        messages: list[Message],
        *,
        request_context_message: Message | None,
        request_context_insert_index: int,
        runtime_context_message: Message,
        runtime_context_insert_index: int,
    ) -> tuple[list[Message], SessionSanitizeResult]:
        source_messages = self._with_request_context_messages(
            messages,
            request_context_message,
            request_context_insert_index,
            runtime_context_message,
            runtime_context_insert_index,
        )
        source_messages = self._apply_provider_tool_result_overrides(source_messages)
        source_messages = self._strip_provider_context_marker_replay_for_provider(source_messages)
        source_messages = self._compact_aggregate_tool_results_for_provider(source_messages)
        source_messages = self._sanitize_projected_tool_use_arguments_for_provider(source_messages)
        source_messages = repair_tool_pairing(source_messages)
        return sanitize_session_messages(source_messages)

    def _apply_provider_tool_result_overrides(self, messages: list[Message]) -> list[Message]:
        if not self._provider_tool_result_overrides:
            return messages

        projected: list[Message] = []
        changed = False
        for message in messages:
            if not isinstance(message.content, list):
                projected.append(message)
                continue
            blocks: list[Any] = []
            message_changed = False
            for block in message.content:
                if isinstance(block, ContentBlockToolResult):
                    override = self._provider_tool_result_overrides.get(block.tool_use_id)
                    if override is not None:
                        blocks.append(override)
                        message_changed = True
                        continue
                blocks.append(block)
            if message_changed:
                projected.append(
                    Message(
                        role=message.role,
                        content=blocks,
                        reasoning_content=message.reasoning_content,
                    )
                )
                changed = True
            else:
                projected.append(message)
        return projected if changed else messages

    @staticmethod
    def _provider_request_is_smaller(before: list[Message], after: list[Message]) -> bool:
        return len(after) < len(before) or session_payload_chars(after) < session_payload_chars(
            before
        )

    def _runtime_context_block(self) -> str:
        now = datetime.now().astimezone()
        tzinfo = now.tzinfo
        tz_name = getattr(tzinfo, "key", None) or str(tzinfo) if tzinfo is not None else "local"
        lines = [
            "[Runtime context for this turn]",
            f"Current local date/time: {now.isoformat(timespec='minutes')} ({now.strftime('%a')})",
            f"Time zone / location hint: {tz_name}",
            "Use this runtime context for questions about the current date, time, or local "
            "time zone. Do not treat it as a user request.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _runtime_context_message(runtime_context: str) -> Message:
        return Message(role="user", content=runtime_context)

    @staticmethod
    def _request_context_message(request_context: str | None) -> Message | None:
        if not request_context or not request_context.strip():
            return None
        lines = [
            "[Request context for this turn]",
            "This request-scoped context is not a user request and is not transcript history.",
            "Use it only when it is relevant to the current user request.",
            request_context.strip(),
        ]
        return Message(role="user", content="\n".join(lines))

    @staticmethod
    def _with_request_context_messages(
        messages: list[Message],
        request_context_message: Message | None,
        request_context_insert_index: int,
        runtime_context_message: Message,
        runtime_context_insert_index: int,
    ) -> list[Message]:
        result = list(messages)
        runtime_idx = max(0, min(runtime_context_insert_index, len(result)))
        if request_context_message is not None:
            request_idx = max(0, min(request_context_insert_index, len(result)))
            result.insert(request_idx, request_context_message)
            if request_idx <= runtime_idx:
                runtime_idx += 1
        runtime_idx = max(0, min(runtime_idx, len(result)))
        if runtime_idx < len(result) and result[runtime_idx].role == "user":
            result[runtime_idx] = Agent._append_runtime_context_to_user_message(
                result[runtime_idx],
                runtime_context_message,
            )
        else:
            result.insert(runtime_idx, runtime_context_message)
        return result

    @staticmethod
    def _append_runtime_context_to_user_message(
        message: Message,
        runtime_context_message: Message,
    ) -> Message:
        runtime_content = runtime_context_message.content
        if not isinstance(runtime_content, str):
            return runtime_context_message
        if isinstance(message.content, str):
            return Message(
                role=message.role,
                content=f"{message.content}\n\n{runtime_content}",
                reasoning_content=message.reasoning_content,
            )
        if isinstance(message.content, list):
            return Message(
                role=message.role,
                content=[
                    *message.content,
                    ContentBlockText(text=f"\n\n{runtime_content}"),
                ],
                reasoning_content=message.reasoning_content,
            )
        return runtime_context_message

    @staticmethod
    def _cache_breakpoints_without_runtime_context(
        cache_breakpoints: list[dict[str, str]] | None,
    ) -> list[dict[str, str]] | None:
        if not cache_breakpoints:
            return None
        return list(cache_breakpoints)

    def _skills_context_message(self) -> Message | None:
        prompt = self.config.skills_context_prompt
        if not prompt or not prompt.strip():
            return None
        lines = [
            "[Available skills for this turn]",
            "This is runtime-provided context, not a user request.",
            "Use it only to decide whether to call skill_view for the current task.",
            prompt.strip(),
        ]
        return Message(role="user", content="\n".join(lines))

    def _transition(self, to: AgentState) -> StateChangeEvent:
        ev = StateChangeEvent(from_state=self._state, to_state=to)
        self._state = to
        return ev

    @staticmethod
    def _is_turn_yield_result(result: ToolResult) -> bool:
        if result.tool_name != "sessions_yield" or result.is_error:
            return False
        try:
            payload = json.loads(result.content)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        return payload.get("status") == "yielded"

    @staticmethod
    def _terminal_artifact_delivery_artifacts(
        results: list[ToolResult],
    ) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for result in results:
            if result.tool_name != "publish_artifact" or result.is_error:
                continue
            if result.artifacts:
                artifacts.extend(result.artifacts)
                continue
            try:
                payload = json.loads(result.content)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("status") not in {"published", "already_published"}:
                continue
            artifact = payload.get("artifact")
            artifacts.append(artifact if isinstance(artifact, dict) else {})
        return artifacts

    @staticmethod
    def _artifact_delivery_final_response_text(
        artifacts: list[dict[str, Any]],
    ) -> str:
        names = [
            str(item.get("name") or item.get("filename") or "").strip()
            for item in artifacts
            if isinstance(item, dict)
        ]
        named = [name for name in names if name]
        if named:
            return "The generated file is ready: " + ", ".join(named) + "."
        return "The generated file is ready."

    def _build_compaction_config(self) -> CompactionConfig:
        return build_compaction_config_from_provider(
            self.provider,
            default_model=self.config.model_id,
        )

    @staticmethod
    def _live_request_jsonable(value: Any) -> Any:
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return model_dump(mode="json", exclude_none=True)
            except TypeError:
                return model_dump(mode="json")
        if isinstance(value, list | tuple):
            return [Agent._live_request_jsonable(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): Agent._live_request_jsonable(item) for key, item in value.items()
            }
        if hasattr(value, "__dict__"):
            return {
                str(key): Agent._live_request_jsonable(item)
                for key, item in vars(value).items()
                if not str(key).startswith("_")
            }
        try:
            json.dumps(value)
        except TypeError:
            return repr(value)
        return value

    def _estimate_live_request_tokens(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> int:
        """Estimate the current provider request size without lifetime usage."""

        payload: dict[str, Any] = {
            "messages": [self._live_request_jsonable(message) for message in messages],
        }
        if tools:
            payload["tools"] = [self._live_request_jsonable(tool) for tool in tools]
        if config is not None:
            if config.system:
                payload["system"] = config.system
            config_payload = config.model_dump(
                mode="json",
                exclude_none=True,
                exclude={"system", "model_capabilities"},
            )
            payload.update(config_payload)

        estimated_chars = len(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        return max(1, estimated_chars // 4)

    async def _check_context_overflow(
        self,
        messages: list[Message],
        estimated_context_tokens: int,
        *,
        request_context_insert_index: int | None = None,
        runtime_context_insert_index: int | None = None,
        compaction_window_tokens: int | None = None,
    ) -> CompactionOutcome | None:
        """Check if estimated live context tokens exceed the overflow threshold.

        Uses sub-agent flush instead of prompt injection.
        The flush is re-entrant: it can trigger on every approach to threshold.
        """
        self._last_compaction_refusal_reason = None
        window_tokens = compaction_window_tokens or self.config.context_window_tokens
        threshold = self.config.context_overflow_threshold * window_tokens
        if estimated_context_tokens <= threshold:
            return CompactionOutcome(
                messages=messages,
                request_context_insert_index=request_context_insert_index,
                runtime_context_insert_index=runtime_context_insert_index,
            )

        compaction_id = new_compaction_id()
        # --- Pre-compaction flush; inline compaction can continue on degraded flush. ---
        flush_task: asyncio.Task | None = None
        self._consume_completed_flush_task()

        async def _await_flush_task() -> Any | None:
            # Give flush a grace period to complete instead of cancelling immediately.
            # Adds up to flush_timeout_seconds (default 15s) of latency, but without
            # this the flush is effectively dead code (always cancelled before finishing).
            if flush_task is not None and not flush_task.done():
                if flush_task is self._flush_wait_timed_out_task:
                    return None
                try:
                    receipt = await asyncio.wait_for(
                        asyncio.shield(flush_task),
                        timeout=self.config.flush_timeout_seconds,
                    )
                    logger.info("memory_flush.completed_after_compaction")
                    self._flush_wait_timed_out_task = None
                    self._mark_flush_task_completed(flush_task)
                    return receipt
                except TimeoutError:
                    self._flush_wait_timed_out_task = flush_task
                    next_retry_seconds = self._record_flush_timeout_backoff()
                    logger.warning(
                        "memory_flush.timed_out",
                        timeout_seconds=self.config.flush_timeout_seconds,
                        next_retry_seconds=next_retry_seconds,
                    )
                except Exception as exc:
                    logger.warning("memory_flush.await_failed", error=str(exc))
                    self._mark_flush_task_completed(flush_task)
                    return None
            if flush_task is not None and flush_task.done():
                try:
                    receipt = flush_task.result()
                    self._flush_wait_timed_out_task = None
                    self._mark_flush_task_completed(flush_task)
                    return receipt
                except Exception as exc:
                    logger.warning("memory_flush.await_failed", error=str(exc))
                    self._flush_wait_timed_out_task = None
                    self._mark_flush_task_completed(flush_task)
                    return None
            return None

        if not self._flush_done_this_cycle and self.config.flush_enabled:
            try:
                from opensquilla.memory.flush import (
                    resolve_flush_plan,
                    should_flush,
                )

                now = time.monotonic()
                if self._active_flush_task is not None and not self._active_flush_task.done():
                    logger.debug("memory_flush.skipped", reason="already_running")
                    flush_task = self._active_flush_task
                elif now < self._flush_backoff_until:
                    logger.warning(
                        "memory_flush.skipped",
                        reason="backoff",
                        retry_after_seconds=round(self._flush_backoff_until - now, 3),
                    )
                else:
                    transcript_bytes = sum(
                        len(m.content.encode("utf-8")) if isinstance(m.content, str) else 0
                        for m in messages
                    )

                    if should_flush(
                        total_tokens=estimated_context_tokens,
                        threshold_tokens=int(threshold),
                        transcript_bytes=transcript_bytes,
                    ):
                        plan = resolve_flush_plan(
                            workspace_dir=self.config.flush_workspace_dir,
                            archive_max_bytes=self.config.flush_archive_max_bytes,
                        )
                        logger.info(
                            "memory_flush.triggered",
                            path=plan.relative_path,
                            total_tokens=estimated_context_tokens,
                            threshold=int(threshold),
                        )
                        flush_task = asyncio.create_task(self._run_flush(plan, list(messages)))
                        flush_task.add_done_callback(self._on_flush_task_done)
                        self._active_flush_task = flush_task
                        self._flush_done_this_cycle = True
            except Exception:
                logger.debug("memory_flush.skipped", reason="flush module unavailable")

        if self.config.flush_enabled:
            if (
                flush_task is not None
                and not flush_task.done()
                and time.monotonic() < self._flush_backoff_until
            ):
                logger.warning(
                    "memory_flush.skipped",
                    reason="backoff",
                    retry_after_seconds=round(self._flush_backoff_until - time.monotonic(), 3),
                )
                self._flush_done_this_cycle = False
            receipt = await _await_flush_task()
            if not flush_receipt_allows_destructive_compaction(receipt):
                reason = "memory_flush_degraded_before_compaction"
                if flush_task is not None and self._flush_wait_timed_out_task is flush_task:
                    reason = "memory_flush_timeout_before_compaction"
                logger.warning(
                    "memory_flush.degraded_before_compaction",
                    reason=reason,
                    mode=getattr(receipt, "mode", None),
                    integrity_status=getattr(receipt, "integrity_status", None),
                    indexed_chunk_count=getattr(receipt, "indexed_chunk_count", None),
                )
                self._flush_done_this_cycle = False
                if self.config.flush_compaction_requires_safe_receipt:
                    self._last_compaction_refusal_reason = reason
                    if self._session_key:
                        notify_compaction(
                            self._session_key,
                            source="automatic",
                            phase="agent_inline_overflow",
                            status="skipped",
                            reason=reason,
                            tokens_before=estimated_context_tokens,
                            context_window_tokens=window_tokens,
                            **compaction_effect_payload(
                                status="skipped",
                                reason=reason,
                            ),
                            **compaction_lifecycle_payload(
                                compaction_id,
                                COMPACTION_TRIGGERED_EVENT,
                            ),
                        )
                    return None

        # --- Compaction ---
        entries = [
            {
                "role": m.role,
                "content": (
                    m.content if isinstance(m.content, str) else _flatten_content_blocks(m.content)
                ),
            }
            for m in messages
        ]

        request = CompactionRequest(
            session_id="agent-turn",
            entries=entries,
            context_window_tokens=window_tokens,
            config=self._build_compaction_config(),
        )

        if self._session_key:
            notify_compaction(
                self._session_key,
                source="automatic",
                phase="agent_inline_overflow",
                status="started",
                tokens_before=estimated_context_tokens,
                context_window_tokens=window_tokens,
                **compaction_effect_payload(status="started"),
                **compaction_lifecycle_payload(
                    compaction_id,
                    COMPACTION_TRIGGERED_EVENT,
                ),
            )

        try:
            result = await compact_context(request)
        except Exception as exc:  # noqa: BLE001
            self._last_compaction_refusal_reason = "compaction_failed"
            if self._session_key:
                notify_compaction(
                    self._session_key,
                    source="automatic",
                    phase="agent_inline_overflow",
                    status="failed",
                    message=str(exc),
                    reason=self._last_compaction_refusal_reason,
                    tokens_before=estimated_context_tokens,
                    context_window_tokens=window_tokens,
                    **compaction_effect_payload(status="failed"),
                    **compaction_lifecycle_payload(
                        compaction_id,
                        COMPACTION_TRIGGERED_EVENT,
                    ),
                )
            return None  # signal failure

        if self._session_key and result.removed_count > 0 and result.summary:
            for event in (
                COMPACTION_CHUNK_SUMMARIZED_EVENT,
                COMPACTION_SUMMARY_VERIFIED_EVENT,
            ):
                observed_payload = compaction_lifecycle_payload(compaction_id, event)
                observed_payload.update(
                    compaction_result_payload(
                        result,
                        tokens_before=estimated_context_tokens,
                    )
                )
                notify_compaction(
                    self._session_key,
                    source="automatic",
                    phase="agent_inline_overflow",
                    status="observed",
                    context_window_tokens=window_tokens,
                    **compaction_effect_payload(status="observed"),
                    **observed_payload,
                )

        # Removing history without a replacement summary is equivalent to
        # bare truncation; reject it so the caller takes the existing
        # compaction failure path instead of silently dropping context.
        if result.removed_count > 0 and not result.summary:
            logger.warning(
                "compaction.empty_summary_rejected",
                removed_count=result.removed_count,
                kept_count=len(result.kept_entries),
            )
            self._last_compaction_refusal_reason = "empty_summary_rejected"
            if self._session_key:
                notify_compaction(
                    self._session_key,
                    source="automatic",
                    phase="agent_inline_overflow",
                    status="failed",
                    reason=self._last_compaction_refusal_reason,
                    tokens_before=estimated_context_tokens,
                    context_window_tokens=window_tokens,
                    removed_count=result.removed_count,
                    kept_count=len(result.kept_entries),
                    **compaction_effect_payload(status="failed"),
                    **compaction_lifecycle_payload(
                        compaction_id,
                        COMPACTION_TRIGGERED_EVENT,
                    ),
                )
            return None

        has_structured_content = any(not isinstance(m.content, str) for m in messages)
        if result.removed_count == 0 and not result.summary and has_structured_content:
            await _await_flush_task()
            self._flush_done_this_cycle = False
            skip_reason = result.skip_reason or "structured_content_noop"
            if self._session_key:
                notify_compaction(
                    self._session_key,
                    source="automatic",
                    phase="agent_inline_overflow",
                    status="skipped",
                    reason=skip_reason,
                    tokens_before=estimated_context_tokens,
                    tokens_after=result.tokens_after,
                    remaining_budget_tokens=result.remaining_budget_tokens,
                    context_window_tokens=window_tokens,
                    **compaction_effect_payload(
                        status="skipped",
                        reason=skip_reason,
                        user_visible=False,
                    ),
                    **compaction_lifecycle_payload(
                        compaction_id,
                        COMPACTION_TRIGGERED_EVENT,
                    ),
                )
            return CompactionOutcome(messages=messages)

        # Rebuild message list from compacted entries
        compacted: list[Message] = []
        if result.summary:
            compacted.append(Message(role="user", content=f"[Context summary]\n{result.summary}"))
            compacted.append(
                Message(role="assistant", content="Understood. Continuing from summary.")
            )
        for entry in result.kept_entries:
            compacted.append(Message(role=entry["role"], content=entry["content"]))

        await _await_flush_task()

        # Reset flush flag so it can trigger again after next compaction
        self._flush_done_this_cycle = False

        # Trigger 6: post-compaction sync
        if self._memory_sync_manager is not None:
            self._memory_sync_manager.mark_dirty()

        kept_entries = [{"role": e["role"], "content": e["content"]} for e in result.kept_entries]
        adjusted_request_idx = self._adjust_compacted_insert_index(
            entries,
            kept_entries,
            request_context_insert_index,
            summary_present=bool(result.summary),
        )
        adjusted_runtime_idx = self._adjust_compacted_insert_index(
            entries,
            kept_entries,
            runtime_context_insert_index,
            summary_present=bool(result.summary),
        )
        return CompactionOutcome(
            messages=compacted,
            compacted=True,
            summary=result.summary,
            kept_entries=kept_entries,
            removed_count=result.removed_count,
            compaction_id=compaction_id,
            request_context_insert_index=adjusted_request_idx,
            runtime_context_insert_index=adjusted_runtime_idx,
        )

    def _consume_completed_flush_task(self) -> None:
        task = self._active_flush_task
        if task is None or not task.done():
            return
        self._mark_flush_task_completed(task)

    def _on_flush_task_done(self, task: asyncio.Task) -> None:
        self._mark_flush_task_completed(task)

    def _mark_flush_task_completed(self, task: asyncio.Task) -> None:
        if self._flush_wait_timed_out_task is task:
            self._flush_wait_timed_out_task = None
        if self._active_flush_task is not task:
            return
        try:
            receipt = task.result()
        except asyncio.CancelledError:
            logger.debug("memory_flush.cancelled")
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_flush.background_failed", error=str(exc))
        else:
            mode = getattr(receipt, "mode", None)
            if not flush_receipt_is_successful_flush(receipt):
                next_retry_seconds = self._ensure_flush_degraded_backoff()
                logger.warning(
                    "memory_flush.degraded",
                    mode=mode,
                    result_status=getattr(receipt, "result_status", None),
                    integrity_status=getattr(receipt, "integrity_status", None),
                    output_coverage_status=getattr(receipt, "output_coverage_status", None),
                    obligation_status=getattr(receipt, "obligation_status", None),
                    raw_reason=getattr(receipt, "raw_reason", None),
                    next_retry_seconds=next_retry_seconds,
                )
            else:
                self._flush_backoff_seconds = 0.0
                self._flush_backoff_until = 0.0
        self._active_flush_task = None

    def _record_flush_timeout_backoff(self) -> float:
        initial = max(0.0, float(self.config.flush_backoff_initial_seconds))
        maximum = max(initial, float(self.config.flush_backoff_max_seconds))
        if initial == 0:
            self._flush_backoff_seconds = 0.0
            self._flush_backoff_until = 0.0
            return 0.0
        if self._flush_backoff_seconds <= 0:
            next_retry_seconds = initial
        else:
            next_retry_seconds = min(self._flush_backoff_seconds * 2, maximum)
        self._flush_backoff_seconds = next_retry_seconds
        self._flush_backoff_until = time.monotonic() + next_retry_seconds
        return next_retry_seconds

    def _ensure_flush_degraded_backoff(self) -> float:
        remaining = self._flush_backoff_until - time.monotonic()
        if remaining > 0:
            return remaining
        return self._record_flush_timeout_backoff()

    @staticmethod
    def _adjust_compacted_insert_index(
        entries: list[dict[str, Any]],
        kept_entries: list[dict[str, Any]],
        original_index: int | None,
        *,
        summary_present: bool,
    ) -> int | None:
        """Map a pre-compaction insertion boundary onto the compacted message list."""
        if original_index is None:
            return None
        adjusted = 2 if summary_present and original_index > 0 else 0
        search_start = 0
        for kept in kept_entries:
            matched_index = None
            for idx in range(search_start, len(entries)):
                entry = entries[idx]
                if entry.get("role") == kept.get("role") and entry.get("content") == kept.get(
                    "content"
                ):
                    matched_index = idx
                    break
            if matched_index is None:
                continue
            if matched_index < original_index:
                adjusted += 1
            search_start = matched_index + 1
        return adjusted

    async def _run_flush(
        self,
        plan: Any,
        messages: list[Message],
    ) -> Any | None:
        """Run memory flush before compaction; delegates to SessionFlushService.

        When a ``SessionFlushService`` is injected, this method forwards the
        call and returns its receipt. When no service is injected (standalone
        Agent instances in unit tests or legacy paths), it falls back to an
        inline raw-dump so we don't silently drop data.
        """
        service = getattr(self, "_session_flush_service", None)
        if service is not None:
            try:
                from opensquilla.session.keys import parse_agent_id

                sk = getattr(self, "_session_key", None) or "agent:main:legacy"
                return await service.execute(
                    messages,
                    session_key=sk,
                    agent_id=parse_agent_id(sk),
                    timeout=self.config.flush_background_timeout_seconds,
                    message_window=0,
                    segment_mode="auto",
                )
            except asyncio.CancelledError:
                logger.debug("memory_flush.cancelled")
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("memory_flush.service_failed", error=str(exc))
            return None

        # Legacy fallback — only hit when no service is injected.
        from opensquilla.memory.flush import dump_transcript_excerpt

        if self.provider is None and self.tool_handler is not None:
            excerpt = dump_transcript_excerpt(messages)
            if excerpt.strip():
                from opensquilla.tool_boundary import ToolCall as _FlushToolCall

                await self.tool_handler(
                    _FlushToolCall(
                        tool_use_id="flush-fallback",
                        tool_name="memory_save",
                        arguments={
                            "content": excerpt,
                            "path": plan.relative_path,
                            "mode": "append",
                        },
                    )
                )
        return None

    @staticmethod
    def _has_provider_context_replay_marker(arguments: dict[str, Any]) -> bool:
        if Agent._has_provider_context_argument_marker(arguments):
            return True
        return any(
            isinstance(value, str) and value.startswith(_INVALID_PROVIDER_CONTEXT_PROJECTION_PREFIX)
            for value in arguments.values()
        )

    @staticmethod
    def _is_provider_context_projection_reuse_result(result: ToolResult) -> bool:
        status: Mapping[str, Any] = result.execution_status or {}
        return bool(
            result.is_error
            and isinstance(status, dict)
            and status.get("reason") == _PROVIDER_CONTEXT_PROJECTION_REUSED_REASON
        )

    def _strip_provider_context_marker_replay_for_provider(
        self,
        messages: list[Message],
    ) -> list[Message]:
        blocked_tool_ids: set[str] = set()
        for message in messages:
            if not isinstance(message.content, list):
                continue
            for block in message.content:
                if (
                    isinstance(block, ContentBlockToolUse)
                    and isinstance(block.id, str)
                    and self._has_provider_context_replay_marker(block.input)
                ):
                    blocked_tool_ids.add(block.id)

        if not blocked_tool_ids:
            return messages

        stripped_messages: list[Message] = []
        stripped_blocks = 0
        for message in messages:
            if not isinstance(message.content, list):
                stripped_messages.append(message)
                continue
            next_content: list[Any] = []
            changed = False
            for block in message.content:
                if isinstance(block, ContentBlockToolUse) and block.id in blocked_tool_ids:
                    stripped_blocks += 1
                    changed = True
                    continue
                if (
                    isinstance(block, ContentBlockToolResult)
                    and block.tool_use_id in blocked_tool_ids
                ):
                    stripped_blocks += 1
                    changed = True
                    continue
                next_content.append(block)
            if not changed:
                stripped_messages.append(message)
                continue
            if not next_content:
                continue
            stripped_messages.append(
                Message(
                    role=message.role,
                    content=next_content,
                    reasoning_content=getattr(message, "reasoning_content", None),
                )
            )

        if (
            stripped_blocks
            and stripped_messages
            and stripped_messages[-1].role == "assistant"
        ):
            stripped_messages.append(
                Message(role="user", content=_PROVIDER_CONTEXT_REPAIR_PROMPT)
            )

        self.config.metadata["tool_argument_projection_replay_stripped"] = (
            self.config.metadata.get("tool_argument_projection_replay_stripped", 0)
            + stripped_blocks
        )
        self._write_turn_call_log(
            "tool_argument_projection_replay_stripped",
            tool_use_ids=sorted(blocked_tool_ids),
            stripped_blocks=stripped_blocks,
        )
        return stripped_messages

    @staticmethod
    def _parse_tool_argument_projection(value: str) -> dict[str, str] | None:
        if not value.startswith(_TOOL_ARGUMENT_PROJECTION_PREFIX):
            return None
        metadata: dict[str, str] = {}
        for line in value.splitlines()[1:]:
            if line in {"head:", "tail:"}:
                break
            key, separator, raw_value = line.partition(":")
            if not separator:
                continue
            metadata[key.strip()] = raw_value.strip()
        return metadata

    @staticmethod
    def _provider_projection_placeholder(tool_name: str, field: str) -> str:
        return (
            f"[invalid_provider_context_projection:{tool_name}.{field}] "
            "provider-only compacted tool argument omitted; regenerate the real "
            "argument instead of copying provider context."
        )

    @staticmethod
    def _has_provider_context_argument_marker(arguments: dict[str, Any]) -> bool:
        return arguments.get(_INVALID_PROVIDER_CONTEXT_ARGUMENTS_KEY) is True or any(
            arguments.get(marker) is True for marker in _COMPACTED_TOOL_ARGUMENT_MARKERS
        )

    @staticmethod
    def _provider_compacted_arguments_placeholder(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            _INVALID_PROVIDER_CONTEXT_ARGUMENTS_KEY: True,
            "tool": tool_name,
            "reason": "provider_context_omitted",
        }

    def _sanitize_projected_tool_call_arguments(self, tc: ToolCall) -> ToolCall:
        if self._has_provider_context_argument_marker(tc.arguments):
            return ToolCall(
                tool_use_id=tc.tool_use_id,
                tool_name=tc.tool_name,
                arguments=self._provider_compacted_arguments_placeholder(
                    tc.tool_name,
                    tc.arguments,
                ),
                synthetic_from_text=tc.synthetic_from_text,
                origin_trace=tc.origin_trace,
            )
        sanitized = dict(tc.arguments)
        changed = False
        for argument_name, value in tc.arguments.items():
            if not isinstance(value, str) or not value.startswith(
                (
                    _TOOL_ARGUMENT_PROJECTION_PREFIX,
                    _HISTORICAL_TOOL_ARGUMENT_PROJECTION_PREFIX,
                    _INVALID_PROVIDER_CONTEXT_PROJECTION_PREFIX,
                )
            ):
                continue
            sanitized[argument_name] = self._provider_projection_placeholder(
                tc.tool_name,
                argument_name,
            )
            changed = True
        if not changed:
            return tc
        return ToolCall(
            tool_use_id=tc.tool_use_id,
            tool_name=tc.tool_name,
            arguments=sanitized,
            synthetic_from_text=tc.synthetic_from_text,
            origin_trace=tc.origin_trace,
        )

    def _projection_rehydrate_error(
        self,
        tc: ToolCall,
        *,
        field: str,
        reason: str,
    ) -> ToolResult:
        self.config.metadata["tool_argument_projection_rehydrate_failures"] = (
            self.config.metadata.get(
                "tool_argument_projection_rehydrate_failures",
                0,
            )
            + 1
        )
        self._write_turn_call_log(
            "tool_argument_projection_rehydrate_failed",
            tool_use_id=tc.tool_use_id,
            tool_name=tc.tool_name,
            field=field,
            reason=reason,
        )
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            tool_name=tc.tool_name,
            content=(
                f"The {tc.tool_name}.{field} input was not available in executable "
                "form. The tool was not run; regenerate the complete argument and "
                "retry the tool call."
            ),
            is_error=True,
            execution_status=runtime_execution_status(
                "error",
                reason=_PROVIDER_CONTEXT_PROJECTION_REUSED_REASON,
            ),
        )

    def _provider_compacted_arguments_error(
        self,
        tc: ToolCall,
        *,
        reason: str,
    ) -> ToolResult:
        self.config.metadata["tool_argument_projection_rehydrate_failures"] = (
            self.config.metadata.get(
                "tool_argument_projection_rehydrate_failures",
                0,
            )
            + 1
        )
        self._write_turn_call_log(
            "tool_argument_projection_rehydrate_failed",
            tool_use_id=tc.tool_use_id,
            tool_name=tc.tool_name,
            reason=reason,
        )
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            tool_name=tc.tool_name,
            content=(
                f"The {tc.tool_name} arguments were not available in executable "
                "form. The tool was not run; regenerate the complete arguments and "
                "retry the tool call."
            ),
            is_error=True,
            execution_status=runtime_execution_status(
                "error",
                reason=_PROVIDER_CONTEXT_PROJECTION_REUSED_REASON,
            ),
        )

    def _rehydrate_projected_tool_arguments(
        self,
        tc: ToolCall,
    ) -> ToolCall | ToolResult:
        if self._has_provider_context_argument_marker(tc.arguments):
            return self._provider_compacted_arguments_error(
                tc,
                reason="provider_compacted_arguments_reused",
            )
        for argument_name, value in tc.arguments.items():
            if not isinstance(value, str) or not value.startswith(
                (
                    _TOOL_ARGUMENT_PROJECTION_PREFIX,
                    _HISTORICAL_TOOL_ARGUMENT_PROJECTION_PREFIX,
                    _INVALID_PROVIDER_CONTEXT_PROJECTION_PREFIX,
                )
            ):
                continue
            return self._projection_rehydrate_error(
                tc,
                field=argument_name,
                reason="provider_projection_reused",
            )
        return tc

    async def _execute_tool(self, tc: ToolCall) -> ToolResult:
        """Dispatch a tool call to the registered handler."""
        args_hash = hashlib.sha256(
            json.dumps(tc.arguments, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()
        failure_signature = (tc.tool_name, args_hash)
        block_threshold = max(
            0,
            int(getattr(self.config, "tool_failure_loop_block_threshold", 0) or 0),
        )
        if (
            block_threshold > 0
            and self._tool_failure_loop_counts.get(failure_signature, 0) >= block_threshold - 1
        ):
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                tool_name=tc.tool_name,
                content=(
                    f"The exact same {tc.tool_name} call has already failed repeatedly. "
                    "Do not retry this exact call unchanged. Use a different approach, "
                    "change the arguments, or explain the blocker to the user."
                ),
                is_error=True,
                execution_status=runtime_execution_status(
                    "error",
                    reason="tool_failure_loop_exhausted",
                ),
            )
        if self.tool_handler is None:
            result = ToolResult(
                tool_use_id=tc.tool_use_id,
                tool_name=tc.tool_name,
                content=f"No tool handler registered for tool '{tc.tool_name}'",
                is_error=True,
                execution_status=runtime_execution_status(
                    "error",
                    reason="runtime_error",
                ),
            )
        else:
            try:
                resolved = self._rehydrate_projected_tool_arguments(tc)
                if isinstance(resolved, ToolResult):
                    result = resolved
                else:
                    tc = resolved
                    result = await self.tool_handler(tc)
            except Exception as exc:  # noqa: BLE001
                result = ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name=tc.tool_name,
                    content=f"Tool '{tc.tool_name}' raised: {exc}",
                    is_error=True,
                    execution_status=runtime_execution_status(
                        "error",
                        reason="runtime_error",
                    ),
                )
        if result.is_error:
            self._tool_failure_loop_counts[failure_signature] = (
                self._tool_failure_loop_counts.get(failure_signature, 0) + 1
            )
        else:
            self._tool_failure_loop_counts.pop(failure_signature, None)
            if tc.tool_name in {
                "apply_patch",
                "background_process",
                "edit_file",
                "execute_code",
                "exec_command",
                "git_commit",
                "install_skill_deps",
                "write_file",
            }:
                self._tool_failure_loop_counts.clear()
        return result

    def _matched_meta_skill_name_from_metadata(self) -> str | None:
        metadata = self.config.metadata or {}
        match = metadata.get("meta_match")
        plan = getattr(match, "plan", None)
        name = getattr(plan, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None

    def _coerce_meta_tool_call(self, tc: ToolCall) -> ToolCall:
        tc = self._coerce_meta_skill_view_tool_call(tc)
        return self._coerce_meta_invoke_tool_call(tc)

    def _coerce_meta_invoke_tool_call(self, tc: ToolCall) -> ToolCall:
        if tc.tool_name != "meta_invoke":
            return tc
        name = tc.arguments.get("name")
        if isinstance(name, str) and name.strip():
            return tc

        raw = tc.arguments.get("_raw")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                parsed_name = parsed.get("name")
                if isinstance(parsed_name, str) and parsed_name.strip():
                    return ToolCall(
                        tool_use_id=tc.tool_use_id,
                        tool_name="meta_invoke",
                        arguments={"name": parsed_name.strip()},
                        synthetic_from_text=tc.synthetic_from_text,
                        origin_trace=tc.origin_trace,
                    )

        matched_name = self._matched_meta_skill_name_from_metadata()
        if matched_name is None or not (self.config.metadata or {}).get("meta_match_tool_choice"):
            return tc

        logger.info(
            "agent.meta_invoke_arguments_coerced",
            skill=matched_name,
            tool_use_id=tc.tool_use_id,
        )
        return ToolCall(
            tool_use_id=tc.tool_use_id,
            tool_name="meta_invoke",
            arguments={"name": matched_name},
            synthetic_from_text=tc.synthetic_from_text,
            origin_trace=tc.origin_trace,
        )

    def _force_matched_meta_invoke_tool_calls(
        self,
        tool_calls: list[ToolCall],
    ) -> list[ToolCall]:
        metadata = self.config.metadata or {}
        if not metadata.get("meta_match_tool_choice"):
            return tool_calls
        matched_name = self._matched_meta_skill_name_from_metadata()
        if not matched_name:
            return tool_calls
        for tc in tool_calls:
            if (
                tc.tool_name == "meta_invoke"
                and isinstance(tc.arguments.get("name"), str)
                and tc.arguments["name"].strip()
            ):
                return tool_calls
        if not tool_calls:
            return tool_calls

        first = tool_calls[0]
        logger.warning(
            "agent.meta_match_forced_invoke_rewrite",
            skill=matched_name,
            original_tool=first.tool_name,
            tool_use_id=first.tool_use_id,
        )
        return [
            ToolCall(
                tool_use_id=first.tool_use_id,
                tool_name="meta_invoke",
                arguments={"name": matched_name},
                synthetic_from_text=first.synthetic_from_text,
                origin_trace=first.origin_trace,
            )
        ]

    def _coerce_meta_skill_view_tool_call(self, tc: ToolCall) -> ToolCall:
        if tc.tool_name != "skill_view":
            return tc
        name = tc.arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            return tc
        file_path = tc.arguments.get("file_path")
        if file_path not in (None, "", "SKILL.md", "./SKILL.md"):
            return tc

        metadata = self.config.metadata or {}
        skill_loader = metadata.get("skill_loader")
        if skill_loader is None:
            return tc
        try:
            skill_spec = skill_loader.get_by_name(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent.meta_skill_view_coerce_failed", skill=name, error=str(exc))
            return tc

        if (
            skill_spec is None
            or getattr(skill_spec, "kind", "skill") != "meta"
            or getattr(skill_spec, "disable_model_invocation", False)
        ):
            return tc

        logger.info(
            "agent.meta_skill_view_coerced",
            skill=name,
            tool_use_id=tc.tool_use_id,
        )
        return ToolCall(
            tool_use_id=tc.tool_use_id,
            tool_name="meta_invoke",
            arguments={"name": name},
            synthetic_from_text=tc.synthetic_from_text,
            origin_trace=tc.origin_trace,
        )

    async def _run_one_streaming(
        self,
        tc: ToolCall,
        tool_context: Any,
    ) -> AsyncIterator[AgentEvent | ToolResult]:
        """Stream a meta_invoke tool call inline and return a terminal ToolResult."""

        import opensquilla.skills.creator  # noqa: F401
        from opensquilla.skills.creator.runtime_e2e import make_runtime_e2e_context
        from opensquilla.skills.meta.enabled import is_meta_skill_enabled
        from opensquilla.skills.meta.inputs import make_meta_inputs
        from opensquilla.skills.meta.orchestrator import (
            MetaOrchestrator,
            make_agent_runner_from_parent,
            make_llm_chat_from_provider,
            make_tool_invoker_from_handler,
        )
        from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan
        from opensquilla.skills.meta.types import MetaMatch, MetaResult
        from opensquilla.tools.dispatch import preflight_tool_call
        from opensquilla.tools.types import current_tool_context

        if not is_meta_skill_enabled(self.config):
            yield ToolResult(
                tool_use_id=tc.tool_use_id,
                tool_name="meta_invoke",
                content="meta-skill is disabled by configuration",
                is_error=True,
                terminates_turn=False,
            )
            return

        current_depth = _meta_invoke_depth.get()
        turn_count = _meta_invoke_turn_count.get()
        if current_depth >= MAX_META_INVOKE_DEPTH:
            yield ToolResult(
                tool_use_id=tc.tool_use_id,
                tool_name="meta_invoke",
                content=(
                    f"meta_invoke recursion depth limit reached "
                    f"({MAX_META_INVOKE_DEPTH}); refusing nested call to "
                    f"{tc.arguments.get('name', '<unknown>')!r}."
                ),
                is_error=True,
                terminates_turn=False,
            )
            return
        if turn_count >= MAX_META_INVOKE_PER_TURN:
            yield ToolResult(
                tool_use_id=tc.tool_use_id,
                tool_name="meta_invoke",
                content=(
                    f"meta_invoke per-turn invocation limit reached "
                    f"({MAX_META_INVOKE_PER_TURN})."
                ),
                is_error=True,
                terminates_turn=False,
            )
            return

        depth_token = _meta_invoke_depth.set(current_depth + 1)
        try:
            _meta_invoke_turn_count.set(turn_count + 1)
            if self._tool_registry is None:
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content="meta_invoke requires Agent to be constructed with tool_registry",
                    is_error=True,
                    terminates_turn=False,
                )
                return

            effective_ctx = current_tool_context.get() or tool_context
            policy_err = await preflight_tool_call(
                registry=self._tool_registry,
                ctx=effective_ctx,
                tool_call=tc,
            )
            if policy_err is not None:
                yield policy_err
                return

            metadata = self.config.metadata or {}
            skill_loader = metadata.get("skill_loader")
            if skill_loader is None:
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content=(
                        "meta_invoke unavailable: skill_loader missing from "
                        "AgentConfig.metadata"
                    ),
                    is_error=True,
                    terminates_turn=False,
                )
                return

            workspace_dir = (
                getattr(effective_ctx, "workspace_dir", None)
                or metadata.get("bootstrap_workspace_dir")
                or getattr(self.config, "workspace_dir", None)
            )
            name = tc.arguments.get("name")
            if not isinstance(name, str) or not name:
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content="meta_invoke requires a non-empty 'name' argument",
                    is_error=True,
                    terminates_turn=False,
                )
                return

            # Spec §10: "New meta_invoke while awaiting | Reject the new
            # invocation". Without this guard the new run hits the
            # partial unique index on (session_key) WHERE
            # status='awaiting_user' deep inside try_claim_awaiting and
            # the user sees an opaque "awaiting claim rejected" error
            # instead of a clear "please finish or cancel the previous
            # form" hint.
            if (
                self._meta_run_writer is not None
                and self._session_key
            ):
                try:
                    existing_awaiting = self._meta_run_writer.peek_awaiting(
                        session_id=self._session_key,
                    )
                except Exception:  # noqa: BLE001 — fail-open
                    existing_awaiting = None
                if existing_awaiting is not None:
                    yield ToolResult(
                        tool_use_id=tc.tool_use_id,
                        tool_name="meta_invoke",
                        content=(
                            f"Previous meta-skill ({existing_awaiting.step_id!r} "
                            f"in run {existing_awaiting.run_id}) is still "
                            "waiting for your answer. Please complete the "
                            "form or reply 'cancel' before starting a new "
                            "meta-skill."
                        ),
                        is_error=True,
                        terminates_turn=True,
                    )
                    return

            skill_spec = skill_loader.get_by_name(name)
            if skill_spec is None or getattr(skill_spec, "kind", "skill") != "meta":
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content=f"meta_invoke: {name!r} is not a registered meta-skill",
                    is_error=True,
                    terminates_turn=False,
                )
                return
            if getattr(skill_spec, "disable_model_invocation", False):
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content=f"meta_invoke: {name!r} is not available for model invocation",
                    is_error=True,
                    terminates_turn=False,
                )
                return

            matched_name = self._matched_meta_skill_name_from_metadata()
            current_user_message = (
                getattr(self, "_current_turn_message", "")
                or metadata.get("user_message", "")
                or ""
            )
            if (
                isinstance(current_user_message, str)
                and current_user_message
                and matched_name != name
                and not semantic_meta_skill_allowed(name, current_user_message)
            ):
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content=(
                        f"meta_invoke: {name!r} does not match the current "
                        "user request closely enough for model invocation"
                    ),
                    is_error=True,
                    terminates_turn=False,
                )
                return

            try:
                plan = parse_meta_plan(skill_spec)
            except MetaPlanError as exc:
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content=f"meta-skill {name!r} plan invalid: {exc}",
                    is_error=True,
                    terminates_turn=False,
                )
                return
            if plan is None:
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content=f"meta-skill {name!r} parsed to None",
                    is_error=True,
                    terminates_turn=False,
                )
                return

            runner = make_agent_runner_from_parent(
                provider=self.provider,
                base_config=self.config,
                tool_definitions=self.tool_definitions,
                tool_handler=self.tool_handler,
                agent_factory=type(self),
                workspace_dir=str(workspace_dir) if workspace_dir else None,
                usage_tracker=self._usage_tracker,
                session_key=self._session_key,
            )
            llm_chat = (
                getattr(self, "_test_llm_chat_override", None)
                or (
                    make_llm_chat_from_provider(
                        provider=self.provider,
                        base_config=self.config,
                        usage_tracker=self._usage_tracker,
                        session_key=self._session_key,
                    )
                    if self.provider is not None
                    else None
                )
            )
            tool_invoker = (
                make_tool_invoker_from_handler(tool_handler=self.tool_handler)
                if self.tool_handler is not None
                else None
            )

            memory_persist_enabled = True
            orch = MetaOrchestrator(
                agent_runner=runner,
                skill_loader=skill_loader,
                llm_chat=llm_chat,
                tool_invoker=tool_invoker,
                workspace_dir=str(workspace_dir) if workspace_dir else None,
                run_writer=self._meta_run_writer,
                triggered_by="soft_meta_invoke",
                session_key=getattr(self, "_session_key", None),
                turn_id=getattr(self, "_turn_id", None),
                memory_persist_enabled=memory_persist_enabled,
                usage_tracker=self._usage_tracker,
            )

            system_prompt = (
                self._context.system_prompt
                if self._context is not None
                else self.config.system_prompt or ""
            )
            match = MetaMatch(
                plan=plan,
                inputs=make_meta_inputs(
                    user_message=(
                        getattr(self, "_current_turn_message", "")
                        or metadata.get("user_message", "")
                    ),
                    system_prompt=system_prompt,
                ),
            )

            result: MetaResult | None = None
            from opensquilla.skills.creator.proposer import (
                reset_runtime_e2e_context,
                reset_smoke_fixture_context,
                set_runtime_e2e_context,
                set_smoke_fixture_context,
            )

            runtime_e2e_ctx = make_runtime_e2e_context(
                provider=self.provider,
                base_config=self.config,
                skill_loader=skill_loader,
                tool_definitions=self.tool_definitions,
                tool_handler=self.tool_handler,
                agent_factory=type(self),
                llm_chat=llm_chat,
                tool_invoker=tool_invoker,
                workspace_dir=str(workspace_dir) if workspace_dir else None,
                usage_tracker=self._usage_tracker,
                session_key=getattr(self, "_session_key", None) or "",
                tool_registry=self._tool_registry,
                tool_context=effective_ctx,
                system_prompt=system_prompt,
                baseline_model=getattr(self.config, "model_id", "") or "",
            )
            runtime_e2e_token = set_runtime_e2e_context(runtime_e2e_ctx)
            smoke_fixture_token = set_smoke_fixture_context({"llm_chat": llm_chat})
            try:
                async for ev in orch.iter_events(match):
                    if isinstance(ev, MetaResult):
                        result = ev
                    elif isinstance(ev, TextDeltaEvent):
                        continue
                    else:
                        yield ev
            except Exception as exc:  # noqa: BLE001
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content=f"meta-skill {name!r} raised: {exc}",
                    is_error=True,
                    terminates_turn=False,
                )
                return
            finally:
                reset_smoke_fixture_context(smoke_fixture_token)
                reset_runtime_e2e_context(runtime_e2e_token)

            if result is None:
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content="orchestrator produced no MetaResult sentinel",
                    is_error=True,
                    terminates_turn=False,
                )
                return
            # PR7: a paused MetaResult (awaiting user_input) is NOT a
            # failure. Render the form description into assistant text
            # so IM/CLI fallbacks see it; the Web surface has its own
            # rich form card driven by the synthetic ToolResultEvent
            # emitted by the scheduler, so we suppress the text fallback
            # there to avoid the user seeing both a plain-text dump AND
            # the form (the text was leaking out and looking like the
            # "real" reply in review.
            if result.paused:
                from opensquilla.engine.turn_runner.turn_finalizer_stage import (
                    render_paused_outcome,
                )
                from opensquilla.tools.types import CallerKind
                caller_kind = getattr(self._tool_context, "caller_kind", None)
                is_rich_surface = caller_kind is CallerKind.WEB
                if not is_rich_surface:
                    paused_text = render_paused_outcome(result)
                    if paused_text:
                        yield TextDeltaEvent(text=paused_text)
                yield ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name="meta_invoke",
                    content=(
                        f"meta-skill {name!r} paused awaiting user input."
                    ),
                    is_error=False,
                    terminates_turn=True,
                )
                return
            if not result.ok:
                yield self._format_meta_invoke_failure(tc, result, plan)
                return
            if result.final_text:
                yield TextDeltaEvent(text=result.final_text)
            yield ToolResult(
                tool_use_id=tc.tool_use_id,
                tool_name="meta_invoke",
                content=(
                    f"meta-skill {name!r} completed."
                    if result.final_text
                    else "(meta-skill completed with no output text)"
                ),
                is_error=False,
                terminates_turn=True,
            )
        finally:
            try:
                _meta_invoke_depth.reset(depth_token)
            except ValueError:
                _meta_invoke_depth.set(current_depth)

    async def _run_meta_resume(self, meta_resume: Any) -> AsyncIterator[Any]:
        """Stream a meta-skill resume's events as a single turn.

        ``meta_resume`` is the tuple ``(claim, parsed_fields)`` that
        ``meta_resolution`` stashes on ctx.metadata after a successful
        try_claim_resume CAS. We build a MetaOrchestrator with the same
        wiring ``_run_one_streaming`` uses, then yield every event from
        ``iter_resume_events`` followed by a synthetic DoneEvent so the
        outer stream pipeline can finalize the turn.
        """
        from opensquilla.engine.types import DoneEvent
        from opensquilla.skills.meta.orchestrator import (
            MetaOrchestrator,
            make_agent_runner_from_parent,
            make_llm_chat_from_provider,
            make_tool_invoker_from_handler,
        )
        from opensquilla.skills.meta.types import MetaResult
        from opensquilla.tools.types import current_tool_context

        try:
            claim, parsed = meta_resume
        except (TypeError, ValueError):
            logger.warning("agent.meta_resume_malformed", extra={"value": str(meta_resume)})
            return

        metadata = self.config.metadata or {}
        skill_loader = metadata.get("skill_loader")
        if skill_loader is None or self._meta_run_writer is None:
            logger.warning(
                "agent.meta_resume_missing_deps",
                extra={
                    "has_loader": skill_loader is not None,
                    "has_writer": self._meta_run_writer is not None,
                },
            )
            return

        # Drop the marker so a re-enter through this turn cannot re-resume.
        if isinstance(metadata, dict):
            metadata.pop("meta_resume", None)

        effective_ctx = current_tool_context.get() or None
        workspace_dir = (
            (getattr(effective_ctx, "workspace_dir", None) if effective_ctx else None)
            or metadata.get("bootstrap_workspace_dir")
            or getattr(self.config, "workspace_dir", None)
        )

        runner = make_agent_runner_from_parent(
            provider=self.provider,
            base_config=self.config,
            tool_definitions=self.tool_definitions,
            tool_handler=self.tool_handler,
            agent_factory=type(self),
            workspace_dir=str(workspace_dir) if workspace_dir else None,
            usage_tracker=self._usage_tracker,
            session_key=self._session_key,
        )
        llm_chat = (
            getattr(self, "_test_llm_chat_override", None)
            or (
                make_llm_chat_from_provider(
                    provider=self.provider,
                    base_config=self.config,
                    usage_tracker=self._usage_tracker,
                    session_key=self._session_key,
                )
                if self.provider is not None
                else None
            )
        )
        tool_invoker = (
            make_tool_invoker_from_handler(tool_handler=self.tool_handler)
            if self.tool_handler is not None
            else None
        )

        orch = MetaOrchestrator(
            agent_runner=runner,
            skill_loader=skill_loader,
            llm_chat=llm_chat,
            tool_invoker=tool_invoker,
            workspace_dir=str(workspace_dir) if workspace_dir else None,
            run_writer=self._meta_run_writer,
            triggered_by="resume",
            session_key=getattr(self, "_session_key", None),
            turn_id=getattr(self, "_turn_id", None),
            memory_persist_enabled=True,
            usage_tracker=self._usage_tracker,
        )

        result: Any = None
        final_text_parts: list[str] = []
        try:
            async for ev in orch.iter_resume_events(
                payload=claim,
                filled_fields=parsed,
            ):
                if isinstance(ev, MetaResult):
                    result = ev
                    continue
                # Stream nested AgentEvents through (TextDelta, ToolUseStart,
                # ToolResult). Capture text deltas so we can render the
                # final assistant text for the transcript / Done event.
                from opensquilla.engine.types import TextDeltaEvent
                if isinstance(ev, TextDeltaEvent) and ev.text:
                    final_text_parts.append(ev.text)
                yield ev
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent.meta_resume_failed", extra={"error": str(exc)})
            yield DoneEvent(text="", input_tokens=0, output_tokens=0, iterations=0)
            return

        # Build the final assistant text. If the DAG re-paused, use the
        # rendered form text; otherwise use the orchestrator's final_text.
        if result is not None:
            if result.paused:
                from opensquilla.engine.turn_runner.turn_finalizer_stage import (
                    render_paused_outcome,
                )
                final_text = render_paused_outcome(result)
            else:
                final_text = result.final_text or "".join(final_text_parts)
            # Emit one synthetic TextDelta for any text not already streamed
            # (re-pause path) so the transcript / surface sees it.
            already_streamed = "".join(final_text_parts)
            if final_text and final_text != already_streamed:
                from opensquilla.engine.types import TextDeltaEvent
                yield TextDeltaEvent(text=final_text)
        else:
            final_text = "".join(final_text_parts)

        yield DoneEvent(
            text=final_text,
            input_tokens=0,
            output_tokens=0,
            iterations=1,
            cost_usd=0.0,
            cost_source="none",
            model=self.config.model_id or "",
        )

    def _read_clarify_outcome(
        self, metadata: dict[str, Any],
    ) -> tuple[str, bool] | None:
        """Translate meta_resolution awaiting-branch metadata into the
        user-visible text dictated by spec §10.

        Returns ``(text, terminates)`` on hit, ``None`` when no clarify
        outcome is staged. Pops the consumed keys so the same turn can't
        re-handle them and a re-entry into ``_turn_generator`` won't
        echo a stale outcome.
        """
        # parse-failure (<3 strikes) — show error list + re-render form
        errors = metadata.pop("meta_clarify_errors", None)
        reprompt = metadata.pop("meta_clarify_reprompt", None)
        if errors and reprompt is not None:
            return self._render_clarify_errors(errors, reprompt), True

        cancelled = metadata.pop("meta_clarify_cancelled", None)
        reason = metadata.pop("meta_clarify_cancel_reason", "")
        if cancelled is not None:
            if reason == "parse_failure_limit":
                return "无法解析回复，已取消上一轮收集。", True
            return "好，已取消。", True

        expired = metadata.pop("meta_clarify_expired", None)
        if expired is not None:
            return "上一轮收集已超时，请重新发起。", True

        race_lost = metadata.pop("meta_clarify_race_lost", None)
        if race_lost is not None:
            return "你之前的回答已被处理。", True

        # Soft-clarify (free-form continuation) — pop the resolver's
        # progress markers so they don't accumulate, then return None
        # to let the turn flow through to the LLM normally. The model
        # responds based on the user's actual message plus the
        # webui's visible clarify form; we deliberately do NOT
        # template a reply here because the whole point of
        # soft-clarify is that the user is having a natural
        # conversation, not getting a form-style canned response.
        # A follow-up commit will inject a brief status hint into
        # the system prompt so the model knows what's still missing;
        # for now the visible form (Web) / CLI prompt is the source
        # of truth for "what's needed".
        metadata.pop("meta_clarify_soft_progress", None)
        metadata.pop("meta_clarify_proceed_blocked", None)

        return None

    def _render_clarify_errors(
        self, errors: Any, awaiting: Any,
    ) -> str:
        """Build the parse-error feedback block plus a re-rendered form.

        ``errors`` is the ``list[str]`` returned by ``parse_clarify_reply``;
        ``awaiting`` is the ``AwaitingPeek`` row whose ``awaiting_schema_json``
        is reused to render the form a second time.
        """
        from opensquilla.engine.turn_runner.turn_finalizer_stage import (
            _schema_language,
            render_paused_outcome,
        )
        from opensquilla.skills.meta.plan_serde import (
            clarify_config_from_jsonable,
        )
        from opensquilla.skills.meta.types import MetaPaused, MetaResult

        try:
            schema_payload = json.loads(awaiting.awaiting_schema_json or "{}")
            cfg = clarify_config_from_jsonable(schema_payload)
            language = _schema_language(cfg, cfg.intro)
            lines: list[str] = [
                "未能解析回复：" if language == "zh" else "I could not parse your reply:",
            ]
            for err in (errors or []):
                lines.append(f"  - {err}")
            synthetic = MetaResult(
                ok=False,
                paused=True,
                paused_payload=MetaPaused(
                    run_id=awaiting.run_id,
                    step_id=awaiting.step_id,
                    schema=cfg,
                    intro=cfg.intro,
                ),
            )
            form_text = render_paused_outcome(synthetic)
            if form_text:
                lines.append("")
                lines.append(form_text)
        except Exception:  # noqa: BLE001 — best-effort re-render
            lines = ["未能解析回复："]
            for err in (errors or []):
                lines.append(f"  - {err}")
            lines.append("")
            lines.append("请按上次的表单格式重新回答，或回 '取消' 终止。")
        return "\n".join(lines)

    async def _emit_terminal_text(
        self, text: str, *, iterations: int,
    ) -> AsyncIterator[Any]:
        """Yield ``TextDeltaEvent(text)`` + a minimal ``DoneEvent`` so the
        stream consumer + transcript treat this as a full assistant turn."""
        from opensquilla.engine.types import DoneEvent, TextDeltaEvent
        if text:
            yield TextDeltaEvent(text=text)
        yield DoneEvent(
            text=text,
            input_tokens=0,
            output_tokens=0,
            iterations=iterations,
            cost_usd=0.0,
            cost_source="none",
            model=self.config.model_id or "",
        )

    def _format_meta_invoke_failure(
        self,
        tc: ToolCall,
        result: Any,
        plan: Any,
    ) -> ToolResult:
        per_step_cap = 1200
        lines: list[str] = [
            f"Meta-skill `{getattr(plan, 'name', '?')}` failed at step "
            f"`{result.failed_step_id}`",
            "",
            f"Error: {result.error}",
            "",
            "Partial outputs:",
        ]
        for sid, text in (result.step_outputs or {}).items():
            if sid == result.failed_step_id:
                continue
            snippet = text if len(text) <= per_step_cap else text[:per_step_cap] + "..."
            lines.extend([f"- {sid}:", snippet, ""])
        lines.append(f"Original meta-skill requested: {tc.arguments.get('name', '')}")
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            tool_name="meta_invoke",
            content="\n".join(lines),
            is_error=True,
            terminates_turn=False,
        )

    # ------------------------------------------------------------------
    # Subagent factory
    # ------------------------------------------------------------------

    def _make_child_agent(self, spec: SubagentSpec, depth: int) -> Agent:
        from opensquilla.session.keys import parse_agent_id
        from opensquilla.tools.types import (
            SUBAGENT_TOOL_DENY,
            CallerKind,
            InteractionMode,
            ToolContext,
            current_tool_context,
        )

        parent_session_key = self._session_key or "unknown"
        subagent_label = spec.label or "subagent"

        # Schema-time filtering: subagents cannot see dangerous tools
        filtered_defs = [td for td in self.tool_definitions if td.name not in SUBAGENT_TOOL_DENY]
        subagent_ctx = ToolContext(
            is_owner=True,
            caller_kind=CallerKind.SUBAGENT,
            interaction_mode=InteractionMode.UNATTENDED,
            subagent_depth=depth,
            agent_id=parse_agent_id(parent_session_key),
            workspace_dir=spec.workspace_dir or self.config.workspace_dir,
            session_key=f"subagent:{parent_session_key}",
            channel_kind="subagent",
            channel_id=f"subagent:{parent_session_key}",
            sender_id=parent_session_key,
            denied_tools=set(SUBAGENT_TOOL_DENY),
            tool_run_budget_key=(
                f"subagent:{parent_session_key}:{subagent_label}:{depth}:{uuid.uuid4().hex}"
            ),
        )

        async def _subagent_tool_handler(tc: ToolCall) -> ToolResult:
            if self.tool_handler is None:
                return ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name=tc.tool_name,
                    content=f"No tool handler registered for tool '{tc.tool_name}'",
                    is_error=True,
                    execution_status=runtime_execution_status(
                        "error",
                        reason="runtime_error",
                    ),
                )
            token = current_tool_context.set(subagent_ctx)
            try:
                return await self.tool_handler(tc)
            finally:
                current_tool_context.reset(token)

        child_cfg = AgentConfig(
            max_iterations=spec.max_iterations,
            timeout=spec.timeout,
            max_tokens=self.config.max_tokens,
            max_turn_llm_calls=self.config.max_turn_llm_calls,
            max_turn_input_tokens=self.config.max_turn_input_tokens,
            max_turn_output_tokens=self.config.max_turn_output_tokens,
            max_turn_billed_cost_usd=self.config.max_turn_billed_cost_usd,
            max_turn_tool_errors=self.config.max_turn_tool_errors,
            length_capped_continuations=self.config.length_capped_continuations,
            context_window_tokens=self.config.context_window_tokens,
            workspace_dir=spec.workspace_dir or self.config.workspace_dir,
            flush_enabled=self.config.flush_enabled,
            flush_timeout_seconds=self.config.flush_timeout_seconds,
            flush_background_timeout_seconds=self.config.flush_background_timeout_seconds,
            flush_backoff_initial_seconds=self.config.flush_backoff_initial_seconds,
            flush_backoff_max_seconds=self.config.flush_backoff_max_seconds,
            flush_archive_max_bytes=self.config.flush_archive_max_bytes,
            flush_compaction_requires_safe_receipt=(
                self.config.flush_compaction_requires_safe_receipt
            ),
            flush_compaction_safety_mode=self.config.flush_compaction_safety_mode,
            tool_result_projection_max_inline_chars=(
                self.config.tool_result_projection_max_inline_chars
            ),
            tool_result_provider_request_max_chars=(
                self.config.tool_result_provider_request_max_chars
            ),
            provider_request_proof_max_chars=self.config.provider_request_proof_max_chars,
            tool_use_argument_provider_request_max_chars=(
                self.config.tool_use_argument_provider_request_max_chars
            ),
            tool_use_argument_projection_enabled=(self.config.tool_use_argument_projection_enabled),
            tool_failure_loop_block_threshold=(self.config.tool_failure_loop_block_threshold),
            max_safe_tool_concurrency=self.config.max_safe_tool_concurrency,
            tool_result_external_keep_recent=self.config.tool_result_external_keep_recent,
            tool_result_store_dir=self.config.tool_result_store_dir,
            tool_result_store_session_id=self.config.tool_result_store_session_id,
            tool_result_store_session_key=self.config.tool_result_store_session_key,
            tool_result_store_agent_id=self.config.tool_result_store_agent_id,
            tool_result_store_max_bytes=self.config.tool_result_store_max_bytes,
            tool_result_store_disk_budget_bytes=(self.config.tool_result_store_disk_budget_bytes),
            tool_result_store_retention_seconds=(self.config.tool_result_store_retention_seconds),
        )
        return Agent(
            provider=self.provider,
            config=child_cfg,
            tool_definitions=filtered_defs,
            tool_handler=_subagent_tool_handler,
            subagent_manager=SubagentManager(spawn_depth=depth),
        )

    async def spawn_subagent(self, spec: SubagentSpec) -> str:
        """Spawn a subagent and return its run_id."""
        handle = await self.subagent_manager.spawn(spec, self._make_child_agent)
        return handle.run_id
