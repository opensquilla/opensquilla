"""Unit tests for Agent._read_clarify_outcome.

meta_resolution stages one of five outcomes on ctx.metadata after the
awaiting branch runs (errors / cancelled / expired / race_lost — plus
resume, which is handled separately by _run_meta_resume). These tests
pin the user-visible text dictated by spec §10.
"""

from __future__ import annotations

import json

import pytest

from opensquilla.engine.agent import Agent
from opensquilla.engine.types import AgentConfig
from opensquilla.skills.meta.plan_serde import clarify_config_to_jsonable
from opensquilla.skills.meta.types import ClarifyField, ClarifyStepConfig


class _FakeAwaiting:
    """Mirrors AwaitingPeek's shape narrowly enough for the handler."""

    def __init__(self, schema: ClarifyStepConfig) -> None:
        self.run_id = "01TESTRUN0000000000000"
        self.step_id = "collect"
        self.awaiting_schema_json = json.dumps(
            clarify_config_to_jsonable(schema), ensure_ascii=False,
        )


@pytest.fixture()
def agent() -> Agent:
    return Agent(
        provider=None,  # type: ignore[arg-type]
        config=AgentConfig(model_id="stub"),
        tool_definitions=[],
        tool_handler=None,
    )


@pytest.fixture()
def schema() -> ClarifyStepConfig:
    return ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="destination", type="string", required=True,
                         prompt="目的地"),
            ClarifyField(name="days", type="int", required=True,
                         min=1, max=14, prompt="天数"),
        ),
        intro="确认 2 件事。",
    )


def test_no_outcome_returns_none(agent: Agent) -> None:
    assert agent._read_clarify_outcome({}) is None


def test_parse_errors_render_error_lines_plus_form(
    agent: Agent, schema: ClarifyStepConfig,
) -> None:
    awaiting = _FakeAwaiting(schema)
    metadata = {
        "meta_clarify_errors": [
            "destination: 'foo' bad",
            "days: 'abc' is not an integer",
        ],
        "meta_clarify_reprompt": awaiting,
    }
    out = agent._read_clarify_outcome(metadata)
    assert out is not None
    text, terminates = out
    assert "未能解析回复" in text
    assert "destination: 'foo' bad" in text
    assert "abc" in text
    assert "请回复以下字段" in text  # form re-rendered
    assert "destination" in text
    assert terminates is True
    # Metadata keys consumed
    assert "meta_clarify_errors" not in metadata
    assert "meta_clarify_reprompt" not in metadata


def test_user_cancel(agent: Agent, schema: ClarifyStepConfig) -> None:
    metadata = {
        "meta_clarify_cancelled": _FakeAwaiting(schema),
        "meta_clarify_cancel_reason": "user_cancel",
    }
    out = agent._read_clarify_outcome(metadata)
    assert out is not None
    text, _ = out
    assert text == "好，已取消。"


def test_three_strike_cancel(agent: Agent, schema: ClarifyStepConfig) -> None:
    metadata = {
        "meta_clarify_cancelled": _FakeAwaiting(schema),
        "meta_clarify_cancel_reason": "parse_failure_limit",
    }
    out = agent._read_clarify_outcome(metadata)
    assert out is not None
    text, _ = out
    assert "无法解析" in text
    assert "已取消上一轮收集" in text


def test_expired(agent: Agent, schema: ClarifyStepConfig) -> None:
    metadata = {"meta_clarify_expired": _FakeAwaiting(schema)}
    out = agent._read_clarify_outcome(metadata)
    assert out is not None
    text, _ = out
    assert "超时" in text


def test_race_lost(agent: Agent) -> None:
    metadata = {"meta_clarify_race_lost": "01OLDRUN0000000000000"}
    out = agent._read_clarify_outcome(metadata)
    assert out is not None
    text, _ = out
    assert "已被处理" in text


def test_soft_progress_surfaces_captured_and_missing_fields(agent: Agent) -> None:
    metadata = {
        "meta_clarify_soft_progress": {
            "filled": {"destination": "Tokyo"},
            "newly_filled": ["destination"],
            "missing_required": ["days"],
            "ambiguous_fields": [
                {"name": "budget", "reason": "多个金额都可能是预算"}
            ],
        }
    }

    out = agent._read_clarify_outcome(metadata)

    assert out is not None
    text, terminates = out
    assert "已记录" in text
    assert "destination=Tokyo" in text
    assert "还需要" in text
    assert "days" in text
    assert "budget" in text
    assert "多个金额" in text
    assert terminates is True
    assert "meta_clarify_soft_progress" not in metadata


def test_proceed_blocked_surfaces_required_next_steps(agent: Agent) -> None:
    metadata = {
        "meta_clarify_proceed_blocked": {
            "filled": {"destination": "Tokyo"},
            "missing_required": ["days", "budget"],
        }
    }

    out = agent._read_clarify_outcome(metadata)

    assert out is not None
    text, terminates = out
    assert "现在还不能开始" in text
    assert "还需要" in text
    assert "days" in text
    assert "budget" in text
    assert "destination=Tokyo" in text
    assert terminates is True
    assert "meta_clarify_proceed_blocked" not in metadata


def test_resume_outcome_is_not_consumed_here(agent: Agent) -> None:
    """meta_resume is handled by _run_meta_resume, not this helper."""
    metadata = {"meta_resume": ("fake", "fake")}
    out = agent._read_clarify_outcome(metadata)
    assert out is None
    assert "meta_resume" in metadata  # still there for the resume handler
