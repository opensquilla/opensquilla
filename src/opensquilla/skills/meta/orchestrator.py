"""MetaOrchestrator — run a MetaPlan as a fleet of one-shot sub-Agents.

Scheduler semantics
-------------------
* Steps run on a DAG-parallel scheduler (M7): every step whose
  ``depends_on`` set has been satisfied is dispatched concurrently as its
  own ``asyncio.Task``. Events from sibling tasks interleave in arrival
  order, but per-step ordering is preserved
  (``ToolUseStartEvent → [skill_view + nested events] → ToolResultEvent``).
* Each step gets its own sub-Agent: same provider, same tool surface as the
  parent turn, but with the composed Skill's body as the system prompt.
* ``with_args`` is rendered via a tiny restricted Jinja environment
  (``StrictUndefined`` + ``xml_escape / truncate / slugify / tojson`` filters)
  and serialised into the user message of the sub-Agent.
* The sub-Agent's ``TextDeltaEvent`` payloads are concatenated; the final
  assistant text becomes the step's output and is available to downstream
  steps as ``outputs.<step_id>``.
* Any exception during a step short-circuits the whole plan: in-flight
  sibling tasks are cancelled, synthetic ``ToolResultEvent`` close-bracket
  frames are emitted for every step whose ``ToolUseStartEvent`` was already
  forwarded (so the UI never sees a dangling in-progress card), and one
  terminal ``MetaResult(ok=False)`` is yielded. ``TurnRunner`` is expected
  to fall back to a normal turn with ``fallback_body`` + ``step_outputs``
  injected as context.

What the orchestrator intentionally skips (see
docs/proposals/meta-skills/MECHANISM.md §20 for the future work):
input-side taint provenance, sub-turn sandbox narrowing,
large_outputs/artifact_ref, retries, when conditions, persistence to
``meta_skill_runs``, separate operator WS channel.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import structlog

from opensquilla.engine.types import (
    AgentConfig,
    AgentEvent,
    ToolResultEvent,
    ToolUseStartEvent,
)
from opensquilla.provider.protocol import LLMProvider
from opensquilla.skills.meta.events import _StepDone
from opensquilla.skills.meta.executors.agent import run_step_with_skill_stream
from opensquilla.skills.meta.executors.llm_classify import run_llm_classify_step
from opensquilla.skills.meta.executors.skill_exec import run_skill_exec_step
from opensquilla.skills.meta.executors.tool_call import run_tool_call_step
from opensquilla.skills.meta.parser import topological_order
from opensquilla.skills.meta.templating import (
    _coerce_to_choice,  # noqa: F401 — re-exported for tests/back-compat
    _expand_skill_placeholders,  # noqa: F401 — re-exported for tests/back-compat
    _format_classify_prompt,  # noqa: F401 — re-exported for back-compat
    format_step_prompt,  # noqa: F401 — re-exported in __all__
    render_with_args,  # noqa: F401 — re-exported in __all__
    resolve_route,
)
from opensquilla.skills.meta.types import MetaMatch, MetaResult, MetaStep

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Sub-Agent factory protocol
# ---------------------------------------------------------------------------

AgentRunner = Callable[[str, str], AsyncIterator[AgentEvent]]
"""Callable: (system_prompt, user_message) -> async iterator of AgentEvents.

