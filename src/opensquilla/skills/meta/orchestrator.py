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
import html
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass as _dataclass
from typing import Any

import jinja2
import structlog

from opensquilla.engine.types import (
    AgentConfig,
    AgentEvent,
    TextDeltaEvent,
    ToolResultEvent,
    ToolUseStartEvent,
)
from opensquilla.provider.protocol import LLMProvider
from opensquilla.skills.meta.parser import topological_order
from opensquilla.skills.meta.types import MetaMatch, MetaResult, MetaStep, RouteCase

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Restricted Jinja environment for ``with_args`` rendering
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _filter_xml_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _filter_truncate(value: object, length: int = 1024) -> str:
    text = str(value)
    if length <= 0 or len(text) <= length:
        return text
    return text[:length]


def _filter_slugify(value: object) -> str:
    return _SLUG_RE.sub("-", str(value)).strip("-").lower()[:128]


def _build_jinja_env() -> jinja2.Environment:
    env = jinja2.Environment(
        undefined=jinja2.StrictUndefined,
        autoescape=False,
        extensions=[],
        keep_trailing_newline=False,
    )
    # Strip unsafe globals/filters; install our allowlist.
    env.globals.clear()
    env.filters = {
        "xml_escape": _filter_xml_escape,
        "truncate": _filter_truncate,
        "slugify": _filter_slugify,
        "tojson": jinja2.filters.do_tojson,
        "default": jinja2.filters.do_default,
        "length": len,
        "join": jinja2.filters.do_join,
    }
    return env


_JINJA_ENV = _build_jinja_env()


