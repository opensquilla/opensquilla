"""Prompt-cache break detection for cache-relevant provider request state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from opensquilla.provider import ChatConfig, Message, ToolDefinition


def _jsonable(value: Any) -> Any:
    """Return a stable JSON-ish shape for Pydantic models and dataclasses."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _message_prefix_messages(messages: list[Message], *, tail_count: int = 2) -> list[Message]:
    if tail_count <= 0:
        return list(messages)
    return list(messages[:-tail_count])


def _message_prefix_payload(messages: list[Message], *, tail_count: int = 2) -> list[Any]:
    return [
        _jsonable(message) for message in _message_prefix_messages(messages, tail_count=tail_count)
    ]


def _message_prefix_item_kind(message: Message) -> str:
    content = message.content
    if isinstance(content, str):
        if content.startswith("[Request context for this turn]"):
            return "request_context"
        if content.startswith("[Runtime context for this turn]"):
            return "runtime_context"
        if content.startswith("[Available skills for this turn]"):
            return "skills_context"
    return "history"


def _cache_control_payload(config: ChatConfig) -> dict[str, Any]:
    return {
        "cache_breakpoints": config.cache_breakpoints,
        "cache_mode": config.cache_mode,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "stop_sequences": config.stop_sequences,
        "thinking": config.thinking,
        "thinking_budget_tokens": config.thinking_budget_tokens,
        "thinking_level": str(config.thinking_level) if config.thinking_level else None,
    }


@dataclass(frozen=True)
class PromptStateSnapshot:
    """Cache-relevant request inputs recorded immediately before a chat call."""

    system_hash: str
    tools_hash: str
    messages_prefix_hash: str
    cache_control_hash: str
    model: str
    message_count: int
    tool_count: int
    messages_prefix_item_hashes: tuple[str, ...] = ()
    messages_prefix_item_kinds: tuple[str, ...] = ()
    cache_control_field_hashes: tuple[tuple[str, str], ...] = ()

    def changed_fields(self, previous: PromptStateSnapshot) -> tuple[str, ...]:
        changed: list[str] = []
        for field_name in (
            "system_hash",
            "tools_hash",
            "messages_prefix_hash",
            "cache_control_hash",
            "model",
        ):
            if getattr(self, field_name) != getattr(previous, field_name):
                changed.append(field_name)
        return tuple(changed)

    def to_forensics(self) -> dict[str, Any]:
        return {
            "system_hash": self.system_hash,
            "tools_hash": self.tools_hash,
            "messages_prefix_hash": self.messages_prefix_hash,
            "messages_prefix_item_hashes": list(self.messages_prefix_item_hashes),
            "messages_prefix_item_kinds": list(self.messages_prefix_item_kinds),
            "cache_control_hash": self.cache_control_hash,
            "cache_control_field_hashes": dict(self.cache_control_field_hashes),
            "model": self.model,
            "message_count": self.message_count,
            "tool_count": self.tool_count,
        }


@dataclass(frozen=True)
class CacheBreakReport:
    """Result of comparing a provider DoneEvent with the previous cache baseline."""

    break_detected: bool
    reason: str
    changed_fields: tuple[str, ...] = ()
    previous_cache_read_tokens: int = 0
    current_cache_read_tokens: int = 0
    drop_tokens: int = 0
    drop_ratio: float = 0.0
    baseline_reset: bool = False
    previous_snapshot: PromptStateSnapshot | None = None
    current_snapshot: PromptStateSnapshot | None = None

    def to_log_dict(self) -> dict[str, Any]:
        payload = {
            "reason": self.reason,
            "changed_fields": list(self.changed_fields),
            "previous_cache_read_tokens": self.previous_cache_read_tokens,
            "current_cache_read_tokens": self.current_cache_read_tokens,
            "drop_tokens": self.drop_tokens,
            "drop_ratio": self.drop_ratio,
            "baseline_reset": self.baseline_reset,
        }
        if self.break_detected and self.previous_snapshot and self.current_snapshot:
            payload["forensics"] = {
                "previous": self.previous_snapshot.to_forensics(),
                "current": self.current_snapshot.to_forensics(),
            }
        return payload


@dataclass(frozen=True)
class _CacheBaseline:
    snapshot: PromptStateSnapshot
    cache_read_tokens: int


