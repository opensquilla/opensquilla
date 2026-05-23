"""MetaOrchestrator facade — run a MetaPlan as a fleet of one-shot sub-Agents.

This module is the public surface of the meta-skill subsystem and a
thin coordinator around three workers:

* :mod:`opensquilla.skills.meta.scheduler` — DAG-parallel ``asyncio``
  scheduler that drives the steps and merges their event streams.
* :mod:`opensquilla.skills.meta.executors` — per-``step.kind`` bodies
  (``agent`` / ``llm_classify`` / ``tool_call`` / ``skill_exec``).
* :mod:`opensquilla.skills.meta.templating` — restricted Jinja env,
  ``with_args`` / route / placeholder rendering.

The :class:`MetaOrchestrator` class binds instance dependencies
(``agent_runner``, ``skill_loader``, optional ``llm_chat`` /
``tool_invoker`` / ``workspace_dir``) and feeds them into the free
worker functions; the factory functions at the bottom of this module
build those dependencies from a parent turn's ``TurnRunner`` context.

Out-of-scope for the MVP (see docs/proposals/meta-skills/MECHANISM.md
§20): input-side taint provenance, sub-turn sandbox narrowing,
large_outputs/artifact_ref, retries, when conditions, persistence to
``meta_skill_runs``, separate operator WS channel.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from opensquilla.engine.types import AgentConfig, AgentEvent
from opensquilla.provider.protocol import LLMProvider
from opensquilla.skills.meta.events import _StepDone, yield_skill_view_preface
from opensquilla.skills.meta.executors.agent import run_step_with_skill_stream
from opensquilla.skills.meta.executors.llm_classify import run_llm_classify_step
from opensquilla.skills.meta.executors.skill_exec import run_skill_exec_step
from opensquilla.skills.meta.executors.tool_call import run_tool_call_step
from opensquilla.skills.meta.scheduler import run_dag
from opensquilla.skills.meta.templating import (
    _coerce_to_choice,  # noqa: F401 — re-exported for tests/back-compat
    _expand_skill_placeholders,  # noqa: F401 — re-exported for tests/back-compat
    _format_classify_prompt,  # noqa: F401 — re-exported for back-compat
    format_step_prompt,  # noqa: F401 — re-exported in __all__
    render_with_args,  # noqa: F401 — re-exported in __all__
    resolve_route,  # noqa: F401 — re-exported in __all__
)
from opensquilla.skills.meta.types import MetaMatch, MetaResult, MetaStep

if TYPE_CHECKING:
    from opensquilla.persistence.meta_run_writer import MetaRunWriter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Injected-dependency protocols
# ---------------------------------------------------------------------------

#: Sub-Agent factory: (system_prompt, user_message) -> async iterator of
#: AgentEvents. The orchestrator depends only on this minimal protocol —
#: it does NOT own the Agent construction. The caller (TurnRunner) injects
#: an :class:`AgentRunner` whose closure captures provider / tool_defs /
#: tool_handler / usage_tracker from the parent turn.
AgentRunner = Callable[[str, str], AsyncIterator[AgentEvent]]

#: Lightweight LLM-only call (no tool loop). Returns the model's reply text.
LLMChat = Callable[[str, str], Awaitable[str]]

#: Direct tool invoker — bypasses the LLM. Returns the tool's result as string.
ToolInvoker = Callable[[str, dict[str, Any]], Awaitable[str]]


class MetaOrchestrator:
    """Run one MetaPlan end-to-end with per-step kind dispatch.

    Step kinds (see :class:`MetaStep`):

    * ``agent``        — spawn a sub-Agent via ``agent_runner`` (MVP path).
    * ``llm_classify`` — single constrained LLM call via ``llm_chat``.
    * ``tool_call``    — direct tool invocation via ``tool_invoker``.

    ``llm_chat`` and ``tool_invoker`` are optional. Steps whose kind requires
    them but the dependency is absent fall back to the agent runner with a
    synthesized prompt that imitates the kind's contract (degraded mode).
    """

    def __init__(
        self,
        agent_runner: AgentRunner,
        skill_loader: Any,
        *,
        llm_chat: LLMChat | None = None,
        tool_invoker: ToolInvoker | None = None,
        workspace_dir: str | None = None,
        max_parallelism: int | None = 8,
        # NEW (all optional — preserve legacy callers)
        run_writer: MetaRunWriter | None = None,
        triggered_by: str = "soft_meta_invoke",
        session_key: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        self._agent_runner = agent_runner
        self._skill_loader = skill_loader
        self._llm_chat = llm_chat
        self._tool_invoker = tool_invoker
        # Shared filesystem root for ``skill_exec`` steps that write
        # cross-skill artefacts (results.csv → plot, references.bib →
        # bibtex, etc.). When set, this overrides the per-skill
        # ``base_dir`` default so all steps share one workspace tree.
        # ``entrypoint.cwd`` on the individual skill still wins if set.
        self._workspace_dir = workspace_dir
        # Concurrency cap fed into ``scheduler.run_dag``. Default 8
        # accommodates a 5-way fan-out (meta-paper-write needs 5) with
        # headroom while still containing pathological 20-way fans.
        # ``None`` = unbounded (preserved for advanced callers).
        self._max_parallelism = max_parallelism
        # Optional persistence ledger (G4 — audit traces). When set,
        # ``iter_events`` opens a run on entry, bridges scheduler
        # begin/finish/failover callbacks to per-step writes, and
        # finalises the row in the ``finally`` block (status keyed off
        # cancellation vs. terminal MetaResult). ``None`` keeps the
        # legacy path unchanged — zero rows written.
        self._run_writer = run_writer
        self._triggered_by = triggered_by
        self._session_key = session_key
        self._turn_id = turn_id

    async def run(self, match: MetaMatch) -> MetaResult:
        """Execute the plan, draining the streaming generator for the final result.

        Tests and any non-UI caller use this; the gateway consumes the
        streaming variant :meth:`iter_events` directly so users can watch each
        step appear in the WebUI as a tool-call card.
        """

        result = MetaResult(ok=False, error="orchestrator produced no result")
        async for item in self.iter_events(match):
            if isinstance(item, MetaResult):
                result = item
        return result

    async def iter_events(
        self,
        match: MetaMatch,
    ) -> AsyncIterator[AgentEvent | MetaResult]:
        """Run the plan and stream a flat sequence of events for the UI.

        Thin wrapper around :func:`scheduler.run_dag`: builds the two
        executor-shaped callables (per-step dispatch keyed on
        ``step.kind``, optional pre-step ``skill_view`` preface) wired
        to this orchestrator's instance state and delegates the DAG
        traversal there.

        When ``run_writer`` was injected at construction the wrapper also
        opens an audit run on entry, bridges the scheduler's three
        lifecycle hooks (begin / finish / failover) to the writer via
        ``run_in_executor`` (the writer is sync sqlite, callbacks fire
        from the event loop), and finalises the run in the ``finally``
        block — ``cancelled`` if the consumer cancelled mid-stream,
        ``ok`` / ``failed`` otherwise based on the terminal
        :class:`MetaResult`. Writer exceptions are swallowed at
        warning level: persistence is observability, never a turn killer.
        """

        run_id: str | None = None
        loop = asyncio.get_running_loop()

        async def _to_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

        if self._run_writer is not None:
            try:
                run_id = await _to_thread(
                    self._run_writer.begin_run_sync,
                    meta_skill_name=match.plan.name,
                    meta_plan=match.plan,
                    triggered_by=self._triggered_by,
                    inputs=match.inputs,
                    session_key=self._session_key,
                    turn_id=self._turn_id,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("orchestrator.begin_run_failed: %s", exc)

        # Build the three writer hooks (no-op if writer absent or
        # begin_run failed to assign a run_id).
        async def on_step_begin(
            step_id: str,
            effective_skill: str,
            rendered_inputs: dict[str, Any],
        ) -> None:
            if run_id is None or self._run_writer is None:
                return
            step = next((s for s in match.plan.steps if s.id == step_id), None)
            if step is None:
                return
            await _to_thread(
                self._run_writer.begin_step_sync,
                run_id=run_id,
                step=step,
                effective_skill=effective_skill,
                rendered_inputs=rendered_inputs,
            )

        async def on_step_finish(
            step_id: str,
            status: str,
            output_text: str | None,
            error: str | None,
        ) -> None:
            if run_id is None or self._run_writer is None:
                return
            await _to_thread(
                self._run_writer.finish_step_sync,
                run_id=run_id,
                step_id=step_id,
                status=status,
                output_text=output_text,
                error=error,
            )

        async def on_step_failover(
            failed_step_id: str,
            substitute_step_id: str,
            error: str,
        ) -> None:
            if run_id is None or self._run_writer is None:
                return
            await _to_thread(
                self._run_writer.on_step_failover_sync,
                run_id=run_id,
                failed_step_id=failed_step_id,
                substitute_step_id=substitute_step_id,
                error=error,
            )

        final_result: MetaResult | None = None
        cancelled = False
        try:
            async for item in run_dag(
                match,
                dispatch_step_stream=self._dispatch_step_stream,
                yield_skill_view_preface=self._yield_skill_view_preface,
                max_parallelism=self._max_parallelism,
                on_step_begin=on_step_begin if self._run_writer else None,
                on_step_finish=on_step_finish if self._run_writer else None,
                on_step_failover=on_step_failover if self._run_writer else None,
            ):
                if isinstance(item, MetaResult):
                    final_result = item
                yield item
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            if run_id is not None and self._run_writer is not None:
                try:
                    if cancelled:
                        await _to_thread(
                            self._run_writer.finish_run_sync,
                            run_id=run_id,
                            status="cancelled",
                            result=None,
                        )
                    elif final_result is not None:
                        await _to_thread(
                            self._run_writer.finish_run_sync,
                            run_id=run_id,
                            status="ok" if final_result.ok else "failed",
                            result=final_result,
                        )
                    else:
                        # Stream ended without a MetaResult and no
                        # cancellation surfaced — treat as cancelled
                        # (consumer broke out early).
                        await _to_thread(
                            self._run_writer.finish_run_sync,
                            run_id=run_id,
                            status="cancelled",
                            result=None,
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("orchestrator.finish_run_failed: %s", exc)

    async def _yield_skill_view_preface(
        self,
        step_id: str,
        effective_skill: str,
    ) -> AsyncIterator[AgentEvent]:
        async for ev in yield_skill_view_preface(
            step_id, effective_skill, tool_invoker=self._tool_invoker,
        ):
            yield ev

    async def _dispatch_step_stream(
        self,
        step: MetaStep,
        effective_skill: str,
        inputs: dict[str, Any],
        outputs: dict[str, str],
    ) -> AsyncIterator[AgentEvent | _StepDone]:
        """Streaming dispatch — yields nested events then a final :class:`_StepDone`.

        Non-agent kinds (``llm_classify`` / ``tool_call`` / ``skill_exec``)
        have no nested events to forward, so they just compute the text and
        yield a single ``_StepDone``. ``agent`` kind passes the sub-Agent's
        full event stream through to the outer iterator so the user can see
        every inner tool call.
        """

        if step.kind == "llm_classify":
            text = await run_llm_classify_step(
                step,
                inputs,
                outputs,
                llm_chat=self._llm_chat,
                agent_runner=self._agent_runner,
            )
            yield _StepDone(text=text)
            return
        if step.kind == "tool_call":
            text = await run_tool_call_step(
                step,
                inputs,
                outputs,
                tool_invoker=self._tool_invoker,
                agent_runner=self._agent_runner,
            )
            yield _StepDone(text=text)
            return
        if step.kind == "skill_exec":
            text = await run_skill_exec_step(
                step,
                effective_skill,
                inputs,
                outputs,
                skill_loader=self._skill_loader,
                workspace_dir=self._workspace_dir,
            )
            yield _StepDone(text=text)
            return
        # agent kind: forward sub-Agent events as they arrive.
        async for item in run_step_with_skill_stream(
            step,
            effective_skill,
            inputs,
            outputs,
            agent_runner=self._agent_runner,
            skill_loader=self._skill_loader,
        ):
            yield item


def make_agent_runner_from_parent(
    *,
    provider: LLMProvider,
    base_config: AgentConfig,
    tool_definitions: list,
    tool_handler: Any,
    agent_factory: Callable[..., Any],
    workspace_dir: str | None = None,
) -> AgentRunner:
    """Build an :class:`AgentRunner` that mirrors the parent turn's surface.

    ``agent_factory`` is the ``Agent`` class itself (passed in so the
    orchestrator module doesn't import the heavy engine.agent module).

    ``workspace_dir`` is the per-turn resolved workspace path (caller-side
    3-tier: ``ToolContext > metadata > AgentConfig``). Pass it explicitly
    because the parent ``AgentConfig.workspace_dir`` field is typically
    unset by ``TurnRunner._build_agent_for_turn`` — the real value lives in
    the runtime's ``ToolContext`` and must be forwarded here so the
    sub-Agent both knows the path (system_prompt grounding) and resolves
    file tools against it (sub_config.workspace_dir).
    """

    async def _runner(system_prompt: str, user_message: str) -> AsyncIterator[AgentEvent]:
        # Build a fresh AgentConfig keyed off the parent's settings but with
        # the skill body installed as the sub-turn's system prompt. The
        # iteration cap allows for multi-fetch flows (arxiv-deck pulls 6
        # paper abstracts + handles rate-limit retries = easily 10+ rounds)
        # while preventing runaway loops. Past history:
        #   cap=4  → silent failures (no closing plain-text deliverable)
        #   cap=12 → fetch_arxiv truncated mid-flow on real arxiv with
        #             rate-limit + 6 paper title fetches
        #   cap=30 → fits multi-search-engine / arxiv / deep-research
        #             without losing the runaway protection
        #
        # Workspace grounding: the LLM otherwise has NO visibility into
        # where its files should live and guesses paths like
        # `/workspace/foo`, `/Users/.../foo`, or `/tmp/foo` — most of which
        # land outside the configured workspace_dir and trigger
        # sandbox-off-approval prompts that block 60s waiting for human
        # action. Appending the literal workspace path here gives the
        # model a concrete absolute prefix to use with write_file /
        # publish_artifact / etc.
        #
        # The path comes from the factory ``workspace_dir`` parameter
        # (caller-resolved per-turn via ToolContext > metadata > config).
        # We deliberately do NOT read ``base_config.workspace_dir`` — that
        # field is unset on the main Agent's AgentConfig built by
        # TurnRunner._build_agent_for_turn; the live value lives only in
        # the per-call ToolContext and must be threaded through here.
        sub_system_prompt = system_prompt
        if workspace_dir:
            sub_system_prompt = (
                f"{system_prompt}\n\n## Workspace\n"
                f"Your workspace directory is `{workspace_dir}`.\n"
                f"When calling write_file / read_file / list_dir / "
                f"publish_artifact, use absolute paths INSIDE this "
                f"directory. Paths outside it may be blocked or require "
                f"approval."
            )

        sub_config = AgentConfig(
            model_id=getattr(base_config, "model_id", None),
            max_iterations=min(getattr(base_config, "max_iterations", 30), 30),
            system_prompt=sub_system_prompt,
            extra_system_prompt=None,
            metadata=dict(getattr(base_config, "metadata", {}) or {}),
            # Forward the resolved workspace_dir so sub-Agent's write_file /
            # memory_save / shell tools resolve paths inside the operator's
            # workspace rather than falling back to process cwd. Without
            # this, sub-Agents trip workspace_strict ToolError loops in the
            # persist / publish_artifact steps of multi-step DAGs.
            workspace_dir=workspace_dir,
        )

        # Strip meta_invoke from the sub-Agent's tool surface so a step
        # cannot recurse into another meta-skill (pitfall #3 in the
        # mechanism doc: meta-A → meta-B → meta-A loops).
        filtered_tool_definitions = [
            td for td in tool_definitions
            if not (
                getattr(td, "name", None) == "meta_invoke"
                or (isinstance(td, dict) and td.get("name") == "meta_invoke")
            )
        ]
        agent = agent_factory(
            provider=provider,
            config=sub_config,
            tool_definitions=filtered_tool_definitions,
            tool_handler=tool_handler,
        )
        from opensquilla.engine.agent import _flatten_content_blocks
        from opensquilla.engine.types import TextDeltaEvent

        saw_text_delta = False
        async for event in agent.run_turn(user_message):
            if isinstance(event, TextDeltaEvent) and event.text:
                saw_text_delta = True
            yield event

        # Bug fix: when the LLM returns final answer as a non-streaming
        # content block (e.g., deepseek-v3.1-terminus via OpenRouter
        # for some final outputs), no TextDeltaEvent is yielded. The
        # text persists in agent._history but the meta executor only
        # listens for TextDeltaEvent → reports "no plain-text output"
        # falsely. Synthesize a single TextDeltaEvent from the last
        # assistant message's flattened content so the executor sees
        # the same text the transcript stores.
        if not saw_text_delta:
            history = getattr(agent, "_history", None) or []
            for msg in reversed(history):
                if getattr(msg, "role", None) == "assistant":
                    content = msg.content
                    flat = (
                        content
                        if isinstance(content, str)
                        else _flatten_content_blocks(content)
                    ).strip()
                    if flat:
                        yield TextDeltaEvent(text=flat)
                    break

    return _runner


def make_llm_chat_from_provider(
    *,
    provider: LLMProvider,
    base_config: AgentConfig,
    max_tokens: int = 256,
) -> LLMChat:
    """Build a single-turn LLM caller — no tools, no agent loop.

    Concatenates the streamed ``TextDeltaEvent`` payloads and returns the
    final text. Used by ``llm_classify`` steps to avoid sub-Agent overhead.
    ``max_tokens`` defaults to 256 (sufficient for classification); callers
    that need full JSON payloads (e.g. slot-filling) should pass a larger
    value.
    """

    from opensquilla.provider.types import ChatConfig, Message
    from opensquilla.provider.types import TextDeltaEvent as ProviderTextDelta

    async def _chat(system_prompt: str, user_message: str) -> str:
        config = ChatConfig(
            system=system_prompt,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        messages = [Message(role="user", content=user_message)]
        parts: list[str] = []
        async for event in provider.chat(messages, tools=None, config=config):
            if isinstance(event, ProviderTextDelta):
                parts.append(event.text)
        return "".join(parts).strip()

    # base_config is reserved for future use (model selection, capabilities).
    del base_config
    return _chat


def make_tool_invoker_from_handler(
    *,
    tool_handler: Any,
) -> ToolInvoker:
    """Build a direct tool caller that bypasses the LLM.

    Wraps the parent turn's ``AgentToolHandler`` with a synthetic
    :class:`ToolCall`. The result is returned as a string (errors are surfaced
    by raising :class:`RuntimeError` so the orchestrator's step-failure path
    catches them and falls back to a normal turn).
    """

    import uuid

    from opensquilla.tool_boundary import ToolCall

    async def _invoke(tool_name: str, arguments: dict[str, Any]) -> str:
        call = ToolCall(
            tool_use_id=f"meta_tool_{uuid.uuid4().hex[:12]}",
            tool_name=tool_name,
            arguments=arguments,
            origin_trace="meta-orchestrator",
        )
        result = await tool_handler(call)
        if getattr(result, "is_error", False):
            raise RuntimeError(
                f"tool {tool_name!r} failed: {getattr(result, 'content', '')!s}",
            )
        return str(getattr(result, "content", ""))

    return _invoke


# Re-export for type clarity at the import site.
__all__ = [
    "AgentRunner",
    "LLMChat",
    "MetaOrchestrator",
    "ToolInvoker",
    "format_step_prompt",
    "make_agent_runner_from_parent",
    "make_llm_chat_from_provider",
    "make_tool_invoker_from_handler",
    "render_with_args",
    "resolve_route",
]
