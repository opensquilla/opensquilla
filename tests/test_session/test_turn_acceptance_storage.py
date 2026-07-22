"""Storage contract tests for durable, idempotent turn acceptance."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from opensquilla.session.models import (
    AgentTaskRecord,
    AgentTaskStatus,
    SessionNode,
    SessionStatus,
    TranscriptEntry,
)
from opensquilla.session.storage import (
    MetaLaunchDraftDiscardedError,
    SessionStorage,
    StorageBusyError,
)

SESSION_KEY = "agent:main:webchat:durable-acceptance"
SESSION_ID = "session-durable-acceptance"


def _session(*, updated_at: int = 100) -> SessionNode:
    return SessionNode(
        session_key=SESSION_KEY,
        session_id=SESSION_ID,
        agent_id="main",
        created_at=100,
        updated_at=updated_at,
        epoch=0,
    )


def _entry(message_id: str, *, content: str = "hello", created_at: int = 200) -> TranscriptEntry:
    return TranscriptEntry(
        session_id=SESSION_ID,
        session_key=SESSION_KEY,
        message_id=message_id,
        role="user",
        content=content,
        created_at=created_at,
    )


def _task(task_id: str, *, updated_at: int = 200) -> AgentTaskRecord:
    return AgentTaskRecord(
        task_id=task_id,
        session_key=SESSION_KEY,
        agent_id="main",
        source_kind="webui",
        queue_mode="followup",
        run_kind="web_turn",
        status=AgentTaskStatus.QUEUED,
        created_at=updated_at,
        updated_at=updated_at,
    )


async def _accept_turn(
    storage: SessionStorage,
    *,
    message_id: str,
    task_id: str,
    request_id: str = "request-one",
    fingerprint: str = "sha256:request-one",
    updated_at: int = 200,
) -> Any:
    return await storage.accept_turn(
        _entry(message_id, created_at=updated_at),
        expected_epoch=0,
        updated_at=updated_at,
        task_record=_task(task_id, updated_at=updated_at),
        source_scope="webui",
        request_session_key=SESSION_KEY,
        client_request_id=request_id,
        request_fingerprint=fingerprint,
    )


def _result_value(result: Any, name: str) -> Any:
    """Read an accepted identifier from either a result or its receipt member."""

    if isinstance(result, dict):
        candidate = result.get("receipt", result)
    else:
        candidate = getattr(result, "receipt", result)
    if isinstance(candidate, dict):
        return candidate[name]
    return getattr(candidate, name)


async def _row_count(storage: SessionStorage, table: str) -> int:
    async with storage.conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:
        row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def _receipt_rows(storage: SessionStorage) -> list[dict[str, Any]]:
    async with storage.conn.execute(
        "SELECT * FROM turn_ingress_receipts ORDER BY accepted_at, receipt_id"
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


@pytest.mark.asyncio
async def test_meta_control_staging_prunes_only_abandoned_rows_after_30_days(
    tmp_path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        old, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:old-staged",
            meta_skill_name="meta-paper-write",
        )
        accepted, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:old-accepted",
            meta_skill_name="meta-paper-write",
        )
        await storage.conn.execute(
            "UPDATE meta_control_intents SET created_at = 1 WHERE intent_id IN (?, ?)",
            (old.intent_id, accepted.intent_id),
        )
        await storage.conn.execute(
            "UPDATE meta_control_intents SET status = 'accepted' WHERE intent_id = ?",
            (accepted.intent_id,),
        )
        await storage.conn.commit()

        recent, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:recent-staged",
            meta_skill_name="meta-paper-write",
        )

        assert await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:old-staged",
        ) is None
        assert await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:old-accepted",
        ) is not None
        assert await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:recent-staged",
        ) == recent
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_reset_epoch_invalidates_staged_and_fences_recent_accepted_controls(
    tmp_path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())
        staged, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:staged-before-reset",
            meta_skill_name="meta-paper-write",
        )
        accepted, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:accepted-before-reset",
            meta_skill_name="meta-paper-write",
        )
        await storage.conn.execute(
            "UPDATE meta_control_intents SET status = 'accepted' WHERE intent_id = ?",
            (accepted.intent_id,),
        )
        await storage.conn.commit()

        assert await storage.advance_reset_epoch(SESSION_KEY) == 1

        assert await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=staged.correlation_id,
        ) is None
        preserved = await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=accepted.correlation_id,
        )
        assert preserved is not None
        assert preserved.intent_id == accepted.intent_id
        assert preserved.status == "accepted"
        assert await storage.is_meta_launch_discarded(
            session_key=SESSION_KEY,
            client_request_id="staged-before-reset",
        )
        assert await storage.is_meta_launch_discarded(
            session_key=SESSION_KEY,
            client_request_id="accepted-before-reset",
        )
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_atomic_turn_reset_invalidates_staged_meta_controls(tmp_path) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())
        staged, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:before-atomic-reset",
            meta_skill_name="meta-paper-write",
        )
        await storage.stage_meta_launch_draft(
            session_key=SESSION_KEY,
            client_request_id="atomic-reset-turn",
            meta_skill_name="meta-paper-write",
            launch_text="/meta meta-paper-write -- stale collision with reset ingress",
        )
        reset_node = _session(updated_at=300)
        reset_node.session_id = "session-after-atomic-reset"
        reset_node.epoch = 1

        await storage.accept_turn(
            TranscriptEntry(
                session_id=reset_node.session_id,
                session_key=SESSION_KEY,
                message_id="message-after-atomic-reset",
                role="user",
                content="start over with this message",
                created_at=300,
            ),
            expected_epoch=1,
            updated_at=300,
            task_record=AgentTaskRecord(
                task_id="task-after-atomic-reset",
                session_key=SESSION_KEY,
                agent_id="main",
                source_kind="webui",
                queue_mode="followup",
                run_kind="web_turn",
                status=AgentTaskStatus.QUEUED,
                created_at=300,
                updated_at=300,
            ),
            source_scope="webui",
            request_session_key=SESSION_KEY,
            client_request_id="atomic-reset-turn",
            request_fingerprint="sha256:atomic-reset-turn",
            session_node=reset_node,
            reset_from_session_id=SESSION_ID,
        )

        assert await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=staged.correlation_id,
        ) is None
        rotated = await storage.get_session(SESSION_KEY)
        assert rotated is not None
        assert rotated.session_id == reset_node.session_id
        assert rotated.epoch == 1
        with pytest.raises(MetaLaunchDraftDiscardedError):
            await storage.stage_meta_launch_draft(
                session_key=SESSION_KEY,
                client_request_id="atomic-reset-turn",
                meta_skill_name="meta-paper-write",
                launch_text="/meta meta-paper-write -- stale collision with reset ingress",
            )
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_atomic_turn_reset_preserves_only_control_accepted_by_new_turn(
    tmp_path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())
        stale, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:stale-before-reset",
            meta_skill_name="meta-paper-write",
        )
        accepted_old, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:accepted-before-atomic-reset",
            meta_skill_name="meta-paper-write",
        )
        await storage.conn.execute(
            "UPDATE meta_control_intents SET status = 'accepted' WHERE intent_id = ?",
            (accepted_old.intent_id,),
        )
        await storage.conn.commit()
        current, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id="request:current-reset-turn",
            meta_skill_name="meta-paper-write",
        )
        control = {
            "version": 1,
            "intent_id": current.intent_id,
            "kind": "manual",
            "name": "meta-paper-write",
            "correlation_id": current.correlation_id,
        }
        reset_node = _session(updated_at=300)
        reset_node.session_id = "session-after-meta-control-reset"
        reset_node.epoch = 1
        entry = TranscriptEntry(
            session_id=reset_node.session_id,
            session_key=SESSION_KEY,
            message_id="message-current-reset-turn",
            role="user",
            content="/meta meta-paper-write -- start in the reset session",
            created_at=300,
            turn_context={"meta_control": control},
        )
        task = AgentTaskRecord(
            task_id="task-current-reset-turn",
            session_key=SESSION_KEY,
            agent_id="main",
            source_kind="webui",
            queue_mode="followup",
            run_kind="web_turn",
            status=AgentTaskStatus.QUEUED,
            created_at=300,
            updated_at=300,
            details={"metadata": {"meta_control": control}},
        )

        accepted = await storage.accept_turn(
            entry,
            expected_epoch=1,
            updated_at=300,
            task_record=task,
            source_scope="webui",
            request_session_key=SESSION_KEY,
            client_request_id="current-reset-turn",
            request_fingerprint="sha256:current-reset-turn",
            session_node=reset_node,
            reset_from_session_id=SESSION_ID,
            meta_control_intent_id=current.intent_id,
        )

        assert accepted.replayed is False
        assert await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=stale.correlation_id,
        ) is None
        preserved = await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=current.correlation_id,
        )
        assert preserved is not None
        assert preserved.status == "accepted"
        assert preserved.accepted_task_id == task.task_id
        accepted_history = await storage.get_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=accepted_old.correlation_id,
        )
        assert accepted_history is not None
        assert accepted_history.status == "accepted"
        assert await storage.is_meta_launch_discarded(
            session_key=SESSION_KEY,
            client_request_id="stale-before-reset",
        )
        assert await storage.is_meta_launch_discarded(
            session_key=SESSION_KEY,
            client_request_id="accepted-before-atomic-reset",
        )
        assert not await storage.is_meta_launch_discarded(
            session_key=SESSION_KEY,
            client_request_id="current-reset-turn",
        )
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_meta_control_recovery_quarantines_invalid_head_before_claiming_valid(
    tmp_path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())

        async def accept_control(index: int) -> AgentTaskRecord:
            request_id = f"recovery-{index}"
            message_id = f"recovery-message-{index}"
            task_id = f"recovery-task-{index}"
            created_at = 200 + index
            intent, _ = await storage.stage_meta_control_intent(
                session_key=SESSION_KEY,
                control_kind="manual",
                correlation_id=f"request:{request_id}",
                meta_skill_name="meta-paper-write",
            )
            control = {
                "version": 1,
                "intent_id": intent.intent_id,
                "kind": "manual",
                "name": "meta-paper-write",
                "correlation_id": f"request:{request_id}",
            }
            entry = TranscriptEntry(
                session_id=SESSION_ID,
                session_key=SESSION_KEY,
                message_id=message_id,
                role="user",
                content=f"/meta meta-paper-write -- recovery {index}",
                created_at=created_at,
                turn_context={"meta_control": control},
            )
            task = AgentTaskRecord(
                task_id=task_id,
                session_key=SESSION_KEY,
                agent_id="main",
                source_kind="webui",
                queue_mode="followup",
                run_kind="web_turn",
                status=AgentTaskStatus.QUEUED,
                created_at=created_at,
                updated_at=created_at,
                details={
                    "metadata": {"meta_control": control},
                    "persisted_user_message_id": message_id,
                },
            )
            await storage.accept_turn(
                entry,
                expected_epoch=0,
                updated_at=created_at,
                task_record=task,
                source_scope="webui",
                request_session_key=SESSION_KEY,
                client_request_id=request_id,
                request_fingerprint=f"sha256:{request_id}",
                meta_control_intent_id=intent.intent_id,
            )
            return task

        invalid = await accept_control(0)
        valid = await accept_control(1)
        assert await storage.mark_abandoned_agent_tasks(now_ms=300) == 2
        await storage.conn.execute(
            "UPDATE agent_tasks SET details = '{}' WHERE task_id = ?",
            (invalid.task_id,),
        )
        await storage.conn.commit()

        claimed = await storage.claim_recoverable_meta_control_tasks(limit=1)

        assert [item.task.task_id for item in claimed] == [valid.task_id]
        quarantined = await storage.get_agent_task(invalid.task_id)
        assert quarantined is not None
        assert quarantined.status == AgentTaskStatus.ABANDONED
        assert quarantined.terminal_reason == "meta_control_recovery_invalid"
        assert quarantined.error_class == "MetaControlRecoveryInvalid"
        assert await storage.claim_recoverable_meta_control_tasks(limit=1) == []
    finally:
        await storage.close()


@pytest.mark.parametrize(
    "terminal_status",
    [
        SessionStatus.DONE,
        SessionStatus.FAILED,
        SessionStatus.KILLED,
        SessionStatus.TIMEOUT,
    ],
)
@pytest.mark.asyncio
async def test_meta_control_recovery_never_reopens_terminal_session(
    tmp_path,
    terminal_status: SessionStatus,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())
        request_id = f"terminal-{terminal_status.value}"
        intent, _ = await storage.stage_meta_control_intent(
            session_key=SESSION_KEY,
            control_kind="manual",
            correlation_id=f"request:{request_id}",
            meta_skill_name="meta-paper-write",
        )
        control = {
            "version": 1,
            "intent_id": intent.intent_id,
            "kind": "manual",
            "name": "meta-paper-write",
            "correlation_id": f"request:{request_id}",
        }
        message_id = f"message-{terminal_status.value}"
        task_id = f"task-{terminal_status.value}"
        await storage.accept_turn(
            TranscriptEntry(
                session_id=SESSION_ID,
                session_key=SESSION_KEY,
                message_id=message_id,
                role="user",
                content="/meta meta-paper-write -- terminal recovery",
                created_at=200,
                turn_context={"meta_control": control},
            ),
            expected_epoch=0,
            updated_at=200,
            task_record=AgentTaskRecord(
                task_id=task_id,
                session_key=SESSION_KEY,
                agent_id="main",
                source_kind="webui",
                queue_mode="followup",
                run_kind="web_turn",
                status=AgentTaskStatus.QUEUED,
                created_at=200,
                updated_at=200,
                details={
                    "metadata": {"meta_control": control},
                    "persisted_user_message_id": message_id,
                },
            ),
            source_scope="webui",
            request_session_key=SESSION_KEY,
            client_request_id=request_id,
            request_fingerprint=f"sha256:{request_id}",
            meta_control_intent_id=intent.intent_id,
        )
        terminal = await storage.get_session(SESSION_KEY)
        assert terminal is not None
        terminal.status = terminal_status
        terminal.ended_at = 250
        terminal.runtime_ms = 150
        await storage.upsert_session(terminal)

        assert await storage.mark_abandoned_agent_tasks(now_ms=300) == 1
        abandoned = await storage.get_agent_task(task_id)
        assert abandoned is not None
        assert abandoned.status == AgentTaskStatus.ABANDONED
        assert abandoned.terminal_reason == "process_restart"

        # Databases opened once by the buggy build may already carry the
        # recovery marker. The claim path must reject those rows independently
        # rather than trusting only the current restart-marking pass.
        await storage.conn.execute(
            "UPDATE agent_tasks SET terminal_reason = ? WHERE task_id = ?",
            ("meta_control_restart_before_start", task_id),
        )
        await storage.conn.commit()

        assert await storage.claim_recoverable_meta_control_tasks() == []
        preserved = await storage.get_session(SESSION_KEY)
        assert preserved is not None
        assert preserved.status == terminal_status
        assert preserved.ended_at == 250
        assert preserved.runtime_ms == 150
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_accept_turn_commits_message_session_task_and_receipt_together(tmp_path) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())

        result = await _accept_turn(
            storage,
            message_id="message-one",
            task_id="task-one",
        )

        transcript = await storage.get_transcript(SESSION_ID)
        session = await storage.get_session(SESSION_KEY)
        task = await storage.get_agent_task("task-one")
        receipts = await _receipt_rows(storage)

        assert [entry.message_id for entry in transcript] == ["message-one"]
        assert session is not None
        assert session.updated_at == 200
        assert task is not None
        assert task.status == AgentTaskStatus.QUEUED
        assert task.details is not None
        assert task.details["persisted_user_message_id"] == "message-one"
        assert task.details["persisted_user_message_ids"] == ["message-one"]
        assert task.details["message_count"] == 1
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt["receipt_id"]
        assert receipt["accepted_at"] >= 200
        assert {
            key: receipt[key]
            for key in (
                "source_scope",
                "request_session_key",
                "client_request_id",
                "request_fingerprint",
                "accepted_session_key",
                "session_id",
                "message_id",
                "task_id",
                "schema_version",
            )
        } == {
            "source_scope": "webui",
            "request_session_key": SESSION_KEY,
            "client_request_id": "request-one",
            "request_fingerprint": "sha256:request-one",
            "accepted_session_key": SESSION_KEY,
            "session_id": SESSION_ID,
            "message_id": "message-one",
            "task_id": "task-one",
            "schema_version": 1,
        }
        assert _result_value(result, "message_id") == "message-one"
        assert _result_value(result, "task_id") == "task-one"
        assert _result_value(result, "session_id") == SESSION_ID
    finally:
        await storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_table", ["agent_tasks", "turn_ingress_receipts"])
async def test_accept_turn_rolls_back_every_write_when_an_insert_fails(
    tmp_path,
    failing_table: str,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / f"{failing_table}.db"))
    try:
        await storage.upsert_session(_session())
        trigger_name = f"fail_acceptance_insert_{failing_table}"
        await storage.conn.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON {failing_table}
            BEGIN
                SELECT RAISE(ABORT, 'injected acceptance failure');
            END
            """
        )

        with pytest.raises(sqlite3.IntegrityError, match="injected acceptance failure"):
            await _accept_turn(
                storage,
                message_id="message-failed",
                task_id="task-failed",
            )

        session = await storage.get_session(SESSION_KEY)
        assert session is not None
        assert session.updated_at == 100
        assert await storage.count_transcript_entries(SESSION_ID) == 0
        assert await storage.get_agent_task("task-failed") is None
        assert await _row_count(storage, "turn_ingress_receipts") == 0
        assert storage.conn.in_transaction is False
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_accept_turn_replays_same_request_without_duplicate_side_effects(tmp_path) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())
        first = await _accept_turn(
            storage,
            message_id="message-original",
            task_id="task-original",
        )

        replay = await _accept_turn(
            storage,
            message_id="message-prospective-retry",
            task_id="task-prospective-retry",
            updated_at=300,
        )

        session = await storage.get_session(SESSION_KEY)
        assert session is not None
        assert session.updated_at == 200
        assert await storage.count_transcript_entries(SESSION_ID) == 1
        assert await _row_count(storage, "agent_tasks") == 1
        assert await _row_count(storage, "turn_ingress_receipts") == 1
        assert await storage.get_agent_task("task-prospective-retry") is None
        assert _result_value(replay, "receipt_id") == _result_value(first, "receipt_id")
        assert _result_value(replay, "message_id") == "message-original"
        assert _result_value(replay, "task_id") == "task-original"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_accept_turn_collects_into_existing_task_in_the_same_transaction(
    tmp_path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())
        existing = _task("task-collect")
        existing.queue_mode = "collect"
        existing.details = {
            "message_count": 1,
            "persisted_user_message_id": "message-first",
            "persisted_user_message_ids": ["message-first"],
            "fresh_user_session": True,
            "existing_only": "preserved",
        }
        await storage.create_agent_task(existing)

        collected = _task("task-collect", updated_at=300)
        collected.queue_mode = "collect"
        collected.details = {
            "collected": True,
            "message_count": 2,
            "persisted_user_message_id": "message-first",
            "persisted_user_message_ids": [
                "message-first",
                "message-collected",
            ],
        }
        result = await storage.accept_turn(
            _entry("message-collected", content="second", created_at=300),
            expected_epoch=0,
            updated_at=300,
            task_record=collected,
            source_scope="webui",
            request_session_key=SESSION_KEY,
            client_request_id="request-collect",
            request_fingerprint="sha256:request-collect",
            merge_into_task=True,
        )

        task = await storage.get_agent_task("task-collect")
        assert task is not None
        assert task.details is not None
        assert task.details["collected"] is True
        assert task.details["message_count"] == 2
        assert task.details["persisted_user_message_id"] == "message-first"
        assert task.details["persisted_user_message_ids"] == [
            "message-first",
            "message-collected",
        ]
        assert task.details["fresh_user_session"] is True
        assert task.details["existing_only"] == "preserved"
        assert [
            entry.message_id for entry in await storage.get_transcript(SESSION_ID)
        ] == ["message-collected"]
        assert await _row_count(storage, "agent_tasks") == 1
        assert await _row_count(storage, "turn_ingress_receipts") == 1
        assert _result_value(result, "task_id") == "task-collect"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_failed_collected_acceptance_rolls_back_task_details_and_message(
    tmp_path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())
        existing = _task("task-collect")
        existing.queue_mode = "collect"
        original_details = {
            "message_count": 1,
            "persisted_user_message_id": "message-first",
            "persisted_user_message_ids": ["message-first"],
        }
        existing.details = original_details
        await storage.create_agent_task(existing)
        await storage.conn.execute(
            """
            CREATE TRIGGER fail_collected_receipt
            BEFORE INSERT ON turn_ingress_receipts
            BEGIN
                SELECT RAISE(ABORT, 'injected collected receipt failure');
            END
            """
        )
        collected = _task("task-collect", updated_at=300)
        collected.queue_mode = "collect"
        collected.details = {"collected": True, "message_count": 2}

        with pytest.raises(sqlite3.IntegrityError, match="collected receipt failure"):
            await storage.accept_turn(
                _entry("message-collected", content="second", created_at=300),
                expected_epoch=0,
                updated_at=300,
                task_record=collected,
                source_scope="webui",
                request_session_key=SESSION_KEY,
                client_request_id="request-collect",
                request_fingerprint="sha256:request-collect",
                merge_into_task=True,
            )

        task = await storage.get_agent_task("task-collect")
        assert task is not None
        assert task.details == original_details
        assert await storage.get_transcript(SESSION_ID) == []
        assert await _row_count(storage, "turn_ingress_receipts") == 0
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_accept_turn_rejects_request_id_reuse_with_a_different_fingerprint(tmp_path) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        await storage.upsert_session(_session())
        await _accept_turn(
            storage,
            message_id="message-original",
            task_id="task-original",
        )

        with pytest.raises(Exception) as caught:
            await _accept_turn(
                storage,
                message_id="message-conflict",
                task_id="task-conflict",
                fingerprint="sha256:different-payload",
                updated_at=300,
            )

        assert caught.value.__class__.__name__ == "TurnIngressConflictError"
        session = await storage.get_session(SESSION_KEY)
        assert session is not None
        assert session.updated_at == 200
        assert await storage.count_transcript_entries(SESSION_ID) == 1
        assert await _row_count(storage, "agent_tasks") == 1
        assert await _row_count(storage, "turn_ingress_receipts") == 1
        assert await storage.get_agent_task("task-conflict") is None
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_accept_turn_busy_timeout_has_no_partial_side_effects(tmp_path) -> None:
    db_path = tmp_path / "sessions.db"
    storage = await SessionStorage.open(str(db_path))
    locker: sqlite3.Connection | None = None
    try:
        await storage.upsert_session(_session())
        storage._busy_budget_seconds = 0.0
        locker = sqlite3.connect(str(db_path), timeout=0.1, isolation_level=None)
        locker.execute("BEGIN IMMEDIATE")

        with pytest.raises(StorageBusyError):
            await _accept_turn(
                storage,
                message_id="message-busy",
                task_id="task-busy",
            )

        locker.execute("ROLLBACK")
        locker.close()
        locker = None

        session = await storage.get_session(SESSION_KEY)
        assert session is not None
        assert session.updated_at == 100
        assert await storage.count_transcript_entries(SESSION_ID) == 0
        assert await storage.get_agent_task("task-busy") is None
        assert await _row_count(storage, "turn_ingress_receipts") == 0
        assert storage.conn.in_transaction is False
    finally:
        if locker is not None:
            locker.execute("ROLLBACK")
            locker.close()
        await storage.close()
