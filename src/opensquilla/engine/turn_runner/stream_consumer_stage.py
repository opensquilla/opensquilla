"""Stage object for the agent stream consumer loop.

Owns the per-turn slice between the attachment stage boundary
and the post-stream transcript-persist boundary: the
pre-loop accumulator declarations, the
``async for event in agent.run_turn(...)`` body, and the post-stream
sync-manager notify call.

Departs from the ``StageOutcome`` uniformity: this stage is an
async generator. Each ``AgentEvent`` the agent produces is forwarded
through the stage (after optional in-place rewrite) so downstream
consumers (WebUI, CLI, channels) keep their per-event streaming
contract. Terminal state for the post-stream surface flows
through the harness-owned ``_StreamState`` value object the stage
mutates in place.

Compaction refresh preservation: the ``_CompactionHandler`` fires the
supplied ``CompactionHook`` observers around the success-only three-step
``persist -> snapshot refresh -> system-prompt refresh`` sequence. The
``persist_compaction_result`` re-entrancy contract is preserved -- the
adapter forwards the call verbatim and the IN-TURN path remains the
only call site after the previous extraction landed.

No ``TurnHook`` is fired from inside the stream loop today.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

import structlog

from opensquilla.engine.hooks.types import CompactionState
from opensquilla.engine.tool_text_compat import ProtocolTextLeakGuard
from opensquilla.observability.decision_log import build_vision_followup_gate_reason_code

if TYPE_CHECKING:
    from opensquilla.engine.agent import Agent
    from opensquilla.engine.agent_injection import PendingInputProvider
    from opensquilla.engine.hooks.types import CompactionHook
    from opensquilla.engine.types import (
        AgentEvent,
        ArtifactEvent,
        CompactionEvent,
        DoneEvent,
        ErrorEvent,
        TextDeltaEvent,
        ToolResultEvent,
        ToolUseStartEvent,
        WarningEvent,
    )

log = structlog.get_logger(__name__)

# Sentinel for "this event was consumed and should NOT be yielded
# downstream" (CompactionEvent + ErrorEvent take this path -- the
# loop continues instead of yielding).
_SUPPRESS: Final = object()

# ---------------------------------------------------------------------------
# Ports -- five narrow Protocols + one callable
# ---------------------------------------------------------------------------

@runtime_checkable
class AgentRunPort(Protocol):
    """Wrap ``agent.run_turn(turn_input, extra_messages=..., **kwargs)``.

    Returns the async iterator the agent produces; the stage consumes
    it via ``async for``. The port handles the ``_accepts_keyword_arg``
    introspection for ``semantic_message`` so the stage body has no
    ``inspect``-based branching. The agent is supplied per-call so a
    single stage instance can serve every turn.
    """

    def run_turn(
        self,
        agent: Agent,
        *,
        turn_input: str,
        extra_messages: list[Any] | None,
        semantic_message: str | None,
        pending_input_provider: PendingInputProvider | None = None,
    ) -> AsyncIterator[AgentEvent]: ...

@runtime_checkable
class CompactionPersistPort(Protocol):
    """Persist the IN-TURN ``CompactionEvent`` result + notify cache monitor.

    Wraps ``SessionManager.persist_compaction_result(session_key, summary,
    kept_entries)`` followed by a completed lifecycle notification. The
    stage handles persistence failures by emitting a failed lifecycle
    notification and preserving pre-refresh runtime state.

    Compaction refresh: This is the only remaining call site for
    ``persist_compaction_result``. The compaction contract requires the
    call to remain re-entrant -- the Agent has already mutated its
    in-memory message list before the runner sees ``CompactionEvent``,
    so the DB transcript may have more entries than ``kept_entries``.
    The stage forwards the call verbatim.
    """

    async def persist_and_notify(
        self,
        *,
        session_key: str,
        summary: str,
        kept_entries: list[Any],
        compaction_id: str | None = None,
    ) -> None: ...

@runtime_checkable
class MemorySnapshotRefreshPort(Protocol):
    """Refresh ``_memory_snapshots[(agent_id, session_key)]`` after compaction.

    Wraps the resolve-workspace + load-memory-md + load-daily-notes +
    dict-write sequence. The adapter respects ``private_memory_allowed``:
    when false, the dict is not written.

    Compaction refresh: the frozen system-prompt snapshot lives in this dict;
    the design note "the in-turn path must keep emitting
    through CompactionEvent so TurnRunner can update the frozen
    system-prompt snapshot ... before the next turn" is satisfied by
    refreshing here, BEFORE the agent's next iteration runs.
    """

    def refresh_snapshot(
        self,
        *,
        agent_id: str,
        session_key: str,
        private_memory_allowed: bool,
    ) -> None: ...

@runtime_checkable
class SystemPromptRefreshPort(Protocol):
    """Rebuild + apply the cacheable system-prompt base after compaction.

    Wraps the ``_assemble_prompt(...)`` call + the tuple-vs-str extract
    + ``agent.refresh_system_prompt(refreshed_prompt)``.

    Compaction refresh: the post-compaction prompt rebuild MUST extract the
    cacheable base (not the full ``(base, dynamic_suffix)`` tuple) --
    feeding the tuple directly into ``agent.refresh_system_prompt``
    would smuggle volatile bytes into ``ChatConfig.system`` and raise
    ``ValidationError`` on the next turn. The adapter handles the
    extract; the stage cannot bypass it.
    """

    def refresh_system_prompt(
        self,
        *,
        agent: Agent,
        agent_id: str,
        tool_defs: list[Any],
        session_key: str,
        bootstrap_context_mode: str | None,
    ) -> None: ...

@runtime_checkable
class MemorySyncNotifyPort(Protocol):
    """Notify ``sync_manager.notify_message(byte_count)`` post-stream.

    Fires exactly once after the ``async for`` exits cleanly. The
    adapter handles the ``sync_manager is None`` guard so the stage
    body has no conditional.
    """

    def notify_message_bytes(
        self,
        sync_manager: Any | None,
        runtime_message: str,
    ) -> None: ...

# Callable signature for runtime warning transformation. Implemented as a
# plain callable rather than a Protocol because it is a single-method
# contract and the recording-fake discipline applies identically.
WarningTransformer = Callable[["WarningEvent"], "WarningEvent"]

# ---------------------------------------------------------------------------
# Stream state -- four owned + four pass-by-reference accumulators
# ---------------------------------------------------------------------------

@dataclass
class _StreamState:
    """Mutable accumulators shared across the stage's event handlers.

    Owned by the harness (created in ``_run_turn``, passed in as
    ``inp.state``), mutated by handler classes inside the stage. The
    stage does NOT mutate ``TurnContext`` directly -- it writes through
    this state object the harness owns.

    Four fields move INTO this object from the inline body. Four
    fields STAY on the harness-level ``_run_turn`` body and are
    PASSED IN as mutable references -- the outer ``CancelledError``
    handler reads them after the stream loop. Wrapping each mutation
    into a yielded state-delta envelope would balloon LOC and harm
    readability for zero behavioral benefit.
    """

    # Moved INTO stage scope (declared inline before the stage extraction).
    current_text_parts: list[str] = field(default_factory=list)
    error_message: str | None = None
    pending_error_event: ErrorEvent | None = None
    done_event: DoneEvent | None = None
    protocol_text_guard: ProtocolTextLeakGuard = field(
        default_factory=ProtocolTextLeakGuard
    )

    # PASSED IN by the harness -- references, not copies.
    final_text_parts: list[str] = field(default_factory=list)
    turn_segments: list[dict] = field(default_factory=list)
    turn_artifacts: list[dict[str, Any]] = field(default_factory=list)
    artifact_delivery_failures: list[str] = field(default_factory=list)
    completed_meta_skill_without_text: str | None = None

# ---------------------------------------------------------------------------
# Stage I/O dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StreamConsumerStageInput:
    """Inputs the StreamConsumerStage needs at its boundary.

    Pulled from earlier-stage ``TurnContext`` accumulators by the
    harness. The ``state`` field is intentionally NOT frozen -- the
    stage mutates it in place.
    """

    # From AgentBootstrapStage
    agent: Agent
    agent_id: str
    sync_manager: Any  # MemorySyncManager | None
    private_memory_allowed: bool

    # From PromptAssemblerStage
    turn: Any  # post-pipeline pipeline.TurnContext
    tool_defs: list[Any]

    # From AttachmentStage
    turn_input: str
    extra_messages: list[Any] | None

    # From InputStage
    semantic_input: str
    effective_runtime_message: str

    # From _run_turn locals
    session_key: str
    run_kind: str
    heartbeat_ack_max_chars: int
    bootstrap_context_mode: str | None

    # From runner (read by handlers without needing a runner reference)
    router_cfg: Any | None
    session_manager_present: bool

    # Mutable shared accumulators (passed by reference)
    state: _StreamState

    # Effective tool context for runtime-generated delivery backstops.
    tool_context: Any | None = None
    # Original input provenance for runtime-generated disclosures.
    input_provenance: dict[str, Any] | None = None
    # In-process pending submitted-line provider for mid-turn injection.
    pending_input_provider: PendingInputProvider | None = None

# ---------------------------------------------------------------------------
# Per-event handler classes
# ---------------------------------------------------------------------------

def _has_tool_boundary(state: _StreamState) -> bool:
    return any(
        segment.get("type") in {"tool_use", "tool_result"}
        for segment in state.turn_segments
    )


def _normalize_cumulative_text_delta(text: str, state: _StreamState) -> str:
    """Convert a post-tool cumulative text snapshot back into a delta."""

    if not text or not _has_tool_boundary(state):
        return text

    accumulated_text = "".join(state.final_text_parts)
    if not accumulated_text:
        return text
    if text == accumulated_text:
        return ""
    if text.startswith(accumulated_text):
        return text[len(accumulated_text) :]
    return text


class _TextDeltaHandler:
    """Accumulate streamed text deltas into the final-text and current-text buffers."""

    def handle(
        self,
        event: TextDeltaEvent,
        state: _StreamState,
    ) -> TextDeltaEvent:
        cleaned_delta = _normalize_cumulative_text_delta(
            state.protocol_text_guard.push(event.text),
            state,
        )
        if cleaned_delta:
            state.final_text_parts.append(cleaned_delta)
            state.current_text_parts.append(cleaned_delta)
        return replace(event, text=cleaned_delta)

class _ToolUseStartHandler:
    """Strip synthetic-tool-call text, flush the current text segment, append tool_use segment.

    Implements the canonical ToolUseStart handling -- the
    synthetic-text strip rewrites ``final_text_parts`` and
    ``current_text_parts`` in place when the agent emitted a synthetic
    tool call with prefix text it now wants stripped.
    """

    def handle(
        self,
        event: ToolUseStartEvent,
        state: _StreamState,
    ) -> ToolUseStartEvent:
        # Late import keeps the module import-cycle-free.
        from opensquilla.engine.tool_text_compat import (
            strip_synthetic_tool_call_text,
        )

        pending_text = state.protocol_text_guard.flush_before_tool_use()
        if pending_text:
            state.final_text_parts.append(pending_text)
            state.current_text_parts.append(pending_text)

        if event.synthetic_from_text and state.current_text_parts:
            raw_current_text = "".join(state.current_text_parts)
            cleaned_current_text = strip_synthetic_tool_call_text(
                raw_current_text,
                event.tool_name,
            )
            if cleaned_current_text != raw_current_text:
                full_text = "".join(state.final_text_parts)
                if full_text.endswith(raw_current_text):
                    prefix = full_text[: -len(raw_current_text)]
                    # Replace the list contents in place to preserve the
                    # caller's reference to the shared list.
                    state.final_text_parts[:] = [prefix + cleaned_current_text]
                else:
                    state.final_text_parts[:] = [
                        strip_synthetic_tool_call_text(
                            full_text,
                            event.tool_name,
                        )
                    ]
                state.current_text_parts[:] = (
                    [cleaned_current_text] if cleaned_current_text else []
                )
        if state.current_text_parts:
            state.turn_segments.append(
                {"type": "text", "text": "".join(state.current_text_parts)}
            )
            state.current_text_parts[:] = []
        state.turn_segments.append(
            {
                "type": "tool_use",
                "tool_use_id": event.tool_use_id,
                "name": event.tool_name,
                "input": "",
            }
        )
        return event

class _ToolResultHandler:
    """Capture artifact-delivery failures and append the tool_result segment."""

    def handle(
        self,
        event: ToolResultEvent,
        state: _StreamState,
    ) -> ToolResultEvent:
        # Late imports keep the module import-cycle-free.
        from opensquilla.engine.runtime import (
            _artifact_delivery_failure_summary,
            _persisted_tool_result_segment,
            _persisted_tool_use_input,
        )

        failure_summary = _artifact_delivery_failure_summary(event)
        if failure_summary is not None:
            state.artifact_delivery_failures.append(failure_summary)
        if _is_completed_meta_invoke(event):
            state.completed_meta_skill_without_text = _meta_invoke_skill_name(event)
        if event.arguments is not None:
            for segment in reversed(state.turn_segments):
                if (
                    segment.get("type") == "tool_use"
                    and segment.get("tool_use_id") == event.tool_use_id
                ):
                    segment["name"] = event.tool_name
                    segment["input"] = _persisted_tool_use_input(
                        event.tool_name,
                        event.tool_use_id,
                        event.arguments,
                    )
                    break
        result_segment = _persisted_tool_result_segment(event)
        for index in range(len(state.turn_segments) - 1, -1, -1):
            segment = state.turn_segments[index]
            if (
                segment.get("type") == "tool_result"
                and segment.get("tool_use_id") == event.tool_use_id
            ):
                state.turn_segments[index] = result_segment
                break
        else:
            state.turn_segments.append(result_segment)
        return event

class _ArtifactHandler:
    """Append an artifact payload to the per-turn artifact list."""

    def handle(
        self,
        event: ArtifactEvent,
        state: _StreamState,
    ) -> ArtifactEvent:
        from opensquilla.artifacts import artifact_payload

        state.turn_artifacts.append(artifact_payload(event))
        return event

class _ErrorHandler:
    """Rewrite timeout envelopes, drop unpaired tool_use, capture pending error.

    Returns ``_SUPPRESS`` -- the loop continues without
    yielding (the pending error event is yielded post-stream by the
    finalizer stage after transcript persist).
    """

    def handle(
        self,
        event: ErrorEvent,
        state: _StreamState,
    ) -> object:
        from opensquilla.engine.runtime import (
            _LLM_TIMEOUT_ENVELOPE,
            _drop_unpaired_tool_use_segments,
        )
        from opensquilla.engine.types import ErrorEvent as _ErrorEvent

        if event.code == "timeout":
            event = _ErrorEvent(
                message=_LLM_TIMEOUT_ENVELOPE["user_message"],
                code=_LLM_TIMEOUT_ENVELOPE["error_class"],
            )
        if event.code in {"incomplete_tool_stream", "provider_output_truncated"}:
            state.turn_segments[:] = _drop_unpaired_tool_use_segments(
                state.turn_segments
            )
        state.error_message = event.message or "Unknown error"
        state.pending_error_event = event
        return _SUPPRESS

class _WarningHandler:
    """Forward warnings to the runner's runtime-warning transformer."""

    def __init__(self, transformer: WarningTransformer) -> None:
        self._transformer = transformer

    def handle(self, event: WarningEvent) -> WarningEvent:
        return self._transformer(event)

