from __future__ import annotations

import math

import pytest

from opensquilla.engine.agent_core_metrics import (
    AgentCoreParityThresholds,
    AgentCoreRunMetrics,
    collect_agent_core_run_metrics,
    compare_agent_core_metrics,
)
from opensquilla.engine.types import (
    ArtifactEvent,
    CompactionEvent,
    DoneEvent,
    ErrorEvent,
    RouterControlReplayEvent,
    RouterDecisionEvent,
    RunHeartbeatEvent,
    StateChangeEvent,
    TextDeltaEvent,
    ThinkingEvent,
    ToolResultEvent,
    ToolUseStartEvent,
    WarningEvent,
)
from opensquilla.engine.usage import SessionTotalsSnapshot


def test_agent_core_metrics_collect_token_tool_and_cache_rates() -> None:
    metrics = collect_agent_core_run_metrics(
        [
            TextDeltaEvent(text="o"),
            TextDeltaEvent(text="k"),
            ToolUseStartEvent(tool_use_id="tool-1", tool_name="echo"),
            ToolResultEvent(
                tool_use_id="tool-1",
                tool_name="echo",
                result="ok",
                arguments={"value": "ok"},
            ),
            ToolResultEvent(
                tool_use_id="spawn-1",
                tool_name="sessions_spawn",
                result='{"session_key":"agent:main:child"}',
                arguments={"prompt": "work"},
            ),
            ToolResultEvent(
                tool_use_id="yield-1",
                tool_name="sessions_yield",
                result='{"status":"yielded"}',
            ),
            ArtifactEvent(
                id="artifact-1",
                sha256="abc123",
                name="report.txt",
                mime="text/plain",
                size=42,
            ),
            RunHeartbeatEvent(
                phase="queue",
                elapsed_ms=25,
                idle_ms=10,
                message="task task-1 running",
            ),
            StateChangeEvent(from_state="idle", to_state="thinking"),
            ThinkingEvent(text="chain-of-thought placeholder"),
            WarningEvent(code="compact_notice", message="compaction recommended"),
            CompactionEvent(
                compaction_id="cmp-1",
                summary="summary",
                kept_entries=[{"idx": 1}],
                kept_count=1,
                removed_count=2,
            ),
            RouterDecisionEvent(
                tier="standard",
                model="openai/gpt-test",
                source="squilla-router",
            ),
            RouterControlReplayEvent(action="switch_model", target_model="openai/gpt-test"),
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                reasoning_tokens=10,
                cached_tokens=40,
                cache_write_tokens=12,
                cost_usd=0.004,
                billed_cost=0.003,
                cost_source="provider",
                model="openai/gpt-base",
                routed_tier="standard",
                routed_model="openai/gpt-test",
                routing_source="squilla-router",
                routing_confidence=0.75,
                baseline_model="openai/gpt-base",
                routing_applied=True,
                cache_hit_active=True,
                runtime_context_hash="host-context-a",
                runtime_context_chars=1000,
                session_totals=SessionTotalsSnapshot(
                    input_tokens=100,
                    output_tokens=20,
                    cache_read_tokens=40,
                    cache_write_tokens=12,
                    cost_usd=0.004,
                    billed_cost=0.003,
                ),
            ),
        ]
    )

    assert metrics.terminal_success is True
    assert metrics.total_tokens == 130
    assert metrics.cache_write_tokens == 12
    assert metrics.cost_usd == 0.004
    assert metrics.billed_cost == 0.003
    assert metrics.tool_success_rate == 1.0
    assert metrics.kv_cache_hit_rate == 0.4
    assert metrics.final_text == "ok"
    assert metrics.stream_text == "ok"
    assert metrics.router_decision_count == 1
    assert metrics.router_decision_fingerprints == (
        '{"model":"openai/gpt-test","source":"squilla-router",'
        '"tier":"standard"}',
    )
    assert metrics.router_control_replay_count == 1
    assert metrics.router_replay_fingerprints == (
        '{"action":"switch_model","replay_depth":0,"target_id":null,'
        '"target_model":"openai/gpt-test","target_provider":null,'
        '"target_tier":null}',
    )
    assert metrics.routed_models == ("openai/gpt-test",)
    assert metrics.routing_sources == ("squilla-router",)
    assert metrics.routing_applied_states == (True,)
    assert metrics.cache_hit_active_states == (True,)
    assert metrics.runtime_context_fingerprints == (
        '{"runtime_context_chars":1000,"runtime_context_hash":"host-context-a"}',
    )
    assert metrics.done_metadata_fingerprints == (
        '{"baseline_model":"openai/gpt-base","cost_source":"provider",'
        '"model":"openai/gpt-base","rollout_phase":"full",'
        '"routed_model":"openai/gpt-test",'
        '"routed_tier":"standard","routing_confidence":0.75,'
        '"routing_source":"squilla-router"}',
    )
    assert metrics.session_total_input_tokens == 100
    assert metrics.session_total_billed_cost_usd == 0.003
    assert metrics.yield_result_count == 1
    assert metrics.tool_result_fingerprints == (
        'echo|ok|{"value":"ok"}|ok|{}',
        'sessions_spawn|{"session_key":"agent:main:child"}|{"prompt":"work"}|ok|{}',
        'sessions_yield|{"status":"yielded"}|{}|ok|{}',
    )
    assert metrics.orchestration_result_fingerprints == (
        'sessions_spawn|{"session_key":"agent:main:child"}|{"prompt":"work"}|ok|{}',
        'sessions_yield|{"status":"yielded"}|{}|ok|{}',
    )
    assert metrics.heartbeat_fingerprints == (
        '{"elapsed_ms":25,"idle_ms":10,"message":"task task-1 running",'
        '"phase":"queue"}',
    )
    assert metrics.state_change_fingerprints == (
        '{"from_state":"idle","to_state":"thinking"}',
    )
    assert metrics.thinking_fingerprints == (
        '{"text":"chain-of-thought placeholder"}',
    )
    assert metrics.warning_fingerprints == (
        '{"code":"compact_notice","message":"compaction recommended"}',
    )
    assert metrics.compaction_fingerprints == (
        '{"compaction_id":"cmp-1","kept_count":1,"kept_entries":[{"idx":1}],'
        '"removed_count":2,"summary":"summary"}',
    )
    assert metrics.artifact_fingerprints == ("report.txt|text/plain|42|abc123",)


