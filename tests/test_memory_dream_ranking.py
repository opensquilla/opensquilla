from __future__ import annotations

from opensquilla.gateway.config import GatewayConfig
from opensquilla.memory.dream.models import PromotionEvidenceEntry, PromotionEvidenceStore
from opensquilla.memory.dream.ranking import rank_promotion_candidates


def _entry(
    candidate_id: str,
    *,
    positive: int = 0,
    correction: int = 0,
    failure: int = 0,
    manual: int = 0,
    seen: int = 1,
) -> PromotionEvidenceEntry:
    return PromotionEvidenceEntry(
        candidate_id=candidate_id,
        agent_id="main",
        source_path=f"memory/{candidate_id}.md",
        source_kind="memory_file",
        source_mtime_ns=1,
        source_size=10,
        snippet=f"{candidate_id} snippet",
        snippet_sha256=f"{candidate_id}-snippet",
        claim_sha256=f"{candidate_id}-claim",
        first_seen_at="2026-05-22T00:00:00Z",
        last_seen_at="2026-05-22T00:00:00Z",
        seen_count=seen,
        positive_signal_count=positive,
        correction_signal_count=correction,
        failure_signal_count=failure,
        manual_signal_count=manual,
        source_days=["2026-05-22"],
    )


def test_positive_candidate_ranks() -> None:
    store = PromotionEvidenceStore(
        version=1, updated_at="now", entries={"a": _entry("a", positive=1)}
    )

    ranked = rank_promotion_candidates(
        store, min_score=0.0, negative_recurrence_threshold=2
    )

    assert [item.candidate_id for item in ranked] == ["a"]
    assert "positive_or_manual_signal" in ranked[0].reasons


def test_default_gateway_threshold_ranks_single_positive_candidate() -> None:
    store = PromotionEvidenceStore(
        version=1, updated_at="now", entries={"a": _entry("a", positive=1)}
    )

    ranked = rank_promotion_candidates(
        store,
        min_score=GatewayConfig().memory.dream.evidence_min_score,
        negative_recurrence_threshold=2,
    )

    assert [item.candidate_id for item in ranked] == ["a"]


def test_pure_negative_candidate_needs_recurrence() -> None:
    store = PromotionEvidenceStore(
        version=1, updated_at="now", entries={"a": _entry("a", correction=1)}
    )

    ranked = rank_promotion_candidates(
        store, min_score=0.0, negative_recurrence_threshold=2
    )

    assert ranked == []


def test_repeated_negative_candidate_can_rank() -> None:
    store = PromotionEvidenceStore(
        version=1, updated_at="now", entries={"a": _entry("a", correction=2, seen=2)}
    )

    ranked = rank_promotion_candidates(
        store, min_score=0.0, negative_recurrence_threshold=2
    )

    assert [item.candidate_id for item in ranked] == ["a"]
    assert "negative_recurrence" in ranked[0].reasons


def test_default_gateway_threshold_ranks_repeated_negative_candidate() -> None:
    store = PromotionEvidenceStore(
        version=1,
        updated_at="now",
        entries={"a": _entry("a", correction=2, seen=2)},
    )

    ranked = rank_promotion_candidates(
        store,
        min_score=GatewayConfig().memory.dream.evidence_min_score,
        negative_recurrence_threshold=2,
    )

    assert [item.candidate_id for item in ranked] == ["a"]
