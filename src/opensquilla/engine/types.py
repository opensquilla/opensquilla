"""Engine type definitions: AgentState, AgentEvent, AgentConfig."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from opensquilla.execution_status import ExecutionStatus
from opensquilla.session.compaction_lifecycle import (
    DEFAULT_FLUSH_TRIGGERS,
    normalize_flush_triggers_strict,
)
from opensquilla.tool_boundary import ToolCall as ToolCall
from opensquilla.tool_boundary import ToolResult as ToolResult

if TYPE_CHECKING:
    from opensquilla.engine.usage import SessionTotalsSnapshot


class ThinkingLevel(StrEnum):
    OFF = "off"
    MINIMAL = "minimal"  # 1024 tokens
    LOW = "low"  # 4096 tokens
    MEDIUM = "medium"  # 10000 tokens
    HIGH = "high"  # 20000 tokens
    XHIGH = "xhigh"  # 50000 tokens
    ADAPTIVE = "adaptive"  # auto-scale based on prompt


THINKING_BUDGETS: dict[ThinkingLevel, int] = {
    ThinkingLevel.OFF: 0,
    ThinkingLevel.MINIMAL: 1024,
    ThinkingLevel.LOW: 4096,
    ThinkingLevel.MEDIUM: 10000,
    ThinkingLevel.HIGH: 20000,
    ThinkingLevel.XHIGH: 50000,
}


class AgentState(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    STREAMING = "streaming"
    ERROR = "error"
    DONE = "done"


# ---------------------------------------------------------------------------
# Agent events
# ---------------------------------------------------------------------------


@dataclass
class ThinkingEvent:
    kind: Literal["thinking"] = field(default="thinking", init=False)
    text: str = ""


@dataclass
class TextDeltaEvent:
    kind: Literal["text_delta"] = field(default="text_delta", init=False)
    text: str = ""


@dataclass
class RunHeartbeatEvent:
    kind: Literal["run_heartbeat"] = field(default="run_heartbeat", init=False)
    phase: str = "agent"
    elapsed_ms: int = 0
    idle_ms: int = 0
    message: str = ""


@dataclass
class ToolUseStartEvent:
    kind: Literal["tool_use_start"] = field(default="tool_use_start", init=False)
    tool_use_id: str = ""
    tool_name: str = ""
    synthetic_from_text: bool = False


@dataclass
class ToolResultEvent:
    kind: Literal["tool_result"] = field(default="tool_result", init=False)
    tool_use_id: str = ""
    tool_name: str = ""
    result: str = ""
    is_error: bool = False
    arguments: dict[str, Any] | None = None
    execution_status: ExecutionStatus | None = None


@dataclass
class RouterControlReplayEvent:
    kind: Literal["router_control_replay"] = field(default="router_control_replay", init=False)
    action: str = ""
    target_tier: str | None = None
    target_model: str | None = None
    target_provider: str | None = None
    target_id: str | None = None
    replay_depth: int = 0


@dataclass
class ArtifactEvent:
    kind: Literal["artifact"] = "artifact"
    id: str = ""
    sha256: str = ""
    name: str = ""
    mime: str = ""
    size: int = 0
    session_id: str = ""
    session_key: str = ""
    source: str = ""
    created_at: str = ""
    download_url: str = ""
    store: str = "artifacts"


@dataclass
class StateChangeEvent:
    kind: Literal["state_change"] = field(default="state_change", init=False)
    from_state: AgentState = AgentState.IDLE
    to_state: AgentState = AgentState.IDLE


@dataclass
class ErrorEvent:
    kind: Literal["error"] = field(default="error", init=False)
    message: str = ""
    code: str = ""


@dataclass
class DoneEvent:
    kind: Literal["done"] = field(default="done", init=False)
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    iterations: int = 0
    cost_usd: float = 0.0
    billed_cost: float = 0.0
    cost_source: str = "none"
    model: str = ""
    runtime_context_hash: str | None = None
    runtime_context_chars: int = 0
    routed_tier: str | None = None
    routing_source: str = "none"
    routing_confidence: float = 0.0
    baseline_model: str = ""
    routed_model: str = ""
    savings_pct: float = 0.0
    savings_usd: float = 0.0
    cache_hit_active: bool = False
    # Comprehensive per-turn savings score derived from token counts and model prices.
    # Route-only compatibility remains in savings_pct/savings_usd.
    total_savings_pct: float = 0.0
    total_savings_usd: float = 0.0
    # New fields appended at the end so positional construction in tests
    # (notably DoneEvent(...) without kwargs) does not silently shift earlier
    # args.
    cache_write_tokens: int = 0
    reasoning_content: str | None = None
    session_totals: SessionTotalsSnapshot | None = None
    routing_applied: bool = True
    rollout_phase: str = "full"
    image_route_reason: str | None = None
    vision_followup_gate_decision: str | None = None
    vision_followup_gate_confidence: float | None = None
    vision_followup_gate_reason: str | None = None
    vision_followup_gate_source: str | None = None
    vision_followup_gate_model: str | None = None
    vision_followup_needs_image: bool | None = None
    vision_followup_fallback: str | None = None

    @property
    def upstream_cost_usd(self) -> float:
        """Backward-compatible alias for earlier OpenRouter cost consumers."""
        return self.billed_cost


@dataclass
class RouterDecisionEvent:
    """Squilla router's decision for this turn, emitted once after the
    pre-turn pipeline resolves the tier/model. Frontend uses this to drive
    the router HUD (tier pill, tier-shift highlight, scanner popover).

    Routing fires exactly once per user-message; the tier sticks across
    the entire agent loop. Subsequent events in the same turn carry no
    routing information.
    """

    kind: Literal["router_decision"] = field(default="router_decision", init=False)
    tier: str = ""
    tier_index: int = -1
    model: str = ""
    baseline_model: str = ""
    source: str = "none"
    confidence: float = 0.0
    probs: list[float] = field(default_factory=list)
    savings_pct: float = 0.0
    fallback: bool = False
    thinking_mode: str = ""
    prompt_policy: str = ""
    routing_applied: bool = True
    rollout_phase: str = "full"


@dataclass
class MetaRunAnnouncedEvent:
    """Emitted once when a MetaSkill run starts and its plan has been
    compiled. WebUI uses this to seed the step ribbon with all declared
    step ids, labels, kinds, and dependency edges. `parent_run_id` is
    reserved for nested meta-skill rollouts (always None today).
    """

    kind: Literal["meta_run_announced"] = field(default="meta_run_announced", init=False)
    run_id: str = ""
    meta_skill_name: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    parent_run_id: str | None = None


@dataclass
class MetaStepStateEvent:
    """One state transition for a single MetaSkill step within a run.

    `state` is one of pending / running / succeeded / failed / skipped /
    substituted. `status_text` is an optional short human-readable label
    shown under the active chip; `error` carries the failure message when
    `state == "failed"`; `substitute_for` is set on the substitute step
    yielded after an `on_failure` branch fires.
    """

    kind: Literal["meta_step_state"] = field(default="meta_step_state", init=False)
    run_id: str = ""
    step_id: str = ""
    state: Literal[
        "pending", "running", "succeeded", "failed", "skipped", "substituted"
    ] = "pending"
    status_text: str | None = None
    error: str | None = None
    substitute_for: str | None = None


@dataclass
class MetaRunCompletedEvent:
    """Terminal event for a MetaSkill run. `outcome` is one of
    ok / failed / cancelled. The three step-id lists let the WebUI freeze
    the final ribbon state without scanning back through the stream.
    """

    kind: Literal["meta_run_completed"] = field(default="meta_run_completed", init=False)
    run_id: str = ""
    outcome: Literal["ok", "failed", "cancelled"] = "ok"
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    skipped_steps: list[str] = field(default_factory=list)


@dataclass
class WarningEvent:
    """Non-persistent user-facing warning surfaced at the end of a turn.

    Unlike ErrorEvent, warnings do not terminate the turn. They flow through
    ``session.event.warning`` to the frontend, which typically shows a toast.
    Not written to the transcript — warnings should never enter LLM context.
    """

    kind: Literal["warning"] = field(default="warning", init=False)
    code: str = ""
    message: str = ""


@dataclass
class CompactionEvent:
    """Emitted when Agent completes inline compaction. Captured by TurnRunner for DB persistence."""

    kind: Literal["compaction"] = field(default="compaction", init=False)
    compaction_id: str | None = None
    summary: str = ""
    kept_entries: list[dict] = field(default_factory=list)
    kept_count: int = 0
    removed_count: int = 0


@dataclass
class CompactionOutcome:
    """Return type for _check_context_overflow — carries compaction metadata."""

    messages: list = field(default_factory=list)
    compacted: bool = False
    summary: str = ""
    kept_entries: list[dict] = field(default_factory=list)
    removed_count: int = 0
    compaction_id: str | None = None
    request_context_insert_index: int | None = None
    runtime_context_insert_index: int | None = None


AgentEvent = (
    ThinkingEvent
    | TextDeltaEvent
    | RunHeartbeatEvent
    | ToolUseStartEvent
    | ToolResultEvent
    | RouterControlReplayEvent
    | ArtifactEvent
    | StateChangeEvent
    | ErrorEvent
    | DoneEvent
    | CompactionEvent
    | WarningEvent
    | RouterDecisionEvent
    | MetaRunAnnouncedEvent
    | MetaStepStateEvent
    | MetaRunCompletedEvent
)


# ---------------------------------------------------------------------------
# Agent config (internal — @dataclass)
# ---------------------------------------------------------------------------


_THINKING_BUDGET_DEFAULT = -1  # sentinel: "not explicitly set"

# Tokens used for ADAPTIVE level when no prompt length is provided
_ADAPTIVE_DEFAULT_TOKENS = 10000

# Characters-per-token estimate for adaptive scaling
_CHARS_PER_TOKEN = 4


@dataclass
class AgentConfig:
    # Model/tool loop budget. 0 = unlimited; explicit positive values are
    # bounded operator budgets for CI, benchmarks, and constrained runs.
    max_iterations: int = 0
    # Total turn wall-clock budget (seconds; 0 = disabled)
    # 30 min — see iteration_timeout note below; outer turn budget for
    # meta-skill DAGs (paper-write / arxiv-deck run 5-7 min commonly).
    timeout: float = 1800.0
    # Per-iteration timeout: one LLM call + its tool executions
    # 30 min — single iteration may be the whole meta DAG when the soft
    # path treats meta_invoke as a single tool call.
    iteration_timeout: float = 1800.0
    # HTTP-level timeout for a single LLM API request
    request_timeout: float = 120.0
    # Per-tool execution timeout
    tool_timeout: float = 60.0
    # Upper bound for same-turn safe tool execution. Safe tools can overlap, but
    # unbounded fan-out can overload local/network resources.
    max_safe_tool_concurrency: int = 6
    max_tokens: int = 16384
    # Optional per-turn operator budgets. 0 disables the corresponding budget.
    max_turn_llm_calls: int = 0
    max_turn_input_tokens: int = 0
    max_turn_output_tokens: int = 0
    max_turn_billed_cost_usd: float = 0.0
    max_turn_tool_errors: int = 0
    temperature: float | None = None
    thinking: bool | ThinkingLevel = False
    thinking_budget_tokens: int = _THINKING_BUDGET_DEFAULT
    system_prompt: str | None = None
    extra_system_prompt: str | None = None
    workspace_dir: str | None = None
    model_id: str | None = None
    stop_sequences: list[str] = field(default_factory=list)
    context_window_tokens: int = 200000
    context_overflow_threshold: float = 0.85  # trigger at 85%
    max_overflow_retries: int = 2
    max_history_turns: int = 0  # 0 = unlimited; compaction handles oversized history
    preserve_historical_images: bool = False
    # Retry policy for transient LLM errors (429, 500, 503)
    max_provider_retries: int = 3
    length_capped_continuations: int = 3
    retry_base_backoff_ms: int = 1000
    retry_max_backoff_ms: int = 30_000
    # Prompt caching breakpoints (list of {"text": ..., "cache": "true"})
    cache_breakpoints: list[dict[str, str]] | None = None
    cache_mode: Literal["off", "auto", "on"] = "off"
    # Per-turn volatile request context injected after persisted history
    # and before the current user turn. It is not persisted to history.
    request_context_prompt: str | None = None
    # Per-turn user-role skill context injected after persisted history
    # and before the current user turn. The agent persists each turn's
    # skill context in history so provider KV-cache prefixes stay stable.
    skills_context_prompt: str | None = None
    # Pre-compaction memory flush
    flush_enabled: bool = False
    flush_triggers: list[str] = field(
        default_factory=lambda: list(DEFAULT_FLUSH_TRIGGERS)
    )
    flush_pre_compaction: bool = False
    flush_timeout_seconds: float = 15.0
    flush_background_timeout_seconds: float = 120.0
    flush_backoff_initial_seconds: float = 30.0
    flush_backoff_max_seconds: float = 300.0
    flush_archive_max_bytes: int = 800_000
    flush_compaction_requires_safe_receipt: bool = False
    flush_compaction_safety_mode: Literal["protect", "best_effort", "block", "off"] = "protect"
    compaction_profile: Literal["conversation", "coding", "research", "support"] = "conversation"
    compaction_protected_recent_messages: int = 0
    repair_enabled: bool = True
    repair_interval_seconds: float = 60.0
    repair_max_items_per_tick: int = 5
    flush_workspace_dir: str | None = None
    model_capabilities: Any | None = None  # ModelCapabilities from provider.types
    # Tokenjuice projection: project eligible fresh tool results before the
    # next LLM turn. This is not user-selectable behavior.
    # Legacy compression knobs remain as compatibility shims for meta_invoke
    # tests and embedded callers; the runtime's default path uses Tokenjuice.
    tool_result_compression_enabled: bool = True
    tool_result_compression_mode: Literal["off", "truncate", "summarize"] | None = None
    tool_result_compression_max_share: float = 0.25
    tool_result_compression_summary_model: str | None = None
    tool_result_compression_summary_max_tokens: int = 1024
    tool_result_compression_summary_timeout_seconds: float = 20.0
    tool_result_compression_summary_input_max_chars: int = 60_000
    tool_result_projection_max_inline_chars: int = 60_000
    tool_result_provider_request_max_chars: int = 0
    provider_request_proof_max_chars: int = 0
    tool_use_argument_provider_request_max_chars: int = 0
    tool_use_argument_projection_enabled: bool = False
    tool_result_external_keep_recent: int = 2
    tool_failure_loop_block_threshold: int = 3
    tool_result_store_dir: str | None = None
    tool_result_store_session_id: str | None = None
    tool_result_store_session_key: str | None = None
    tool_result_store_agent_id: str | None = None
    tool_result_store_max_bytes: int | None = 8 * 1024 * 1024
    tool_result_store_disk_budget_bytes: int | None = 256 * 1024 * 1024
    tool_result_store_retention_seconds: int | None = 7 * 24 * 60 * 60
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.flush_triggers = list(normalize_flush_triggers_strict(self.flush_triggers))
        self.compaction_protected_recent_messages = max(
            0,
            int(self.compaction_protected_recent_messages or 0),
        )

    def resolve_thinking(self, prompt: str | None = None) -> tuple[bool, int]:
        """Return (enabled, budget_tokens) based on the thinking field.

        Rules:
        - False          → (False, 0)
        - True           → same as ThinkingLevel.MEDIUM → (True, 10000)
        - ThinkingLevel.OFF      → (False, 0)
        - ThinkingLevel.ADAPTIVE → estimate from prompt length
        - Other levels   → (True, THINKING_BUDGETS[level])

        If thinking_budget_tokens is explicitly set (not the default sentinel),
        it overrides the resolved budget (but not the enabled flag).
        """
        thinking = self.thinking

        if thinking is False:
            return (False, 0)

        if thinking is True:
            enabled, budget = True, THINKING_BUDGETS[ThinkingLevel.MEDIUM]
        elif thinking == ThinkingLevel.OFF:
            return (False, 0)
        elif thinking == ThinkingLevel.ADAPTIVE:
            enabled = True
            if prompt is not None:
                estimated_tokens = len(prompt) // _CHARS_PER_TOKEN
                # Clamp between MINIMAL and XHIGH
                budget = max(
                    THINKING_BUDGETS[ThinkingLevel.MINIMAL],
                    min(estimated_tokens, THINKING_BUDGETS[ThinkingLevel.XHIGH]),
                )
            else:
                budget = _ADAPTIVE_DEFAULT_TOKENS
        else:
            enabled = True
            budget = THINKING_BUDGETS[thinking]

        # Override budget if explicitly set by caller
        if self.thinking_budget_tokens != _THINKING_BUDGET_DEFAULT:
            budget = self.thinking_budget_tokens

        return (enabled, budget)
