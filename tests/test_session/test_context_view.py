from __future__ import annotations

from opensquilla.provider import ContentBlockCompaction
from opensquilla.session.context_view import (
    build_compaction_context_items,
    build_compaction_context_records,
    build_provider_compaction_context,
)
from opensquilla.session.models import SessionContextState, SessionSummary


def test_provider_compaction_context_prefers_latest_state_independent_of_input_order() -> None:
    newer = SessionContextState(
        session_id="session",
        session_key="agent:main:ctx",
        provider="anthropic",
        model="claude-opus-4-7",
        state_kind="anthropic_compaction_block",
        payload={"content": "new native state"},
        covered_through_id=9,
        created_at=3000,
        portable=False,
        cacheable=True,
    )
    older = SessionContextState(
        session_id="session",
        session_key="agent:main:ctx",
        provider="anthropic",
        model="claude-opus-4-7",
        state_kind="anthropic_compaction_block",
        payload={"content": "old native state"},
        covered_through_id=7,
        created_at=1000,
        portable=False,
        cacheable=True,
    )

    context = build_provider_compaction_context(
        context_states=[newer, older],
        provider_kind="anthropic",
        now_ms=4000,
    )

    assert context.covered_through_ids == {9}
    assert len(context.messages) == 1
    block = context.messages[0].content[0]
    assert isinstance(block, ContentBlockCompaction)
    assert block.content == "new native state"


def test_compaction_context_items_deduplicate_structured_state_by_latest_coverage() -> None:
    newer = SessionContextState(
        session_id="session",
        session_key="agent:main:ctx",
        provider="portable",
        state_kind="structured_summary_v1",
        payload={
            "schema_version": 1,
            "current_status": "new structured state",
        },
        covered_through_id=7,
        created_at=3000,
        portable=True,
        cacheable=True,
    )
    older = SessionContextState(
        session_id="session",
        session_key="agent:main:ctx",
        provider="portable",
        state_kind="structured_summary_v1",
        payload={
            "schema_version": 1,
            "current_status": "old structured state",
        },
        covered_through_id=7,
        created_at=1000,
        portable=True,
        cacheable=True,
    )
    summary = SessionSummary(
        session_id="session",
        session_key="agent:main:ctx",
        summary_text="plain summary fallback",
        covered_through_id=7,
    )

    items = build_compaction_context_items(
        context_states=[newer, older],
        summaries=[summary],
        now_ms=4000,
    )

    rendered = "\n".join(items)
    assert "new structured state" in rendered
    assert "old structured state" not in rendered
    assert "plain summary fallback" not in rendered


def test_compaction_context_records_expose_correlation_metadata() -> None:
    state = SessionContextState(
        session_id="session",
        session_key="agent:main:ctx",
        provider="portable",
        state_kind="structured_summary_v1",
        payload={
            "schema_version": 1,
            "current_status": "structured state",
            "compaction_id": "cmp_state_1",
        },
        covered_through_id=9,
        portable=True,
        cacheable=True,
    )

    records = build_compaction_context_records(
        context_states=[state],
        summaries=[],
    )

    assert len(records) == 1
    assert records[0].compaction_id == "cmp_state_1"
    assert records[0].source == "context_state"
    assert records[0].covered_through_id == 9
