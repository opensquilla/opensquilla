"""Tests for sessions domain RPC handlers."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from opensquilla.agents.registry import AgentRegistry
from opensquilla.engine.types import DoneEvent
from opensquilla.gateway.agent_tasks import get_agent_task_registry
from opensquilla.gateway.attachment_ingest import (
    MAX_STAGED_PDF_BYTES,
    MAX_TOTAL_ATTACHMENT_BYTES,
)
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.config import AgentEntryConfig, GatewayConfig
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.gateway.rpc_sessions import _normalize_terminal_event_payload
from opensquilla.gateway.session_streams import get_session_streams
from opensquilla.gateway.uploads import set_upload_store
from opensquilla.gateway.websocket import SubscriptionManager, get_registry
from opensquilla.session.compaction import CompactionConfig

_DEFAULT_PRINCIPAL = Principal(
    role="operator", scopes=frozenset(["operator.admin"]), is_owner=True, authenticated=True
)


@dataclass
class FakeSession:
    session_key: str = "agent:main:abc123"
    session_id: str = "abc123"
    status: str = "running"
    agent_id: str = "main"
    created_at: int = 1000
    updated_at: int = 2000
    display_name: str | None = None
    derived_title: str | None = None
    channel: str | None = None
    chat_type: str = "unknown"
    group_id: str | None = None
    subject: str | None = None
    last_channel: str | None = None
    last_to: str | None = None
    last_account_id: str | None = None
    last_thread_id: str | None = None
    delivery_context: dict | None = None
    parent_session_key: str | None = None
    spawned_by: str | None = None
    origin: dict | None = None
    model: str | None = None
    model_override: str | None = None


class FakeStorage:
    def __init__(self, sessions: list[FakeSession] | None = None):
        self._sessions = {s.session_key: s for s in (sessions or [])}
        self._transcripts: dict[str, list] = {}
        self._agent_tasks: dict[str, list[SimpleNamespace]] = {}
        self.list_agent_tasks_calls: list[str | None] = []
        self.list_agent_tasks_for_sessions_calls: list[tuple[str, ...]] = []

    async def list_sessions(self, limit: int | None = None) -> list[FakeSession]:
        result = list(self._sessions.values())
        if limit:
            result = result[:limit]
        return result

    async def get_session(self, key: str) -> FakeSession | None:
        return self._sessions.get(key)

    async def delete_session(self, key: str) -> None:
        if key not in self._sessions:
            raise KeyError(f"Session not found: {key}")
        del self._sessions[key]

    async def delete_transcript(self, session_id: str) -> None:
        self._transcripts.pop(session_id, None)

    async def list_agent_tasks(
        self,
        session_key: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SimpleNamespace]:
        self.list_agent_tasks_calls.append(session_key)
        if session_key is None:
            rows = [row for values in self._agent_tasks.values() for row in values]
        else:
            rows = list(self._agent_tasks.get(session_key, []))
        if status is not None:
            rows = [row for row in rows if getattr(row, "status", None) == status]
        return rows[offset : offset + limit]

    async def list_agent_tasks_for_sessions(
        self,
        session_keys: list[str],
        limit_per_session: int = 100,
    ) -> dict[str, list[SimpleNamespace]]:
        self.list_agent_tasks_for_sessions_calls.append(tuple(session_keys))
        return {
            key: list(self._agent_tasks.get(key, []))[:limit_per_session]
            for key in session_keys
        }


class FakeSessionManager:
    def __init__(self, sessions: list[FakeSession] | None = None):
        self._storage = FakeStorage(sessions)
        self.created_messages: list[tuple[str, str, str]] = []
        self.applied_intents: list[tuple[str, str]] = []
        self.truncate_calls: list[tuple[str, int]] = []
        self.compact_calls: list[tuple[str, int, object | None]] = []
        self.compact_summary = "summary for compacted context"
        self.compact_summary_source = "fallback"

    async def append_message(self, key: str, role: str = "user", content: str = "") -> None:
        self.created_messages.append((key, role, content))

    async def create(
        self,
        session_key: str,
        agent_id: str = "main",
        display_name: str | None = None,
        model: str | None = None,
    ):
        session = FakeSession(
            session_key=session_key,
            session_id=session_key.rsplit(":", 1)[-1],
            agent_id=agent_id,
            display_name=display_name,
            model=model,
        )
        self._storage._sessions[session_key] = session
        return session

    async def get_transcript(self, key: str) -> list:
        return []

    async def truncate(self, session_key: str, max_messages: int = 20) -> dict:
        session = await self._storage.get_session(session_key)
        if session is None:
            raise KeyError(f"Session not found: {session_key}")
        self.truncate_calls.append((session_key, max_messages))
        return {"truncated": False, "before_count": 0, "after_count": 0}

    async def compact(self, session_key: str, context_window_tokens: int, config=None) -> str:
        session = await self._storage.get_session(session_key)
        if session is None:
            raise KeyError(f"Session not found: {session_key}")
        self.compact_calls.append((session_key, context_window_tokens, config))
        return self.compact_summary

    async def compact_with_result(self, session_key: str, context_window_tokens: int, config=None):
        summary = await self.compact(session_key, context_window_tokens, config)
        return SimpleNamespace(
            summary=summary,
            removed_count=1 if summary else 0,
            summary_source=self.compact_summary_source if summary else "skipped",
        )

    async def apply_intent(self, session_key: str, intent: str, **kwargs):
        self.applied_intents.append((session_key, str(intent)))
        session = await self._storage.get_session(session_key)
        if session is None:
            session = await self.create(session_key, agent_id=kwargs.get("agent_id", "main"))
            return session, True
        if str(intent) == "new_chat":
            raise ValueError("session_key conflict")
        if str(intent) == "continue":
            return session, False
        if str(intent) != "reset_same_key":
            raise KeyError(f"Session not found: {session_key}")
        old_id = session.session_id
        await self._storage.delete_transcript(old_id)
        session.session_id = f"{old_id}-rotated"
        return session, True


def make_ctx(session_manager=None, **kwargs) -> RpcContext:
    role = kwargs.pop("role", "operator")
    scopes = kwargs.pop("scopes", None)
    if scopes is not None:
        principal = Principal(
            role=role, scopes=frozenset(scopes), is_owner=role == "operator", authenticated=True
        )
    else:
        principal = _DEFAULT_PRINCIPAL
    defaults = {
        "conn_id": "test-conn",
        "principal": principal,
        "config": GatewayConfig(),
    }
    defaults.update(kwargs)
    ctx = RpcContext(**defaults)
    ctx.session_manager = session_manager
    return ctx


class _FakeCompactionProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str = "provider-key",
        model: str = "provider/model",
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url

    @property
    def model(self) -> str:
        return self._model


class _FakeSelectorClone:
    def __init__(self, provider: _FakeCompactionProvider) -> None:
        self.provider = provider
        self.override_calls: list[str] = []

    def override_model(self, model: str) -> None:
        self.override_calls.append(model)
        self.provider._model = model

    def resolve(self) -> _FakeCompactionProvider:
        return self.provider


class _FakeProviderSelector:
    def __init__(self, provider: _FakeCompactionProvider | None = None) -> None:
        self.provider = provider or _FakeCompactionProvider()
        self.clone_instance = _FakeSelectorClone(self.provider)
        self.override_calls: list[str] = []

    def clone(self) -> _FakeSelectorClone:
        return self.clone_instance

    def override_model(self, model: str) -> None:
        self.override_calls.append(model)

    def resolve(self) -> _FakeCompactionProvider:
        return self.provider


class _LegacyCompactManager:
    def __init__(self, session: FakeSession) -> None:
        self._storage = FakeStorage([session])
        self.compact_calls: list[tuple[str, int]] = []

    async def compact(self, session_key: str, context_window_tokens: int) -> str:
        self.compact_calls.append((session_key, context_window_tokens))
        return "legacy summary"


class _ReplayConn:
    def __init__(self, conn_id: str) -> None:
        self.conn_id = conn_id
        self.events: list[tuple[str, dict]] = []

    async def send_event(self, event: str, payload: dict | None = None) -> None:
        self.events.append((event, payload or {}))


class _RecordingTurnRunner:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, Any]] = []
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_session_lock(self, session_key: str) -> asyncio.Lock:
        return self._locks.setdefault(session_key, asyncio.Lock())

    async def run(self, message: str, session_key: str, **kwargs):
        self.run_calls.append({"message": message, "session_key": session_key, **kwargs})
        yield DoneEvent()


class _FakeUploadStore:
    def __init__(self, entries: dict[str, tuple[bytes, dict[str, Any]]]) -> None:
        self.entries = entries
        self.evicted: list[str] = []

    async def get(self, file_uuid: str) -> tuple[bytes, dict[str, Any]]:
        return self.entries[file_uuid]

    async def evict(self, file_uuid: str) -> bool:
        self.evicted.append(file_uuid)
        return self.entries.pop(file_uuid, None) is not None


def _exact_pdf(size: int) -> bytes:
    header = b"%PDF-1.4\n"
    return header + b"a" * (size - len(header))


@pytest.fixture
def dispatcher():
    return get_dispatcher()


@pytest.fixture
def session():
    return FakeSession()


@pytest.fixture
def ctx_with_sessions(session):
    return make_ctx(session_manager=FakeSessionManager([session]))


@pytest.fixture
def ctx_no_manager():
    return make_ctx(session_manager=None)


class TestSessionsCreate:
    @pytest.mark.asyncio
    async def test_create_stub(self, dispatcher, ctx_no_manager):
        res = await dispatcher.dispatch(
            "r1", "sessions.create", {"agentId": "myagent"}, ctx_no_manager
        )
        assert res.ok is True
        assert res.payload["key"].startswith("agent:myagent:")
        assert "sessionId" in res.payload

    @pytest.mark.asyncio
    async def test_create_defaults(self, dispatcher, ctx_no_manager):
        res = await dispatcher.dispatch("r1", "sessions.create", None, ctx_no_manager)
        assert res.ok is True
        assert res.payload["key"].startswith("agent:main:")

    @pytest.mark.asyncio
    async def test_create_cli_kind_uses_cli_session_namespace(self, dispatcher, ctx_no_manager):
        res = await dispatcher.dispatch(
            "r1", "sessions.create", {"agentId": "myagent", "kind": "cli"}, ctx_no_manager
        )
        assert res.ok is True
        assert res.payload["key"].startswith("agent:myagent:cli:")

    @pytest.mark.asyncio
    async def test_create_webchat_kind_uses_webchat_session_namespace(
        self, dispatcher, ctx_no_manager
    ):
        res = await dispatcher.dispatch(
            "r1", "sessions.create", {"agentId": "myagent", "kind": "webchat"}, ctx_no_manager
        )
        assert res.ok is True
        assert res.payload["key"].startswith("agent:myagent:webchat:")

    @pytest.mark.asyncio
    async def test_create_with_message_requires_manager(self, dispatcher, ctx_no_manager):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.create",
            {"agentId": "myagent", "message": "hello"},
            ctx_no_manager,
        )
        assert res.ok is False
        assert res.error.code == "UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_create_with_message_seeds_transcript(self, dispatcher):
        session_manager = FakeSessionManager()
        ctx = make_ctx(session_manager=session_manager)
        res = await dispatcher.dispatch(
            "r1",
            "sessions.create",
            {"agentId": "myagent", "message": "hello"},
            ctx,
        )
        assert res.ok is True
        assert res.payload["seededMessage"] is True
        assert session_manager.created_messages == [(res.payload["key"], "user", "hello")]

    @pytest.mark.asyncio
    async def test_create_uses_agent_registry_model_when_model_not_explicit(self, dispatcher):
        cfg = GatewayConfig(agents=[AgentEntryConfig(id="ops", model="agent/default")])
        registry = AgentRegistry(cfg, persist_changes=False)
        session_manager = FakeSessionManager()
        ctx = make_ctx(session_manager=session_manager, config=cfg, agent_registry=registry)

        res = await dispatcher.dispatch(
            "r1",
            "sessions.create",
            {"agentId": "ops"},
            ctx,
        )

        assert res.ok is True
        session = session_manager._storage._sessions[res.payload["key"]]
        assert session.model == "agent/default"

    @pytest.mark.asyncio
    async def test_create_explicit_model_overrides_agent_registry_model(self, dispatcher):
        cfg = GatewayConfig(agents=[AgentEntryConfig(id="ops", model="agent/default")])
        registry = AgentRegistry(cfg, persist_changes=False)
        session_manager = FakeSessionManager()
        ctx = make_ctx(session_manager=session_manager, config=cfg, agent_registry=registry)

        res = await dispatcher.dispatch(
            "r1",
            "sessions.create",
            {"agentId": "ops", "model": "explicit/model"},
            ctx,
        )

        assert res.ok is True
        session = session_manager._storage._sessions[res.payload["key"]]
        assert session.model == "explicit/model"

    @pytest.mark.asyncio
    async def test_create_rejects_missing_agent_when_registry_present(self, dispatcher):
        cfg = GatewayConfig(agents=[AgentEntryConfig(id="ops", model="agent/default")])
        registry = AgentRegistry(cfg, persist_changes=False)
        session_manager = FakeSessionManager()
        ctx = make_ctx(session_manager=session_manager, config=cfg, agent_registry=registry)

        res = await dispatcher.dispatch(
            "r1",
            "sessions.create",
            {"agentId": "ghost"},
            ctx,
        )

        assert res.ok is False
        assert res.error.code == "agent.not_found"
        assert res.error.details == {"agentId": "ghost"}

    @pytest.mark.asyncio
    async def test_create_with_create_if_missing_does_not_create_agent(self, dispatcher):
        cfg = GatewayConfig()
        registry = AgentRegistry(cfg, persist_changes=False)
        session_manager = FakeSessionManager()
        ctx = make_ctx(
            session_manager=session_manager,
            config=cfg,
            agent_registry=registry,
            scopes=["operator.write"],
        )

        res = await dispatcher.dispatch(
            "r1",
            "sessions.create",
            {
                "agentId": "dragons",
                "agentName": "Dragons",
                "createAgentIfMissing": True,
                "model": "openai/test",
            },
            ctx,
        )

        assert res.ok is False
        assert res.error.code == "agent.not_found"
        assert res.error.details == {"agentId": "dragons"}
        assert cfg.agents == []
        assert session_manager._storage._sessions == {}

    @pytest.mark.asyncio
    async def test_create_with_create_if_missing_existing_agent_no_duplicate(self, dispatcher):
        cfg = GatewayConfig(agents=[AgentEntryConfig(id="ops", model="agent/default")])
        registry = AgentRegistry(cfg, persist_changes=False)
        session_manager = FakeSessionManager()
        ctx = make_ctx(session_manager=session_manager, config=cfg, agent_registry=registry)

        res = await dispatcher.dispatch(
            "r1",
            "sessions.create",
            {"agentId": "ops", "createAgentIfMissing": True},
            ctx,
        )

        assert res.ok is True
        assert sum(1 for a in cfg.agents if a.id == "ops") == 1

    @pytest.mark.asyncio
    async def test_create_main_agent_passes_without_registry(self, dispatcher):
        # No agent_registry on ctx; agentId="main" must always pass through.
        session_manager = FakeSessionManager()
        ctx = make_ctx(session_manager=session_manager)

        res = await dispatcher.dispatch(
            "r1",
            "sessions.create",
            {"agentId": "main"},
            ctx,
        )

        assert res.ok is True


class TestSessionsList:
    @pytest.mark.asyncio
    async def test_list_includes_source_and_delivery_metadata(self, dispatcher):
        session = FakeSession(
            session_key="agent:main:webchat:abc12345",
            display_name="WebChat",
            last_channel="slack",
            last_to="C123",
            last_account_id="acct-1",
            last_thread_id="1700.1",
            delivery_context={"channel_id": "C123"},
        )
        ctx = make_ctx(session_manager=FakeSessionManager([session]))

        res = await dispatcher.dispatch("r1", "sessions.list", None, ctx)

        assert res.ok is True
        row = res.payload["sessions"][0]
        assert row["agent_id"] == "main"
        assert row["display_name"] == "WebChat"
        assert row["source_kind"] == "webui"
        assert row["channel_kind"] == "slack"
        assert row["last_channel"] == "slack"
        assert row["last_to"] == "C123"
        assert row["delivery_context"] == {"channel_id": "C123"}

    @pytest.mark.asyncio
    async def test_list_exposes_persisted_active_task_without_runtime(self, dispatcher):
        session = FakeSession(session_key="agent:main:webchat:task-ledger")
        manager = FakeSessionManager([session])
        manager._storage._agent_tasks[session.session_key] = [
            SimpleNamespace(
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
        ]
        ctx = make_ctx(session_manager=manager, task_runtime=None)

        res = await dispatcher.dispatch("r1", "sessions.list", None, ctx)

        assert res.ok is True
        row = res.payload["sessions"][0]
        assert row["tasks"][0]["task_id"] == "task-1"
        assert row["active_task"]["task_id"] == "task-1"
        assert row["last_task"]["task_id"] == "task-1"
        assert row["run_status"] == "running"

    @pytest.mark.asyncio
    async def test_list_batches_persisted_task_state_for_visible_sessions(self, dispatcher):
        one = FakeSession(session_key="agent:main:webchat:one")
        two = FakeSession(session_key="agent:main:webchat:two")
        manager = FakeSessionManager([one, two])
        manager._storage._agent_tasks[one.session_key] = [
            SimpleNamespace(
                task_id="task-one",
                status="running",
                queue_mode="followup",
                run_kind="web_turn",
                source_kind="webui",
                created_at=100,
                started_at=110,
                finished_at=None,
                terminal_reason=None,
            )
        ]
        manager._storage._agent_tasks[two.session_key] = [
            SimpleNamespace(
                task_id="task-two",
                status="succeeded",
                queue_mode="followup",
                run_kind="web_turn",
                source_kind="webui",
                created_at=90,
                started_at=95,
                finished_at=120,
                terminal_reason="completed",
            )
        ]
        ctx = make_ctx(session_manager=manager, task_runtime=None)

        res = await dispatcher.dispatch("r1", "sessions.list", None, ctx)

        assert res.ok is True
        by_key = {row["key"]: row for row in res.payload["sessions"]}
        assert by_key[one.session_key]["active_task"]["task_id"] == "task-one"
        assert by_key[two.session_key]["last_task"]["task_id"] == "task-two"
        assert manager._storage.list_agent_tasks_for_sessions_calls == [
            (one.session_key, two.session_key)
        ]
        assert manager._storage.list_agent_tasks_calls == []


class TestSessionsSend:
    @pytest.mark.asyncio
    async def test_send_valid(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.send",
            {"key": session.session_key, "message": "hello"},
            ctx_with_sessions,
        )
        assert res.ok is True
        assert ctx_with_sessions.session_manager.applied_intents == [
            (session.session_key, "continue")
        ]

    def test_legacy_session_error_payload_is_terminal_message_normalized(self):
        payload = _normalize_terminal_event_payload(
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

    @pytest.mark.asyncio
    async def test_send_reset_same_key_intent_applies_before_append(
        self, dispatcher, ctx_with_sessions, session
    ):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.send",
            {
                "key": session.session_key,
                "message": "fresh start",
                "intent": "reset_same_key",
            },
            ctx_with_sessions,
        )

        assert res.ok is True
        assert ctx_with_sessions.session_manager.applied_intents == [
            (session.session_key, "reset_same_key")
        ]
        assert ctx_with_sessions.session_manager.created_messages[0] == (
            session.session_key,
            "user",
            "fresh start",
        )

    @pytest.mark.asyncio
    async def test_send_new_chat_intent_creates_missing_key(self, dispatcher):
        manager = FakeSessionManager()
        ctx = make_ctx(session_manager=manager)

        res = await dispatcher.dispatch(
            "r1",
            "sessions.send",
            {
                "key": "agent:default:fresh",
                "message": "fresh",
                "intent": "new_chat",
            },
            ctx,
        )

        assert res.ok is True
        assert manager.applied_intents == [("agent:main:fresh", "new_chat")]
        assert manager.created_messages[0] == ("agent:main:fresh", "user", "fresh")

    @pytest.mark.asyncio
    async def test_send_missing_message(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1", "sessions.send", {"key": session.session_key}, ctx_with_sessions
        )
        assert res.ok is False
        assert res.error.code == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_send_missing_key(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch("r1", "sessions.send", {"message": "hi"}, ctx_with_sessions)
        assert res.ok is False
        assert res.error.code == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_send_not_found(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.send",
            {"key": "nonexistent", "message": "hi"},
            ctx_with_sessions,
        )
        assert res.ok is False
        assert res.error.code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_send_rejects_too_many_attachments(self, dispatcher, ctx_with_sessions, session):
        # The per-turn cap is 10; 11 must be rejected.
        res = await dispatcher.dispatch(
            "r1",
            "sessions.send",
            {
                "key": session.session_key,
                "message": "hi",
                "attachments": [{"type": "image/png", "data": "QQ=="}] * 11,
            },
            ctx_with_sessions,
        )
        assert res.ok is False
        assert res.error.code == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_send_rejects_aggregate_attachment_cap_before_start_and_evict(
        self, dispatcher, ctx_with_sessions, session
    ):
        one_pdf = _exact_pdf(MAX_TOTAL_ATTACHMENT_BYTES // 3 + 1)
        assert len(one_pdf) < MAX_STAGED_PDF_BYTES
        entries = {
            f"u-pdf-{index}": (
                one_pdf,
                {
                    "mime": "application/pdf",
                    "name": f"{index}.pdf",
                    "sha256": "x",
                    "size": len(one_pdf),
                },
            )
            for index in range(3)
        }
        store = _FakeUploadStore(entries)
        set_upload_store(store)  # type: ignore[arg-type]
        try:
            res = await dispatcher.dispatch(
                "r1",
                "sessions.send",
                {
                    "key": session.session_key,
                    "message": "hi",
                    "attachments": [
                        {
                            "file_uuid": file_uuid,
                            "mime": "application/pdf",
                            "name": meta["name"],
                        }
                        for file_uuid, (_payload, meta) in entries.items()
                    ],
                },
                ctx_with_sessions,
            )
        finally:
            set_upload_store(None)

        assert res.ok is False
        assert res.error.code == "INVALID_REQUEST"
        assert ctx_with_sessions.session_manager.created_messages == []
        assert store.evicted == []
        assert set(store.entries) == set(entries)

    @pytest.mark.asyncio
    async def test_send_staged_upload_persists_and_runs_with_material_ref(
        self,
        dispatcher,
        tmp_path,
        session,
    ):
        payload = b"%PDF-1.4\nbody\n"
        sha = hashlib.sha256(payload).hexdigest()
        store = _FakeUploadStore(
            {
                "u-pdf": (
                    payload,
                    {
                        "mime": "application/pdf",
                        "name": "r.pdf",
                        "sha256": sha,
                        "size": len(payload),
                    },
                )
            }
        )
        manager = FakeSessionManager([session])
        runner = _RecordingTurnRunner()
        cfg = GatewayConfig()
        cfg.attachments.media_root = str(tmp_path)
        ctx = make_ctx(session_manager=manager, config=cfg, turn_runner=runner)
        set_upload_store(store)  # type: ignore[arg-type]
        try:
            res = await dispatcher.dispatch(
                "r1",
                "sessions.send",
                {
                    "key": session.session_key,
                    "message": "summarise",
                    "attachments": [
                        {"file_uuid": "u-pdf", "mime": "application/pdf", "name": "r.pdf"}
                    ],
                },
                ctx,
            )
            task = get_agent_task_registry().get(session.session_key)
            if task is not None:
                await task
        finally:
            set_upload_store(None)

        assert res.ok is True
        assert store.evicted == ["u-pdf"]
        persisted = json.loads(manager.created_messages[0][2])
        persisted_att = persisted["attachments"][0]
        assert persisted_att == {
            "sha256_ref": sha,
            "name": "r.pdf",
            "mime": "application/pdf",
            "size": len(payload),
        }
        runtime_att = runner.run_calls[0]["attachments"][0]
        assert runtime_att["kind"] == "attachment_ref"
        assert runtime_att["sha256"] == sha
        assert runtime_att["scope"] == session.session_id
        assert "data" not in runtime_att
        assert "file_uuid" not in runtime_att
        assert (tmp_path / "transcripts" / session.session_id / sha).read_bytes() == payload

    @pytest.mark.asyncio
    async def test_send_rejects_invalid_attachment_media_type(
        self, dispatcher, ctx_with_sessions, session
    ):
        # text/plain is in the allow-list. Use a MIME that is genuinely
        # outside the allow-list to keep this regression honest.
        res = await dispatcher.dispatch(
            "r1",
            "sessions.send",
            {
                "key": session.session_key,
                "message": "hi",
                "attachments": [
                    {"type": "application/x-shellscript", "data": "QQ=="}
                ],
            },
            ctx_with_sessions,
        )
        assert res.ok is False
        assert res.error.code == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_send_uses_agent_registry_model_when_session_model_missing(
        self, dispatcher, tmp_path
    ):
        session = FakeSession(session_key="agent:ops:abc123", agent_id="ops", model=None)
        manager = FakeSessionManager([session])
        agent_workspace = tmp_path / "ops-workspace"
        cfg = GatewayConfig(
            agents=[
                AgentEntryConfig(
                    id="ops",
                    model="agent/default",
                    workspace=str(agent_workspace),
                )
            ]
        )
        registry = AgentRegistry(cfg, persist_changes=False)
        runner = _RecordingTurnRunner()
        ctx = make_ctx(
            session_manager=manager,
            config=cfg,
            agent_registry=registry,
            turn_runner=runner,
        )

        res = await dispatcher.dispatch(
            "r1",
            "sessions.send",
            {"key": session.session_key, "message": "hello"},
            ctx,
        )
        task = get_agent_task_registry().get(session.session_key)
        if task is not None:
            await task

        assert res.ok is True
        assert runner.run_calls[0]["model"] == "agent/default"
        assert runner.run_calls[0]["tool_context"].workspace_dir == str(agent_workspace)


class TestSessionsAbort:
    @pytest.mark.asyncio
    async def test_abort_valid(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1", "sessions.abort", {"key": session.session_key}, ctx_with_sessions
        )
        assert res.ok is True

    @pytest.mark.asyncio
    async def test_abort_no_manager(self, dispatcher, ctx_no_manager):
        res = await dispatcher.dispatch("r1", "sessions.abort", {"key": "any"}, ctx_no_manager)
        assert res.ok is True  # no-op

    @pytest.mark.asyncio
    async def test_abort_not_found(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch(
            "r1", "sessions.abort", {"key": "nonexistent"}, ctx_with_sessions
        )
        assert res.ok is False
        assert res.error.code == "NOT_FOUND"


class TestSessionsPatch:
    @pytest.mark.asyncio
    async def test_patch_valid(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.patch",
            {"key": session.session_key, "displayName": "New Name"},
            ctx_with_sessions,
        )
        assert res.ok is True
        assert res.payload["key"] == session.session_key
        assert "displayName" in res.payload["updated"]

    @pytest.mark.asyncio
    async def test_patch_not_found(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.patch",
            {"key": "nonexistent", "displayName": "x"},
            ctx_with_sessions,
        )
        assert res.ok is False
        assert res.error.code == "NOT_FOUND"


class TestSessionsReset:
    @pytest.mark.asyncio
    async def test_reset_valid(self, dispatcher, ctx_with_sessions, session):
        before = session.session_id
        res = await dispatcher.dispatch(
            "r1", "sessions.reset", {"key": session.session_key}, ctx_with_sessions
        )
        assert res.ok is True
        assert res.payload["session_id"] != before
        assert res.payload["previous_session_id"] == before

    @pytest.mark.asyncio
    async def test_reset_allowed_for_operator_write_scope(self, dispatcher, session):
        ctx = make_ctx(
            session_manager=FakeSessionManager([session]),
            scopes=["operator.read", "operator.write"],
        )

        res = await dispatcher.dispatch("r1", "sessions.reset", {"key": session.session_key}, ctx)

        assert res.ok is True
        assert ctx.session_manager.applied_intents == [(session.session_key, "reset_same_key")]

    @pytest.mark.asyncio
    async def test_reset_lets_recently_completed_runtime_task_settle(self, dispatcher, session):
        class RuntimeSettlesAfterDoneRace:
            def __init__(self) -> None:
                self.status = "running"
                self.wait_calls: list[str] = []
                self.cancel_calls = 0
                self.cancelled = False

            async def list(self, session_key: str | None = None):
                assert session_key == session.session_key
                return [SimpleNamespace(task_id="task-race", status=self.status)]

            async def wait(self, task_id: str):
                self.wait_calls.append(task_id)
                self.status = "succeeded"
                return SimpleNamespace(task_id=task_id, status=self.status)

            async def cancel(self, session_key: str | None = None):
                self.cancel_calls += 1
                assert session_key == session.session_key
                if self.status in {"queued", "running"}:
                    self.cancelled = True
                    self.status = "cancelled"
                    return 1
                return 0

        runtime = RuntimeSettlesAfterDoneRace()
        ctx = make_ctx(session_manager=FakeSessionManager([session]), task_runtime=runtime)

        res = await dispatcher.dispatch("r1", "sessions.reset", {"key": session.session_key}, ctx)

        assert res.ok is True
        assert runtime.wait_calls == ["task-race"]
        assert runtime.cancel_calls == 1
        assert runtime.cancelled is False

    @pytest.mark.asyncio
    async def test_reset_not_found(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch(
            "r1", "sessions.reset", {"key": "nonexistent"}, ctx_with_sessions
        )
        assert res.ok is False
        assert res.error.code == "NOT_FOUND"


class TestSessionsDelete:
    @pytest.mark.asyncio
    async def test_delete_valid(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1", "sessions.delete", {"key": session.session_key}, ctx_with_sessions
        )
        assert res.ok is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch(
            "r1", "sessions.delete", {"key": "nonexistent"}, ctx_with_sessions
        )
        # Bulk-delete returns ok=True but populates errors list for missing keys
        assert res.ok is True
        assert res.payload["deleted"] == []
        assert len(res.payload["errors"]) == 1


class TestSessionsCompact:
    @pytest.mark.asyncio
    async def test_compact_valid(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1", "sessions.compact", {"key": session.session_key}, ctx_with_sessions
        )
        assert res.ok is True

    @pytest.mark.asyncio
    async def test_compact_allowed_for_operator_write_scope(self, dispatcher, session):
        ctx = make_ctx(
            session_manager=FakeSessionManager([session]),
            scopes=["operator.read", "operator.write"],
        )

        res = await dispatcher.dispatch("r1", "sessions.compact", {"key": session.session_key}, ctx)

        assert res.ok is True

    @pytest.mark.asyncio
    async def test_compact_not_found(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch(
            "r1", "sessions.compact", {"key": "nonexistent"}, ctx_with_sessions
        )
        assert res.ok is False
        assert res.error.code == "NOT_FOUND"


class TestSessionsContextCompact:
    @pytest.mark.asyncio
    async def test_context_compact_summarizes_instead_of_truncating(
        self, dispatcher, ctx_with_sessions, session
    ):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.contextCompact",
            {"key": session.session_key, "contextWindowTokens": 1234},
            ctx_with_sessions,
        )

        assert res.ok is True
        assert res.payload["key"] == session.session_key
        assert res.payload["compacted"] is True
        assert res.payload["mode"] == "summary"
        assert res.payload["summary_len"] == len(ctx_with_sessions.session_manager.compact_summary)
        assert res.payload["context_window_tokens"] == 1234
        compact_call = ctx_with_sessions.session_manager.compact_calls[0]
        assert compact_call[:2] == (session.session_key, 1234)
        assert ctx_with_sessions.session_manager.truncate_calls == []

    @pytest.mark.asyncio
    async def test_context_compact_allowed_for_operator_write_scope(self, dispatcher, session):
        ctx = make_ctx(
            session_manager=FakeSessionManager([session]),
            scopes=["operator.read", "operator.write"],
        )

        res = await dispatcher.dispatch(
            "r1", "sessions.contextCompact", {"key": session.session_key}, ctx
        )

        assert res.ok is True
        assert ctx.session_manager.compact_calls[0][:2] == (
            session.session_key,
            ctx.config.context_budget_tokens,
        )

    @pytest.mark.asyncio
    async def test_context_compact_passes_provider_config_without_flush_receipt(
        self, dispatcher
    ):
        session = FakeSession(session_key="agent:main:abc123", model="session/model")
        manager = FakeSessionManager([session])
        selector = _FakeProviderSelector()
        flush_service = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("no flush")))
        ctx = make_ctx(
            session_manager=manager,
            provider_selector=selector,
            flush_service=flush_service,
        )

        res = await dispatcher.dispatch(
            "r1",
            "sessions.contextCompact",
            {"key": session.session_key, "contextWindowTokens": 1234},
            ctx,
        )

        assert res.ok is True
        assert "flush_receipt" not in res.payload
        assert res.payload["summary_source"] == "fallback"
        flush_service.execute.assert_not_called()
        config = manager.compact_calls[0][2]
        assert isinstance(config, CompactionConfig)
        assert config.api_key == "provider-key"
        assert config.model == "session/model"
        assert config.base_url == "https://openrouter.ai/api/v1"

    @pytest.mark.asyncio
    async def test_context_compact_uses_model_override_on_clone_only(self, dispatcher):
        session = FakeSession(
            session_key="agent:main:abc123",
            model="session/model",
            model_override="routed/model",
        )
        manager = FakeSessionManager([session])
        selector = _FakeProviderSelector()
        ctx = make_ctx(session_manager=manager, provider_selector=selector)

        res = await dispatcher.dispatch(
            "r1",
            "sessions.contextCompact",
            {"key": session.session_key, "contextWindowTokens": 1234},
            ctx,
        )

        assert res.ok is True
        config = manager.compact_calls[0][2]
        assert isinstance(config, CompactionConfig)
        assert config.model == "routed/model"
        assert selector.override_calls == []
        assert selector.clone_instance.override_calls == ["routed/model"]

    @pytest.mark.asyncio
    async def test_context_compact_legacy_manager_reports_unknown_source(self, dispatcher):
        session = FakeSession(session_key="agent:main:abc123")
        manager = _LegacyCompactManager(session)
        ctx = make_ctx(session_manager=manager, provider_selector=_FakeProviderSelector())

        res = await dispatcher.dispatch(
            "r1",
            "sessions.contextCompact",
            {"key": session.session_key, "contextWindowTokens": 1234},
            ctx,
        )

        assert res.ok is True
        assert res.payload["summary_source"] == "unknown"
        assert manager.compact_calls == [(session.session_key, 1234)]

    @pytest.mark.asyncio
    async def test_context_compact_not_found(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch(
            "r1", "sessions.contextCompact", {"key": "nonexistent"}, ctx_with_sessions
        )
        assert res.ok is False
        assert res.error.code == "NOT_FOUND"


class TestSessionsSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch("r1", "sessions.subscribe", None, ctx_with_sessions)
        assert res.ok is True

    @pytest.mark.asyncio
    async def test_unsubscribe(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch("r1", "sessions.unsubscribe", None, ctx_with_sessions)
        assert res.ok is True


class TestSessionsMessagesSubscribe:
    @pytest.mark.asyncio
    async def test_messages_subscribe(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.messages.subscribe",
            {"key": session.session_key},
            ctx_with_sessions,
        )
        assert res.ok is True
        assert res.payload["subscribed"] is False
        assert res.payload["key"] == session.session_key
        assert isinstance(res.payload["current_stream_seq"], int)
        assert res.payload["replay_complete"] is True
        assert res.payload["replayed_count"] == 0

    @pytest.mark.asyncio
    async def test_messages_subscribe_replays_buffered_events_after_cursor(self, dispatcher):
        key = "agent:main:replay-test"
        stream_registry = get_session_streams()
        first = stream_registry.record(key, "session.event.text_delta", {"text": "old"})
        second = stream_registry.record(key, "session.event.done", {"reason": "stop"})

        conn_id = "replay-test-conn"
        conn = _ReplayConn(conn_id)
        registry = get_registry()
        registry.register(conn)
        try:
            ctx = make_ctx(
                session_manager=FakeSessionManager([FakeSession(session_key=key)]),
                conn_id=conn_id,
                subscription_manager=SubscriptionManager(),
            )

            res = await dispatcher.dispatch(
                "r1",
                "sessions.messages.subscribe",
                {"key": key, "since_stream_seq": first["stream_seq"]},
                ctx,
            )
        finally:
            registry.unregister(conn_id)

        assert res.ok is True
        assert res.payload["subscribed"] is True
        assert res.payload["current_stream_seq"] == second["stream_seq"]
        assert res.payload["replay_complete"] is True
        assert res.payload["replayed_count"] == 1
        assert conn.events == [("session.event.done", second)]

    @pytest.mark.asyncio
    async def test_messages_subscribe_replays_task_group_events(self, dispatcher):
        key = "agent:main:task-group-replay-test"
        stream_registry = get_session_streams()
        waiting = stream_registry.record(
            key,
            "session.event.task_group.waiting",
            {"group_id": "group-1", "parent_task_id": "task-parent", "status": "waiting"},
        )
        done = stream_registry.record(
            key,
            "session.event.task_group.done",
            {
                "group_id": "group-1",
                "parent_task_id": "task-parent",
                "status": "done",
                "delivery_status": "sent",
            },
        )

        conn_id = "task-group-replay-test-conn"
        conn = _ReplayConn(conn_id)
        registry = get_registry()
        registry.register(conn)
        try:
            ctx = make_ctx(
                session_manager=FakeSessionManager([FakeSession(session_key=key)]),
                conn_id=conn_id,
                subscription_manager=SubscriptionManager(),
            )

            res = await dispatcher.dispatch(
                "r1",
                "sessions.messages.subscribe",
                {"key": key, "since_stream_seq": waiting["stream_seq"]},
                ctx,
            )
        finally:
            registry.unregister(conn_id)

        assert res.ok is True
        assert res.payload["replayed_count"] == 1
        assert conn.events == [("session.event.task_group.done", done)]

    @pytest.mark.asyncio
    async def test_messages_subscribe_reports_persisted_task_state_and_replay_gap(
        self, dispatcher
    ):
        key = "agent:main:webchat:restarted"
        session = FakeSession(session_key=key)
        manager = FakeSessionManager([session])
        manager._storage._agent_tasks[key] = [
            SimpleNamespace(
                task_id="task-abandoned",
                status="abandoned",
                queue_mode="followup",
                run_kind="web_turn",
                source_kind="webui",
                created_at=100,
                started_at=110,
                finished_at=120,
                terminal_reason="process_restart",
            )
        ]
        ctx = make_ctx(session_manager=manager, subscription_manager=SubscriptionManager())

        res = await dispatcher.dispatch(
            "r1",
            "sessions.messages.subscribe",
            {"key": key, "since_stream_seq": 7},
            ctx,
        )

        assert res.ok is True
        assert res.payload["replay_complete"] is False
        assert res.payload["replay_gap_reason"] == "stream_buffer_reset"
        assert res.payload["last_task"]["task_id"] == "task-abandoned"
        assert res.payload["run_status"] == "interrupted"

    @pytest.mark.asyncio
    async def test_messages_subscribe_missing_key(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch(
            "r1", "sessions.messages.subscribe", None, ctx_with_sessions
        )
        assert res.ok is False
        assert res.error.code == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_messages_unsubscribe(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.messages.unsubscribe",
            {"key": session.session_key},
            ctx_with_sessions,
        )
        assert res.ok is True


class TestSessionsPreview:
    @pytest.mark.asyncio
    async def test_preview_all(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch("r1", "sessions.preview", None, ctx_with_sessions)
        assert res.ok is True
        assert "ts" in res.payload
        assert "previews" in res.payload
        assert len(res.payload["previews"]) == 1

    @pytest.mark.asyncio
    async def test_preview_by_keys(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.preview",
            {"keys": [session.session_key]},
            ctx_with_sessions,
        )
        assert res.ok is True
        assert len(res.payload["previews"]) == 1

    @pytest.mark.asyncio
    async def test_preview_no_manager(self, dispatcher, ctx_no_manager):
        res = await dispatcher.dispatch("r1", "sessions.preview", None, ctx_no_manager)
        assert res.ok is True
        assert res.payload["previews"] == []


class TestSessionsResolve:
    @pytest.mark.asyncio
    async def test_resolve_valid(self, dispatcher, ctx_with_sessions, session):
        res = await dispatcher.dispatch(
            "r1",
            "sessions.resolve",
            {"key": session.session_key},
            ctx_with_sessions,
        )
        assert res.ok is True
        assert res.payload["session_key"] == session.session_key

    @pytest.mark.asyncio
    async def test_resolve_by_session_id(self, dispatcher):
        session = FakeSession(session_key="agent:default:abc123", session_id="abc123")
        ctx = make_ctx(session_manager=FakeSessionManager([session]))

        res = await dispatcher.dispatch(
            "r1",
            "sessions.resolve",
            {"key": "abc123"},
            ctx,
        )

        assert res.ok is True
        assert res.payload["session_key"] == "agent:default:abc123"

    @pytest.mark.asyncio
    async def test_resolve_by_unique_short_prefix(self, dispatcher):
        session = FakeSession(session_key="agent:default:abc123", session_id="abc123")
        other = FakeSession(session_key="agent:default:def456", session_id="def456")
        ctx = make_ctx(session_manager=FakeSessionManager([session, other]))

        res = await dispatcher.dispatch(
            "r1",
            "sessions.resolve",
            {"key": "abc"},
            ctx,
        )

        assert res.ok is True
        assert res.payload["session_key"] == "agent:default:abc123"

    @pytest.mark.asyncio
    async def test_resolve_rejects_ambiguous_prefix(self, dispatcher):
        one = FakeSession(session_key="agent:default:abc123", session_id="abc123")
        two = FakeSession(session_key="agent:bench:abc999", session_id="abc999")
        ctx = make_ctx(session_manager=FakeSessionManager([one, two]))

        res = await dispatcher.dispatch(
            "r1",
            "sessions.resolve",
            {"key": "abc"},
            ctx,
        )

        assert res.ok is False
        assert res.error.code == "INVALID_REQUEST"
        assert "Ambiguous session id" in res.error.message

    @pytest.mark.asyncio
    async def test_resolve_not_found(self, dispatcher, ctx_with_sessions):
        res = await dispatcher.dispatch(
            "r1", "sessions.resolve", {"key": "nonexistent"}, ctx_with_sessions
        )
        assert res.ok is False
        assert res.error.code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_scope_enforcement(self, dispatcher, session):
        """sessions.create requires operator.write."""
        ctx = make_ctx(
            scopes=["operator.read"],
            session_manager=FakeSessionManager([session]),
        )
        res = await dispatcher.dispatch("r1", "sessions.create", {"agentId": "test"}, ctx)
        assert res.ok is False
        assert res.error.code == "UNAUTHORIZED"
