from __future__ import annotations

import pytest

from opensquilla.session.manager import SessionManager
from opensquilla.session.openai_responses_state import (
    OPENAI_RESPONSES_COMPACTED_WINDOW_STATE_KIND,
    build_openai_responses_input_items,
    openai_responses_compacted_window_state,
)
from opensquilla.session.storage import SessionStorage


@pytest.mark.asyncio
async def test_openai_responses_compacted_window_state_persists_opaque_output() -> None:
    storage = SessionStorage(":memory:")
    await storage.connect()
    manager = SessionManager(storage, inject_time_prefix=False)
    node = await manager.create("agent:main:responses")
    compact_output = [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "retained item"}],
        },
        {
            "type": "reasoning",
            "encrypted_content": "opaque-encrypted-compaction-item",
            "summary": [{"type": "summary_text", "text": "do not parse"}],
        },
    ]

    state = openai_responses_compacted_window_state(
        session_id=node.session_id,
        session_key=node.session_key,
        model="gpt-5.5",
        compact_response={
            "id": "resp_compact",
            "output": compact_output,
            "usage": {"input_tokens": 120, "output_tokens": 30},
        },
        covered_through_id=42,
    )
    saved = await manager.save_context_state(state)
    loaded = await manager.get_context_states(
        node.session_key,
        provider="openai_responses",
        state_kind=OPENAI_RESPONSES_COMPACTED_WINDOW_STATE_KIND,
    )

    await storage.close()

    assert saved.portable is False
    assert saved.cacheable is False
    assert saved.provider == "openai_responses"
    assert saved.state_kind == OPENAI_RESPONSES_COMPACTED_WINDOW_STATE_KIND
    assert loaded[0].payload == {
        "response_id": "resp_compact",
        "output": compact_output,
        "usage": {"input_tokens": 120, "output_tokens": 30},
        "opaque": True,
    }
    assert loaded[0].covered_through_id == 42


def test_openai_responses_input_items_replay_latest_compacted_window_as_is() -> None:
    older_output = [{"type": "message", "role": "assistant", "content": "older"}]
    latest_output = [
        {"type": "message", "role": "assistant", "content": "retained"},
        {"type": "reasoning", "encrypted_content": "opaque-latest"},
    ]
    states = [
        openai_responses_compacted_window_state(
            session_id="s1",
            session_key="agent:main:responses",
            model="gpt-5.5",
            compact_response={"id": "old", "output": older_output},
            covered_through_id=10,
        ),
        openai_responses_compacted_window_state(
            session_id="s1",
            session_key="agent:main:responses",
            model="gpt-5.5",
            compact_response={"id": "new", "output": latest_output},
            covered_through_id=20,
        ),
    ]
    current_items = [{"type": "message", "role": "user", "content": "continue"}]

    replay_items = build_openai_responses_input_items(
        context_states=states,
        current_items=current_items,
    )

    assert replay_items == [*latest_output, *current_items]
    assert replay_items[: len(latest_output)] == latest_output


def test_openai_responses_input_items_prefers_latest_state_independent_of_input_order() -> None:
    older_output = [{"type": "message", "role": "assistant", "content": "older"}]
    latest_output = [
        {"type": "message", "role": "assistant", "content": "retained"},
        {"type": "reasoning", "encrypted_content": "opaque-latest"},
    ]
    older = openai_responses_compacted_window_state(
        session_id="s1",
        session_key="agent:main:responses",
        model="gpt-5.5",
        compact_response={"id": "old", "output": older_output},
        covered_through_id=10,
    )
    older.created_at = 1000
    latest = openai_responses_compacted_window_state(
        session_id="s1",
        session_key="agent:main:responses",
        model="gpt-5.5",
        compact_response={"id": "new", "output": latest_output},
        covered_through_id=20,
    )
    latest.created_at = 3000
    current_items = [{"type": "message", "role": "user", "content": "continue"}]

    replay_items = build_openai_responses_input_items(
        context_states=[latest, older],
        current_items=current_items,
    )

    assert replay_items == [*latest_output, *current_items]
