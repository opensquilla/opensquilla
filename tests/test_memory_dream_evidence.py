from __future__ import annotations

import json
import os
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
    assert store.version == 2
    assert len(store.entries) == 1
    entry = next(iter(store.entries.values()))
    assert entry.seen_count == 1
    assert entry.positive_signal_count == 1
    assert entry.status == "candidate"


def test_update_promotion_evidence_does_not_recount_same_source_occurrence(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    update_promotion_evidence(tmp_path, [candidate], now_iso="2026-05-22T00:00:00Z")
    store = update_promotion_evidence(
        tmp_path, [candidate], now_iso="2026-05-22T01:00:00Z"
    )

    entry = next(iter(store.entries.values()))
    assert entry.seen_count == 1
    assert entry.positive_signal_count == 1
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


def test_scan_splits_routing_preference_log_per_line(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "routing-preferences.md").write_text(
        "- prefers routing to `model:x-ai/grok-4.5`\n"
        "- do not route to `model:openai/gpt-6`\n",
        encoding="utf-8",
    )

    candidates = scan_dream_candidates(tmp_path, cursor=0.0, max_batch_size=10, agent_id="main")

    # Each thumb is its own candidate with its own signal, not one collapsed blob.
    assert len(candidates) == 2
    by_signal = {candidate.signal_kind for candidate in candidates}
    assert by_signal == {"positive", "correction"}
    # Distinct claims → distinct dedup keys, so they accrue evidence independently.
    assert len({candidate.claim_sha256 for candidate in candidates}) == 2


def test_rescanning_appended_preference_log_counts_only_new_occurrences(
    tmp_path: Path,
) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    note = memory_dir / "routing-preferences.md"
    avoided = "- do not route to `model:openai/gpt-6`"
    preferred = "- prefers routing to `model:x-ai/grok-4.5`"
    note.write_text(avoided + "\n", encoding="utf-8")

    first = scan_dream_candidates(
        tmp_path, cursor=0.0, max_batch_size=10, agent_id="main"
    )
    update_promotion_evidence(
        tmp_path,
        first,
        now_iso="2026-05-22T00:00:00Z",
    )

    # A later append makes the whole file eligible again.  The old avoidance
    # line must not acquire fake recurrence merely because another model was
    # rated; only the newly appended occurrence is new evidence.
    with note.open("a", encoding="utf-8") as handle:
        handle.write(preferred + "\n")
    second = scan_dream_candidates(
        tmp_path, cursor=0.0, max_batch_size=10, agent_id="main"
    )
    store = update_promotion_evidence(
        tmp_path,
        second,
        now_iso="2026-05-22T01:00:00Z",
    )
    by_snippet = {entry.snippet: entry for entry in store.entries.values()}
    assert by_snippet[avoided].seen_count == 1
    assert by_snippet[avoided].correction_signal_count == 1
    assert by_snippet[preferred].seen_count == 1
    assert by_snippet[preferred].positive_signal_count == 1

    # An actually repeated identical thumb is a distinct occurrence and counts
    # once, while the two historical lines remain deduplicated.
    with note.open("a", encoding="utf-8") as handle:
        handle.write(avoided + "\n")
    third = scan_dream_candidates(
        tmp_path, cursor=0.0, max_batch_size=10, agent_id="main"
    )
    store = update_promotion_evidence(
        tmp_path,
        third,
        now_iso="2026-05-22T02:00:00Z",
    )
    by_snippet = {entry.snippet: entry for entry in store.entries.values()}
    assert by_snippet[avoided].seen_count == 2
    assert by_snippet[avoided].correction_signal_count == 2
    assert by_snippet[preferred].seen_count == 1
    assert by_snippet[preferred].positive_signal_count == 1


def test_v1_store_migration_maps_legacy_occurrences_without_recounting(
    tmp_path: Path,
) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    note = memory_dir / "routing-preferences.md"
    line = "- prefers routing to `model:x-ai/grok-4.5`"
    note.write_text(line + "\n" + line + "\n", encoding="utf-8")
    candidates = scan_dream_candidates(
        tmp_path, cursor=0.0, max_batch_size=10, agent_id="main"
    )
    initial = update_promotion_evidence(
        tmp_path,
        candidates,
        now_iso="2026-05-22T00:00:00Z",
    )
    initial_entry = next(iter(initial.entries.values()))
    assert initial_entry.seen_count == 2

    # Simulate the released v1 shape: aggregate counts, but no occurrence ids.
    path = promotion_evidence_path(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = 1
    for raw_entry in payload["entries"].values():
        raw_entry.pop("observed_occurrence_ids", None)
        raw_entry.pop("legacy_unmapped_occurrence_count", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    migrated = update_promotion_evidence(
        tmp_path,
        candidates,
        now_iso="2026-05-22T01:00:00Z",
    )
    migrated_entry = next(iter(migrated.entries.values()))
    assert migrated.version == 2
    assert migrated_entry.seen_count == 2
    assert migrated_entry.positive_signal_count == 2
    assert migrated_entry.legacy_unmapped_occurrence_count == 0
    assert len(migrated_entry.observed_occurrence_ids) == 2
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2

    # A genuinely new third occurrence increments after the v1 watermark has
    # been fully mapped.
    with note.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    replay = scan_dream_candidates(
        tmp_path, cursor=0.0, max_batch_size=10, agent_id="main"
    )
    updated = update_promotion_evidence(
        tmp_path,
        replay,
        now_iso="2026-05-22T02:00:00Z",
    )
    updated_entry = next(iter(updated.entries.values()))
    assert updated_entry.seen_count == 3
    assert updated_entry.positive_signal_count == 3


def test_scan_does_not_split_equal_mtime_boundary(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    shared_mtime_ns = 1_800_000_000_000_000_000
    for index in range(22):
        path = memory_dir / f"2027-01-15-note-{index}.md"
        path.write_text(
            f"Memory: durable note {index}\n",
            encoding="utf-8",
        )
        os.utime(path, ns=(shared_mtime_ns, shared_mtime_ns))

    first = scan_dream_candidates(
        tmp_path,
        cursor=0.0,
        max_batch_size=20,
        agent_id="main",
    )
    cursor = max(candidate.source_mtime_ns for candidate in first) / 1_000_000_000
    second = scan_dream_candidates(
        tmp_path,
        cursor=cursor,
        max_batch_size=20,
        agent_id="main",
    )

    # The mtime cursor cannot represent a position inside a tie. The scanner
    # therefore expands the boundary batch instead of silently starving two
    # files after advancing the cursor.
    assert len(first) == 22
    assert second == []


def test_scan_keeps_narrative_note_whole(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    # A multi-line prose note has no routing marker: it stays one narrative candidate.
    (memory_dir / "2026-05-22-note.md").write_text(
        "User prefers real benchmark runs.\n"
        "They do not want toy simulations in the report.\n",
        encoding="utf-8",
    )

    candidates = scan_dream_candidates(tmp_path, cursor=0.0, max_batch_size=10, agent_id="main")

    assert len(candidates) == 1
