from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import opensquilla.session.recovery_merge as session_merge_module
from opensquilla.artifacts import ArtifactStore
from opensquilla.attachment_refs import (
    transcript_material_path,
    write_transcript_material,
)
from opensquilla.cli.recovery_cmd import recovery_app
from opensquilla.recovery.errors import RecoveryError
from opensquilla.session.manager import SessionManager
from opensquilla.session.models import SessionNode, TranscriptEntry
from opensquilla.session.recovery_merge import (
    SessionMergeError,
    merge_recovery_sessions,
)
from opensquilla.session.storage import SessionStorage


async def _create_conversation(
    database: Path,
    *,
    session_key: str,
    session_id: str,
    messages: tuple[str, ...],
    label: str,
    compaction_count: int = 0,
) -> None:
    storage = SessionStorage(str(database))
    await storage.connect()
    try:
        await storage.upsert_session(
            SessionNode(
                session_key=session_key,
                session_id=session_id,
                label=label,
                compaction_count=compaction_count,
                status="done",
            )
        )
        for index, content in enumerate(messages):
            await storage.append_transcript_entry(
                TranscriptEntry(
                    session_id=session_id,
                    session_key=session_key,
                    message_id=f"{session_id}-message-{index}",
                    role="user" if index % 2 == 0 else "assistant",
                    content=content,
                    created_at=1_700_000_000_000 + index,
                )
            )
    finally:
        await storage.close()


async def _read_conversations(
    database: Path,
) -> dict[str, tuple[SessionNode, tuple[TranscriptEntry, ...], bool]]:
    storage = SessionStorage(str(database))
    await storage.connect()
    try:
        nodes = await storage.list_sessions(limit=1000)
        result = {}
        for node in nodes:
            result[node.session_key] = (
                node,
                tuple(await storage.get_canonical_transcript(node.session_id)),
                await storage.is_canonical_transcript_complete(node.session_id),
            )
        return result
    finally:
        await storage.close()


async def _create_compacted_conversation(database: Path) -> tuple[str, tuple[str, ...]]:
    storage = SessionStorage(str(database))
    await storage.connect()
    try:
        manager = SessionManager(storage, inject_time_prefix=False)
        node = await manager.create("agent:main:webchat:compacted")
        original = tuple(f"message {index}" for index in range(4))
        for content in original:
            await manager.append_message(node.session_key, "user", content)
        await manager.persist_compaction_result(
            node.session_key,
            "synthetic summary",
            [{"role": "user", "content": original[-1]}],
            compaction_id="recovery-merge-compaction",
        )
        return node.session_key, original
    finally:
        await storage.close()


async def _continue_conversation(
    database: Path,
    session_key: str,
    *,
    content: str,
) -> None:
    storage = SessionStorage(str(database))
    await storage.connect()
    try:
        node = await storage.get_session(session_key)
        assert node is not None
        node.label = "Renamed after recovery"
        node.updated_at += 10_000
        await storage.upsert_session(node)
        await storage.append_transcript_entry(
            TranscriptEntry(
                session_id=node.session_id,
                session_key=node.session_key,
                message_id="continued-after-recovery",
                role="user",
                content=content,
                created_at=1_800_000_000_000,
            )
        )
    finally:
        await storage.close()


async def _delete_conversation(database: Path, session_key: str) -> None:
    storage = SessionStorage(str(database))
    await storage.connect()
    try:
        await storage.delete_session(session_key)
    finally:
        await storage.close()


