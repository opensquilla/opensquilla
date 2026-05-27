from pathlib import Path

import pytest

from opensquilla.memory.checkpoint import (
    CheckpointEvent,
    checkpoint_event_hash,
    checkpoint_relative_path,
)


def test_checkpoint_event_serializes_required_fields() -> None:
    event = CheckpointEvent(
        schema_version=1,
        event_id="evt-1",
        session_key="agent:main:webchat:abc",
        session_id="session-1",
        turn_id="turn-1",
        sequence=1,
        timestamp_ms=123,
        role="tool_result",
        content_type="json",
        content='{"ok": true}',
        summary="tool succeeded",
        tool_name="memory_save",
        tool_call_id="call-1",
        status="ok",
        token_estimate=3,
        source="tool_runtime",
        attachments=[],
        content_hash="",
    )

    payload = event.to_json_dict()

    assert payload["schema_version"] == 1
    assert payload["session_key"] == "agent:main:webchat:abc"
    assert payload["role"] == "tool_result"
    assert payload["tool_name"] == "memory_save"
    assert payload["status"] == "ok"


def test_checkpoint_hash_is_stable_for_normalized_content() -> None:
    first = checkpoint_event_hash(" user message\n")
    second = checkpoint_event_hash("user message")

    assert first == second
    assert len(first) == 64


def test_checkpoint_relative_path_is_sidecar_only() -> None:
    path = checkpoint_relative_path(
        session_key="agent:main:webchat:abc",
        turn_id="turn-1",
    )

    assert path == Path("memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl")


@pytest.mark.parametrize(
    ("session_key", "expected_component"),
    [
        ("..", "unknown"),
        (".", "unknown"),
        ("..-", "unknown"),
        ("-..", "unknown"),
        ("---..---", "unknown"),
        (".-", "unknown"),
        ("-.", "unknown"),
        ("../abc", "..-abc"),
        ("a/b", "a-b"),
    ],
)
def test_checkpoint_relative_path_sanitizes_unsafe_session_components(
    session_key: str,
    expected_component: str,
) -> None:
    path = checkpoint_relative_path(session_key=session_key, turn_id="turn-1")

    assert path == Path("memory/.checkpoints") / expected_component / "turn-1.jsonl"
    assert ".." not in path.relative_to("memory/.checkpoints").parts
    assert "." not in path.relative_to("memory/.checkpoints").parts
