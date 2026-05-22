"""Executor for ``agent``-kind meta-steps.

Spawns a sub-Agent via the injected ``agent_runner`` callable with the
composed Skill's body as the system prompt and ``format_step_prompt`` as
the user message. The sub-Agent's events flow straight through so the
caller (and the UI) can see every inner tool call; once it finishes a
:class:`_StepDone` is yielded carrying the consolidated plain-text
output.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from opensquilla.engine.types import AgentEvent, TextDeltaEvent, ToolResultEvent
from opensquilla.skills.meta.events import _StepDone
from opensquilla.skills.meta.templating import (
    _expand_skill_placeholders,
    format_step_prompt,
    render_with_args,
)
from opensquilla.skills.meta.types import MetaStep


async def run_step_with_skill_stream(
    step: MetaStep,
    effective_skill: str,
    inputs: dict[str, Any],
    outputs: dict[str, str],
    *,
    agent_runner: Callable[[str, str], AsyncIterator[AgentEvent]],
    skill_loader: Any,
) -> AsyncIterator[AgentEvent | _StepDone]:
    """Streaming sub-Agent step: forward sub-Agent events + capture final text.

    The sub-Agent's own ``ToolUseStart`` / ``ToolUseEnd`` / ``ToolResult``
    and ``TextDelta`` events flow straight through so the outer caller
    (and the UI) can see the inner activity. Once the sub-Agent finishes
    we yield a single :class:`_StepDone` carrying the consolidated text.
    """

    skill_spec = skill_loader.get_by_name(effective_skill)
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
    async for event in agent_runner(system_prompt, user_message):
        # Suppress sub-Agent's terminal DoneEvent — it would prematurely
        # close the WS turn from the user's point of view. Everything
        # else (text deltas, tool use, tool results) is forwarded.
        from opensquilla.engine.types import DoneEvent as _DoneEvent

        if isinstance(event, _DoneEvent):
            continue
        if isinstance(event, TextDeltaEvent):
            final_text_parts.append(event.text)
            # Suppress sub-Agent TextDelta forwarding so its content
            # stays folded inside the parent meta-step:<id> card.
            # The full text is yielded once via _StepDone at end of step,
            # and the scheduler emits a tight ``preview`` (≤100 chars) in
            # the closing ToolResultEvent. UI noise → near zero for
            # text-heavy skills (paper-section-author etc.).
            continue
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


__all__ = ["run_step_with_skill_stream"]