def _database_bundle(database: Path) -> dict[str, bytes]:
    result = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(f"{database}{suffix}")
        if candidate.exists():
            result[suffix] = candidate.read_bytes()
    return result


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_merge_preserves_target_and_resolves_collisions_idempotently(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    target.parent.mkdir()
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:webchat:default",
            session_id="source-session-id",
            messages=("recovery question", "recovery answer"),
            label="Recovery chat",
        )
    )
    asyncio.run(
        _create_conversation(
            target,
            session_key="agent:main:webchat:default",
            session_id="target-session-id",
            messages=("primary question", "primary answer"),
            label="Primary chat",
        )
    )

    first = merge_recovery_sessions(source, target)

    assert first.outcome == "complete"
    assert first.sessions_found == 1
    assert first.sessions_imported == 1
    assert first.sessions_skipped == 0
    assert first.collisions_resolved == 1
    assert first.transcript_entries_imported == 2
    conversations = asyncio.run(_read_conversations(target))
    assert len(conversations) == 2
    primary = conversations["agent:main:webchat:default"]
    assert primary[0].label == "Primary chat"
    assert [entry.content for entry in primary[1]] == [
        "primary question",
        "primary answer",
    ]
    recovered_keys = [
        key for key in conversations if key != "agent:main:webchat:default"
    ]
    assert len(recovered_keys) == 1
    recovered = conversations[recovered_keys[0]]
    assert recovered[0].label == "Recovery chat"
    assert recovered[0].session_id != primary[0].session_id
    assert [entry.content for entry in recovered[1]] == [
        "recovery question",
        "recovery answer",
    ]
    assert recovered[2] is True

    asyncio.run(
        _continue_conversation(
            target,
            recovered_keys[0],
            content="continued after recovery",
        )
    )
    second = merge_recovery_sessions(source, target)

    assert second.outcome == "unchanged"
    assert second.stable_code == "session_merge_already_complete"
    assert second.sessions_imported == 0
    assert second.sessions_skipped == 1
    after_second_merge = asyncio.run(_read_conversations(target))
    assert len(after_second_merge) == 2
    assert after_second_merge[recovered_keys[0]][0].label == "Renamed after recovery"
    assert [entry.content for entry in after_second_merge[recovered_keys[0]][1]] == [
        "recovery question",
        "recovery answer",
        "continued after recovery",
    ]