def render_with_args(
    template_map: dict[str, Any],
    *,
    inputs: dict[str, Any],
    outputs: dict[str, str],
) -> dict[str, Any]:
    """Render every leaf string in ``template_map`` against ``inputs/outputs``.

    Non-string leaves pass through unchanged. Nested dicts / lists are walked
    recursively. A ``jinja2.UndefinedError`` becomes a regular ValueError so
    the orchestrator's StepFailure handling treats it as a normal failure.
    """

    context = {
        "inputs": inputs,
        "outputs": outputs,
    }

    def _render(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return _JINJA_ENV.from_string(value).render(**context)
            except jinja2.UndefinedError as exc:
                raise ValueError(f"undefined template variable: {exc}") from exc
            except jinja2.TemplateSyntaxError as exc:
                raise ValueError(f"template syntax error: {exc}") from exc
        if isinstance(value, dict):
            return {k: _render(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_render(item) for item in value]
        return value

    rendered = _render(template_map)
    assert isinstance(rendered, dict)
    return rendered


def resolve_route(
    cases: tuple[RouteCase, ...],
    *,
    inputs: dict[str, Any],
    outputs: dict[str, str],
) -> str | None:
    """Return the ``to`` skill of the first case whose ``when`` evaluates truthy.

    Returns ``None`` when ``cases`` is empty or no case matches — caller falls
    back to the step's default ``skill`` name.  Jinja errors are surfaced as
    :class:`ValueError` so the orchestrator's step-failure path catches them.
    """

    if not cases:
        return None
    context = {"inputs": inputs, "outputs": outputs}
    for index, case in enumerate(cases):
        # Wrap the expression as ``{{ (<expr>) | tojson }}`` is overkill; use
        # Jinja's ``compile_expression`` so the user writes a real expression
        # (``outputs.classify == 'URL'``) rather than a template.
        try:
            expr = _JINJA_ENV.compile_expression(case.when)
        except jinja2.TemplateSyntaxError as exc:
            raise ValueError(
                f"route[{index}] when expression syntax error: {exc}",
            ) from exc
        try:
            value = expr(**context)
        except jinja2.UndefinedError as exc:
            raise ValueError(
                f"route[{index}] when references undefined variable: {exc}",
            ) from exc
        if value:
            return case.to
    return None


def format_step_prompt(skill_name: str, args: dict[str, Any]) -> str:
    """Render the user-message payload that drives one sub-Agent turn."""

    if not args:
        return (
            f"Run the {skill_name} skill with no arguments. "
            "Produce the deliverable described in its SKILL.md."
        )

    lines = [f"Invoke the {skill_name} skill with the following arguments:"]
    for key, value in args.items():
        if isinstance(value, str):
            lines.append(f"- {key}: {value}")
        else:
            lines.append(f"- {key}: {value!r}")
    lines.append(
        "\nWhen the work is complete, reply with the final deliverable as plain text. "
        "If the skill produced a file, include the absolute path on the last line.",
    )
    return "\n".join(lines)


def _format_classify_prompt(step: MetaStep, args: dict[str, Any]) -> str:
    """Render the user-message body for an ``llm_classify`` step.

    Concatenates the rendered ``with_args`` values into a flat prompt — the
    classifier system prompt already constrains the output, so we don't
    re-state the choices here.
    """

    if not args:
        return ""
    parts: list[str] = []
    for key, value in args.items():
        text = value if isinstance(value, str) else repr(value)
        # Skip purely-decorative keys; otherwise prefix with the key for clarity.
        if key in ("text", "prompt", "task", "input"):
            parts.append(text)
        else:
            parts.append(f"{key}: {text}")
    return "\n".join(parts).strip()


def _expand_skill_placeholders(skill_spec: Any) -> str:
    """Substitute ``{baseDir}`` (and aliases) in a skill body with its real path.

    Bundled SKILL.md files reference helper scripts via ``{baseDir}/scripts/foo.py``.
    Regular skill invocation routes the body through tooling that resolves
    these placeholders; meta-skill composition injects the body directly into
    a sub-Agent system prompt, so we must do the same substitution here —
    otherwise the sub-Agent sees a literal ``{baseDir}`` and tries to glob
    the workspace for it.
    """

    body = (getattr(skill_spec, "content", "") or "").strip()
    base_dir = str(getattr(skill_spec, "base_dir", "") or "").rstrip("/")
    if not base_dir:
        return body
    # Cover both the canonical ``{baseDir}`` and the snake-case alias some
    # internal tools emit; keep substitution simple (no regex) so the body
    # remains byte-stable for callers that hash it.
    return body.replace("{baseDir}", base_dir).replace("{base_dir}", base_dir)


def _coerce_to_choice(raw: str, choices: list[str]) -> str:
    """Normalise a model reply to one of the allowed labels.

    Match precedence: exact → quote/punctuation-stripped → case-insensitive →
    uppercase-substring containment. When nothing matches the original trimmed
    text is returned — downstream route ``when`` clauses use Python's ``in``
    against it and can still succeed.
    """

    if not choices:
        return raw.strip()
    text = raw.strip()
    if text in choices:
        return text
    stripped = text.strip("'\"`.,!? \t\r\n")
    if stripped in choices:
        return stripped
    upper = stripped.upper()
    for choice in choices:
        if upper == choice.upper():
            return choice
    for choice in choices:
        if choice.upper() in upper:
            return choice
    return stripped or text


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


@_dataclass(frozen=True)
class _StepDone:
    """Internal sentinel — terminates a step's streaming sub-iterator.

    Not a public event type; the orchestrator strips these before forwarding
    the outer stream to callers. Carrying the text inline avoids needing a
    side-channel (mutable holder / instance variable) to communicate the
    step's final string output back to ``iter_events``.
    """

    text: str


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
    ) -> None:
        self._agent_runner = agent_runner
        self._skill_loader = skill_loader
        self._llm_chat = llm_chat
        self._tool_invoker = tool_invoker

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
        """Streaming sub-Agent step: forward sub-Agent events + capture final text.

        The sub-Agent's own ``ToolUseStart`` / ``ToolUseEnd`` / ``ToolResult``
        and ``TextDelta`` events flow straight through so the outer caller
        (and the UI) can see the inner activity. Once the sub-Agent finishes
        we yield a single :class:`_StepDone` carrying the consolidated text.
        """

        skill_spec = self._skill_loader.get_by_name(effective_skill)
        if skill_spec is None:
            raise ValueError(
                f"step {step.id!r}: skill {effective_skill!r} not found in loader",
            )
        if getattr(skill_spec, "kind", "skill") == "meta":
            raise ValueError(
                f"step {step.id!r}: cannot compose another meta-skill ({effective_skill!r})",
            )

        rendered_args = render_with_args(
            step.with_args,
            inputs=inputs,
            outputs=outputs,
        )
        user_message = format_step_prompt(effective_skill, rendered_args)
        system_prompt = _expand_skill_placeholders(skill_spec)

        final_text_parts: list[str] = []
        last_error_tool_result: str = ""
        async for event in self._agent_runner(system_prompt, user_message):
            # Suppress sub-Agent's terminal DoneEvent — it would prematurely
            # close the WS turn from the user's point of view. Everything
            # else (text deltas, tool use, tool results) is forwarded.
            from opensquilla.engine.types import DoneEvent as _DoneEvent

            if isinstance(event, _DoneEvent):
                continue
            if isinstance(event, TextDeltaEvent):
                final_text_parts.append(event.text)
            elif isinstance(event, ToolResultEvent):
                result_text = event.result if isinstance(event.result, str) else ""
                if result_text.strip() and getattr(event, "is_error", False):
                    last_error_tool_result = result_text
            yield event

        text = "".join(final_text_parts).strip()
        if text:
            yield _StepDone(text=text)
            return
        if last_error_tool_result:
            raise RuntimeError(
                f"sub-agent produced no plain-text output; last tool error: "
                f"{last_error_tool_result[:200]}",
            )
        raise RuntimeError(
            "sub-agent produced no plain-text output and no tool results",
        )

    async def _run_llm_classify_step(
        self,
        step: MetaStep,
        inputs: dict[str, Any],
        outputs: dict[str, str],
    ) -> str:
        """Single constrained LLM call — no tool loop, no sub-Agent overhead.

        The model is told to reply with exactly one label from
        ``step.output_choices``. The reply is normalised and coerced via
        :func:`_coerce_to_choice`. Falls back to the agent runner when
        ``llm_chat`` was not wired (degraded mode).
        """

        rendered_args = render_with_args(step.with_args, inputs=inputs, outputs=outputs)
        user_message = _format_classify_prompt(step, rendered_args)
        choices = list(step.output_choices)
        choices_str = " | ".join(choices)
        system_prompt = (
            "You are a deterministic classifier. Read the user's input and decide "
            f"which single label applies. Reply with EXACTLY ONE of: {choices_str}\n"
            "Do not add quotes, punctuation, prefixes, or explanations — emit only "
            "the label."
        )

        if self._llm_chat is None:
            raw = await self._drain_agent_runner(system_prompt, user_message)
        else:
            raw = await self._llm_chat(system_prompt, user_message)
        return _coerce_to_choice(raw, choices)

    async def _run_tool_call_step(
        self,
        step: MetaStep,
        inputs: dict[str, Any],
        outputs: dict[str, str],
    ) -> str:
        """Direct tool invocation — bypasses the LLM entirely.

        ``step.tool_args`` are Jinja-rendered against ``inputs`` + ``outputs``
        then passed to ``self._tool_invoker``. Falls back to the agent runner
        with a one-shot tool-call instruction when ``tool_invoker`` is None.
        """

        rendered_args = render_with_args(step.tool_args, inputs=inputs, outputs=outputs)

        if self._tool_invoker is None:
            import json as _json

            args_blob = _json.dumps(rendered_args, ensure_ascii=False, default=str)
            system_prompt = (
                f"Invoke the {step.tool!r} tool exactly once with the JSON "
                "arguments provided. Do not call any other tools. After the tool "
                "returns, reply with its result as plain text."
            )
            user_message = f"Tool: {step.tool}\nArguments: {args_blob}"
            return await self._drain_agent_runner(system_prompt, user_message)

        return await self._tool_invoker(step.tool, rendered_args)

    async def _run_skill_exec_step(
        self,
        step: MetaStep,
        effective_skill: str,
        inputs: dict[str, Any],
        outputs: dict[str, str],
    ) -> str:
        """Run a wrapped-CLI skill via its ``entrypoint`` manifest — no LLM.

        Resolves ``skill.entrypoint`` from the loader, renders ``command`` /
        ``args`` against ``inputs`` + ``outputs`` + ``with`` (the step's
        rendered ``with_args``), then ``asyncio.create_subprocess_exec``\\s
        the process. Stdout is interpreted per ``parse`` (``text`` |
        ``json`` | ``lines``) and returned as the step output.

        Errors (missing entrypoint, non-zero exit, timeout, invalid JSON when
        ``parse=json``) raise :class:`RuntimeError` so the orchestrator's
        step-failure path catches them and the meta-skill falls back to a
        normal turn instead of silently feeding garbage downstream.
        """

        import asyncio
        import json as _json
        import shlex

        skill_spec = self._skill_loader.get_by_name(effective_skill)
        if skill_spec is None:
            raise RuntimeError(
                f"step {step.id!r}: skill {effective_skill!r} not found in loader",
            )
        entrypoint = getattr(skill_spec, "entrypoint", None)
        if not isinstance(entrypoint, dict) or not entrypoint:
            raise RuntimeError(
                f"step {step.id!r}: skill {effective_skill!r} has no "
                f"entrypoint manifest — cannot run as skill_exec",
            )
        command_raw = entrypoint.get("command")
        if not isinstance(command_raw, str) or not command_raw.strip():
            raise RuntimeError(
                f"step {step.id!r}: skill {effective_skill!r} entrypoint "
                f"missing non-empty 'command'",
            )

        # Render with_args first so it becomes part of the Jinja context for
        # the entrypoint templates (lets the entrypoint reference ``with.q``
        # in addition to the global ``inputs`` / ``outputs``).
        rendered_with = render_with_args(step.with_args, inputs=inputs, outputs=outputs)
        base_dir = str(getattr(skill_spec, "base_dir", "") or "")
        context = {
            "inputs": inputs,
            "outputs": outputs,
            "with": rendered_with,
            "baseDir": base_dir,
        }

        def _render(value: str) -> str:
            try:
                return _JINJA_ENV.from_string(value).render(**context)
            except jinja2.UndefinedError as exc:
                raise RuntimeError(f"entrypoint template undefined: {exc}") from exc
            except jinja2.TemplateSyntaxError as exc:
                raise RuntimeError(f"entrypoint template syntax error: {exc}") from exc

        # `{baseDir}` is a static placeholder (not Jinja) — substitute before
        # rendering so it survives shlex.split() below.
        command_str = command_raw.replace("{baseDir}", base_dir)
        command_str = _render(command_str)

        raw_args = entrypoint.get("args") or []
        if not isinstance(raw_args, list):
            raise RuntimeError(
                f"step {step.id!r}: entrypoint.args must be a list",
            )
        rendered_args: list[str] = []
        for index, item in enumerate(raw_args):
            if not isinstance(item, str):
                raise RuntimeError(
                    f"step {step.id!r}: entrypoint.args[{index}] must be a string",
                )
            rendered_args.append(_render(item.replace("{baseDir}", base_dir)))

        # Resolve cwd early so assemble's relative-path anchoring matches the
        # subprocess's working directory.
        cwd = entrypoint.get("cwd")
        if isinstance(cwd, str) and cwd:
            cwd = cwd.replace("{baseDir}", base_dir)
            workdir: str | None = cwd
        else:
            workdir = base_dir or None

        # Optional assemble: render templated files to disk before exec.
        assemble_raw = entrypoint.get("assemble") or []
        if assemble_raw and not isinstance(assemble_raw, list):
            raise RuntimeError(
                f"step {step.id!r}: entrypoint.assemble must be a list of mappings",
            )
        for index, entry in enumerate(assemble_raw):
            if not isinstance(entry, dict):
                raise RuntimeError(
                    f"step {step.id!r}: entrypoint.assemble[{index}] must be a mapping",
                )
            into_raw = entry.get("into")
            template_raw = entry.get("from_template")
            if not isinstance(into_raw, str) or not into_raw:
                raise RuntimeError(
                    f"step {step.id!r}: entrypoint.assemble[{index}] missing 'into'",
                )
            if not isinstance(template_raw, str):
                raise RuntimeError(
                    f"step {step.id!r}: entrypoint.assemble[{index}] missing "
                    f"'from_template'",
                )
            into_path_str = _render(into_raw.replace("{baseDir}", base_dir))
            template_body = _render(template_raw.replace("{baseDir}", base_dir))
            # Relative paths anchor to cwd (workdir), absolute paths pass through.
            from pathlib import Path as _Path

            target = _Path(into_path_str)
            if not target.is_absolute() and workdir:
                target = _Path(workdir) / target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(template_body, encoding="utf-8")
            log.info(
                "meta_orchestrator.skill_exec_assemble",
                step=step.id,
                into=str(target),
                bytes=len(template_body),
            )

        argv = shlex.split(command_str) + rendered_args
        if not argv:
            raise RuntimeError(f"step {step.id!r}: empty argv after rendering")

        timeout_raw = entrypoint.get("timeout", 60.0)
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError):
            timeout = 60.0
        parse_mode = str(entrypoint.get("parse", "text"))

        # Optional stdin: render Jinja template and pipe to the subprocess.
        stdin_raw = entrypoint.get("stdin")
        stdin_bytes: bytes | None = None
        if isinstance(stdin_raw, str) and stdin_raw:
            stdin_text = _render(stdin_raw.replace("{baseDir}", base_dir))
            try:
                stdin_bytes = stdin_text.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise RuntimeError(
                    f"step {step.id!r}: entrypoint.stdin rendered to text that "
                    f"cannot be encoded as UTF-8: {exc}",
                ) from exc
        elif stdin_raw not in (None, ""):
            raise RuntimeError(
                f"step {step.id!r}: entrypoint.stdin must be a string template",
            )

        log.info(
            "meta_orchestrator.skill_exec_spawn",
            step=step.id,
            skill=effective_skill,
            argv_head=argv[0],
            argc=len(argv),
            timeout=timeout,
            parse=parse_mode,
            stdin_bytes=len(stdin_bytes) if stdin_bytes is not None else 0,
        )

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes), timeout=timeout,
            )
        except TimeoutError as exc:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise RuntimeError(
                f"skill {effective_skill!r} timed out after {timeout}s",
            ) from exc

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(
                f"skill {effective_skill!r} exited {proc.returncode}: "
                f"{stderr_text[:500]}",
            )

        if parse_mode == "json":
            try:
                parsed = _json.loads(stdout_text)
            except _json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"skill {effective_skill!r} stdout was not valid JSON: {exc}",
                ) from exc
            return _json.dumps(parsed, ensure_ascii=False)
        if parse_mode == "lines":
            lines = [ln for ln in stdout_text.splitlines() if ln.strip()]
            return _json.dumps(lines, ensure_ascii=False)
        return stdout_text.strip()

    async def _drain_agent_runner(self, system_prompt: str, user_message: str) -> str:
        """Run the sub-Agent and concatenate its text output.

        Plain-text output is the contract: sub-Agents are instructed to write
        a final-deliverable summary even when their real work happens through
        tools. If the sub-Agent ends without any plain text we raise
        :class:`RuntimeError` so the orchestrator short-circuits to its
        fallback path instead of feeding the next step whatever the last tool
        happened to print (which is usually noise from an introspection
        probe like ``glob_search`` or ``list_dir``).

        Trailing-error context is included in the exception message to make
        the failure diagnosable from the fallback turn.
        """

        final_text_parts: list[str] = []
        last_error_tool_result: str = ""
        async for event in self._agent_runner(system_prompt, user_message):
            if isinstance(event, TextDeltaEvent):
                final_text_parts.append(event.text)
            elif isinstance(event, ToolResultEvent):
                result_text = event.result if isinstance(event.result, str) else ""
                if result_text.strip() and getattr(event, "is_error", False):
                    last_error_tool_result = result_text
        text = "".join(final_text_parts).strip()
        if text:
            return text
        if last_error_tool_result:
            raise RuntimeError(
                f"sub-agent produced no plain-text output; last tool error: "
                f"{last_error_tool_result[:200]}",
            )
        raise RuntimeError(
            "sub-agent produced no plain-text output and no tool results",
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
