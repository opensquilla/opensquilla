"""Shared Dream data models."""

from __future__ import annotations

from dataclasses import dataclass, field

PROMOTION_EVIDENCE_STORE_VERSION = 2


@dataclass
class RawDreamCandidate:
    agent_id: str
    source_path: str
    source_kind: str
    source_mtime_ns: int
    source_size: int
    snippet: str
    snippet_sha256: str
    claim_sha256: str
    source_day: str | None = None
    signal_kind: str = "neutral"
    # Stable identity for one occurrence inside its source.  Dream may rescan an
    # append-only file after its mtime changes; this prevents old lines from
    # being counted again while still allowing two identical appended lines to
    # count as two independent observations.
    source_occurrence_id: str = ""


@dataclass
class PromotionEvidenceEntry:
    candidate_id: str
    agent_id: str
    source_path: str
    source_kind: str
    source_mtime_ns: int
    source_size: int
    snippet: str
    snippet_sha256: str
    claim_sha256: str
    first_seen_at: str
    last_seen_at: str
    seen_count: int = 0
    positive_signal_count: int = 0
    correction_signal_count: int = 0
    failure_signal_count: int = 0
    manual_signal_count: int = 0
    source_days: list[str] = field(default_factory=list)
    status: str = "candidate"
    promoted_at: str | None = None
    rejected_at: str | None = None
    last_skip_reason: str | None = None
    observed_occurrence_ids: list[str] = field(default_factory=list)
    # A v1 store knew only the aggregate seen_count.  During migration this
    # watermark is consumed as stable occurrence ids are rediscovered, so
    # replaying old evidence cannot increment the aggregate a second time.
    legacy_unmapped_occurrence_count: int = 0


@dataclass
class PromotionEvidenceStore:
    version: int = PROMOTION_EVIDENCE_STORE_VERSION
    updated_at: str = ""
    entries: dict[str, PromotionEvidenceEntry] = field(default_factory=dict)


@dataclass
class PromotionCandidate:
    candidate_id: str
    source_path: str
    snippet: str
    snippet_sha256: str
    claim_sha256: str
    score: float
    reasons: list[str]
    signal_counts: dict[str, int]


@dataclass
class PromotionPatchOperation:
    op: str
    candidate_ids: list[str] = field(default_factory=list)
    section: str = ""
    memory_id: str = ""
    text: str = ""
    replaces_memory_id: str | None = None
    replaces_memory_ids: list[str] = field(default_factory=list)
    expected_old_text_sha256: str | None = None
    reason: str | None = None


@dataclass
class PromotionPatch:
    operations: list[PromotionPatchOperation] = field(default_factory=list)


@dataclass
class ApplyPromotionResult:
    applied: int = 0
    skipped: int = 0
    changed: bool = False
    applied_operations: list[dict[str, object]] = field(default_factory=list)


@dataclass
class RehydrateResult:
    ok: bool
    reason: str | None = None
