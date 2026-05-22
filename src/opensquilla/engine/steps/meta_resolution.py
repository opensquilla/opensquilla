"""Pipeline step: detect Meta-Skill trigger matches and emit a soft hint.

Behaviour (post-hard-takeover-removal)
--------------------------------------
* Scans the loaded skills for entries with ``kind == "meta"``.
* Matches the current user message (case-insensitive substring for CJK,
  word-boundary regex for ASCII) against each meta-skill's ``triggers``.
* If at least one matches, the highest ``meta_priority`` wins; a
  :class:`MetaMatch` is written to ``ctx.metadata['meta_match']`` for
  downstream observability (decision log card, persistence, audit) and a
  short hint string is appended to ``ctx.system_prompt`` telling the LLM
  *"this looks like meta-skill X; call meta_invoke(name=X) if that's the
  intent"*.
* **The LLM decides** whether to call ``meta_invoke``. The runtime no
  longer routes meta-matched turns through ``MetaOrchestrator`` directly;
  there is exactly one execution path now (the soft / LLM-driven path),
  which eliminates the silent hard-takeover failure modes (false trigger
  fires, ``meta_invoke`` "never seen", filter short-circuit, etc.).
* Any parse error on a meta-skill is logged and skipped — the rest of the
  turn falls back to normal handling (fail-open).
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


def _first_matching_trigger(triggers: list[str], message_lower: str) -> str:
    """Return the trigger phrase that fired, for the hint text."""
    for t in triggers:
        if isinstance(t, str) and t and _trigger_matches(t, message_lower):
            return t
    return ""  # unreachable when caller already verified ``any(...)``


def _build_hint(skill_name: str, trigger_phrase: str) -> str:
    """Render the soft-hint suffix appended to ``system_prompt``.

    The phrasing is deliberately balanced: it nudges the model toward
    ``meta_invoke`` *only when intent matches*, and explicitly allows
    declining when the trigger word appears in an off-topic context
    (e.g. "my **travel plan** got cancelled" should NOT auto-run the
    travel-planner DAG just because "travel plan" was uttered).
    """
    return (
        "\n\n## Meta-skill trigger hint\n"
        f'The user message contains the phrase "{trigger_phrase}", which is a '
        f'registered trigger for the meta-skill `{skill_name}`. If running '
        f'that workflow end-to-end matches the user\'s intent, call '
        f'`meta_invoke(name="{skill_name}")`; the framework will drive the '
        f'multi-step DAG and the deliverable becomes the assistant reply. '
        f'If the user is asking *about* the meta-skill, querying status, or '
        f'their request is only tangentially related to the trigger phrase, '
        f'ignore this hint and answer normally.'
    )


async def meta_resolution(ctx: TurnContext) -> TurnContext:
    """Resolve a Meta-Skill trigger, stash a MetaMatch, and inject a soft hint."""

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

    matched: list[tuple[int, str, object, str]] = []
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
        trigger_phrase = _first_matching_trigger(triggers, message_lower)
        matched.append((plan.priority, plan.name, plan, trigger_phrase))

    if not matched:
        return ctx

    # Highest priority wins; ties broken by name for determinism.
    matched.sort(key=lambda item: (-item[0], item[1]))
    chosen_plan = matched[0][2]
    chosen_trigger = matched[0][3]

    match = MetaMatch(
        plan=chosen_plan,  # type: ignore[arg-type]
        inputs={"user_message": ctx.message},
    )
    ctx.metadata["meta_match"] = match
    ctx.metadata["meta_match_trigger"] = chosen_trigger

    # ── Soft-hint injection ────────────────────────────────────────────
    # Append to the uncached suffix slot of system_prompt so cache
    # breakpoints upstream stay stable across turns. Both str and tuple
    # shapes are handled the same way as in skills_filter.py. Skipped
    # silently when ctx has no system_prompt attribute (some unit tests
    # construct ctx as a bare SimpleNamespace).
    skill_name = getattr(chosen_plan, "name", "")
    sp = getattr(ctx, "system_prompt", None)
    if skill_name and chosen_trigger and sp is not None:
        hint = _build_hint(skill_name, chosen_trigger)
        if isinstance(sp, str):
            base, suffix = sp, ""
        else:
            base, suffix = sp
        new_suffix = f"{suffix}{hint}" if suffix else hint
        ctx.system_prompt = (base, new_suffix)

    log.info(
        "meta_resolution.matched",
        meta_skill=skill_name,
        trigger=chosen_trigger,
        candidates=len(matched),
        # Include the head of the actual input so an operator can
        # diagnose accidental fires from the log alone.
        message_head=(ctx.message or "")[:200],
    )
    return ctx