class _DoneHandler:
    """Apply routing-tier metadata, savings, normalize text, emit notices.

    Largest single handler. Returns ``(transformed_done_event,
    extra_yields)`` where ``extra_yields`` is the (possibly empty) list
    of events the outer stage must yield BEFORE the DoneEvent itself --
    the artifact-delivery-failure notice TextDelta and/or the
    hallucination Warning yield, in the original order.
    """

    def handle(
        self,
        event: DoneEvent,
        inp: StreamConsumerStageInput,
        state: _StreamState,
    ) -> tuple[DoneEvent, list[AgentEvent]]:
        from opensquilla.engine.artifact_delivery import (
            auto_publish_omitted_workspace_artifacts,
        )
        from opensquilla.engine.runtime import (
            _artifact_delivery_failure_notice,
            _claims_image_without_tool_use,
            _compute_comprehensive_turn_savings,
            _compute_route_input_savings_usd,
            _normalize_heartbeat_text,
            _should_add_artifact_delivery_failure_notice,
        )
        from opensquilla.engine.types import (
            WarningEvent as _WarningEvent,
        )

        turn = inp.turn
        metadata = turn.metadata

        pending_text = state.protocol_text_guard.flush()
        if pending_text:
            state.final_text_parts.append(pending_text)
            state.current_text_parts.append(pending_text)

        from opensquilla.engine.tool_text_compat import strip_protocol_text_leak

        normalized_text = strip_protocol_text_leak(
            _normalize_heartbeat_text(
                event.text,
                run_kind=inp.run_kind,
                heartbeat_ack_max_chars=inp.heartbeat_ack_max_chars,
            )
        )
        routed_tier = metadata.get("routed_tier")
        routing_source = metadata.get("routing_source", "none")
        routing_confidence = float(metadata.get("routing_confidence") or 0.0)
        routing_applied = metadata.get("routing_applied")
        if routing_applied is None:
            routing_applied = True
        rollout_phase = str(metadata.get("rollout_phase") or "full")
        baseline_model = metadata.get("baseline_model", "")
        routed_model = metadata.get("routed_model", "") or event.model
        savings_pct = float(metadata.get("savings_pct") or 0.0)
        _max_p = float(metadata.get("savings_max_price_per_m") or 0.0)
        _rte_p = float(metadata.get("savings_routed_price_per_m") or 0.0)
        savings_usd = _compute_route_input_savings_usd(
            _max_p,
            _rte_p,
            event.input_tokens,
        )
        router_cfg = inp.router_cfg
        squilla_router_tiers = getattr(router_cfg, "tiers", {})
        estimated_output_savings_pct = getattr(
            router_cfg,
            "estimated_output_savings_pct",
            0.03,
        )
        comprehensive = _compute_comprehensive_turn_savings(
            event,
            metadata,
            squilla_router_tiers,
            routed_model,
            estimated_output_savings_pct=estimated_output_savings_pct,
        )
        provider_cache_hit = (event.cached_tokens or 0) > 0
        opensquilla_cache_hit = metadata.get("cache_mode") == "hit"
        event = replace(
            event,
            text=normalized_text,
            routed_tier=routed_tier,
            routing_source=routing_source or "none",
            routing_confidence=routing_confidence,
            routing_applied=bool(routing_applied),
            rollout_phase=rollout_phase,
            baseline_model=baseline_model,
            routed_model=routed_model,
            savings_pct=savings_pct,
            savings_usd=savings_usd,
            cache_hit_active=provider_cache_hit or opensquilla_cache_hit,
            total_savings_pct=comprehensive.pct,
            total_savings_usd=comprehensive.usd,
            image_route_reason=metadata.get("image_route_reason"),
            vision_followup_gate_decision=metadata.get(
                "router_vision_followup_gate_decision"
            ),
            vision_followup_gate_confidence=metadata.get(
                "router_vision_followup_gate_confidence"
            ),
            vision_followup_gate_reason=build_vision_followup_gate_reason_code(
                decision=metadata.get("router_vision_followup_gate_decision"),
                source=metadata.get("router_vision_followup_gate_source"),
                reason=metadata.get("router_vision_followup_gate_reason"),
                fallback=metadata.get("router_vision_followup_fallback"),
            ),
            vision_followup_gate_source=metadata.get(
                "router_vision_followup_gate_source"
            ),
            vision_followup_gate_model=metadata.get("router_vision_followup_gate_model"),
            vision_followup_needs_image=metadata.get("router_vision_followup_needs_image"),
            vision_followup_fallback=metadata.get("router_vision_followup_fallback"),
        )
        state.done_event = event

        if normalized_text and not state.final_text_parts:
            state.final_text_parts.append(normalized_text)
            if state.turn_segments:
                state.current_text_parts.append(normalized_text)

        accumulated_text = "".join(state.final_text_parts)
        extra_yields: list[AgentEvent] = []
        if accumulated_text.strip() and not event.text.strip():
            event = replace(event, text=accumulated_text)
            state.done_event = event
        if not accumulated_text.strip() and state.completed_meta_skill_without_text:
            event, fallback_event = _append_done_notice_delta(
                event,
                state,
                _meta_completed_without_text_notice(
                    state.completed_meta_skill_without_text
                ),
                accumulated_text=accumulated_text,
            )
            extra_yields.append(fallback_event)
            accumulated_text = "".join(state.final_text_parts)
        from opensquilla.engine.types import ArtifactEvent as _ArtifactEvent

        omitted_publish_result = auto_publish_omitted_workspace_artifacts(
            inp.tool_context,
            final_text=accumulated_text,
        )
        for artifact in omitted_publish_result.artifacts:
            artifact_event = _ArtifactEvent(**artifact)
            state.turn_artifacts.append(artifact)
            extra_yields.append(artifact_event)
        state.artifact_delivery_failures.extend(
            omitted_publish_result.failure_summaries
        )

        if _should_add_artifact_delivery_failure_notice(
            failure_summaries=state.artifact_delivery_failures,
            turn_artifacts=state.turn_artifacts,
            final_text=accumulated_text,
        ):
            event, notice_event = _append_done_notice_delta(
                event,
                state,
                _artifact_delivery_failure_notice(partial=bool(state.turn_artifacts)),
                accumulated_text=accumulated_text,
            )
            extra_yields.append(notice_event)

        accumulated_text = "".join(state.final_text_parts)
        disclosure = _subagent_partial_failure_disclosure(inp.input_provenance)
        if disclosure is not None:
            event, notice_event = _append_done_notice_delta(
                event,
                state,
                disclosure,
                accumulated_text=accumulated_text,
            )
            extra_yields.append(notice_event)

        accumulated_text = "".join(state.final_text_parts)
        if _claims_image_without_tool_use(
            accumulated_text, turn.tool_defs, state.turn_segments
        ):
            extra_yields.append(
                _WarningEvent(
                    code="image_generate_claimed_without_call",
                    message=(
                        "The assistant described a generated image but did not "
                        "call an image-generation tool. No image was produced."
                    ),
                )
            )
        return event, extra_yields