def test_agent_core_metrics_reject_python_only_fingerprint_values() -> None:
    class PythonOnlyValue:
        pass

    with pytest.raises(RuntimeError, match="parity fingerprint.*JSON-compatible"):
        collect_agent_core_run_metrics(
            [
                ToolResultEvent(
                    tool_use_id="tool-1",
                    tool_name="echo",
                    result="ok",
                    arguments={"value": PythonOnlyValue()},
                ),
                DoneEvent(text="ok", input_tokens=10, output_tokens=3),
            ]
        )


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (
            ArtifactEvent(
                id="artifact-1",
                sha256="abc123",
                name="report.txt",
                mime="text/plain",
                size=-1,
            ),
            "artifact size",
        ),
        (
            RunHeartbeatEvent(
                phase="queue",
                elapsed_ms=-1,
                idle_ms=0,
                message="running",
            ),
            "heartbeat elapsed_ms",
        ),
        (
            RunHeartbeatEvent(
                phase="queue",
                elapsed_ms=0,
                idle_ms=-1,
                message="running",
            ),
            "heartbeat idle_ms",
        ),
        (
            CompactionEvent(
                compaction_id="cmp-1",
                summary="summary",
                kept_entries=[],
                kept_count=-1,
                removed_count=0,
            ),
            "compaction kept_count",
        ),
        (
            CompactionEvent(
                compaction_id="cmp-1",
                summary="summary",
                kept_entries=[],
                kept_count=0,
                removed_count=-1,
            ),
            "compaction removed_count",
        ),
        (
            RouterDecisionEvent(tier="standard", confidence=1.5),
            "router decision confidence must be a probability",
        ),
        (
            RouterDecisionEvent(tier="standard", probs=[0.1, 1.2]),
            "router decision probs must be a list of probabilities",
        ),
        (
            RouterControlReplayEvent(action="switch_model", replay_depth=-1),
            "router replay depth",
        ),
    ],
)
def test_agent_core_metrics_reject_negative_public_event_counters(
    event: object,
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        collect_agent_core_run_metrics([event, DoneEvent(text="ok")])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"input_tokens": -1}, "input_tokens"),
        ({"output_tokens": -1}, "output_tokens"),
        ({"reasoning_tokens": -1}, "reasoning_tokens"),
        ({"cached_tokens": -1}, "cached_tokens"),
        ({"cache_write_tokens": -1}, "cache_write_tokens"),
        ({"iterations": -1}, "iterations"),
        ({"runtime_context_chars": -1}, "runtime_context_chars"),
        ({"cost_usd": -0.01}, "cost_usd"),
        ({"billed_cost": -0.01}, "billed_cost"),
        ({"cost_usd": math.inf}, "cost_usd"),
        ({"model": object()}, "model"),
        ({"cost_source": None}, "cost_source"),
        ({"reasoning_content": object()}, "reasoning_content"),
        ({"routing_confidence": object()}, "routing_confidence"),
        ({"routing_confidence": 1.5}, "routing_confidence must be a probability"),
        ({"savings_pct": math.nan}, "savings_pct"),
        ({"savings_usd": -0.01}, "savings_usd"),
        ({"total_savings_pct": math.inf}, "total_savings_pct"),
        ({"total_savings_usd": None}, "total_savings_usd"),
        (
            {"input_tokens": 10, "cached_tokens": 11},
            "cached_tokens must be less than or equal to input_tokens",
        ),
        (
            {"input_tokens": 10, "cache_write_tokens": 11},
            "cache_write_tokens must be less than or equal to input_tokens",
        ),
    ],
)
def test_agent_core_metrics_reject_malformed_done_accounting(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        collect_agent_core_run_metrics([DoneEvent(text="ok", **kwargs)])


def test_agent_core_metrics_reject_multiple_done_events() -> None:
    with pytest.raises(RuntimeError, match="AgentEvent stream must contain at most one DoneEvent"):
        collect_agent_core_run_metrics(
            [
                DoneEvent(text="first", input_tokens=10),
                DoneEvent(text="second", input_tokens=20),
            ]
        )


def test_agent_core_metrics_reject_events_after_terminal_done() -> None:
    with pytest.raises(
        RuntimeError,
        match="AgentEvent stream must not emit events after terminal event",
    ):
        collect_agent_core_run_metrics([DoneEvent(text="ok"), TextDeltaEvent(text="late")])


def test_agent_core_metrics_reject_missing_terminal_event() -> None:
    with pytest.raises(
        RuntimeError,
        match="AgentEvent stream must contain a terminal DoneEvent or ErrorEvent",
    ):
        collect_agent_core_run_metrics([TextDeltaEvent(text="partial")])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"input_tokens": -1}, "session_totals.input_tokens"),
        ({"output_tokens": -1}, "session_totals.output_tokens"),
        ({"cache_read_tokens": -1}, "session_totals.cache_read_tokens"),
        ({"cache_write_tokens": -1}, "session_totals.cache_write_tokens"),
        ({"cost_usd": -0.01}, "session_totals.cost_usd"),
        ({"billed_cost": -0.01}, "session_totals.billed_cost"),
        ({"billed_cost": math.nan}, "session_totals.billed_cost"),
        (
            {"input_tokens": 10, "cache_read_tokens": 11},
            "session_totals.cache_read_tokens must be less than or equal to "
            "session_totals.input_tokens",
        ),
        (
            {"input_tokens": 10, "cache_write_tokens": 11},
            "session_totals.cache_write_tokens must be less than or equal to "
            "session_totals.input_tokens",
        ),
    ],
)
def test_agent_core_metrics_reject_malformed_session_totals(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        collect_agent_core_run_metrics(
            [
                DoneEvent(
                    text="ok",
                    session_totals=SessionTotalsSnapshot(**kwargs),
                )
            ]
        )


@pytest.mark.parametrize(
    ("thresholds", "message"),
    [
        (AgentCoreParityThresholds(max_total_token_ratio=0.99), "max_total_token_ratio"),
        (AgentCoreParityThresholds(max_total_token_ratio=math.inf), "max_total_token_ratio"),
        (AgentCoreParityThresholds(total_token_slack=-1), "total_token_slack"),
        (AgentCoreParityThresholds(total_token_slack=True), "total_token_slack"),
        (
            AgentCoreParityThresholds(min_tool_success_rate_delta=-0.01),
            "min_tool_success_rate_delta",
        ),
        (
            AgentCoreParityThresholds(min_tool_success_rate_delta=math.nan),
            "min_tool_success_rate_delta",
        ),
        (
            AgentCoreParityThresholds(min_kv_cache_hit_rate_delta=math.nan),
            "min_kv_cache_hit_rate_delta",
        ),
        (
            AgentCoreParityThresholds(min_kv_cache_hit_rate_delta=-1.01),
            "min_kv_cache_hit_rate_delta",
        ),
        (AgentCoreParityThresholds(max_cost_ratio=0.99), "max_cost_ratio"),
        (AgentCoreParityThresholds(cost_slack_usd=-0.01), "cost_slack_usd"),
    ],
)
def test_agent_core_metric_comparison_rejects_malformed_thresholds(
    thresholds: AgentCoreParityThresholds,
    message: str,
) -> None:
    metrics = collect_agent_core_run_metrics([DoneEvent(text="ok")])

    with pytest.raises(RuntimeError, match=message):
        compare_agent_core_metrics(
            baseline=metrics,
            candidate=metrics,
            candidate_name="pi",
            thresholds=thresholds,
        )


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (
            AgentCoreRunMetrics(
                terminal_success=True,
                input_tokens=-1,
            ),
            "candidate.input_tokens",
        ),
        (
            AgentCoreRunMetrics(
                terminal_success=True,
                input_tokens=10,
                cached_tokens=11,
            ),
            "candidate.cached_tokens must be less than or equal to "
            "candidate.input_tokens",
        ),
        (
            AgentCoreRunMetrics(
                terminal_success=True,
                input_tokens=10,
                cache_write_tokens=11,
            ),
            "candidate.cache_write_tokens must be less than or equal to "
            "candidate.input_tokens",
        ),
        (
            AgentCoreRunMetrics(
                terminal_success=True,
                session_total_input_tokens=10,
                session_total_cache_read_tokens=11,
            ),
            "candidate.session_total_cache_read_tokens must be less than or "
            "equal to candidate.session_total_input_tokens",
        ),
        (
            AgentCoreRunMetrics(
                terminal_success=True,
                session_total_input_tokens=10,
                session_total_cache_write_tokens=11,
            ),
            "candidate.session_total_cache_write_tokens must be less than or "
            "equal to candidate.session_total_input_tokens",
        ),
        (
            AgentCoreRunMetrics(
                terminal_success=True,
                tool_calls=1,
                tool_successes=1,
                tool_errors=1,
            ),
            "candidate.tool result count must be less than or equal to "
            "candidate.tool_calls or candidate.tool_result_fingerprints",
        ),
        (
            AgentCoreRunMetrics(
                terminal_success=True,
                tool_result_fingerprints=('echo|{"result":"ok"}',),
            ),
            "candidate.tool result count must equal "
            "candidate.tool_result_fingerprints",
        ),
    ],
)
def test_agent_core_metric_comparison_rejects_malformed_run_metrics(
    candidate: AgentCoreRunMetrics,
    message: str,
) -> None:
    baseline = collect_agent_core_run_metrics([DoneEvent(text="ok", input_tokens=10)])

    with pytest.raises(RuntimeError, match=message):
        compare_agent_core_metrics(
            baseline=baseline,
            candidate=candidate,
            candidate_name="pi",
        )


