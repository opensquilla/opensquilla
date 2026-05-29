import json
from types import SimpleNamespace

import pytest

from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_chat import _handle_chat_history
from opensquilla.session.models import TranscriptEntry


class _FakeSessionManager:
    def __init__(self, entries, *, canonical_entries=None, summaries=None):
        self._entries = entries
        self._canonical_entries = canonical_entries
        self._summaries = summaries or []
        self.used_canonical = False

    async def get_transcript(self, session_key):
        return self._entries

    async def get_canonical_transcript(self, session_key):
        self.used_canonical = True
        if self._canonical_entries is None:
            raise RuntimeError("canonical unavailable")
        return self._canonical_entries

    async def get_summaries(self, session_key):
        return self._summaries


def _entry(idx: int, role: str = "user") -> TranscriptEntry:
    return TranscriptEntry(
        id=idx,
        session_id="parent",
        session_key="agent:main:webchat:test",
        role=role,
        content=f"message {idx}",
        created_at=idx,
        message_id=f"msg-{idx}",
    )


@pytest.mark.asyncio
async def test_chat_history_returns_pagination_metadata_with_legacy_messages() -> None:
    entries = [_entry(idx) for idx in range(1, 4)]

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test", "limit": 2},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=_FakeSessionManager(entries, canonical_entries=entries),
        ),
    )

    assert [msg["text"] for msg in result["messages"]] == ["message 2", "message 3"]
    assert result["has_more"] is True
    assert result["oldest_cursor"] == "2|2"
    assert result["newest_cursor"] == "3|3"
    assert result["history_scope"] == "latest_window"
    assert result["loaded_count"] == 2
    assert result["page_size"] == 2
    assert result["canonical_available"] is True


@pytest.mark.asyncio
async def test_chat_history_before_cursor_returns_older_page() -> None:
    entries = [_entry(idx) for idx in range(1, 6)]

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test", "limit": 2, "before": "4|4"},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=_FakeSessionManager(entries, canonical_entries=entries),
        ),
    )

    assert [msg["text"] for msg in result["messages"]] == ["message 2", "message 3"]
    assert result["has_more"] is True
    assert result["oldest_cursor"] == "2|2"
    assert result["newest_cursor"] == "3|3"


@pytest.mark.asyncio
async def test_chat_history_uses_canonical_transcript_when_available() -> None:
    active_entries = [_entry(3)]
    canonical_entries = [_entry(1), _entry(2), _entry(3)]
    mgr = _FakeSessionManager(active_entries, canonical_entries=canonical_entries)

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test", "limit": 10},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=mgr,
        ),
    )

    assert mgr.used_canonical is True
    assert [msg["text"] for msg in result["messages"]] == [
        "message 1",
        "message 2",
        "message 3",
    ]
    assert result["canonical_available"] is True


@pytest.mark.asyncio
async def test_chat_history_falls_back_when_canonical_unavailable() -> None:
    entries = [_entry(1)]
    mgr = _FakeSessionManager(entries)

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test", "limit": 10},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=mgr,
        ),
    )

    assert mgr.used_canonical is True
    assert [msg["text"] for msg in result["messages"]] == ["message 1"]
    assert result["canonical_available"] is False


@pytest.mark.asyncio
async def test_chat_history_exposes_subagent_completion_provenance() -> None:
    entry = TranscriptEntry(
        session_id="parent",
        session_key="agent:main:webchat:test",
        role="system",
        content='{"type":"subagent_completion","child_session_key":"agent:main:subagent:abc123"}',
    )
    entry.provenance_kind = "internal_system"
    entry.provenance_source_session_key = "agent:main:subagent:abc123"
    entry.provenance_source_tool = "subagent_completion"

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test"},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=_FakeSessionManager([entry]),
        ),
    )

    assert result["messages"] == [
        {
            "id": entry.message_id,
            "message_id": entry.message_id,
            "role": "system",
            "text": entry.content,
            "timestamp": entry.created_at,
            "provenance_kind": "internal_system",
            "provenance_source_session_key": "agent:main:subagent:abc123",
            "provenance_source_tool": "subagent_completion",
        }
    ]


@pytest.mark.asyncio
async def test_chat_history_exposes_stable_message_identity() -> None:
    entry = TranscriptEntry(
        session_id="parent",
        session_key="agent:main:webchat:test",
        role="assistant",
        content="done",
    )

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test"},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=_FakeSessionManager([entry]),
        ),
    )

    msg = result["messages"][0]
    assert msg["id"] == entry.message_id
    assert msg["message_id"] == entry.message_id


