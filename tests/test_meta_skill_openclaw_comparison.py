from scripts.compare_meta_skill_openclaw import (
    COMPARISON_CASES,
    EndpointResult,
    JudgeResult,
    _discover_openclaw_session_file,
    _openclaw_session_file_events,
    _resolve_openclaw_session_path,
    apply_judge_result,
    build_judge_prompt,
    compare_results,
    extract_text_from_events,
    parse_judge_response,
    render_markdown,
    render_prompts_markdown,
    score_response,
)


def test_comparison_catalog_covers_expected_meta_skill_scenarios() -> None:
    primary = [case for case in COMPARISON_CASES if case.scenario == "primary"]
    assert [case.skill_name for case in primary] == [
        "meta-web-research-to-report",
        "meta-paper-write",
        "meta-pdf-intelligence",
        "meta-stack-trace-investigator",
        "meta-travel-planner",
        "meta-skill-creator",
        "meta-migration-assistant",
    ]
    assert len({case.case_id for case in COMPARISON_CASES}) == 21
    assert {
        (case.skill_name, case.scenario)
        for case in COMPARISON_CASES
    } >= {
        (skill_name, scenario)
        for skill_name in {case.skill_name for case in primary}
        for scenario in {"primary", "degraded", "boundary"}
    }
    assert all(case.failure_modes for case in COMPARISON_CASES if case.scenario != "primary")


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


def test_extract_text_prefers_terminal_done_over_long_intermediate() -> None:
    events = [
        {
            "event": "session.tool.result",
            "payload": {
                "tool_name": "meta_invoke",
                "data": {"text": "intermediate meta output " * 50},
            },
        },
        {"event": "session.event.done", "payload": {"text": "final answer"}},
    ]

    assert extract_text_from_events(events) == "final answer"


def test_extract_text_prefers_latest_assistant_message_not_longest() -> None:
    events = [
        {
            "event": "session.message",
            "payload": {
                "message": {
                    "role": "assistant",
                    "content": "older assistant draft " * 20,
                }
            },
        },
        {
            "event": "session.message",
            "payload": {
                "message": {
                    "role": "assistant",
                    "content": "latest final assistant message",
                }
            },
        },
    ]

    assert extract_text_from_events(events) == "latest final assistant message"


def test_extract_text_ignores_toolish_text_when_final_assistant_exists() -> None:
    events = [
        {
            "event": "session.message",
            "payload": {
                "message": {"role": "tool", "content": "tool output " * 20}
            },
        },
        {
            "event": "session.message",
            "payload": {
                "message": {"role": "assistant", "content": "visible answer"}
            },
        },
    ]

    assert extract_text_from_events(events) == "visible answer"


def test_openclaw_session_file_fallback_discovers_and_extracts_final_text(tmp_path) -> None:
    sessions_dir = tmp_path / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    session_file = sessions_dir / "abc.jsonl"
    prompt = "Benchmark constraints: return inline.\n\nNeed a memo."
    session_file.write_text(
        "\n".join(
            [
                '{"type":"session","id":"abc"}',
                '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"'
                + prompt.replace("\n", "\\n")
                + '"}]}}',
                (
                    '{"type":"message","message":{"role":"assistant","content":'
                    '[{"type":"thinking","thinking":"draft"},'
                    '{"type":"text","text":"final memo answer"}]}}'
                ),
            ]
        ),
        encoding="utf-8",
    )

    found = _discover_openclaw_session_file(
        tmp_path,
        session_key="agent:main:dashboard:test",
        prompt=prompt,
        started_at=0,
    )
    assert found == session_file
    events = _openclaw_session_file_events(session_file, "agent:main:dashboard:test")
    assert extract_text_from_events(events) == "final memo answer"


def test_openclaw_session_path_resolves_state_dir_placeholder(tmp_path) -> None:
    expected = tmp_path / "agents" / "main" / "sessions" / "abc.jsonl"
    assert (
        _resolve_openclaw_session_path(
            "$OPENCLAW_STATE_DIR/agents/main/sessions/abc.jsonl",
            tmp_path,
        )
        == expected
    )


def test_judge_prompt_blinds_endpoint_names_and_includes_caps() -> None:
    case = COMPARISON_CASES[0]
    opensquilla = EndpointResult(
        endpoint="opensquilla",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="A compact memo with assumptions, sources, and risks.",
        score={"total": 5},
    )
    openclaw = EndpointResult(
        endpoint="openclaw",
        case_id=case.case_id,
        ok=False,
        elapsed_s=1.0,
        response_text="",
        score={"total": 0},
        error="TimeoutError",
    )

    prompt = build_judge_prompt(case, opensquilla, openclaw)

    assert "Candidate A" in prompt
    assert "Candidate B" in prompt
    assert "OpenSquilla" not in prompt
    assert "OpenClaw" not in prompt
    assert "Hard caps" in prompt
    assert "timeout, empty response, or endpoint error" in prompt


def test_parse_judge_response_normalizes_json_and_winner() -> None:
    result = parse_judge_response(
        """
        ```json
        {
          "winner": "tie",
          "scores": {"opensquilla": 82, "openclaw": 77},
          "confidence": 1.5,
          "rationale": "A is more grounded.",
          "risks": ["single prompt"]
        }
        ```
        """,
        model="judge-model",
    )

    assert result.winner == "opensquilla"
    assert result.scores == {"opensquilla": 82, "openclaw": 77}
    assert result.confidence == 1.0
    assert result.rationale == "A is more grounded."
    assert result.risks == ["single prompt"]


def test_parse_judge_response_recovers_malformed_json_fields() -> None:
    result = parse_judge_response(
        """
        {
          "winner": "openclaw",
          "scores": {
            "opensquilla": 88,
            "openclaw": 97
        """,
        model="judge-model",
    )

    assert result.winner == "openclaw"
    assert result.scores == {"opensquilla": 88, "openclaw": 97}
    assert "recovered" in result.risks[0]


def test_parse_judge_response_recovers_scores_object_fragment() -> None:
    result = parse_judge_response(
        '{"opensquilla": 76, "openclaw": 91}',
        model="judge-model",
    )

    assert result.winner == "openclaw"
    assert result.scores == {"opensquilla": 76, "openclaw": 91}


def test_judge_result_becomes_final_winner_and_reported_basis() -> None:
    case = COMPARISON_CASES[0]
    opensquilla = EndpointResult(
        endpoint="opensquilla",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="baseline rich answer",
        score={"total": 5},
    )
    openclaw = EndpointResult(
        endpoint="openclaw",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="judge preferred answer",
        score={"total": 4},
    )
    row = compare_results(case, opensquilla, openclaw)
    row["judge_error"] = "RuntimeError: stale failure"
    judged = apply_judge_result(
        row,
        JudgeResult(
            winner="openclaw",
            scores={"opensquilla": 70, "openclaw": 88},
            confidence=0.8,
            rationale="B better handles correctness.",
            risks=["short answer"],
            raw={},
            model="judge-model",
        ),
        case,
    )

    report = render_markdown([judged], jsonl_path="raw.jsonl")

    assert judged["baseline_winner"] == "opensquilla"
    assert judged["winner"] == "openclaw"
    assert judged["score_basis"] == "llm_judge"
    assert "judge_error" not in judged
    assert "Final winner uses LLM judge for 1/1 rows." in report
    assert "| web_research_report | 5 | 4 | opensquilla | 70-88 openclaw | openclaw |" in report


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