The orchestrator depends only on this minimal protocol — it does NOT own
the Agent construction. The caller (TurnRunner) injects an
:class:`AgentRunner` whose closure captures provider / tool_defs /
tool_handler / usage_tracker from the parent turn.
"""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


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

        DAG-parallel scheduler (M7): steps whose ``depends_on`` is satisfied
        run concurrently; events from different steps interleave in arrival
        order. Per-step ordering is preserved:
        ``ToolUseStartEvent → [skill_view + nested events] → ToolResultEvent``.

        Failure of any step cancels all in-flight sibling tasks and yields
        one terminal ``MetaResult(ok=False)``.
        """
        outputs: dict[str, str] = {}
        try:
            ordered = list(topological_order(match.plan.steps))
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_orchestrator.plan_topo_failed", error=str(exc))
            yield MetaResult(ok=False, error=f"plan topology error: {exc}")
            return

        if not ordered:
            yield MetaResult(ok=True, final_text="", step_outputs={})
            return

        steps_by_id: dict[str, MetaStep] = {s.id: s for s in ordered}
        pending_deps: dict[str, set[str]] = {
            s.id: set(s.depends_on) for s in ordered
        }
        unstarted: set[str] = set(steps_by_id.keys())
        running: dict[str, asyncio.Task[None]] = {}
        last_step_id = ordered[-1].id

        event_queue: asyncio.Queue[
            tuple[str, AgentEvent | MetaResult | _StepDone | Exception]
        ] = asyncio.Queue()

        async def _run_one(step: MetaStep) -> None:
            """Drive a single step; push its events into the shared queue."""
            try:
                routed_to = resolve_route(
                    step.route, inputs=match.inputs, outputs=outputs,
                )
                effective_skill = routed_to or step.skill
                log.info(
                    "meta_orchestrator.step_started",
                    step=step.id,
                    kind=step.kind,
                    skill=effective_skill,
                    default_skill=step.skill,
                    routed=routed_to is not None,
                )
                step_use_id = f"meta_step_{step.id}"
                step_tool_name = f"meta-step:{step.id}"
                await event_queue.put(
                    (
                        step.id,
                        ToolUseStartEvent(
                            tool_use_id=step_use_id,
                            tool_name=step_tool_name,
                        ),
                    ),
                )
                if step.kind in ("skill_exec", "agent"):
                    async for sv_ev in self._yield_skill_view_preface(
                        step.id, effective_skill,
                    ):
                        await event_queue.put((step.id, sv_ev))

                final_text = ""
                async for ev in self._dispatch_step_stream(
                    step, effective_skill, match.inputs, outputs,
                ):
                    if isinstance(ev, _StepDone):
                        final_text = ev.text
                    else:
                        await event_queue.put((step.id, ev))

                outputs[step.id] = final_text
                log.info(
                    "meta_orchestrator.step_finished",
                    step=step.id,
                    kind=step.kind,
                    skill=effective_skill,
                    output_chars=len(final_text),
                    output_preview=final_text[:200],
                )
                preview = (
                    final_text if len(final_text) <= 400 else final_text[:400] + "…"
                )
                await event_queue.put(
                    (
                        step.id,
                        ToolResultEvent(
                            tool_use_id=step_use_id,
                            tool_name=step_tool_name,
                            result=preview,
                            is_error=False,
                            arguments={
                                "kind": step.kind,
                                "skill": effective_skill,
                                "default_skill": step.skill,
                                "routed": routed_to is not None,
                                "output_chars": len(final_text),
                            },
                        ),
                    ),
                )
                await event_queue.put((step.id, _StepDone(text=final_text)))
            except asyncio.CancelledError:
                # Re-raise so gather/wait see the cancellation, but the
                # queue drain in iter_events will not see a _StepDone for
                # this step — that's how the outer loop detects siblings
                # that never completed.
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "meta_orchestrator.step_failed",
                    step=step.id,
                    error=str(exc),
                )
                step_use_id = f"meta_step_{step.id}"
                step_tool_name = f"meta-step:{step.id}"
                await event_queue.put(
                    (
                        step.id,
                        ToolResultEvent(
                            tool_use_id=step_use_id,
                            tool_name=step_tool_name,
                            result=str(exc),
                            is_error=True,
                            arguments={"step": step.id},
                        ),
                    ),
                )
                await event_queue.put((step.id, exc))

        def _spawn_ready() -> None:
            for sid in list(unstarted):
                if not pending_deps[sid]:
                    unstarted.discard(sid)
                    task = asyncio.create_task(_run_one(steps_by_id[sid]))
                    running[sid] = task

        _spawn_ready()
        if not running:
            yield MetaResult(
                ok=False,
                error="no runnable steps (all blocked by dependencies)",
            )
            return

        failure: Exception | None = None
        failed_step_id: str | None = None
        # Step IDs whose ToolUseStartEvent we have already forwarded to the
        # caller but whose matching ToolResultEvent has not yet been yielded.
        # On failure we use this set to emit synthetic close-bracket frames
        # for every still-open step, so the UI never sees a dangling
        # in-progress tool-call card.
        seen_starts: set[str] = set()

        def _track_yielded(ev: AgentEvent, sid: str) -> None:
            if isinstance(ev, ToolUseStartEvent) and ev.tool_name.startswith(
                "meta-step:",
            ):
                seen_starts.add(sid)
            elif isinstance(ev, ToolResultEvent) and ev.tool_name.startswith(
                "meta-step:",
            ):
                seen_starts.discard(sid)

        try:
            while running or not event_queue.empty():
                step_id, item = await event_queue.get()
                if isinstance(item, _StepDone):
                    task = running.pop(step_id, None)
                    if task is not None and not task.done():
                        await task
                    for dependent_id, deps in pending_deps.items():
                        deps.discard(step_id)
                    _spawn_ready()
                    continue
                if isinstance(item, Exception):
                    failure = item
                    failed_step_id = step_id
                    seen_starts.discard(step_id)  # failed step's result already yielded
                    running.pop(step_id, None)
                    for tid, t in list(running.items()):
                        if not t.done():
                            t.cancel()
                    break
                if isinstance(item, MetaResult):
                    # Defensive — _run_one never publishes MetaResult.
                    continue
                if isinstance(item, AgentEvent):
                    _track_yielded(item, step_id)
                yield item
        except BaseException:
            # Generator was closed early (GeneratorExit / task cancellation)
            # or an unexpected error bubbled out of the loop body. Clean up
            # any in-flight sibling tasks so we don't leak them. We
            # intentionally do NOT emit synthetic close-brackets here — the
            # consumer is no longer listening.
            for t in running.values():
                if not t.done():
                    t.cancel()
            for t in running.values():
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            raise

        # On failure: cancelled siblings may have published real
        # ToolResultEvent close-brackets to the queue just before their
        # cancellation took effect. Drain non-blockingly and forward any
        # such results so the UI sees the authentic outcome rather than a
        # synthetic placeholder. Anything still un-closed afterwards gets
        # a synthetic cancellation frame so the UI always sees a balanced
        # ToolUseStart/ToolResult pair per step.
        if failure is not None:
            for t in running.values():
                if not t.done():
                    t.cancel()
            for t in running.values():
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            while not event_queue.empty():
                try:
                    step_id, item = event_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if isinstance(item, ToolResultEvent) and item.tool_name.startswith(
                    "meta-step:",
                ):
                    _track_yielded(item, step_id)
                    yield item
            for orphan_id in sorted(seen_starts):
                yield ToolResultEvent(
                    tool_use_id=f"meta_step_{orphan_id}",
                    tool_name=f"meta-step:{orphan_id}",
                    result="cancelled due to sibling step failure",
                    is_error=True,
                    arguments={
                        "step": orphan_id,
                        "cancelled_by": failed_step_id,
                    },
                )

        if failure is not None:
            yield MetaResult(
                ok=False,
                step_outputs=outputs,
                error=str(failure),
                failed_step_id=failed_step_id,
            )
            return

        yield MetaResult(
            ok=True,
            final_text=outputs.get(last_step_id, ""),
            step_outputs=outputs,
        )

    async def _yield_skill_view_preface(
        self,
        step_id: str,
        effective_skill: str,
    ) -> AsyncIterator[AgentEvent]:
        """Invoke the **real** ``skill_view`` tool before each skill-loading step.

        This is not a synthetic UI hint: it routes through the parent turn's
        registered ``skill_view`` tool via ``self._tool_invoker`` so the call
        goes through the normal tool boundary (audit log, sandbox checks,
        usage tracking) and the ``result`` is whatever ``skill_view`` actually
        returned — not a pre-computed preview of ``SKILL.md``.

        When the tool invoker is not wired (degraded mode used by some tests),
        the preface is skipped silently — the step executor still runs and
        will surface its own loader error if the skill is missing.
        """

        if self._tool_invoker is None:
            return

        sv_use_id = f"meta_skill_view_{step_id}"
        sv_tool_name = "skill_view"
        yield ToolUseStartEvent(
            tool_use_id=sv_use_id,
            tool_name=sv_tool_name,
        )
        try:
            result_text = await self._tool_invoker(
                sv_tool_name,
                {"name": effective_skill},
            )
        except Exception as exc:  # noqa: BLE001 — surface as an error card.
            yield ToolResultEvent(
                tool_use_id=sv_use_id,
                tool_name=sv_tool_name,
                result=str(exc),
                is_error=True,
                arguments={"name": effective_skill},
            )
            return

        yield ToolResultEvent(
            tool_use_id=sv_use_id,
            tool_name=sv_tool_name,
            result=result_text,
            is_error=False,
            arguments={"name": effective_skill},
        )

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
            text = await self._run_llm_classify_step(step, inputs, outputs)
            yield _StepDone(text=text)
            return
        if step.kind == "tool_call":
            text = await self._run_tool_call_step(step, inputs, outputs)
            yield _StepDone(text=text)
            return
        if step.kind == "skill_exec":
            text = await self._run_skill_exec_step(step, effective_skill, inputs, outputs)
            yield _StepDone(text=text)
            return
        # agent kind: forward sub-Agent events as they arrive.
        async for item in self._run_step_with_skill_stream(
            step, effective_skill, inputs, outputs,
        ):
            yield item

    async def _run_step_with_skill_stream(
        self,
        step: MetaStep,
        effective_skill: str,
        inputs: dict[str, Any],
        outputs: dict[str, str],
    ) -> AsyncIterator[AgentEvent | _StepDone]:
        async for item in run_step_with_skill_stream(
            step,
            effective_skill,
            inputs,
            outputs,
            agent_runner=self._agent_runner,
            skill_loader=self._skill_loader,
        ):
            yield item

    async def _run_llm_classify_step(
        self,
        step: MetaStep,
        inputs: dict[str, Any],
        outputs: dict[str, str],
    ) -> str:
        return await run_llm_classify_step(
            step,
            inputs,
            outputs,
            llm_chat=self._llm_chat,
            agent_runner=self._agent_runner,
        )

    async def _run_tool_call_step(
        self,
        step: MetaStep,
        inputs: dict[str, Any],
        outputs: dict[str, str],
    ) -> str:
        return await run_tool_call_step(
            step,
            inputs,
            outputs,
            tool_invoker=self._tool_invoker,
            agent_runner=self._agent_runner,
        )

    async def _run_skill_exec_step(
        self,
        step: MetaStep,
        effective_skill: str,
        inputs: dict[str, Any],
        outputs: dict[str, str],
    ) -> str:
        return await run_skill_exec_step(
            step,
            effective_skill,
            inputs,
            outputs,
            skill_loader=self._skill_loader,
            workspace_dir=self._workspace_dir,
        )