def test_merge_flattens_complete_compacted_history_into_visible_transcript(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    session_key, original = asyncio.run(_create_compacted_conversation(source))

    report = merge_recovery_sessions(source, target)

    assert report.sessions_imported == 1
    assert report.transcript_entries_imported == len(original)
    node, entries, complete = asyncio.run(_read_conversations(target))[session_key]
    assert node.compaction_count == 0
    assert [entry.content for entry in entries] == list(original)
    assert complete is True


def test_exact_existing_session_receipt_prevents_duplicate_after_continuation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    target.parent.mkdir()
    session_key = "agent:main:webchat:shared"
    asyncio.run(
        _create_conversation(
            source,
            session_key=session_key,
            session_id="same-session-id",
            messages=("already in primary",),
            label="Shared chat",
        )
    )
    shutil.copy2(source, target)

    first = merge_recovery_sessions(source, target)

    assert first.outcome == "unchanged"
    assert first.sessions_imported == 0
    assert first.sessions_skipped == 1
    asyncio.run(
        _continue_conversation(
            target,
            session_key,
            content="primary continued",
        )
    )

    second = merge_recovery_sessions(source, target)

    assert second.outcome == "unchanged"
    assert second.sessions_imported == 0
    assert second.sessions_skipped == 1
    conversations = asyncio.run(_read_conversations(target))
    assert list(conversations) == [session_key]
    assert [entry.content for entry in conversations[session_key][1]] == [
        "already in primary",
        "primary continued",
    ]


def test_user_deleted_recovered_session_is_not_resurrected(tmp_path: Path) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    session_key = "agent:main:webchat:user-deleted"
    asyncio.run(
        _create_conversation(
            source,
            session_key=session_key,
            session_id="deleted-after-merge",
            messages=("delete me later",),
            label="User deletion",
        )
    )

    first = merge_recovery_sessions(source, target)
    assert first.sessions_imported == 1
    asyncio.run(_delete_conversation(target, session_key))
    assert asyncio.run(_read_conversations(target)) == {}

    second = merge_recovery_sessions(source, target)

    assert second.outcome == "unchanged"
    assert second.sessions_imported == 0
    assert second.sessions_skipped == 1
    assert asyncio.run(_read_conversations(target)) == {}


def test_merge_copies_attachment_and_artifact_across_media_roots_with_id_remap(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source_media = tmp_path / "recovery-media"
    target_media = tmp_path / "primary-media"
    source.parent.mkdir()
    target.parent.mkdir()
    source_key = "agent:main:webchat:materials"
    source_id = "shared-session-id"
    asyncio.run(
        _create_conversation(
            source,
            session_key=source_key,
            session_id=source_id,
            messages=("attachment and artifact",),
            label="Material recovery",
        )
    )
    # A different primary conversation owns the same session id, forcing the
    # recovered conversation and every material bucket onto a new deterministic id.
    asyncio.run(
        _create_conversation(
            target,
            session_key="agent:main:webchat:existing",
            session_id=source_id,
            messages=("existing primary",),
            label="Existing primary",
        )
    )
    attachment_payload = b"historical upload bytes"
    attachment_sha, _, _ = write_transcript_material(
        media_root=source_media,
        session_id=source_id,
        payload=attachment_payload,
    )
    artifact_payload = b"historical generated file"
    artifact = ArtifactStore(source_media).publish_bytes(
        artifact_payload,
        session_id=source_id,
        session_key=source_key,
        name="report.txt",
        mime="text/plain",
        source="publish_artifact",
    )
    source_media_before = _tree_bytes(source_media)

    first = merge_recovery_sessions(
        source,
        target,
        source_media_root=source_media,
        target_media_root=target_media,
    )

    assert first.materials_status == "complete"
    assert first.attachment_files_copied == 1
    assert first.artifacts_copied == 1
    assert first.material_bytes_copied == len(attachment_payload) + len(artifact_payload)
    assert _tree_bytes(source_media) == source_media_before
    conversations = asyncio.run(_read_conversations(target))
    recovered = next(
        node
        for node, _, _ in conversations.values()
        if node.label == "Material recovery"
    )
    assert recovered.session_id != source_id
    assert transcript_material_path(
        target_media,
        recovered.session_id,
        attachment_sha,
    ).read_bytes() == attachment_payload
    recovered_ref, recovered_path = ArtifactStore(target_media).resolve_for_download(
        artifact.id,
        session_id=recovered.session_id,
    )
    assert recovered_path.read_bytes() == artifact_payload
    assert recovered_ref.session_key == recovered.session_key

    second = merge_recovery_sessions(
        source,
        target,
        source_media_root=source_media,
        target_media_root=target_media,
    )

    assert second.outcome == "unchanged"
    assert second.materials_status == "complete"
    assert second.attachment_files_copied == 0
    assert second.artifacts_copied == 0
    assert second.material_bytes_copied == 0
    assert _tree_bytes(source_media) == source_media_before


def test_invalid_source_artifact_keeps_transcript_and_reports_partial_idempotently(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source_media = tmp_path / "recovery-media"
    target_media = tmp_path / "primary-media"
    source.parent.mkdir()
    target.parent.mkdir()
    source_key = "agent:main:webchat:invalid-material"
    source_id = "invalid-material-source"
    asyncio.run(
        _create_conversation(
            source,
            session_key=source_key,
            session_id=source_id,
            messages=("broken artifact metadata",),
            label="Invalid material",
        )
    )
    asyncio.run(
        _create_conversation(
            target,
            session_key="agent:main:main",
            session_id="protected-material-target",
            messages=("must remain unchanged",),
            label="Protected target",
        )
    )
    artifact = ArtifactStore(source_media).publish_bytes(
        b"artifact bytes",
        session_id=source_id,
        session_key=source_key,
        name="bad.txt",
        mime="text/plain",
        source="publish_artifact",
    )
    ArtifactStore(source_media).path_for(artifact).parent.joinpath("meta.json").write_text(
        "{invalid",
        encoding="utf-8",
    )
    source_before = _database_bundle(source)
    source_media_before = _tree_bytes(source_media)

    first = merge_recovery_sessions(
        source,
        target,
        source_media_root=source_media,
        target_media_root=target_media,
    )

    assert first.outcome == "partial"
    assert first.stable_code == "session_merge_partial"
    assert first.sessions_found == 1
    assert first.sessions_imported == 1
    assert first.sessions_blocked == 0
    assert first.materials_status == "blocked"
    assert first.materials_sessions_blocked == 1
    assert first.blocked_codes == ("session_merge_material_invalid",)
    assert not target_media.exists()
    conversations = asyncio.run(_read_conversations(target))
    recovered = next(
        entries
        for node, entries, _ in conversations.values()
        if node.session_id == source_id
    )
    assert [entry.content for entry in recovered] == ["broken artifact metadata"]
    assert _database_bundle(source) == source_before
    assert _tree_bytes(source_media) == source_media_before

    second = merge_recovery_sessions(
        source,
        target,
        source_media_root=source_media,
        target_media_root=target_media,
    )

    assert second.outcome == "partial"
    assert second.sessions_imported == 0
    assert second.sessions_skipped == 1
    assert second.materials_sessions_blocked == 1
    assert len(asyncio.run(_read_conversations(target))) == 2
    assert _database_bundle(source) == source_before
    assert _tree_bytes(source_media) == source_media_before


def test_missing_referenced_attachment_does_not_block_transcript_import(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source_media = tmp_path / "missing-recovery-media"
    target_media = tmp_path / "primary-media"
    source.parent.mkdir()
    source_id = "missing-attachment-source"
    envelope = json.dumps(
        {
            "text": "historical attachment",
            "attachments": [
                {
                    "sha256_ref": "a" * 64,
                    "name": "evidence.txt",
                    "mime": "text/plain",
                    "size": 12,
                }
            ],
        }
    )
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:webchat:missing-attachment",
            session_id=source_id,
            messages=(envelope,),
            label="Missing attachment",
        )
    )
    source_before = _database_bundle(source)

    first = merge_recovery_sessions(
        source,
        target,
        source_media_root=source_media,
        target_media_root=target_media,
    )

    assert first.outcome == "partial"
    assert first.sessions_imported == 1
    assert first.sessions_blocked == 0
    assert first.materials_status == "blocked"
    assert first.materials_sessions_blocked == 1
    assert first.blocked_codes == ("session_merge_material_invalid",)
    assert not target_media.exists()
    assert [entry.content for entry in asyncio.run(_read_conversations(target))[
        "agent:main:webchat:missing-attachment"
    ][1]] == [envelope]
    assert _database_bundle(source) == source_before

    second = merge_recovery_sessions(
        source,
        target,
        source_media_root=source_media,
        target_media_root=target_media,
    )

    assert second.outcome == "partial"
    assert second.sessions_imported == 0
    assert second.sessions_skipped == 1
    assert second.materials_sessions_blocked == 1
    assert len(asyncio.run(_read_conversations(target))) == 1
    assert _database_bundle(source) == source_before


def test_unsafe_target_media_does_not_block_transcript_import(tmp_path: Path) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source_media = tmp_path / "recovery-media"
    target_media = tmp_path / "primary-media"
    outside = tmp_path / "outside"
    source.parent.mkdir()
    outside.mkdir()
    try:
        target_media.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")
    source_id = "unsafe-target-media-source"
    attachment_payload = b"historical attachment remains in the source"
    attachment_sha, _, _ = write_transcript_material(
        media_root=source_media,
        session_id=source_id,
        payload=attachment_payload,
    )
    envelope = json.dumps(
        {
            "text": "transcript remains recoverable",
            "attachments": [
                {
                    "sha256_ref": attachment_sha,
                    "name": "evidence.txt",
                    "mime": "text/plain",
                    "size": len(attachment_payload),
                }
            ],
        }
    )
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:webchat:unsafe-target-media",
            session_id=source_id,
            messages=(envelope,),
            label="Unsafe target media",
        )
    )

    report = merge_recovery_sessions(
        source,
        target,
        source_media_root=source_media,
        target_media_root=target_media,
    )

    assert report.outcome == "partial"
    assert report.sessions_imported == 1
    assert report.sessions_blocked == 0
    assert report.materials_status == "blocked"
    assert report.materials_sessions_blocked == 1
    assert report.blocked_codes == ("session_merge_material_target_invalid",)
    assert [entry.content for entry in asyncio.run(_read_conversations(target))[
        "agent:main:webchat:unsafe-target-media"
    ][1]] == [envelope]
    assert list(outside.iterdir()) == []