def test_agent_core_metric_comparison_flags_stream_text_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [TextDeltaEvent(text="ok"), DoneEvent(text="ok")]
    )
    candidate = collect_agent_core_run_metrics([DoneEvent(text="ok")])

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("stream text parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_heartbeat_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            RunHeartbeatEvent(
                phase="queue",
                elapsed_ms=25,
                idle_ms=10,
                message="task task-1 running",
            ),
            DoneEvent(text="ok"),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            RunHeartbeatEvent(
                phase="queue",
                elapsed_ms=25,
                idle_ms=10,
                message="task task-2 running",
            ),
            DoneEvent(text="ok"),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("heartbeat parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_thinking_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [ThinkingEvent(text="visible reasoning"), DoneEvent(text="ok")]
    )
    candidate = collect_agent_core_run_metrics(
        [ThinkingEvent(text="different reasoning"), DoneEvent(text="ok")]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("thinking parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_state_change_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [StateChangeEvent(from_state="idle", to_state="thinking"), DoneEvent(text="ok")]
    )
    candidate = collect_agent_core_run_metrics(
        [StateChangeEvent(from_state="idle", to_state="streaming"), DoneEvent(text="ok")]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("state-change parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_warning_and_compaction_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            WarningEvent(code="compact_notice", message="compaction recommended"),
            CompactionEvent(
                compaction_id="cmp-1",
                summary="summary",
                kept_entries=[{"idx": 1}],
                kept_count=1,
                removed_count=2,
            ),
            DoneEvent(text="ok"),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            WarningEvent(code="other", message="different"),
            DoneEvent(text="ok"),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("warning parity regressed" in violation for violation in violations)
    assert any("compaction parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_host_owned_public_events() -> None:
    baseline = collect_agent_core_run_metrics([DoneEvent(text="ok")])
    candidate = collect_agent_core_run_metrics(
        [
            RunHeartbeatEvent(
                phase="queue",
                elapsed_ms=25,
                idle_ms=10,
                message="task task-1 running",
            ),
            ThinkingEvent(text="visible reasoning"),
            StateChangeEvent(from_state="idle", to_state="streaming"),
            WarningEvent(code="compact_notice", message="compaction recommended"),
            CompactionEvent(
                compaction_id="cmp-1",
                summary="summary",
                kept_entries=[{"idx": 1}],
                kept_count=1,
                removed_count=2,
            ),
            DoneEvent(text="ok"),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("heartbeat parity regressed" in violation for violation in violations)
    assert any("thinking parity regressed" in violation for violation in violations)
    assert any("state-change parity regressed" in violation for violation in violations)
    assert any("warning parity regressed" in violation for violation in violations)
    assert any("compaction parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_weaker_candidate() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            ToolUseStartEvent(tool_use_id="tool-1", tool_name="echo"),
            ToolResultEvent(tool_use_id="tool-1", tool_name="echo", result="ok"),
            RouterDecisionEvent(tier="standard", model="openai/gpt-test"),
            RouterControlReplayEvent(action="switch_model", target_model="openai/gpt-test"),
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=50,
                cache_write_tokens=20,
                cost_usd=0.01,
                billed_cost=0.02,
                session_totals=SessionTotalsSnapshot(input_tokens=100, output_tokens=20),
            ),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ToolUseStartEvent(tool_use_id="tool-1", tool_name="echo"),
            ToolResultEvent(
                tool_use_id="tool-1",
                tool_name="echo",
                result="failed",
                is_error=True,
            ),
            DoneEvent(text="ok", input_tokens=180, output_tokens=20, cached_tokens=0),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            max_total_token_ratio=1.0,
            total_token_slack=0,
            max_cost_ratio=1.0,
            cost_slack_usd=0.0,
            min_kv_cache_hit_rate_delta=0.0,
        ),
    )

    assert any("tool success rate regressed" in violation for violation in violations)
    assert any("total tokens regressed" in violation for violation in violations)
    assert any("KV cache hit rate regressed" in violation for violation in violations)
    assert any("cost accounting missing" in violation for violation in violations)
    assert any("billed cost accounting missing" in violation for violation in violations)
    assert any("cache write tokens missing" in violation for violation in violations)
    assert any("router decision metadata regressed" in violation for violation in violations)
    assert any("router replay metadata regressed" in violation for violation in violations)
    assert any("session totals missing" in violation for violation in violations)


def test_agent_core_metric_comparison_reports_tool_success_delta_threshold() -> None:
    baseline = AgentCoreRunMetrics(
        tool_calls=2,
        tool_successes=1,
        tool_errors=1,
        terminal_success=True,
    )
    candidate = AgentCoreRunMetrics(
        tool_calls=2,
        tool_successes=1,
        tool_errors=1,
        terminal_success=True,
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(min_tool_success_rate_delta=0.25),
    )

    assert any(
        "tool success rate regressed: 0.500 < 0.750 (baseline 0.500)"
        in violation
        for violation in violations
    )


def test_agent_core_metric_comparison_flags_extra_tool_errors() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ToolUseStartEvent(tool_use_id="tool-1", tool_name="echo"),
            ToolResultEvent(
                tool_use_id="tool-1",
                tool_name="echo",
                result="failed",
                is_error=True,
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("tool error count regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_billed_cost_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cost_usd=0.01,
                billed_cost=0.02,
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cost_usd=0.01,
                billed_cost=0.04,
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            max_cost_ratio=1.0,
            cost_slack_usd=0.0,
        ),
    )

    assert any("billed cost regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_unexpected_cost_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cost_usd=0.02,
                billed_cost=0.03,
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            max_cost_ratio=1.0,
            cost_slack_usd=0.0,
        ),
    )

    assert any("cost regressed" in violation for violation in violations)
    assert any("billed cost regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_token_component_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                reasoning_tokens=10,
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=0,
                output_tokens=130,
                reasoning_tokens=0,
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            max_total_token_ratio=1.0,
            total_token_slack=0,
        ),
    )

    assert any("input token accounting missing" in violation for violation in violations)
    assert any("reasoning token accounting missing" in violation for violation in violations)
    assert any("output tokens regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_unexpected_token_regressions() -> None:
    baseline = collect_agent_core_run_metrics([DoneEvent(text="ok")])
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                reasoning_tokens=7,
                cache_write_tokens=5,
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            max_total_token_ratio=1.0,
            total_token_slack=0,
        ),
    )

    assert any("total tokens regressed" in violation for violation in violations)
    assert any("input tokens regressed" in violation for violation in violations)
    assert any("output tokens regressed" in violation for violation in violations)
    assert any("reasoning tokens regressed" in violation for violation in violations)
    assert any("cache write tokens regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_cache_write_token_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cache_write_tokens=10,
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cache_write_tokens=50,
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            max_total_token_ratio=1.0,
            total_token_slack=0,
        ),
    )

    assert any("cache write tokens regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_cached_token_accounting_missing() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=40,
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=0,
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            min_kv_cache_hit_rate_delta=-1.0,
        ),
    )

    assert any("cached tokens missing" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_session_totals() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                session_totals=SessionTotalsSnapshot(
                    input_tokens=100,
                    output_tokens=20,
                    cache_read_tokens=10,
                    cache_write_tokens=5,
                    cost_usd=0.01,
                    billed_cost=0.02,
                ),
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("session totals unexpected" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_zero_baseline_session_total_drift() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                session_totals=SessionTotalsSnapshot(
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                    cost_usd=0.0,
                    billed_cost=0.0,
                ),
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                session_totals=SessionTotalsSnapshot(
                    input_tokens=2,
                    output_tokens=3,
                    cache_read_tokens=1,
                    cache_write_tokens=1,
                    cost_usd=0.02,
                    billed_cost=0.03,
                ),
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            max_total_token_ratio=1.0,
            total_token_slack=0,
            max_cost_ratio=1.0,
            cost_slack_usd=0.0,
        ),
    )

    assert any("session input total regressed" in violation for violation in violations)
    assert any("session output total regressed" in violation for violation in violations)
    assert any("session cache read total regressed" in violation for violation in violations)
    assert any("session cache write total regressed" in violation for violation in violations)
    assert any("session cost total regressed" in violation for violation in violations)
    assert any(
        "session billed cost total regressed" in violation
        for violation in violations
    )


