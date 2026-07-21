from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from opensquilla.memory.dream import Dream
from opensquilla.memory.dream.evidence import load_evidence_store


class _Response:
    def __init__(self, content: str) -> None:
        self.content = content


class _PatchProvider:
    def __init__(self, text: str | None = None, *, delete_path=None) -> None:
        self.calls = 0
        self.delete_path = delete_path
        self.text = text or json.dumps(
            {
                "operations": [
                    {
                        "op": "upsert",
                        "candidate_ids": ["auto"],
                        "section": "User Preferences",
                        "memory_id": "mem_provider_benchmarks",
                        "text": "- User prefers provider-backed benchmarks over toy simulations.",
                    }
                ]
            }
        )

    async def complete(self, *, messages, max_tokens):
        self.calls += 1
        if self.delete_path is not None and self.delete_path.exists():
            self.delete_path.unlink()
        return _Response(self.text)


class _FailIfCalledProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *, messages, max_tokens):  # noqa: ARG002
        self.calls += 1
        raise AssertionError("provider should not be called")


def _dream(
    workspace,
    *,
    provider=None,
    preview=False,
    max_batch_size=10,
    curated_writes=True,
):
    config = SimpleNamespace(
        max_batch_size=max_batch_size,
        min_batch_size=1,
        input_slimming="off",
        preview_mode=preview,
        dry_run=preview,
        evidence_min_score=0.0,
        evidence_negative_recurrence_threshold=2,
        evidence_quarantine_enabled=True,
        evidence_curated_writes_enabled=curated_writes,
    )
    return Dream(
        workspace=workspace,
        provider=provider or _PatchProvider(),
        session_lock=None,
        config=config,
    )


@pytest.mark.asyncio
async def test_dream_records_evidence_and_writes_curated_memory(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "note.md").write_text(
        "User prefers provider-backed benchmarks over toy simulations.",
        encoding="utf-8",
    )

    result = await _dream(tmp_path).run()

    assert result.evidence_status == "ok"
    assert result.apply_status == "ok"
    assert "User Preferences" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert (memory_dir / ".dream_state" / "promotion_evidence.json").exists()
    assert (memory_dir / "note.md").exists()


@pytest.mark.asyncio
async def test_dream_processes_entire_equal_mtime_boundary(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    shared_mtime_ns = 1_800_000_000_000_000_000
    for index in range(22):
        path = memory_dir / f"note-{index}.md"
        path.write_text(f"Memory: durable note {index}.\n", encoding="utf-8")
        os.utime(path, ns=(shared_mtime_ns, shared_mtime_ns))
    dream = _dream(tmp_path, max_batch_size=20)

    result = await dream.run()

    assert result.apply_status == "ok"
    assert result.files_considered == 22
    assert result.files_processed == 22
    assert dream.pending_candidate_count() == 0
    store = load_evidence_store(tmp_path)
    assert len(store.entries) == 22
    assert {entry.status for entry in store.entries.values()} == {"promoted"}


@pytest.mark.asyncio
async def test_dream_terminally_acknowledges_curator_skip(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "temporary-label.md").write_text(
        "Memory: use a one-off temporary label.\n",
        encoding="utf-8",
    )
    provider = _PatchProvider(
        text=json.dumps(
            {
                "operations": [
                    {
                        "op": "skip",
                        "candidate_ids": ["auto"],
                        "reason": "not durable",
                    }
                ]
            }
        )
    )
    dream = _dream(tmp_path, provider=provider)

    result = await dream.run()

    assert result.apply_status == "ok"
    entry = next(iter(load_evidence_store(tmp_path).entries.values()))
    assert entry.status == "rejected"
    assert entry.rejected_at is not None
    assert entry.last_skip_reason == "curator_skip"
    assert dream.pending_candidate_count() == 0

    replay = await dream.run()

    assert replay.files_considered == 0
    assert replay.provider_calls == 0
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_dream_result_and_log_use_single_path_names(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "note.md").write_text(
        "User prefers provider-backed benchmarks over toy simulations.",
        encoding="utf-8",
    )

    result = await _dream(tmp_path).run()
    log_path = next((tmp_path / "logs").glob("dream-main-*.jsonl"))
    log_row = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])

    assert result.evidence_status == "ok"
    assert result.apply_status == "ok"
    assert result.provider_calls == 1
    assert not hasattr(result, "phase" + "1_status")
    assert not hasattr(result, "phase" + "2_status")
    assert not hasattr(result, "files_deleted")
    assert "evidence_status" in log_row
    assert "apply_status" in log_row
    assert "provider_calls" in log_row
    assert "files_deleted" not in log_row
    assert all("phase" not in key for key in log_row)


@pytest.mark.asyncio
async def test_dream_preview_mutates_nothing(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    note = memory_dir / "note.md"
    note.write_text("User prefers concise implementation notes.", encoding="utf-8")

    result = await _dream(tmp_path, preview=True).run()

    assert result.evidence_status == "ok"
    assert result.apply_status == "ok"
    assert note.exists()
    assert not (tmp_path / "MEMORY.md").exists()
    assert not (memory_dir / ".dream_state" / "promotion_evidence.json").exists()
    assert result.cursor_after == result.cursor_before


@pytest.mark.asyncio
async def test_dream_disabled_curated_writes_keeps_candidate_pending_without_provider_call(
    tmp_path,
):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "pending-note.md").write_text(
        "Memory: retain this durable operational note.\n",
        encoding="utf-8",
    )
    provider = _FailIfCalledProvider()
    dream = _dream(
        tmp_path,
        provider=provider,
        curated_writes=False,
    )

    result = await dream.run()

    assert result.apply_status == "skipped"
    assert result.provider_calls == 0
    assert provider.calls == 0
    assert result.cursor_after == result.cursor_before
    assert result.files_processed == 0
    assert not (tmp_path / "MEMORY.md").exists()
    entry = next(iter(load_evidence_store(tmp_path).entries.values()))
    assert entry.status == "candidate"
    assert entry.last_skip_reason == "curated_writes_disabled"
    assert dream.pending_candidate_count() == 1


