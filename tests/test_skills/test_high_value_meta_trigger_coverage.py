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
                    "Can you look into local-first AI coding assistants and "
                    "write up the findings for our CTO?"
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
