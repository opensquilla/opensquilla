"""Contracts for the default high-value meta-skill workflows."""

from __future__ import annotations

from pathlib import Path

from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.parser import parse_meta_plan

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


def _plan(loader: SkillLoader, name: str):
    spec = loader.get_by_name(name)
    assert spec is not None, name
    plan = parse_meta_plan(spec)
    assert plan is not None, name
    return plan


def _steps_by_id(loader: SkillLoader, name: str):
    plan = _plan(loader, name)
    return {step.id: step for step in plan.steps}, plan


def _orchestrated_skill_names(loader: SkillLoader, name: str) -> set[str]:
    steps, _ = _steps_by_id(loader, name)
    return {
        step.skill
        for step in steps.values()
        if step.kind in {"agent", "skill_exec"} and step.skill
    }


def _assert_composes_at_least_two_skills(loader: SkillLoader, name: str) -> None:
    skill_names = _orchestrated_skill_names(loader, name)
    assert len(skill_names) >= 2, f"{name} composes too few skills: {skill_names}"


def test_high_value_meta_skill_descriptions_signal_orchestration_priority(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    names = {
        "meta-web-research-to-report",
        "meta-paper-write",
        "meta-pdf-intelligence",
        "meta-stack-trace-investigator",
        "meta-travel-planner",
        "meta-skill-creator",
        "meta-migration-assistant",
    }

    for name in names:
        spec = loader.get_by_name(name)
        assert spec is not None, name
        description = spec.description.lower()
        assert "multi-skill orchestration" in description, name
        assert "instead of answering directly" in description, name


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


def test_report_meta_skill_uses_fast_final_report_path(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-web-research-to-report")
    steps, plan = _steps_by_id(loader, "meta-web-research-to-report")

    assert plan.final_text_mode == "step:final_report"
    assert steps["report_mode"].kind == "llm_classify"
    assert set(steps["report_mode"].output_choices) == {
        "QUICK_DECISION_MEMO",
        "DEEP_REPORT",
        "EXPORT_DOCX",
    }
    assert steps["research"].when == "outputs.report_mode in ('DEEP_REPORT', 'EXPORT_DOCX')"
    assert steps["export"].when == "outputs.report_mode == 'EXPORT_DOCX'"
    for step_id in (
        "preferences",
        "source_quality",
        "outline",
        "source_to_claim",
        "final_report",
    ):
        assert steps[step_id].kind == "llm_chat"
    assert steps["search"].skill == "multi-search-engine"
    assert steps["research"].skill == "deep-research"
    assert steps["export"].skill == "docx"


def test_paper_meta_skill_has_pre_compile_quality_gates(tmp_path: Path) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-paper-write")

    assert {
        "final_manuscript_package",
        "paper_length_gate",
        "citation_integrity_gate",
        "latex_sanitizer",
        "compile_latex",
    } <= ids


def test_paper_meta_skill_uses_compact_default_manuscript_path(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-paper-write")
    steps, plan = _steps_by_id(loader, "meta-paper-write")

    assert plan.final_text_mode == "step:final_manuscript_package"
    assert steps["paper_mode"].kind == "llm_classify"
    assert set(steps["paper_mode"].output_choices) == {
        "FULL_MANUSCRIPT",
        "COMPACT_SKELETON",
        "REPAIR_EXISTING",
        "COMPILE_ONLY",
    }
    assert steps["experiment"].when == "outputs.paper_mode == 'FULL_MANUSCRIPT'"
    assert steps["plot"].when == "outputs.paper_mode == 'FULL_MANUSCRIPT'"
    assert steps["compile_latex"].when == "outputs.paper_mode == 'COMPILE_ONLY'"
    for step_id in (
        "paper_preferences",
        "source_pack",
        "outline",
        "citation_plan",
        "final_manuscript_package",
        "paper_length_gate",
        "citation_integrity_gate",
        "latex_sanitizer",
        "compile_latex",
    ):
        assert steps[step_id].kind == "llm_chat"
    for step_id in ("search_papers", "experiment", "refbib", "plot"):
        assert steps[step_id].kind == "skill_exec"
    assert steps["compile_latex"].depends_on == ("latex_sanitizer",)


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


def test_pdf_intelligence_has_inline_fallback_and_final_synthesis(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-pdf-intelligence")
    steps, plan = _steps_by_id(loader, "meta-pdf-intelligence")

    assert plan.final_text_mode == "step:cross_document_synthesis"
    assert steps["extract"].on_failure == "inline_excerpt_extract"
    assert steps["inline_excerpt_extract"].kind == "llm_chat"
    for step_id in ("intake", "cross_document_synthesis", "traceable_index"):
        assert steps[step_id].kind == "llm_chat"
    assert steps["extract"].skill == "pdf-toolkit"
    assert steps["per_document_digest"].skill == "summarize"


def test_stack_trace_investigator_supports_language_routing_and_degraded_output(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    ids = _step_ids(loader, "meta-stack-trace-investigator")
    spec = loader.get_by_name("meta-stack-trace-investigator")
    assert spec is not None
    raw = str(spec.composition_raw)

    assert {"classify_language", "repro_suggestion", "degraded_summary"} <= ids
    assert "javascript" in raw
    assert "typescript" in raw
    assert "go" in raw
    assert "rust" in raw


def test_stack_trace_final_report_requires_patch_target_checklist(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-stack-trace-investigator")
    spec = loader.get_by_name("meta-stack-trace-investigator")
    assert spec is not None
    raw = str(spec.composition_raw)

    assert "## Patch Target Checklist" in raw
    assert "Assumptions / Constraints" in raw
    assert "git-diff" in _orchestrated_skill_names(loader, "meta-stack-trace-investigator")
    assert "history-explorer" in _orchestrated_skill_names(
        loader, "meta-stack-trace-investigator",
    )


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
        "final_plan",
    } <= ids
    assert "export" not in ids


def test_travel_planner_uses_fast_final_itinerary_path(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-travel-planner")
    steps, plan = _steps_by_id(loader, "meta-travel-planner")

    assert plan.final_text_mode == "step:final_plan"
    for step_id in (
        "trip_preferences",
        "constraints",
        "itinerary",
        "final_plan",
    ):
        assert steps[step_id].kind == "llm_chat"
    assert steps["weather"].skill == "weather"
    assert steps["weather"].kind == "skill_exec"
    assert steps["poi"].skill == "multi-search-engine"
    assert steps["poi"].kind == "skill_exec"
    assert steps["final_plan"].depends_on == ("itinerary", "constraints", "weather", "poi")
    assert "Primary 3-day itinerary" in str(steps["final_plan"].with_args)
    assert "Variants" in str(steps["final_plan"].with_args)
    assert "Evidence and source notes" in str(steps["final_plan"].with_args)
    assert "Next steps" in str(steps["final_plan"].with_args)
    assert "explicitly asks for a file" in str(steps["final_plan"].with_args)
    assert "ARTIFACT_READY" not in str(plan.steps)


def test_meta_skill_creator_has_intent_collision_risk_and_preview_gates(
    tmp_path: Path,
) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-skill-creator")

    assert {
        "clarify_intent",
        "creator_mode",
        "collision_check",
        "risk_classify",
        "single_model_baseline",
        "acceptance_compare",
        "preview",
        "persist",
    } <= ids


def test_meta_skill_creator_supports_preview_only_branch(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-skill-creator")
    steps, plan = _steps_by_id(loader, "meta-skill-creator")

    assert plan.final_text_mode == "step:preview"
    assert steps["creator_mode"].kind == "llm_classify"
    assert set(steps["creator_mode"].output_choices) == {
        "PREVIEW_ONLY",
        "PERSISTED_PROPOSAL",
        "FULL_GATED",
    }
    assert steps["smoke"].when == "outputs.creator_mode != 'PREVIEW_ONLY'"
    assert steps["persist"].when == "outputs.creator_mode != 'PREVIEW_ONLY'"


def test_meta_skill_creator_acceptance_compares_against_highest_tier_baseline(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    steps, _plan = _steps_by_id(loader, "meta-skill-creator")

    baseline = steps["single_model_baseline"]
    compare = steps["acceptance_compare"]

    assert baseline.kind == "llm_chat"
    assert baseline.depends_on == ("creator_mode",)
    assert baseline.when == "outputs.creator_mode == 'FULL_GATED'"
    assert "highest-tier" in str(baseline.with_args).lower()
    assert "same task" in str(baseline.with_args).lower()
    assert "system prompt" in str(baseline.with_args).lower()
    assert "inputs.system_prompt" in str(baseline.with_args)
    assert "outputs." not in str(baseline.with_args)

    assert compare.kind == "llm_chat"
    assert set(compare.depends_on) == {"assemble", "single_model_baseline"}
    assert compare.when == "outputs.creator_mode == 'FULL_GATED'"
    assert "orchestrated candidate" in str(compare.with_args).lower()
    assert "single-model baseline" in str(compare.with_args).lower()
    assert "winner" in str(compare.with_args).lower()
    assert "acceptance_compare" in str(steps["preview"].depends_on)
    assert "Baseline comparison" in str(steps["preview"].with_args)


def test_migration_assistant_routes_guides_and_optional_repo_context(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-migration-assistant")
    steps, plan = _steps_by_id(loader, "meta-migration-assistant")

    assert plan.final_text_mode == "step:write_plan"
    assert steps["fetch_guide"].skill == "deep-research"
    assert [case.to for case in steps["fetch_guide"].route] == [
        "github",
        "multi-search-engine",
    ]
    assert steps["repo_context"].skill == "git-diff"
    assert "current repo" in steps["repo_context"].when
    assert set(steps["write_plan"].depends_on) == {
        "classify",
        "fetch_guide",
        "repo_context",
    }
