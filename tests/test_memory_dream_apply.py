from __future__ import annotations

import hashlib
from pathlib import Path

from opensquilla.memory.dream.curated_apply import apply_promotion_patch
from opensquilla.memory.dream.models import (
    PromotionCandidate,
    PromotionPatch,
    PromotionPatchOperation,
)
from opensquilla.memory.dream.rehydrate import rehydrate_candidate


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _candidate(text: str = "User prefers concise implementation notes.") -> PromotionCandidate:
    return PromotionCandidate(
        candidate_id="c1",
        source_path="memory/note.md",
        snippet=text,
        snippet_sha256=_sha(text),
        claim_sha256=_sha(" ".join(text.lower().split())),
        score=0.9,
        reasons=["positive_or_manual_signal"],
        signal_counts={"positive": 1, "correction": 0, "failure": 0, "manual": 0},
    )


def test_rehydrate_candidate_succeeds_when_source_contains_snippet(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    text = "User prefers concise implementation notes."
    (memory_dir / "note.md").write_text(text, encoding="utf-8")

    result = rehydrate_candidate(tmp_path, _candidate(text))

    assert result.ok
    assert result.reason is None


def test_rehydrate_candidate_skips_missing_source(tmp_path: Path) -> None:
    result = rehydrate_candidate(tmp_path, _candidate())

    assert not result.ok
    assert result.reason == "source_missing"


def test_rehydrate_candidate_matches_normalized_multiline_source(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    raw = "User prefers\nconcise implementation notes."
    snippet = "User prefers concise implementation notes."
    (memory_dir / "note.md").write_text(raw, encoding="utf-8")

    result = rehydrate_candidate(tmp_path, _candidate(snippet))

    assert result.ok
    assert result.reason is None


def test_apply_promotion_patch_upserts_curated_section(tmp_path: Path) -> None:
    memory_md = tmp_path / "MEMORY.md"
    patch = PromotionPatch(
        operations=[
            PromotionPatchOperation(
                op="upsert",
                candidate_ids=["c1"],
                section="User Preferences",
                memory_id="mem_concise_notes",
                text="- User prefers concise implementation notes.",
            )
        ]
    )

    result = apply_promotion_patch(tmp_path, patch, dry_run=False)

    assert result.applied == 1
    assert "## User Preferences" in memory_md.read_text(encoding="utf-8")
    assert "User prefers concise implementation notes" in memory_md.read_text(encoding="utf-8")
    assert "Promoted From Dream Evidence" not in memory_md.read_text(encoding="utf-8")


def test_apply_promotion_patch_dry_run_does_not_write(tmp_path: Path) -> None:
    patch = PromotionPatch(
        operations=[
            PromotionPatchOperation(
                op="upsert",
                candidate_ids=["c1"],
                section="User Preferences",
                memory_id="mem_concise_notes",
                text="- User prefers concise implementation notes.",
            )
        ]
    )

    result = apply_promotion_patch(tmp_path, patch, dry_run=True)

    assert result.applied == 0
    assert not (tmp_path / "MEMORY.md").exists()