def test_windows_prepare_target_media_root_accepts_existing_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_media = tmp_path / "primary-media"
    target_media.mkdir()
    monkeypatch.setattr(session_merge_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(session_merge_module, "_absolute", lambda _path: target_media)
    monkeypatch.setattr(session_merge_module, "_parent_chain_identities", lambda _path: {})
    monkeypatch.setattr(session_merge_module, "no_follow_manifest", lambda _path: {})

    assert session_merge_module._prepare_target_media_root(target_media) == target_media


def test_normalize_snapshot_closes_connections_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = tmp_path / "copied.db"
    normalized = tmp_path / "normalized.db"
    original_connect = sqlite3.connect
    seed = original_connect(copied)
    try:
        seed.execute("CREATE TABLE messages (content TEXT NOT NULL)")
        seed.execute("INSERT INTO messages VALUES ('preserved')")
        seed.commit()
    finally:
        seed.close()

    connections: list[sqlite3.Connection] = []

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self) -> None:
            self.closed = True
            super().close()

    def tracked_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = original_connect(*args, factory=TrackedConnection, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(session_merge_module.sqlite3, "connect", tracked_connect)
    try:
        session_merge_module._normalize_snapshot(copied, normalized)
        assert len(connections) == 2
        assert all(getattr(connection, "closed", False) for connection in connections)
    finally:
        for connection in connections:
            connection.close()

    verify = original_connect(normalized)
    try:
        assert verify.execute("SELECT content FROM messages").fetchone() == ("preserved",)
    finally:
        verify.close()


def test_merge_snapshots_committed_wal_without_mutating_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    target.parent.mkdir()
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:main",
            session_id="wal-session-id",
            messages=("stored before WAL",),
            label="Before WAL",
        )
    )
    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "UPDATE sessions SET label = ? WHERE session_key = ?",
            ("Committed in WAL", "agent:main:main"),
        )
        writer.commit()
        assert Path(f"{source}-wal").is_file()
        source_before = _database_bundle(source)

        report = merge_recovery_sessions(source, target)

        assert report.sessions_imported == 1
        assert _database_bundle(source) == source_before
        conversations = asyncio.run(_read_conversations(target))
        node, entries, complete = conversations["agent:main:main"]
        assert node.label == "Committed in WAL"
        assert [entry.content for entry in entries] == ["stored before WAL"]
        assert complete is True
    finally:
        writer.close()