@pytest.mark.asyncio
async def test_chat_history_exposes_persisted_turn_usage() -> None:
    entry = TranscriptEntry(
        session_id="parent",
        session_key="agent:main:webchat:test",
        role="assistant",
        content="done",
        turn_usage={
            "model": "openai/gpt-test",
            "input_tokens": 11,
            "output_tokens": 5,
            "cost_usd": 0.0123,
            "cached_tokens": 2,
            "routed_tier": "economy",
            "routing_source": "squilla_router",
            "total_savings_pct": 42.0,
        },
    )

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test"},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=_FakeSessionManager([entry]),
        ),
    )

    msg = result["messages"][0]
    assert msg["usage"]["input_tokens"] == 11
    assert msg["usage"]["output_tokens"] == 5
    assert msg["usage"]["cost_usd"] == 0.0123
    assert msg["model"] == "openai/gpt-test"
    assert msg["input"] == 11
    assert msg["output"] == 5


@pytest.mark.asyncio
async def test_chat_history_exposes_assistant_artifacts() -> None:
    artifact = {
        "id": "art-1",
        "kind": "artifact_ref",
        "name": "report.txt",
        "mime": "text/plain",
        "size": 12,
        "sha256": "c" * 64,
        "session_id": "session-1",
        "session_key": "agent:main:webchat:test",
        "source": "publish_artifact",
        "created_at": "2026-05-06T12:00:00Z",
        "download_url": "/api/v1/artifacts/art-1?sessionKey=agent%3Amain%3Awebchat%3Atest",
    }
    entry = TranscriptEntry(
        session_id="session-1",
        session_key="agent:main:webchat:test",
        role="assistant",
        content='{"text":"done","artifacts":[' + json.dumps(artifact) + "]}",
    )

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test"},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=_FakeSessionManager([entry]),
        ),
    )

    assert result["messages"][0]["text"] == "done"
    output_artifact = result["messages"][0]["artifacts"][0]
    assert output_artifact["download_url"] == "/api/v1/artifacts/art-1"
    assert "session_key" not in output_artifact
    assert "sessionKey" not in json.dumps(output_artifact)


@pytest.mark.asyncio
async def test_chat_history_strips_artifact_omitted_marker_from_visible_text() -> None:
    artifact = {
        "id": "art-1",
        "kind": "artifact_ref",
        "name": "peppa_and_mummy_correct.png",
        "mime": "image/jpeg",
        "size": 339_000,
        "sha256": "c" * 64,
        "session_id": "session-1",
        "session_key": "agent:main:webchat:test",
        "source": "image_generate",
        "created_at": "2026-05-06T12:00:00Z",
        "download_url": "/api/v1/artifacts/art-1",
    }
    marker = "[generated artifact omitted: peppa_and_mummy_correct.png (image/jpeg)]"
    entry = TranscriptEntry(
        session_id="session-1",
        session_key="agent:main:webchat:test",
        role="assistant",
        content=json.dumps(
            {
                "text": f"图片已经生成。\n\n{marker}",
                "artifacts": [artifact],
            }
        ),
    )

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test"},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=_FakeSessionManager([entry]),
        ),
    )

    msg = result["messages"][0]
    assert msg["text"] == "图片已经生成。"
    assert msg["artifacts"][0]["name"] == "peppa_and_mummy_correct.png"


@pytest.mark.asyncio
async def test_chat_history_prefers_attachment_display_text() -> None:
    entry = TranscriptEntry(
        session_id="session-1",
        session_key="agent:main:webchat:test",
        role="user",
        content=json.dumps(
            {
                "text": "Describe these attachments",
                "display_text": "",
                "attachments": [
                    {
                        "type": "image/png",
                        "name": "image.png",
                        "data": "aW1hZ2U=",
                    }
                ],
            }
        ),
    )

    result = await _handle_chat_history(
        {"sessionKey": "agent:main:webchat:test"},
        RpcContext(
            conn_id="test",
            principal=SimpleNamespace(role="operator"),
            session_manager=_FakeSessionManager([entry]),
        ),
    )

    msg = result["messages"][0]
    assert msg["text"] == ""
    assert msg["attachments"][0]["name"] == "image.png"
