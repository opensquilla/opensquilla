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
from opensquilla.skills.meta.executors.llm_classify import (
    run_llm_chat_step,
    run_llm_classify_step,
)
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
from opensquilla.skills.meta.types import MetaMatch, MetaPlan, MetaResult, MetaStep

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
        max_parallelism: int | None = 4,
        # NEW (all optional — preserve legacy callers)
        run_writer: MetaRunWriter | None = None,
        triggered_by: str = "soft_meta_invoke",
        session_key: str | None = None,
        turn_id: str | None = None,
        memory_persist_enabled: bool = True,
        usage_tracker: Any | None = None,
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
        # Concurrency cap fed into ``scheduler.run_dag``. Default 4 matches
        # the public DSL schema / mechanism doc safety budget. Callers that
        # intentionally need a wider fan-out must pass it explicitly.
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
        self._usage_tracker = usage_tracker
        # When False the orchestrator skips any ``skill: memory`` step
        # (the conventional last-step archive pattern). Honoured by
        # ``_dispatch_step_stream`` — see GatewayConfig.meta_skill
        # .persistence.memory_persist_enabled for the wiring.
        self._memory_persist_enabled = memory_persist_enabled

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

        # Inject workspace_dir into inputs so SKILL.md task templates can
        # reference ``{{ inputs.workspace_dir }}`` for deliverable paths
        # (avoids hardcoded ``~/.opensquilla/...`` strings that miss the
        # operator's actual workspace and trip publish_artifact /
        # sandbox-off approval gates). ``inputs`` is a plain dict on a
        # frozen MetaMatch — safe to setdefault. Always set, even when
        # the orchestrator wasn't given a workspace_dir (degraded
        # caller, unit tests), so SKILL.md templates that reference
        # this key don't trip jinja2's UndefinedError. Honours any
        # value the caller already put there.
        if "workspace_dir" not in match.inputs:
            match.inputs["workspace_dir"] = self._workspace_dir or ""

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
                usage_tracker=self._usage_tracker,
                session_key=self._session_key,
                usage_scope_prefix=run_id or f"meta:{match.plan.name}:{id(match)}",
            ):
                if isinstance(item, MetaResult):
                    # Resolve user-facing ``final_text`` per
                    # ``plan.final_text_mode`` before yielding. The
                    # scheduler always seeds ``final_text`` with the last
                    # non-substitute step's output; "auto" mode replaces
                    # that with an LLM-summarised Markdown blurb so the
                    # WebUI doesn't show a raw JSON or path. "raw" and
                    # "step:<id>" modes preserve the legacy behaviour for
                    # skills whose last step is already user-friendly.
                    if item.ok:
                        item.final_text = await self._resolve_final_text(
                            plan=match.plan,
                            current_final_text=item.final_text,
                            step_outputs=item.step_outputs,
                        )
                    final_result = item
                yield item
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            if run_id is not None and self._run_writer is not None:
                try:
                    if cancelled:
                        # A cancelled task may interrupt an awaited executor
                        # future before the sqlite update is visible. The
                        # cancel marker is a single local UPDATE, so keep it
                        # in this task's finalizer.
                        self._run_writer.finish_run_sync(
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

    @staticmethod
    def _is_memory_step(step: MetaStep, effective_skill: str) -> bool:
        """True when this step's deliverable is writing to the memory store.

        Covers two patterns used across bundled meta-skills:
          - ``skill: memory`` (sub-Agent form; ``effective_skill == 'memory'``)
          - ``kind: tool_call`` + ``tool: memory_save`` (direct tool form)

        memory_search reads are intentionally NOT skipped — read-side
        recall is the recall step's only purpose, and silencing it would
        replace the step's signal with a placeholder that downstream
        depends_on links would then propagate.
        """
        if effective_skill == "memory":
            return True
        if step.kind == "tool_call" and step.tool == "memory_save":
            return True
        return False

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

        # Operator-controlled opt-out: when memory persistence is disabled
        # at the config level, short-circuit any step that targets the
        # ``memory`` skill (the conventional last-step archive). The skip
        # is *transparent* to downstream steps — they see a non-empty
        # placeholder output so ``depends_on`` links remain satisfied.
        # Tool-call form (``tool: memory_save``/``memory_search``) is also
        # skipped here so the config knob covers both styles.
        if not self._memory_persist_enabled and self._is_memory_step(
            step, effective_skill
        ):
            yield _StepDone(text="[memory persist skipped by config]")
            return

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
        if step.kind == "llm_chat":
            text = await run_llm_chat_step(
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

    async def _resolve_final_text(
        self,
        *,
        plan: MetaPlan,
        current_final_text: str,
        step_outputs: dict[str, str],
    ) -> str:
        """Derive ``MetaResult.final_text`` per ``plan.final_text_mode``.

        - ``"raw"``         → preserve scheduler-seeded last-step output.
        - ``"step:<id>"``   → outputs[id] verbatim (falls through to current
                              on miss or empty output so callers never get an
                              empty reply).
        - ``"auto"``/other  → LLM post-processes step_outputs into a short
                              Markdown summary; falls back to the seeded
                              value on any failure (missing llm_chat,
                              provider error, empty LLM reply).
        """
        mode = (plan.final_text_mode or "auto").strip()

        if mode == "raw":
            return current_final_text
        if mode.startswith("step:"):
            sid = mode[len("step:"):].strip()
            selected = step_outputs.get(sid, "")
            if selected.strip():
                return selected
            return current_final_text
        if mode != "auto":
            log.warning(
                "orchestrator.unknown_final_text_mode mode=%s skill=%s",
                mode,
                plan.name,
            )
            return current_final_text

        # auto: synthesize a friendly Markdown summary from step_outputs.
        if self._llm_chat is None or not step_outputs:
            return current_final_text
        try:
            summary = await self._summarize_step_outputs(plan, step_outputs)
        except Exception as exc:  # noqa: BLE001 — best-effort UX layer
            log.warning(
                "orchestrator.final_text_summarize_failed skill=%s error=%s",
                plan.name,
                exc,
            )
            return current_final_text
        if not summary.strip():
            return current_final_text
        # Append the scheduler-seeded raw output below the LLM summary
        # (separated by a horizontal rule) so the deliverable's concrete
        # details — proposal IDs, file paths, verdicts, raw verdicts —
        # are preserved verbatim rather than left to whatever the LLM
        # paraphrased. Empty raw output (rare) just yields the summary.
        if not current_final_text.strip():
            return summary
        return f"{summary}\n\n---\n\n**Output details:**\n\n{current_final_text}"

    async def _summarize_step_outputs(
        self,
        plan: MetaPlan,
        step_outputs: dict[str, str],
    ) -> str:
        """One-shot LLM call to render step_outputs as a short Markdown summary.

        Truncates each step's output to 1200 chars to keep the prompt
        bounded (24 steps × 1200 ≈ 29k chars, comfortably inside 32k
        context for budget reasoners). Returns the raw LLM text or an
        empty string if the call produced no content; caller decides
        whether to fall back to the legacy raw value.
        """
        if self._llm_chat is None:
            return ""
        # The orchestrator appends the raw last-step output verbatim
        # below this summary (separated by a horizontal rule), so the
        # summary itself is the *human cover sheet* and does NOT need
        # to reproduce raw fields. Keep it short and scannable.
        system_prompt = (
            "You write a brief Markdown summary (3-6 lines max) of a "
            "meta-skill DAG run, addressed to the operator who triggered "
            "it. The run already succeeded; open with a ✅ emoji on the "
            "first line. The raw step output will be appended below your "
            "summary by the framework, so do NOT copy long blocks "
            "verbatim — quote only short identifiers (paths, IDs, "
            "verdict tokens).\n"
            "Include:\n"
            "  • the meta-skill name in backticks\n"
            "  • the single most important deliverable as a short "
            "identifier (file path, artifact ID, proposal ID, URL, "
            "verdict word) — exact text, not paraphrased\n"
            "  • a one-line next-step hint where one is natural "
            "(\"Run X to apply\", \"Open the file at Y\", \"Verify "
            "with Z\") — omit if no obvious next step\n"
            "Be terse, no preamble, no markdown headings other than the "
            "leading ✅ line. Reply in the same language as the "
            "deliverables (Chinese if outputs are Chinese, English "
            "otherwise)."
        )
        snippets: list[str] = []
        for sid, raw in step_outputs.items():
            truncated = (raw or "")[:1200]
            snippets.append(f"### step `{sid}`\n{truncated}")
        user_msg = (
            f"Meta-skill: `{plan.name}`\n\n"
            + ("\n\n".join(snippets) if snippets else "(no step outputs)")
        )
        return (await self._llm_chat(system_prompt, user_msg)).strip()


def make_agent_runner_from_parent(
    *,
    provider: LLMProvider,
    base_config: AgentConfig,
    tool_definitions: list,
    tool_handler: Any,
    agent_factory: Callable[..., Any],
    workspace_dir: str | None = None,
    usage_tracker: Any | None = None,
    session_key: str | None = None,
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
        # `/workspace/foo`, `~/Documents/foo`, or `/tmp/foo` — most of which
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
            usage_tracker=usage_tracker,
            session_key=session_key,
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
    max_tokens: int = 4096,
    usage_tracker: Any | None = None,
    session_key: str | None = None,
) -> LLMChat:
    """Build a single-turn LLM caller — no tools, no agent loop.

    Concatenates the streamed visible ``TextDeltaEvent`` payloads and returns
    the final text. Used by ``llm_classify`` steps to avoid sub-Agent
    overhead.

    ``max_tokens`` defaults to 4096. The earlier 256 default was sized for
    "classifier returns one short label", which is correct in steady state
    — but reasoning-capable models (e.g. deepseek-v4-flash with
    ``reasoning_format='deepseek'``) emit a chain-of-thought into
    ``reasoning_content`` BEFORE producing the visible label, and that
    chain is counted against the same ``max_tokens`` budget. With 256
    tokens the budget is exhausted inside the reasoning stream and the
    visible content stays empty, producing zero output_chars and tripping
    downstream ``meta_skill_fill_slots`` with an invalid empty argument
    (observed live on meta-skill-creator pick_pattern step 2026-05-23).
    2048 gives reasoning room for classifiers but is too small for final
    deliverable steps such as travel plans and paper sections; 4096 keeps
    those outputs from truncating while still bounding no-tool calls.
    Callers that need very large payloads should still pass a larger value.
    """

    from opensquilla.provider.types import ChatConfig, DoneEvent, Message
    from opensquilla.provider.types import TextDeltaEvent as ProviderTextDelta

    async def _chat(system_prompt: str, user_message: str) -> str:
        config = ChatConfig(
            system=system_prompt,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        messages = [Message(role="user", content=user_message)]
        parts: list[str] = []
        first_error: str = ""
        async for event in provider.chat(messages, tools=None, config=config):
            if isinstance(event, ProviderTextDelta):
                parts.append(event.text)
            elif isinstance(event, DoneEvent):
                if usage_tracker is not None and session_key:
                    usage_tracker.add(
                        session_key,
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                        model_id=event.model or base_config.model_id or "",
                        cache_read_tokens=event.cached_tokens,
                        cache_write_tokens=event.cache_write_tokens,
                    )
            elif type(event).__name__ == "ErrorEvent" and not first_error:
                # Capture provider-level errors (auth, network, illegal
                # header, rate-limit) so the caller does not see a
                # silently-empty response that gets misdiagnosed as
                # "model returned no content". The empty-string fall
                # through that happened before this surfaced as JSON
                # validation failures at the wrong layer.
                first_error = getattr(event, "message", repr(event))
        result = "".join(parts).strip()
        if not result and first_error:
            import structlog
            structlog.get_logger(__name__).warning(
                "meta.llm_chat.provider_error",
                error=first_error,
                max_tokens=max_tokens,
                prompt_chars=len(user_message),
                system_chars=len(system_prompt),
            )
        return result

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
