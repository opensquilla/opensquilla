"""Contracts for retained and experimental high-value meta-skill workflows."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from opensquilla.engine.steps.meta_resolution import meta_resolution
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.parser import parse_meta_plan

BUNDLED = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "opensquilla"
    / "skills"
    / "bundled"
)
EXP = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "exp"


def _loader(tmp_path: Path) -> SkillLoader:
    loader = SkillLoader(
        bundled_dir=BUNDLED,
        extra_dirs=[EXP],
        snapshot_path=tmp_path / "snapshot.json",
    )
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


def _assert_user_input_step(
    steps: dict,
    step_id: str,
    *,
    when_contains: str,
    required_fields: set[str],
) -> None:
    step = steps[step_id]
    assert step.kind == "user_input"
    assert when_contains in step.when
    assert step.clarify_config is not None
    assert step.clarify_config.nl_extract is True
    assert required_fields <= {field.name for field in step.clarify_config.fields}


def test_high_value_meta_skill_descriptions_signal_orchestration_priority(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    names = {
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


def test_paper_meta_skill_has_pre_compile_quality_gates(tmp_path: Path) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-paper-write")

    assert {
        "final_manuscript_package",
        "persist_sections",
        "assemble_manuscript_tex",
        "citation_map",
        "citation_integrity_gate",
        "latex_sanitizer",
        "compile_latex",
    } <= ids


def test_paper_meta_skill_uses_compact_default_with_clarification(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-paper-write")
    steps, plan = _steps_by_id(loader, "meta-paper-write")

    assert plan.final_text_mode == "step:deliver_paper"
    assert steps["paper_collect"].kind == "llm_chat"
    assert steps["paper_collect"].clarify_config is None
    assert steps["paper_clarify"].kind == "user_input"
    assert steps["paper_clarify"].when == (
        "'NEEDS_CLARIFICATION: yes' in outputs.paper_collect"
    )
    assert steps["paper_contract"].kind == "llm_chat"
    assert steps["paper_contract"].depends_on == ("paper_collect", "paper_clarify")
    paper_collect_prompt = str(steps["paper_collect"].with_args)
    assert "NEEDS_CLARIFICATION" in paper_collect_prompt
    assert "COMPACT_SKELETON by default" in paper_collect_prompt
    assert "Use FULL_MANUSCRIPT only when the user explicitly asks" in paper_collect_prompt
    assert "Do not set NEEDS_CLARIFICATION: yes for missing paper_mode" in paper_collect_prompt
    assert "write CLARIFY_QUESTION in the same" in paper_collect_prompt
    assert "TARGET_PAGES" in paper_collect_prompt
    assert "CITATION_TARGET" in paper_collect_prompt
    assert "MISSING_FIELDS" in paper_collect_prompt
    clarify = steps["paper_clarify"].clarify_config
    assert clarify is not None
    assert "Some paper details are missing" in clarify.intro
    assert "论文信息还不完整" in clarify.intro
    assert "user_language" in clarify.intro
    assert "contains_cjk" in clarify.intro
    assert clarify.fields[1].default == "COMPACT_SKELETON"
    assert "Mode (default COMPACT_SKELETON" in clarify.fields[1].prompt
    assert "类型（默认 COMPACT_SKELETON" in clarify.fields[1].prompt
    raw = str(loader.get_by_name("meta-paper-write").composition_raw)
    assert "inputs.collected.paper_collect" not in raw
    # Pipeline rewrite: experiment/plot (skill_exec stubs producing fake
    # CSV + matplotlib chart) replaced with 4 LLM steps that design the
    # experiments and emit LaTeX placeholder figures/tables/analysis.
    assert "experiment" not in steps
    assert "plot" not in steps
    assert steps["experiment_design"].when == (
        "'PAPER_MODE: FULL_MANUSCRIPT' in outputs.paper_contract or "
        "'PAPER_MODE: COMPACT_SKELETON' in outputs.paper_contract"
    )
    assert steps["figure_placeholders"].when == steps["experiment_design"].when
    assert steps["table_placeholders"].when == steps["experiment_design"].when
    assert steps["analysis_outline"].when == steps["experiment_design"].when
    assert steps["compile_latex"].when == (
        "'PAPER_MODE: COMPILE_ONLY' in outputs.paper_contract"
    )
    assert steps["writing_plan"].when == (
        "'PAPER_MODE: FULL_MANUSCRIPT' in outputs.paper_contract"
    )
    assert steps["compile_pdf"].when == (
        "'PAPER_MODE: FULL_MANUSCRIPT' in outputs.paper_contract or "
        "'PAPER_MODE: COMPACT_SKELETON' in outputs.paper_contract or "
        "'PAPER_MODE: REPAIR_EXISTING' in outputs.paper_contract"
    )
    assert steps["publish_pdf"].when == steps["compile_pdf"].when
    assert steps["deliver_paper"].when == steps["compile_pdf"].when
    compile_prompt = str(steps["compile_pdf"].tool_args)
    assert "refusing to create degraded PDF" in compile_prompt
    for step_id in (
        "paper_contract",
        "paper_preferences",
        "source_pack",
        "experiment_design",
        "figure_placeholders",
        "table_placeholders",
        "analysis_outline",
        "outline",
        "citation_plan",
        "final_manuscript_package",
        "citation_integrity_gate",
        "latex_sanitizer",
        "compile_latex",
    ):
        assert steps[step_id].kind == "llm_chat", step_id
    for step_id in (
        "persist_sections",
        "assemble_manuscript_tex",
        "citation_map",
        "compile_pdf",
    ):
        assert steps[step_id].kind == "tool_call", step_id
    for step_id in (
        "section_abstract",
        "section_introduction",
        "section_related_work",
        "section_method",
        "section_experiments",
        "section_discussion",
        "section_conclusion",
    ):
        assert steps[step_id].kind == "agent", step_id
        assert steps[step_id].skill == "paper-section-author", step_id
    for step_id in ("search_papers", "refbib"):
        assert steps[step_id].kind == "skill_exec"
    assert steps["persist_sections"].depends_on == (
        "section_abstract",
        "section_introduction",
        "section_related_work",
        "section_method",
        "section_experiments",
        "section_discussion",
        "section_conclusion",
    )
    assert steps["assemble_manuscript_tex"].depends_on == (
        "writing_plan", "persist_sections", "refbib",
    )
    assert steps["compile_latex"].depends_on == ("latex_sanitizer",)
    # New citation-provenance contract — the manuscript prompt must
    # carry the strict "do not invent cite keys" instructions.
    final_prompt = str(steps["final_manuscript_package"].with_args)
    assert "DO NOT invent cite keys" in final_prompt
    assert "verbatim in REFERENCES_BIB" in final_prompt
    assert "MANUSCRIPT_PLAN" in final_prompt
    assert "REFERENCE_PLACEHOLDERS" in final_prompt
    assert "TARGET_LENGTH_EXPANSION_PLAN" in final_prompt
    assert "Limitations" in final_prompt
    assert "Threats to Validity" in final_prompt
    assert "references are safer than fabricated BibTeX" in final_prompt
    assert "put the plan and expansion plan before the LaTeX skeleton" in final_prompt
    assert "keep MANUSCRIPT_TEX under 2,500 words" in final_prompt
    assert "\\documentclass" in final_prompt
    assert "\\begin{document}" in final_prompt
    assert "figure_placeholders" in final_prompt
    assert "table_placeholders" in final_prompt
    assert "analysis_outline" in final_prompt
    assert "CITATION_STRATEGY" in final_prompt
    # citation_map step exposes the per-key audit table.
    persist_prompt = str(steps["persist_sections"].tool_args)
    assert "SECTION_ARTIFACTS" in persist_prompt
    assert "CONTEXT_POLICY" in persist_prompt
    assemble_prompt = str(steps["assemble_manuscript_tex"].tool_args)
    assert "MANUSCRIPT_PATH" in assemble_prompt
    assert "full manuscript persisted on disk" in assemble_prompt
    citation_map_prompt = str(steps["citation_map"].tool_args)
    assert "Source Quality" in citation_map_prompt
    assert "INVALID" in citation_map_prompt
    assert "STRONG" in citation_map_prompt


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
    _assert_user_input_step(
        steps,
        "pdf_clarify",
        when_contains="NEEDS_CLARIFICATION: yes",
        required_fields={"source_status", "source_material"},
    )
    assert steps["extract"].on_failure == "inline_excerpt_extract"
    assert steps["extract"].depends_on == ("intake", "pdf_clarify")
    assert "inline_excerpts_only" in steps["extract"].when
    assert "reference_without_content" in steps["extract"].when
    assert "pdf upload handy" in steps["extract"].when
    assert "page " in steps["extract"].when
    assert " says " in steps["extract"].when
    assert steps["inline_excerpt_extract"].kind == "llm_chat"
    for step_id in ("intake", "cross_document_synthesis", "traceable_index"):
        assert steps[step_id].kind == "llm_chat"
    assert steps["extract"].skill == "pdf-toolkit"
    assert steps["per_document_digest"].skill == "summarize"
    synthesis_prompt = str(steps["cross_document_synthesis"].with_args)
    assert "Evidence Matrix" in synthesis_prompt
    assert "Direct Evidence" in synthesis_prompt
    assert "Inferences" in synthesis_prompt
    assert "EXCERPT-ONLY" in synthesis_prompt
    assert "Source Excerpts table" in synthesis_prompt
    assert "source hierarchy" in synthesis_prompt
    assert "extraction anomaly" in synthesis_prompt
    assert "page 3 says" in synthesis_prompt
    assert "never claim page count" in synthesis_prompt
    assert "Reusable Memory Index" in synthesis_prompt
    assert "evidence_ids" in synthesis_prompt
    intake_prompt = str(steps["intake"].with_args)
    assert "SOURCE_STATUS" in intake_prompt
    assert "USER_EXCERPTS" in intake_prompt
    assert "inline_excerpts_only" in intake_prompt
    assert "NEEDS_CLARIFICATION" in intake_prompt
    assert "reference_without_content" in intake_prompt
    assert "Clarification answers" in synthesis_prompt


@pytest.mark.asyncio
async def test_pdf_intelligence_matches_lived_chinese_pdf_request(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    ctx = SimpleNamespace(
        message=(
            "帮我看一下这个 PDF："
            "tests/fixtures/meta_skill_inputs/pdf_intelligence/"
            "router-evaluation-summary.pdf"
        ),
        session_key="test-session",
        metadata={"skill_loader": loader},
        system_prompt=("base prompt", ""),
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="web",
    )

    out = await meta_resolution(ctx)  # type: ignore[arg-type]

    assert out.metadata["meta_match"].plan.name == "meta-pdf-intelligence"
    assert out.metadata["meta_match_trigger"].lower() == "看一下这个 pdf"
    assert 'call `meta_invoke(name="meta-pdf-intelligence")`' in out.system_prompt[1]


def test_stack_trace_investigator_supports_language_routing_and_degraded_output(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    ids = _step_ids(loader, "meta-stack-trace-investigator")
    spec = loader.get_by_name("meta-stack-trace-investigator")
    assert spec is not None
    raw = str(spec.composition_raw)

    assert {"trace_collect", "repro_suggestion", "degraded_summary"} <= ids
    steps = {step["id"]: step for step in spec.composition_raw["steps"]}
    assert steps["trace_collect"]["kind"] == "llm_chat"
    trace_collect = str(steps["trace_collect"]["with"])
    assert "Do NOT ask the user to confirm" in trace_collect
    assert "ASSUMED" in trace_collect
    assert "PRIMARY_EXCEPTION" in trace_collect
    assert "inputs.collected.trace_collect" not in raw
    assert "outputs.trace_collect" in raw
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
    assert "## Exception Semantics" in raw
    assert "## Trace Facts" in raw
    assert "First line must be exactly: ## Trace Facts" in raw
    assert "## Ranked Root Cause Matrix" in raw
    assert "Reject payload shapes" in raw
    assert "json.loads(raw) succeeded" in raw
    assert "top-level key \"result\" was absent" in raw
    assert "Use the same language as the original user request" in raw
    assert "raw errors from repository/history tools as private diagnostic" in raw
    assert "Do not quote raw lookup errors" in raw
    assert "list/string/null payloads would cause" in raw
    assert "REPO_GREP: DEGRADED" in raw
    assert "ISSUE_SEARCH: DEGRADED" in raw
    assert "GIT_HISTORY: DEGRADED" in raw
    assert "MEMORY_RECALL: DEGRADED" in raw
    assert "static sweeps" in raw
    assert "producer/wrappers, runtime/streaming" in raw
    assert "streaming/control frames" in raw
    assert "provider/transport rewraps" in raw
    assert "at least seven ranked hypotheses" in raw
    assert "schema/version drift" in raw
    assert "exception serialized as tool output" in raw
    assert "## Related Checks" in raw
    assert "non-authoritative search hint" in raw
    assert "Prior incident" in raw
    assert "memory path" in raw
    assert "hypothesis-driven reproducer matrix" in raw
    assert "tool identity / tool_call_id" in raw
    assert "streaming/control-frame path" in raw
    assert "git log/blame" in raw
    assert "rg -nF \"parse_tool_result\"" in raw
    assert "result|data|output|content|error|status|message" in raw
    assert "json.loads" in raw
    assert "repo-wide commands first" in raw
    assert "Verification Commands must contain only commands/checks" in raw
    assert "Never include file-creation or file-edit commands" in raw
    assert "no `cat >`" in raw
    assert "no `tee`" in raw
    assert "no `python - <<`" in raw
    assert "no `/tmp`" in raw
    assert "inline snippet" in raw
    assert "Use only read-only searches/history/log commands" in raw
    assert "cap root-cause" in raw and "matrix rows at 8" in raw
    assert "Patch Direction must complete before Related Checks" in raw
    assert "do not recommend returning a default" in raw
    assert "typed" in raw and "protocol/execution errors" in raw
    assert "fixture-driven contract tests" in raw
    assert "exact import-path" in raw and "reproducer" in raw
    assert "targeted pytest command" in raw
    assert "producer-adapter checks and contract tests" in raw
    assert "parser boundary: decode, type check, error-envelope branch" in raw
    assert "Explicitly" in raw and "silent default-return behavior" in raw
    assert "Do not include the words \"meta-skill\"" in raw
    assert "not executed" in raw
    assert "Assumptions / Constraints" in raw
    assert "git-diff" in _orchestrated_skill_names(loader, "meta-stack-trace-investigator")
    assert "history-explorer" in _orchestrated_skill_names(
        loader, "meta-stack-trace-investigator",
    )


def test_travel_planner_collects_preferences_constraints_and_variants(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    spec = loader.get_by_name("meta-travel-planner")
    assert spec is not None
    ids = _step_ids(loader, "meta-travel-planner")

    assert {
        "trip_preferences",
        "weather",
        "poi",
        "constraints",
        "itinerary",
        "final_plan",
    } <= ids
    assert "export" not in ids
    triggers = {trigger.lower() for trigger in spec.triggers}
    assert "days in" in triggers
    assert "plan a trip" in triggers
    assert "itinerary for" in triggers


def test_travel_planner_uses_fast_final_itinerary_path(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-travel-planner")
    steps, plan = _steps_by_id(loader, "meta-travel-planner")

    assert plan.final_text_mode == "step:final_plan"
    assert steps["trip_collect"].kind == "llm_chat"
    assert steps["trip_collect"].clarify_config is None
    _assert_user_input_step(
        steps,
        "trip_clarify",
        when_contains="NEEDS_CLARIFICATION: yes",
        required_fields={"destination", "days"},
    )
    for step_id in (
        "trip_collect",
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
    assert steps["trip_preferences"].depends_on == ("trip_collect", "trip_clarify")
    assert steps["final_plan"].depends_on == ("itinerary", "constraints", "weather", "poi")
    collect_prompt = str(steps["trip_collect"].with_args)
    preference_prompt = str(steps["trip_preferences"].with_args)
    constraint_prompt = str(steps["constraints"].with_args)
    final_plan_prompt = str(steps["final_plan"].with_args)
    assert "Do NOT ask the user to confirm details" in collect_prompt
    assert "safely inferable" in collect_prompt
    assert "Do not invent exact calendar dates" in collect_prompt
    assert "NEEDS_CLARIFICATION" in collect_prompt
    assert "only when destination or trip length is absent" in collect_prompt
    assert "outputs.trip_collect" in preference_prompt
    assert "Clarification answers" in preference_prompt
    assert "Never return a clarification question" in preference_prompt
    assert "short-range/current forecasts" in constraint_prompt
    assert "seasonal risk language" in constraint_prompt
    assert "mobility, dietary, fixed-booking" in constraint_prompt
    assert "Primary 3-day itinerary" not in final_plan_prompt
    assert "requested or inferred trip length" in final_plan_prompt
    assert "Variants" in str(steps["final_plan"].with_args)
    assert "Evidence and source notes" in str(steps["final_plan"].with_args)
    assert "Next steps" in str(steps["final_plan"].with_args)
    assert "artifact or file" in final_plan_prompt
    assert "Route spine" in final_plan_prompt
    assert "Do not open with" in final_plan_prompt
    assert "Do not invent exact trip calendar dates" in final_plan_prompt
    assert "seasonal planning assumption" in final_plan_prompt
    assert "one rest block or pacing reset per day" in final_plan_prompt
    assert "weather switch points" in final_plan_prompt
    assert "verify before booking" in final_plan_prompt
    assert "avoid cross-city zigzags" in final_plan_prompt
    assert "ranges and flex levers" in final_plan_prompt
    assert "omit artifact generation suggestions" in final_plan_prompt
    assert "ARTIFACT_READY" not in str(plan.steps)


def test_meta_skill_creator_has_intent_collision_risk_and_preview_gates(
    tmp_path: Path,
) -> None:
    ids = _step_ids(_loader(tmp_path), "meta-skill-creator")

    assert {
        "clarify_intent",
        "normal_skill_exit",
        "creator_mode",
        "collision_check",
        "risk_classify",
        "single_model_baseline",
        "acceptance_compare",
        "runtime_e2e",
        "preview",
        "persist",
        "final_response",
    } <= ids


def test_meta_skill_creator_supports_preview_only_branch(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    steps, plan = _steps_by_id(loader, "meta-skill-creator")

    assert plan.final_text_mode == "step:final_response"
    _assert_user_input_step(
        steps,
        "creator_clarify",
        when_contains="route: meta-skill",
        required_fields={"workflow_goal", "output_shape"},
    )
    assert "needs_clarification: yes" in steps["creator_clarify"].when
    assert steps["normal_skill_exit"].kind == "tool_call"
    assert steps["normal_skill_exit"].tool == "emit_text"
    assert "route: normal-skill" in steps["normal_skill_exit"].when
    assert steps["creator_mode"].kind == "llm_classify"
    assert steps["creator_mode"].depends_on == ("clarify_intent", "creator_clarify")
    assert "route: meta-skill" in steps["creator_mode"].when
    assert set(steps["creator_mode"].output_choices) == {
        "PREVIEW_ONLY",
        "PERSISTED_PROPOSAL",
        "FULL_GATED",
    }
    assert set(steps["pick_pattern"].output_choices) == {
        "p1_sequential",
        "p2_fan_out_merge",
        "p3_condition_gated",
    }
    clarify_intent_text = str(steps["clarify_intent"].with_args)
    creator_mode_text = str(steps["creator_mode"].with_args)
    assert "NEEDS_CLARIFICATION" in clarify_intent_text
    assert "Clarification answers" in creator_mode_text
    assert "inputs.system_prompt" in creator_mode_text
    assert "unattended auto-propose" in creator_mode_text
    assert "dream" in creator_mode_text
    assert "cron" in creator_mode_text
    assert steps["clarify_intent"].kind == "llm_chat"
    assert steps["collision_check"].kind == "llm_chat"
    assert steps["risk_classify"].kind == "llm_chat"
    assert steps["preview"].kind == "llm_chat"
    assert steps["harvest"].kind == "skill_exec"
    assert steps["harvest"].skill == "history-explorer"
    creation_steps = {
        "creator_mode",
        "harvest",
        "pick_pattern",
        "fill_slots",
        "assemble",
        "collision_check",
        "lint",
        "risk_classify",
        "single_model_baseline",
        "acceptance_compare",
        "smoke",
        "runtime_e2e",
        "preview",
        "persist",
    }
    for step_id in creation_steps:
        assert "route: meta-skill" in steps[step_id].when
    assert "Unattended meta-skill auto-propose run" in steps["harvest"].when
    assert "outputs.creator_mode != 'PREVIEW_ONLY'" in steps["smoke"].when
    assert "outputs.creator_mode != 'PREVIEW_ONLY'" in steps["persist"].when
    assert steps["final_response"].depends_on == ("preview", "normal_skill_exit")
    assert steps["final_response"].tool == "emit_text"


def test_meta_skill_creator_acceptance_compares_against_highest_tier_baseline(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    steps, _plan = _steps_by_id(loader, "meta-skill-creator")

    baseline = steps["single_model_baseline"]
    compare = steps["acceptance_compare"]

    assert baseline.kind == "llm_chat"
    assert baseline.depends_on == ("creator_mode",)
    assert "route: meta-skill" in baseline.when
    assert "outputs.creator_mode == 'FULL_GATED'" in baseline.when
    assert "highest-tier" in str(baseline.with_args).lower()
    assert "same task" in str(baseline.with_args).lower()
    assert "system prompt" in str(baseline.with_args).lower()
    assert "inputs.system_prompt" in str(baseline.with_args)
    assert "meta-skill-creator" in str(baseline.with_args)
    assert "auto-enable" in str(baseline.with_args)
    assert "outputs." not in str(baseline.with_args)

    assert compare.kind == "llm_chat"
    assert set(compare.depends_on) == {"assemble", "single_model_baseline"}
    assert "route: meta-skill" in compare.when
    assert "outputs.creator_mode == 'FULL_GATED'" in compare.when
    assert "orchestrated candidate" in str(compare.with_args).lower()
    assert "single-model baseline" in str(compare.with_args).lower()
    assert "meta-skill-creator" in str(compare.with_args)
    assert "Never make proposal persistence" in str(compare.with_args)
    assert "winner" in str(compare.with_args).lower()
    assert "runtime_e2e" in steps
    assert steps["runtime_e2e"].kind == "tool_call"
    assert steps["runtime_e2e"].tool == "meta_skill_runtime_e2e_run"
    assert "route: meta-skill" in steps["runtime_e2e"].when
    assert "outputs.creator_mode == 'FULL_GATED'" in steps["runtime_e2e"].when
    assert set(steps["runtime_e2e"].depends_on) == {"assemble", "smoke"}
    assert "acceptance_compare" in str(steps["preview"].depends_on)
    assert "runtime_e2e" in str(steps["preview"].depends_on)
    assert "Baseline comparison" in str(steps["preview"].with_args)
    assert "acceptance_result" in str(steps["persist"].tool_args)
    assert "outputs.acceptance_compare" in str(steps["persist"].tool_args)
    assert "runtime_e2e_result" in str(steps["persist"].tool_args)
    assert "outputs.runtime_e2e" in str(steps["persist"].tool_args)
    assert "collision_result" in str(steps["persist"].tool_args)
    assert "risk_result" in str(steps["persist"].tool_args)
    assert "creator_mode" in str(steps["persist"].tool_args)


def test_migration_assistant_routes_guides_and_optional_repo_context(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path)
    _assert_composes_at_least_two_skills(loader, "meta-migration-assistant")
    steps, plan = _steps_by_id(loader, "meta-migration-assistant")

    assert plan.final_text_mode == "step:write_plan"
    assert steps["migration_intake"].kind == "llm_chat"
    _assert_user_input_step(
        steps,
        "migration_clarify",
        when_contains="NEEDS_CLARIFICATION: yes",
        required_fields={"source_stack", "target_stack"},
    )
    assert set(steps["classify"].depends_on) == {"migration_intake", "migration_clarify"}
    assert steps["fetch_guide"].kind == "skill_exec"
    assert steps["fetch_guide"].skill == "multi-search-engine"
    assert set(steps["fetch_guide"].depends_on) == {"classify", "migration_clarify"}
    assert steps["repo_context"].skill == "git-diff"
    assert "current diff" in steps["repo_context"].when
    assert "current branch" in steps["repo_context"].when
    assert "'pr' in" not in steps["repo_context"].when
    assert "pull request" in steps["repo_context"].when
    assert set(steps["write_plan"].depends_on) == {
        "classify",
        "migration_clarify",
        "fetch_guide",
        "repo_context",
    }
    assert steps["write_plan"].kind == "llm_chat"
    intake_prompt = str(steps["migration_intake"].with_args)
    classify_prompt = str(steps["classify"].with_args)
    fetch_prompt = str(steps["fetch_guide"].with_args)
    write_plan_prompt = str(steps["write_plan"].with_args)
    assert "NEEDS_CLARIFICATION" in intake_prompt
    assert "Clarification answers" in classify_prompt
    assert "Ignore benchmark wrappers" in classify_prompt
    assert "truncate(1400)" in classify_prompt
    assert "after benchmark constraints" in classify_prompt
    assert "CommonJS" in classify_prompt and "native ESM" in classify_prompt
    assert "return exactly" in classify_prompt and "CJS_TO_ESM" in classify_prompt
    assert "Clarification answers" in fetch_prompt
    assert "Ignore benchmark preambles" in fetch_prompt
    assert "package.json type/exports" in fetch_prompt
    assert "directory imports" in fetch_prompt
    assert "Answer the user's requested" in write_plan_prompt
    assert "EFFECTIVE_KIND=CJS_TO_ESM" in write_plan_prompt
    assert "CommonJS to native ES Modules" in write_plan_prompt
    assert "do not wrap the entire answer in a fenced code block" in write_plan_prompt
    assert "## Evidence boundary" in write_plan_prompt
    assert "## Repository discovery checklist" in write_plan_prompt
    assert "## Rollout and rollback" in write_plan_prompt
    assert "requested migration kind is authoritative" in write_plan_prompt
    assert "final-layer classifier override" in write_plan_prompt
    assert "Do not expose classifier labels" in write_plan_prompt
    assert "Do not invent repo-specific files" in write_plan_prompt
    assert "Do not use unverified concrete entrypoint paths" in write_plan_prompt
    assert "`git commit`" in write_plan_prompt
    assert "CJS_TO_ESM" in write_plan_prompt
    assert "npm pkg get type main exports scripts" in write_plan_prompt
    assert "hypothesis-driven" in write_plan_prompt
    assert "npm pack --dry-run" in write_plan_prompt
    assert "npx publint" in write_plan_prompt
    assert "arethetypeswrong" in write_plan_prompt
    assert "semver-major trigger" in write_plan_prompt
    assert "canary/internal" in write_plan_prompt
    assert "Avoid file-creation" in write_plan_prompt
    assert "Benchmark/no-write constraint" in write_plan_prompt
    assert "`cat >`" in write_plan_prompt
    assert "`tee`" in write_plan_prompt
    assert "`node -e` snippets that write files" in write_plan_prompt
    assert "Never ask the user to create `tmp-smoke.*` files" in write_plan_prompt
    assert "JSON-module/import-attributes support" in write_plan_prompt
    assert "Avoid invented loader placeholders" in write_plan_prompt
    assert "exports` takes precedence" in write_plan_prompt
    assert "1,200-1,800 words" in write_plan_prompt
    assert "directory `index.js` imports" in write_plan_prompt
    assert "default export shape changes" in write_plan_prompt
    assert "subpath whitelisting" in write_plan_prompt
    assert "Do not include brittle placeholder commands" in write_plan_prompt
    assert "dual-package hazards" in write_plan_prompt
    assert "eslint --fix" in write_plan_prompt
    assert "Avoid obsolete Node flags" in write_plan_prompt


# ── A8: high-risk experimental meta-skills carry enforced metadata ──


def _read_exp_frontmatter(name: str) -> dict:
    """Parse the YAML frontmatter of an experimental meta-skill."""
    path = EXP / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    # Frontmatter is the block between the first pair of ``---`` fences.
    chunks = text.split("---", 2)
    assert len(chunks) >= 3, f"{name} missing frontmatter fences"
    return yaml.safe_load(chunks[1]) or {}


_A8_DEPRECATED = (
    "meta-issue-to-pr-autopilot",
    "meta-long-running-build-watchdog",
)

_A8_HARDENED = _A8_DEPRECATED + (
    "meta-pre-commit-quality-gate",
    "meta-security-review-bundle",
)


@pytest.mark.parametrize("skill_name", _A8_DEPRECATED)
def test_a8_deprecated_high_risk_skill_is_invocation_disabled(
    skill_name: str,
) -> None:
    """A8: the two top-risk experimental meta-skills must stay off the
    resolver's match path. They have no per-step budget (E5), no
    runtime capability enforcement (P1 narrowed ToolContext), and no
    side-effect ledger (E4), so a resolver match would re-open every
    auto-fix loop / PR-creation loop the deprecation was meant to
    contain. Empty triggers + ``disable-model-invocation: true`` is
    belt and suspenders: either alone would also suffice."""
    fm = _read_exp_frontmatter(skill_name)
    assert fm.get("disable-model-invocation") is True, (
        f"{skill_name} must set ``disable-model-invocation: true`` to "
        f"stay off the resolver"
    )
    triggers = fm.get("triggers")
    assert triggers in ([], None), (
        f"{skill_name} must have empty triggers; got {triggers!r}"
    )
    # The description must announce the deprecation so a human reading
    # the SKILL.md (or a creator-generated catalog index) immediately
    # sees why this skill no longer fires.
    description = str(fm.get("description") or "")
    assert "[DEPRECATED]" in description, (
        f"{skill_name} description must lead with ``[DEPRECATED]``; got "
        f"{description!r}"
    )


@pytest.mark.parametrize("skill_name", _A8_HARDENED)
def test_a8_high_risk_skill_declares_risk_and_capabilities(
    skill_name: str,
) -> None:
    """A8: every high-risk experimental meta-skill must declare
    ``metadata.opensquilla.risk: high`` AND a non-empty
    ``capabilities`` list. The fields are advisory in P0 (runtime
    enforcement lands with E5 + narrowed ``ToolContext`` in P1), but
    pinning them now means the auto-propose risk classifier
    cross-check has something to compare against and the catalog audit
    can grep these without parsing the DAG body."""
    fm = _read_exp_frontmatter(skill_name)
    metadata = fm.get("metadata") or {}
    omc = metadata.get("opensquilla") or {}
    assert omc.get("risk") == "high", (
        f"{skill_name} must declare ``metadata.opensquilla.risk: high``; "
        f"got {omc.get('risk')!r}"
    )
    capabilities = omc.get("capabilities") or []
    assert isinstance(capabilities, list) and capabilities, (
        f"{skill_name} must declare a non-empty "
        f"``metadata.opensquilla.capabilities`` list; got {capabilities!r}"
    )
