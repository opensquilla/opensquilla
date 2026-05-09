"""Unit tests for UsageSummary / UsageCounter savings-line wiring."""

from __future__ import annotations

from dataclasses import dataclass

from opensquilla.cli.repl.stream import UsageCounter, UsageSummary


@dataclass
class _FakeDoneEvent:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    billed_cost: float = 0.0
    cost_source: str = "none"
    model: str = ""
    baseline_model: str = ""
    routed_model: str = ""
    savings_usd: float = 0.0
    total_savings_usd: float = 0.0
    total_savings_pct: float = 0.0


def test_usage_summary_from_done_event_reads_savings_fields() -> None:
    event = _FakeDoneEvent(
        input_tokens=1000,
        output_tokens=200,
        cost_usd=0.0010,
        model="deepseek-v4-flash",
        baseline_model="claude-opus-4-7",
        routed_model="deepseek-v4-flash",
        savings_usd=0.0080,
        total_savings_usd=0.0090,
        total_savings_pct=90.0,
    )

    summary = UsageSummary.from_done_event(event)

    assert summary.baseline_model == "claude-opus-4-7"
    assert summary.routed_model == "deepseek-v4-flash"
    assert summary.savings_usd == 0.0080
    assert summary.total_savings_usd == 0.0090
    assert summary.total_savings_pct == 90.0


def test_usage_summary_from_done_event_defaults_savings_to_zero() -> None:
    """Existing engine paths that do not populate savings still produce a valid summary."""
    event = _FakeDoneEvent(input_tokens=100, output_tokens=20, cost_usd=0.001)

    summary = UsageSummary.from_done_event(event)

    assert summary.baseline_model == ""
    assert summary.routed_model == ""
    assert summary.savings_usd == 0.0
    assert summary.total_savings_usd == 0.0
    assert summary.total_savings_pct == 0.0


def test_usage_summary_from_gateway_payload_reads_snake_case() -> None:
    payload = {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cost_usd": 0.0010,
        "baseline_model": "claude-opus-4-7",
        "routed_model": "deepseek-v4-flash",
        "savings_usd": 0.0080,
        "total_savings_usd": 0.0090,
        "total_savings_pct": 90.0,
    }

    summary = UsageSummary.from_gateway_payload(payload)

    assert summary.baseline_model == "claude-opus-4-7"
    assert summary.routed_model == "deepseek-v4-flash"
    assert summary.total_savings_usd == 0.0090
    assert summary.total_savings_pct == 90.0


def test_usage_summary_from_gateway_payload_reads_camel_case() -> None:
    """The other fields in this dataclass support camelCase fallback; savings should too."""
    payload = {
        "inputTokens": 1000,
        "outputTokens": 200,
        "costUsd": 0.0010,
        "baselineModel": "claude-opus-4-7",
        "routedModel": "deepseek-v4-flash",
        "savingsUsd": 0.0080,
        "totalSavingsUsd": 0.0090,
        "totalSavingsPct": 90.0,
    }

    summary = UsageSummary.from_gateway_payload(payload)

    assert summary.baseline_model == "claude-opus-4-7"
    assert summary.total_savings_usd == 0.0090
    assert summary.total_savings_pct == 90.0


def test_usage_counter_render_omits_savings_line_when_no_savings() -> None:
    counter = UsageCounter(input_tokens=100, output_tokens=20, cost_usd=0.001)

    rendered = counter.render()

    assert "saved" not in rendered
    assert "$0.001000" in rendered


def test_usage_counter_render_shows_savings_when_present() -> None:
    counter = UsageCounter(
        input_tokens=8400,
        output_tokens=3945,
        cached_tokens=1200,
        cost_usd=0.001234,
        total_savings_usd=0.013966,
        baseline_model="claude-opus-4-7",
    )

    rendered = counter.render()

    assert "saved ~" in rendered
    # baseline_cost = 0.001234 + 0.013966 = 0.015200
    assert "$0.015200" in rendered
    assert "claude-opus-4-7" in rendered


def test_usage_counter_render_omits_baseline_model_suffix_when_unknown() -> None:
    counter = UsageCounter(
        cost_usd=0.001234,
        total_savings_usd=0.013966,
    )

    rendered = counter.render()

    assert "saved ~" in rendered
    assert "if routed straight to" not in rendered


def test_usage_counter_add_accumulates_savings() -> None:
    counter = UsageCounter()
    counter.add(UsageSummary(total_savings_usd=0.01, baseline_model="model-a"))
    counter.add(UsageSummary(total_savings_usd=0.02, baseline_model="model-a"))

    assert counter.total_savings_usd == 0.03
    assert counter.baseline_model == "model-a"


def test_usage_counter_add_remembers_last_baseline_model_when_changed() -> None:
    """If the operator changes provider mid-session, baseline reflects the latest turn."""
    counter = UsageCounter()
    counter.add(UsageSummary(total_savings_usd=0.01, baseline_model="model-a"))
    counter.add(UsageSummary(total_savings_usd=0.02, baseline_model="model-b"))

    assert counter.baseline_model == "model-b"


def test_usage_counter_add_does_not_overwrite_baseline_with_blank() -> None:
    """A turn without router data (baseline_model='') must not erase the prior value."""
    counter = UsageCounter()
    counter.add(UsageSummary(total_savings_usd=0.01, baseline_model="model-a"))
    counter.add(UsageSummary(total_savings_usd=0.005, baseline_model=""))

    assert counter.baseline_model == "model-a"


def test_usage_counter_reset_clears_savings() -> None:
    counter = UsageCounter(
        cost_usd=0.001,
        total_savings_usd=0.01,
        baseline_model="model-a",
    )
    counter.reset()

    assert counter.total_savings_usd == 0.0
    assert counter.baseline_model == ""
    assert counter.cost_usd == 0.0
