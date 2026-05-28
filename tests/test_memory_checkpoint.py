from pathlib import Path

import pytest

import opensquilla.memory.checkpoint as checkpoint
from opensquilla.memory.checkpoint import (
    CheckpointEvent,
    append_checkpoint_events,
    checkpoint_event_hash,
    checkpoint_relative_path,
)


def _checkpoint_event(
    *,
    session_key: str = "agent:main:webchat:abc",
    turn_id: str = "turn-1",
) -> CheckpointEvent:
    return CheckpointEvent(
        schema_version=1,
        event_id="evt-1",
        session_key=session_key,
        session_id="session-1",
        turn_id=turn_id,
        sequence=1,
        timestamp_ms=123,
        role="user",
        content_type="text",
        content="hello",
        summary=None,
        tool_name=None,
        tool_call_id=None,
        status="ok",
        token_estimate=1,
        source="turn_runner",
        attachments=[],
        content_hash="",
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


async def test_append_checkpoint_events_writes_jsonl_once(tmp_path):
    event = _checkpoint_event()

    result = append_checkpoint_events(tmp_path, [event])
    second = append_checkpoint_events(tmp_path, [event])

    assert result.relative_path == "memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl"
    assert result.event_count == 1
    assert result.content_hash == second.content_hash
    lines = (tmp_path / result.relative_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


@pytest.mark.parametrize(
    "event",
    [
        _checkpoint_event(session_key="agent:main:webchat:other"),
        _checkpoint_event(turn_id="turn-2"),
    ],
)
def test_append_checkpoint_events_rejects_mixed_turn_batches(tmp_path, event):
    with pytest.raises(ValueError, match="share session_key and turn_id"):
        append_checkpoint_events(tmp_path, [_checkpoint_event(), event])


def test_append_checkpoint_events_cleans_temp_file_when_write_fails(
    tmp_path,
    monkeypatch,
):
    class FailingTempFile:
        def __init__(self, *, dir, prefix, suffix, **_kwargs):
            self.name = str(Path(dir) / f"{prefix}forced{suffix}")

        def __enter__(self):
            Path(self.name).write_text("partial", encoding="utf-8")
            return self

        def __exit__(self, *_args):
            return False

        def write(self, _body):
            raise OSError("simulated write failure")

    monkeypatch.setattr(checkpoint.tempfile, "NamedTemporaryFile", FailingTempFile)

    with pytest.raises(OSError, match="simulated write failure"):
        append_checkpoint_events(tmp_path, [_checkpoint_event()])

    checkpoint_dir = tmp_path / "memory/.checkpoints/agent-main-webchat-abc"
    assert not any(path.name.endswith(".tmp") for path in checkpoint_dir.iterdir())


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
