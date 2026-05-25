"""Contracts for the default high-value meta-skill workflows."""

from __future__ import annotations

from pathlib import Path

from opensquilla.skills.loader import SkillLoader

BUNDLED = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "opensquilla"
    / "skills"
    / "bundled"
)


def _loader(tmp_path: Path) -> SkillLoader:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")
    loader.invalidate_cache()
    return loader


def _step_ids(loader: SkillLoader, name: str) -> set[str]:
    spec = loader.get_by_name(name)
    assert spec is not None, name
    assert spec.composition_raw is not None, name
    return {
        str(step["id"])
        for step in spec.composition_raw.get("steps", [])
        if isinstance(step, dict) and "id" in step
    }


def test_report_meta_skill_has_preferences_sources_outline_and_quality_gate(
    tmp_path: Path,
) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-web-research-to-report")

    assert {
        "preferences",
        "source_quality",
        "outline",
        "report_draft",
        "quality_gate",
        "export",
    } <= ids


def test_deck_meta_skill_has_storyline_notes_and_slide_quality_gate(
    tmp_path: Path,
) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-research-to-deck")

    assert {
        "deck_preferences",
        "storyline",
        "slide_outline",
        "speaker_notes",
        "slide_quality_gate",
        "deck",
    } <= ids


def test_paper_meta_skill_has_pre_compile_quality_gates(tmp_path: Path) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-paper-write")

    assert {
        "paper_length_gate",
        "citation_integrity_gate",
        "latex_sanitizer",
        "compile_latex",
    } <= ids


def test_pdf_intelligence_preserves_traceable_multi_document_structure(
    tmp_path: Path,
) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-pdf-intelligence")

    assert {
        "intake",
        "extract",
        "per_document_digest",
        "cross_document_synthesis",
        "traceable_index",
        "memorize",
    } <= ids


def test_stack_trace_investigator_supports_language_routing_and_degraded_output(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    ids = _step_ids(loader, "meta-stack-trace-investigator")
    spec = loader.get_by_name("meta-stack-trace-investigator")
    assert spec is not None
    raw = str(spec.composition_raw)

    assert {"classify_language", "repro_suggestion", "degraded_summary"} <= ids
    assert "JavaScript" in raw
    assert "TypeScript" in raw
    assert "Go" in raw
    assert "Rust" in raw


def test_travel_planner_collects_preferences_constraints_and_variants(
    tmp_path: Path,
) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-travel-planner")

    assert {
        "trip_preferences",
        "weather",
        "poi",
        "constraints",
        "itinerary",
        "variants",
        "export",
    } <= ids


def test_meta_skill_creator_has_intent_collision_risk_and_preview_gates(
    tmp_path: Path,
) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-skill-creator")

    assert {
        "clarify_intent",
        "collision_check",
        "risk_classify",
        "preview",
        "persist",
    } <= ids
