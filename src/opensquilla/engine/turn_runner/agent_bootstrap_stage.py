"""Stage object for runtime budget resolve + AgentConfig assembly + Agent construction.

Owns the source slice that previously lived inline at the top of
``TurnRunner._run_turn`` between the prompt-assembler stage boundary and the
pre-flight compaction call. The harness invokes
``AgentBootstrapStage.run`` once per turn, AFTER PromptAssemblerStage
and BEFORE PreflightCompactionStage.
Side-effect contract: re-raises any exception from the budget resolvers,
the model-catalog lookups, the AgentConfig constructor, the memory
warm/load helpers, or the Agent constructor exactly as the inline body
did. The harness catches it through the existing CancelledError /
Exception terminal handlers in ``_run_turn``. ``AgentBootstrapStage``
does NOT call any ``TurnHook`` directly.

NEVER terminates. Always returns ``StageOutcome.success(...)``. The
``StageOutcome`` shape is preserved for forward-compatibility with a
future AgentConfig-validation early-yield branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from opensquilla.engine.agent import Agent, ToolHandler
    from opensquilla.engine.turn_runner.outcome import StageOutcome
    from opensquilla.engine.types import AgentConfig, ThinkingLevel
    from opensquilla.observability.turn_call_log import TurnCallLogger
    from opensquilla.provider.protocol import LLMProvider
    from opensquilla.provider.types import ModelCapabilities
    from opensquilla.tools.types import ToolContext

# ---------------------------------------------------------------------------
# Value objects returned by the ports — typed frozen tuples that collapse
# the multi-call slice into declarative single-call shapes.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ResolvedBudgets:
    """Frozen value returned by ``TimeoutBudgetPort.resolve_budgets``."""

    runtime_timeout: float
    max_iterations: int
    max_iterations_source: str
    iteration_timeout: float
    tool_timeout: float
    request_timeout: float
    max_provider_retries: int

@dataclass(frozen=True)
class _ResolvedCatalog:
    """Three-field frozen value returned by ``ModelCatalogPort.lookup``."""

    max_tokens: int
    context_window: int
    capabilities: ModelCapabilities | None

@dataclass(frozen=True)
class _AgentConfigAuxiliaries:
    """Bag of resolved auxiliaries for AgentConfig construction.

    Carries every value the AgentConfig body reads via
    ``getattr(_mem_cfg, ...)`` / ``getattr(_agent_token_cfg, ...)`` so the
    stage body becomes a single ``AgentConfig(...)`` call site.
    """

    thinking: bool | ThinkingLevel
    flush_workspace_dir: str
    tool_result_store_dir: str
    tool_result_store_session_id: str
    # Memory-cfg-derived (defaults match the inline ``getattr`` defaults)
    flush_enabled: bool
    flush_triggers: list[str]
    flush_pre_compaction: bool
    flush_timeout_seconds: float
    flush_background_timeout_seconds: float
    flush_backoff_initial_seconds: float
    flush_backoff_max_seconds: float
    flush_archive_max_bytes: int
    flush_compaction_requires_safe_receipt: bool
    flush_compaction_safety_mode: Literal["protect", "best_effort", "block", "off"]
    compaction_profile: Literal["conversation", "coding", "research", "support"]
    compaction_protected_recent_messages: int
    # Agent-token-cfg-derived
    tool_result_projection_max_inline_chars: int
    tool_result_store_max_bytes: int
    tool_result_store_disk_budget_bytes: int
    tool_result_store_retention_seconds: int

@dataclass(frozen=True)
class _MemorySnapshotResult:
    """Two-field frozen value returned by ``MemorySnapshotPort.warm_and_capture``."""

    sync_manager: Any | None
    private_memory_allowed: bool

# ---------------------------------------------------------------------------
# Ports — six narrow Protocols so the stage is unit-testable without the
# full TurnRunner. The runtime adapters in ``harness.py`` bind these to the
# concrete TurnRunner methods.
# ---------------------------------------------------------------------------

@runtime_checkable
class TimeoutBudgetPort(Protocol):
    """Wraps the five ``TurnRunner._resolve_agent_*`` helpers as a
    coordinated single-call port. Returns the resolved budget tuple in
    one shot to keep the stage body declarative.

    ``effective_runtime_timeout`` honors the per-call ``timeout``
    override (``float(timeout) if timeout is not None else
    self._resolve_agent_runtime_timeout(session_key)``). The other four
    resolvers consume the per-call explicit override and the
    session/env/config fallback chain internally.
    """

    def resolve_budgets(
        self,
        *,
        session_key: str,
        timeout: float | None,
        max_iterations: int | None,
        iteration_timeout: float | None,
        tool_timeout: float | None,
        request_timeout: float | None,
        max_provider_retries: int | None,
    ) -> _ResolvedBudgets: ...

@runtime_checkable
class ModelCatalogPort(Protocol):
    """Wraps ``TurnRunner._model_catalog`` lookups defensively.

    Mirrors the inline three-call sequence with the fallback
    semantics: when ``self._model_catalog is None`` the inline body
    computes ``max_tokens=user_override or 16384`` and
    ``context_window=200_000`` and ``model_caps=None``. The adapter folds
    those defaults into the port so the stage body has no branching on
    catalog presence.

    The adapter reads ``user_max_tokens`` / ``provider_name`` /
    ``base_url`` off the runner's ``_config.llm`` chain.
    """

    def lookup(self, model_id: str, provider: str = "") -> _ResolvedCatalog: ...

@runtime_checkable
class AgentConfigBuilderPort(Protocol):
    """Wraps the ``TurnRunner`` helpers AgentConfig assembly needs.

    The inline body calls ``_resolve_turn_thinking(turn)``,
    ``_resolve_memory_source_dir(agent_id)``, and reads a handful of
    ``getattr`` values off ``_mem_cfg`` / ``_agent_token_cfg``.

    Folding them into a single port keeps the stage body free of
    runtime imports. The adapter returns a typed
    ``_AgentConfigAuxiliaries`` value that the stage feeds straight into
    ``AgentConfig(...)``.
    """

    def build_auxiliaries(
        self,
        *,
        agent_id: str,
        session_key: str,
        session_id_for_log: str | None,
        turn: Any,
    ) -> _AgentConfigAuxiliaries: ...


def _route_max_history_turns(metadata: dict[str, Any]) -> int:
    value = metadata.get("route_max_history_turns")
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str):
        try:
            return max(0, int(value))
        except ValueError:
            return 0
    return 0


def _preserve_historical_images(metadata: dict[str, Any]) -> bool:
    image_route_reason = metadata.get("image_route_reason")
    return image_route_reason in {"current_turn", "gate_history"}


@runtime_checkable
class MemorySnapshotPort(Protocol):
    """Wraps the per-agent memory sync warm + the per-(agent_id, session_key)
    memory snapshot capture. Two effects, one async port.

    Inline body does:
      - ``sync_manager = self._memory_sync_managers.get(agent_id)``
      - ``await sync_manager.warm_session(session_key)`` (if present)
      - ``private_memory_allowed = allows_private_memory_prompt_injection(session_key)``
      - if allowed and snapshot missing: ``self._memory_snapshots[snap_key] = MemorySnapshot(...)``

    The port encapsulates ALL of that, including the
    ``_memory_snapshots`` dict mutation. The harness cannot move the
    mutation out without changing semantics — the snapshot is consulted
    by ``_assemble_prompt`` AND by StreamConsumerStage on CompactionEvent.
    Keeping the mutation inside the port preserves the existing
    single-writer invariant. The port returns ``(sync_manager,
    private_memory_allowed)`` so the Agent constructor receives the same
    ``sync_manager`` and the harness can read ``private_memory_allowed``
    for downstream consumers.
    """

    async def warm_and_capture(
        self,
        *,
        agent_id: str,
        session_key: str,
    ) -> _MemorySnapshotResult: ...

@runtime_checkable
class AgentFactoryPort(Protocol):
    """Wraps the typed ``Agent(...)`` constructor.

    Mirrors the call shape with the typed runtime constructor params
    (``memory_sync_manager``, ``session_flush_service``). The adapter at
    the harness side reads ``self._session_flush_service`` from the
    runner and forwards everything else from the call site.
    """

    def build(
        self,
        *,
        provider: LLMProvider,
        config: AgentConfig,
        tool_definitions: list[Any],
        tool_handler: ToolHandler | None,
        session_key: str,
        turn_call_logger: TurnCallLogger | None,
        memory_sync_manager: Any | None,
        tool_context: ToolContext | None,
    ) -> Agent: ...

# ---------------------------------------------------------------------------
# Stage I/O dataclasses (frozen)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentBootstrapStageInput:
    """Inputs the AgentBootstrapStage needs at the boundary it owns.

    Mirrors the locals visible to the original inline slice at the point
    PromptAssemblerStage has finished. The ``provider``,
    ``cloned_selector``, ``turn``, ``final_prompt``, ``cache_breakpoints``,
    ``request_context_prompt``, ``resolved_model``, and
    ``session_id_for_log`` fields come from's
    ``PromptAssemblerStageOutput``. ``tool_handler`` comes from's
    output.
    """

    # From PromptAssemblerStage / ProviderAndToolsStage / call site
    provider: Any
    cloned_selector: Any
    turn: Any  # post-pipeline pipeline.TurnContext
    final_prompt: str
    cache_breakpoints: list[Any] | None
    request_context_prompt: str | None
    resolved_model: str
    session_id_for_log: str | None
    tool_handler: ToolHandler | None
    turn_call_logger: TurnCallLogger | None
    tool_context: ToolContext | None

    # Per-turn inputs from _run_turn locals
    session_key: str
    agent_id: str
    timeout: float | None
    max_iterations: int | None
    iteration_timeout: float | None
    tool_timeout: float | None
    request_timeout: float | None
    max_provider_retries: int | None
    length_capped_continuations: int | None
    active_provider_id: str = ""

@dataclass(frozen=True)
class AgentBootstrapStageOutput:
    """The pieces of state subsequent stages consume.

    - ``agent``: the constructed ``Agent`` instance ready for
      ``run_turn``. Subsequent stages mutate ``agent.config`` (history
      load) and ``agent._context.system_prompt`` (compaction).
    - ``agent_config``: the same ``AgentConfig`` carried on
      ``agent.config``. Surfaced separately because PreflightCompactionStage
      reads ``agent_config.context_window_tokens`` directly.
    - ``effective_runtime_timeout`` / ``effective_max_iterations`` /
      ``effective_iteration_timeout`` / ``effective_tool_timeout`` /
      ``effective_request_timeout`` / ``effective_max_provider_retries``:
      surfaced for parity assertions and downstream consumers.
    - ``model_capabilities``: the resolved ``ModelCapabilities`` (or
      ``None``). Surfaced for downstream observability.
    - ``private_memory_allowed``: the result of
      ``allows_private_memory_prompt_injection(session_key)``. Surfaced
      for parity assertions.
    - ``sync_manager``: the per-agent ``MemorySyncManager`` instance (or
      ``None``). The Agent constructor receives it; surfaced for parity
      assertions.
    """

    agent: Agent
    agent_config: AgentConfig
    effective_runtime_timeout: float
    effective_max_iterations: int
    effective_max_iterations_source: str
    effective_iteration_timeout: float
    effective_tool_timeout: float
    effective_request_timeout: float
    effective_max_provider_retries: int
    model_capabilities: ModelCapabilities | None
    private_memory_allowed: bool
    sync_manager: Any | None

# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------

class AgentBootstrapStage:
    """Resolve runtime budgets, build AgentConfig, instantiate the Agent.

    Stable boundary: runs ONCE per turn, after PromptAssemblerStage and
    before PreflightCompactionStage. Pure with respect to its inputs
    except for:

    - ``timeout_budget.resolve_budgets`` — synchronous reads of
      session/env/config; pure read, idempotent.
    - ``model_catalog.lookup`` — synchronous catalog dict lookups; pure.
    - ``agent_config_builder.build_auxiliaries`` — synchronous reads of
      ``_mem_cfg`` / ``_agent_token_cfg`` plus
      ``_resolve_memory_source_dir`` filesystem path resolution.
    - ``memory_snapshot.warm_and_capture`` — async; calls
      ``sync_manager.warm_session`` (transcript-driven preload) and
      mutates ``self._memory_snapshots`` dict.
    - ``agent_factory.build`` — pure constructor call.

    Exception model: re-raises every exception. The harness catches them
    through the existing CancelledError / Exception terminal handlers in
    ``_run_turn``.
    """

    name = "agent_bootstrap_stage"

    def __init__(
        self,
        *,
        timeout_budget: TimeoutBudgetPort,
        model_catalog: ModelCatalogPort,
        agent_config_builder: AgentConfigBuilderPort,
        memory_snapshot: MemorySnapshotPort,
        agent_factory: AgentFactoryPort,
    ) -> None:
        self._timeout_budget = timeout_budget
        self._model_catalog = model_catalog
        self._agent_config_builder = agent_config_builder
        self._memory_snapshot = memory_snapshot
        self._agent_factory = agent_factory

    async def run(
        self,
        inp: AgentBootstrapStageInput,
    ) -> StageOutcome[AgentBootstrapStageOutput]:
        # Local imports keep the module import-cycle-free.
        from opensquilla.engine.turn_runner.outcome import StageOutcome
        from opensquilla.engine.types import AgentConfig

        # 1. Resolve runtime/iteration/tool/request/retry budgets
        budgets = self._timeout_budget.resolve_budgets(
            session_key=inp.session_key,
            timeout=inp.timeout,
            max_iterations=inp.max_iterations,
            iteration_timeout=inp.iteration_timeout,
            tool_timeout=inp.tool_timeout,
            request_timeout=inp.request_timeout,
            max_provider_retries=inp.max_provider_retries,
        )

        # 2. Resolve max_tokens, context_window, capabilities from catalog
        catalog = self._model_catalog.lookup(inp.resolved_model, inp.active_provider_id)

        # 3. Build AgentConfig auxiliaries (thinking, projection, store, mem cfg)
        aux = self._agent_config_builder.build_auxiliaries(
            agent_id=inp.agent_id,
            session_key=inp.session_key,
            session_id_for_log=inp.session_id_for_log,
            turn=inp.turn,
        )
        agent_metadata = inp.turn.metadata
        agent_metadata["agent_max_iterations"] = budgets.max_iterations
        agent_metadata["agent_max_iterations_source"] = budgets.max_iterations_source

        # 4. Construct AgentConfig (declarative, single call site)
        #
        # ``workspace_dir`` is sourced from the per-turn metadata key
        # ``bootstrap_workspace_dir`` (written by ``_run_pipeline`` from
        # the call-site's ToolContext/agent-resolved value — see
        # runtime.py initial_metadata). This makes AgentConfig.workspace_dir
        # the single authoritative source for downstream code (meta_invoke
        # handler, sub-Agent factory, etc.). Without this, the bootstrap
        # stage left workspace_dir=None, the meta_invoke fallback chain
        # collapsed to ContextVar lookups, and sub-Agents ended up using
        # the process default workspace instead of the configured one.
        agent_config = AgentConfig(
            max_iterations=budgets.max_iterations,
            system_prompt=inp.final_prompt,
            cache_breakpoints=inp.cache_breakpoints,
            request_context_prompt=inp.request_context_prompt,
            cache_mode=inp.turn.metadata.get("cache_mode", "off"),
            skills_context_prompt=inp.turn.metadata.get("skills_context_prompt"),
            model_id=inp.resolved_model,
            workspace_dir=inp.turn.metadata.get("bootstrap_workspace_dir") or None,
            timeout=budgets.runtime_timeout,
            iteration_timeout=budgets.iteration_timeout,
            tool_timeout=budgets.tool_timeout,
            request_timeout=budgets.request_timeout,
            max_provider_retries=budgets.max_provider_retries,
            length_capped_continuations=(
                inp.length_capped_continuations
                if inp.length_capped_continuations is not None
                else AgentConfig().length_capped_continuations
            ),
            max_tokens=catalog.max_tokens,
            context_window_tokens=catalog.context_window,
            max_history_turns=_route_max_history_turns(inp.turn.metadata),
            preserve_historical_images=_preserve_historical_images(inp.turn.metadata),
            flush_enabled=aux.flush_enabled,
            flush_triggers=aux.flush_triggers,
            flush_pre_compaction=aux.flush_pre_compaction,
            flush_timeout_seconds=aux.flush_timeout_seconds,
            flush_background_timeout_seconds=aux.flush_background_timeout_seconds,
            flush_backoff_initial_seconds=aux.flush_backoff_initial_seconds,
            flush_backoff_max_seconds=aux.flush_backoff_max_seconds,
            flush_archive_max_bytes=aux.flush_archive_max_bytes,
            flush_compaction_requires_safe_receipt=(
                aux.flush_compaction_requires_safe_receipt
            ),
            flush_compaction_safety_mode=aux.flush_compaction_safety_mode,
            compaction_profile=aux.compaction_profile,
            compaction_protected_recent_messages=(
                aux.compaction_protected_recent_messages
            ),
            flush_workspace_dir=aux.flush_workspace_dir,
            model_capabilities=catalog.capabilities,
            thinking=aux.thinking,
            tool_result_projection_max_inline_chars=(
                aux.tool_result_projection_max_inline_chars
            ),
            tool_result_store_dir=aux.tool_result_store_dir,
            tool_result_store_session_id=aux.tool_result_store_session_id,
            tool_result_store_session_key=inp.session_key,
            tool_result_store_agent_id=inp.agent_id,
            tool_result_store_max_bytes=aux.tool_result_store_max_bytes,
            tool_result_store_disk_budget_bytes=(
                aux.tool_result_store_disk_budget_bytes
            ),
            tool_result_store_retention_seconds=(
                aux.tool_result_store_retention_seconds
            ),
            metadata=agent_metadata,
        )

        # 5. Warm session and capture memory snapshot (async, dict-mutating)
        memory = await self._memory_snapshot.warm_and_capture(
            agent_id=inp.agent_id,
            session_key=inp.session_key,
        )

        # 7. Construct the Agent from the typed runtime parameters.
        agent = self._agent_factory.build(
            provider=inp.provider,
            config=agent_config,
            tool_definitions=inp.turn.tool_defs,
            tool_handler=inp.tool_handler,
            session_key=inp.session_key,
            turn_call_logger=inp.turn_call_logger,
            memory_sync_manager=memory.sync_manager,
            tool_context=inp.tool_context,
        )

        return StageOutcome.success(
            AgentBootstrapStageOutput(
                agent=agent,
                agent_config=agent_config,
                effective_runtime_timeout=budgets.runtime_timeout,
                effective_max_iterations=budgets.max_iterations,
                effective_max_iterations_source=budgets.max_iterations_source,
                effective_iteration_timeout=budgets.iteration_timeout,
                effective_tool_timeout=budgets.tool_timeout,
                effective_request_timeout=budgets.request_timeout,
                effective_max_provider_retries=budgets.max_provider_retries,
                model_capabilities=catalog.capabilities,
                private_memory_allowed=memory.private_memory_allowed,
                sync_manager=memory.sync_manager,
            )
        )
