"""Dataclasses for the Meta-Skill MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RouteCase:
    """One conditional branch on a MetaStep.

    The orchestrator evaluates ``when`` as a Jinja boolean expression against
    ``inputs`` + ``outputs``; the first truthy case wins and ``to`` overrides
    the step's default skill name. Empty route list ⇒ static behavior.
    """

    when: str
    to: str


#: Supported step execution kinds.
#:
#: * ``agent``         — spawn a one-shot sub-Agent with the named skill's
#:                       SKILL.md body as system prompt. Full tool loop.
#:                       Right for genuinely open-ended steps. (MVP default.)
#: * ``llm_classify``  — single constrained LLM call, no tool loop. The model
#:                       must reply with exactly one of ``output_choices``.
#:                       Cheap & deterministic. Use for routing classifiers,
#:                       label extraction, etc.
#: * ``llm_chat``      — single unconstrained LLM call, no tool loop. Use for
#:                       bounded synthesis steps that should not spawn a full
#:                       sub-Agent or call tools.
#: * ``tool_call``     — direct tool handler invocation, no LLM. The named
#:                       ``tool`` is invoked with ``tool_args`` (Jinja-rendered).
#:                       Use for deterministic side-effects (memory_save,
#:                       file writes, etc.).
StepKind = str  # Literal["agent", "llm_classify", "tool_call"] in annotation


@dataclass(frozen=True)
class MetaStep:
    """One step in a Meta-Skill composition DAG.

    ``kind`` selects the execution mode. ``agent`` is the default and
    preserves MVP behavior (full sub-Agent). ``llm_classify`` and
    ``tool_call`` are lighter-weight executors with their own required
    fields validated at parse time.
    """

    id: str
    skill: str
    with_args: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    # Optional Jinja boolean expression evaluated against ``inputs`` and
    # ``outputs`` after dependencies complete. False skips this step while
    # still satisfying downstream ``depends_on`` links with an empty output.
    when: str = ""
    route: tuple[RouteCase, ...] = ()
    # New in B: execution-mode dispatch.
    kind: StepKind = "agent"
    # Required when kind == "llm_classify": the closed set of valid labels.
    output_choices: tuple[str, ...] = ()
    # Required when kind == "tool_call": the tool to invoke and its args
    # (args are Jinja-rendered against ``inputs`` + ``outputs``).
    tool: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    # Optional per-step tool gate (kind == "tool_call" only). Empty
    # tuple = no allowlist (pre-existing behaviour, backwards
    # compatible). When non-empty, the parser cross-validates that
    # ``tool`` is one of these names; the runtime executor also
    # double-checks defensively.
    tool_allowlist: tuple[str, ...] = ()
    # Optional. Names another step in the same plan that should be spawned
    # if this step fails. The substitute's output is mirrored to outputs under
    # THIS step's id, so downstream depends_on links remain satisfied.
    # Empty string = no substitute (DAG fails normally on error).
    on_failure: str = ""


@dataclass(frozen=True)
class MetaPlan:
    """Parsed composition plan for a Meta-Skill."""

    name: str
    triggers: tuple[str, ...]
    priority: int
    steps: tuple[MetaStep, ...]
    fallback_body: str = ""
    # How MetaOrchestrator should derive the user-facing
    # ``MetaResult.final_text``:
    #   "auto" (default): post-process step_outputs via a single LLM call
    #     into a short Markdown summary (status + key deliverables + next
    #     step). Adds ~1-2s and ~¥0.001 per DAG run on v4-flash.
    #   "raw": legacy behaviour — return the last non-substitute step's
    #     output verbatim. Use when the last step already produces a
    #     Markdown report (e.g. summarize / deep-research).
    #   "step:<step_id>": return outputs[step_id] verbatim. Use to point
    #     at a specific deliverable step that is not the last.
    final_text_mode: str = "auto"


@dataclass(frozen=True)
class MetaMatch:
    """Resolver hit — a plan plus the inputs supplied for this turn."""

    plan: MetaPlan
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetaResult:
    """Outcome of MetaOrchestrator.run().

    ``ok=True`` ⇒ ``final_text`` is the user-facing reply (last step output).
    ``ok=False`` ⇒ caller should fall back to a normal turn with
    ``failed_step_id`` and ``step_outputs`` injected as context.
    """

    ok: bool
    final_text: str = ""
    step_outputs: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    failed_step_id: str | None = None
