"""Idempotent import of Desktop SessionNodes and canonical transcripts."""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from opensquilla.recovery.atomic import PathIdentity, no_follow_manifest
from opensquilla.recovery.errors import RecoveryError, UnsafePathError

_SNAPSHOT_ATTEMPTS = 3
_COPY_CHUNK_BYTES = 1024 * 1024
_MERGE_MARKER = "_opensquilla_desktop_recovery_merge"
_MERGE_NAMESPACE = uuid.UUID("414ece79-da95-5b36-91f4-3c557f1e3c6e")
_CREATE_MERGE_RECEIPTS = """
CREATE TABLE IF NOT EXISTS desktop_session_merge_receipts (
    merge_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    source_session_key TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    source_updated_at INTEGER NOT NULL,
    transcript_entries INTEGER NOT NULL,
    last_message_id TEXT,
    last_created_at INTEGER,
    target_session_key TEXT NOT NULL,
    target_session_id TEXT NOT NULL,
    imported_at INTEGER NOT NULL
)
"""

SessionMergeOutcome = Literal["complete", "partial", "unchanged", "blocked"]
MaterialMergeStatus = Literal["complete", "not_requested", "blocked"]


class SessionMergeError(RecoveryError):
    """A stable, machine-reportable session merge failure."""


@dataclass(frozen=True, slots=True)
class SessionMergeReport:
    """Fixed protocol returned to the Desktop parent process."""

    outcome: SessionMergeOutcome
    stable_code: str
    source_database: Path
    target_database: Path
    sessions_found: int = 0
    sessions_imported: int = 0
    sessions_skipped: int = 0
    sessions_blocked: int = 0
    collisions_resolved: int = 0
    transcript_entries_imported: int = 0
    materials_status: MaterialMergeStatus = "not_requested"
    materials_sessions_blocked: int = 0
    blocked_codes: tuple[str, ...] = ()
    attachment_files_copied: int = 0
    artifacts_copied: int = 0
    material_bytes_copied: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "outcome": self.outcome,
            "stable_code": self.stable_code,
            "source_database": str(self.source_database),
            "target_database": str(self.target_database),
            "sessions_found": self.sessions_found,
            "sessions_imported": self.sessions_imported,
            "sessions_skipped": self.sessions_skipped,
            "sessions_blocked": self.sessions_blocked,
            "collisions_resolved": self.collisions_resolved,
            "transcript_entries_imported": self.transcript_entries_imported,
            "materials_status": self.materials_status,
            "materials_sessions_blocked": self.materials_sessions_blocked,
            "blocked_codes": list(self.blocked_codes),
            "attachment_files_copied": self.attachment_files_copied,
            "artifacts_copied": self.artifacts_copied,
            "material_bytes_copied": self.material_bytes_copied,
        }


@dataclass(frozen=True, slots=True)
class _Conversation:
    node: Any
    entries: tuple[Any, ...]
    source_fingerprint: str
    merge_id: str


@dataclass(frozen=True, slots=True)
class _ConversationSnapshot:
    conversations: tuple[_Conversation, ...]
    sessions_found: int
    sessions_blocked: int
    blocked_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _TargetConversation:
    node: Any
    entries: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class _PlannedConversation:
    source: _Conversation
    session_key: str
    session_id: str
    existing: bool
    collision_resolved: bool
    receipt_required: bool = False


@dataclass(frozen=True, slots=True)
class _MergeReceipt:
    merge_id: str
    source_session_key: str
    source_session_id: str
    source_updated_at: int
    transcript_entries: int
    last_message_id: str | None
    last_created_at: int | None
    target_session_key: str
    target_session_id: str


@dataclass(frozen=True, slots=True)
class _TargetBinding:
    storage_path: Path
    verify: Callable[[], None]


@dataclass(frozen=True, slots=True)
class _AttachmentMaterial:
    sha256: str
    snapshot_path: Path
    size: int


@dataclass(frozen=True, slots=True)
class _ArtifactMaterial:
    ref_payload: dict[str, object]
    snapshot_path: Path
    thumbnail_path: Path | None
    size: int
    thumbnail_size: int


@dataclass(frozen=True, slots=True)
class _SessionMaterials:
    attachments: tuple[_AttachmentMaterial, ...] = ()
    artifacts: tuple[_ArtifactMaterial, ...] = ()


@dataclass(frozen=True, slots=True)
class _MaterialSnapshot:
    sessions: dict[str, _SessionMaterials]
    blocked_session_ids: frozenset[str] = frozenset()
    blocked_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _MaterialCopyReport:
    attachment_files_copied: int = 0
    artifacts_copied: int = 0
    material_bytes_copied: int = 0


@dataclass(frozen=True, slots=True)
class _TargetMergeReport:
    sessions_imported: int = 0
    sessions_skipped: int = 0
    collisions_resolved: int = 0
    transcript_entries_imported: int = 0
    materials: _MaterialCopyReport = _MaterialCopyReport()
    material_blocked_session_ids: frozenset[str] = frozenset()
    blocked_codes: tuple[str, ...] = ()


def _absolute(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right))
    )


def _identity(path: Path) -> PathIdentity:
    try:
        manifest = no_follow_manifest(path)
    except FileNotFoundError as exc:
        raise SessionMergeError(
            f"session database is missing: {path}",
            stable_code="session_merge_source_missing",
        ) from exc
    except UnsafePathError:
        raise
    except OSError as exc:
        raise SessionMergeError(
            f"session database cannot be inspected: {path}",
            stable_code="session_merge_source_unreadable",
        ) from exc
    identity = manifest["."]
    if not stat.S_ISREG(identity.mode):
        raise UnsafePathError(f"session merge requires a regular file: {path}")
    return identity


