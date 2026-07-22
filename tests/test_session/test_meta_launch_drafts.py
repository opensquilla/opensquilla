"""Durability and lifecycle contracts for unaccepted MetaSkill requests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import opensquilla.session.storage as storage_module
from opensquilla.session.models import (
    AgentTaskRecord,
    AgentTaskStatus,
    SessionNode,
    TranscriptEntry,
)
from opensquilla.session.storage import (
    MetaLaunchDraftCapacityError,
    MetaLaunchDraftConflictError,
    MetaLaunchDraftUnavailableError,
    SessionStorage,
)

SESSION_KEY = "agent:main:webchat:durable-meta-draft"
SESSION_ID = "durable-meta-draft-session"
REQUEST_ID = "durable-meta-draft-request"
LAUNCH_TEXT = "/meta meta-paper-write -- Write the full paper with cited sources"


def _session() -> SessionNode:
    return SessionNode(
        session_key=SESSION_KEY,
        session_id=SESSION_ID,
        agent_id="main",
        created_at=100,
        updated_at=100,
        epoch=0,
    )


@pytest.mark.asyncio
async def test_draft_survives_reopen_and_acceptance_consumes_it_atomically(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sessions.db"
    storage = await SessionStorage.open(str(db_path))
    try:
        await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
            meta_skill_name="meta-paper-write",
            launch_text=LAUNCH_TEXT,
        )
    finally:
        await storage.close()

    reopened = await SessionStorage.open(str(db_path))
    try:
        recovered = await reopened.list_meta_launch_drafts(agent_id="main")
        assert [(draft.client_request_id, draft.launch_text) for draft in recovered] == [
            (REQUEST_ID, LAUNCH_TEXT)
        ]

        await reopened.upsert_session(_session())
        intent, _ = await reopened.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=f"request:{REQUEST_ID}",
            meta_skill_name="meta-paper-write",
        )
        control = {
            "version": 1,
            "intent_id": intent.intent_id,
            "kind": "manual",
            "name": "meta-paper-write",
            "correlation_id": intent.correlation_id,
        }
        entry = TranscriptEntry(
            session_id=SESSION_ID,
            session_key=SESSION_KEY,
            message_id="durable-meta-draft-message",
            role="user",
            content=LAUNCH_TEXT,
            created_at=200,
            turn_context={"meta_control": control},
        )
        task = AgentTaskRecord(
            task_id="durable-meta-draft-task",
            session_key=SESSION_KEY,
            agent_id="main",
            source_kind="webui",
            queue_mode="followup",
            run_kind="web_turn",
            status=AgentTaskStatus.QUEUED,
            created_at=200,
            updated_at=200,
            details={"metadata": {"meta_control": control}},
        )

        await reopened.accept_turn(
            entry,
            expected_epoch=0,
            updated_at=200,
            task_record=task,
            source_scope="webui",
            request_session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
            request_fingerprint="sha256:durable-meta-draft",
            meta_control_intent_id=intent.intent_id,
        )

        assert await reopened.list_meta_launch_drafts(session_key=SESSION_KEY) == []
        assert not await reopened.discard_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
        )
        accepted_intent = await reopened.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=f"request:{REQUEST_ID}",
        )
        assert accepted_intent is not None
        assert accepted_intent.status == "accepted"
        transcript = await reopened.get_transcript(SESSION_ID)
        assert transcript[0].content == LAUNCH_TEXT
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_reset_and_delete_remove_session_drafts_including_provisional_key(
    tmp_path: Path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())
        await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id="before-reset",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- reset me",
        )
        assert await storage.advance_reset_epoch(SESSION_KEY) == 1
        assert await storage.list_meta_launch_drafts(session_key=SESSION_KEY) == []

        await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id="before-delete",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- delete me",
        )
        await storage.delete_session(SESSION_KEY)
        assert await storage.list_meta_launch_drafts(session_key=SESSION_KEY) == []

        provisional = "agent:main:webchat:provisional-only"
        await storage.stage_meta_launch_draft(
            session_key=provisional,
            client_request_id="provisional-delete",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- never accepted",
        )
        await storage.promote_meta_launch_draft(
            session_key=provisional,
            client_request_id="provisional-delete",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- never accepted",
        )
        await storage.delete_session(provisional)
        assert await storage.list_meta_launch_drafts(session_key=provisional) == []
        assert await storage.get_meta_control_intent(
            session_key=provisional,
            control_kind="manual",
            correlation_id="request:provisional-delete",
        ) is None
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_draft_identity_ttl_and_capacity_are_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage_module, "_META_LAUNCH_DRAFT_PER_SESSION_LIMIT", 2)
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        first, disposition = await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id="request-1",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- first",
        )
        replayed, replay_disposition = await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id="request-1",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- first",
        )
        assert replayed.draft_id == first.draft_id
        assert (disposition, replay_disposition) == ("stamped", "replayed")

        with pytest.raises(MetaLaunchDraftConflictError):
            await storage.stage_meta_launch_draft(
                session_key=SESSION_KEY,
                client_request_id="request-1",
                meta_skill_name="meta-paper-write",
                launch_text="/meta meta-paper-write -- changed",
            )

        await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id="request-2",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- second",
        )
        with pytest.raises(MetaLaunchDraftCapacityError):
            await storage.stage_meta_launch_draft(
                session_key=SESSION_KEY,
                client_request_id="request-3",
                meta_skill_name="meta-paper-write",
                launch_text="/meta meta-paper-write -- third",
            )

        await storage.conn.execute(
            "UPDATE meta_launch_drafts SET expires_at = 1 WHERE draft_id = ?",
            (first.draft_id,),
        )
        await storage.conn.commit()
        await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id="request-3",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- third",
        )
        recovered = await storage.list_meta_launch_drafts(session_key=SESSION_KEY)
        assert [draft.client_request_id for draft in recovered] == ["request-2", "request-3"]
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_agent_recovery_uses_an_exact_agent_prefix_before_limit(
    tmp_path: Path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        # SQLite LIKE treats ``_`` as a wildcard. A lookalike agent created
        # first must not consume the bounded recovery page for ``main_test``.
        await storage.stage_meta_launch_draft(
            session_key="agent:mainXtest:webchat:lookalike",
            client_request_id="lookalike",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- lookalike",
        )
        await storage.stage_meta_launch_draft(
            session_key="agent:main_test:webchat:exact",
            client_request_id="exact",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- exact",
        )

        recovered = await storage.list_meta_launch_drafts(agent_id="main_test", limit=1)

        assert [draft.client_request_id for draft in recovered] == ["exact"]
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_discarded_draft_cannot_be_promoted_after_slow_readiness_boundary(
    tmp_path: Path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
            meta_skill_name="meta-paper-write",
            launch_text=LAUNCH_TEXT,
        )
        assert await storage.discard_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
        )

        with pytest.raises(MetaLaunchDraftUnavailableError):
            await storage.promote_meta_launch_draft(
                session_key=SESSION_KEY,
                client_request_id=REQUEST_ID,
                meta_skill_name="meta-paper-write",
                launch_text=LAUNCH_TEXT,
            )
        assert await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=f"request:{REQUEST_ID}",
        ) is None
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_listing_physically_purges_expired_prompt_and_staged_control(
    tmp_path: Path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        draft, _ = await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
            meta_skill_name="meta-paper-write",
            launch_text=LAUNCH_TEXT,
        )
        await storage.promote_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
            meta_skill_name="meta-paper-write",
            launch_text=LAUNCH_TEXT,
        )
        await storage.conn.execute(
            "UPDATE meta_launch_drafts SET expires_at = 1 WHERE draft_id = ?",
            (draft.draft_id,),
        )
        await storage.conn.commit()

        assert await storage.list_meta_launch_drafts(session_key=SESSION_KEY) == []
        async with storage.conn.execute(
            "SELECT COUNT(*) FROM meta_launch_drafts WHERE draft_id = ?",
            (draft.draft_id,),
        ) as cur:
            assert (await cur.fetchone())[0] == 0
        assert await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=f"request:{REQUEST_ID}",
        ) is None
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_discard_is_idempotent_after_committed_response_loss(tmp_path: Path) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
            meta_skill_name="meta-paper-write",
            launch_text=LAUNCH_TEXT,
        )
        assert await storage.discard_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
        )
        assert await storage.discard_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
        )
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_periodic_gc_physically_enforces_retention_while_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage_module, "_META_LAUNCH_DRAFT_GC_INTERVAL_SECONDS", 0.01)
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        draft, _ = await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id=REQUEST_ID,
            meta_skill_name="meta-paper-write",
            launch_text=LAUNCH_TEXT,
        )
        await storage.conn.execute(
            "UPDATE meta_launch_drafts SET expires_at = 1 WHERE draft_id = ?",
            (draft.draft_id,),
        )
        await storage.conn.commit()

        for _ in range(50):
            async with storage.conn.execute(
                "SELECT COUNT(*) FROM meta_launch_drafts WHERE draft_id = ?",
                (draft.draft_id,),
            ) as cur:
                if (await cur.fetchone())[0] == 0:
                    break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("periodic retention cleanup did not remove the expired raw prompt")
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_open_physically_purges_expired_prompt_without_a_list_call(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sessions.db"
    storage = await SessionStorage.open(str(db_path))
    draft, _ = await storage.stage_meta_launch_draft(
        session_key=SESSION_KEY,
        client_request_id=REQUEST_ID,
        meta_skill_name="meta-paper-write",
        launch_text=LAUNCH_TEXT,
    )
    await storage.conn.execute(
        "UPDATE meta_launch_drafts SET expires_at = 1 WHERE draft_id = ?",
        (draft.draft_id,),
    )
    await storage.conn.commit()
    await storage.close()

    reopened = await SessionStorage.open(str(db_path))
    try:
        async with reopened.conn.execute(
            "SELECT COUNT(*) FROM meta_launch_drafts WHERE draft_id = ?",
            (draft.draft_id,),
        ) as cur:
            assert (await cur.fetchone())[0] == 0
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_provisional_agent_recovery_is_not_starved_by_existing_sessions(
    tmp_path: Path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        for index in range(20):
            key = f"agent:main:webchat:existing-{index:02d}"
            await storage.upsert_session(SessionNode(
                session_key=key,
                session_id=f"existing-session-{index:02d}",
                agent_id="main",
                created_at=100 + index,
                updated_at=100 + index,
            ))
            await storage.stage_meta_launch_draft(
                session_key=key,
                client_request_id=f"existing-request-{index:02d}",
                meta_skill_name="meta-paper-write",
                launch_text=f"/meta meta-paper-write -- existing {index}",
            )
        provisional_key = "agent:main:webchat:provisional-after-twenty"
        await storage.stage_meta_launch_draft(
            session_key=provisional_key,
            client_request_id="provisional-after-twenty",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- recover the provisional chat",
        )

        recovered = await storage.list_meta_launch_drafts(
            agent_id="main",
            provisional_only=True,
        )

        assert [(draft.session_key, draft.client_request_id) for draft in recovered] == [
            (provisional_key, "provisional-after-twenty")
        ]
    finally:
        await storage.close()
