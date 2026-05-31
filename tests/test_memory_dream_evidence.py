from __future__ import annotations

from pathlib import Path

from opensquilla.memory.dream.candidates import scan_dream_candidates
from opensquilla.memory.dream.evidence import (
    load_evidence_store,
    promotion_evidence_path,
    update_promotion_evidence,
)
from opensquilla.memory.dream.models import RawDreamCandidate
from opensquilla.memory.dream.quarantine import is_quarantined_path, is_quarantined_text


def _candidate(
    path: str = "memory/2026-05-22-note.md",
    text: str = "User prefers real benchmark runs.",
) -> RawDreamCandidate:
    return RawDreamCandidate(
        agent_id="main",
        source_path=path,
        source_kind="memory_file",
        source_mtime_ns=100,
        source_size=len(text),
        snippet=text,
        snippet_sha256="",
        claim_sha256="",
        source_day="2026-05-22",
        signal_kind="positive",
    )


def test_update_promotion_evidence_creates_store(tmp_path: Path) -> None:
    store = update_promotion_evidence(
        tmp_path, [_candidate()], now_iso="2026-05-22T00:00:00Z"
    )

    path = promotion_evidence_path(tmp_path)
    assert path.exists()
    assert store.version == 1
    assert len(store.entries) == 1
    entry = next(iter(store.entries.values()))
    assert entry.seen_count == 1
    assert entry.positive_signal_count == 1
    assert entry.status == "candidate"


def test_update_promotion_evidence_accumulates_seen_count(tmp_path: Path) -> None:
    candidate = _candidate()
    update_promotion_evidence(tmp_path, [candidate], now_iso="2026-05-22T00:00:00Z")
    store = update_promotion_evidence(
        tmp_path, [candidate], now_iso="2026-05-22T01:00:00Z"
    )

    entry = next(iter(store.entries.values()))
    assert entry.seen_count == 2
    assert entry.positive_signal_count == 2
    assert entry.first_seen_at == "2026-05-22T00:00:00Z"
    assert entry.last_seen_at == "2026-05-22T01:00:00Z"


def test_update_promotion_evidence_accumulates_same_claim_across_files(
    tmp_path: Path,
) -> None:
    text = "Correction: do not use rejected labels; use project-native naming instead."
    first = _candidate(
        path="memory/2026-05-21-naming.md",
        text=text,
    )
    first.signal_kind = "correction"
    first.source_day = "2026-05-21"
    second = _candidate(
        path="memory/2026-05-22-naming.md",
        text=text,
    )
    second.signal_kind = "correction"

    update_promotion_evidence(tmp_path, [first], now_iso="2026-05-21T00:00:00Z")
    store = update_promotion_evidence(
        tmp_path,
        [second],
        now_iso="2026-05-22T00:00:00Z",
    )

    assert len(store.entries) == 1
    entry = next(iter(store.entries.values()))
    assert entry.seen_count == 2
    assert entry.correction_signal_count == 2
    assert entry.source_path == "memory/2026-05-22-naming.md"
    assert entry.source_days == ["2026-05-21", "2026-05-22"]


def test_load_evidence_store_normalizes_corrupt_or_missing_store(tmp_path: Path) -> None:
    assert load_evidence_store(tmp_path).entries == {}
    promotion_evidence_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    promotion_evidence_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert load_evidence_store(tmp_path).entries == {}


def test_quarantine_rejects_dream_state_and_logs() -> None:
    assert is_quarantined_path("memory/.dream_state/promotion_evidence.json")
    assert is_quarantined_path("memory/.dream_receipts/main-1.json")
    assert is_quarantined_path("logs/dream-main-2026-05-22.jsonl")
    assert not is_quarantined_path("memory/2026-05-22-note.md")


def test_quarantine_rejects_generated_markers() -> None:
    assert is_quarantined_text("<!-- opensquilla-dream-promotion:abc -->")
    assert is_quarantined_text("Dream receipt generated this")
    assert not is_quarantined_text("User prefers concise implementation notes.")


def test_scan_dream_candidates_extracts_top_level_memory_files(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    note = memory_dir / "2026-05-22-note.md"
    note.write_text(
        "User prefers provider-backed benchmarks over toy simulations.\n",
        encoding="utf-8",
    )
    (memory_dir / ".hidden.md").write_text("hidden", encoding="utf-8")
    (memory_dir / "MEMORY.md").write_text("nested", encoding="utf-8")

    candidates = scan_dream_candidates(tmp_path, cursor=0.0, max_batch_size=10, agent_id="main")

    assert len(candidates) == 1
    assert candidates[0].source_path == "memory/2026-05-22-note.md"
    assert candidates[0].signal_kind == "positive"
    assert candidates[0].snippet_sha256
    assert candidates[0].claim_sha256
