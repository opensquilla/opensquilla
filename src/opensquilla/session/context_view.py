"""Build provider-visible context views from durable session state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from opensquilla.provider.types import ContentBlockCompaction, Message
from opensquilla.session.compaction_state import (
    StructuredCompactionSummary,
    render_structured_summary,
)
from opensquilla.session.context_state_selection import (
    latest_context_state,
    latest_context_states_by_covered_through_id,
    ordered_context_states,
)
from opensquilla.session.models import SessionContextState, SessionSummary

_ANTHROPIC_COMPACTION_STATE_KIND = "anthropic_compaction_block"


@dataclass(frozen=True)
class ProviderCompactionContext:
    messages: list[Message]
    covered_through_ids: set[int]


@dataclass(frozen=True)
class CompactionContextItem:
    text: str
    compaction_id: str | None
    source: str
    covered_through_id: int


def _now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def _valid_structured_summary_state(
    state: SessionContextState,
    *,
    now_ms: int,
) -> bool:
    if not state.valid:
        return False
    if state.expires_at is not None and state.expires_at <= now_ms:
        return False
    return (
        state.provider == "portable"
        and state.state_kind == "structured_summary_v1"
        and state.portable
        and isinstance(state.payload, dict)
    )


def _valid_anthropic_compaction_state(
    state: SessionContextState,
    *,
    now_ms: int,
) -> bool:
    if not state.valid:
        return False
    if state.expires_at is not None and state.expires_at <= now_ms:
        return False
    content = state.payload.get("content") if isinstance(state.payload, dict) else None
    return (
        state.provider == "anthropic"
        and state.state_kind == _ANTHROPIC_COMPACTION_STATE_KIND
        and not state.portable
        and isinstance(content, str)
        and bool(content.strip())
    )


def build_provider_compaction_context(
    *,
    context_states: Sequence[SessionContextState],
    provider_kind: str,
    now_ms: int | None = None,
) -> ProviderCompactionContext:
    """Return provider-native compaction messages for compatible providers."""

    now = _now_ms() if now_ms is None else now_ms
    provider = provider_kind.strip().lower()
    messages: list[Message] = []
    covered_through_ids: set[int] = set()
    if provider != "anthropic":
        return ProviderCompactionContext(messages=messages, covered_through_ids=covered_through_ids)

    valid_states = [
        state for state in context_states if _valid_anthropic_compaction_state(state, now_ms=now)
    ]
    if not valid_states:
        return ProviderCompactionContext(messages=messages, covered_through_ids=covered_through_ids)

    state = latest_context_state(valid_states, provider="anthropic")
    if state is None:
        return ProviderCompactionContext(messages=messages, covered_through_ids=covered_through_ids)
    payload = state.payload
    cache_control = payload.get("cache_control")
    if not isinstance(cache_control, dict):
        cache_control = None
    messages.append(
        Message(
            role="assistant",
            content=[
                ContentBlockCompaction(
                    content=str(payload["content"]),
                    cache_control=cache_control,
                )
            ],
        )
    )
    covered_through_ids.add(state.covered_through_id)

    return ProviderCompactionContext(messages=messages, covered_through_ids=covered_through_ids)


def build_compaction_context_items(
    *,
    context_states: Sequence[SessionContextState],
    summaries: Sequence[SessionSummary],
    legacy_summary_markers: Sequence[str] = (),
    skip_covered_through_ids: set[int] | None = None,
    now_ms: int | None = None,
) -> list[str]:
    """Return stable compaction context blocks with summary_text fallback."""

    return [
        item.text
        for item in build_compaction_context_records(
            context_states=context_states,
            summaries=summaries,
            legacy_summary_markers=legacy_summary_markers,
            skip_covered_through_ids=skip_covered_through_ids,
            now_ms=now_ms,
        )
    ]


def build_compaction_context_records(
    *,
    context_states: Sequence[SessionContextState],
    summaries: Sequence[SessionSummary],
    legacy_summary_markers: Sequence[str] = (),
    skip_covered_through_ids: set[int] | None = None,
    now_ms: int | None = None,
) -> list[CompactionContextItem]:
    """Return stable compaction context blocks with correlation metadata."""

    now = _now_ms() if now_ms is None else now_ms
    items: list[CompactionContextItem] = []
    state_covered_ids: set[int] = set(skip_covered_through_ids or set())

    structured_states = [
        state
        for state in ordered_context_states(context_states)
        if _valid_structured_summary_state(state, now_ms=now)
    ]
    for state in latest_context_states_by_covered_through_id(structured_states):
        if state.covered_through_id in state_covered_ids:
            continue
        try:
            structured = StructuredCompactionSummary.model_validate(state.payload)
        except Exception:
            continue
        rendered = render_structured_summary(structured)
        if rendered.strip():
            compaction_id = None
            if isinstance(state.payload, dict):
                raw_compaction_id = state.payload.get("compaction_id")
                if isinstance(raw_compaction_id, str) and raw_compaction_id.strip():
                    compaction_id = raw_compaction_id.strip()
            items.append(
                CompactionContextItem(
                    text=rendered,
                    compaction_id=compaction_id,
                    source="context_state",
                    covered_through_id=state.covered_through_id,
                )
            )
            state_covered_ids.add(state.covered_through_id)

    for summary in summaries:
        if summary.covered_through_id in state_covered_ids:
            continue
        text = summary.summary_text.strip()
        if text:
            items.append(
                CompactionContextItem(
                    text=text,
                    compaction_id=summary.compaction_id,
                    source="summary",
                    covered_through_id=summary.covered_through_id,
                )
            )

    for marker in legacy_summary_markers:
        text = marker.strip()
        if text:
            items.append(
                CompactionContextItem(
                    text=text,
                    compaction_id=None,
                    source="legacy_marker",
                    covered_through_id=0,
                )
            )

    return items