def _open_source_file(path: Path) -> tuple[int, PathIdentity]:
    before = _identity(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SessionMergeError(
            f"session database cannot be read: {path}",
            stable_code="session_merge_source_unreadable",
        ) from exc
    opened = PathIdentity.from_stat(os.fstat(descriptor))
    if not stat.S_ISREG(opened.mode) or opened != before:
        os.close(descriptor)
        raise SessionMergeError(
            f"session database changed while opening: {path}",
            stable_code="session_merge_source_changed",
        )
    return descriptor, opened


def _copy_and_digest(source: Path, destination: Path) -> tuple[PathIdentity, str]:
    descriptor, identity = _open_source_file(source)
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as source_handle:
            with destination.open("xb") as destination_handle:
                while chunk := source_handle.read(_COPY_CHUNK_BYTES):
                    digest.update(chunk)
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
    except OSError as exc:
        raise SessionMergeError(
            f"session database snapshot failed: {source}",
            stable_code="session_merge_snapshot_failed",
        ) from exc
    return identity, digest.hexdigest()


def _digest_file(path: Path) -> tuple[PathIdentity, str]:
    descriptor, identity = _open_source_file(path)
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            while chunk := handle.read(_COPY_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise SessionMergeError(
            f"session database changed while validating: {path}",
            stable_code="session_merge_source_changed",
        ) from exc
    return identity, digest.hexdigest()


def _bundle_paths(database: Path) -> tuple[Path, ...]:
    paths = [database]
    for suffix in ("-wal", "-journal"):
        candidate = Path(f"{database}{suffix}")
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        paths.append(candidate)
    return tuple(paths)


def _normalize_snapshot(copied_database: Path, normalized_database: Path) -> None:
    try:
        with contextlib.closing(sqlite3.connect(copied_database)) as source:
            with source:
                result = source.execute("PRAGMA integrity_check").fetchone()
                if result is None or result[0] != "ok":
                    raise SessionMergeError(
                        "source session database failed integrity validation",
                        stable_code="session_merge_source_invalid",
                    )
                with contextlib.closing(sqlite3.connect(normalized_database)) as target:
                    with target:
                        source.backup(target)
                        target_result = target.execute("PRAGMA integrity_check").fetchone()
                        if target_result is None or target_result[0] != "ok":
                            raise SessionMergeError(
                                "session database snapshot failed integrity validation",
                                stable_code="session_merge_snapshot_failed",
                            )
    except SessionMergeError:
        raise
    except sqlite3.Error as exc:
        raise SessionMergeError(
            "source session database is not a valid SQLite database",
            stable_code="session_merge_source_invalid",
        ) from exc


def _stable_source_snapshot(source_database: Path, directory: Path) -> Path:
    """Copy a stable database/WAL bundle without ever opening the source in SQLite."""

    _identity(source_database)
    for attempt in range(_SNAPSHOT_ATTEMPTS):
        attempt_directory = directory / f"attempt-{attempt}"
        attempt_directory.mkdir(mode=0o700)
        copied_database = attempt_directory / "sessions.db"
        members_before = _bundle_paths(source_database)
        copied: dict[str, tuple[PathIdentity, str]] = {}
        try:
            for member in members_before:
                suffix = str(member)[len(str(source_database)) :]
                destination = Path(f"{copied_database}{suffix}")
                copied[suffix] = _copy_and_digest(member, destination)
        except SessionMergeError as exc:
            if (
                exc.stable_code == "session_merge_source_missing"
                and source_database.exists()
            ):
                continue
            raise

        members_after = _bundle_paths(source_database)
        if tuple(str(path) for path in members_before) != tuple(
            str(path) for path in members_after
        ):
            continue
        stable = True
        for member in members_after:
            suffix = str(member)[len(str(source_database)) :]
            try:
                identity, digest = _digest_file(member)
            except SessionMergeError:
                stable = False
                break
            if copied.get(suffix) != (identity, digest):
                stable = False
                break
        if not stable:
            continue

        normalized = attempt_directory / "normalized.db"
        _normalize_snapshot(copied_database, normalized)
        return normalized

    raise SessionMergeError(
        "source session database did not remain stable long enough to snapshot",
        stable_code="session_merge_source_busy",
    )


def _without_marker(origin: object) -> object:
    if not isinstance(origin, dict) or _MERGE_MARKER not in origin:
        return origin
    cleaned = dict(origin)
    cleaned.pop(_MERGE_MARKER, None)
    return cleaned or None


def _conversation_payload(node: Any, entries: tuple[Any, ...]) -> dict[str, object]:
    node_payload = node.model_dump(mode="json")
    node_payload["origin"] = _without_marker(node_payload.get("origin"))
    entry_payloads: list[dict[str, object]] = []
    for entry in entries:
        payload = entry.model_dump(mode="json", exclude={"id"})
        entry_payloads.append(payload)
    return {"node": node_payload, "entries": entry_payloads}


def _conversation_fingerprint(node: Any, entries: tuple[Any, ...]) -> str:
    try:
        encoded = json.dumps(
            _conversation_payload(node, entries),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SessionMergeError(
            "session data cannot be represented safely",
            stable_code="session_merge_source_invalid",
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _entry_fingerprint(entry: Any) -> str:
    try:
        encoded = json.dumps(
            entry.model_dump(mode="json", exclude={"id"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SessionMergeError(
            "transcript data cannot be represented safely",
            stable_code="session_merge_source_invalid",
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _merge_id(node: Any, source_scope: str) -> str:
    identity = json.dumps(
        {
            "source_scope": source_scope,
            "session_key": node.session_key,
            "session_id": node.session_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return str(uuid.uuid5(_MERGE_NAMESPACE, identity))


def _offline_session_storage(database: Path) -> Any:
    """Open/migrate storage without applying runtime-restart lifecycle updates."""

    from opensquilla.session.storage import SessionStorage

    class _OfflineSessionStorage(SessionStorage):
        async def mark_abandoned_agent_tasks(self, now_ms: int | None = None) -> int:
            del now_ms
            return 0

    return _OfflineSessionStorage(str(database))


async def _load_source_conversations(
    snapshot: Path,
    *,
    source_scope: str,
) -> _ConversationSnapshot:
    storage = _offline_session_storage(snapshot)
    try:
        await storage.connect()
        orphaned_session_ids = await storage.list_orphaned_transcript_session_ids()
        nodes = await storage.list_session_nodes_for_recovery()
        blocked_codes: set[str] = set()
        sessions_blocked = len(orphaned_session_ids)
        if orphaned_session_ids:
            blocked_codes.add("session_merge_source_invalid")

        session_id_counts: dict[str, int] = {}
        for node in nodes:
            session_id_counts[node.session_id] = (
                session_id_counts.get(node.session_id, 0) + 1
            )

        conversations: list[_Conversation] = []
        for node in nodes:
            if session_id_counts[node.session_id] > 1:
                sessions_blocked += 1
                blocked_codes.add("session_merge_source_invalid")
                continue
            try:
                coverage = await storage.get_canonical_transcript_coverage(
                    node.session_id
                )
                if not coverage.canonical_complete:
                    raise SessionMergeError(
                        f"canonical transcript is incomplete for {node.session_key}",
                        stable_code="session_merge_source_incomplete",
                    )
                entries = tuple(
                    await storage.get_canonical_transcript(node.session_id)
                )
                if any(entry.session_id != node.session_id for entry in entries):
                    raise SessionMergeError(
                        f"canonical transcript identity is invalid for {node.session_key}",
                        stable_code="session_merge_source_invalid",
                    )
                fingerprint = _conversation_fingerprint(node, entries)
            except SessionMergeError as exc:
                sessions_blocked += 1
                blocked_codes.add(exc.stable_code)
                continue
            except Exception:
                sessions_blocked += 1
                blocked_codes.add("session_merge_source_invalid")
                continue
            conversations.append(
                _Conversation(
                    node=node,
                    entries=entries,
                    source_fingerprint=fingerprint,
                    merge_id=_merge_id(node, source_scope),
                )
            )
        return _ConversationSnapshot(
            conversations=tuple(conversations),
            sessions_found=len(nodes) + len(orphaned_session_ids),
            sessions_blocked=sessions_blocked,
            blocked_codes=tuple(sorted(blocked_codes)),
        )
    except SessionMergeError:
        raise
    except Exception as exc:
        raise SessionMergeError(
            "source session database could not be decoded",
            stable_code="session_merge_source_invalid",
        ) from exc
    finally:
        await storage.close()


def _snapshot_material_file(source: Path, destination: Path) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied_identity, copied_digest = _copy_and_digest(source, destination)
    current_identity, current_digest = _digest_file(source)
    if (copied_identity, copied_digest) != (current_identity, current_digest):
        raise SessionMergeError(
            f"source session material changed while snapshotting: {source}",
            stable_code="session_merge_source_changed",
        )
    return copied_digest, copied_identity.size


def _snapshot_session_attachments(
    source_media_root: Path,
    conversation: _Conversation,
    destination: Path,
) -> tuple[_AttachmentMaterial, ...]:
    from opensquilla.attachment_refs import transcript_material_dir

    expected_hashes: set[str] = set()
    for entry in conversation.entries:
        content = entry.content
        if not isinstance(content, str):
            continue
        try:
            envelope = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(envelope, dict):
            continue
        raw_attachments = envelope.get("attachments")
        if not isinstance(raw_attachments, list):
            continue
        for attachment in raw_attachments:
            if not isinstance(attachment, dict) or "sha256_ref" not in attachment:
                continue
            sha = attachment.get("sha256_ref")
            if (
                not isinstance(sha, str)
                or len(sha) != 64
                or any(character not in "0123456789abcdefABCDEF" for character in sha)
            ):
                raise SessionMergeError(
                    "source transcript attachment reference is invalid",
                    stable_code="session_merge_material_invalid",
                )
            expected_hashes.add(sha.lower())

    source_directory = transcript_material_dir(
        source_media_root,
        conversation.node.session_id,
    )
    try:
        source_directory.lstat()
    except FileNotFoundError:
        if expected_hashes:
            raise SessionMergeError(
                "source transcript attachment material is missing",
                stable_code="session_merge_material_invalid",
            )
        return ()
    if not source_directory.is_dir() or source_directory.is_symlink():
        raise UnsafePathError(
            f"session transcript material is not a plain directory: {source_directory}"
        )

    attachments: list[_AttachmentMaterial] = []
    for source_path in sorted(source_directory.iterdir(), key=lambda item: item.name):
        if not source_path.is_file() or source_path.is_symlink():
            continue
        name = source_path.name
        if len(name) != 64 or any(character not in "0123456789abcdef" for character in name):
            continue
        snapshot_path = destination / "attachments" / name
        digest, size = _snapshot_material_file(source_path, snapshot_path)
        if digest != name:
            raise SessionMergeError(
                f"source transcript material hash is invalid: {source_path}",
                stable_code="session_merge_material_invalid",
            )
        attachments.append(
            _AttachmentMaterial(
                sha256=name,
                snapshot_path=snapshot_path,
                size=size,
            )
        )
    copied_hashes = {attachment.sha256 for attachment in attachments}
    if not expected_hashes.issubset(copied_hashes):
        raise SessionMergeError(
            "source transcript attachment material is incomplete",
            stable_code="session_merge_material_invalid",
        )
    return tuple(attachments)


def _snapshot_session_artifacts(
    source_media_root: Path,
    conversation: _Conversation,
    destination: Path,
) -> tuple[_ArtifactMaterial, ...]:
    from opensquilla.artifacts import ArtifactRef, ArtifactStore

    store = ArtifactStore(source_media_root)
    artifacts: dict[str, _ArtifactMaterial] = {}
    for index, meta_path in enumerate(
        store._iter_session_meta_paths(conversation.node.session_id)
    ):
        artifact_directory = destination / "artifacts" / f"{index:08d}"
        meta_snapshot = artifact_directory / "meta.json"
        _snapshot_material_file(meta_path, meta_snapshot)
        try:
            payload = json.loads(meta_snapshot.read_text(encoding="utf-8"))
            ref = ArtifactRef.from_dict(payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SessionMergeError(
                f"source artifact metadata is invalid: {meta_path}",
                stable_code="session_merge_material_invalid",
            ) from exc
        if ref.session_id != conversation.node.session_id:
            raise SessionMergeError(
                f"source artifact belongs to another session: {meta_path}",
                stable_code="session_merge_material_invalid",
            )
        source_material = store.path_for(ref)
        material_snapshot = artifact_directory / "data"
        digest, size = _snapshot_material_file(source_material, material_snapshot)
        if digest != ref.sha256 or size != ref.size:
            raise SessionMergeError(
                f"source artifact material is invalid: {source_material}",
                stable_code="session_merge_material_invalid",
            )
        thumbnail_snapshot: Path | None = None
        thumbnail_size = 0
        if ref.has_thumbnail:
            source_thumbnail = store.thumbnail_path_for(ref)
            thumbnail_snapshot = artifact_directory / "thumbnail"
            _, thumbnail_size = _snapshot_material_file(
                source_thumbnail,
                thumbnail_snapshot,
            )
        candidate = _ArtifactMaterial(
            ref_payload=ref.to_dict(),
            snapshot_path=material_snapshot,
            thumbnail_path=thumbnail_snapshot,
            size=size,
            thumbnail_size=thumbnail_size,
        )
        previous = artifacts.get(ref.id)
        if previous is not None:
            if previous.ref_payload != candidate.ref_payload:
                raise SessionMergeError(
                    f"source artifact identity is ambiguous: {ref.id}",
                    stable_code="session_merge_material_invalid",
                )
            continue
        artifacts[ref.id] = candidate
    return tuple(artifacts[key] for key in sorted(artifacts))


def _snapshot_source_materials(
    source_media_root: Path,
    conversations: tuple[_Conversation, ...],
    destination: Path,
) -> _MaterialSnapshot:
    source_root = _absolute(source_media_root)
    try:
        source_root.lstat()
    except FileNotFoundError:
        pass
    else:
        try:
            no_follow_manifest(source_root)
        except (OSError, UnsafePathError):
            return _MaterialSnapshot(
                sessions={},
                blocked_session_ids=frozenset(
                    conversation.merge_id for conversation in conversations
                ),
                blocked_codes=("session_merge_material_invalid",),
            )

    sessions: dict[str, _SessionMaterials] = {}
    blocked_session_ids: set[str] = set()
    blocked_codes: set[str] = set()
    for conversation in conversations:
        session_destination = destination / conversation.merge_id
        try:
            attachments = _snapshot_session_attachments(
                source_root,
                conversation,
                session_destination,
            )
            artifacts = _snapshot_session_artifacts(
                source_root,
                conversation,
                session_destination,
            )
        except RecoveryError as exc:
            blocked_session_ids.add(conversation.merge_id)
            blocked_codes.add(exc.stable_code)
            continue
        except OSError:
            blocked_session_ids.add(conversation.merge_id)
            blocked_codes.add("session_merge_material_invalid")
            continue
        if attachments or artifacts:
            sessions[conversation.merge_id] = _SessionMaterials(
                attachments=attachments,
                artifacts=artifacts,
            )
    return _MaterialSnapshot(
        sessions=sessions,
        blocked_session_ids=frozenset(blocked_session_ids),
        blocked_codes=tuple(sorted(blocked_codes)),
    )


def _prepare_target_media_root(target_media_root: Path) -> Path:
    target_root = _absolute(target_media_root)
    try:
        target_guard = _parent_chain_identities(target_root)
        if os.name == "nt":
            target_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        else:
            descriptor = _open_posix_target_directory(target_root, target_guard)
            os.close(descriptor)
        no_follow_manifest(target_root)
    except (OSError, UnsafePathError) as exc:
        raise SessionMergeError(
            "target media root is unsafe or unreadable",
            stable_code="session_merge_material_target_invalid",
        ) from exc
    return target_root


def _copy_snapshot_file(
    source: Path,
    target: Path,
    *,
    expected_sha256: str | None = None,
) -> int:
    from opensquilla.artifacts import _link_or_copy

    if target.exists():
        if not target.is_file() or target.is_symlink():
            raise SessionMergeError(
                f"target session material is unsafe: {target}",
                stable_code="session_merge_material_target_invalid",
            )
        _, digest = _digest_file(target)
        if expected_sha256 is not None and digest != expected_sha256:
            raise SessionMergeError(
                f"target session material conflicts with recovered content: {target}",
                stable_code="session_merge_material_target_conflict",
            )
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _link_or_copy(source, target)
    except OSError as exc:
        raise SessionMergeError(
            f"target session material could not be copied: {target}",
            stable_code="session_merge_material_target_failed",
        ) from exc
    identity, digest = _digest_file(target)
    if expected_sha256 is not None and digest != expected_sha256:
        raise SessionMergeError(
            f"copied target session material failed validation: {target}",
            stable_code="session_merge_material_target_failed",
        )
    return identity.size


def _copy_session_materials(
    snapshot: _MaterialSnapshot,
    target_media_root: Path,
    plan: _PlannedConversation,
) -> _MaterialCopyReport:
    from dataclasses import replace as dataclass_replace

    from opensquilla.artifacts import (
        ARTIFACT_MATERIAL_NAME,
        ARTIFACT_THUMBNAIL_NAME,
        ArtifactRef,
        ArtifactStore,
        _atomic_write_bytes,
    )
    from opensquilla.attachment_refs import transcript_material_path

    materials = snapshot.sessions.get(plan.source.merge_id)
    if materials is None:
        return _MaterialCopyReport()

    attachments_copied = 0
    artifacts_copied = 0
    bytes_copied = 0
    for attachment in materials.attachments:
        target_path = transcript_material_path(
            target_media_root,
            plan.session_id,
            attachment.sha256,
        )
        written = _copy_snapshot_file(
            attachment.snapshot_path,
            target_path,
            expected_sha256=attachment.sha256,
        )
        if written:
            attachments_copied += 1
            bytes_copied += written

    target_store = ArtifactStore(target_media_root)
    for artifact in materials.artifacts:
        ref = ArtifactRef.from_dict(dict(artifact.ref_payload))
        child_ref = dataclass_replace(
            ref,
            session_id=plan.session_id,
            session_key=plan.session_key,
            has_thumbnail=artifact.thumbnail_path is not None,
        )
        target_directory = target_store._artifact_dir(plan.session_id, ref.id)
        target_material = target_directory / ARTIFACT_MATERIAL_NAME
        target_meta = target_directory / "meta.json"
        target_thumbnail = target_directory / ARTIFACT_THUMBNAIL_NAME
        meta_existed = target_meta.exists()
        if meta_existed:
            try:
                existing_ref = ArtifactRef.from_dict(
                    json.loads(target_meta.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise SessionMergeError(
                    f"target artifact metadata is invalid: {target_meta}",
                    stable_code="session_merge_material_target_conflict",
                ) from exc
            if existing_ref != child_ref:
                raise SessionMergeError(
                    f"target artifact metadata conflicts with recovery: {target_meta}",
                    stable_code="session_merge_material_target_conflict",
                )
        material_written = _copy_snapshot_file(
            artifact.snapshot_path,
            target_material,
            expected_sha256=ref.sha256,
        )
        bytes_copied += material_written
        thumbnail_written = 0
        if artifact.thumbnail_path is not None:
            thumbnail_written = _copy_snapshot_file(
                artifact.thumbnail_path,
                target_thumbnail,
            )
            bytes_copied += thumbnail_written
        if not meta_existed:
            _atomic_write_bytes(
                target_meta,
                json.dumps(
                    child_ref.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8"),
            )
        if not meta_existed or material_written or thumbnail_written:
            artifacts_copied += 1

    return _MaterialCopyReport(
        attachment_files_copied=attachments_copied,
        artifacts_copied=artifacts_copied,
        material_bytes_copied=bytes_copied,
    )


def _marker(node: Any) -> dict[str, object] | None:
    origin = node.origin
    if not isinstance(origin, dict):
        return None
    marker = origin.get(_MERGE_MARKER)
    return marker if isinstance(marker, dict) else None


def _recovered_key(source_key: str, merge_id: str, counter: int = 0) -> str:
    suffix = f":recovered:{merge_id[:12]}"
    if counter:
        suffix += f":{counter}"
    return f"{source_key[: 512 - len(suffix)]}{suffix}"


def _replacement_session_id(merge_id: str, counter: int = 0) -> str:
    name = merge_id if counter == 0 else f"{merge_id}:{counter}"
    return str(uuid.uuid5(_MERGE_NAMESPACE, name))


async def _target_conversations(conn: Any) -> dict[str, _TargetConversation]:
    from opensquilla.session.models import SessionNode
    from opensquilla.session.storage import SessionStorage, _deserialize_row

    async with conn.execute("SELECT * FROM sessions ORDER BY session_key") as cursor:
        rows = await cursor.fetchall()
    result: dict[str, _TargetConversation] = {}
    for row in rows:
        node = SessionNode(**_deserialize_row(dict(row)))
        entries = tuple(
            await SessionStorage._select_canonical_transcript(conn, node.session_id)
        )
        result[node.session_key] = _TargetConversation(node=node, entries=entries)
    return result


async def _target_receipts(conn: Any) -> dict[str, _MergeReceipt]:
    await conn.execute(_CREATE_MERGE_RECEIPTS)
    async with conn.execute(
        """
        SELECT
            merge_id,
            schema_version,
            source_session_key,
            source_session_id,
            source_updated_at,
            transcript_entries,
            last_message_id,
            last_created_at,
            target_session_key,
            target_session_id
        FROM desktop_session_merge_receipts
        ORDER BY merge_id
        """
    ) as cursor:
        rows = await cursor.fetchall()
    receipts: dict[str, _MergeReceipt] = {}
    for row in rows:
        if int(row["schema_version"]) != 1:
            raise SessionMergeError(
                "target session merge receipt has an unsupported schema",
                stable_code="session_merge_target_conflict",
            )
        receipt = _MergeReceipt(
            merge_id=str(row["merge_id"]),
            source_session_key=str(row["source_session_key"]),
            source_session_id=str(row["source_session_id"]),
            source_updated_at=int(row["source_updated_at"]),
            transcript_entries=int(row["transcript_entries"]),
            last_message_id=(
                str(row["last_message_id"])
                if row["last_message_id"] is not None
                else None
            ),
            last_created_at=(
                int(row["last_created_at"])
                if row["last_created_at"] is not None
                else None
            ),
            target_session_key=str(row["target_session_key"]),
            target_session_id=str(row["target_session_id"]),
        )
        receipts[receipt.merge_id] = receipt
    return receipts


def _receipt_matches_source(receipt: _MergeReceipt, source: _Conversation) -> bool:
    last_entry = source.entries[-1] if source.entries else None
    return (
        receipt.source_session_key == source.node.session_key
        and receipt.source_session_id == source.node.session_id
        and receipt.source_updated_at == int(source.node.updated_at)
        and receipt.transcript_entries == len(source.entries)
        and receipt.last_message_id
        == (last_entry.message_id if last_entry is not None else None)
        and receipt.last_created_at
        == (int(last_entry.created_at) if last_entry is not None else None)
    )


async def _write_receipt(
    conn: Any,
    source: _Conversation,
    *,
    target_session_key: str,
    target_session_id: str,
) -> None:
    last_entry = source.entries[-1] if source.entries else None
    await conn.execute(
        """
        INSERT INTO desktop_session_merge_receipts (
            merge_id,
            schema_version,
            source_session_key,
            source_session_id,
            source_updated_at,
            transcript_entries,
            last_message_id,
            last_created_at,
            target_session_key,
            target_session_id,
            imported_at
        ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source.merge_id,
            source.node.session_key,
            source.node.session_id,
            int(source.node.updated_at),
            len(source.entries),
            last_entry.message_id if last_entry is not None else None,
            int(last_entry.created_at) if last_entry is not None else None,
            target_session_key,
            target_session_id,
            int(time.time() * 1000),
        ),
    )


def _validate_matching_marker(
    source: _Conversation,
    target: _TargetConversation,
) -> None:
    marker = _marker(target.node)
    if marker is None:
        raise SessionMergeError(
            "session merge marker disappeared",
            stable_code="session_merge_target_conflict",
        )
    if (
        marker.get("schema_version") != 1
        or marker.get("merge_id") != source.merge_id
        or marker.get("transcript_entries") != len(source.entries)
        or marker.get("source_session_key") != source.node.session_key
        or marker.get("source_session_id") != source.node.session_id
    ):
        raise SessionMergeError(
            "an existing recovered conversation no longer matches its merge receipt",
            stable_code="session_merge_target_conflict",
        )
    _validate_source_transcript_present(source, target)


def _validate_source_transcript_present(
    source: _Conversation,
    target: _TargetConversation,
) -> None:
    expected = [
        _entry_fingerprint(
            entry.model_copy(
                deep=True,
                update={
                    "id": None,
                    "session_key": target.node.session_key,
                    "session_id": target.node.session_id,
                },
            )
        )
        for entry in source.entries
    ]
    remaining = iter(_entry_fingerprint(entry) for entry in target.entries)
    transcript_missing = any(
        not any(candidate == fingerprint for candidate in remaining)
        for fingerprint in expected
    )
    if transcript_missing:
        raise SessionMergeError(
            "an existing recovered conversation no longer contains its source transcript",
            stable_code="session_merge_target_conflict",
        )


def _plan_conversations(
    sources: tuple[_Conversation, ...],
    targets: dict[str, _TargetConversation],
    receipts: dict[str, _MergeReceipt],
) -> tuple[_PlannedConversation, ...]:
    used_keys = set(targets)
    used_ids = {target.node.session_id for target in targets.values()}
    marker_index: dict[str, list[_TargetConversation]] = {}
    for target in targets.values():
        marker = _marker(target.node)
        merge_id = marker.get("merge_id") if marker is not None else None
        if isinstance(merge_id, str):
            marker_index.setdefault(merge_id, []).append(target)

    planned: list[_PlannedConversation] = []
    for source in sources:
        receipt = receipts.get(source.merge_id)
        if receipt is not None:
            if not _receipt_matches_source(receipt, source):
                raise SessionMergeError(
                    "source session changed after its completed merge",
                    stable_code="session_merge_source_changed",
                )
            receipt_target = targets.get(receipt.target_session_key)
            if (
                receipt_target is not None
                and receipt_target.node.session_id == receipt.target_session_id
            ):
                _validate_source_transcript_present(source, receipt_target)
            planned.append(
                _PlannedConversation(
                    source=source,
                    session_key=receipt.target_session_key,
                    session_id=receipt.target_session_id,
                    existing=True,
                    collision_resolved=(
                        receipt.target_session_key != source.node.session_key
                    ),
                    receipt_required=False,
                )
            )
            continue

        marked = marker_index.get(source.merge_id, [])
        if len(marked) > 1:
            raise SessionMergeError(
                "duplicate session merge receipts exist in the target database",
                stable_code="session_merge_target_conflict",
            )
        if marked:
            target = marked[0]
            _validate_matching_marker(source, target)
            planned.append(
                _PlannedConversation(
                    source=source,
                    session_key=target.node.session_key,
                    session_id=target.node.session_id,
                    existing=True,
                    collision_resolved=target.node.session_key != source.node.session_key,
                    receipt_required=True,
                )
            )
            continue

        same_key = targets.get(source.node.session_key)
        if (
            same_key is not None
            and _marker(same_key.node) is None
            and _conversation_fingerprint(same_key.node, same_key.entries)
            == source.source_fingerprint
        ):
            planned.append(
                _PlannedConversation(
                    source=source,
                    session_key=same_key.node.session_key,
                    session_id=same_key.node.session_id,
                    existing=True,
                    collision_resolved=False,
                    receipt_required=True,
                )
            )
            continue

        collision = source.node.session_key in used_keys
        session_key = source.node.session_key
        counter = 0
        while session_key in used_keys:
            session_key = _recovered_key(source.node.session_key, source.merge_id, counter)
            counter += 1
        used_keys.add(session_key)

        session_id = source.node.session_id
        counter = 0
        while session_id in used_ids:
            session_id = _replacement_session_id(source.merge_id, counter)
            counter += 1
        used_ids.add(session_id)
        planned.append(
            _PlannedConversation(
                source=source,
                session_key=session_key,
                session_id=session_id,
                existing=False,
                collision_resolved=collision,
                receipt_required=False,
            )
        )
    return tuple(planned)


def _materialize(
    plan: _PlannedConversation,
    key_map: dict[str, str],
) -> tuple[Any, tuple[Any, ...]]:
    node = plan.source.node.model_copy(deep=True)
    node.session_key = plan.session_key
    node.session_id = plan.session_id
    node.compaction_count = 0
    node.forked_from_parent = False
    if node.spawned_by in key_map:
        node.spawned_by = key_map[node.spawned_by]
    if node.parent_session_key in key_map:
        node.parent_session_key = key_map[node.parent_session_key]

    entries = tuple(
        entry.model_copy(
            deep=True,
            update={
                "id": None,
                "session_key": plan.session_key,
                "session_id": plan.session_id,
            },
        )
        for entry in plan.source.entries
    )
    origin = dict(node.origin) if isinstance(node.origin, dict) else {}
    origin[_MERGE_MARKER] = _marker_payload(plan.source)
    node.origin = origin
    return node, entries


def _marker_payload(source: _Conversation) -> dict[str, object]:
    return {
        "schema_version": 1,
        "merge_id": source.merge_id,
        "transcript_entries": len(source.entries),
        "source_session_key": source.node.session_key,
        "source_session_id": source.node.session_id,
    }


async def _write_existing_receipt(
    conn: Any,
    target: _TargetConversation,
    source: _Conversation,
) -> None:
    from opensquilla.session.storage import _serialize

    origin = dict(target.node.origin) if isinstance(target.node.origin, dict) else {}
    origin[_MERGE_MARKER] = _marker_payload(source)
    await conn.execute(
        "UPDATE sessions SET origin = ? WHERE session_key = ?",
        (_serialize(origin), target.node.session_key),
    )


async def _insert_conversation(conn: Any, node: Any, entries: tuple[Any, ...]) -> None:
    from opensquilla.session.storage import SessionStorage, _serialize

    data = node.model_dump()
    columns = list(data)
    placeholders = ", ".join("?" for _ in columns)
    await conn.execute(
        f"INSERT INTO sessions ({', '.join(columns)}) VALUES ({placeholders})",
        [_serialize(data[column]) for column in columns],
    )
    for entry in entries:
        await SessionStorage._insert_transcript_entry(
            conn,
            entry,
            expected_epoch=None,
        )


async def _merge_into_target(
    sources: tuple[_Conversation, ...],
    *,
    binding: _TargetBinding,
    materials: _MaterialSnapshot | None,
    target_media_root: Path | None,
) -> _TargetMergeReport:
    storage = _offline_session_storage(binding.storage_path)
    try:
        await storage.connect()
        binding.verify()
        async with storage._write_transaction(
            "merge_recovery_sessions",
            budget_seconds=5.0,
        ) as conn:
            targets = await _target_conversations(conn)
            receipts = await _target_receipts(conn)
            planned = _plan_conversations(sources, targets, receipts)
            key_map = {
                plan.source.node.session_key: plan.session_key for plan in planned
            }
            imported = 0
            skipped = 0
            collisions = 0
            transcript_entries = 0
            attachment_files_copied = 0
            artifacts_copied = 0
            material_bytes_copied = 0
            material_blocked_session_ids: set[str] = set()
            blocked_codes: set[str] = set()
            for plan in planned:
                target_conversation = targets.get(plan.session_key)
                target_still_exists = (
                    target_conversation is not None
                    and target_conversation.node.session_id == plan.session_id
                )
                if (
                    materials is not None
                    and target_media_root is not None
                    and (not plan.existing or target_still_exists)
                ):
                    try:
                        material_report = _copy_session_materials(
                            materials,
                            target_media_root,
                            plan,
                        )
                    except RecoveryError as exc:
                        material_blocked_session_ids.add(plan.source.merge_id)
                        blocked_codes.add(exc.stable_code)
                    except OSError:
                        material_blocked_session_ids.add(plan.source.merge_id)
                        blocked_codes.add("session_merge_material_target_failed")
                    else:
                        attachment_files_copied += (
                            material_report.attachment_files_copied
                        )
                        artifacts_copied += material_report.artifacts_copied
                        material_bytes_copied += (
                            material_report.material_bytes_copied
                        )
                if plan.existing:
                    if plan.receipt_required:
                        await _write_existing_receipt(
                            conn,
                            targets[plan.session_key],
                            plan.source,
                        )
                        await _write_receipt(
                            conn,
                            plan.source,
                            target_session_key=plan.session_key,
                            target_session_id=plan.session_id,
                        )
                    skipped += 1
                    continue
                node, entries = _materialize(plan, key_map)
                await _insert_conversation(conn, node, entries)
                await _write_receipt(
                    conn,
                    plan.source,
                    target_session_key=plan.session_key,
                    target_session_id=plan.session_id,
                )
                imported += 1
                collisions += int(plan.collision_resolved)
                transcript_entries += len(entries)
            binding.verify()
            result = _TargetMergeReport(
                sessions_imported=imported,
                sessions_skipped=skipped,
                collisions_resolved=collisions,
                transcript_entries_imported=transcript_entries,
                materials=_MaterialCopyReport(
                    attachment_files_copied=attachment_files_copied,
                    artifacts_copied=artifacts_copied,
                    material_bytes_copied=material_bytes_copied,
                ),
                material_blocked_session_ids=frozenset(
                    material_blocked_session_ids
                ),
                blocked_codes=tuple(sorted(blocked_codes)),
            )
        # Re-check the lexical target after SQLite has committed and removed or
        # finalized its journal. A parent-directory swap during commit must not
        # be reported as a successful merge into the primary profile.
        binding.verify()
        return result
    except SessionMergeError:
        raise
    except Exception as exc:
        raise SessionMergeError(
            "target session database could not accept the recovered conversations",
            stable_code="session_merge_target_failed",
        ) from exc
    finally:
        await storage.close()


def _link_or_reparse(value: os.stat_result) -> bool:
    reparse_attribute = int(getattr(value, "st_file_attributes", 0)) & 0x400
    return (
        stat.S_ISLNK(value.st_mode)
        or bool(int(getattr(value, "st_reparse_tag", 0)))
        or bool(reparse_attribute)
    )


def _parent_chain_identities(directory: Path) -> dict[str, PathIdentity]:
    identities: dict[str, PathIdentity] = {}
    current = directory
    while True:
        try:
            value = current.lstat()
        except FileNotFoundError:
            pass
        else:
            if _link_or_reparse(value):
                raise UnsafePathError(
                    f"session merge refuses target parent links or reparse points: {current}"
                )
            if not stat.S_ISDIR(value.st_mode):
                raise UnsafePathError(
                    f"session merge requires target parents to be directories: {current}"
                )
            identities[os.path.normcase(os.path.normpath(str(current)))] = (
                PathIdentity.from_stat(value)
            )
        parent = current.parent
        if parent == current:
            break
        current = parent
    return identities


def _validate_parent_guard(
    directory: Path,
    expected: dict[str, PathIdentity],
) -> dict[str, PathIdentity]:
    observed = _parent_chain_identities(directory)
    for key, identity in expected.items():
        current = observed.get(key)
        if (
            current is None
            or current.device != identity.device
            or current.inode != identity.inode
            or current.mode != identity.mode
            or current.reparse_tag != identity.reparse_tag
        ):
            raise SessionMergeError(
                "target session database parent changed during merge",
                stable_code="session_merge_target_changed",
            )
    return observed


def _same_object(actual: PathIdentity, expected: PathIdentity) -> bool:
    return (
        actual.device == expected.device
        and actual.inode == expected.inode
        and actual.mode == expected.mode
        and actual.reparse_tag == expected.reparse_tag
    )


def _open_posix_target_directory(
    directory: Path,
    expected: dict[str, PathIdentity],
) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    anchor = Path(directory.anchor)
    try:
        descriptor = os.open(anchor, flags)
    except OSError as exc:
        raise UnsafePathError("cannot bind target filesystem root") from exc
    current = anchor
    try:
        parts = directory.parts[1:]
        for part in parts:
            current /= part
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    child = os.open(part, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise UnsafePathError(
                        f"cannot safely create target directory: {current}"
                    ) from exc
            except OSError as exc:
                raise UnsafePathError(
                    f"cannot safely bind target directory: {current}"
                ) from exc
            value = os.fstat(child)
            if not stat.S_ISDIR(value.st_mode):
                os.close(child)
                raise UnsafePathError(
                    f"target path component is not a directory: {current}"
                )
            identity = PathIdentity.from_stat(value)
            expected_identity = expected.get(
                os.path.normcase(os.path.normpath(str(current)))
            )
            if expected_identity is not None and not _same_object(
                identity,
                expected_identity,
            ):
                os.close(child)
                raise SessionMergeError(
                    "target parent changed while binding",
                    stable_code="session_merge_target_changed",
                )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextlib.contextmanager
def _bind_posix_target(
    target: Path,
    *,
    parent_guard: dict[str, PathIdentity],
    database_identity: PathIdentity | None,
) -> Iterator[_TargetBinding]:
    directory_fd = _open_posix_target_directory(target.parent, parent_guard)
    cwd_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        cwd_flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        cwd_flags |= os.O_CLOEXEC
    cwd_fd = os.open(".", cwd_flags)
    expected_database = [database_identity]

    def verify() -> None:
        try:
            value = os.stat(target.name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise SessionMergeError(
                "target session database disappeared while bound",
                stable_code="session_merge_target_changed",
            ) from exc
        if _link_or_reparse(value) or not stat.S_ISREG(value.st_mode):
            raise UnsafePathError("bound target session database is not a regular file")
        identity = PathIdentity.from_stat(value)
        if expected_database[0] is None:
            expected_database[0] = identity
        elif not _same_object(identity, expected_database[0]):
            raise SessionMergeError(
                "target session database changed while bound",
                stable_code="session_merge_target_changed",
            )
        parent_value = os.fstat(directory_fd)
        if not stat.S_ISDIR(parent_value.st_mode):
            raise SessionMergeError(
                "target session database parent changed while bound",
                stable_code="session_merge_target_changed",
            )
        try:
            lexical_parent = target.parent.lstat()
        except OSError as exc:
            raise SessionMergeError(
                "target session database parent disappeared while bound",
                stable_code="session_merge_target_changed",
            ) from exc
        if (
            _link_or_reparse(lexical_parent)
            or int(lexical_parent.st_dev) != int(parent_value.st_dev)
            or int(lexical_parent.st_ino) != int(parent_value.st_ino)
        ):
            raise SessionMergeError(
                "target session database parent changed while bound",
                stable_code="session_merge_target_changed",
            )

    try:
        os.fchdir(directory_fd)
        yield _TargetBinding(storage_path=Path(target.name), verify=verify)
    finally:
        try:
            os.fchdir(cwd_fd)
        finally:
            os.close(cwd_fd)
            os.close(directory_fd)


@contextlib.contextmanager
def _bind_windows_target(
    target: Path,
    *,
    parent_guard: dict[str, PathIdentity],
    database_identity: PathIdentity | None,
) -> Iterator[_TargetBinding]:
    from opensquilla.recovery import atomic as atomic_module

    win_dll = getattr(ctypes, "WinDLL")
    get_last_error = getattr(ctypes, "get_last_error")
    kernel32 = win_dll("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    get_information = kernel32.GetFileInformationByHandleEx
    close_handle = kernel32.CloseHandle
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    get_information.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    get_information.restype = ctypes.c_int
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_read_attributes = 0x00000080
    file_traverse = 0x00000020
    synchronize = 0x00100000
    generic_read = 0x80000000
    generic_write = 0x40000000
    create_new = 1
    open_existing = 3
    open_reparse = 0x00200000
    backup_semantics = 0x02000000
    attribute_tag_info = 9
    file_id_info = 18
    invalid_handle = ctypes.c_void_p(-1).value

    def open_handle(
        path: Path,
        *,
        access: int,
        disposition: int,
        directory: bool,
    ) -> int:
        flags = open_reparse | (backup_semantics if directory else 0)
        raw = create_file(
            atomic_module._windows_extended_path(path),
            access,
            file_share_read | file_share_write,
            None,
            disposition,
            flags,
            None,
        )
        value = atomic_module._windows_handle_value(raw)
        if value in {0, invalid_handle}:
            error_number = get_last_error()
            raise UnsafePathError(
                f"cannot bind Desktop session path (Windows error {error_number})"
            )
        return value

    def handle_identity(handle: int, *, require_directory: bool) -> PathIdentity:
        attributes = atomic_module._WindowsFileAttributeTagInfo()
        if not get_information(
            handle,
            attribute_tag_info,
            ctypes.byref(attributes),
            ctypes.sizeof(attributes),
        ):
            raise UnsafePathError("cannot inspect bound Desktop session path")
        if attributes.file_attributes & 0x400:
            raise UnsafePathError("bound Desktop session path is a reparse point")
        if require_directory and not attributes.file_attributes & 0x10:
            raise UnsafePathError("bound Desktop session parent is not a directory")
        if not require_directory and attributes.file_attributes & 0x10:
            raise UnsafePathError("bound Desktop session database is not a regular file")
        file_id = atomic_module._WindowsFileIdInfo()
        if not get_information(
            handle,
            file_id_info,
            ctypes.byref(file_id),
            ctypes.sizeof(file_id),
        ):
            raise UnsafePathError("cannot identify bound Desktop session path")
        return PathIdentity(
            device=int(file_id.volume_serial_number),
            inode=int.from_bytes(bytes(file_id.file_id.identifier), "little"),
            mode=stat.S_IFDIR if require_directory else stat.S_IFREG,
            size=0,
            modified_at_ns=0,
        )

    directory_chain: list[Path] = []
    current_directory = target.parent
    while True:
        directory_chain.append(current_directory)
        parent = current_directory.parent
        if parent == current_directory:
            break
        current_directory = parent
    directory_chain.reverse()

    # Hold every lexical ancestor without FILE_SHARE_DELETE. Holding only the
    # direct parent lets an attacker rename an ancestor and recreate the same
    # lexical path, redirecting SQLite while verification watches old handles.
    directory_handles: list[tuple[Path, int, PathIdentity]] = []
    target_handle = 0
    try:
        for index, directory in enumerate(directory_chain):
            try:
                handle = open_handle(
                    directory,
                    access=file_traverse | file_read_attributes | synchronize,
                    disposition=open_existing,
                    directory=True,
                )
            except UnsafePathError as open_error:
                if index == 0:
                    raise
                # Previously opened ancestors cannot be renamed while held.
                # Creating one missing child is therefore bounded to the
                # verified chain. A racing reparse point is rejected below.
                try:
                    directory.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise open_error from exc
                handle = open_handle(
                    directory,
                    access=file_traverse | file_read_attributes | synchronize,
                    disposition=open_existing,
                    directory=True,
                )
            try:
                identity = handle_identity(handle, require_directory=True)
                expected = parent_guard.get(
                    os.path.normcase(os.path.normpath(str(directory)))
                )
                if expected is not None and (
                    identity.device != expected.device
                    or identity.inode != expected.inode
                ):
                    raise SessionMergeError(
                        "target parent changed while binding",
                        stable_code="session_merge_target_changed",
                    )
            except BaseException:
                close_handle(handle)
                raise
            directory_handles.append((directory, handle, identity))

        target_handle = open_handle(
            target,
            access=generic_read | generic_write | synchronize,
            disposition=create_new if database_identity is None else open_existing,
            directory=False,
        )
        bound_identity = handle_identity(target_handle, require_directory=False)
        if (
            database_identity is not None
            and (
                bound_identity.device != database_identity.device
                or bound_identity.inode != database_identity.inode
            )
        ):
            raise SessionMergeError(
                "target session database changed while binding",
                stable_code="session_merge_target_changed",
            )

        def verify() -> None:
            for directory, handle, bound_directory in directory_handles:
                current_directory_identity = handle_identity(
                    handle,
                    require_directory=True,
                )
                if (
                    current_directory_identity.device != bound_directory.device
                    or current_directory_identity.inode != bound_directory.inode
                ):
                    raise SessionMergeError(
                        "target parent changed while bound",
                        stable_code="session_merge_target_changed",
                    )
                try:
                    lexical_directory = directory.lstat()
                except OSError as exc:
                    raise SessionMergeError(
                        "target parent disappeared while bound",
                        stable_code="session_merge_target_changed",
                    ) from exc
                lexical_directory_identity = PathIdentity.from_stat(lexical_directory)
                if (
                    _link_or_reparse(lexical_directory)
                    or not stat.S_ISDIR(lexical_directory.st_mode)
                    or lexical_directory_identity.device != bound_directory.device
                    or lexical_directory_identity.inode != bound_directory.inode
                ):
                    raise SessionMergeError(
                        "target parent changed while bound",
                        stable_code="session_merge_target_changed",
                    )
            current = handle_identity(target_handle, require_directory=False)
            if (
                current.device != bound_identity.device
                or current.inode != bound_identity.inode
            ):
                raise SessionMergeError(
                    "target session database changed while bound",
                    stable_code="session_merge_target_changed",
                )
            try:
                lexical_target = target.lstat()
            except OSError as exc:
                raise SessionMergeError(
                    "target session database disappeared while bound",
                    stable_code="session_merge_target_changed",
                ) from exc
            lexical_identity = PathIdentity.from_stat(lexical_target)
            if (
                _link_or_reparse(lexical_target)
                or not stat.S_ISREG(lexical_target.st_mode)
                or lexical_identity.device != bound_identity.device
                or lexical_identity.inode != bound_identity.inode
            ):
                raise SessionMergeError(
                    "target session database changed while bound",
                    stable_code="session_merge_target_changed",
                )

        yield _TargetBinding(storage_path=target, verify=verify)
    finally:
        if target_handle:
            close_handle(target_handle)
        for _, handle, _ in reversed(directory_handles):
            close_handle(handle)


@contextlib.contextmanager
def _bind_target_database(
    target: Path,
    *,
    parent_guard: dict[str, PathIdentity],
    database_identity: PathIdentity | None,
) -> Iterator[_TargetBinding]:
    if os.name == "nt":
        with _bind_windows_target(
            target,
            parent_guard=parent_guard,
            database_identity=database_identity,
        ) as binding:
            yield binding
        return
    with _bind_posix_target(
        target,
        parent_guard=parent_guard,
        database_identity=database_identity,
    ) as binding:
        yield binding


def _validate_target_path(
    source_database: Path,
    target_database: Path,
) -> tuple[dict[str, PathIdentity], PathIdentity | None]:
    parent_guard = _parent_chain_identities(target_database.parent)
    database_identity: PathIdentity | None = None
    source_identities: set[tuple[int, int]] = set()
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(f"{source_database}{suffix}")
        try:
            identity = _identity(candidate)
        except SessionMergeError as exc:
            if exc.stable_code == "session_merge_source_missing":
                continue
            raise
        source_identities.add((identity.device, identity.inode))

    for candidate in (
        target_database,
        Path(f"{target_database}-wal"),
        Path(f"{target_database}-shm"),
        Path(f"{target_database}-journal"),
    ):
        try:
            value = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(value.st_mode):
            raise UnsafePathError(
                f"session merge refuses target links or special files: {candidate}"
            )
        if candidate == target_database:
            database_identity = PathIdentity.from_stat(value)
        if (int(value.st_dev), int(value.st_ino)) in source_identities:
            raise SessionMergeError(
                "source and target session database bundles overlap",
                stable_code="session_merge_same_database",
            )
    return parent_guard, database_identity


def _merge_recovery_sessions(
    source_database: str | Path,
    target_database: str | Path,
    *,
    source_media_root: str | Path | None = None,
    target_media_root: str | Path | None = None,
) -> SessionMergeReport:
    """Merge all complete source conversations into the target exactly once."""

    source = _absolute(source_database)
    target = _absolute(target_database)
    if _same_path(source, target):
        raise SessionMergeError(
            "source and target session databases must be different",
            stable_code="session_merge_same_database",
        )
    if (source_media_root is None) != (target_media_root is None):
        raise SessionMergeError(
            "source and target media roots must be supplied together",
            stable_code="session_merge_media_options_invalid",
        )

    with tempfile.TemporaryDirectory(prefix="opensquilla-session-merge-") as raw_directory:
        temporary_root = Path(raw_directory)
        snapshot = _stable_source_snapshot(source, temporary_root)
        source_scope = os.path.normcase(os.path.normpath(str(source)))
        source_snapshot = asyncio.run(
            _load_source_conversations(snapshot, source_scope=source_scope)
        )
        conversations = source_snapshot.conversations
        materials: _MaterialSnapshot | None = None
        prepared_target_media_root: Path | None = None
        if source_media_root is not None and target_media_root is not None:
            materials = _snapshot_source_materials(
                _absolute(source_media_root),
                conversations,
                temporary_root / "materials",
            )
            if materials.sessions:
                # Only material snapshots proven safe create a destination root.
                # Missing or malformed source material remains source-local.
                try:
                    prepared_target_media_root = _prepare_target_media_root(
                        _absolute(target_media_root)
                    )
                except RecoveryError as exc:
                    materials = _MaterialSnapshot(
                        sessions={},
                        blocked_session_ids=frozenset(
                            set(materials.blocked_session_ids) | set(materials.sessions)
                        ),
                        blocked_codes=tuple(
                            sorted(set(materials.blocked_codes) | {exc.stable_code})
                        ),
                    )
                except OSError:
                    materials = _MaterialSnapshot(
                        sessions={},
                        blocked_session_ids=frozenset(
                            set(materials.blocked_session_ids) | set(materials.sessions)
                        ),
                        blocked_codes=tuple(
                            sorted(
                                set(materials.blocked_codes)
                                | {"session_merge_material_target_invalid"}
                            )
                        ),
                    )

        target_report = _TargetMergeReport()
        if conversations:
            # Invalid individual sessions are excluded above; healthy sessions
            # retain their own independent, idempotent receipts.
            parent_guard, database_identity = _validate_target_path(source, target)
            with _bind_target_database(
                target,
                parent_guard=parent_guard,
                database_identity=database_identity,
            ) as binding:
                target_report = asyncio.run(
                    _merge_into_target(
                        conversations,
                        binding=binding,
                        materials=materials,
                        target_media_root=prepared_target_media_root,
                    )
                )

    material_blocked_session_ids = set(
        materials.blocked_session_ids if materials is not None else ()
    )
    material_blocked_session_ids.update(
        target_report.material_blocked_session_ids
    )
    blocked_codes = set(source_snapshot.blocked_codes)
    if materials is not None:
        blocked_codes.update(materials.blocked_codes)
    blocked_codes.update(target_report.blocked_codes)
    material_report = target_report.materials
    changed = bool(
        target_report.sessions_imported
        or material_report.attachment_files_copied
        or material_report.artifacts_copied
        or material_report.material_bytes_copied
    )
    partial = bool(
        source_snapshot.sessions_blocked or material_blocked_session_ids
    )
    if partial:
        outcome: SessionMergeOutcome = "partial"
        stable_code = "session_merge_partial"
    else:
        outcome = "complete" if changed else "unchanged"
        stable_code = (
            "session_merge_complete" if changed else "session_merge_already_complete"
        )
    return SessionMergeReport(
        outcome=outcome,
        stable_code=stable_code,
        source_database=source,
        target_database=target,
        sessions_found=source_snapshot.sessions_found,
        sessions_imported=target_report.sessions_imported,
        sessions_skipped=target_report.sessions_skipped,
        sessions_blocked=source_snapshot.sessions_blocked,
        collisions_resolved=target_report.collisions_resolved,
        transcript_entries_imported=target_report.transcript_entries_imported,
        materials_status=(
            "not_requested"
            if materials is None
            else ("blocked" if material_blocked_session_ids else "complete")
        ),
        materials_sessions_blocked=len(material_blocked_session_ids),
        blocked_codes=tuple(sorted(blocked_codes)),
        attachment_files_copied=material_report.attachment_files_copied,
        artifacts_copied=material_report.artifacts_copied,
        material_bytes_copied=material_report.material_bytes_copied,
    )


def merge_recovery_sessions(
    source_database: str | Path,
    target_database: str | Path,
    *,
    source_media_root: str | Path | None = None,
    target_media_root: str | Path | None = None,
) -> SessionMergeReport:
    """Run the merge while keeping every failure machine-reportable."""

    try:
        return _merge_recovery_sessions(
            source_database,
            target_database,
            source_media_root=source_media_root,
            target_media_root=target_media_root,
        )
    except RecoveryError:
        raise
    except Exception as exc:
        raise SessionMergeError(
            "session merge failed before it could establish a safe result",
            stable_code="session_merge_failed",
        ) from exc


__all__ = [
    "SessionMergeError",
    "SessionMergeReport",
    "merge_recovery_sessions",
]
