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

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

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

        Thin wrapper around :func:`scheduler.run_dag`: builds the two
        executor-shaped callables (per-step dispatch keyed on
        ``step.kind``, optional pre-step ``skill_view`` preface) wired
        to this orchestrator's instance state and delegates the DAG
        traversal there.
        """

        async for item in run_dag(
            match,
            dispatch_step_stream=self._dispatch_step_stream,
            yield_skill_view_preface=self._yield_skill_view_preface,
        ):
            yield item

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