@pytest.mark.asyncio
async def test_dream_externally_missing_candidate_after_evidence_does_not_raise(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    note = memory_dir / "note.md"
    note.write_text("User prefers concise implementation notes.", encoding="utf-8")
    provider = _PatchProvider(delete_path=note)

    result = await _dream(tmp_path, provider=provider).run()

    assert result.apply_status == "error"
    assert "changed during provider completion" in (result.error or "")
    assert not (tmp_path / "MEMORY.md").exists()
    assert "FileNotFoundError" not in (result.error or "")


@pytest.mark.asyncio
async def test_dream_writes_evidence_receipt(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "note.md").write_text(
        "User prefers provider-backed benchmarks over toy simulations.",
        encoding="utf-8",
    )

    result = await _dream(tmp_path).run()

    assert result.edit_receipt_path is not None
    receipt = json.loads((tmp_path / result.edit_receipt_path).read_text(encoding="utf-8"))
    assert receipt["schema_version"] == 1
    assert "version" not in receipt
    assert "ranked_candidates" in receipt
    assert "applied_promotions" in receipt


@pytest.mark.asyncio
async def test_dream_skips_provider_when_no_candidates_rank(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    note = memory_dir / "note.md"
    note.write_text("Do not use this one-off label.", encoding="utf-8")
    provider = _FailIfCalledProvider()

    result = await _dream(tmp_path, provider=provider).run()

    assert provider.calls == 0
    assert result.provider_calls == 0
    assert result.evidence_status == "ok"
    assert result.apply_status == "skipped"
    assert note.exists()
    assert not (tmp_path / "MEMORY.md").exists()


@pytest.mark.asyncio
async def test_dream_does_not_promote_stale_candidate_from_mixed_operation(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    stale_text = "Memory: stale source."
    live_text = "Memory: live source."
    stale = memory_dir / "stale.md"
    live = memory_dir / "live.md"
    stale.write_text(stale_text, encoding="utf-8")
    live.write_text(live_text, encoding="utf-8")
    provider = _PatchProvider(
        text=json.dumps(
            {
                "operations": [
                    {
                        "op": "upsert",
                        "candidate_ids": ["auto"],
                        "section": "User Preferences",
                        "memory_id": "mem_mixed",
                        "text": stale_text + "\n" + live_text,
                    }
                ]
            }
        ),
        delete_path=stale,
    )

    result = await _dream(tmp_path, provider=provider).run()
    store = load_evidence_store(tmp_path)
    stale_entries = [
        entry for entry in store.entries.values() if entry.source_path.endswith(stale.name)
    ]
    live_entries = [
        entry for entry in store.entries.values() if entry.source_path.endswith(live.name)
    ]

    assert result.apply_status == "error"
    assert "changed during provider completion" in (result.error or "")
    assert not (tmp_path / "MEMORY.md").exists()
    assert stale_entries and stale_entries[0].status == "candidate"
    assert stale_entries[0].last_skip_reason == "source_missing"
    assert live_entries and live_entries[0].status == "candidate"

    recovery_provider = _PatchProvider(
        text=json.dumps(
            {
                "operations": [
                    {
                        "op": "upsert",
                        "candidate_ids": ["auto"],
                        "section": "User Preferences",
                        "memory_id": "mem_live",
                        "text": live_text,
                    }
                ]
            }
        )
    )
    recovery = await _dream(tmp_path, provider=recovery_provider).run()

    assert recovery.apply_status == "ok"
    memory_text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert live_text in memory_text
    assert stale_text not in memory_text
    recovered_store = load_evidence_store(tmp_path)
    recovered_live = next(
        entry
        for entry in recovered_store.entries.values()
        if entry.source_path.endswith(live.name)
    )
    assert recovered_live.status == "promoted"


@pytest.mark.asyncio
async def test_dream_marks_noop_curated_write_as_represented_not_promoted(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    existing = "- User prefers provider-backed benchmarks over toy simulations."
    (tmp_path / "MEMORY.md").write_text(
        f"# Long-Term Memory\n\n## User Preferences\n\n{existing}\n",
        encoding="utf-8",
    )
    (memory_dir / "note.md").write_text(
        "User prefers provider-backed benchmarks over toy simulations.",
        encoding="utf-8",
    )

    result = await _dream(tmp_path).run()
    store = load_evidence_store(tmp_path)
    entry = next(iter(store.entries.values()))
    receipt = json.loads((tmp_path / result.edit_receipt_path).read_text(encoding="utf-8"))

    assert result.apply_status == "ok"
    assert entry.status == "represented"
    assert entry.promoted_at is None
    assert entry.last_skip_reason == "no_curated_change"
    assert receipt["applied_promotions"][0]["changed"] is False
