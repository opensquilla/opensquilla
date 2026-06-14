"""Registration of the ``meta_invoke`` tool.

The tool exists in the registry so it appears in the LLM's tool
catalogue and so policy checks apply via the standard dispatcher
preflight. Its handler body is a routing guard: the actual execution
happens inside ``Agent._run_one_streaming``, which intercepts
``tc.tool_name == 'meta_invoke'`` before the standard ``_execute_tool``
path. If this handler ever fires, something is misconfigured.

Visibility: ``exposed_by_default=False``. ``meta_invoke`` is
conditionally surfaced by ``SkillInjector`` (via
``ToolContext.surfaced_tools``) when at least one ``kind=meta`` skill
is present in ``<available_skills>``. Until Task 4 (SkillInjector)
wires this up, the tool will NOT be visible to the LLM at all — that
is intentional, as exposing the tool with no meta-skills in the
catalogue would invite hallucinated calls.

See ``docs/superpowers/specs/2026-05-19-meta-invoke-soft-activation-design.md``.
"""

from __future__ import annotations

from opensquilla.tools.registry import tool


@tool(
    name="meta_invoke",
    description=(
        "Run a meta-skill end-to-end: a multi-step DAG where the framework "
        "runs sub-skills. Call this tool with the exact name of a "
        "<skill kind='meta'> entry from <available_skills>. Do NOT invent "
        "names. On success, the meta-skill's deliverable becomes the "
        "assistant's response for this turn."
    ),
    params={
        "name": {
            "type": "string",
            "description": (
                "Exact meta-skill name from <available_skills> "
                "kind='meta' entries"
            ),
        },
    },
    required=["name"],
    exposed_by_default=False,
)
async def meta_invoke(name: str) -> str:  # noqa: ARG001 — name unused in guard
    raise RuntimeError(
        "meta_invoke must be intercepted by Agent._run_one_streaming "
        "before reaching the registry handler. This RuntimeError indicates "
        "a configuration bug — the dispatch loop did not detect the "
        "meta_invoke tool_name in time. See "
        "docs/superpowers/specs/2026-05-19-meta-invoke-soft-activation-design.md "
        "for the intended dispatch path.",
    )
