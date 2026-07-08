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


def _budgeted(tmp_path: Path, budget: int | None) -> AttachmentWorkspaceMaterializer:
    return AttachmentWorkspaceMaterializer(
        media_root=tmp_path / "media",
        workspace_dir=tmp_path / "workspace",
        materializable_mimes=None,
        disk_budget_bytes=budget,
    )


def test_budget_rejects_materialization_that_would_exceed_it(tmp_path: Path) -> None:
    materializer = _budgeted(tmp_path, budget=10)

    result = materializer.materialize_bytes(
        b"x" * 11,
        name="big.bin",
        mime="application/octet-stream",
        session_id="session-a",
    )

    assert result.available is False
    assert result.error is not None
    assert "workspace attachment budget exceeded" in result.error
    # The marker text names the remedy for the operator/model to see.
    assert "workspace_attachment_disk_budget_bytes" in result.error
    files = list((tmp_path / "workspace" / ".opensquilla" / "attachments").rglob("*-big.bin"))
    assert files == []


def test_budget_counts_existing_workspace_files(tmp_path: Path) -> None:
    materializer = _budgeted(tmp_path, budget=16)
    first = materializer.materialize_bytes(
        b"a" * 10, name="a.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert first.available is True

    # A fresh instance re-scans the tree, so the 10 existing bytes count.
    second = _budgeted(tmp_path, budget=16).materialize_bytes(
        b"b" * 10, name="b.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert second.available is False
    assert "workspace attachment budget exceeded" in (second.error or "")

    # A smaller payload that fits the remaining headroom is admitted.
    third = _budgeted(tmp_path, budget=16).materialize_bytes(
        b"c" * 6, name="c.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert third.available is True


def test_budget_reuse_of_existing_file_is_always_free(tmp_path: Path) -> None:
    payload = b"d" * 12
    first = _budgeted(tmp_path, budget=12).materialize_bytes(
        payload, name="d.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert first.available is True

    # At-budget workspace: re-materializing the SAME content must stay
    # available (reuse short-circuits before the budget check) so replay of
    # already-materialized history never degrades when the budget fills.
    again = _budgeted(tmp_path, budget=12).materialize_bytes(
        payload, name="d.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert again.available is True
    assert again.rel_path == first.rel_path


def test_budget_none_is_unbounded(tmp_path: Path) -> None:
    result = _budgeted(tmp_path, budget=None).materialize_bytes(
        b"e" * 4096, name="e.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert result.available is True


def test_budget_shared_across_one_instance_batch(tmp_path: Path) -> None:
    # One materializer instance (one turn) tracks its own writes against the
    # budget without re-walking the tree.
    materializer = _budgeted(tmp_path, budget=16)
    first = materializer.materialize_bytes(
        b"f" * 10, name="f.bin", mime="application/octet-stream", session_id="session-a"
    )
    second = materializer.materialize_bytes(
        b"g" * 10, name="g.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert first.available is True
    assert second.available is False


def test_workspace_attachment_budget_from_config_guards() -> None:
    from types import SimpleNamespace

    from opensquilla.attachment_workspace import workspace_attachment_budget_from_config

    good = SimpleNamespace(
        attachments=SimpleNamespace(workspace_attachment_disk_budget_bytes=123)
    )
    assert workspace_attachment_budget_from_config(good) == 123
    assert workspace_attachment_budget_from_config(None) is None
    assert (
        workspace_attachment_budget_from_config(
            SimpleNamespace(
                attachments=SimpleNamespace(workspace_attachment_disk_budget_bytes=0)
            )
        )
        is None
    )
    assert (
        workspace_attachment_budget_from_config(
            SimpleNamespace(
                attachments=SimpleNamespace(workspace_attachment_disk_budget_bytes="2")
            )
        )
        is None
    )


def test_budget_overwrite_of_mismatched_file_frees_replaced_bytes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    payload = b"h" * 10
    sha = hashlib.sha256(payload).hexdigest()
    target_dir = workspace / ".opensquilla" / "attachments" / "session-a"
    target_dir.mkdir(parents=True)
    stale = target_dir / f"{sha[:12]}-h.bin"
    stale.write_bytes(b"stale-different-content-12345")  # 29 bytes at the target path

    materializer = _budgeted(tmp_path, budget=16)
    # 29 stale bytes alone exceed the budget, but the overwrite frees them:
    # (29 - 29) + 10 <= 16 must be admitted.
    result = materializer.materialize_bytes(
        payload, name="h.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert result.available is True
    assert stale.read_bytes() == payload

    # Cached usage after the overwrite must be 10 (not 29 or 39): a 6-byte
    # payload fits (10 + 6 <= 16), one more byte does not.
    ok = materializer.materialize_bytes(
        b"i" * 6, name="i.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert ok.available is True
    over = materializer.materialize_bytes(
        b"j", name="j.bin", mime="application/octet-stream", session_id="session-a"
    )
    assert over.available is False
