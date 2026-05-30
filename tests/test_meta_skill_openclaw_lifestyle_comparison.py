import asyncio
import json
from pathlib import Path

from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.trigger_accuracy import TriggerCase, evaluate_trigger_cases
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.templating import evaluate_when
from scripts.compare_meta_skill_openclaw import EndpointResult, JudgeResult, OpenSquillaRunner
from scripts.compare_meta_skill_openclaw_lifestyle import (
    ENGLISH_LIFESTYLE_PROMPTS,
    LIFESTYLE_COMPARISON_CASES,
    OPENCLAW_T3_MODEL,
    _apply_lifestyle_judge_result,
    _compare_results,
    _judge_lifestyle_with_retries,
    _lifestyle_judge_result_is_complete,
    build_lifestyle_rows,
    judge_existing,
    load_openclaw_baseline,
    render_lifestyle_markdown,
    render_lifestyle_prompts_markdown,
    score_response,
)

SELECTED_SKILLS = [
    "meta-document-to-decision",
    "meta-web-research-to-report",
    "meta-daily-operator-brief",
    "meta-account-watch",
    "meta-job-search-pipeline",
    "meta-kid-project-planner",
]


def test_lifestyle_catalog_covers_selected_meta_skills_without_exclusions() -> None:
    assert [case.skill_name for case in LIFESTYLE_COMPARISON_CASES] == SELECTED_SKILLS
    assert {case.case_id for case in LIFESTYLE_COMPARISON_CASES} == {
        "document_vendor_decision",
        "web_research_parent_esim",
        "daily_operator_morning_plan",
        "account_watch_competitor_week",
        "job_search_tailor_pack",
        "kid_project_balcony_plants",
    }
    assert all(case.scenario == "lifestyle_primary" for case in LIFESTYLE_COMPARISON_CASES)
    assert "meta-paper-write" not in {case.skill_name for case in LIFESTYLE_COMPARISON_CASES}
    assert "meta-skill-creator" not in {case.skill_name for case in LIFESTYLE_COMPARISON_CASES}


