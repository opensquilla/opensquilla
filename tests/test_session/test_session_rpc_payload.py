from __future__ import annotations

from types import SimpleNamespace

from opensquilla.session.rpc_payload import (
    messages_subscribe_response,
    normalize_terminal_event_payload,
    session_create_response,
    session_create_stub_response,
    session_list_row,
    session_preview_last_message,
    session_preview_row,
    session_resolve_response,
    task_state_summary,
)


def test_session_list_row_preserves_source_metadata_and_task_state() -> None:
    session = SimpleNamespace(
        session_key="agent:main:webchat:abc123",
        agent_id="main",
        status="running",
        model="gpt-test",
        updated_at=2000,
        display_name="WebChat",
        channel=None,
        chat_type="direct",
        group_id=None,
        subject=None,
        last_channel="slack",
        last_to="C123",
        last_account_id="acct-1",
        last_thread_id="1700.1",
        delivery_context={"channel_id": "C123"},
        parent_session_key=None,
        spawned_by=None,
        origin=None,
    )
    task = SimpleNamespace(
        task_id="task-1",
        status="running",
        queue_mode="followup",
        run_kind="web_turn",
        source_kind="webui",
        created_at=100,
        started_at=110,
        finished_at=None,
        terminal_reason=None,
    )

    row = session_list_row(session, entry_count=3, task_rows=[task], now_ms=9999)

    assert row["key"] == "agent:main:webchat:abc123"
    assert row["message_count"] == 3
    assert row["entry_count"] == 3
    assert row["source_kind"] == "webui"
    assert row["channel_kind"] == "slack"
    assert row["deliveryContext"] == {"channel_id": "C123"}
    assert row["tasks"][0]["task_id"] == "task-1"
    assert row["active_task"]["task_id"] == "task-1"
    assert row["last_task"]["task_id"] == "task-1"
    assert row["run_status"] == "running"


def test_task_state_summary_maps_abandoned_terminal_task_to_interrupted() -> None:
    task = SimpleNamespace(
        task_id="task-abandoned",
        status="abandoned",
        queue_mode="followup",
        run_kind="web_turn",
        source_kind="webui",
        created_at=100,
        started_at=110,
        finished_at=120,
        terminal_reason="runtime-restart",
        error_class="worker_lost",
        error_message="worker disappeared",
    )

    payload = task_state_summary([task])

    assert payload["active_task"] is None
    assert payload["last_task"]["task_id"] == "task-abandoned"
    assert payload["last_task"]["terminal_reason"] == "runtime-restart"
    assert payload["last_task"]["terminal_message"]
    assert payload["run_status"] == "interrupted"


def test_messages_subscribe_response_merges_replay_and_task_state() -> None:
    replay = SimpleNamespace(
        current_stream_seq=42,
        replay_complete=False,
        gap_reason="stream_buffer_reset",
    )
    task = SimpleNamespace(
        task_id="task-abandoned",
        status="abandoned",
        queue_mode="followup",
        run_kind="web_turn",
        source_kind="webui",
        created_at=100,
        started_at=110,
        finished_at=120,
        terminal_reason="process_restart",
        error_class=None,
        error_message=None,
    )

    payload = messages_subscribe_response(
        key="agent:main:webchat:restarted",
        subscribed=True,
        replay=replay,
        replayed_count=3,
        task_rows=[task],
    )

    assert payload["subscribed"] is True
    assert payload["key"] == "agent:main:webchat:restarted"
    assert payload["current_stream_seq"] == 42
    assert payload["replay_complete"] is False
    assert payload["replay_gap_reason"] == "stream_buffer_reset"
    assert payload["replayed_count"] == 3
    assert payload["last_task"]["task_id"] == "task-abandoned"
    assert payload["run_status"] == "interrupted"


def test_normalize_terminal_event_payload_preserves_non_error_events() -> None:
    payload = {"message": "ok"}

    assert normalize_terminal_event_payload("session.event.done", payload) is payload


