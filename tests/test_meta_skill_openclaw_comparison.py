import asyncio

from scripts.compare_meta_skill_openclaw import (
    COMPARISON_CASES,
    EndpointResult,
    JudgeResult,
    _discover_openclaw_session_file,
    _latest_opensquilla_meta_final_text,
    _latest_opensquilla_transcript_text,
    _openclaw_session_file_events,
    _resolve_openclaw_session_path,
    _wait_for_openclaw_session_file_events,
    _wait_for_opensquilla_transcript_text,
    apply_judge_result,
    build_judge_prompt,
    compare_results,
    extract_text_from_events,
    judge_with_retries,
    parse_judge_response,
    render_markdown,
    render_prompts_markdown,
    score_response,
)


def test_comparison_catalog_covers_expected_meta_skill_scenarios() -> None:
    primary = [case for case in COMPARISON_CASES if case.scenario == "primary"]
    assert [case.skill_name for case in primary] == [
        "meta-paper-write",
        "meta-pdf-intelligence",
        "meta-stack-trace-investigator",
        "meta-travel-planner",
        "meta-skill-creator",
        "meta-migration-assistant",
    ]
    assert len({case.case_id for case in COMPARISON_CASES}) == 18
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


def test_opensquilla_transcript_fallback_reads_final_assistant_text(tmp_path, monkeypatch) -> None:
    import sqlite3

    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE transcript_entries ("
        "id INTEGER PRIMARY KEY, session_key TEXT, role TEXT, content TEXT)"
    )
    conn.execute(
        "INSERT INTO transcript_entries (session_key, role, content) VALUES (?, ?, ?)",
        ("agent:main:cli:test", "assistant", "short streaming preface"),
    )
    conn.execute(
        "INSERT INTO transcript_entries (session_key, role, content) VALUES (?, ?, ?)",
        ("agent:main:cli:test", "assistant", "full final meta-skill deliverable"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("OPENSQUILLA_STATE_DB", str(db_path))

    assert (
        _latest_opensquilla_transcript_text("agent:main:cli:test")
        == "full final meta-skill deliverable"
    )


def test_opensquilla_meta_final_text_reads_clean_dag_deliverable(tmp_path, monkeypatch) -> None:
    import sqlite3

    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE meta_skill_runs ("
        "id INTEGER PRIMARY KEY, session_key TEXT, status TEXT, final_text TEXT, "
        "started_at_ms INTEGER)"
    )
    conn.execute(
        "INSERT INTO meta_skill_runs (session_key, status, final_text, started_at_ms) "
        "VALUES (?, ?, ?, ?)",
        ("agent:main:cli:test", "ok", "clean meta deliverable", 100),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("OPENSQUILLA_STATE_DB", str(db_path))

    assert (
        _latest_opensquilla_meta_final_text("agent:main:cli:test")
        == "clean meta deliverable"
    )


def test_wait_for_opensquilla_transcript_polls_until_final_text(monkeypatch) -> None:
    import asyncio

    responses = iter(["short preface", "full final meta-skill deliverable"])

    def fake_latest(_session_key: str) -> str:
        return next(responses)

    monkeypatch.setattr(
        "scripts.compare_meta_skill_openclaw._latest_opensquilla_transcript_text",
        fake_latest,
    )

    assert (
        asyncio.run(
            _wait_for_opensquilla_transcript_text(
                "agent:main:cli:test",
                minimum_len=len("short preface"),
                timeout_s=1,
                interval_s=0,
            )
        )
        == "full final meta-skill deliverable"
    )


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


def test_openclaw_session_file_events_can_ignore_warmup_before_prompt(tmp_path) -> None:
    sessions_dir = tmp_path / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    session_file = sessions_dir / "abc.jsonl"
    prompt = "Need a decision memo from the copied vendor renewal terms."
    session_file.write_text(
        "\n".join(
            [
                (
                    '{"type":"message","message":{"role":"user","content":'
                    '[{"type":"text","text":"warmup"}]}}'
                ),
                (
                    '{"type":"message","message":{"role":"assistant","content":'
                    '[{"type":"text","text":"Bootstrap removed. Ready for the task."}]}}'
                ),
                '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"'
                + prompt
                + '"}]}}',
                (
                    '{"type":"message","message":{"role":"assistant","content":'
                    '[{"type":"text","text":"usable decision memo"}]}}'
                ),
            ]
        ),
        encoding="utf-8",
    )

    all_events = _openclaw_session_file_events(session_file, "agent:main:dashboard:test")
    prompt_events = _openclaw_session_file_events(
        session_file,
        "agent:main:dashboard:test",
        after_prompt=prompt,
    )

    assert extract_text_from_events(all_events) == "usable decision memo"
    assert extract_text_from_events(prompt_events) == "usable decision memo"
    assert all(
        "Bootstrap removed" not in str(event)
        for event in prompt_events
    )


def test_wait_for_openclaw_session_file_events_polls_until_answer(tmp_path) -> None:
    import asyncio

    session_file = tmp_path / "abc.jsonl"
    prompt = "Need a memo."
    session_file.write_text(
        (
            '{"type":"message","message":{"role":"user","content":'
            '[{"type":"text","text":"Need a memo."}]}}\n'
        ),
        encoding="utf-8",
    )

    async def append_answer() -> None:
        await asyncio.sleep(0)
        with session_file.open("a", encoding="utf-8") as fh:
            fh.write(
                '{"type":"message","message":{"role":"assistant","content":'
                '[{"type":"text","text":"final memo"}]}}\n'
            )

    async def collect() -> str:
        task = asyncio.create_task(append_answer())
        events = await _wait_for_openclaw_session_file_events(
            [session_file],
            session_key="agent:main:dashboard:test",
            after_prompt=prompt,
            timeout_s=1,
            interval_s=0.001,
            stable_s=0.01,
        )
        await task
        return extract_text_from_events(events)

    assert asyncio.run(collect()) == "final memo"


def test_wait_for_openclaw_session_file_events_prefers_later_final_answer(tmp_path) -> None:
    import asyncio

    session_file = tmp_path / "abc.jsonl"
    prompt = "Need a memo."
    session_file.write_text(
        "\n".join(
            [
                (
                    '{"type":"message","message":{"role":"user","content":'
                    '[{"type":"text","text":"Need a memo."}]}}'
                ),
                (
                    '{"type":"message","message":{"role":"assistant","content":'
                    '[{"type":"text","text":"checking sources"}]}}'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    async def append_answer() -> None:
        await asyncio.sleep(0)
        with session_file.open("a", encoding="utf-8") as fh:
            fh.write(
                '{"type":"message","message":{"role":"assistant","content":'
                '[{"type":"text","text":"final sourced memo"}]}}\n'
            )

    async def collect() -> str:
        task = asyncio.create_task(append_answer())
        events = await _wait_for_openclaw_session_file_events(
            [session_file],
            session_key="agent:main:dashboard:test",
            after_prompt=prompt,
            timeout_s=1,
            interval_s=0.001,
            stable_s=0.01,
        )
        await task
        return extract_text_from_events(events)

    assert asyncio.run(collect()) == "final sourced memo"


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


def test_judge_prompt_includes_fairness_and_traceability_dimensions() -> None:
    case = COMPARISON_CASES[0]
    opensquilla = EndpointResult(
        endpoint="opensquilla",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="A sourced memo with assumptions and risks.",
        score={"total": 5},
    )
    openclaw = EndpointResult(
        endpoint="openclaw",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="A sourced memo with assumptions and risks.",
        score={"total": 5},
    )

    prompt = build_judge_prompt(case, opensquilla, openclaw)

    assert "fairness_control" in prompt
    assert "evidence_traceability" in prompt
    assert "risk_boundary_safety" in prompt
    assert "endpoint_validity" in prompt
    assert "Do not award a win because the other endpoint errored" in prompt
    assert "unrelated bootstrap" in prompt
    assert "tool output" in prompt


def test_judge_prompt_weights_final_artifact_quality_highest() -> None:
    case = COMPARISON_CASES[0]
    opensquilla = EndpointResult(
        endpoint="opensquilla",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="A usable memo.",
        score={"total": 5},
    )
    openclaw = EndpointResult(
        endpoint="openclaw",
        case_id=case.case_id,
        ok=True,
        elapsed_s=1.0,
        response_text="A usable memo.",
        score={"total": 5},
    )

    prompt = build_judge_prompt(case, opensquilla, openclaw)

    assert "final_artifact_quality: 40 points" in prompt
    assert "task_completion: 20 points" in prompt
    assert "evidence_traceability: 15 points" in prompt
    assert "meta_skill_fit: 5 points" in prompt
    assert "scores MUST equal the sum of the six weighted subscores" in prompt
    assert "Prioritize the quality of the final user-visible deliverable" in prompt


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
            raw={
                "subscores": {
                    "opensquilla": {
                        "final_artifact_quality": 25,
                        "task_completion": 15,
                        "evidence_traceability": 10,
                        "actionability": 8,
                        "risk_boundary_safety": 8,
                        "meta_skill_fit": 4,
                    },
                    "openclaw": {
                        "final_artifact_quality": 35,
                        "task_completion": 18,
                        "evidence_traceability": 14,
                        "actionability": 9,
                        "risk_boundary_safety": 8,
                        "meta_skill_fit": 4,
                    },
                }
            },
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
    assert f"| {case.case_id} | 5 | 4 | opensquilla | 70-88 openclaw | openclaw |" in report


def test_apply_judge_result_recomputes_scores_from_weighted_subscores() -> None:
    case = COMPARISON_CASES[0]
    row = compare_results(
        case,
        EndpointResult("opensquilla", case.case_id, True, 1.0, "a", {"total": 1}),
        EndpointResult("openclaw", case.case_id, True, 1.0, "b", {"total": 1}),
    )
    judged = apply_judge_result(
        row,
        JudgeResult(
            winner="openclaw",
            scores={"opensquilla": 0, "openclaw": 100},
            confidence=0.8,
            rationale="Weighted subscores favor Candidate A.",
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
        ),
        case,
    )

    assert judged["winner"] == "opensquilla"
    assert judged["judge"]["scores"] == {"opensquilla": 100, "openclaw": 90}
    assert judged["judge"]["raw"]["score_source"] == "weighted_subscores"


def test_apply_judge_result_rejects_incomplete_weighted_payload() -> None:
    case = COMPARISON_CASES[0]
    row = compare_results(
        case,
        EndpointResult("opensquilla", case.case_id, True, 1.0, "a", {"total": 1}),
        EndpointResult("openclaw", case.case_id, True, 1.0, "b", {"total": 1}),
    )

    try:
        apply_judge_result(
            row,
            JudgeResult(
                winner="openclaw",
                scores={"opensquilla": 0, "openclaw": 100},
                confidence=0.8,
                rationale="missing subscores",
                risks=[],
                raw={},
                model="judge-model",
            ),
            case,
        )
    except ValueError as exc:
        assert "weighted subscores" in str(exc)
    else:
        raise AssertionError("expected incomplete judge payload to fail")


def test_judge_with_retries_requires_complete_weighted_payload() -> None:
    case = COMPARISON_CASES[0]
    opensquilla = EndpointResult("opensquilla", case.case_id, True, 1.0, "a", {"total": 1})
    openclaw = EndpointResult("openclaw", case.case_id, True, 1.0, "b", {"total": 1})

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
    result = asyncio.run(judge_with_retries(fake, case, opensquilla, openclaw))  # type: ignore[arg-type]

    assert fake.calls == 2
    assert result.scores == {"opensquilla": 100, "openclaw": 90}


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