def test_selected_meta_skills_are_grounded_in_clawhub_top100_components() -> None:
    expectations = {
        "meta-document-to-decision": ["Word / DOCX", "Excel / XLSX", "Pdf"],
        "meta-web-research-to-report": ["Multi Search Engine", "Word / DOCX"],
        "meta-daily-operator-brief": ["Weather", "Multi Search Engine", "Elite Longterm Memory"],
        "meta-account-watch": ["Multi Search Engine", "Excel / XLSX", "Word / DOCX"],
        "meta-job-search-pipeline": ["Multi Search Engine", "Excel / XLSX", "Word / DOCX"],
        "meta-kid-project-planner": ["Multi Search Engine", "Weather", "PowerPoint / PPTX"],
    }

    for skill_name in SELECTED_SKILLS:
        raw = Path(f"src/opensquilla/skills/bundled/{skill_name}/SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "clawhub_top100_composition:" in raw
        assert "Top ClawHub Skills" in raw
        for component in expectations[skill_name]:
            assert component in raw


def test_lifestyle_prompts_are_conversational_and_realistic() -> None:
    prompts = [case.prompt for case in LIFESTYLE_COMPARISON_CASES]

    assert all("benchmark:" not in prompt.lower() for prompt in prompts)
    assert all("OpenSquilla" not in prompt and "OpenClaw" not in prompt for prompt in prompts)
    assert any("爸妈" in prompt for prompt in prompts)
    assert any("幼儿园" in prompt for prompt in prompts)
    assert any("报价" in prompt or "供应商" in prompt for prompt in prompts)
    assert any("今天" in prompt for prompt in prompts)
    assert any("能不能装" in prompt for prompt in prompts)
    assert any("小红书" in prompt for prompt in prompts)
    assert any("产品运营岗位" in prompt for prompt in prompts)
    assert any("阳台种豆芽" in prompt for prompt in prompts)
    assert all("example.invalid" not in prompt for prompt in prompts)
    assert all("manifest" not in prompt.lower() for prompt in prompts)
    assert any("孩子老师昨天 16:20" in prompt for prompt in prompts)


def _bundled_meta_plan(skill_name: str, tmp_path: Path):
    loader = SkillLoader(
        bundled_dir=Path("src/opensquilla/skills/bundled"),
        snapshot_path=tmp_path / "snapshot.json",
    )
    spec = loader.get_by_name(skill_name)
    assert spec is not None
    plan = parse_meta_plan(spec)
    assert plan is not None
    return plan


def test_lifestyle_meta_skills_do_not_clarify_when_intake_found_no_missing_fields(
    tmp_path: Path,
) -> None:
    examples = {
        "meta-document-to-decision": """
DOCUMENT_TYPES:
  - pasted_text
SOURCES:
  - quote
DECISION_QUESTION: should we sign?
NEEDS_CLARIFICATION: yes
MISSING_FIELDS:
  - none
""",
        "meta-daily-operator-brief": """
DATE_SCOPE: today
TIMEZONE: Asia/Shanghai
LOCATION: Shanghai
NEEDS_CLARIFICATION: yes
MISSING_FIELDS:
  - none
""",
    }

    for skill_name, intake in examples.items():
        plan = _bundled_meta_plan(skill_name, tmp_path)
        clarify = next(step for step in plan.steps if step.id == "clarify")

        assert evaluate_when(
            clarify.when,
            inputs={},
            outputs={"intake": intake},
        ) is False


def test_kid_project_planner_does_not_clarify_when_no_fields_missing(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-kid-project-planner", tmp_path)
    clarify = next(step for step in plan.steps if step.id == "project_clarify")

    preferences = """
TOPIC: balcony mung bean observation
AGE_BAND: EARLY_GRADE
DEADLINE_DAYS: 14
BUDGET_BAND: SHOESTRING
PARENT_SUPERVISION: LIGHT
LANGUAGE: zh
PROJECT_SAFE: yes
UNSAFE_REASON: none
NEEDS_CLARIFICATION: yes
MISSING_FIELDS:
  - none
ASSUMPTIONS:
  - balcony gets half-day sun
"""

    assert evaluate_when(
        clarify.when,
        inputs={},
        outputs={"preferences": preferences},
    ) is False


def test_lifestyle_meta_skills_handle_missing_memory_skill_with_failover(
    tmp_path: Path,
) -> None:
    expectations = {
        "meta-daily-operator-brief": ("memory_recall", "memory_recall_fallback"),
    }

    for skill_name, (step_id, fallback_id) in expectations.items():
        plan = _bundled_meta_plan(skill_name, tmp_path)
        memory_step = next(step for step in plan.steps if step.id == step_id)
        fallback_step = next(step for step in plan.steps if step.id == fallback_id)

        assert memory_step.on_failure == fallback_id
        assert fallback_step.kind == "llm_chat"


def test_new_lifestyle_meta_skills_hide_runtime_failures_and_reply_inline(
    tmp_path: Path,
) -> None:
    expectations = {
        "meta-account-watch": {
            "final": "deliver_watch_brief",
            "fallbacks": {
                "recall_baseline": "recall_baseline_fallback",
                "web_research": "web_research_fallback",
                "store_brief": "store_brief_fallback",
            },
            "required": ["baseline diff", "signal", "actions"],
        },
        "meta-job-search-pipeline": {
            "final": "deliver_jobpack",
            "fallbacks": {
                "recall_company": "recall_company_fallback",
                "web_research": "web_research_fallback",
            },
            "required": ["JD Requirement / My Evidence / Gap Table", "48-Hour Interview Prep"],
        },
        "meta-kid-project-planner": {
            "final": "project_pack",
            "fallbacks": {
                "recall_past_projects": "recall_past_projects_fallback",
                "quick_reference": "quick_reference_fallback",
                "heavy_research": "heavy_research_fallback",
                "weather_check": "weather_check_fallback",
                "kid_deck": "kid_deck_fallback",
                "project_illustration": "project_illustration_fallback",
            },
            "required": [
                "Tiny observation sheet",
                "use the generated image as the cover/front image",
                "print-ready markdown",
            ],
        },
        "meta-web-research-to-report": {
            "final": "final_report_audit",
            "fallbacks": {
                "search": "search_fallback",
            },
            "required": [
                "assumptions/decision context",
                "recommendation",
                "risks/tradeoffs",
                "evidence limits",
                "next steps for tonight",
            ],
        },
    }

    for skill_name, expected in expectations.items():
        plan = _bundled_meta_plan(skill_name, tmp_path)
        step_by_id = {step.id: step for step in plan.steps}

        for step_id, fallback_id in expected["fallbacks"].items():
            assert step_by_id[step_id].on_failure == fallback_id
            assert step_by_id[fallback_id].kind == "llm_chat"

        final_step = step_by_id[expected["final"]]
        final_text = json.dumps(final_step.with_args, ensure_ascii=False)
        assert "Return the complete" in final_text
        assert "inline in chat" in final_text
        assert "Do not create, save, export, attach" in final_text
        assert "Never mention workflow, meta-skill, tool names" in final_text
        assert "connector failures, workspace paths, or runtime details" in final_text
        for required in expected["required"]:
            assert required in final_text

    web_raw = Path(
        "src/opensquilla/skills/bundled/meta-web-research-to-report/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "source_seed" in web_raw
    assert "Verification targets, not live-checked" in web_raw
    assert "to check tonight, not live-verified" in web_raw
    assert "not as proof for factual claims" in web_raw


def test_job_search_pipeline_preserves_language_and_source_truth() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-job-search-pipeline/SKILL.md"
    ).read_text(encoding="utf-8")

    assert 'final_text_mode: "step:deliver_jobpack_audit"' in raw
    assert "deliver_jobpack_audit" in raw
    assert "Never return JSON" in raw
    assert "Remove leading process commentary" in raw
    assert "Remove internal sentinels such as PACK_MODE" in raw
    assert "Do not default Chinese user requests to English" in raw
    assert (
        "If the request is English, write\n            English-only prose and English headings"
        in raw
    )
    assert "write Simplified Chinese, including headings" in raw
    assert "Do not add unprovided tools, methods, outcomes, or metrics" in raw
    assert "A/B testing, NPS, customer interviews, Jira" in raw
    assert "ticket reduction" in raw
    assert "Do not upgrade responsibility" in raw
    assert "participated; do not rewrite it as owned, led, orchestrated" in raw
    assert "Use placeholders like [待补充]" in raw
    assert "Do not upgrade\n          participation to ownership" in raw
    assert "source_fact_ledger" in raw
    assert "PROVIDED_CANDIDATE_FACTS" in raw
    assert "FORBIDDEN_INFERENCES" in raw
    assert "Do not infer ownership from participation or training work" in raw
    assert "Before returning, audit every concrete claim against the Strict" in raw
    assert "事实边界 / 不编造说明" in raw
    assert "Avoid overclaim wording unless sourced" in raw
    assert "核心成员" in raw
    assert "对话记录" in raw
    assert "Do not call missing user-research preparation a fake or pretend" in raw
    assert "Keep the full output concise enough to complete in one turn" in raw
    assert "The 48-hour prep must include Day -2 and Day -1" in raw
    assert "if any intermediate draft conflicts with the source fact ledger" in raw
    assert "Do not copy\n          intermediate resume or cover-letter drafts verbatim" in raw
    assert "do not use the raw tailor_resume or cover_letter" in raw
    assert "Regenerate the final user-facing resume and letter from the" in raw
    assert "可直接粘贴的中文简历段落" in raw
    assert "负责过 3 个企业客户的上线培训" in raw
    assert "参与 AI 客服试点，但不是负责人" in raw


def test_account_watch_final_audit_and_export_gate(tmp_path: Path) -> None:
    plan = _bundled_meta_plan("meta-account-watch", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}

    assert plan.final_text_mode == "step:watch_brief_audit"
    assert "watch_brief_audit" in step_by_id
    assert "deliver_watch_brief" in step_by_id["watch_brief_audit"].depends_on
    assert "extract_signals" in step_by_id["watch_brief_audit"].depends_on

    xlsx_when = step_by_id["signals_xlsx"].when or ""
    assert "表格" not in xlsx_when
    assert "导出" in xlsx_when
    assert "xlsx" in xlsx_when

    audit_text = json.dumps(step_by_id["watch_brief_audit"].with_args, ensure_ascii=False)
    assert "Remove runtime commentary" in audit_text
    assert "Remove artifact or attachment claims" in audit_text
    assert "Do not claim that a file was generated" in audit_text
    assert "If a signal has no source hint" in audit_text
    assert "source limit" in audit_text


def test_account_watch_summarizes_web_without_non_executable_skill(tmp_path: Path) -> None:
    plan = _bundled_meta_plan("meta-account-watch", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}

    summarize_web = step_by_id["summarize_web"]
    assert summarize_web.kind == "llm_chat"
    assert summarize_web.skill != "summarize"
    summarize_text = json.dumps(summarize_web.with_args, ensure_ascii=False)
    assert "Compress the web research" in summarize_text
    assert "Do not expose tool names" in summarize_text


def test_account_watch_propagates_pasted_baseline_and_context_without_clarify(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-account-watch", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}

    assert "watch_context" in step_by_id

    watch_context = step_by_id["watch_context"]
    assert watch_context.kind == "llm_chat"
    context_text = json.dumps(watch_context.with_args, ensure_ascii=False)
    assert "inputs.user_message" in context_text
    assert "PASTED_BASELINE" in context_text
    assert "ACCOUNT_DIMENSION_GRID" in context_text
    assert "AUDIENCE" in context_text

    for step_id in (
        "web_research",
        "summarize_web",
        "enrich_accounts",
        "extract_signals",
        "baseline_diff",
        "recommend_actions",
        "deliver_watch_brief",
        "watch_brief_audit",
    ):
        step = step_by_id[step_id]
        assert "watch_context" in step.depends_on
        step_text = json.dumps(step.with_args, ensure_ascii=False)
        assert "watch_context" in step_text

    baseline_text = json.dumps(step_by_id["baseline_diff"].with_args, ensure_ascii=False)
    assert "PASTED_BASELINE" in baseline_text
    assert "inputs.user_message" in baseline_text

    extract_text = json.dumps(step_by_id["extract_signals"].with_args, ensure_ascii=False)
    assert "Do not return only the table header" in extract_text
    assert "emit one row per requested account × dimension" in extract_text


def test_account_watch_final_audit_avoids_source_limited_overclaim(tmp_path: Path) -> None:
    plan = _bundled_meta_plan("meta-account-watch", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}
    audit_text = json.dumps(step_by_id["watch_brief_audit"].with_args, ensure_ascii=False)

    assert "未见已核验新增" in audit_text
    assert "not proof that nothing changed" in audit_text
    assert "Do not say baseline judgments remain confirmed" in audit_text
    assert "Do not say public channels had no evidence" in audit_text
    assert "For source-limited table rows" in audit_text
    assert "do not use words such as" in audit_text
    assert "稳定、无变化、维持、沿用" in audit_text
    assert "Do not name specific sources in the source-limit section" in audit_text
    assert "extracted signals cite those exact sources" in audit_text


def test_document_decision_pasted_text_path_does_not_wait_on_substitute_fallbacks(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-document-to-decision", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}

    assert "pasted_text_extract" in step_by_id

    risk_review = step_by_id["risk_review"]
    assert "pasted_text_extract" in risk_review.depends_on
    assert "pdf_extract" in risk_review.depends_on
    assert "docx_extract" in risk_review.depends_on
    assert "xlsx_extract" in risk_review.depends_on
    assert "pdf_extract_fallback" not in risk_review.depends_on
    assert "docx_extract_fallback" not in risk_review.depends_on
    assert "xlsx_extract_fallback" not in risk_review.depends_on


def test_document_decision_prompt_prevents_false_overdue_and_fake_export() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-document-to-decision/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "payment deadline" in raw
    assert "overdue" in raw
    assert "upcoming/待确认" in raw
    assert "payment due" in raw
    assert "cancellation window has already passed" in raw
    assert "create, save, export, download, or attach a file" in raw
    assert "no workflow commentary" in raw
    assert "no meta-skill" in raw
    assert "exact reply deadlines" in raw
    assert "Do not cite statutes" in raw


def test_document_decision_never_derives_cancel_window_from_payment_deadline() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-document-to-decision/SKILL.md"
    ).read_text(encoding="utf-8")

    assert (
        "Do not derive cancellation deadlines by subtracting days from invoice or payment due dates"
        in raw
    )
    assert "If the contract end date or renewal effective date is missing" in raw
    assert "cancellation deadline unknown" in raw
    assert "avoid saying the notice window has passed" in raw
    assert "one-paragraph boss-forwardable summary" in raw
    assert "sign / negotiate first / reject" in raw
    assert "Do not speculate that the notice period may already be too short" in raw


def test_document_decision_final_audit_removes_legal_and_date_overreach(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-document-to-decision", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}

    assert plan.final_text_mode == "step:decision_brief_audit"
    assert "decision_brief_audit" in step_by_id
    assert "decision_brief" in step_by_id["decision_brief_audit"].depends_on
    assert "risk_review" in step_by_id["decision_brief_audit"].depends_on

    audit_text = json.dumps(step_by_id["decision_brief_audit"].with_args, ensure_ascii=False)
    assert "Remove statutes, legal article numbers" in audit_text
    assert "Civil Code" in audit_text
    assert "民法典" in audit_text
    assert "Do not invent today's date" in audit_text
    assert "relative wording such as today or before the payment due date" in audit_text
    assert "sales email" in audit_text
    assert "do not call it oral or verbal" in audit_text
    assert "Do not say an email promise is legally invalid" in audit_text
    assert "Use these exact section titles" in audit_text
    assert "Bottom-line recommendation / 底线推荐" in audit_text
    assert "What to do next in 24 hours / 接下来 24 小时" in audit_text
    assert "效力弱于合同" in audit_text
    assert "书面条款优先" in audit_text


def test_daily_operator_brief_hides_runtime_failures_and_clears_small_debts() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-daily-operator-brief/SKILL.md"
    ).read_text(encoding="utf-8")

    assert 'final_text_mode: "step:final_brief_audit"' in raw
    assert "final_brief_audit" in raw
    assert "Never expose raw tool/runtime failure details" in raw
    assert (
        "Never mention workflow, meta-skill, tool names, connector failures, "
        "workspace paths, or runtime details"
        in raw
    )
    assert "If the user asks for a morning brief, produce a morning-first plan" in raw
    assert "Do not turn it into an afternoon-only" in raw
    assert "Top 3 / 前三优先级" in raw
    assert "Risk / 风险 / 冲突" in raw
    assert "Data limits / 数据限制" in raw
    assert "only pasted / 仅根据" in raw
    assert "path/workspace/meta-skill problem" in raw
    assert "Rank priorities by consequence and reversibility" in raw
    assert "fixed external" in raw and "audience/customer impact" in raw
    assert "quick reply sweep / 快速回复清账" in raw
    assert "Do not defer a yesterday teacher/caregiver headcount reply" in raw
    assert "Drafts / 可直接发送" in raw
    assert "preserve uncertainty instead of" in raw
    assert "inventing amounts, prices, times, or attendance numbers" in raw
    assert "do not mark same-day future deadlines as" in raw
    assert "missed, overdue, or already late" in raw
    assert "11:30 前完成" in raw
    assert "[人数]" in raw and "[日期1]" in raw and "[时间1]" in raw and "[报价版本]" in raw
    assert "Do not invent weekdays, month-day" in raw
    assert "remove absolute dates, month-day dates" in raw
    assert "[日期1] [时间1] 或 [日期2] [时间2]" in raw
    assert (
        "Do not mention HTTP status codes, API failures, connector stack traces, "
        "or search errors"
        in raw
    )
    assert "When live data is unavailable, summarize only the user-facing limit" in raw
    assert "Clear one-minute social debts before deep work when they unblock other people" in raw
    assert "include ready-to-send message drafts" in raw
    assert "overdue school, caregiver, vendor, HR, finance, or customer replies" in raw
    assert "clear them in the first 15 minutes" in raw
    assert (
        "teacher / 老师 replies that were sent yesterday must be cleared in the "
        "first 15 minutes"
        not in raw
    )
    assert "Do not rely on remembered or previous-day weather" in raw
    assert "live weather not verified" in raw
    assert "ready-to-send drafts for named recipients or roles" in raw
    assert (
        "examples include school, caregiver, HR, finance, customer, vendor, and "
        "quote replies"
        in raw
    )
    assert "drafts for teacher, HR, finance, customer, and quote replies" not in raw


def test_lifestyle_meta_skills_have_natural_language_activation_cues() -> None:
    expectations = {
        "meta-document-to-decision": [
            "供应商续费",
            "这个合同要不要签",
            "vendor renewal",
            "contract excerpt",
            "decide tomorrow whether to sign",
            "sign, reject, or negotiate",
        ],
        "meta-web-research-to-report": [
            "decision memo",
            "travel esim research report",
            "carrier roaming vs local sim report",
            "mobile data plan decision memo",
            "research what i should order",
        ],
        "meta-daily-operator-brief": ["今天先帮我排一下", "今天前三优先级"],
        "meta-account-watch": ["盯一下这两个对手", "竞品销售群简报", "对手动态和基线相比"],
    }

    for skill_name, cues in expectations.items():
        raw = Path(f"src/opensquilla/skills/bundled/{skill_name}/SKILL.md").read_text(
            encoding="utf-8"
        )
        for cue in cues:
            assert cue in raw


def test_english_lifestyle_prompts_trigger_target_meta_skills(tmp_path: Path) -> None:
    from opensquilla.engine.steps.meta_resolution import _trigger_matches

    target_cases = {
        "document_vendor_decision": "meta-document-to-decision",
        "web_research_parent_esim": "meta-web-research-to-report",
    }
    loader = SkillLoader(
        bundled_dir=Path("src/opensquilla/skills/bundled"),
        snapshot_path=tmp_path / "snapshot.json",
    )

    for case_id, skill_name in target_cases.items():
        case = next(case for case in LIFESTYLE_COMPARISON_CASES if case.case_id == case_id)
        english_prompt = ENGLISH_LIFESTYLE_PROMPTS[case_id].lower()
        target = loader.get_by_name(skill_name)
        assert target is not None
        assert any(
            _trigger_matches(trigger, english_prompt)
            for trigger in (target.triggers or [])
        ), f"{case_id} should trigger {skill_name}"
        assert case.prompt


def test_account_watch_outranks_daily_brief_for_competitor_followup_prompts(
    tmp_path: Path,
) -> None:
    account_plan = _bundled_meta_plan("meta-account-watch", tmp_path)
    daily_plan = _bundled_meta_plan("meta-daily-operator-brief", tmp_path)

    assert account_plan.priority > daily_plan.priority


def test_account_watch_prompt_resolves_ahead_of_daily_brief(tmp_path: Path) -> None:
    from opensquilla.engine.steps.meta_resolution import _trigger_matches

    prompt = next(
        case.prompt
        for case in LIFESTYLE_COMPARISON_CASES
        if case.case_id == "account_watch_competitor_week"
    )
    loader = SkillLoader(
        bundled_dir=Path("src/opensquilla/skills/bundled"),
        snapshot_path=tmp_path / "snapshot.json",
    )

    matches = []
    for skill_name in ("meta-account-watch", "meta-daily-operator-brief"):
        spec = loader.get_by_name(skill_name)
        assert spec is not None
        plan = parse_meta_plan(spec)
        assert plan is not None
        trigger = next(
            (
                trigger
                for trigger in spec.triggers
                if _trigger_matches(trigger, prompt.lower())
            ),
            "",
        )
        if trigger:
            matches.append((plan.priority, plan.name, trigger))

    matches.sort(key=lambda item: (-item[0], item[1]))

    assert matches
    assert matches[0][1] == "meta-account-watch"


def test_kid_project_preferences_do_not_block_on_optional_context() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-kid-project-planner/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "If the request already includes a project topic, child age or age" in raw
    assert "NEEDS_CLARIFICATION: no and MISSING_FIELDS: none" in raw
    assert "Budget, exact presentation format, exact weather, and exact" in raw
    assert "proceed with explicit assumptions" in raw


def test_kid_project_planner_removes_heavy_default_export_paths(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-kid-project-planner", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}

    removed_heavy_steps = {
        "web_research",
        "project_fact_ledger",
        "project_core",
        "deep_research",
        "outline_steps",
        "material_list",
        "safety_notes",
        "learning_objectives",
        "vocab_cards",
        "deliver_project_pack",
        "project_pack_audit",
    }

    assert plan.final_text_mode == "step:project_pack"
    assert removed_heavy_steps.isdisjoint(step_by_id)
    assert step_by_id["project_route"].kind == "llm_classify"
    assert step_by_id["project_route"].output_choices == (
        "LIGHT_PROJECT_PACK",
        "HEAVY_PROJECT_PACK",
    )
    assert step_by_id["quick_reference"].kind == "skill_exec"
    assert step_by_id["quick_reference"].skill == "multi-search-engine"
    assert step_by_id["quick_reference"].with_args["max_results"] == 3
    assert step_by_id["quick_reference"].with_args["engines"] == ["duckduckgo"]
    assert step_by_id["heavy_research"].kind == "skill_exec"
    assert step_by_id["heavy_research"].skill == "multi-search-engine"
    assert "HEAVY_PROJECT_PACK" in (step_by_id["heavy_research"].when or "")
    assert step_by_id["weather_check"].kind == "skill_exec"
    assert step_by_id["weather_check"].skill == "weather"
    assert "HEAVY_PROJECT_PACK" in (step_by_id["weather_check"].when or "")
    assert step_by_id["kid_deck"].kind == "skill_exec"
    assert step_by_id["kid_deck"].skill == "pptx"
    assert "HEAVY_PROJECT_PACK" in (step_by_id["kid_deck"].when or "")

    final_text = json.dumps(step_by_id["project_pack"].with_args, ensure_ascii=False)
    assert "full pack" in final_text
    assert "detailed steps" in final_text
    assert "slide deck" in final_text
    assert "Avoid report-like sections" in final_text
    assert "If Route is HEAVY_PROJECT_PACK" in final_text


def test_kid_project_planner_compact_default_and_visual_generation_contract(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-kid-project-planner", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}

    assert plan.final_text_mode == "step:project_pack"
    assert list(step_by_id) == [
        "preferences",
        "project_clarify",
        "feasibility",
        "project_route",
        "redirect_unsafe",
        "recall_past_projects",
        "recall_past_projects_fallback",
        "quick_reference",
        "quick_reference_fallback",
        "heavy_research",
        "heavy_research_fallback",
        "weather_location",
        "weather_check",
        "weather_check_fallback",
        "project_pack",
        "visual_brief",
        "kid_deck",
        "kid_deck_fallback",
        "project_illustration",
        "project_illustration_fallback",
        "store_project",
        "store_project_fallback",
    ]

    project_pack = step_by_id["project_pack"]
    assert project_pack.kind == "llm_chat"
    assert "preferences" in project_pack.depends_on
    assert "feasibility" in project_pack.depends_on
    assert "project_route" in project_pack.depends_on
    assert "recall_past_projects" in project_pack.depends_on
    assert "quick_reference" in project_pack.depends_on
    assert "heavy_research" in project_pack.depends_on
    assert "weather_check" in project_pack.depends_on
    assert "Exactly 3-4 main steps" in json.dumps(project_pack.with_args, ensure_ascii=False)
    assert "350-650 words" in json.dumps(project_pack.with_args, ensure_ascii=False)
    assert "one-evening school projects" in json.dumps(project_pack.with_args, ensure_ascii=False)

    visual_brief = step_by_id["visual_brief"]
    project_illustration = step_by_id["project_illustration"]
    fallback = step_by_id["project_illustration_fallback"]

    assert visual_brief.kind == "llm_chat"
    assert "project_pack" in visual_brief.depends_on
    assert "配图" in (visual_brief.when or "")
    assert "image" in (visual_brief.when or "")
    assert "cover" in (visual_brief.when or "")
    assert "front" in (visual_brief.when or "")
    assert project_illustration.kind == "tool_call"
    assert project_illustration.tool == "image_generate"
    assert project_illustration.tool_allowlist == ("image_generate",)
    assert project_illustration.on_failure == "project_illustration_fallback"
    assert project_illustration.with_args["filename"] == "kid_project_illustration.png"
    assert set(project_illustration.with_args) == {"prompt", "filename"}
    assert "outputs.get('visual_brief'" in project_illustration.with_args["prompt"]
    assert "Generate the child-safe school-project cover illustration" in project_illustration.with_args["prompt"]
    assert fallback.kind == "llm_chat"
    assert "IMAGE_PROMPT_TO_REUSE" in json.dumps(fallback.with_args, ensure_ascii=False)

    final_text = json.dumps(project_pack.with_args, ensure_ascii=False)
    assert "one-evening school-project structure" in final_text
    assert "Exactly 3-4 main steps" in final_text
    assert "use the generated image as the cover/front image" in final_text
    assert "artifact metadata" in final_text
    assert "## Illustration" in final_text
    assert "one-page project card" in final_text
    assert "no dense walls of text" in final_text
    assert "top title, center" in final_text


def test_kid_project_planner_final_audits_original_user_constraints(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-kid-project-planner", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}
    assert plan.final_text_mode == "step:project_pack"
    final_text = json.dumps(step_by_id["project_pack"].with_args, ensure_ascii=False)

    assert step_by_id["recall_past_projects"].kind == "agent"
    assert step_by_id["recall_past_projects"].skill == "memory"
    recall_text = json.dumps(
        step_by_id["recall_past_projects"].with_args,
        ensure_ascii=False,
    )
    assert "Return only remembered facts" in recall_text
    assert "do not curate memory files" in recall_text
    assert "REMEMBERED_PRIOR_PROJECTS" in recall_text
    assert "recall_past_projects" in step_by_id["project_pack"].depends_on
    assert "quick_reference" in step_by_id["project_pack"].depends_on
    assert "{{ inputs.user_message" in final_text
    assert "Durable memory / past-project recall" in final_text
    assert "artifact metadata" in final_text
    assert "file paths" in final_text
    assert "download URLs" in final_text
    assert "print-ready markdown" in final_text
    assert "inline" in final_text
    assert "Preserve every explicit user constraint" in final_text
    assert "age, deadline, available" in final_text
    assert "parent time" in final_text
    assert "Do not invent calendar dates" in final_text
    assert "Prefer a clear comparison design when it fits" in final_text


def test_kid_project_planner_memory_and_weather_are_source_strict(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-kid-project-planner", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}

    recall = step_by_id["recall_past_projects"]
    quick_reference = step_by_id["quick_reference"]
    store_project = step_by_id["store_project"]
    final_text = json.dumps(step_by_id["project_pack"].with_args, ensure_ascii=False)

    assert recall.kind == "agent"
    assert recall.skill == "memory"
    assert "child age, drawing/writing preferences" in json.dumps(
        recall.with_args,
        ensure_ascii=False,
    )
    assert store_project.kind == "agent"
    assert store_project.skill == "memory"
    assert store_project.on_failure == "store_project_fallback"
    assert "remember this project" in (store_project.when or "")
    assert "save this project" in (store_project.when or "")
    assert "archive this project" in (store_project.when or "")
    assert "Do not rewrite the project pack" in json.dumps(
        store_project.with_args,
        ensure_ascii=False,
    )
    assert quick_reference.kind == "skill_exec"
    assert quick_reference.skill == "multi-search-engine"
    assert quick_reference.on_failure == "quick_reference_fallback"
    assert "'weather' in (inputs.user_message | lower)" in (quick_reference.when or "")
    assert "weather day" in (quick_reference.when or "")
    assert "'school' in (inputs.user_message | lower)" in (quick_reference.when or "")
    assert "show-and-tell" in (quick_reference.when or "")
    assert "Lightweight project reference" in final_text
    assert step_by_id["weather_location"].kind == "llm_chat"
    assert "HEAVY_PROJECT_PACK" in (step_by_id["weather_location"].when or "")
    assert step_by_id["weather_check"].skill == "weather"
    assert "DESTINATION: UNKNOWN" in (step_by_id["weather_check"].when or "")
    assert "workspace paths" in final_text
    assert "runtime details" in final_text
    assert "Do not invent exact calendar dates, weather" in final_text


def test_kid_project_planner_triggers_science_project_prompt(tmp_path: Path) -> None:
    loader = SkillLoader(
        bundled_dir=Path("src/opensquilla/skills/bundled"),
        snapshot_path=tmp_path / "snapshot.json",
    )
    results = evaluate_trigger_cases(
        loader,
        [
            TriggerCase(
                name="kid_memory_science_project",
                user_message=(
                    "My child needs to submit a small science project in two weeks. "
                    "Use plant growth as the topic."
                ),
                expected_meta_skill="meta-kid-project-planner",
            )
        ],
    )

    assert results["passed"] == 1
    assert results["failed"] == 0


def test_kid_project_planner_triggers_lifestyle_weather_show_and_tell_prompt(
    tmp_path: Path,
) -> None:
    raw_skill = Path(
        "src/opensquilla/skills/bundled/meta-kid-project-planner/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "show something about the weather" not in raw_skill
    assert "front-cover illustration" not in raw_skill
    assert "weather day" in raw_skill
    assert "show-and-tell" in raw_skill
    assert "class presentation" in raw_skill

    loader = SkillLoader(
        bundled_dir=Path("src/opensquilla/skills/bundled"),
        snapshot_path=tmp_path / "snapshot.json",
    )
    results = evaluate_trigger_cases(
        loader,
        [
            TriggerCase(
                name="kid_lifestyle_weather_show_and_tell",
                user_message=(
                    "My daughter just remembered that tomorrow is "
                    "'show something about the weather' day at school. "
                    "It's already after dinner, so I need something we can "
                    "finish tonight without making a mess. Can you give me a "
                    "very simple project with only a few steps, a tiny sheet "
                    "she can fill in, a few sentences for class, and one cute "
                    "front-cover illustration/image?"
                ),
                expected_meta_skill="meta-kid-project-planner",
            )
        ],
    )

    assert results["passed"] == 1
    assert results["failed"] == 0


def test_kid_project_planner_trigger_surface_avoids_broad_lifestyle_false_positives(
    tmp_path: Path,
) -> None:
    loader = SkillLoader(
        bundled_dir=Path("src/opensquilla/skills/bundled"),
        snapshot_path=tmp_path / "snapshot.json",
    )
    results = evaluate_trigger_cases(
        loader,
        [
            TriggerCase(
                name="adult_class_presentation_due_tomorrow",
                user_message=(
                    "I have a class presentation due tomorrow about quarterly "
                    "revenue. Make the speaker notes concise."
                ),
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="ordinary_weather_question",
                user_message="What's the weather day after tomorrow in Tokyo?",
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="generic_product_poster_image",
                user_message="Create a poster image concept for our product launch.",
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="adult_plant_growth_analysis",
                user_message=(
                    "Compare plant growth models for greenhouse yield forecasting."
                ),
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="kid_generic_artifact_for_school",
                user_message=(
                    "My kid needs to bring one small object to school tomorrow "
                    "and explain it in three sentences."
                ),
                expected_meta_skill="meta-kid-project-planner",
            ),
            TriggerCase(
                name="child_class_presentation_visual",
                user_message=(
                    "My child has a class presentation and needs a simple "
                    "poster with a cute image."
                ),
                expected_meta_skill="meta-kid-project-planner",
            ),
        ],
    )

    assert results["passed"] == results["total"], results["cases"]
    assert results["false_positives"] == 0


def test_kid_project_planner_final_avoids_fake_dates_weather_and_data(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-kid-project-planner", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}
    final_text = json.dumps(step_by_id["project_pack"].with_args, ensure_ascii=False)

    assert "If the user gives only a relative deadline" in final_text
    assert "do not convert it into a calendar date" in final_text
    assert "Do not prefill observation tables with fake measurements" in final_text
    assert "leave measurement cells blank or as placeholders" in final_text
    assert "Do not suggest tasting or eating the experiment materials" in final_text
    assert "Prefer a clear comparison design" in final_text
    assert "same container" in final_text
    assert "Never mention workflow, meta-skill" in final_text
    assert "Return the complete response inline in chat" in final_text


def test_kid_project_planner_printable_defaults_to_inline_markdown() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-kid-project-planner/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "Treat requests for a printable worksheet" in raw
    assert "print-ready markdown included inline" in raw
    assert "Printable\" means a clean markdown table" in raw
    assert "Do not\n            create or refer to PDFs, HTML files, downloads" in raw
    assert "unless the user explicitly asked for a file/PDF/export/download" in raw
    assert "memorable title" in raw
    assert "visual theme" in raw
    assert "drawing-heavy record sheet" in raw
    assert "cover/front image" in raw


def test_lifestyle_prompts_have_english_equivalents_without_benchmark_jargon() -> None:
    rows = build_lifestyle_rows("en")
    prompts = [row["case"]["prompt"] for row in rows]

    assert all(row["case"]["case_id"].endswith("_en") for row in rows)
    assert all("benchmark:" not in prompt.lower() for prompt in prompts)
    assert all("meta-skill" not in prompt.lower() for prompt in prompts)
    assert all("OpenSquilla" not in prompt and "OpenClaw" not in prompt for prompt in prompts)
    assert any("My parents are going to Japan" in prompt for prompt in prompts)
    assert any("messaged yesterday at 16:20" in prompt for prompt in prompts)
    assert any("Xiaohongshu and Dewu" in prompt for prompt in prompts)
    assert any("product operations role" in prompt for prompt in prompts)
    assert any("balcony sprout" in prompt for prompt in prompts)
    assert all("example.invalid" not in prompt for prompt in prompts)


def test_lifestyle_rubrics_reward_meta_specific_artifacts() -> None:
    for case in LIFESTYLE_COMPARISON_CASES:
        assert len(case.rubric) >= 5
        assert case.failure_modes
        assert "Squilla Router" in case.expected_advantage
        assert "Opus 4.7" in case.expected_advantage
        assert "If OpenSquilla does not beat OpenClaw" in case.optimization_if_not_better


def test_lifestyle_score_rewards_strong_answers_over_t3_generic_answers() -> None:
    weak = "可以，建议你按优先级处理。我会列一个简短计划。"
    strong_by_case = {
        "document_vendor_decision": """
        Bottom-line recommendation: negotiate before signing.
        Evidence table: source Quote A, source contract excerpt, due date 2026-06-03,
        amount RMB 18,600, auto-renewal obligation, cancellation penalty.
        Risks ranked high/medium/low. Questions to ask vendor. Next 24 hours.
        Professional-review caveat.
        """,
        "web_research_parent_esim": """
        Assumptions / Decision Context: parents travel to Japan for 8 days.
        Recommendation: buy a travel eSIM plus backup roaming day pass.
        Five Key Findings with sources [S1] [S2] and URL https://example.com.
        Practical Risks / Tradeoffs: activation, hotspot, support, refund.
        Evidence Limits. Next Steps. Sources.
        """,
        "daily_operator_morning_plan": """
        Top 3 priorities. Calendar/task risks. Weather/commute implications.
        Follow up with Li and finance. Time blocks 09:00, 11:00, 15:00.
        Missing connector/data limits. Optional reminders.
        """,
        "account_watch_competitor_week": """
        Account scope: Xiaohongshu and Dewu. Signal table by account and dimension:
        pricing, product, hiring, partnerships. Baseline diff: new / changed /
        unchanged. Strength verdict HIGH / MED / LOW. Next actions for sales/BD.
        Source limits and unknowns.
        """,
        "job_search_tailor_pack": """
        Target role: product operations. Fit thesis. Tailored resume bullets
        based only on SQL retention, onboarding, help docs, and AI pilot evidence.
        Cover letter. JD requirements / evidence / gap table. Interview prep.
        Do not invent experience.
        """,
        "kid_project_balcony_plants": """
        Age fit for an 8-year-old. Daily step plan and timeline.
        Materials, budget, substitutes. Safety and adult supervision.
        Learning objectives, data recording, charts, presentation plan.
        Weather/light assumptions and deadline constraints.
        """,
    }

    for case in LIFESTYLE_COMPARISON_CASES:
        assert score_response(
            strong_by_case[case.case_id], case
        ).total > score_response(weak, case).total


def test_lifestyle_report_labels_openclaw_t3_opus_baseline() -> None:
    rows = build_lifestyle_rows()
    markdown = render_lifestyle_markdown(rows)
    prompts = render_lifestyle_prompts_markdown(rows)

    assert "# OpenSquilla Meta-Skills vs OpenClaw t3 Matched-Skills Lifestyle Benchmark" in markdown
    assert "OpenSquilla + Squilla Router" in markdown
    assert "OpenClaw + t3 + capability-equivalent normal skills baseline" in markdown
    assert "multi-search-engine" in markdown
    assert "pdf-toolkit" in markdown
    assert "docx -> OpenClaw word-docx" in markdown
    assert "deep-research -> OpenClaw deep-research-pro" in markdown
    assert OPENCLAW_T3_MODEL in markdown
    assert "# Lifestyle Test Prompts" in prompts
    assert "OpenSquilla" not in prompts
    assert "OpenClaw" not in prompts
    assert "Benchmark constraints" not in prompts
    assert "Meta-skill:" not in prompts
    assert "Expected advantage:" not in prompts
    assert all(row["openclaw"]["model"] == OPENCLAW_T3_MODEL for row in rows)


def test_lifestyle_report_surfaces_models_and_judge_scores() -> None:
    rows = build_lifestyle_rows()
    row = rows[0]
    row["opensquilla"]["model"] = "deepseek/deepseek-v4-flash-20260423"
    row["openclaw"]["model"] = OPENCLAW_T3_MODEL
    row["score_basis"] = "llm_judge"
    row["winner"] = "opensquilla"
    row["judge"] = {
        "scores": {"opensquilla": 91, "openclaw": 87},
        "confidence": 0.81,
        "rationale": "OpenSquilla has the better final artifact.",
        "raw": {
            "subscores": {
                "opensquilla": {"final_artifact_quality": 38},
                "openclaw": {"final_artifact_quality": 34},
            }
        },
    }

    markdown = render_lifestyle_markdown(rows)

    assert "OpenSquilla model" in markdown
    assert "Judge 0-100" in markdown
    assert "Final artifact" in markdown
    assert "deepseek/deepseek-v4-flash-20260423" in markdown
    assert "91-87" in markdown
    assert "38-34" in markdown


def test_lifestyle_judge_result_requires_subscores_and_rationale() -> None:
    incomplete = JudgeResult(
        winner="openclaw",
        scores={"opensquilla": 78, "openclaw": 83},
        confidence=0.0,
        rationale="",
        risks=[],
        raw={"opensquilla": 78, "openclaw": 83},
        model="judge-model",
    )
    complete = JudgeResult(
        winner="opensquilla",
        scores={"opensquilla": 91, "openclaw": 87},
        confidence=0.8,
        rationale="OpenSquilla has the better final artifact.",
        risks=[],
        raw={
            "subscores": {
                "opensquilla": {
                    "final_artifact_quality": 38,
                    "task_completion": 19,
                    "evidence_traceability": 14,
                    "actionability": 9,
                    "risk_boundary_safety": 8,
                    "meta_skill_fit": 3,
                },
                "openclaw": {
                    "final_artifact_quality": 34,
                    "task_completion": 18,
                    "evidence_traceability": 13,
                    "actionability": 8,
                    "risk_boundary_safety": 9,
                    "meta_skill_fit": 5,
                },
            }
        },
        model="judge-model",
    )

    assert _lifestyle_judge_result_is_complete(incomplete) is False
    assert _lifestyle_judge_result_is_complete(complete) is True


def test_lifestyle_judge_scores_are_recomputed_from_weighted_subscores() -> None:
    case = LIFESTYLE_COMPARISON_CASES[0]
    opensquilla = EndpointResult(
        endpoint="opensquilla",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="strong answer",
        score={"total": 1},
    )
    openclaw = EndpointResult(
        endpoint="openclaw",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="baseline answer",
        score={"total": 1},
        model=OPENCLAW_T3_MODEL,
    )
    row = _compare_results(case, opensquilla, openclaw)
    judge = JudgeResult(
        winner="openclaw",
        scores={"opensquilla": 0, "openclaw": 100},
        confidence=0.9,
        rationale="OpenSquilla has the better weighted final artifact.",
        risks=[],
        raw={
            "subscores": {
                "opensquilla": {
                    "final_artifact_quality": 40,
                    "task_completion": 20,
                    "evidence_traceability": 15,
                    "actionability": 10,
                    "risk_boundary_safety": 10,
                    "meta_skill_fit": 5,
                },
                "openclaw": {
                    "final_artifact_quality": 30,
                    "task_completion": 20,
                    "evidence_traceability": 15,
                    "actionability": 10,
                    "risk_boundary_safety": 10,
                    "meta_skill_fit": 5,
                },
            }
        },
        model="judge-model",
    )

    updated = _apply_lifestyle_judge_result(row, judge, case)

    assert updated["judge"]["scores"] == {"opensquilla": 100, "openclaw": 90}
    assert updated["winner"] == "opensquilla"
    assert updated["judge"]["raw"]["score_source"] == "weighted_subscores"


def test_lifestyle_judge_retries_until_weighted_payload_is_complete() -> None:
    case = LIFESTYLE_COMPARISON_CASES[0]
    opensquilla = EndpointResult(
        endpoint="opensquilla",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="strong answer",
        score={"total": 1},
    )
    openclaw = EndpointResult(
        endpoint="openclaw",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="baseline answer",
        score={"total": 1},
        model=OPENCLAW_T3_MODEL,
    )

    class FakeJudge:
        def __init__(self) -> None:
            self.calls = 0

        async def judge(self, *_args):
            self.calls += 1
            if self.calls == 1:
                return JudgeResult(
                    winner="openclaw",
                    scores={"opensquilla": 10, "openclaw": 20},
                    confidence=0.1,
                    rationale="missing subscores",
                    risks=[],
                    raw={},
                    model="judge-model",
                )
            return JudgeResult(
                winner="openclaw",
                scores={"opensquilla": 10, "openclaw": 20},
                confidence=0.9,
                rationale="complete weighted payload",
                risks=[],
                raw={
                    "subscores": {
                        "opensquilla": {
                            "final_artifact_quality": 40,
                            "task_completion": 20,
                            "evidence_traceability": 15,
                            "actionability": 10,
                            "risk_boundary_safety": 10,
                            "meta_skill_fit": 5,
                        },
                        "openclaw": {
                            "final_artifact_quality": 30,
                            "task_completion": 20,
                            "evidence_traceability": 15,
                            "actionability": 10,
                            "risk_boundary_safety": 10,
                            "meta_skill_fit": 5,
                        },
                    }
                },
                model="judge-model",
            )

    fake = FakeJudge()
    result = asyncio.run(
        _judge_lifestyle_with_retries(fake, case, opensquilla, openclaw)  # type: ignore[arg-type]
    )

    assert fake.calls == 2
    assert result.scores == {"opensquilla": 100, "openclaw": 90}


def test_lifestyle_judge_existing_rejudges_jsonl_with_weighted_scores(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = LIFESTYLE_COMPARISON_CASES[0]
    report = tmp_path / "existing.jsonl"
    row = _compare_results(
        case,
        EndpointResult(
            endpoint="opensquilla",
            case_id=case.case_id,
            ok=True,
            elapsed_s=1.0,
            response_text="strong answer",
            score={"total": 1},
        ),
        EndpointResult(
            endpoint="openclaw",
            case_id=case.case_id,
            ok=True,
            elapsed_s=1.0,
            response_text="baseline answer",
            score={"total": 1},
            model=OPENCLAW_T3_MODEL,
        ),
    )
    report.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    captured: dict[str, list[dict]] = {}

    class FakeJudge:
        def __init__(self, **_kwargs) -> None:
            pass

        async def judge(self, *_args):
            return JudgeResult(
                winner="openclaw",
                scores={"opensquilla": 0, "openclaw": 100},
                confidence=0.9,
                rationale="complete weighted payload",
                risks=[],
                raw={
                    "subscores": {
                        "opensquilla": {
                            "final_artifact_quality": 40,
                            "task_completion": 20,
                            "evidence_traceability": 15,
                            "actionability": 10,
                            "risk_boundary_safety": 10,
                            "meta_skill_fit": 5,
                        },
                        "openclaw": {
                            "final_artifact_quality": 30,
                            "task_completion": 20,
                            "evidence_traceability": 15,
                            "actionability": 10,
                            "risk_boundary_safety": 10,
                            "meta_skill_fit": 5,
                        },
                    }
                },
                model="judge-model",
            )

    def fake_write(rows, stamp=None):
        captured["rows"] = rows
        return tmp_path / "out.jsonl", tmp_path / "out.md"

    monkeypatch.setattr(
        "scripts.compare_meta_skill_openclaw_lifestyle.LLMJudge",
        FakeJudge,
    )
    monkeypatch.setattr(
        "scripts.compare_meta_skill_openclaw_lifestyle.write_lifestyle_reports",
        fake_write,
    )
    args = type(
        "Args",
        (),
        {
            "judge_jsonl": str(report),
            "judge_model": "judge-model",
            "judge_api_key": "x",
            "judge_base_url": "http://judge",
            "judge_timeout": 1.0,
        },
    )()

    asyncio.run(judge_existing(args))

    judged = captured["rows"][0]
    assert judged["winner"] == "opensquilla"
    assert judged["judge"]["scores"] == {"opensquilla": 100, "openclaw": 90}


def test_lifestyle_comparison_marks_endpoint_failure_invalid_not_win() -> None:
    case = LIFESTYLE_COMPARISON_CASES[0]
    opensquilla = EndpointResult(
        endpoint="opensquilla",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="rich answer",
        score={"total": 6},
    )
    openclaw = EndpointResult(
        endpoint="openclaw",
        case_id=case.case_id,
        ok=False,
        elapsed_s=1.0,
        response_text="",
        score={"total": 0},
        error="401 Missing Authentication header",
        model=OPENCLAW_T3_MODEL,
    )

    row = _compare_results(case, opensquilla, openclaw)

    assert row["winner"] == "invalid"
    assert row["score_basis"] == "invalid_endpoint"
    assert row["opensquilla_better"] is False
    assert row["recommended_optimization"] is None


def test_lifestyle_comparison_marks_bootstrap_response_invalid_not_win() -> None:
    case = LIFESTYLE_COMPARISON_CASES[0]
    opensquilla = EndpointResult(
        endpoint="opensquilla",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="rich answer",
        score={"total": 6},
    )
    openclaw = EndpointResult(
        endpoint="openclaw",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="Bootstrap removed. Ready for the task — what would you like me to do?",
        score={"total": 0},
        model=OPENCLAW_T3_MODEL,
    )

    row = _compare_results(case, opensquilla, openclaw)

    assert row["winner"] == "invalid"
    assert row["score_basis"] == "invalid_endpoint"
    assert row["opensquilla_better"] is False
    assert "openclaw: unrelated bootstrap response" in row["invalid_reasons"]


def test_lifestyle_comparison_only_scores_when_both_endpoints_are_valid() -> None:
    case = LIFESTYLE_COMPARISON_CASES[0]
    opensquilla = EndpointResult(
        endpoint="opensquilla",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="rich answer",
        score={"total": 6},
    )
    openclaw = EndpointResult(
        endpoint="openclaw",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="baseline answer",
        score={"total": 4},
        model=OPENCLAW_T3_MODEL,
    )

    row = _compare_results(case, opensquilla, openclaw)

    assert row["winner"] == "opensquilla"
    assert row["score_basis"] == "deterministic"
    assert row["opensquilla_better"] is True


def test_opensquilla_runner_can_isolate_agent_per_case() -> None:
    runner = OpenSquillaRunner(
        "ws://example/ws",
        token=None,
        agent_id="main",
        isolated_agent_per_case=True,
        run_id="testrun",
    )
    first = runner._agent_id_for_case(LIFESTYLE_COMPARISON_CASES[0])
    second = runner._agent_id_for_case(LIFESTYLE_COMPARISON_CASES[1])

    assert first == "meta-compare-testrun-document-vendor-decision"
    assert second == "meta-compare-testrun-web-research-parent-esim"
    assert first != second
    assert first != "main"


def test_load_openclaw_baseline_refreshes_final_text_from_state(
    tmp_path: Path,
) -> None:
    case = LIFESTYLE_COMPARISON_CASES[0]
    state_dir = tmp_path / "openclaw"
    sessions_dir = state_dir / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    session_key = "agent:main:dashboard:test"
    session_file = sessions_dir / "abc.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"'
                + case.prompt
                + '"}]}}',
                (
                    '{"type":"message","message":{"role":"assistant","content":'
                    '[{"type":"text","text":"final openclaw baseline answer with '
                    '风险 证据表 24 小时"}]}}'
                ),
            ]
        ),
        encoding="utf-8",
    )
    (sessions_dir / "abc.trajectory.jsonl").write_text(
        f'{{"sessionKey":"{session_key}"}}\n',
        encoding="utf-8",
    )
    report = tmp_path / "baseline.jsonl"
    row = {
        "case": {"case_id": case.case_id, "prompt": case.prompt},
        "openclaw": {
            "endpoint": "openclaw",
            "case_id": case.case_id,
            "ok": True,
            "elapsed_s": 1.0,
            "response_text": "checking sources",
            "score": {"total": 0},
            "session_key": session_key,
            "model": OPENCLAW_T3_MODEL,
        },
    }
    report.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    baseline = load_openclaw_baseline(report, [case], state_dir=state_dir)

    assert baseline[case.case_id].response_text.startswith("final openclaw baseline")
    assert baseline[case.case_id].ok is True


def test_load_openclaw_baseline_rejects_prompt_mismatch(tmp_path: Path) -> None:
    case = LIFESTYLE_COMPARISON_CASES[0]
    report = tmp_path / "baseline.jsonl"
    row = {
        "case": {"case_id": case.case_id, "prompt": "changed prompt"},
        "openclaw": {
            "endpoint": "openclaw",
            "case_id": case.case_id,
            "ok": True,
            "elapsed_s": 1.0,
            "response_text": "baseline answer",
            "score": {"total": 1},
            "model": OPENCLAW_T3_MODEL,
        },
    }
    report.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    try:
        load_openclaw_baseline(report, [case])
    except SystemExit as exc:
        assert "baseline prompt mismatch" in str(exc)
    else:
        raise AssertionError("expected prompt mismatch to fail")