class CacheBreakMonitor:
    """Track cache-read drops and attribute them to prompt-state changes."""

    def __init__(self, *, min_drop_tokens: int = 2000, min_drop_ratio: float = 0.05) -> None:
        self._baselines: dict[str, _CacheBaseline] = {}
        self._reset_pending: set[str] = set()
        self._min_drop_tokens = max(0, int(min_drop_tokens))
        self._min_drop_ratio = max(0.0, float(min_drop_ratio))

    def record_prompt_state(
        self,
        *,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: ChatConfig,
        model: str,
    ) -> PromptStateSnapshot:
        messages_prefix_messages = _message_prefix_messages(messages)
        messages_prefix_payload = [_jsonable(message) for message in messages_prefix_messages]
        cache_control_payload = _cache_control_payload(config)
        return PromptStateSnapshot(
            system_hash=_stable_hash(config.system or ""),
            tools_hash=_stable_hash(tools or []),
            messages_prefix_hash=_stable_hash(messages_prefix_payload),
            cache_control_hash=_stable_hash(cache_control_payload),
            model=model,
            message_count=len(messages),
            tool_count=len(tools or []),
            messages_prefix_item_hashes=tuple(
                _stable_hash(message) for message in messages_prefix_payload
            ),
            messages_prefix_item_kinds=tuple(
                _message_prefix_item_kind(message) for message in messages_prefix_messages
            ),
            cache_control_field_hashes=tuple(
                (key, _stable_hash(value)) for key, value in sorted(cache_control_payload.items())
            ),
        )

    def check_response_for_cache_break(
        self,
        session_key: str,
        snapshot: PromptStateSnapshot,
        cache_read_tokens: int,
    ) -> CacheBreakReport:
        current_tokens = max(0, int(cache_read_tokens or 0))
        previous = self._baselines.get(session_key)
        reset_pending = session_key in self._reset_pending
        self._baselines[session_key] = _CacheBaseline(snapshot, current_tokens)
        if reset_pending:
            self._reset_pending.discard(session_key)
            return CacheBreakReport(
                break_detected=False,
                reason="baseline_reset_after_compaction",
                current_cache_read_tokens=current_tokens,
                baseline_reset=True,
            )
        if previous is None:
            return CacheBreakReport(
                break_detected=False,
                reason="baseline_initialized",
                current_cache_read_tokens=current_tokens,
            )

        drop_tokens = max(0, previous.cache_read_tokens - current_tokens)
        drop_ratio = drop_tokens / previous.cache_read_tokens if previous.cache_read_tokens else 0.0
        changed_fields = snapshot.changed_fields(previous.snapshot)
        break_detected = (
            bool(changed_fields)
            and drop_tokens >= self._min_drop_tokens
            and drop_ratio >= self._min_drop_ratio
        )
        return CacheBreakReport(
            break_detected=break_detected,
            reason="cache_read_drop" if break_detected else "cache_read_stable",
            changed_fields=changed_fields,
            previous_cache_read_tokens=previous.cache_read_tokens,
            current_cache_read_tokens=current_tokens,
            drop_tokens=drop_tokens,
            drop_ratio=round(drop_ratio, 4),
            previous_snapshot=previous.snapshot if break_detected else None,
            current_snapshot=snapshot if break_detected else None,
        )

    def notify_compaction(self, session_key: str) -> None:
        """Treat the next provider response for this session as a new baseline."""
        self._reset_pending.add(session_key)

    def clear(self) -> None:
        self._baselines.clear()
        self._reset_pending.clear()


default_cache_break_monitor = CacheBreakMonitor()

_CompactionListener = Callable[[str, dict[str, Any]], None]
_compaction_listeners: list[_CompactionListener] = []


def add_compaction_listener(listener: _CompactionListener) -> Callable[[], None]:
    """Register a best-effort listener for successful compaction events."""

    _compaction_listeners.append(listener)

    def remove() -> None:
        try:
            _compaction_listeners.remove(listener)
        except ValueError:
            pass

    return remove


def record_prompt_state(
    *,
    messages: list[Message],
    tools: list[ToolDefinition] | None,
    config: ChatConfig,
    model: str,
) -> PromptStateSnapshot:
    return default_cache_break_monitor.record_prompt_state(
        messages=messages,
        tools=tools,
        config=config,
        model=model,
    )


def check_response_for_cache_break(
    session_key: str,
    snapshot: PromptStateSnapshot,
    cache_read_tokens: int,
) -> CacheBreakReport:
    return default_cache_break_monitor.check_response_for_cache_break(
        session_key,
        snapshot,
        cache_read_tokens,
    )


def notify_compaction(
    session_key: str,
    *,
    notify_listeners: object = True,
    **payload: Any,
) -> None:
    event_payload = {
        "status": str(payload.pop("status", "completed") or "completed"),
        "source": str(payload.pop("source", "automatic") or "automatic"),
        **payload,
    }
    if event_payload["status"].lower() == "completed":
        default_cache_break_monitor.notify_compaction(session_key)
    if not bool(notify_listeners):
        return
    for listener in tuple(_compaction_listeners):
        try:
            listener(session_key, dict(event_payload))
        except Exception:
            pass
