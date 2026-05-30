import asyncio
import json
from scripts.compare_meta_skill_openclaw_lifestyle import (
    OPENCLAW_T3_MODEL,
    LIFESTYLE_COMPARISON_CASES,
    _lifestyle_judge_result_is_complete,
    _compare_results,
    _apply_lifestyle_judge_result,
    _judge_lifestyle_with_retries,
    judge_existing,
    load_openclaw_baseline,
    build_lifestyle_rows,
    render_lifestyle_markdown,
    render_lifestyle_prompts_markdown,
    score_response,
)
from scripts.compare_meta_skill_openclaw import EndpointResult, JudgeResult, OpenSquillaRunner
from pathlib import Path

from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.templating import evaluate_when


SELECTED_SKILLS = [
    "meta-document-to-decision",
    "meta-web-research-to-report",
    "meta-daily-operator-brief",
    "meta-safe-skill-installer",
    "meta-family-day-coordinator",
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
        "safe_skill_install_audit",
        "family_school_errand_day",
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
        "meta-safe-skill-installer": ["Skill Vetter", "Find Skills Skill", "Multi Search Engine"],
        "meta-family-day-coordinator": ["Weather", "Elite Longterm Memory", "Caldav Calendar"],
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
        "meta-family-day-coordinator": """
DATE_SCOPE: tomorrow
LOCATION: Hangzhou
FIXED_EVENTS:
  - pickup at 17:00
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
        "meta-family-day-coordinator": ("family_memory", "family_memory_fallback"),
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
            "final": "deliver_project_pack",
            "fallbacks": {
                "recall_past_projects": "recall_past_projects_fallback",
                "web_research": "web_research_fallback",
                "weather_check": "weather_check_fallback",
            },
            "required": ["Record and chart", "Weather / light adjustment", "Final presentation"],
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
        "meta-family-day-coordinator": {
            "final": "family_plan_audit",
            "fallbacks": {
                "family_memory": "family_memory_fallback",
                "weather": "weather_fallback",
            },
            "required": [
                "Pickup, Dropoff & Errands / 接送和跑腿",
                "Meals, Health & Sleep / 吃饭健康睡眠",
                "Data limits / 数据限制",
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

    assert "Do not default Chinese user requests to English" in raw
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

    assert "Do not derive cancellation deadlines by subtracting days from invoice or payment due dates" in raw
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
    assert "Never mention workflow, meta-skill, tool names, connector failures, workspace paths, or runtime details" in raw
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
    assert "Do not mention HTTP status codes, API failures, connector stack traces, or search errors" in raw
    assert "When live data is unavailable, summarize only the user-facing limit" in raw
    assert "Clear one-minute social debts before deep work when they unblock other people" in raw
    assert "include ready-to-send message drafts" in raw
    assert "overdue school, caregiver, vendor, HR, finance, or customer replies" in raw
    assert "clear them in the first 15 minutes" in raw
    assert "teacher / 老师 replies that were sent yesterday must be cleared in the first 15 minutes" not in raw
    assert "Do not rely on remembered or previous-day weather" in raw
    assert "live weather not verified" in raw
    assert "ready-to-send drafts for named recipients or roles" in raw
    assert "examples include school, caregiver, HR, finance, customer, vendor, and quote replies" in raw
    assert "drafts for teacher, HR, finance, customer, and quote replies" not in raw


def test_safe_skill_installer_uses_valid_isolated_audit_commands() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-safe-skill-installer/SKILL.md"
    ).read_text(encoding="utf-8")

    assert 'final_text_mode: "step:safety_decision_audit"' in raw
    assert "pasted_evidence" in raw
    assert "Build a source-of-truth evidence ledger" in raw
    assert "Never show invalid container flags such as --network=host=NO" in raw
    assert "Use --network=none for offline container inspection" in raw
    assert "download without executing" in raw
    assert "do not run bash install.sh until static review passes" in raw
    assert "Do not say the domain is unreachable" in raw
    assert "Keep the final answer concise enough to finish in one turn" in raw
    assert "Do not include a long incident-response runbook unless the user says it was already installed" in raw
    assert "For not-yet-installed tools, keep rollback to pre-install backup and what to rotate if accidentally run" in raw


def test_safe_skill_installer_keeps_source_evidence_boundaries_upstream() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-safe-skill-installer/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "Treat the pasted evidence ledger as the primary source of truth" in raw
    assert "Do not audit the meta-skill's own \"sub-agent\" machinery" in raw
    assert "Apply this evidence boundary in every step, not only the final answer" in raw
    assert "Search failure, missing lookup output, or absent public reputation is not proof of NXDOMAIN" in raw
    assert "Do not call a domain dead, unreachable, unresolvable, NXDOMAIN, or verified-bad" in raw
    assert "Source inspection must pass through only visible evidence and unknowns" in raw
    assert "Vetting and backup steps must not add new reputation or DNS claims" in raw
    assert "Download commands are for isolated audit only and must not be run on the real machine" in raw
    assert "Do not expose tool parameter errors, fetch failures, connector wording, or internal audit mechanics" in raw
    assert "Do not claim zero public footprint, no GitHub record, or no security-community record" in raw
    assert "unless the output cites the checked sources or says these checks were not verified" in raw


def test_lifestyle_meta_skills_have_natural_language_activation_cues() -> None:
    expectations = {
        "meta-document-to-decision": ["供应商续费", "要不要签"],
        "meta-daily-operator-brief": ["今天先帮我排一下", "前三优先级"],
        "meta-safe-skill-installer": ["这个插件能不能装", "curl -fsSL"],
        "meta-account-watch": ["盯一下这两个对手", "销售群里的简报", "和基线相比"],
    }

    for skill_name, cues in expectations.items():
        raw = Path(f"src/opensquilla/skills/bundled/{skill_name}/SKILL.md").read_text(
            encoding="utf-8"
        )
        for cue in cues:
            assert cue in raw


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


def test_family_day_coordinator_prioritizes_realistic_parent_schedule() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-family-day-coordinator/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "tonight / before-bed prep pass" in raw
    assert 'final_text_mode: "step:family_plan_audit"' in raw
    assert "family_plan_audit" in raw
    assert "Return the complete final plan inline in chat" in raw
    assert "Do not create, save, export, attach" in raw
    assert "Never mention workflow, meta-skill, tool names" in raw
    assert "path/workspace/meta-skill/weather problem" in raw
    assert "Never compress errands into the" in raw
    assert "pre-dropoff window" in raw
    assert "dropoff first" in raw
    assert "live weather was not verified" in raw
    assert "without runtime/tool chatter" in raw
    assert "Allergy guidance should be operational" in raw
    assert "without inventing prescriptions, medicine names, dosage, or allergy severity" in raw
    assert "Do not upgrade \"peanut allergy / 花生过敏\" into \"severe allergy" in raw
    assert "Do not name allergy medicines, emergency injectors, drug classes" in raw
    assert "按医生/家庭既有方案准备已开具的过敏药物或应急用品" in raw
    assert "Pickup, Dropoff & Errands / 接送和跑腿" in raw
    assert "Reminders / 要提醒谁" in raw
    assert "only pasted / 仅根据" in raw


def test_kid_project_preferences_do_not_block_on_optional_context() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-kid-project-planner/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "If the request already includes a project topic, child age or age" in raw
    assert "NEEDS_CLARIFICATION: no and MISSING_FIELDS: none" in raw
    assert "Budget, exact presentation format, exact weather, and exact" in raw
    assert "proceed with explicit assumptions" in raw


def test_kid_project_planner_only_generates_vocab_when_explicitly_requested(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-kid-project-planner", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}

    vocab_when = step_by_id["vocab_cards"].when or ""
    assert "vocab" in vocab_when
    assert "bilingual" in vocab_when
    assert "英语" in vocab_when
    assert "双语" in vocab_when
    assert "单词" in vocab_when

    final_text = json.dumps(step_by_id["deliver_project_pack"].with_args, ensure_ascii=False)
    assert "Do not include vocabulary cards unless the user explicitly asked" in final_text
    assert "For Chinese requests, do not use English section headings" in final_text
    assert "do not copy intermediate outputs verbatim" in final_text
    assert "1800-3200 Chinese characters" in final_text


def test_kid_project_planner_final_audits_original_user_constraints(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-kid-project-planner", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}
    assert plan.final_text_mode == "step:project_pack_audit"
    final_text = json.dumps(step_by_id["deliver_project_pack"].with_args, ensure_ascii=False)
    audit_text = json.dumps(step_by_id["project_pack_audit"].with_args, ensure_ascii=False)

    assert "project_fact_ledger" in step_by_id
    assert "project_fact_ledger" in step_by_id["deliver_project_pack"].depends_on
    assert "deliver_project_pack" in step_by_id["project_pack_audit"].depends_on
    assert "project_fact_ledger" in step_by_id["project_pack_audit"].depends_on
    assert "{{ inputs.user_message" in final_text
    assert "Project fact ledger" in final_text
    assert "Project fact ledger" in audit_text
    assert "Preserve every explicit user constraint" in final_text
    assert "age, deadline, location, available materials, budget" in final_text
    assert "parent time, light/weather constraints" in final_text
    assert "Do not invent calendar dates" in final_text
    assert "Do not replace user-provided materials" in final_text
    assert "Design a comparison experiment when it fits the project" in final_text


def test_kid_project_planner_final_avoids_fake_dates_weather_and_data(
    tmp_path: Path,
) -> None:
    plan = _bundled_meta_plan("meta-kid-project-planner", tmp_path)
    step_by_id = {step.id: step for step in plan.steps}
    final_text = json.dumps(step_by_id["deliver_project_pack"].with_args, ensure_ascii=False)
    audit_text = json.dumps(step_by_id["project_pack_audit"].with_args, ensure_ascii=False)

    assert "If the user gives only a relative deadline" in final_text
    assert "do not convert it into a calendar date" in final_text
    assert "Do not invent balcony direction, temperature ranges" in final_text
    assert "Do not prefill observation tables with fake measurements" in final_text
    assert "leave measurement cells blank or as placeholders" in final_text
    assert "Do not suggest tasting or eating the experiment materials" in final_text
    assert "Prefer a clear comparison design" in final_text
    assert "same seed, cup, water, and paper-towel conditions" in final_text
    assert "If the fact ledger marks a detail UNKNOWN" in final_text
    assert "Remove exact calendar dates, weekdays, months, or current-year references" in audit_text
    assert "Remove fake sample measurements" in audit_text
    assert "Remove invented balcony direction, temperature ranges, rain forecasts" in audit_text
    assert "2500-3600 Chinese characters" in audit_text


def test_safe_skill_installer_avoids_unverified_external_lookup_claims() -> None:
    raw = Path(
        "src/opensquilla/skills/bundled/meta-safe-skill-installer/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "safety_decision_audit" in raw
    assert "If both remote shell installer and secret/account-directory access" in raw
    assert "Never say \"none described\", \"not applicable\", or \"no installer\"" in raw
    assert "source_lookup_fallback" in raw
    assert "external source not verified / 外部来源未验证" in raw
    assert "Do not claim that" in raw
    assert "Never say the domain is unreachable" in raw
    assert "one-line threat model" in raw
    assert "immediate action plan" in raw
    assert "isolated audit recipe" in raw
    assert "what evidence would change the verdict" in raw
    assert "short message the user can send back" in raw
    assert "credential/key rotation" in raw
    assert "safer alternatives" in raw
    assert "infer that a project is not well-known" in raw
    assert "default to reject" in raw


def test_lifestyle_prompts_have_english_equivalents_without_benchmark_jargon() -> None:
    rows = build_lifestyle_rows("en")
    prompts = [row["case"]["prompt"] for row in rows]

    assert all(row["case"]["case_id"].endswith("_en") for row in rows)
    assert all("benchmark:" not in prompt.lower() for prompt in prompts)
    assert all("meta-skill" not in prompt.lower() for prompt in prompts)
    assert all("OpenSquilla" not in prompt and "OpenClaw" not in prompt for prompt in prompts)
    assert any("My parents are going to Japan" in prompt for prompt in prompts)
    assert any("daily report helper" in prompt for prompt in prompts)
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
        "safe_skill_install_audit": """
        VERDICT: audit only.
        Risk table: file access, shell, network, secrets, persistence.
        Suspicious patterns: curl installer, reads ~/.ssh, postinstall.
        Required manual checks. Backup/rollback plan. Unknowns that block trust.
        """,
        "family_school_errand_day": """
        Time-blocked family plan. Pickup/dropoff/errand checklist.
        Weather adjustments. Meal/health/sleep/hydration notes.
        Remind teacher and dad. Optional reminder schedule. Missing data limits.
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
        assert score_response(strong_by_case[case.case_id], case).total > score_response(weak, case).total


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
                '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"final openclaw baseline answer with 风险 证据表 24 小时"}]}}',
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
