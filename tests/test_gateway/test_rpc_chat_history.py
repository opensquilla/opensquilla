import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway import rpc_chat
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_chat import _handle_chat_history
from opensquilla.session.models import TranscriptEntry


class _FakeSessionManager:
    def __init__(self, entries):
        self._entries = entries

    async def get_transcript(self, session_key):
        return self._entries


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


def test_gateway_rpc_chat_history_delegates_payload_to_session_boundary() -> None:
    source = Path(rpc_chat.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    handler = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_chat_history"
    )
    direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }

    assert ("opensquilla.session.rpc_payload", "chat_history_response") in imports
    assert any(
        isinstance(node, ast.Name) and node.id == "chat_history_response"
        for node in ast.walk(handler)
    )
    assert ("messages",) not in direct_key_sets
    assert ("id", "message_id", "role", "text", "timestamp") not in direct_key_sets
    assert "json.loads" not in source
    assert "ContentBlockText" not in source


def test_gateway_rpc_chat_envelopes_delegate_payloads_to_session_boundary() -> None:
    source = Path(rpc_chat.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    handlers = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name in {"_handle_chat_send", "_handle_chat_abort", "_handle_chat_inject"}
    }
    handler_names = {
        node.id
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    helper_names = {
        "chat_send_instant_accept_response",
        "chat_send_refusal_response",
        "chat_send_response",
        "chat_abort_unavailable_response",
        "chat_abort_response",
        "chat_inject_response",
    }

    assert {
        ("opensquilla.session.rpc_payload", helper_name)
        for helper_name in helper_names
    }.issubset(imports)
    assert helper_names.issubset(handler_names)
    assert ("ok", "sessionKey", "instant_accept") not in direct_key_sets
    assert ("ok", "sessionKey") not in direct_key_sets
    assert ("ok", "sessionKey", "aborted") not in direct_key_sets
    assert ("sessionKey",) not in direct_key_sets