def test_agent_core_metric_comparison_flags_missing_zero_baseline_session_total_fields() -> None:
    baseline = AgentCoreRunMetrics(
        terminal_success=True,
        session_total_input_tokens=0,
        session_total_output_tokens=0,
        session_total_cache_read_tokens=0,
        session_total_cache_write_tokens=0,
        session_total_cost_usd=0.0,
        session_total_billed_cost_usd=0.0,
    )
    candidate = AgentCoreRunMetrics(
        terminal_success=True,
        session_total_input_tokens=0,
        session_total_output_tokens=0,
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("session cache read total missing" in violation for violation in violations)
    assert any("session cache write total missing" in violation for violation in violations)
    assert any("session cost total missing" in violation for violation in violations)
    assert any(
        "session billed cost total missing" in violation for violation in violations
    )


def test_agent_core_metric_comparison_flags_unexpected_session_total_fields() -> None:
    baseline = AgentCoreRunMetrics(
        terminal_success=True,
        session_total_input_tokens=100,
        session_total_output_tokens=20,
    )
    candidate = AgentCoreRunMetrics(
        terminal_success=True,
        session_total_input_tokens=100,
        session_total_output_tokens=20,
        session_total_cache_read_tokens=10,
        session_total_cache_write_tokens=5,
        session_total_cost_usd=0.01,
        session_total_billed_cost_usd=0.02,
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any(
        "session cache read total unexpected" in violation
        for violation in violations
    )
    assert any(
        "session cache write total unexpected" in violation
        for violation in violations
    )
    assert any("session cost total unexpected" in violation for violation in violations)
    assert any(
        "session billed cost total unexpected" in violation
        for violation in violations
    )


def test_agent_core_metric_comparison_flags_session_total_field_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=40,
                cache_write_tokens=10,
                cost_usd=0.01,
                session_totals=SessionTotalsSnapshot(
                    input_tokens=500,
                    output_tokens=120,
                    cache_read_tokens=220,
                    cache_write_tokens=80,
                    cost_usd=0.05,
                    billed_cost=0.06,
                ),
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=40,
                cache_write_tokens=10,
                cost_usd=0.01,
                session_totals=SessionTotalsSnapshot(
                    input_tokens=500,
                    output_tokens=120,
                ),
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("session cache read total regressed" in violation for violation in violations)
    assert any("session cache write total regressed" in violation for violation in violations)
    assert any("session cost total regressed" in violation for violation in violations)
    assert any(
        "session billed cost total regressed" in violation
        for violation in violations
    )


def test_agent_core_metric_comparison_checks_partial_session_total_dimensions() -> None:
    baseline = AgentCoreRunMetrics(
        terminal_success=True,
        session_total_cache_read_tokens=40,
        session_total_cache_write_tokens=10,
        session_total_cost_usd=0.01,
        session_total_billed_cost_usd=0.02,
    )
    candidate = AgentCoreRunMetrics(
        terminal_success=True,
        session_total_cache_read_tokens=0,
        session_total_cache_write_tokens=0,
        session_total_cost_usd=0.0,
        session_total_billed_cost_usd=0.0,
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            max_total_token_ratio=1.0,
            total_token_slack=0,
            max_cost_ratio=1.0,
            cost_slack_usd=0.0,
        ),
    )

    assert any("session cache read total regressed" in violation for violation in violations)
    assert any("session cache write total regressed" in violation for violation in violations)
    assert any("session cost total regressed" in violation for violation in violations)
    assert any(
        "session billed cost total regressed" in violation
        for violation in violations
    )


def test_agent_core_metric_comparison_flags_excessive_session_total_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=40,
                cache_write_tokens=10,
                cost_usd=0.01,
                billed_cost=0.02,
                session_totals=SessionTotalsSnapshot(
                    input_tokens=100,
                    output_tokens=20,
                    cache_read_tokens=40,
                    cache_write_tokens=10,
                    cost_usd=0.01,
                    billed_cost=0.02,
                ),
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=40,
                cache_write_tokens=10,
                cost_usd=0.01,
                billed_cost=0.02,
                session_totals=SessionTotalsSnapshot(
                    input_tokens=300,
                    output_tokens=60,
                    cache_read_tokens=120,
                    cache_write_tokens=50,
                    cost_usd=0.05,
                    billed_cost=0.08,
                ),
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
        thresholds=AgentCoreParityThresholds(
            max_total_token_ratio=1.0,
            total_token_slack=0,
            max_cost_ratio=1.0,
            cost_slack_usd=0.0,
        ),
    )

    assert any("session input total regressed" in violation for violation in violations)
    assert any("session output total regressed" in violation for violation in violations)
    assert any("session cache read total regressed" in violation for violation in violations)
    assert any("session cache write total regressed" in violation for violation in violations)
    assert any("session cost total regressed" in violation for violation in violations)
    assert any(
        "session billed cost total regressed" in violation
        for violation in violations
    )


