"""DAG-parallel scheduler for MetaOrchestrator.

Topologically orders the plan, dispatches each ready step as its own
``asyncio.Task``, drains a shared event queue, preserves per-step
ordering (``ToolUseStartEvent → [skill_view + nested events] →
ToolResultEvent``), short-circuits on failure (cancel siblings + emit
synthetic close-brackets for already-opened steps), and yields one
terminal :class:`MetaResult`.

The two executor-shaped callables (``dispatch_step_stream`` for the
per-step body, ``yield_skill_view_preface`` for the optional pre-step
``skill_view`` tool invocation) are injected by the orchestrator
facade so the scheduler stays decoupled from the concrete executors.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import structlog

from opensquilla.engine.types import (
    AgentEvent,
    ToolResultEvent,
    ToolUseStartEvent,
)
from opensquilla.skills.meta.events import _StepDone
from opensquilla.skills.meta.parser import topological_order
from opensquilla.skills.meta.templating import resolve_route
from opensquilla.skills.meta.types import MetaMatch, MetaResult, MetaStep

log = structlog.get_logger(__name__)


async def run_dag(
    match: MetaMatch,
    *,
    dispatch_step_stream: Callable[
        [MetaStep, str, dict[str, Any], dict[str, str]],
        AsyncIterator[AgentEvent | _StepDone],
    ],
    yield_skill_view_preface: Callable[
        [str, str], AsyncIterator[AgentEvent],
    ],
    max_parallelism: int | None = None,
) -> AsyncIterator[AgentEvent | MetaResult]:
    """Run the plan and stream a flat sequence of events for the UI.

    DAG-parallel scheduler (M7): steps whose ``depends_on`` is satisfied
    run concurrently; events from different steps interleave in arrival
    order. Per-step ordering is preserved:
    ``ToolUseStartEvent → [skill_view + nested events] → ToolResultEvent``.

    Failure of any step cancels all in-flight sibling tasks and yields
    one terminal ``MetaResult(ok=False)``.

    ``max_parallelism``: optional concurrency cap. ``None`` (default) is
    unbounded — every step whose deps are satisfied is spawned
    immediately. An integer ``N`` limits the in-flight task pool to at
    most ``N``; any extra ready steps stay queued in ``unstarted`` and
    are picked up on the next ``_spawn_ready()`` (called after each
    ``_StepDone``). Guardrails fan-out for meta-skills with many
    independent steps so we don't fan token usage past provider rate
    limits.
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
                async for sv_ev in yield_skill_view_preface(
                    step.id, effective_skill,
                ):
                    await event_queue.put((step.id, sv_ev))

            final_text = ""
            async for ev in dispatch_step_stream(
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
            if max_parallelism is not None and len(running) >= max_parallelism:
                # Cap reached — leave remaining ready steps in
                # ``unstarted`` for the next _spawn_ready() call.
                break
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


__all__ = ["run_dag"]
