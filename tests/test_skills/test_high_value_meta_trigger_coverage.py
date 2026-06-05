from __future__ import annotations

from pathlib import Path

from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.trigger_accuracy import TriggerCase, evaluate_trigger_cases

SKILLS_DIR = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills"
BUNDLED = SKILLS_DIR / "bundled"
EXP = SKILLS_DIR / "exp"


def test_high_value_meta_skills_match_natural_user_prompts(tmp_path: Path) -> None:
    loader = SkillLoader(
        bundled_dir=BUNDLED,
        extra_dirs=[EXP],
        snapshot_path=tmp_path / "snap.json",
    )
    loader.invalidate_cache()

    report = evaluate_trigger_cases(
        loader,
        [
            TriggerCase(
                name="stack_trace_traceback",
                user_message=(
                    "This traceback is failing with KeyError result. Can you "
                    "figure out why and give me patch targets plus verification "
                    "commands?\n\nTraceback (most recent call last):\n"
                    "  File \"src/agent/runtime.py\", line 88, in run_step\n"
                    "    payload = parse_tool_result(raw)\n"
                    "KeyError: 'result'"
                ),
                expected_meta_skill="meta-stack-trace-investigator",
            ),
            TriggerCase(
                name="travel_natural_cn",
                user_message="我和对象六月底第一次去东京，帮我安排三天怎么玩。",
                expected_meta_skill="meta-travel-planner",
            ),
            TriggerCase(
                name="web_research_lifelike",
                user_message=(
                    "Can you look into local-first AI coding assistants and produce a "
                    "source-backed writeup of the findings for our CTO?"
                ),
                expected_meta_skill="meta-web-research-to-report",
            ),
            TriggerCase(
                name="paper_manuscript",
                user_message=(
                    "I need an academic manuscript about meta-skill "
                    "orchestration with enough citations for a workshop draft."
                ),
                expected_meta_skill="meta-paper-write",
            ),
            TriggerCase(
                name="pdf_comparison",
                user_message="Can you compare these PDFs and give me page-backed findings?",
                expected_meta_skill="meta-pdf-intelligence",
            ),
            TriggerCase(
                name="creator_explicit_orchestration",
                user_message=(
                    "Create a meta-skill that orchestrates search, PDF analysis, "
                    "and report writing into one workflow."
                ),
                expected_meta_skill="meta-skill-creator",
            ),
            TriggerCase(
                name="creator_plain_meta_skill_request",
                user_message="Create a meta-skill for my weekly research pipeline.",
                expected_meta_skill="meta-skill-creator",
            ),
            TriggerCase(
                name="migration_cjs_to_esm_natural",
                user_message=(
                    "We're planning to migrate a small frontend package from "
                    "CommonJS to native ESM next sprint. Please give me a "
                    "practical migration checklist with rollout risks."
                ),
                expected_meta_skill="meta-migration-assistant",
            ),
        ],
    )

    failures = [case for case in report["cases"] if not case["passed"]]
    assert failures == []


def test_stable_bundled_meta_skills_do_not_match_neighboring_prompts(
    tmp_path: Path,
) -> None:
    loader = SkillLoader(
        bundled_dir=BUNDLED,
        snapshot_path=tmp_path / "stable-negative-snap.json",
    )
    loader.invalidate_cache()

    report = evaluate_trigger_cases(
        loader,
        [
            TriggerCase(
                name="web_research_decision_memo_without_web",
                user_message=(
                    "Write a decision memo from these notes, no web research "
                    "or citations needed."
                ),
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="daily_operator_single_reminder",
                user_message="Today plan: remind me to call Alex at 4pm.",
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="document_generic_contract_excerpt",
                user_message=(
                    "Summarize this contract excerpt generally; I am not "
                    "deciding whether to sign."
                ),
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="job_search_generic_career_advice_cn",
                user_message="给我一些通用求职准备建议，不针对任何岗位或JD。",
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="kid_project_adult_logo_craft_cn",
                user_message="帮我做一个手工 logo 的创意说明，不是孩子作业。",
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="kid_project_science_fair_explanation",
                user_message="Explain the science fair format.",
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="paper_long_form_non_research",
                user_message=(
                    "Write a long-form paper airplane guide for a craft blog."
                ),
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="creator_historical_orchestrates_search",
                user_message=(
                    "This old workflow orchestrates search and summarize; "
                    "analyze its failure modes."
                ),
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="competitive_intel_account_support",
                user_message="Watch this account login issue and tell support.",
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="competitive_intel_single_company_profile_cn",
                user_message=(
                    "inception labs,创始团队和核心员工有哪些？现在估值，"
                    "核心技术路线和进展是啥？然后每一轮交割大概节奏和"
                    "估值股东等信息列出来。"
                ),
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="short_drama_script_only",
                user_message="Write a short script idea, not a video or MP4.",
                expected_meta_skill=None,
            ),
        ],
    )

    failures = [case for case in report["cases"] if not case["passed"]]
    assert failures == []


def test_competitive_intel_description_avoids_single_company_research_pull(
    tmp_path: Path,
) -> None:
    loader = SkillLoader(
        bundled_dir=BUNDLED,
        snapshot_path=tmp_path / "competitive-intel-description-snap.json",
    )
    loader.invalidate_cache()
    spec = loader.get_by_name("meta-competitive-intel")
    assert spec is not None

    description = (spec.description or "").lower()

    assert "defined company" not in description
    assert "leadership, hiring, partnerships, funding" not in description
    assert "competitive-intel monitoring" in description
    assert "baseline" in description
    assert "ordinary company profiles" not in description