def _append_done_notice_delta(
    event: DoneEvent,
    state: _StreamState,
    notice: str,
    *,
    accumulated_text: str,
) -> tuple[DoneEvent, AgentEvent]:
    from opensquilla.engine.types import TextDeltaEvent as _TextDeltaEvent

    separator = "\n\n" if accumulated_text.strip() else ""
    notice_delta = separator + notice
    state.final_text_parts.append(notice_delta)
    state.current_text_parts.append(notice_delta)
    event = replace(event, text="".join(state.final_text_parts))
    state.done_event = event
    return event, _TextDeltaEvent(text=notice_delta)


def _is_completed_meta_invoke(event: ToolResultEvent) -> bool:
    if event.tool_name != "meta_invoke" or event.is_error:
        return False
    result = event.result.strip().lower()
    return "meta-skill" in result and "completed" in result


def _meta_invoke_skill_name(event: ToolResultEvent) -> str:
    arguments = event.arguments if isinstance(event.arguments, dict) else {}
    candidate = arguments.get("name")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return "meta skill"


def _meta_completed_without_text_notice(skill_name: str) -> str:
    return (
        f"Meta skill `{skill_name}` 已完成，但这次流程没有生成可展示的最终回答。"
        "请查看上方步骤结果和产物；如果需要，可以补充更明确的输出要求后重新运行。"
    )


