from __future__ import annotations

from types import SimpleNamespace

from opensquilla.chat.history import transcript_entries_to_chat_messages


def test_transcript_entries_to_chat_messages_preserves_usage_and_artifacts() -> None:
    entry = SimpleNamespace(
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
    assert messages[0]["artifacts"][0]["id"] == "art-a1"
    assert messages[0]["input_tokens"] == 1
    assert messages[0]["output_tokens"] == 2
    assert messages[0]["model"] == "openai/test"
