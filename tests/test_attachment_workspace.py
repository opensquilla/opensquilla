from __future__ import annotations

import hashlib
from pathlib import Path

from opensquilla.attachment_refs import make_attachment_ref, write_transcript_material
from opensquilla.attachment_workspace import (
    AttachmentWorkspaceMaterializer,
    is_materializable_attachment_mime,
)

_MATERIALIZABLE_MIMES = frozenset({"application/pdf", "text/plain"})


def test_unsupported_mime_is_not_materialized(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    workspace = tmp_path / "workspace"
    materializer = AttachmentWorkspaceMaterializer(
        media_root=media_root,
        workspace_dir=workspace,
        materializable_mimes=_MATERIALIZABLE_MIMES,
    )

    result = materializer.materialize_bytes(
        b"not an image",
        name="photo.png",
        mime="image/png",
        session_id="session-a",
    )

    assert result.available is False
    assert result.error == "attachment type is not materializable"
    assert not (workspace / ".opensquilla").exists()
    assert not is_materializable_attachment_mime("image/png", _MATERIALIZABLE_MIMES)


def test_materializes_transcript_ref_inside_workspace(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    workspace = tmp_path / "workspace"
    payload = b"%PDF-1.4\nminimal\n%%EOF\n"
    sha, _path, _wrote = write_transcript_material(
        media_root=media_root,
        session_id="session-a",
        payload=payload,
    )
    ref = make_attachment_ref(
        sha256=sha,
        name="../../report.pdf",
        mime="application/pdf",
        size=len(payload),
        session_id="session-a",
        source="transcript",
    )

    result = AttachmentWorkspaceMaterializer(
        media_root=media_root,
        workspace_dir=workspace,
        materializable_mimes=_MATERIALIZABLE_MIMES,
    ).materialize(ref)

    assert result.available is True
    assert result.rel_path is not None
    assert result.rel_path.startswith(".opensquilla/attachments/session-a/")
    assert ".." not in result.rel_path
    materialized = (workspace / result.rel_path).resolve()
    materialized.relative_to(workspace.resolve())
    assert materialized.read_bytes() == payload
    assert materialized.name == f"{sha[:12]}-report.pdf"


def test_existing_materialized_file_is_reused_when_hash_matches(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    payload = b"hello,world\n"
    sha = hashlib.sha256(payload).hexdigest()
    rel_dir = workspace / ".opensquilla" / "attachments" / "session-a"
    rel_dir.mkdir(parents=True)
    existing = rel_dir / f"{sha[:12]}-notes.txt"
    existing.write_bytes(payload)
    before_mtime_ns = existing.stat().st_mtime_ns

    result = AttachmentWorkspaceMaterializer(
        media_root=tmp_path / "media",
        workspace_dir=workspace,
        materializable_mimes=_MATERIALIZABLE_MIMES,
    ).materialize_bytes(
        payload,
        name="notes.txt",
        mime="text/plain",
        session_id="session-a",
    )

    assert result.available is True
    assert existing.stat().st_mtime_ns == before_mtime_ns
    assert existing.read_bytes() == payload