def _subagent_partial_failure_disclosure(
    input_provenance: dict[str, Any] | None,
) -> str | None:
    if not isinstance(input_provenance, dict):
        return None
    required = input_provenance.get("runtime_partial_failure_disclosure_required") is True
    outcome = input_provenance.get("subagent_group_outcome")
    if not isinstance(outcome, dict):
        if required:
            raise RuntimeError(
                "subagent partial failure disclosure required but outcome metadata is missing"
            )
        return None
    non_success = _int_value(outcome.get("non_success"))
    if non_success <= 0:
        return None
    total = _int_value(outcome.get("total"))
    succeeded = _int_value(outcome.get("succeeded"))
    failures = _format_subagent_failure_children(outcome.get("failed_children"))
    suffix = f"; failures: {failures}" if failures else ""
    return f"Subagents: {succeeded}/{total} succeeded{suffix}."


def _format_subagent_failure_children(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for child in value[:3]:
        if not isinstance(child, dict):
            continue
        child_id = _first_text(
            child.get("child_session_key"),
            child.get("task_id"),
            child.get("agent_id"),
            default="unknown child",
        )
        status = _first_text(child.get("status"), default="non-success")
        reason = _first_text(child.get("terminal_reason"), default="")
        detail = f"{child_id} {status}"
        if reason:
            detail = f"{detail} ({reason})"
        error = _format_subagent_failure_error(child)
        if error:
            detail = f"{detail}: {error}"
        parts.append(detail)
    remaining = len(value) - len(parts)
    if remaining > 0:
        parts.append(f"{remaining} more")
    return "; ".join(parts)


def _format_subagent_failure_error(child: dict[str, Any]) -> str:
    error_class = _first_text(child.get("error_class"), default="")
    error_message = _first_text(child.get("error_message"), default="")
    if error_class in {"current_turn_context_exhausted", "provider_request_too_large"}:
        return "provider_request_too_large"
    if error_message and len(error_message) > 160:
        error_message = f"{error_message[:157]}..."
    if error_class and error_message:
        return f"{error_class}: {error_message}"
    return error_message or error_class


def _first_text(*values: Any, default: str) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return default


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

class _CompactionHandler:
    """Persist compaction and refresh memory snapshot + system prompt.

    The success order persist -> snapshot -> prompt is load-bearing per the
    compaction contract (the Agent has already mutated its
    in-memory history; the DB transcript must be brought into sync
    first, then the next turn's snapshot dependencies refreshed). The
    persist call is wrapped so durable failures emit failed lifecycle feedback
    and stop before snapshot/prompt refresh can manufacture a false compacted
    runtime view.

    Does NOT yield -- ``CompactionEvent`` is internal-only.
    """

    def __init__(
        self,
        *,
        persist: CompactionPersistPort,
        memory_snapshot: MemorySnapshotRefreshPort,
        system_prompt: SystemPromptRefreshPort,
        compaction_hooks: tuple[CompactionHook, ...] = (),
    ) -> None:
        self._persist = persist
        self._memory_snapshot = memory_snapshot
        self._system_prompt = system_prompt
        self._compaction_hooks = compaction_hooks

    async def handle(
        self,
        event: CompactionEvent,
        inp: StreamConsumerStageInput,
    ) -> None:
        state = CompactionState(
            session_key=inp.session_key,
            agent_id=inp.agent_id,
            extra={
                "phase": "in_turn_stream",
                "summary": event.summary,
                "kept_entries": event.kept_entries,
            },
        )
        await self._fire_before_compact(state)
        if inp.session_manager_present:
            try:
                await self._persist.persist_and_notify(
                    session_key=inp.session_key,
                    summary=event.summary,
                    kept_entries=event.kept_entries,
                    compaction_id=event.compaction_id,
                )
            except Exception as exc:  # noqa: BLE001 - preserve turn recoverability
                log.warning("compaction_persist_failed", error=str(exc))
                from opensquilla.engine.cache_break_monitor import notify_compaction
                from opensquilla.session.compaction_lifecycle import (
                    COMPACTION_TRIGGERED_EVENT,
                    compaction_effect_payload,
                    compaction_lifecycle_payload,
                    new_compaction_id,
                )

                compaction_id = event.compaction_id or new_compaction_id()

                notify_compaction(
                    inp.session_key,
                    source="automatic",
                    phase="agent_inline_overflow",
                    status="failed",
                    reason="persist_failed",
                    message=str(exc),
                    kept_count=len(event.kept_entries),
                    summary_len=len(event.summary or ""),
                    **compaction_effect_payload(status="failed", reason="persist_failed"),
                    **compaction_lifecycle_payload(
                        compaction_id,
                        COMPACTION_TRIGGERED_EVENT,
                    ),
                )
                await self._fire_after_compact(
                    state,
                    {
                        "status": "failed",
                        "reason": "persist_failed",
                        "message": str(exc),
                    },
                )
                return

        self._memory_snapshot.refresh_snapshot(
            agent_id=inp.agent_id,
            session_key=inp.session_key,
            private_memory_allowed=inp.private_memory_allowed,
        )
        self._system_prompt.refresh_system_prompt(
            agent=inp.agent,
            agent_id=inp.agent_id,
            tool_defs=inp.tool_defs,
            session_key=inp.session_key,
            bootstrap_context_mode=inp.bootstrap_context_mode,
        )
        await self._fire_after_compact(
            state,
            {
                "status": "completed",
                "summary": event.summary,
                "kept_entries": event.kept_entries,
            },
        )

    async def _fire_before_compact(self, state: CompactionState) -> None:
        for hook in self._compaction_hooks:
            try:
                await hook.before_compact(state)
            except Exception:  # noqa: BLE001 - hook isolation contract
                pass

    async def _fire_after_compact(
        self,
        state: CompactionState,
        outcome: dict[str, Any],
    ) -> None:
        for hook in self._compaction_hooks:
            try:
                await hook.after_compact(state, outcome)
            except Exception:  # noqa: BLE001 - hook isolation contract
                pass

# ---------------------------------------------------------------------------
# Outer stage class
# ---------------------------------------------------------------------------

class StreamConsumerStage:
    """Consume the agent stream and yield events; persist mid-stream side effects.

    Stable boundary: runs ONCE per turn, after AttachmentStage and
    before TurnFinalizerStage. The five ports execute as follows:

    1. ``AgentRunPort.run_turn`` -- one async iterator started; the
       stage owns the lifetime of the consumer loop.
    2. Per ``CompactionEvent``, conditionally:
       a. ``CompactionPersistPort.persist_and_notify``.
       b. ``MemorySnapshotRefreshPort.refresh_snapshot``.
       c. ``SystemPromptRefreshPort.refresh_system_prompt``.
    3. Post-stream: ``MemorySyncNotifyPort.notify_message_bytes`` -- one
       call after the loop exits cleanly.

    Async-generator signature -- the FIRST TurnRunner stage that does NOT
    return ``StageOutcome``. Each yielded value is forwarded by the
    harness to its own caller. Terminal state for flows
    through ``inp.state`` (the harness-owned ``_StreamState``).

    Exception model: the stream loop propagates ``CancelledError``
    unchanged (the outer ``_run_turn`` CancelledError handler owns the
    partial-persist behavior). Other exceptions propagate to the outer
    terminal handler. The ``_CompactionHandler`` wraps its persist call
    in a log-and-continue try/except so transient persistence failures
    do not abort the surrounding turn.

    ``CompactionHook`` observers supplied by the runner fire around
    in-turn ``CompactionEvent`` handling only; hook exceptions are
    isolated and do not change the stream outcome.
    """

    name = "stream_consumer_stage"

    def __init__(
        self,
        *,
        agent_run: AgentRunPort,
        compaction_persist: CompactionPersistPort,
        memory_snapshot_refresh: MemorySnapshotRefreshPort,
        system_prompt_refresh: SystemPromptRefreshPort,
        memory_sync_notify: MemorySyncNotifyPort,
        warning_transformer: WarningTransformer,
        compaction_hooks: tuple[CompactionHook, ...] = (),
    ) -> None:
        self._agent_run = agent_run
        self._memory_sync_notify = memory_sync_notify

        self._text_delta_handler = _TextDeltaHandler()
        self._tool_use_start_handler = _ToolUseStartHandler()
        self._tool_result_handler = _ToolResultHandler()
        self._artifact_handler = _ArtifactHandler()
        self._error_handler = _ErrorHandler()
        self._warning_handler = _WarningHandler(warning_transformer)
        self._done_handler = _DoneHandler()
        self._compaction_handler = _CompactionHandler(
            persist=compaction_persist,
            memory_snapshot=memory_snapshot_refresh,
            system_prompt=system_prompt_refresh,
            compaction_hooks=compaction_hooks,
        )

    async def run(
        self,
        inp: StreamConsumerStageInput,
    ) -> AsyncIterator[AgentEvent]:
        # Late imports keep the module import-cycle-free.
        from opensquilla.engine.types import (
            ArtifactEvent,
            CompactionEvent,
            DoneEvent,
            ErrorEvent,
            TextDeltaEvent,
            ToolResultEvent,
            ToolUseDeltaEvent,
            ToolUseStartEvent,
            WarningEvent,
        )

        state = inp.state
        async for event in self._agent_run.run_turn(
            inp.agent,
            turn_input=inp.turn_input,
            extra_messages=inp.extra_messages,
            semantic_message=inp.semantic_input,
            pending_input_provider=inp.pending_input_provider,
        ):
            transformed: AgentEvent | object
            extra_yields: list[AgentEvent] = []
            if isinstance(event, TextDeltaEvent):
                transformed = self._text_delta_handler.handle(event, state)
            elif isinstance(event, ToolUseStartEvent):
                transformed = self._tool_use_start_handler.handle(event, state)
            elif isinstance(event, ToolUseDeltaEvent):
                transformed = event
            elif isinstance(event, ToolResultEvent):
                transformed = self._tool_result_handler.handle(event, state)
            elif isinstance(event, ArtifactEvent):
                transformed = self._artifact_handler.handle(event, state)
            elif isinstance(event, ErrorEvent):
                transformed = self._error_handler.handle(event, state)
            elif isinstance(event, WarningEvent):
                transformed = self._warning_handler.handle(event)
            elif isinstance(event, DoneEvent):
                transformed, extra_yields = self._done_handler.handle(
                    event, inp, state
                )
            elif isinstance(event, CompactionEvent):
                await self._compaction_handler.handle(event, inp)
                transformed = _SUPPRESS
            else:
                transformed = event

            for extra_event in extra_yields:
                yield extra_event
            if transformed is not _SUPPRESS:
                yield transformed  # type: ignore[misc]

        # Post-stream: notify sync manager once.
        self._memory_sync_notify.notify_message_bytes(
            inp.sync_manager,
            inp.effective_runtime_message,
        )