def test_incomplete_source_session_does_not_block_healthy_transcript(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    target.parent.mkdir()
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:main",
            session_id="incomplete-source",
            messages=("tail without canonical archive",),
            label="Incomplete",
            compaction_count=1,
        )
    )
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:webchat:healthy",
            session_id="healthy-source",
            messages=("healthy transcript survives",),
            label="Healthy",
        )
    )
    asyncio.run(
        _create_conversation(
            target,
            session_key="agent:main:main",
            session_id="protected-target",
            messages=("must remain byte-for-byte unchanged",),
            label="Protected",
        )
    )
    source_before = _database_bundle(source)

    first = merge_recovery_sessions(source, target)

    assert first.outcome == "partial"
    assert first.stable_code == "session_merge_partial"
    assert first.sessions_found == 2
    assert first.sessions_imported == 1
    assert first.sessions_skipped == 0
    assert first.sessions_blocked == 1
    assert first.transcript_entries_imported == 1
    assert first.blocked_codes == ("session_merge_source_incomplete",)
    assert (
        first.sessions_imported + first.sessions_skipped + first.sessions_blocked
        == first.sessions_found
    )
    conversations = asyncio.run(_read_conversations(target))
    assert set(conversations) == {
        "agent:main:main",
        "agent:main:webchat:healthy",
    }
    assert [entry.content for entry in conversations[
        "agent:main:webchat:healthy"
    ][1]] == ["healthy transcript survives"]
    assert _database_bundle(source) == source_before

    second = merge_recovery_sessions(source, target)

    assert second.outcome == "partial"
    assert second.sessions_found == 2
    assert second.sessions_imported == 0
    assert second.sessions_skipped == 1
    assert second.sessions_blocked == 1
    assert len(asyncio.run(_read_conversations(target))) == 2
    assert _database_bundle(source) == source_before


