"""Agent core — explicit state machine + tool loop.

Core loop is under 500 lines. No recursive calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import structlog

from opensquilla.artifacts import artifact_payload
from opensquilla.engine.cache_break_monitor import (
    check_response_for_cache_break,
    notify_compaction,
    record_prompt_state,
)
from opensquilla.engine.fallback import FallbackPolicy, backoff_sleep
from opensquilla.engine.history import limit_turns, repair_tool_pairing
from opensquilla.engine.session_sanitize import (
    sanitize_session_messages,
    session_payload_chars,
)
from opensquilla.engine.thinking import drop_reasoning
from opensquilla.engine.tool_text_compat import strip_synthetic_tool_call_suffix
from opensquilla.engine.tool_truncation import estimate_tokens as get_approx_tokens
from opensquilla.engine.tool_truncation import truncate_result
from opensquilla.observability.turn_call_log import TurnCallLogger
from opensquilla.provider import (
    ChatConfig,
    ContentBlockText,
    ContentBlockThinking,
    ContentBlockToolResult,
    ContentBlockToolUse,
    LLMProvider,
    Message,
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
from opensquilla.session.compaction import (
    CompactionConfig,
    CompactionRequest,
    build_compaction_config_from_provider,
    compact_context,
)
from opensquilla.tool_boundary import AgentToolHandler as ToolHandler

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


def _is_deepseek_model_id(model_id: str | None) -> bool:
    normalized = (model_id or "").strip().lower()
    return normalized.startswith("deepseek") or "/deepseek" in normalized


def _is_direct_deepseek_v4_model_id(model_id: str | None) -> bool:
    normalized = (model_id or "").strip().lower()
    return normalized in {"deepseek-v4-flash", "deepseek-v4-pro"}


_TOOL_RESULT_SUMMARY_SYSTEM = (
    "You compress tool output before it is passed to another agent. Preserve exact "
    "filenames, paths, ids, numbers, commands, error messages, and code-relevant snippets. "
    "Do not invent facts. Keep the same language as the tool output when possible. "
    "Return only the compressed tool result, with concise bullets when that helps."
)
_LARGE_JSON_TOOL_FIELD_KEYS: frozenset[str] = frozenset({"body", "body_base64"})
_LARGE_JSON_TOOL_FIELD_CHARS = 20_000


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


class _ProviderAttemptKind(StrEnum):
    OK = "ok"
    REASONING_ONLY = "reasoning_only"
    MALFORMED_EMPTY = "malformed_empty"
    INCOMPLETE_TOOLS = "incomplete_tools"
    STREAM_INCOMPLETE = "stream_incomplete"
    LENGTH_CAPPED = "length_capped"


class _IterationStreamTimeoutError(TimeoutError):
    """Raised when provider streaming exceeds the active Agent iteration budget."""


@dataclass(frozen=True)
class _ProviderAttemptClassification:
    kind: _ProviderAttemptKind
    stop_reason: str | None = None
    user_visible_emitted: bool = False


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
    if visible_text or tool_calls:
        return _ProviderAttemptClassification(
            _ProviderAttemptKind.OK,
            stop_reason=stop_reason,
            user_visible_emitted=user_visible_emitted,
        )
    if (stop_reason or "").lower() == "length":
        return _ProviderAttemptClassification(
            _ProviderAttemptKind.LENGTH_CAPPED,
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
        tool_result_summarizer_provider: LLMProvider | None = None,
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
        self._tool_result_summarizer_provider = tool_result_summarizer_provider
        self._pending_warnings: list[WarningEvent] = []

        self._state: AgentState = AgentState.IDLE
        self._history: list[Message] = []
        self._context: ContextAssembly | None = None
        self._memory_sync_manager: Any | None = None

        # Memory flush state (sub-agent based, re-entrant per compaction cycle)
        self._flush_done_this_cycle: bool = False
        self._active_flush_task: asyncio.Task | None = None
        self._flush_backoff_until: float = 0.0
        self._flush_backoff_seconds: float = 0.0
        self._session_flush_service = None  # set externally by runtime/gateway

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
    def _count_image_blocks(messages: list[Message]) -> int:
        count = 0
        for message in messages:
            if not isinstance(message.content, list):
                continue
            count += sum(1 for block in message.content if isinstance(block, ContentBlockImage))
        return count

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

    @staticmethod
    def _trim_summary_input(text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        head_chars = int(max_chars * 0.70)
        tail_chars = int(max_chars * 0.20)
        omitted = len(text) - head_chars - tail_chars
        marker = f"\n[...omitted {omitted} chars before summarization...]\n"
        return text[:head_chars] + marker + text[-tail_chars:]

    async def _summarize_tool_result(self, result: ToolResult) -> str | None:
        provider = self._tool_result_summarizer_provider
        if provider is None:
            return None

        summary_input = self._trim_summary_input(
            result.content,
            self.config.tool_result_compression_summary_input_max_chars,
        )
        prompt = (
            f"Tool name: {result.tool_name}\n"
            f"Original size: {len(result.content)} chars\n\n"
            "Compress this tool result for the next reasoning step. Preserve actionable "
            "details and any exact strings that may be needed later.\n\n"
            f"{summary_input}"
        )
        cfg = ChatConfig(
            max_tokens=self.config.tool_result_compression_summary_max_tokens,
            temperature=0,
            system=_TOOL_RESULT_SUMMARY_SYSTEM,
            timeout=self.config.tool_result_compression_summary_timeout_seconds,
        )
        parts: list[str] = []
        model = self.config.tool_result_compression_summary_model or self.config.model_id or ""
        try:
            async for event in provider.chat([Message(role="user", content=prompt)], config=cfg):
                if isinstance(event, ProviderTextDelta):
                    parts.append(event.text)
                elif isinstance(event, ProviderErrorEvent):
                    raise RuntimeError(event.message)
                elif isinstance(event, ProviderDoneEvent) and not model:
                    model = event.model
        except Exception as exc:  # noqa: BLE001 - compression is best-effort
            model_label = model or self.config.tool_result_compression_summary_model or "default"
            message = str(exc)
            logger.warning(
                "tool_result_summary_failed",
                tool=result.tool_name,
                model=model_label,
                error=message,
            )
            self.config.tool_result_compression_enabled = False
            self.config.tool_result_compression_mode = "off"
            self._pending_warnings.append(
                WarningEvent(
                    code="tool_result_summary_failed",
                    message=(
                        f"Tool result summary model {model_label!r} failed: {message}. "
                        "Falling back to truncation for this result."
                    ),
                )
            )
            return None

        summary = "".join(parts).strip()
        if not summary:
            return None

        header_model = f" via {model}" if model else ""
        compressed = (
            f"[Tool result summarized{header_model}: {len(result.content)} chars -> "
            f"{len(summary)} chars]\n{summary}"
        )
        return truncate_result(
            compressed,
            self.config.context_window_tokens,
            max_share=self.config.tool_result_compression_max_share,
        )

    async def _compress_tool_result(self, result: ToolResult) -> ToolResult:
        guarded_content, guarded = _omit_large_json_tool_fields(result.content)
        if guarded:
            result = ToolResult(
                tool_use_id=result.tool_use_id,
                tool_name=result.tool_name,
                content=guarded_content,
                is_error=result.is_error,
                artifacts=list(result.artifacts),
            )
            self.config.metadata["tool_json_guard_applied"] = True
            self.config.metadata["tool_json_guard_calls"] = (
                self.config.metadata.get("tool_json_guard_calls", 0) + 1
            )

        mode = self._tool_result_compression_mode()
        if mode == "off" or not self._tool_result_over_budget(result.content):
            return result

        compressed_content: str | None = None
        applied_mode = mode
        if mode == "summarize":
            compressed_content = await self._summarize_tool_result(result)
            if compressed_content is None:
                applied_mode = "truncate"

        if compressed_content is None:
            compressed_content = truncate_result(
                result.content,
                self.config.context_window_tokens,
                max_share=self.config.tool_result_compression_max_share,
            )

        tokens_before = get_approx_tokens(result.content)
        tokens_after = get_approx_tokens(compressed_content)
        self.config.metadata["tool_compression_applied"] = True
        self.config.metadata["tool_compression_calls"] = (
            self.config.metadata.get("tool_compression_calls", 0) + 1
        )
        self.config.metadata["tool_compression_tokens_before"] = (
            self.config.metadata.get("tool_compression_tokens_before", 0) + tokens_before
        )
        self.config.metadata["tool_compression_tokens_after"] = (
            self.config.metadata.get("tool_compression_tokens_after", 0) + tokens_after
        )
        self.config.metadata["tool_compression_tokens_saved"] = (
            self.config.metadata.get("tool_compression_tokens_saved", 0)
            + max(0, tokens_before - tokens_after)
        )

        self._write_turn_call_log(
            "tool_response_compression",
            tool_use_id=result.tool_use_id,
            name=result.tool_name,
            mode=applied_mode,
            original_chars=len(result.content),
            compressed_chars=len(compressed_content),
        )
        return ToolResult(
            tool_use_id=result.tool_use_id,
            tool_name=result.tool_name,
            content=compressed_content,
            is_error=result.is_error,
            artifacts=list(result.artifacts),
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

        Explicit state machine — no recursion. Tool loop iterates up to
        config.max_iterations times.
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
        # ------ IDLE → THINKING ------
        yield self._transition(AgentState.THINKING)

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
        loaded_history = list(self._history)
        self._write_context_stage("session:loaded", loaded_history)
        sanitized_history, sanitize_result = sanitize_session_messages(loaded_history)
        sanitized_history = repair_tool_pairing(sanitized_history)
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
        request_context_insert_index = len(turn_messages)
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
        request_context_message = self._request_context_message(
            self.config.request_context_prompt
        )
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
        last_actual_model = ""
        terminal_error: ErrorEvent | None = None
        window_input_tokens = 0
        window_output_tokens = 0
        final_text_parts: list[str] = []
        final_reasoning_parts: list[str] = []
        _fallback = FallbackPolicy(
            max_retries=self.config.max_provider_retries,
            base_backoff_ms=self.config.retry_base_backoff_ms,
            max_backoff_ms=self.config.retry_max_backoff_ms,
        )

        # Deadline-based timeouts: optional total turn budget + per-iteration budget
        _loop = asyncio.get_running_loop()
        _total_deadline = _loop.time() + self.config.timeout if self.config.timeout > 0 else None
        tools_supported = True
        if self.config.model_capabilities is not None:
            tools_supported = bool(getattr(self.config.model_capabilities, "supports_tools", True))
        provider_tool_definitions = self.tool_definitions or None
        if not tools_supported:
            provider_tool_definitions = None

        try:
            while True:
                if iterations >= self.config.max_iterations:
                    yield self._transition(AgentState.ERROR)
                    terminal_error = ErrorEvent(
                        message=(
                            f"Reached max_iterations={self.config.max_iterations}. "
                            "Increase --max-iterations or "
                            "OPENSQUILLA_AGENT_MAX_ITERATIONS for longer tasks."
                        ),
                        code="max_iterations",
                    )
                    yield terminal_error
                    break

                # Check total turn deadline (if configured)
                if _total_deadline is not None and _loop.time() > _total_deadline:
                    raise TimeoutError(f"Agent total timeout after {self.config.timeout}s")

                iterations += 1
                _iter_deadline = _loop.time() + self.config.iteration_timeout

                # ------ THINKING → STREAMING ------
                yield self._transition(AgentState.STREAMING)

                # Collect this LLM response
                assistant_text_parts: list[str] = []
                tool_calls: list[ToolCall] = []
                pending_tools: dict[str, _StreamAccumulator] = {}
                iter_input_tokens = 0
                iter_output_tokens = 0
                iter_reasoning_tokens = 0
                iter_reasoning_content: str | None = None
                iter_thinking_signature: str | None = None
                provider_error: ProviderErrorEvent | None = None

                _retry_attempt = 0
                _call_attempt = 0
                _reasoning_only_retry_done = False
                _malformed_empty_retry_done = False
                _stream_incomplete_retry_done = False
                _invalid_response_fallback_done = False
                while _retry_attempt <= _fallback.max_retries:
                    provider_error = None
                    assistant_text_parts = []
                    tool_calls = []
                    pending_tools = {}
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
                    request_source_messages = self._with_request_context_messages(
                        turn_messages,
                        request_context_message,
                        request_context_insert_index,
                        runtime_context_message,
                        runtime_context_insert_index,
                    )
                    request_messages, request_sanitize_result = sanitize_session_messages(
                        request_source_messages
                    )
                    self._write_context_stage(
                        "stream:context",
                        request_messages,
                        call_id=call_id,
                        iteration=iterations,
                        attempt=_call_attempt,
                        sanitize=request_sanitize_result,
                    )

                    self._write_turn_call_log(
                        "llm_request",
                        call_id=call_id,
                        iteration=iterations,
                        attempt=_call_attempt,
                        messages=request_messages,
                        tools=provider_tool_definitions,
                        config=chat_cfg,
                    )
                    cache_prompt_snapshot = None
                    if self._session_key:
                        cache_prompt_snapshot = record_prompt_state(
                            messages=request_messages,
                            tools=provider_tool_definitions,
                            config=chat_cfg,
                            model=self.config.model_id or "",
                        )

                    _got_done_event = False
                    attempt_user_visible_emitted = False
                    try:
                        raw_stream = self.provider.chat(
                            request_messages,
                            tools=provider_tool_definitions,
                            config=chat_cfg,
                        )
                        async for raw_ev in self._stream_provider_events_with_deadline(
                            raw_stream,
                            loop=_loop,
                            iter_deadline=_iter_deadline,
                            total_deadline=_total_deadline,
                        ):
                            if isinstance(raw_ev, ProviderTextDelta):
                                assistant_text_parts.append(raw_ev.text)
                                if raw_ev.text:
                                    attempt_user_visible_emitted = True
                                yield TextDeltaEvent(text=raw_ev.text)

                            elif isinstance(raw_ev, ProviderToolUseStart):
                                if not tools_supported:
                                    continue
                                pending_tools[raw_ev.tool_use_id] = _StreamAccumulator(
                                    tool_use_id=raw_ev.tool_use_id,
                                    tool_name=raw_ev.tool_name,
                                    synthetic_from_text=raw_ev.synthetic_from_text,
                                )
                                attempt_user_visible_emitted = True
                                yield ToolUseStartEvent(
                                    tool_use_id=raw_ev.tool_use_id,
                                    tool_name=raw_ev.tool_name,
                                    synthetic_from_text=raw_ev.synthetic_from_text,
                                )

                            elif raw_ev.kind == "tool_use_delta":
                                if not tools_supported:
                                    continue
                                acc = pending_tools.get(raw_ev.tool_use_id)  # type: ignore[union-attr]
                                if acc:
                                    acc.json_buf.append(raw_ev.json_fragment)  # type: ignore[union-attr]

                            elif isinstance(raw_ev, ToolUseEndEvent):
                                if not tools_supported:
                                    continue
                                acc = pending_tools.pop(raw_ev.tool_use_id, None)
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
                                    self._usage_tracker.add(
                                        self._session_key,
                                        input_tokens=raw_ev.input_tokens,
                                        output_tokens=raw_ev.output_tokens,
                                        model_id=raw_ev.model or self.config.model_id or "",
                                        cache_read_tokens=raw_ev.cached_tokens,
                                        cache_write_tokens=raw_ev.cache_write_tokens,
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
                    except _IterationStreamTimeoutError:
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
                    response_text = "".join(assistant_text_parts)
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

                        if (
                            attempt_classification.kind == _ProviderAttemptKind.REASONING_ONLY
                            and thinking_enabled
                            and not _reasoning_only_retry_done
                            and _fallback.max_retries > 0
                        ):
                            _reasoning_only_retry_done = True
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
                            and not _malformed_empty_retry_done
                            and _fallback.max_retries > 0
                        ):
                            _malformed_empty_retry_done = True
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
                            attempt_classification.kind
                            == _ProviderAttemptKind.STREAM_INCOMPLETE
                            and not attempt_classification.user_visible_emitted
                            and not _stream_incomplete_retry_done
                            and _fallback.max_retries > 0
                        ):
                            _stream_incomplete_retry_done = True
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
                            yield WarningEvent(
                                code="provider_output_truncated",
                                message=(
                                    "The provider stopped because the output limit was reached."
                                ),
                            )
                            terminal_error = ErrorEvent(
                                message="Provider stopped before producing visible content",
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
                        failure_kind = classify_provider_error(
                            provider_name=getattr(self.provider, "provider_name", ""),
                            status_code=(
                                int(provider_error.code)
                                if str(provider_error.code).isdigit()
                                else None
                            ),
                            raw_code=provider_error.code,
                            message=provider_error.message,
                        )
                        kind = _fallback.classify_error(
                            provider_error.message,
                        )
                        if failure_kind == ProviderFailureKind.CONTEXT_OVERFLOW:
                            if overflow_retries >= self.config.max_overflow_retries:
                                yield self._transition(AgentState.ERROR)
                                terminal_error = ErrorEvent(
                                    message="Context overflow persists after compaction",
                                    code="compaction_exhausted",
                                )
                                yield terminal_error
                                break
                            overflow_retries += 1
                            overflow_outcome = await self._check_context_overflow(
                                turn_messages,
                                self.config.context_window_tokens + 1,
                                request_context_insert_index=request_context_insert_index,
                                runtime_context_insert_index=runtime_context_insert_index,
                            )
                            if overflow_outcome is None:
                                yield self._transition(AgentState.ERROR)
                                terminal_error = ErrorEvent(
                                    message="Context overflow persists after compaction",
                                    code="compaction_exhausted",
                                )
                                yield terminal_error
                                break
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
                                terminal_error = ErrorEvent(
                                    message="Context overflow persists after compaction",
                                    code="compaction_exhausted",
                                )
                                yield terminal_error
                                break
                            turn_messages = overflow_outcome.messages
                            request_context_insert_index = next_request_context_insert_index
                            runtime_context_insert_index = next_runtime_context_insert_index
                            yield CompactionEvent(
                                summary=overflow_outcome.summary,
                                kept_entries=overflow_outcome.kept_entries,
                                kept_count=len(overflow_outcome.messages),
                                removed_count=overflow_outcome.removed_count,
                            )
                            if self._session_key:
                                notify_compaction(self._session_key)
                            window_input_tokens = 0
                            window_output_tokens = 0
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
                            message="Provider stopped before producing visible content",
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

                window_input_tokens += iter_input_tokens
                window_output_tokens += iter_output_tokens

                # Per-iteration deadline check after LLM streaming
                if _loop.time() > _iter_deadline:
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

                # Check overflow against the current post-compaction window,
                # not lifetime usage for the whole turn.
                overflow_outcome = await self._check_context_overflow(
                    turn_messages,
                    window_input_tokens + window_output_tokens,
                    request_context_insert_index=request_context_insert_index,
                    runtime_context_insert_index=runtime_context_insert_index,
                )
                if overflow_outcome is None:
                    if overflow_retries >= self.config.max_overflow_retries:
                        yield self._transition(AgentState.ERROR)
                        terminal_error = ErrorEvent(
                            message="Context overflow persists after compaction",
                            code="compaction_exhausted",
                        )
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
                    # Compaction happened — replace message list and reset only
                    # the live-window gauge. Lifetime counters keep feeding
                    # DoneEvent usage/cost accounting for this turn.
                    turn_messages = overflow_outcome.messages
                    if overflow_outcome.request_context_insert_index is not None:
                        request_context_insert_index = (
                            overflow_outcome.request_context_insert_index
                        )
                    if overflow_outcome.runtime_context_insert_index is not None:
                        runtime_context_insert_index = overflow_outcome.runtime_context_insert_index
                    yield CompactionEvent(
                        summary=overflow_outcome.summary,
                        kept_entries=overflow_outcome.kept_entries,
                        kept_count=len(overflow_outcome.messages),
                        removed_count=overflow_outcome.removed_count,
                    )
                    if self._session_key:
                        notify_compaction(self._session_key)
                    window_input_tokens = 0
                    window_output_tokens = 0
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
                    )

                assembled_text = "".join(assistant_text_parts)
                visible_text = strip_synthetic_tool_call_suffix(
                    assembled_text,
                    [tc.tool_name for tc in tool_calls if tc.synthetic_from_text],
                )
                if visible_text:
                    final_text_parts.append(visible_text)

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
                    break

                # Per-iteration deadline check before tool execution
                if _loop.time() > _iter_deadline:
                    yield self._transition(AgentState.ERROR)
                    terminal_error = ErrorEvent(
                        message=(
                            f"Iteration {iterations} exceeded iteration_timeout"
                            f" ({self.config.iteration_timeout}s) before tool execution"
                        ),
                        code="iteration_timeout",
                    )
                    yield terminal_error
                    break

                # ------ STREAMING → TOOL_CALLING ------
                yield self._transition(AgentState.TOOL_CALLING)

                # Execute tools and collect results.
                # Safe tools (named in _SAFE_TOOL_NAMES) run concurrently via
                # asyncio.gather; mutex tools run serially. Results are emitted
                # in the original tool_calls arrival order regardless of
                # completion order.
                from opensquilla.engine.runtime import _SAFE_TOOL_NAMES  # noqa: PLC0415

                tool_result_blocks: list[ContentBlockToolResult] = []
                executed_results: list[ToolResult] = []
                turn_yielded = False

                # Map tool_use_id -> ToolResult built up below.
                results_by_id: dict[str, ToolResult] = {}

                async def _run_one(tc: ToolCall) -> ToolResult:
                    started = time.monotonic()
                    self._write_turn_call_log(
                        "tool_request",
                        iteration=iterations,
                        tool_use_id=tc.tool_use_id,
                        name=tc.tool_name,
                        arguments=tc.arguments,
                    )
                    tool_timeout = self._tool_execution_timeout(tc)
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

                # Dispatch preserving original order: accumulate consecutive safe
                # tools into a batch and flush with asyncio.gather before each
                # mutex tool, then run the mutex tool serially.  This ensures
                # that a safe tool appearing after a mutex tool cannot start
                # until that mutex tool has completed.
                safe_batch: list[ToolCall] = []

                async def _flush_safe_batch(batch: list[ToolCall]) -> None:
                    if not batch:
                        return
                    gather_results = await asyncio.gather(
                        *[_run_one(tc) for tc in batch], return_exceptions=True
                    )
                    for tc, outcome in zip(batch, gather_results):
                        if isinstance(outcome, BaseException):
                            outcome = ToolResult(
                                tool_use_id=tc.tool_use_id,
                                tool_name=tc.tool_name,
                                content=f"Tool '{tc.tool_name}' raised: {outcome}",
                                is_error=True,
                            )
                        results_by_id[tc.tool_use_id] = outcome

                for tc in tool_calls:
                    if tc.tool_name in _SAFE_TOOL_NAMES:
                        safe_batch.append(tc)
                    else:
                        await _flush_safe_batch(safe_batch)
                        safe_batch = []
                        results_by_id[tc.tool_use_id] = await _run_one(tc)

                await _flush_safe_batch(safe_batch)

                # Emit results in original tool_calls order.
                for tc in tool_calls:
                    result = await self._compress_tool_result(
                        results_by_id[tc.tool_use_id]
                    )
                    executed_results.append(result)
                    for artifact in result.artifacts:
                        yield ArtifactEvent(**_artifact_event_kwargs(artifact))
                    yield ToolResultEvent(
                        tool_use_id=result.tool_use_id,
                        tool_name=result.tool_name,
                        result=result.content,
                        is_error=result.is_error,
                        arguments=tc.arguments,
                    )
                    while self._pending_warnings:
                        yield self._pending_warnings.pop(0)
                    if self._is_turn_yield_result(result):
                        turn_yielded = True
                    tool_result_blocks.append(
                        ContentBlockToolResult(
                            tool_use_id=result.tool_use_id,
                            content=result.content,
                            is_error=result.is_error,
                        )
                    )

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
                if _loop.time() > _iter_deadline:
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
                if turn_yielded:
                    break

                # ------ TOOL_CALLING → THINKING ------
                yield self._transition(AgentState.THINKING)
                # Loop continues

        except TimeoutError:
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

        has_usage = bool(
            total_input_tokens
            or total_output_tokens
            or total_reasoning_tokens
            or total_cached_tokens
            or total_cache_write_tokens
            or total_billed_cost
        )
        if terminal_error is None or has_usage:
            if terminal_error is None:
                yield self._transition(AgentState.DONE)
            yield DoneEvent(
                text="".join(final_text_parts),
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                reasoning_tokens=total_reasoning_tokens,
                cached_tokens=total_cached_tokens,
                cache_write_tokens=total_cache_write_tokens,
                iterations=iterations,
                cost_usd=done_cost,
                billed_cost=total_billed_cost,
                cost_source=cost_source,
                model=done_model,
                runtime_context_hash=runtime_context_hash,
                runtime_context_chars=len(runtime_context),
                reasoning_content=(
                    "\n".join(final_reasoning_parts) if final_reasoning_parts else None
                ),
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
        iter_deadline: float,
        total_deadline: float | None,
    ) -> AsyncIterator[Any]:
        stream_iter = stream.__aiter__()
        while True:
            remaining_iter = iter_deadline - loop.time()
            if remaining_iter <= 0:
                await self._close_provider_stream(stream_iter)
                raise _IterationStreamTimeoutError

            wait_budget = remaining_iter
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
                await self._close_provider_stream(stream_iter)
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
        source_messages = self._with_request_context_messages(
            messages,
            request_context_message,
            request_context_insert_index,
            runtime_context_message,
            runtime_context_insert_index,
        )
        request_messages, _ = sanitize_session_messages(source_messages)
        return request_messages

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
        result.insert(runtime_idx, runtime_context_message)
        return result

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

    def _build_compaction_config(self) -> CompactionConfig:
        return build_compaction_config_from_provider(
            self.provider,
            default_model=self.config.model_id,
        )

    async def _check_context_overflow(
        self,
        messages: list[Message],
        total_tokens: int,
        *,
        request_context_insert_index: int | None = None,
        runtime_context_insert_index: int | None = None,
    ) -> CompactionOutcome | None:
        """Check if total tokens exceed the overflow threshold.

        Uses sub-agent flush instead of prompt injection.
        The flush is re-entrant: it can trigger on every approach to threshold.
        """
        threshold = self.config.context_overflow_threshold * self.config.context_window_tokens
        if total_tokens <= threshold:
            return CompactionOutcome(
                messages=messages,
                request_context_insert_index=request_context_insert_index,
                runtime_context_insert_index=runtime_context_insert_index,
            )

        # --- Pre-compaction flush via direct Agent (best-effort, concurrent) ---
        flush_task: asyncio.Task | None = None
        self._consume_completed_flush_task()

        async def _await_flush_task() -> None:
            # Give flush a grace period to complete instead of cancelling immediately.
            # Adds up to flush_timeout_seconds (default 5s) of latency, but without
            # this the flush is effectively dead code (always cancelled before finishing).
            if flush_task is not None and not flush_task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(flush_task),
                        timeout=self.config.flush_timeout_seconds,
                    )
                    logger.info("memory_flush.completed_after_compaction")
                    self._mark_flush_task_completed(flush_task)
                except TimeoutError:
                    next_retry_seconds = self._record_flush_timeout_backoff()
                    logger.warning(
                        "memory_flush.timed_out",
                        timeout_seconds=self.config.flush_timeout_seconds,
                        next_retry_seconds=next_retry_seconds,
                    )
                except Exception as exc:
                    logger.warning("memory_flush.await_failed", error=str(exc))
                    self._mark_flush_task_completed(flush_task)

        if not self._flush_done_this_cycle and self.config.flush_enabled:
            try:
                from opensquilla.memory.flush import (
                    resolve_flush_plan,
                    should_flush,
                )

                now = time.monotonic()
                if self._active_flush_task is not None and not self._active_flush_task.done():
                    logger.debug("memory_flush.skipped", reason="already_running")
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
                        total_tokens=total_tokens,
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
                            total_tokens=total_tokens,
                            threshold=int(threshold),
                        )
                        flush_task = asyncio.create_task(self._run_flush(plan, list(messages)))
                        flush_task.add_done_callback(self._on_flush_task_done)
                        self._active_flush_task = flush_task
                        self._flush_done_this_cycle = True
            except Exception:
                logger.debug("memory_flush.skipped", reason="flush module unavailable")

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
            context_window_tokens=self.config.context_window_tokens,
            config=self._build_compaction_config(),
        )

        try:
            result = await compact_context(request)
        except Exception:  # noqa: BLE001
            return None  # signal failure

        # Removing history without a replacement summary is equivalent to
        # bare truncation; reject it so the caller takes the existing
        # compaction failure path instead of silently dropping context.
        if result.removed_count > 0 and not result.summary:
            logger.warning(
                "compaction.empty_summary_rejected",
                removed_count=result.removed_count,
                kept_count=len(result.kept_entries),
            )
            return None

        has_structured_content = any(not isinstance(m.content, str) for m in messages)
        if result.removed_count == 0 and not result.summary and has_structured_content:
            await _await_flush_task()
            self._flush_done_this_cycle = False
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
        if self._active_flush_task is not task:
            return
        try:
            task.result()
        except asyncio.CancelledError:
            logger.debug("memory_flush.cancelled")
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_flush.background_failed", error=str(exc))
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
    ) -> None:
        """Fire-and-forget memory flush; delegates to SessionFlushService.

        When a ``SessionFlushService`` is injected (post-PR2a), this method
        just forwards the call and drops the receipt. When no service is
        injected (standalone Agent instances in unit tests or legacy paths),
        falls back to an inline raw-dump so we don't silently drop data.
        """
        service = getattr(self, "_session_flush_service", None)
        if service is not None:
            try:
                from opensquilla.session.keys import parse_agent_id

                sk = getattr(self, "_session_key", None) or "agent:main:legacy"
                await service.execute(
                    messages,
                    session_key=sk,
                    agent_id=parse_agent_id(sk),
                    message_window=0,
                    segment_mode="auto",
                )
            except asyncio.CancelledError:
                logger.debug("memory_flush.cancelled")
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("memory_flush.service_failed", error=str(exc))
            return

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

    async def _execute_tool(self, tc: ToolCall) -> ToolResult:
        """Dispatch a tool call to the registered handler."""
        if self.tool_handler is None:
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                tool_name=tc.tool_name,
                content=f"No tool handler registered for tool '{tc.tool_name}'",
                is_error=True,
            )
        try:
            return await self.tool_handler(tc)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                tool_name=tc.tool_name,
                content=f"Tool '{tc.tool_name}' raised: {exc}",
                is_error=True,
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
        )

        async def _subagent_tool_handler(tc: ToolCall) -> ToolResult:
            if self.tool_handler is None:
                return ToolResult(
                    tool_use_id=tc.tool_use_id,
                    tool_name=tc.tool_name,
                    content=f"No tool handler registered for tool '{tc.tool_name}'",
                    is_error=True,
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
            context_window_tokens=self.config.context_window_tokens,
            workspace_dir=spec.workspace_dir or self.config.workspace_dir,
            tool_result_compression_enabled=self.config.tool_result_compression_enabled,
            tool_result_compression_mode=self.config.tool_result_compression_mode,
            tool_result_compression_max_share=self.config.tool_result_compression_max_share,
            tool_result_compression_summary_model=(
                self.config.tool_result_compression_summary_model
            ),
            tool_result_compression_summary_max_tokens=(
                self.config.tool_result_compression_summary_max_tokens
            ),
            tool_result_compression_summary_timeout_seconds=(
                self.config.tool_result_compression_summary_timeout_seconds
            ),
            tool_result_compression_summary_input_max_chars=(
                self.config.tool_result_compression_summary_input_max_chars
            ),
        )
        return Agent(
            provider=self.provider,
            config=child_cfg,
            tool_definitions=filtered_defs,
            tool_handler=_subagent_tool_handler,
            subagent_manager=SubagentManager(spawn_depth=depth),
            tool_result_summarizer_provider=self._tool_result_summarizer_provider,
        )

    async def spawn_subagent(self, spec: SubagentSpec) -> str:
        """Spawn a subagent and return its run_id."""
        handle = await self.subagent_manager.spawn(spec, self._make_child_agent)
        return handle.run_id
