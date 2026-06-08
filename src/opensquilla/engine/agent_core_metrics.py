"""Parity metrics for selectable agent kernels.

These helpers are intentionally runtime-neutral: they consume the public
``AgentEvent`` stream so old OpenSquilla, the new selectable OpenSquilla path,
and Pi adapters can be compared without changing CLI/TUI contracts.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from opensquilla.engine.types import (
    AgentEvent,
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


@dataclass(frozen=True)
class AgentCoreRunMetrics:
    """Comparable per-run health and cost metrics."""

    terminal_success: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    billed_cost: float = 0.0
    tool_calls: int = 0
    tool_successes: int = 0
    tool_errors: int = 0
    router_decision_count: int = 0
    router_control_replay_count: int = 0
    router_decision_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    routed_models: tuple[str, ...] = field(default_factory=tuple)
    routing_sources: tuple[str, ...] = field(default_factory=tuple)
    routing_applied_states: tuple[bool, ...] = field(default_factory=tuple)
    cache_hit_active_states: tuple[bool, ...] = field(default_factory=tuple)
    runtime_context_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    done_metadata_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    router_replay_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    heartbeat_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    state_change_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    thinking_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    warning_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    compaction_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    tool_result_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    yield_result_count: int = 0
    orchestration_result_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    artifact_fingerprints: tuple[str, ...] = field(default_factory=tuple)
    stream_text: str = ""
    final_text: str = ""
    session_total_input_tokens: int | None = None
    session_total_output_tokens: int | None = None
    session_total_cache_read_tokens: int | None = None
    session_total_cache_write_tokens: int | None = None
    session_total_cost_usd: float | None = None
    session_total_billed_cost_usd: float | None = None
    error_messages: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.reasoning_tokens

    @property
    def tool_success_rate(self) -> float:
        observed_results = self.tool_successes + self.tool_errors
        denominator = max(self.tool_calls, observed_results)
        if denominator <= 0:
            return 1.0
        return self.tool_successes / denominator

    @property
    def kv_cache_hit_rate(self) -> float:
        if self.input_tokens <= 0:
            return 0.0
        return self.cached_tokens / self.input_tokens


@dataclass(frozen=True)
class AgentCoreParityThresholds:
    """Allowed live-test drift for nondeterministic model calls."""

    max_total_token_ratio: float = 1.10
    total_token_slack: int = 32
    min_tool_success_rate_delta: float = 0.0
    min_kv_cache_hit_rate_delta: float = -0.05
    max_cost_ratio: float = 1.10
    cost_slack_usd: float = 0.001



_ORCHESTRATION_TOOL_NAMES = frozenset(
    {"sessions_spawn", "sessions_send", "sessions_yield"}
)


def _json_fingerprint_payload(payload: object) -> str:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Agent-core parity fingerprint payload must be JSON-compatible"
        ) from exc


def _non_negative_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"{field_name} must be a non-negative integer")
    return value


def _int_less_than_or_equal(
    value: int,
    *,
    limit: int,
    field_name: str,
    limit_field_name: str,
) -> None:
    if value > limit:
        raise RuntimeError(
            f"{field_name} must be less than or equal to {limit_field_name}"
        )


def _finite_number(value: object, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RuntimeError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"{field_name} must be a finite number")
    return number


def _non_negative_number(value: object, *, field_name: str) -> float:
    number = _finite_number(value, field_name=field_name)
    if number < 0.0:
        raise RuntimeError(f"{field_name} must be a finite non-negative number")
    return number


def _probability_number(value: object, *, field_name: str) -> float:
    number = _non_negative_number(value, field_name=field_name)
    if number > 1.0:
        raise RuntimeError(f"{field_name} must be a probability")
    return number


def _probability_list(value: object, *, field_name: str) -> None:
    if not isinstance(value, list) or any(
        not isinstance(item, (int, float))
        or isinstance(item, bool)
        or not math.isfinite(float(item))
        or float(item) < 0.0
        or float(item) > 1.0
        for item in value
    ):
        raise RuntimeError(f"{field_name} must be a list of probabilities")


def _number_at_least(
    value: object,
    *,
    minimum: float,
    field_name: str,
) -> float:
    number = _finite_number(value, field_name=field_name)
    if number < minimum:
        raise RuntimeError(f"{field_name} must be at least {minimum}")
    return number


def _string_value(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{field_name} must be a string")
    return value


def _optional_string_value(value: object, *, field_name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise RuntimeError(f"{field_name} must be a string or None")
    return value


def _string_tuple_value(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(f"{field_name} must be a tuple of strings")
    return value


def _bool_tuple_value(value: object, *, field_name: str) -> tuple[bool, ...]:
    if not isinstance(value, tuple) or any(not isinstance(item, bool) for item in value):
        raise RuntimeError(f"{field_name} must be a tuple of booleans")
    return value


def _validate_done_event_accounting(event: DoneEvent) -> None:
    for field_name in (
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "iterations",
        "runtime_context_chars",
        "cache_write_tokens",
    ):
        _non_negative_int(getattr(event, field_name), field_name=field_name)
    _int_less_than_or_equal(
        event.cached_tokens,
        limit=event.input_tokens,
        field_name="cached_tokens",
        limit_field_name="input_tokens",
    )
    _int_less_than_or_equal(
        event.cache_write_tokens,
        limit=event.input_tokens,
        field_name="cache_write_tokens",
        limit_field_name="input_tokens",
    )
    for field_name in ("cost_usd", "billed_cost"):
        _non_negative_number(getattr(event, field_name), field_name=field_name)

    for field_name in (
        "savings_pct",
        "savings_usd",
        "total_savings_pct",
        "total_savings_usd",
    ):
        _non_negative_number(getattr(event, field_name), field_name=field_name)
    _probability_number(event.routing_confidence, field_name="routing_confidence")

    for field_name in (
        "text",
        "model",
        "cost_source",
        "routing_source",
        "baseline_model",
        "routed_model",
        "rollout_phase",
    ):
        _string_value(getattr(event, field_name), field_name=field_name)

    for field_name in (
        "reasoning_content",
        "runtime_context_hash",
        "routed_tier",
    ):
        _optional_string_value(getattr(event, field_name), field_name=field_name)

    session_totals = event.session_totals
    if session_totals is None:
        return
    for field_name in (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        _non_negative_int(
            getattr(session_totals, field_name),
            field_name=f"session_totals.{field_name}",
        )
    _int_less_than_or_equal(
        session_totals.cache_read_tokens,
        limit=session_totals.input_tokens,
        field_name="session_totals.cache_read_tokens",
        limit_field_name="session_totals.input_tokens",
    )
    _int_less_than_or_equal(
        session_totals.cache_write_tokens,
        limit=session_totals.input_tokens,
        field_name="session_totals.cache_write_tokens",
        limit_field_name="session_totals.input_tokens",
    )
    for field_name in ("cost_usd", "billed_cost"):
        _non_negative_number(
            getattr(session_totals, field_name),
            field_name=f"session_totals.{field_name}",
        )


def _validate_run_metrics(metrics: AgentCoreRunMetrics, *, label: str) -> None:
    if not isinstance(metrics.terminal_success, bool):
        raise RuntimeError(f"{label}.terminal_success must be a boolean")

    for field_name in (
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "tool_calls",
        "tool_successes",
        "tool_errors",
        "router_decision_count",
        "router_control_replay_count",
        "yield_result_count",
    ):
        _non_negative_int(
            getattr(metrics, field_name),
            field_name=f"{label}.{field_name}",
        )
    _int_less_than_or_equal(
        metrics.cached_tokens,
        limit=metrics.input_tokens,
        field_name=f"{label}.cached_tokens",
        limit_field_name=f"{label}.input_tokens",
    )
    _int_less_than_or_equal(
        metrics.cache_write_tokens,
        limit=metrics.input_tokens,
        field_name=f"{label}.cache_write_tokens",
        limit_field_name=f"{label}.input_tokens",
    )
    observed_tool_results = metrics.tool_successes + metrics.tool_errors
    if metrics.tool_result_fingerprints:
        if observed_tool_results != len(metrics.tool_result_fingerprints):
            raise RuntimeError(
                f"{label}.tool result count must equal "
                f"{label}.tool_result_fingerprints"
            )
    else:
        _int_less_than_or_equal(
            observed_tool_results,
            limit=metrics.tool_calls,
            field_name=f"{label}.tool result count",
            limit_field_name=f"{label}.tool_calls or "
            f"{label}.tool_result_fingerprints",
        )
    for field_name in ("cost_usd", "billed_cost"):
        _non_negative_number(
            getattr(metrics, field_name),
            field_name=f"{label}.{field_name}",
        )

    for field_name in (
        "session_total_input_tokens",
        "session_total_output_tokens",
        "session_total_cache_read_tokens",
        "session_total_cache_write_tokens",
    ):
        value = getattr(metrics, field_name)
        if value is not None:
            _non_negative_int(value, field_name=f"{label}.{field_name}")
    if metrics.session_total_input_tokens is not None:
        if metrics.session_total_cache_read_tokens is not None:
            _int_less_than_or_equal(
                metrics.session_total_cache_read_tokens,
                limit=metrics.session_total_input_tokens,
                field_name=f"{label}.session_total_cache_read_tokens",
                limit_field_name=f"{label}.session_total_input_tokens",
            )
        if metrics.session_total_cache_write_tokens is not None:
            _int_less_than_or_equal(
                metrics.session_total_cache_write_tokens,
                limit=metrics.session_total_input_tokens,
                field_name=f"{label}.session_total_cache_write_tokens",
                limit_field_name=f"{label}.session_total_input_tokens",
            )

    for field_name in ("session_total_cost_usd", "session_total_billed_cost_usd"):
        value = getattr(metrics, field_name)
        if value is not None:
            _non_negative_number(value, field_name=f"{label}.{field_name}")

    for field_name in (
        "router_decision_fingerprints",
        "routed_models",
        "routing_sources",
        "runtime_context_fingerprints",
        "done_metadata_fingerprints",
        "router_replay_fingerprints",
        "heartbeat_fingerprints",
        "state_change_fingerprints",
        "thinking_fingerprints",
        "warning_fingerprints",
        "compaction_fingerprints",
        "tool_result_fingerprints",
        "orchestration_result_fingerprints",
        "artifact_fingerprints",
        "error_messages",
    ):
        _string_tuple_value(getattr(metrics, field_name), field_name=f"{label}.{field_name}")

    _bool_tuple_value(
        metrics.routing_applied_states,
        field_name=f"{label}.routing_applied_states",
    )
    _bool_tuple_value(
        metrics.cache_hit_active_states,
        field_name=f"{label}.cache_hit_active_states",
    )

    for field_name in ("stream_text", "final_text"):
        _string_value(getattr(metrics, field_name), field_name=f"{label}.{field_name}")


def _validate_parity_thresholds(thresholds: AgentCoreParityThresholds) -> None:
    _number_at_least(
        thresholds.max_total_token_ratio,
        minimum=1.0,
        field_name="max_total_token_ratio",
    )
    _non_negative_int(
        thresholds.total_token_slack,
        field_name="total_token_slack",
    )
    _non_negative_number(
        thresholds.min_tool_success_rate_delta,
        field_name="min_tool_success_rate_delta",
    )
    _number_at_least(
        thresholds.min_kv_cache_hit_rate_delta,
        minimum=-1.0,
        field_name="min_kv_cache_hit_rate_delta",
    )
    _number_at_least(
        thresholds.max_cost_ratio,
        minimum=1.0,
        field_name="max_cost_ratio",
    )
    _non_negative_number(
        thresholds.cost_slack_usd,
        field_name="cost_slack_usd",
    )


def _tool_result_fingerprint(event: ToolResultEvent) -> str:
    arguments = _json_fingerprint_payload(event.arguments or {})
    execution_status = _json_fingerprint_payload(event.execution_status or {})
    status = "error" if event.is_error else "ok"
    return f"{event.tool_name}|{event.result}|{arguments}|{status}|{execution_status}"


def _artifact_fingerprint(event: ArtifactEvent) -> str:
    size = _non_negative_int(event.size, field_name="artifact size")
    return f"{event.name}|{event.mime}|{size}|{event.sha256}"


def _heartbeat_fingerprint(event: RunHeartbeatEvent) -> str:
    payload = {
        "elapsed_ms": _non_negative_int(
            event.elapsed_ms,
            field_name="heartbeat elapsed_ms",
        ),
        "idle_ms": _non_negative_int(
            event.idle_ms,
            field_name="heartbeat idle_ms",
        ),
        "message": event.message,
        "phase": event.phase,
    }
    return _json_fingerprint_payload(payload)


def _thinking_fingerprint(event: ThinkingEvent) -> str:
    payload = {"text": event.text}
    return _json_fingerprint_payload(payload)


def _state_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _state_change_fingerprint(event: StateChangeEvent) -> str:
    payload = {
        "from_state": _state_value(event.from_state),
        "to_state": _state_value(event.to_state),
    }
    return _json_fingerprint_payload(payload)


def _warning_fingerprint(event: WarningEvent) -> str:
    payload = {
        "code": event.code,
        "message": event.message,
    }
    return _json_fingerprint_payload(payload)


def _compaction_fingerprint(event: CompactionEvent) -> str:
    payload = {
        "compaction_id": event.compaction_id,
        "summary": event.summary,
        "kept_entries": event.kept_entries,
        "kept_count": _non_negative_int(
            event.kept_count,
            field_name="compaction kept_count",
        ),
        "removed_count": _non_negative_int(
            event.removed_count,
            field_name="compaction removed_count",
        ),
    }
    return _json_fingerprint_payload(payload)


def _canonical_router_tier(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip().lower()
    return {
        "t0": "c0",
        "t1": "c1",
        "t2": "c2",
        "t3": "c3",
        "c0": "c0",
        "c1": "c1",
        "c2": "c2",
        "c3": "c3",
    }.get(raw, value)


def _canonical_router_target_id(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw.startswith("tier:"):
        return value
    tier = _canonical_router_tier(raw.removeprefix("tier:"))
    return f"tier:{tier}" if tier else value


def _router_decision_fingerprint(event: RouterDecisionEvent) -> str:
    payload = {
        "tier": _canonical_router_tier(event.tier),
        "model": event.model,
        "source": event.source,
    }
    return _json_fingerprint_payload(payload)


def _router_replay_fingerprint(event: RouterControlReplayEvent) -> str:
    payload = {
        "action": event.action,
        "target_tier": _canonical_router_tier(event.target_tier),
        "target_model": event.target_model,
        "target_provider": event.target_provider,
        "target_id": _canonical_router_target_id(event.target_id),
        "replay_depth": event.replay_depth,
    }
    return _json_fingerprint_payload(payload)


def _meaningful_metadata_values(values: tuple[str, ...]) -> set[str]:
    return {value for value in values if value and value.lower() != "none"}


def _normalized_final_text(value: str) -> str:
    return value.strip()


def collect_agent_core_run_metrics(events: Iterable[AgentEvent]) -> AgentCoreRunMetrics:
    """Summarize an ``AgentEvent`` stream for kernel parity comparison."""

    done_events: list[DoneEvent] = []
    errors: list[str] = []
    tool_calls = 0
    tool_successes = 0
    tool_errors = 0
    router_decision_count = 0
    router_control_replay_count = 0
    router_decision_fingerprints: list[str] = []
    routed_models: list[str] = []
    routing_sources: list[str] = []
    router_replay_fingerprints: list[str] = []
    heartbeat_fingerprints: list[str] = []
    state_change_fingerprints: list[str] = []
    thinking_fingerprints: list[str] = []
    warning_fingerprints: list[str] = []
    compaction_fingerprints: list[str] = []
    tool_result_fingerprints: list[str] = []
    yield_result_count = 0
    orchestration_result_fingerprints: list[str] = []
    artifact_fingerprints: list[str] = []
    text_deltas: list[str] = []
    terminal_seen = False

    for event in events:
        if terminal_seen:
            if isinstance(event, DoneEvent) and done_events:
                raise RuntimeError("AgentEvent stream must contain at most one DoneEvent")
            raise RuntimeError("AgentEvent stream must not emit events after terminal event")
        if isinstance(event, TextDeltaEvent):
            text_deltas.append(event.text)
        elif isinstance(event, ToolUseStartEvent):
            tool_calls += 1
        elif isinstance(event, ToolResultEvent):
            fingerprint = _tool_result_fingerprint(event)
            tool_result_fingerprints.append(fingerprint)
            if event.tool_name in _ORCHESTRATION_TOOL_NAMES:
                orchestration_result_fingerprints.append(fingerprint)
            if event.tool_name == "sessions_yield":
                yield_result_count += 1
            if event.is_error:
                tool_errors += 1
            else:
                tool_successes += 1
        elif isinstance(event, ErrorEvent):
            errors.append(event.message)
            terminal_seen = True
        elif isinstance(event, DoneEvent):
            _validate_done_event_accounting(event)
            done_events.append(event)
            terminal_seen = True
            routed_model = event.routed_model or event.model
            if routed_model:
                routed_models.append(routed_model)
            if event.routing_source:
                routing_sources.append(event.routing_source)
        elif isinstance(event, RouterDecisionEvent):
            _probability_number(
                event.confidence,
                field_name="router decision confidence",
            )
            _probability_list(
                event.probs,
                field_name="router decision probs",
            )
            router_decision_count += 1
            router_decision_fingerprints.append(_router_decision_fingerprint(event))
            if event.model:
                routed_models.append(event.model)
            if event.source:
                routing_sources.append(event.source)
        elif isinstance(event, RouterControlReplayEvent):
            _non_negative_int(
                event.replay_depth,
                field_name="router replay depth",
            )
            router_control_replay_count += 1
            router_replay_fingerprints.append(_router_replay_fingerprint(event))
            if event.target_model:
                routed_models.append(event.target_model)
        elif isinstance(event, ArtifactEvent):
            artifact_fingerprints.append(_artifact_fingerprint(event))
        elif isinstance(event, RunHeartbeatEvent):
            heartbeat_fingerprints.append(_heartbeat_fingerprint(event))
        elif isinstance(event, StateChangeEvent):
            state_change_fingerprints.append(_state_change_fingerprint(event))
        elif isinstance(event, ThinkingEvent):
            thinking_fingerprints.append(_thinking_fingerprint(event))
        elif isinstance(event, WarningEvent):
            warning_fingerprints.append(_warning_fingerprint(event))
        elif isinstance(event, CompactionEvent):
            compaction_fingerprints.append(_compaction_fingerprint(event))

    session_totals = next(
        (
            event.session_totals
            for event in reversed(done_events)
            if event.session_totals is not None
        ),
        None,
    )
    if len(done_events) > 1:
        raise RuntimeError("AgentEvent stream must contain at most one DoneEvent")
    if not done_events and not errors:
        raise RuntimeError("AgentEvent stream must contain a terminal DoneEvent or ErrorEvent")

    return AgentCoreRunMetrics(
        terminal_success=bool(done_events) and not errors,
        input_tokens=sum(event.input_tokens for event in done_events),
        output_tokens=sum(event.output_tokens for event in done_events),
        cached_tokens=sum(event.cached_tokens for event in done_events),
        cache_write_tokens=sum(event.cache_write_tokens for event in done_events),
        reasoning_tokens=sum(event.reasoning_tokens for event in done_events),
        cost_usd=sum(event.cost_usd for event in done_events),
        billed_cost=sum(event.billed_cost for event in done_events),
        tool_calls=tool_calls,
        tool_successes=tool_successes,
        tool_errors=tool_errors,
        router_decision_count=router_decision_count,
        router_control_replay_count=router_control_replay_count,
        router_decision_fingerprints=tuple(router_decision_fingerprints),
        routed_models=tuple(dict.fromkeys(routed_models)),
        routing_sources=tuple(dict.fromkeys(routing_sources)),
        routing_applied_states=tuple(event.routing_applied for event in done_events),
        cache_hit_active_states=tuple(event.cache_hit_active for event in done_events),
        runtime_context_fingerprints=tuple(
            _json_fingerprint_payload(
                {
                    "runtime_context_chars": event.runtime_context_chars,
                    "runtime_context_hash": event.runtime_context_hash,
                }
            )
            for event in done_events
        ),
        done_metadata_fingerprints=tuple(
            _json_fingerprint_payload(
                {
                    "baseline_model": event.baseline_model,
                    "cost_source": event.cost_source,
                    "model": event.model,
                    "routed_model": event.routed_model,
                    "routed_tier": _canonical_router_tier(event.routed_tier),
                    "routing_confidence": event.routing_confidence,
                    "routing_source": event.routing_source,
                    "rollout_phase": event.rollout_phase,
                }
            )
            for event in done_events
        ),
        router_replay_fingerprints=tuple(router_replay_fingerprints),
        heartbeat_fingerprints=tuple(heartbeat_fingerprints),
        state_change_fingerprints=tuple(state_change_fingerprints),
        thinking_fingerprints=tuple(thinking_fingerprints),
        warning_fingerprints=tuple(warning_fingerprints),
        compaction_fingerprints=tuple(compaction_fingerprints),
        tool_result_fingerprints=tuple(tool_result_fingerprints),
        yield_result_count=yield_result_count,
        orchestration_result_fingerprints=tuple(orchestration_result_fingerprints),
        artifact_fingerprints=tuple(artifact_fingerprints),
        stream_text="".join(text_deltas),
        final_text=done_events[-1].text if done_events else "",
        session_total_input_tokens=(
            session_totals.input_tokens if session_totals is not None else None
        ),
        session_total_output_tokens=(
            session_totals.output_tokens if session_totals is not None else None
        ),
        session_total_cache_read_tokens=(
            session_totals.cache_read_tokens if session_totals is not None else None
        ),
        session_total_cache_write_tokens=(
            session_totals.cache_write_tokens if session_totals is not None else None
        ),
        session_total_cost_usd=session_totals.cost_usd if session_totals is not None else None,
        session_total_billed_cost_usd=(
            session_totals.billed_cost if session_totals is not None else None
        ),
        error_messages=tuple(errors),
    )


def compare_agent_core_metrics(
    *,
    baseline: AgentCoreRunMetrics,
    candidate: AgentCoreRunMetrics,
    candidate_name: str,
    thresholds: AgentCoreParityThresholds | None = None,
) -> list[str]:
    """Return human-readable violations where ``candidate`` is weaker."""

    limits = thresholds or AgentCoreParityThresholds()
    _validate_run_metrics(baseline, label="baseline")
    _validate_run_metrics(candidate, label="candidate")
    _validate_parity_thresholds(limits)
    violations: list[str] = []

    if baseline.terminal_success and not candidate.terminal_success:
        detail = "; ".join(candidate.error_messages) or "no terminal DoneEvent"
        violations.append(f"{candidate_name} failed terminal success: {detail}")

    baseline_final_text = _normalized_final_text(baseline.final_text)
    candidate_final_text = _normalized_final_text(candidate.final_text)
    if candidate.terminal_success and candidate_final_text != baseline_final_text:
        violations.append(
            f"{candidate_name} final text regressed: "
            f"{candidate.final_text!r} != {baseline.final_text!r}"
        )

    baseline_stream_text = _normalized_final_text(baseline.stream_text)
    candidate_stream_text = _normalized_final_text(candidate.stream_text)
    if candidate_stream_text != baseline_stream_text:
        violations.append(
            f"{candidate_name} stream text parity regressed: "
            f"{candidate.stream_text!r} != {baseline.stream_text!r}"
        )

    if candidate.tool_calls != baseline.tool_calls:
        violations.append(
            f"{candidate_name} tool call count regressed: "
            f"{candidate.tool_calls} != {baseline.tool_calls}"
        )

    min_tool_success_rate = baseline.tool_success_rate + limits.min_tool_success_rate_delta
    if candidate.tool_success_rate < min_tool_success_rate:
        violations.append(
            f"{candidate_name} tool success rate regressed: "
            f"{candidate.tool_success_rate:.3f} < {min_tool_success_rate:.3f} "
            f"(baseline {baseline.tool_success_rate:.3f})"
        )
    if candidate.tool_errors > baseline.tool_errors:
        violations.append(
            f"{candidate_name} tool error count regressed: "
            f"{candidate.tool_errors} > {baseline.tool_errors}"
        )

    if baseline.total_tokens > 0 and candidate.total_tokens <= 0:
        violations.append(
            f"{candidate_name} token accounting missing: "
            f"candidate reported {candidate.total_tokens} tokens"
        )

    if baseline.input_tokens > 0 and candidate.input_tokens <= 0:
        violations.append(
            f"{candidate_name} input token accounting missing: "
            f"candidate reported {candidate.input_tokens}"
        )

    if baseline.output_tokens > 0 and candidate.output_tokens <= 0:
        violations.append(
            f"{candidate_name} output token accounting missing: "
            f"candidate reported {candidate.output_tokens}"
        )

    if baseline.reasoning_tokens > 0 and candidate.reasoning_tokens <= 0:
        violations.append(
            f"{candidate_name} reasoning token accounting missing: "
            f"candidate reported {candidate.reasoning_tokens}"
        )

    if baseline.cached_tokens > 0 and candidate.cached_tokens <= 0:
        violations.append(
            f"{candidate_name} cached tokens missing: "
            f"candidate reported {candidate.cached_tokens}"
        )

    allowed_total_tokens = (
        int(baseline.total_tokens * limits.max_total_token_ratio) + limits.total_token_slack
    )
    if candidate.total_tokens > allowed_total_tokens:
        violations.append(
            f"{candidate_name} total tokens regressed: "
            f"{candidate.total_tokens} > allowed {allowed_total_tokens} "
            f"(baseline {baseline.total_tokens})"
        )

    allowed_input_tokens = (
        int(baseline.input_tokens * limits.max_total_token_ratio)
        + limits.total_token_slack
    )
    if candidate.input_tokens > allowed_input_tokens:
        violations.append(
            f"{candidate_name} input tokens regressed: "
            f"{candidate.input_tokens} > allowed {allowed_input_tokens} "
            f"(baseline {baseline.input_tokens})"
        )

    allowed_output_tokens = (
        int(baseline.output_tokens * limits.max_total_token_ratio)
        + limits.total_token_slack
    )
    if candidate.output_tokens > allowed_output_tokens:
        violations.append(
            f"{candidate_name} output tokens regressed: "
            f"{candidate.output_tokens} > allowed {allowed_output_tokens} "
            f"(baseline {baseline.output_tokens})"
        )

    allowed_reasoning_tokens = (
        int(baseline.reasoning_tokens * limits.max_total_token_ratio)
        + limits.total_token_slack
    )
    if candidate.reasoning_tokens > allowed_reasoning_tokens:
        violations.append(
            f"{candidate_name} reasoning tokens regressed: "
            f"{candidate.reasoning_tokens} > allowed {allowed_reasoning_tokens} "
            f"(baseline {baseline.reasoning_tokens})"
        )

    if baseline.cache_write_tokens > 0 and candidate.cache_write_tokens <= 0:
        violations.append(
            f"{candidate_name} cache write tokens missing: "
            f"candidate reported {candidate.cache_write_tokens}"
        )
    allowed_cache_write_tokens = (
        int(baseline.cache_write_tokens * limits.max_total_token_ratio)
        + limits.total_token_slack
    )
    if candidate.cache_write_tokens > allowed_cache_write_tokens:
        violations.append(
            f"{candidate_name} cache write tokens regressed: "
            f"{candidate.cache_write_tokens} > allowed {allowed_cache_write_tokens} "
            f"(baseline {baseline.cache_write_tokens})"
        )

    min_cache_rate = baseline.kv_cache_hit_rate + limits.min_kv_cache_hit_rate_delta
    if candidate.kv_cache_hit_rate < min_cache_rate:
        violations.append(
            f"{candidate_name} KV cache hit rate regressed: "
            f"{candidate.kv_cache_hit_rate:.3f} < {min_cache_rate:.3f} "
            f"(baseline {baseline.kv_cache_hit_rate:.3f})"
        )

    if baseline.cost_usd > 0.0 and candidate.cost_usd <= 0.0:
        violations.append(
            f"{candidate_name} cost accounting missing: "
            f"candidate reported {candidate.cost_usd:.6f} USD"
        )

    allowed_cost = baseline.cost_usd * limits.max_cost_ratio + limits.cost_slack_usd
    if candidate.cost_usd > allowed_cost:
        violations.append(
            f"{candidate_name} cost regressed: "
            f"{candidate.cost_usd:.6f} > allowed {allowed_cost:.6f} "
            f"(baseline {baseline.cost_usd:.6f})"
        )

    if baseline.billed_cost > 0.0 and candidate.billed_cost <= 0.0:
        violations.append(
            f"{candidate_name} billed cost accounting missing: "
            f"candidate reported {candidate.billed_cost:.6f} USD"
        )

    allowed_billed_cost = (
        baseline.billed_cost * limits.max_cost_ratio + limits.cost_slack_usd
    )
    if candidate.billed_cost > allowed_billed_cost:
        violations.append(
            f"{candidate_name} billed cost regressed: "
            f"{candidate.billed_cost:.6f} > allowed {allowed_billed_cost:.6f} "
            f"(baseline {baseline.billed_cost:.6f})"
        )

    if candidate.router_decision_count != baseline.router_decision_count:
        violations.append(
            f"{candidate_name} router decision metadata regressed: "
            f"{candidate.router_decision_count} != {baseline.router_decision_count}"
        )

    if (
        baseline.router_decision_fingerprints
        and candidate.router_decision_fingerprints != baseline.router_decision_fingerprints
    ):
        violations.append(
            f"{candidate_name} router decision parity regressed: "
            f"{candidate.router_decision_fingerprints!r} "
            f"!= {baseline.router_decision_fingerprints!r}"
        )

    if candidate.router_control_replay_count != baseline.router_control_replay_count:
        violations.append(
            f"{candidate_name} router replay metadata regressed: "
            f"{candidate.router_control_replay_count} != {baseline.router_control_replay_count}"
        )

    if (
        baseline.router_replay_fingerprints
        and candidate.router_replay_fingerprints != baseline.router_replay_fingerprints
    ):
        violations.append(
            f"{candidate_name} router replay parity regressed: "
            f"{candidate.router_replay_fingerprints!r} "
            f"!= {baseline.router_replay_fingerprints!r}"
        )

    if candidate.heartbeat_fingerprints != baseline.heartbeat_fingerprints:
        violations.append(
            f"{candidate_name} heartbeat parity regressed: "
            f"{candidate.heartbeat_fingerprints!r} "
            f"!= {baseline.heartbeat_fingerprints!r}"
        )

    if candidate.thinking_fingerprints != baseline.thinking_fingerprints:
        violations.append(
            f"{candidate_name} thinking parity regressed: "
            f"{candidate.thinking_fingerprints!r} "
            f"!= {baseline.thinking_fingerprints!r}"
        )

    if candidate.state_change_fingerprints != baseline.state_change_fingerprints:
        violations.append(
            f"{candidate_name} state-change parity regressed: "
            f"{candidate.state_change_fingerprints!r} "
            f"!= {baseline.state_change_fingerprints!r}"
        )

    if candidate.warning_fingerprints != baseline.warning_fingerprints:
        violations.append(
            f"{candidate_name} warning parity regressed: "
            f"{candidate.warning_fingerprints!r} "
            f"!= {baseline.warning_fingerprints!r}"
        )

    if candidate.compaction_fingerprints != baseline.compaction_fingerprints:
        violations.append(
            f"{candidate_name} compaction parity regressed: "
            f"{candidate.compaction_fingerprints!r} "
            f"!= {baseline.compaction_fingerprints!r}"
        )

    baseline_routed_models = _meaningful_metadata_values(baseline.routed_models)
    candidate_routed_models = _meaningful_metadata_values(candidate.routed_models)
    if candidate_routed_models != baseline_routed_models:
        violations.append(
            f"{candidate_name} routed model metadata regressed: "
            f"{candidate.routed_models!r} != {baseline.routed_models!r}"
        )

    baseline_routing_sources = _meaningful_metadata_values(baseline.routing_sources)
    candidate_routing_sources = _meaningful_metadata_values(candidate.routing_sources)
    if candidate_routing_sources != baseline_routing_sources:
        violations.append(
            f"{candidate_name} routing source metadata regressed: "
            f"{candidate.routing_sources!r} != {baseline.routing_sources!r}"
        )

    if (
        candidate.terminal_success
        and candidate.routing_applied_states != baseline.routing_applied_states
    ):
        violations.append(
            f"{candidate_name} routing applied metadata regressed: "
            f"{candidate.routing_applied_states!r} "
            f"!= {baseline.routing_applied_states!r}"
        )

    if (
        candidate.terminal_success
        and candidate.cache_hit_active_states != baseline.cache_hit_active_states
    ):
        violations.append(
            f"{candidate_name} cache hit active metadata regressed: "
            f"{candidate.cache_hit_active_states!r} "
            f"!= {baseline.cache_hit_active_states!r}"
        )

    if (
        candidate.terminal_success
        and candidate.runtime_context_fingerprints
        != baseline.runtime_context_fingerprints
    ):
        violations.append(
            f"{candidate_name} runtime context metadata regressed: "
            f"{candidate.runtime_context_fingerprints!r} "
            f"!= {baseline.runtime_context_fingerprints!r}"
        )

    if (
        candidate.terminal_success
        and candidate.done_metadata_fingerprints != baseline.done_metadata_fingerprints
    ):
        violations.append(
            f"{candidate_name} terminal done metadata regressed: "
            f"{candidate.done_metadata_fingerprints!r} "
            f"!= {baseline.done_metadata_fingerprints!r}"
        )

    if candidate.tool_result_fingerprints != baseline.tool_result_fingerprints:
        violations.append(
            f"{candidate_name} tool result projection regressed: "
            f"{candidate.tool_result_fingerprints!r} != {baseline.tool_result_fingerprints!r}"
        )

    if candidate.yield_result_count != baseline.yield_result_count:
        violations.append(
            f"{candidate_name} yield/subagent result count regressed: "
            f"{candidate.yield_result_count} != {baseline.yield_result_count}"
        )

    if (
        candidate.orchestration_result_fingerprints
        != baseline.orchestration_result_fingerprints
    ):
        violations.append(
            f"{candidate_name} orchestration result parity regressed: "
            f"{candidate.orchestration_result_fingerprints!r} "
            f"!= {baseline.orchestration_result_fingerprints!r}"
        )

    if candidate.artifact_fingerprints != baseline.artifact_fingerprints:
        violations.append(
            f"{candidate_name} artifact event parity regressed: "
            f"{candidate.artifact_fingerprints!r} != {baseline.artifact_fingerprints!r}"
        )

    baseline_session_totals = (
        baseline.session_total_input_tokens,
        baseline.session_total_output_tokens,
        baseline.session_total_cache_read_tokens,
        baseline.session_total_cache_write_tokens,
        baseline.session_total_cost_usd,
        baseline.session_total_billed_cost_usd,
    )
    candidate_session_totals = (
        candidate.session_total_input_tokens,
        candidate.session_total_output_tokens,
        candidate.session_total_cache_read_tokens,
        candidate.session_total_cache_write_tokens,
        candidate.session_total_cost_usd,
        candidate.session_total_billed_cost_usd,
    )
    if any(value is not None for value in baseline_session_totals) and not any(
        value is not None for value in candidate_session_totals
    ):
        violations.append(f"{candidate_name} session totals missing")
    if not any(value is not None for value in baseline_session_totals) and any(
        value is not None for value in candidate_session_totals
    ):
        violations.append(f"{candidate_name} session totals unexpected")

    def _allowed_session_token_total(baseline_value: int | None) -> int:
        return (
            int((baseline_value or 0) * limits.max_total_token_ratio)
            + limits.total_token_slack
        )

    def _allowed_session_cost_total(baseline_value: float | None) -> float:
        return (baseline_value or 0.0) * limits.max_cost_ratio + limits.cost_slack_usd

    def _compare_session_token_total(
        label: str,
        baseline_value: int | None,
        candidate_value: int | None,
    ) -> None:
        if baseline_value is None:
            if candidate_value is not None:
                violations.append(
                    f"{candidate_name} session {label} total unexpected: "
                    f"{candidate_value}"
                )
            return
        if candidate_value is None:
            violations.append(f"{candidate_name} session {label} total missing")
            return
        baseline_total = baseline_value
        candidate_total = candidate_value
        if baseline_total > 0 and candidate_total < baseline_total:
            violations.append(
                f"{candidate_name} session {label} total regressed: "
                f"{candidate_value} < {baseline_value}"
            )
        allowed_total = _allowed_session_token_total(baseline_value)
        if candidate_total > allowed_total:
            violations.append(
                f"{candidate_name} session {label} total regressed: "
                f"{candidate_value} > allowed {allowed_total} "
                f"(baseline {baseline_value})"
            )

    def _compare_session_cost_total(
        label: str,
        baseline_value: float | None,
        candidate_value: float | None,
    ) -> None:
        if baseline_value is None:
            if candidate_value is not None:
                violations.append(
                    f"{candidate_name} session {label} total unexpected: "
                    f"{candidate_value}"
                )
            return
        if candidate_value is None:
            violations.append(f"{candidate_name} session {label} total missing")
            return
        baseline_total = baseline_value
        candidate_total = candidate_value
        if baseline_total > 0.0 and candidate_total < baseline_total:
            violations.append(
                f"{candidate_name} session {label} total regressed: "
                f"{candidate_value} < {baseline_value}"
            )
        allowed_total = _allowed_session_cost_total(baseline_value)
        if candidate_total > allowed_total:
            violations.append(
                f"{candidate_name} session {label} total regressed: "
                f"{candidate_value} > allowed {allowed_total:.6f} "
                f"(baseline {baseline_value})"
            )

    _compare_session_token_total(
        "input",
        baseline.session_total_input_tokens,
        candidate.session_total_input_tokens,
    )
    _compare_session_token_total(
        "output",
        baseline.session_total_output_tokens,
        candidate.session_total_output_tokens,
    )
    _compare_session_token_total(
        "cache read",
        baseline.session_total_cache_read_tokens,
        candidate.session_total_cache_read_tokens,
    )
    _compare_session_token_total(
        "cache write",
        baseline.session_total_cache_write_tokens,
        candidate.session_total_cache_write_tokens,
    )
    _compare_session_cost_total(
        "cost",
        baseline.session_total_cost_usd,
        candidate.session_total_cost_usd,
    )
    _compare_session_cost_total(
        "billed cost",
        baseline.session_total_billed_cost_usd,
        candidate.session_total_billed_cost_usd,
    )

    return violations
