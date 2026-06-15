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


def test_transcript_entries_to_chat_messages_sanitizes_legacy_preflight_confirmation() -> None:
    entry = SimpleNamespace(
        id=43,
        message_id="m2",
        role="user",
        content=(
            "请帮我判断这份供应商续费材料：这个合同要不要签、拒绝还是谈判，并给我一份决策表。\n\n"
            "合同摘录：\n"
            "- 服务期：2026-07-01 到 2027-06-30\n\n"
            "Confirmed request fields:\n"
            "- audience: decision owner\n"
            "- decision_question: 签不签合同\n\n"
            "<!-- opensquilla:meta_preflight_confirmed=1 -->\n"
            "<!-- opensquilla:meta_preflight_run_id=01KTCSELFVALID123 -->"
        ),
        created_at="now",
        provenance_kind=None,
        provenance_source_session_key=None,
        provenance_source_tool=None,
        turn_usage=None,
        tool_calls=None,
    )

    messages = transcript_entries_to_chat_messages([entry])

    assert messages[0]["text"] == (
        "请帮我判断这份供应商续费材料：这个合同要不要签、拒绝还是谈判，并给我一份决策表。\n\n"
        "合同摘录：\n"
        "- 服务期：2026-07-01 到 2027-06-30"
    )
    assert "Confirmed request fields" not in messages[0]["text"]
    assert "opensquilla:meta_preflight" not in messages[0]["text"]


def test_transcript_entries_to_chat_messages_hides_marker_only_preflight_confirmation() -> None:
    entry = SimpleNamespace(
        id=45,
        message_id="m4",
        role="user",
        content=(
            "<!-- opensquilla:meta_preflight_confirmed=1 -->\n"
            "<!-- opensquilla:meta_preflight_run_id=01KTCMARKERONLY -->"
        ),
        created_at="now",
        provenance_kind=None,
        provenance_source_session_key=None,
        provenance_source_tool=None,
        turn_usage=None,
        tool_calls=None,
    )

    messages = transcript_entries_to_chat_messages([entry])

    assert messages[0]["text"] == ""


def test_transcript_entries_to_chat_messages_sanitizes_tool_call_preflight_payloads() -> None:
    entry = SimpleNamespace(
        id=44,
        message_id="m3",
        role="assistant",
        content="done",
        created_at="now",
        provenance_kind=None,
        provenance_source_session_key=None,
        provenance_source_tool=None,
        turn_usage=None,
        tool_calls=[
            {
                "name": "meta_user_input",
                "input": {
                    "clarify_skip_summary": {
                        "trigger_message": (
                            "请帮我判断这份供应商续费材料。\n\n"
                            "合同摘录：\n"
                            "- 价格：每月 $4,800\n\n"
                            "Confirmed request fields:\n"
                            "- audience: decision owner\n"
                            "- decision_question: 签不签合同\n\n"
                            "<!-- opensquilla:meta_preflight_confirmed=1 -->"
                        )
                    }
                },
            }
        ],
    )

    messages = transcript_entries_to_chat_messages([entry])

    trigger = messages[0]["tool_calls"][0]["input"]["clarify_skip_summary"][
        "trigger_message"
    ]
    assert trigger == (
        "请帮我判断这份供应商续费材料。\n\n"
        "合同摘录：\n"
        "- 价格：每月 $4,800"
    )
    assert "Confirmed request fields" not in trigger


def test_transcript_entries_to_chat_messages_keeps_plain_confirmed_fields_text() -> None:
    entry = SimpleNamespace(
        id=46,
        message_id="m5",
        role="assistant",
        content="done",
        created_at="now",
        provenance_kind=None,
        provenance_source_session_key=None,
        provenance_source_tool=None,
        turn_usage=None,
        tool_calls=[{"text": "Confirmed request fields:\n- this is a visible note"}],
    )

    messages = transcript_entries_to_chat_messages([entry])

    assert messages[0]["tool_calls"][0]["text"] == (
        "Confirmed request fields:\n- this is a visible note"
    )
