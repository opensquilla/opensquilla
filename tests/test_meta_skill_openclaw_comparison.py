from scripts.compare_meta_skill_openclaw import (
    COMPARISON_CASES,
    render_markdown,
    render_prompts_markdown,
    score_response,
)


def test_comparison_catalog_covers_expected_meta_skill_scenarios() -> None:
    assert [case.skill_name for case in COMPARISON_CASES] == [
        "meta-web-research-to-report",
        "meta-paper-write",
        "meta-pdf-intelligence",
        "meta-stack-trace-investigator",
        "meta-travel-planner",
        "meta-skill-creator",
        "meta-migration-assistant",
    ]
    assert len({case.case_id for case in COMPARISON_CASES}) == 7


def test_comparison_prompts_are_conversational_not_benchmark_labels() -> None:
    prompts = [case.prompt for case in COMPARISON_CASES]

    assert all("benchmark:" not in prompt.lower() for prompt in prompts)
    assert any("I need" in prompt or "I'm" in prompt for prompt in prompts)
    assert any("Could you" in prompt for prompt in prompts)


def test_score_response_rewards_structured_evidence_and_artifacts() -> None:
    weak = "Here is a quick answer."
    strong = """
    Summary
    - Finding with source: https://example.com/report
    - Citation [1] and page 3 evidence

    Assumptions
    - budget is moderate

    Verification
    - next command: pytest tests/example.py

    Artifact: report.docx
    """

    weak_score = score_response(weak)
    strong_score = score_response(strong)

    assert strong_score.total > weak_score.total
    assert strong_score.dimensions["structure"] > weak_score.dimensions["structure"]
    assert strong_score.dimensions["evidence"] > weak_score.dimensions["evidence"]
    assert (
        strong_score.dimensions["artifact_readiness"]
        > weak_score.dimensions["artifact_readiness"]
    )


def test_reports_persist_conclusion_and_prompts() -> None:
    row = {
        "case": {
            "case_id": "stack_trace_investigator",
            "skill_name": "meta-stack-trace-investigator",
            "prompt": "Investigate stack trace benchmark",
            "expected_advantage": "structured evidence",
        },
        "opensquilla": {
            "ok": True,
            "elapsed_s": 1.0,
            "event_count": 3,
            "provider": None,
            "model": "model-a",
            "score": {"total": 9},
            "error": None,
        },
        "openclaw": {
            "ok": True,
            "elapsed_s": 2.0,
            "event_count": 4,
            "provider": "openrouter",
            "model": "model-b",
            "score": {"total": 5},
            "error": None,
        },
        "winner": "opensquilla",
        "recommended_optimization": None,
    }

    report = render_markdown([row], jsonl_path="raw.jsonl")
    prompts = render_prompts_markdown([row], jsonl_path="raw.jsonl")

    assert "## Conclusion" in report
    assert "OpenSquilla won 1/1 cases" in report
    assert "Investigate stack trace benchmark" in report
    assert "# OpenClaw vs OpenSquilla Meta-Skill Benchmark Prompts" in prompts
    assert "meta-stack-trace-investigator" in prompts