def test_corrupt_source_fails_before_missing_target_is_created(tmp_path: Path) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    source.write_bytes(b"not a sqlite database")

    with pytest.raises(SessionMergeError) as caught:
        merge_recovery_sessions(source, target)

    assert caught.value.stable_code == "session_merge_source_invalid"
    assert not target.exists()
    assert not target.parent.exists()


def test_source_and_target_hard_link_alias_is_rejected_without_writes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    target.parent.mkdir()
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:main",
            session_id="hard-link-source",
            messages=("one physical database",),
            label="Hard link",
        )
    )
    try:
        os.link(source, target)
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")
    source_before = source.read_bytes()

    with pytest.raises(SessionMergeError) as caught:
        merge_recovery_sessions(source, target)

    assert caught.value.stable_code == "session_merge_same_database"
    assert source.read_bytes() == source_before


def test_target_parent_symlink_is_rejected_without_escape(tmp_path: Path) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    outside = tmp_path / "outside"
    linked_parent = tmp_path / "primary"
    source.parent.mkdir()
    outside.mkdir()
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:main",
            session_id="symlink-parent-source",
            messages=("must not escape",),
            label="Symlink parent",
        )
    )
    try:
        linked_parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(RecoveryError) as caught:
        merge_recovery_sessions(source, linked_parent / "sessions.db")

    assert caught.value.stable_code == "unsafe_path"
    assert not (outside / "sessions.db").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-fd regression")
def test_target_parent_swap_cannot_redirect_sqlite_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    parked = tmp_path / "parked-primary"
    outside = tmp_path / "outside"
    source.parent.mkdir()
    target.parent.mkdir()
    outside.mkdir()
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:main",
            session_id="parent-swap-source",
            messages=("stay inside the bound directory",),
            label="Parent swap",
        )
    )
    original_storage = session_merge_module._offline_session_storage
    swapped = False

    def swap_before_target_open(database: Path):
        nonlocal swapped
        if database == Path(target.name) and not swapped:
            swapped = True
            target.parent.rename(parked)
            target.parent.symlink_to(outside, target_is_directory=True)
        return original_storage(database)

    monkeypatch.setattr(
        session_merge_module,
        "_offline_session_storage",
        swap_before_target_open,
    )

    with pytest.raises(SessionMergeError) as caught:
        merge_recovery_sessions(source, target)

    assert swapped is True
    assert caught.value.stable_code == "session_merge_target_changed"
    assert not (outside / "sessions.db").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows no-delete-share regression")
