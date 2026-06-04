from __future__ import annotations

import asyncio
import sqlite3

import pytest

from opensquilla.gateway.approval_queue import ApprovalQueue


def test_approval_queue_request_persists_across_queue_restart(tmp_path) -> None:
    db_path = tmp_path / "approval_queue.sqlite"
    queue = ApprovalQueue(db_path=str(db_path))
    approval_id = queue.request(
        "exec",
        {
            "toolName": "exec_command",
            "command": "rm -f /tmp/stale",
            "sessionKey": "agent:main:demo",
        },
    )
    assert queue.get(approval_id).resolved is False
    queue.close()

    reloaded = ApprovalQueue(db_path=str(db_path))
    assert reloaded.get(approval_id).approval_id == approval_id
    assert reloaded.get(approval_id).resolved is False

    reloaded.resolve(approval_id, True, allow_always=True)
    assert reloaded.get(approval_id).resolved is True
    assert reloaded.get(approval_id).approved is True
    reloaded.consume(approval_id)
    assert reloaded.get(approval_id).consumed is True
    assert reloaded.list_pending("exec") == []
    reloaded.close()


def test_approval_queue_ignores_corrupt_json_payload(tmp_path) -> None:
    db_path = tmp_path / "approval_queue.sqlite"
    queue = ApprovalQueue(db_path=str(db_path))
    bad_id = "bad-json-01"
    conn = sqlite3.connect(str(db_path))
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT OR REPLACE INTO approval_queue "
        "(approval_id, namespace, params, created_at, resolved, approved, consumed) "
        "VALUES (?, ?, ?, ?, 0, 0, 0)",
        (bad_id, "exec", "{not-json}", 0.0),
    )
    conn.commit()
    conn.close()
    queue.close()

    reloaded = ApprovalQueue(db_path=str(db_path))
    entry = reloaded.get(bad_id)
    assert entry.approval_id == bad_id
    assert entry.params == {}
    reloaded.close()


@pytest.mark.asyncio
async def test_approval_queue_wait_observes_resolution_from_second_queue_same_sqlite(
    tmp_path,
) -> None:
    db_path = tmp_path / "approval_queue.sqlite"
    queue_a = ApprovalQueue(db_path=str(db_path), default_timeout=1.0, poll_interval=0.01)
    approval_id = queue_a.request("exec", {"toolName": "exec_command", "command": "rm x"})
    queue_b = ApprovalQueue(db_path=str(db_path), default_timeout=1.0, poll_interval=0.01)
    try:
        waiter = asyncio.create_task(queue_a.wait(approval_id, timeout=1.0))
        await asyncio.sleep(0.03)
        queue_b.resolve(approval_id, True)

        assert await waiter is True
        assert queue_a.get(approval_id).approved is True
    finally:
        queue_a.close()
        queue_b.close()


@pytest.mark.asyncio
async def test_approval_queue_wait_same_process_event_fast_path(tmp_path) -> None:
    db_path = tmp_path / "approval_queue.sqlite"
    queue = ApprovalQueue(db_path=str(db_path), default_timeout=1.0, poll_interval=1.0)
    approval_id = queue.request("exec", {"toolName": "exec_command", "command": "rm x"})
    try:
        waiter = asyncio.create_task(queue.wait(approval_id, timeout=1.0))
        await asyncio.sleep(0)
        queue.resolve(approval_id, True)

        assert await asyncio.wait_for(waiter, timeout=0.2) is True
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_approval_queue_wait_preserves_timeout_denies(tmp_path) -> None:
    db_path = tmp_path / "approval_queue.sqlite"
    queue = ApprovalQueue(db_path=str(db_path), default_timeout=1.0, poll_interval=0.01)
    approval_id = queue.request("exec", {"toolName": "exec_command", "command": "rm x"})
    try:
        assert await queue.wait(approval_id, timeout=0.02) is False
        entry = queue.get(approval_id)
        assert entry.resolved is True
        assert entry.approved is False
    finally:
        queue.close()


def test_approval_queue_resolve_does_not_overwrite_prior_resolution(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "approval_queue.sqlite"
    queue = ApprovalQueue(db_path=str(db_path), default_timeout=1.0, poll_interval=0.01)
    approval_id = queue.request("exec", {"toolName": "exec_command", "command": "rm x"})
    stale_unresolved_row = queue._get_row(approval_id)
    assert stale_unresolved_row is not None
    queue._conn.execute(
        "UPDATE approval_queue SET resolved = 1, approved = 0 WHERE approval_id = ?",
        (approval_id,),
    )
    queue._conn.commit()
    original_get_row = queue._get_row
    calls = 0

    def stale_once(row_approval_id: str) -> sqlite3.Row | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return stale_unresolved_row
        return original_get_row(row_approval_id)

    monkeypatch.setattr(queue, "_get_row", stale_once)
    try:
        with pytest.raises(ValueError, match="already resolved"):
            queue.resolve(approval_id, True)

        entry = queue.get(approval_id)
        assert entry.resolved is True
        assert entry.approved is False
    finally:
        queue.close()


def test_approval_queue_consume_is_one_shot_with_stale_unconsumed_read(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "approval_queue.sqlite"
    queue = ApprovalQueue(db_path=str(db_path), default_timeout=1.0, poll_interval=0.01)
    approval_id = queue.request("exec", {"toolName": "exec_command", "command": "rm x"})
    queue.resolve(approval_id, True)
    stale_unconsumed_row = queue._get_row(approval_id)
    assert stale_unconsumed_row is not None
    queue._conn.execute(
        "UPDATE approval_queue SET consumed = 1 WHERE approval_id = ?",
        (approval_id,),
    )
    queue._conn.commit()
    original_get_row = queue._get_row
    calls = 0

    def stale_once(row_approval_id: str) -> sqlite3.Row | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return stale_unconsumed_row
        return original_get_row(row_approval_id)

    monkeypatch.setattr(queue, "_get_row", stale_once)
    try:
        with pytest.raises(ValueError, match="already consumed"):
            queue.consume(approval_id)

        assert queue.get(approval_id).consumed is True
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_approval_queue_keeps_stale_resolved_claim_not_ready(tmp_path) -> None:
    db_path = tmp_path / "approval_queue.sqlite"
    queue = ApprovalQueue(db_path=str(db_path), default_timeout=1.0, poll_interval=0.01)
    approval_id = queue.request("exec", {"toolName": "exec_command", "command": "rm x"})
    token = queue.claim_resolution(approval_id)
    try:
        queue.finalize_claimed_resolution(approval_id, token, True)
        queue._conn.execute(
            "UPDATE approval_queue SET claim_token = ?, claim_started_at = 0 "
            "WHERE approval_id = ?",
            ("stale-token", approval_id),
        )
        queue._conn.commit()

        entry = queue.get(approval_id)

        assert entry.claim_token == "stale-token"
        assert entry.resolved is True
        assert entry.approved is True
        assert queue.status(approval_id)["resolved"] is False
        assert queue.status(approval_id)["approved"] is False
        with pytest.raises(ValueError, match="in progress"):
            queue.consume(approval_id)
        with pytest.raises(ValueError, match="in progress"):
            await queue.wait(approval_id, timeout=0.02)
    finally:
        queue.close()
