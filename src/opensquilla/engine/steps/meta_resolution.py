"""Pipeline step: detect Meta-Skill trigger matches and stash them on the turn.

MVP behaviour
-------------
* Scans the loaded skills for entries with ``kind == "meta"``.
* Matches the current user message (case-insensitive substring) against
  each meta-skill's ``triggers``.
* If at least one matches, the highest ``meta_priority`` wins; the
  resulting :class:`MetaMatch` is written to
  ``ctx.metadata['meta_match']`` so downstream steps (``filter_skills``)
  can short-circuit and ``TurnRunner`` can branch into the orchestrator.
* Any parse error on a meta-skill is logged and skipped — the rest of
  the turn falls back to the normal path (fail-open).

Intentionally minimal: no retrieval/semantic fallback, no per-channel
gating, no operator audit log entry beyond a structured log line.
"""

from __future__ import annotations

import re

import structlog

from opensquilla.engine.pipeline import TurnContext
from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch

log = structlog.get_logger(__name__)


def _trigger_matches(trigger: str, message_lower: str) -> bool:
    """Match a trigger phrase against the user message.

    * Pure-ASCII triggers (English) require word boundaries — so the
      trigger "research report" does NOT fire on
      "How does the *research report* meta-skill work?" because the
      phrase is embedded in a larger sentence about the skill itself.
    * Triggers containing CJK characters fall back to substring match
      since Chinese phrases have no word boundaries in the regex sense
      and are typically distinctive enough (e.g. "合规审计") that
      substring matching does not produce ambiguous fires.
    """
    tl = trigger.lower()
    if tl not in message_lower:
        return False
    if all(ord(c) < 128 for c in tl):
        return bool(re.search(r"\b" + re.escape(tl) + r"\b", message_lower))
    return True


async def meta_resolution(ctx: TurnContext) -> TurnContext:
    """Resolve a Meta-Skill trigger and stash a MetaMatch in metadata."""

    loader = ctx.metadata.get("skill_loader")
    if loader is None:
        return ctx

    try:
        all_skills = loader.load_all()
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        log.warning("meta_resolution.load_failed", error=str(exc))
        return ctx

    # Use ``ctx.message`` (not ``semantic_message``) so the string used
    # for matching is the same one stuffed into ``MetaMatch.inputs``
    # downstream. Earlier divergence — match on semantic, render on raw
    # — meant downstream Jinja templates could see a different message
    # than the one that fired the trigger.
    message_lower = (ctx.message or "").lower()
    if not message_lower:
        return ctx

    matched: list[tuple[int, str, object]] = []
    for spec in all_skills:
        if getattr(spec, "kind", "skill") != "meta":
            continue
        triggers = getattr(spec, "triggers", None) or []
        if not any(
            isinstance(t, str) and t and _trigger_matches(t, message_lower) for t in triggers
        ):
            continue
        try:
            plan = parse_meta_plan(spec)
        except MetaPlanError as exc:
            log.warning(
                "meta_resolution.plan_invalid",
                skill=spec.name,
                error=str(exc),
            )
            continue
        if plan is None:
            continue
        matched.append((plan.priority, plan.name, plan))

    if not matched:
        return ctx

    # Highest priority wins; ties broken by name for determinism.
    matched.sort(key=lambda item: (-item[0], item[1]))
    chosen_plan = matched[0][2]

    match = MetaMatch(
        plan=chosen_plan,  # type: ignore[arg-type]
        inputs={"user_message": ctx.message},
    )
    ctx.metadata["meta_match"] = match
    log.info(
        "meta_resolution.matched",
        meta_skill=getattr(chosen_plan, "name", ""),
        candidates=len(matched),
        # Include the head of the actual input so an operator can
        # diagnose accidental fires from the log alone.
        message_head=(ctx.message or "")[:200],
    )
    return ctx