def test_windows_target_binding_blocks_ancestor_replacement_before_sqlite_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target_root = tmp_path / "primary"
    target = target_root / "nested" / "sessions.db"
    parked = tmp_path / "parked-primary"
    source.parent.mkdir()
    target.parent.mkdir(parents=True)
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:main",
            session_id="windows-ancestor-swap-source",
            messages=("stay on the bound Windows path",),
            label="Windows ancestor binding",
        )
    )
    original_storage = session_merge_module._offline_session_storage
    attempted = False
    replacement_blocked = False

    def attempt_ancestor_replacement(database: Path):
        nonlocal attempted, replacement_blocked
        if database == target and not attempted:
            attempted = True
            try:
                target_root.rename(parked)
            except OSError:
                replacement_blocked = True
            else:
                # Never let the test itself direct SQLite to a replacement.
                raise AssertionError("bound target ancestor remained replaceable")
        return original_storage(database)

    monkeypatch.setattr(
        session_merge_module,
        "_offline_session_storage",
        attempt_ancestor_replacement,
    )

    report = merge_recovery_sessions(source, target)

    assert attempted is True
    assert replacement_blocked is True
    assert report.sessions_imported == 1
    assert not parked.exists()


def test_merge_sessions_cli_emits_fixed_machine_protocol(tmp_path: Path) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source_media = tmp_path / "recovery-media"
    target_media = tmp_path / "primary-media"
    source.parent.mkdir()
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:main",
            session_id="cli-source",
            messages=("visible from CLI",),
            label="CLI recovery",
        )
    )
    write_transcript_material(
        media_root=source_media,
        session_id="cli-source",
        payload=b"CLI attachment",
    )

    result = CliRunner().invoke(
        recovery_app,
        [
            "merge-sessions",
            "--source-db",
            str(source),
            "--target-db",
            str(target),
            "--source-media-root",
            str(source_media),
            "--target-media-root",
            str(target_media),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "schema_version",
        "outcome",
        "stable_code",
        "source_database",
        "target_database",
        "sessions_found",
        "sessions_imported",
        "sessions_skipped",
        "sessions_blocked",
        "collisions_resolved",
        "transcript_entries_imported",
        "materials_status",
        "materials_sessions_blocked",
        "blocked_codes",
        "attachment_files_copied",
        "artifacts_copied",
        "material_bytes_copied",
    }
    assert payload["outcome"] == "complete"
    assert payload["stable_code"] == "session_merge_complete"
    assert payload["sessions_imported"] == 1
    assert payload["sessions_blocked"] == 0
    assert payload["transcript_entries_imported"] == 1
    assert payload["materials_status"] == "complete"
    assert payload["materials_sessions_blocked"] == 0
    assert payload["blocked_codes"] == []
    assert payload["attachment_files_copied"] == 1


def test_merge_sessions_cli_emits_partial_protocol_with_exit_one(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    asyncio.run(
        _create_conversation(
            source,
            session_key="agent:main:main",
            session_id="cli-incomplete-source",
            messages=("incomplete CLI transcript",),
            label="Incomplete CLI recovery",
            compaction_count=1,
        )
    )

    result = CliRunner().invoke(
        recovery_app,
        [
            "merge-sessions",
            "--source-db",
            str(source),
            "--target-db",
            str(target),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "partial"
    assert payload["stable_code"] == "session_merge_partial"
    assert payload["sessions_found"] == 1
    assert payload["sessions_imported"] == 0
    assert payload["sessions_blocked"] == 1
    assert payload["materials_sessions_blocked"] == 0
    assert payload["blocked_codes"] == ["session_merge_source_incomplete"]
    assert not target.exists()


def test_merge_sessions_cli_emits_json_failure_without_touching_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recovery" / "sessions.db"
    target = tmp_path / "primary" / "sessions.db"
    source.parent.mkdir()
    source.write_bytes(b"invalid sqlite")

    result = CliRunner().invoke(
        recovery_app,
        [
            "merge-sessions",
            "--source-db",
            str(source),
            "--target-db",
            str(target),
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "blocked"
    assert payload["stable_code"] == "session_merge_source_invalid"
    assert payload["sessions_imported"] == 0
    assert not target.parent.exists()