def test_agent_core_metric_comparison_flags_router_metadata_identity_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            RouterDecisionEvent(
                tier="standard",
                model="openai/gpt-router",
                source="squilla-router",
            ),
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                routed_model="openai/gpt-router",
                routing_source="squilla-router",
            ),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            RouterDecisionEvent(
                tier="standard",
                model="openai/gpt-fallback",
                source="manual",
            ),
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                routed_model="openai/gpt-fallback",
                routing_source="manual",
            ),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("routed model metadata regressed" in violation for violation in violations)
    assert any("routing source metadata regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_done_metadata_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cost_source="provider",
                model="openai/gpt-base",
                routed_tier="standard",
                routing_source="squilla-router",
                routing_confidence=0.75,
                baseline_model="openai/gpt-base",
                routed_model="openai/gpt-router",
                rollout_phase="full",
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cost_source="none",
                model="openai/gpt-base",
                routed_tier="standard",
                routing_source="squilla-router",
                routing_confidence=0.75,
                baseline_model="openai/gpt-base",
                routed_model="openai/gpt-router",
                rollout_phase="full",
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("terminal done metadata regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_router_metadata() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                routed_model="openai/gpt-sidecar",
                routing_source="pi-sidecar",
            ),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("routed model metadata regressed" in violation for violation in violations)
    assert any("routing source metadata regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_cache_hit_active_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=40,
                cache_hit_active=True,
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=40,
                cache_hit_active=False,
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("cache hit active metadata regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_routing_applied_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                routed_model="openai/gpt-router",
                routing_source="squilla-router",
                routing_applied=True,
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                routed_model="openai/gpt-router",
                routing_source="squilla-router",
                routing_applied=False,
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("routing applied metadata regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_runtime_context_metadata_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                runtime_context_hash="host-context-a",
                runtime_context_chars=1000,
            )
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                runtime_context_hash="sidecar-context-b",
                runtime_context_chars=1000,
            )
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("runtime context metadata regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_router_decision_fingerprint_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            RouterDecisionEvent(
                tier="standard",
                model="openai/gpt-router",
                source="squilla-router",
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            RouterDecisionEvent(
                tier="fallback",
                model="openai/gpt-router",
                source="squilla-router",
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("router decision parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_router_decisions() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            RouterDecisionEvent(
                tier="standard",
                model="openai/gpt-router",
                source="squilla-router",
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("router decision metadata regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_router_replay_fingerprint_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            RouterControlReplayEvent(
                action="switch_model",
                target_tier="standard",
                target_model="openai/gpt-router",
                target_provider="openrouter",
                target_id="router-1",
                replay_depth=1,
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            RouterControlReplayEvent(
                action="switch_model",
                target_tier="standard",
                target_model="openai/gpt-fallback",
                target_provider="manual",
                target_id="router-2",
                replay_depth=1,
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("router replay parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_normalizes_legacy_router_tier_aliases() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            RouterDecisionEvent(
                tier="c3",
                model="openai/gpt-router",
                source="squilla-router",
            ),
            RouterControlReplayEvent(
                action="switch_model",
                target_tier="c3",
                target_model="openai/gpt-router",
                target_provider="openrouter",
                target_id="tier:c3",
                replay_depth=1,
            ),
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                routed_model="openai/gpt-router",
                routed_tier="c3",
                routing_source="squilla-router",
            ),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            RouterDecisionEvent(
                tier="t3",
                model="openai/gpt-router",
                source="squilla-router",
            ),
            RouterControlReplayEvent(
                action="switch_model",
                target_tier="t3",
                target_model="openai/gpt-router",
                target_provider="openrouter",
                target_id="tier:t3",
                replay_depth=1,
            ),
            DoneEvent(
                text="ok",
                input_tokens=100,
                output_tokens=20,
                routed_model="openai/gpt-router",
                routed_tier="t3",
                routing_source="squilla-router",
            ),
        ]
    )

    assert (
        compare_agent_core_metrics(
            baseline=baseline,
            candidate=candidate,
            candidate_name="pi",
        )
        == []
    )


def test_agent_core_metric_comparison_flags_extra_router_replays() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            RouterControlReplayEvent(
                action="switch_model",
                target_tier="standard",
                target_model="openai/gpt-router",
                target_provider="openrouter",
                target_id="router-1",
                replay_depth=1,
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("router replay metadata regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_missing_tool_calls_and_token_accounting() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            ToolUseStartEvent(tool_use_id="tool-1", tool_name="echo"),
            ToolResultEvent(tool_use_id="tool-1", tool_name="echo", result="ok"),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics([DoneEvent(text="ok")])

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("tool call count regressed" in violation for violation in violations)
    assert any("token accounting missing" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_tool_calls() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ToolUseStartEvent(tool_use_id="tool-1", tool_name="echo"),
            ToolResultEvent(tool_use_id="tool-1", tool_name="echo", result="ok"),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("tool call count regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_terminal_failure() -> None:
    baseline = collect_agent_core_run_metrics([DoneEvent(text="ok")])
    candidate = collect_agent_core_run_metrics([ErrorEvent(message="boom", code="pi_error")])

    assert compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    ) == ["pi failed terminal success: boom"]


def test_agent_core_metric_comparison_flags_final_text_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="LIVE_AGENT_CORE_PARITY", input_tokens=10, output_tokens=3)]
    )
    candidate = collect_agent_core_run_metrics(
        [DoneEvent(text="wrong final answer", input_tokens=10, output_tokens=3)]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("final text regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_final_text() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="", input_tokens=10, output_tokens=0)]
    )
    candidate = collect_agent_core_run_metrics(
        [DoneEvent(text="sidecar final text", input_tokens=10, output_tokens=3)]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("final text regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_stream_text() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=10, output_tokens=2)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            TextDeltaEvent(text="sidecar stream"),
            DoneEvent(text="ok", input_tokens=10, output_tokens=2),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("stream text parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_projection_and_yield_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            ToolUseStartEvent(tool_use_id="tool-1", tool_name="echo"),
            ToolResultEvent(
                tool_use_id="tool-1",
                tool_name="echo",
                result="projected host result",
                arguments={"path": "/tmp/a"},
            ),
            ToolResultEvent(
                tool_use_id="yield-1",
                tool_name="sessions_yield",
                result='{"status":"yielded","waited":false}',
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ToolUseStartEvent(tool_use_id="tool-1", tool_name="echo"),
            ToolResultEvent(
                tool_use_id="tool-1",
                tool_name="echo",
                result="raw sidecar result",
                arguments={"path": "/tmp/a"},
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("tool result projection regressed" in violation for violation in violations)
    assert any("yield/subagent result count regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_tool_results() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ToolResultEvent(
                tool_use_id="tool-1",
                tool_name="echo",
                result="sidecar injected result",
                arguments={"value": "ok"},
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("tool result projection regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_orchestration_results() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ToolResultEvent(
                tool_use_id="spawn-1",
                tool_name="sessions_spawn",
                result='{"session_key":"agent:main:child"}',
                arguments={"prompt": "work"},
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("tool result projection regressed" in violation for violation in violations)
    assert any(
        "orchestration result parity regressed" in violation
        for violation in violations
    )


def test_agent_core_metric_comparison_flags_extra_yield_results() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            ToolResultEvent(
                tool_use_id="yield-1",
                tool_name="sessions_yield",
                result='{"status":"yielded"}',
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ToolResultEvent(
                tool_use_id="yield-1",
                tool_name="sessions_yield",
                result='{"status":"yielded"}',
            ),
            ToolResultEvent(
                tool_use_id="yield-2",
                tool_name="sessions_yield",
                result='{"status":"yielded"}',
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("yield/subagent result count regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_tool_execution_status_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            ToolResultEvent(
                tool_use_id="tool-1",
                tool_name="exec_command",
                result="ok",
                execution_status={
                    "version": 1,
                    "status": "succeeded",
                    "timed_out": False,
                    "truncated": False,
                },
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ToolResultEvent(
                tool_use_id="tool-1",
                tool_name="exec_command",
                result="ok",
                execution_status={
                    "version": 1,
                    "status": "timeout",
                    "timed_out": True,
                    "truncated": False,
                },
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("tool result projection regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_orchestration_result_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            ToolResultEvent(
                tool_use_id="spawn-1",
                tool_name="sessions_spawn",
                result='{"session_key":"agent:main:child"}',
                arguments={"prompt": "work"},
            ),
            ToolResultEvent(
                tool_use_id="yield-1",
                tool_name="sessions_yield",
                result='{"status":"yielded","waited":true}',
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ToolResultEvent(
                tool_use_id="spawn-1",
                tool_name="sessions_spawn",
                result='{"session_key":"agent:main:other"}',
                arguments={"prompt": "work"},
            ),
            ToolResultEvent(
                tool_use_id="yield-1",
                tool_name="sessions_yield",
                result='{"status":"yielded","waited":false}',
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any(
        "orchestration result parity regressed" in violation
        for violation in violations
    )


    baseline = collect_agent_core_run_metrics(
        [
            ArtifactEvent(
                id="artifact-1",
                sha256="abc123",
                name="report.txt",
                mime="text/plain",
                size=42,
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("artifact event parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_artifact_regressions() -> None:
    baseline = collect_agent_core_run_metrics(
        [
            ArtifactEvent(
                id="artifact-1",
                sha256="abc123",
                name="report.txt",
                mime="text/plain",
                size=42,
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ArtifactEvent(
                id="artifact-1",
                sha256="def456",
                name="report.txt",
                mime="text/plain",
                size=44,
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("artifact event parity regressed" in violation for violation in violations)


def test_agent_core_metric_comparison_flags_extra_artifacts() -> None:
    baseline = collect_agent_core_run_metrics(
        [DoneEvent(text="ok", input_tokens=100, output_tokens=20)]
    )
    candidate = collect_agent_core_run_metrics(
        [
            ArtifactEvent(
                id="artifact-1",
                sha256="abc123",
                name="report.txt",
                mime="text/plain",
                size=42,
            ),
            DoneEvent(text="ok", input_tokens=100, output_tokens=20),
        ]
    )

    violations = compare_agent_core_metrics(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("artifact event parity regressed" in violation for violation in violations)