def make_agent_runner_from_parent(
    *,
    provider: LLMProvider,
    base_config: AgentConfig,
    tool_definitions: list,
    tool_handler: Any,
    agent_factory: Callable[..., Any],
) -> AgentRunner:
    """Build an :class:`AgentRunner` that mirrors the parent turn's surface.

    ``agent_factory`` is the ``Agent`` class itself (passed in so the
    orchestrator module doesn't import the heavy engine.agent module).
    """

    async def _runner(system_prompt: str, user_message: str) -> AsyncIterator[AgentEvent]:
        # Build a fresh AgentConfig keyed off the parent's settings but with
        # the skill body installed as the sub-turn's system prompt. The
        # iteration cap is generous because some bundled skills
        # (multi-search-engine, deep-research, xlsx) need several rounds:
        # read SKILL.md → run the wrapped script → summarise. Capping at 4
        # produced silent failures where the sub-Agent did not get a chance
        # to write its closing plain-text deliverable.
        sub_config = AgentConfig(
            model_id=getattr(base_config, "model_id", None),
            max_iterations=min(getattr(base_config, "max_iterations", 12), 12),
            system_prompt=system_prompt,
            extra_system_prompt=None,
            metadata=dict(getattr(base_config, "metadata", {}) or {}),
        )

        agent = agent_factory(
            provider=provider,
            config=sub_config,
            tool_definitions=tool_definitions,
            tool_handler=tool_handler,
        )
        async for event in agent.run_turn(user_message):
            yield event

    return _runner


def make_llm_chat_from_provider(
    *,
    provider: LLMProvider,
    base_config: AgentConfig,
) -> LLMChat:
    """Build a single-turn LLM caller — no tools, no agent loop.

    Concatenates the streamed ``TextDeltaEvent`` payloads and returns the
    final text. Used by ``llm_classify`` steps to avoid sub-Agent overhead.
    """

    from opensquilla.provider.types import ChatConfig, Message
    from opensquilla.provider.types import TextDeltaEvent as ProviderTextDelta

    async def _chat(system_prompt: str, user_message: str) -> str:
        config = ChatConfig(
            system=system_prompt,
            max_tokens=256,
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


# ``_Coroutine`` placeholder used by some optional type-checkers; not needed
# at runtime but documents the intent of ``AgentRunner`` returning an async
# iterator rather than a coroutine.
_Coroutine = Awaitable  # noqa: F841 — kept to silence "unused import" warnings.
