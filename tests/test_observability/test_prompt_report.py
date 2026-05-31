from __future__ import annotations

from opensquilla.observability.prompt_report import build_prompt_report


def test_prompt_report_captures_daily_notes_policy_metadata() -> None:
    report = build_prompt_report(
        turn_id="turn-1",
        session_key="agent:main:test",
        session_id="session-1",
        agent_id="main",
        system_prompt="system",
        tool_defs=[],
        metadata={
            "daily_notes_omitted": True,
            "daily_notes_count_before_omit": 2,
            "daily_notes_policy_reason": "auto_injection_disabled",
        },
    )

    assert report.daily_notes_omitted is True
    assert report.daily_notes_count_before_omit == 2
    assert report.daily_notes_policy_reason == "auto_injection_disabled"
