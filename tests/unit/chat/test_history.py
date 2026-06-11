from __future__ import annotations

from types import SimpleNamespace

from opensquilla.chat.history import transcript_entries_to_chat_messages


def test_transcript_entries_to_chat_messages_preserves_usage_and_artifacts() -> None:
    entry = SimpleNamespace(
        id=42,
        message_id="m1",
        role="assistant",
        content=(
            '{"text": "raw", "display_text": "shown", '
            '"artifacts": [{"id": "art-a1"}]}'
        ),
        created_at="now",
        provenance_kind=None,
        provenance_source_session_key=None,
        provenance_source_tool=None,
        turn_usage={"input_tokens": 1, "output_tokens": 2, "model": "openai/test"},
        tool_calls=None,
    )

    messages = transcript_entries_to_chat_messages([entry])

    assert messages[0]["id"] == "m1"
    assert messages[0]["text"] == "shown"
    assert messages[0]["transcript_id"] == 42
    assert messages[0]["artifacts"][0]["id"] == "art-a1"
    assert messages[0]["input_tokens"] == 1
    assert messages[0]["output_tokens"] == 2
    assert messages[0]["model"] == "openai/test"
    assert "reasoning_content" not in messages[0]


def _assistant_entry(**overrides: object) -> SimpleNamespace:
    entry = SimpleNamespace(
        id=7,
        message_id="m2",
        role="assistant",
        content="final answer",
        created_at="now",
        provenance_kind=None,
        provenance_source_session_key=None,
        provenance_source_tool=None,
        turn_usage=None,
        tool_calls=None,
    )
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def test_transcript_entries_to_chat_messages_carries_assistant_reasoning() -> None:
    entry = _assistant_entry(reasoning_content="Weighing both options first.")

    messages = transcript_entries_to_chat_messages([entry])

    assert messages[0]["reasoning_content"] == "Weighing both options first."


def test_transcript_entries_to_chat_messages_omits_blank_reasoning() -> None:
    entry = _assistant_entry(reasoning_content="   ")

    messages = transcript_entries_to_chat_messages([entry])

    assert "reasoning_content" not in messages[0]
