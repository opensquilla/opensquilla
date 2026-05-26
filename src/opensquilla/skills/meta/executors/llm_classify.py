"""Executor for ``llm_classify`` meta-steps.

A single constrained LLM call — no sub-Agent loop, no tools. The model is
told to reply with exactly one label from ``step.output_choices``; the
reply is normalised via :func:`_coerce_to_choice`. When ``llm_chat`` is
not wired (degraded mode used by some tests) the call falls back to
draining the sub-Agent runner with the same prompt.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from opensquilla.engine.types import AgentEvent, TextDeltaEvent, ToolResultEvent
from opensquilla.skills.meta.templating import (
    _coerce_to_choice,
    _format_classify_prompt,
    render_with_args,
)
from opensquilla.skills.meta.types import MetaStep


async def _drain_agent_runner(
    system_prompt: str,
    user_message: str,
    *,
    agent_runner: Callable[[str, str], AsyncIterator[AgentEvent]],
) -> str:
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
    async for event in agent_runner(system_prompt, user_message):
        if isinstance(event, TextDeltaEvent):
            final_text_parts.append(event.text)
            continue
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


async def run_llm_classify_step(
    step: MetaStep,
    inputs: dict[str, Any],
    outputs: dict[str, str],
    *,
    llm_chat: Callable[[str, str], Awaitable[str]] | None,
    agent_runner: Callable[[str, str], AsyncIterator[AgentEvent]],
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

    if llm_chat is None:
        raw = await _drain_agent_runner(
            system_prompt, user_message, agent_runner=agent_runner,
        )
    else:
        raw = await llm_chat(system_prompt, user_message)
    return _coerce_to_choice(raw, choices)


async def run_llm_chat_step(
    step: MetaStep,
    inputs: dict[str, Any],
    outputs: dict[str, str],
    *,
    llm_chat: Callable[[str, str], Awaitable[str]] | None,
    agent_runner: Callable[[str, str], AsyncIterator[AgentEvent]],
) -> str:
    """Single unconstrained LLM call — no tools and no sub-Agent loop."""

    rendered_args = render_with_args(step.with_args, inputs=inputs, outputs=outputs)
    system_prompt = str(
        rendered_args.get("system")
        or "You are a precise workflow step. Reply only with the requested deliverable.",
    )
    user_message = str(
        rendered_args.get("task")
        or rendered_args.get("prompt")
        or rendered_args.get("text")
        or "",
    )
    if not user_message.strip():
        raise RuntimeError(f"step {step.id!r} (kind=llm_chat) has no task/prompt/text")

    if llm_chat is None:
        return await _drain_agent_runner(
            system_prompt,
            user_message,
            agent_runner=agent_runner,
        )
    return (await llm_chat(system_prompt, user_message)).strip()


__all__ = ["_drain_agent_runner", "run_llm_chat_step", "run_llm_classify_step"]