def test_normalize_terminal_event_payload_maps_legacy_timeout_errors() -> None:
    payload = normalize_terminal_event_payload(
        "session.event.error",
        {
            "message": "Session event stream idle before terminal event",
            "code": "stream_idle_timeout",
        },
    )

    assert payload["message"] == "The task timed out before it could finish."
    assert payload["terminal_message"] == "The task timed out before it could finish."
    assert payload["terminal_reason"] == "timeout"
    assert payload["error_message"] == "Session event stream idle before terminal event"


def test_normalize_terminal_event_payload_prefers_error_message_and_reason() -> None:
    payload = normalize_terminal_event_payload(
        "session.event.error",
        {
            "message": "outer",
            "error_message": "inner failure",
            "terminal_reason": "model_error",
            "code": "provider_error",
        },
    )

    assert payload["message"] == "The task failed before it could finish."
    assert payload["terminal_message"] == "The task failed before it could finish."
    assert payload["terminal_reason"] == "model_error"
    assert payload["error_message"] == "inner failure"


def test_session_preview_row_uses_display_title_and_last_chat_message() -> None:
    session = SimpleNamespace(
        session_key="agent:main:webchat:abc123",
        session_id="abc123987654",
        display_name="Support thread",
        derived_title="Fallback title",
        updated_at=12345,
    )
    transcript = [
        SimpleNamespace(role="system", content="internal"),
        SimpleNamespace(role="user", content="first"),
        SimpleNamespace(role="tool", content="tool output"),
        SimpleNamespace(role="assistant", content="latest assistant message"),
    ]

    row = session_preview_row(session, transcript=transcript, now_ms=99999)

    assert row == {
        "key": "agent:main:webchat:abc123",
        "title": "Support thread",
        "lastMessage": "latest assistant message",
        "updatedAt": 12345,
    }


def test_session_preview_row_falls_back_to_derived_title_and_session_id() -> None:
    session = SimpleNamespace(
        session_key="agent:main:cli:abc123",
        session_id="abcdef123456",
        display_name=None,
        derived_title="Derived",
    )

    row = session_preview_row(session, transcript=[], now_ms=99999)

    assert row["title"] == "Derived"
    assert row["lastMessage"] == ""
    assert row["updatedAt"] == 99999

    session.derived_title = None
    assert session_preview_row(session, transcript=[], now_ms=1)["title"] == "abcdef12"


def test_session_preview_last_message_truncates_and_skips_non_chat_entries() -> None:
    transcript = [
        SimpleNamespace(role="tool", content="x" * 200),
        SimpleNamespace(role="assistant", content="a" * 130),
    ]

    assert session_preview_last_message(transcript) == "a" * 120


def test_session_resolve_response_owns_wire_shape() -> None:
    session = SimpleNamespace(
        session_key="agent:main:webchat:abc123",
        session_id="abc123",
        status="running",
        agent_id="main",
        model="gpt-test",
        created_at=1000,
        updated_at=2000,
    )

    assert session_resolve_response(session) == {
        "session_key": "agent:main:webchat:abc123",
        "session_id": "abc123",
        "status": "running",
        "agent_id": "main",
        "model": "gpt-test",
        "created_at": 1000,
        "updated_at": 2000,
    }


def test_session_create_stub_response_owns_no_manager_wire_shape() -> None:
    payload = session_create_stub_response("agent:ops:webchat:abc123")

    assert payload == {
        "key": "agent:ops:webchat:abc123",
        "sessionId": "abc123",
        "note": "session manager not available",
    }


def test_session_create_response_owns_created_session_wire_shape() -> None:
    session = SimpleNamespace(session_key="agent:ops:cli:abc123", session_id="abc123")

    assert session_create_response(session) == {
        "key": "agent:ops:cli:abc123",
        "sessionId": "abc123",
    }
    assert session_create_response(session, seeded_message=True) == {
        "key": "agent:ops:cli:abc123",
        "sessionId": "abc123",
        "seededMessage": True,
    }
