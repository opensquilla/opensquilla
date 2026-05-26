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
from opensquilla.skills.meta.inputs import make_meta_inputs
from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch

log = structlog.get_logger(__name__)

_META_SKILL_EXPLANATION_RE = re.compile(
    r"\b(how|what|why|explain|describe)\b.*\bmeta-skill\b"
)


def _tier_sort_key(name: str, index: int) -> tuple[int, int]:
    """Prefer numeric router tiers (t0 < t1 < t2 < t3), then declaration order."""

    match = re.fullmatch(r"t(\d+)", name.strip().lower())
    if match:
        return (int(match.group(1)), index)
    return (-1, index)


def _highest_text_tier(ctx: TurnContext) -> tuple[str, str] | None:
    """Return ``(tier_name, model)`` for the highest configured text tier."""

    router_cfg = getattr(getattr(ctx, "config", None), "squilla_router", None)
    tiers = getattr(router_cfg, "tiers", None)
    if not isinstance(tiers, dict) or not tiers:
        return None

    candidates: list[tuple[tuple[int, int], str, str]] = []
    for index, (name, tier_cfg) in enumerate(tiers.items()):
        if not isinstance(tier_cfg, dict):
            continue
        if bool(tier_cfg.get("image_only", False)):
            continue
        model = str(tier_cfg.get("model") or "").strip()
        tier_name = str(name).strip()
        if tier_name and model:
            candidates.append((_tier_sort_key(tier_name, index), tier_name, model))
    if not candidates:
        return None
    _key, tier_name, model = max(candidates, key=lambda item: item[0])
    return tier_name, model


def _trigger_matches(trigger: str, message_lower: str) -> bool:
    """Match a trigger phrase against the user message.

    * Pure-ASCII triggers (English) require word boundaries — so the
      trigger "research report" does NOT fire on
      "How does the *research report* meta-skill work?" because the
      phrase is embedded in a larger sentence about the skill itself.
    * Triggers containing CJK characters fall back to substring match
      since Chinese phrases have no word boundaries in the regex sense
      and are typically distinctive enough (for example, compliance-audit
      phrases in CJK languages) that
      substring matching does not produce ambiguous fires.
    """
    tl = trigger.lower()
    if tl not in message_lower:
        return False
    if all(ord(c) < 128 for c in tl):
        if _META_SKILL_EXPLANATION_RE.search(message_lower):
            return False
        return bool(re.search(r"\b" + re.escape(tl) + r"\b", message_lower))
    return True


def _first_matching_trigger(triggers: list[str], message_lower: str) -> str:
    """Return the trigger phrase that fired, for the hint text."""
    for t in triggers:
        if isinstance(t, str) and t and _trigger_matches(t, message_lower):
            return t
    return ""  # unreachable when caller already verified ``any(...)``


def _build_hint(
    skill_name: str,
    trigger_phrase: str,
    candidates: list[tuple[int, str, str]] | None = None,
) -> str:
    """Render the soft-hint suffix appended to ``system_prompt``.

    The phrasing is deliberately balanced: it nudges the model toward
    ``meta_invoke`` *only when intent matches*, and explicitly allows
    declining when the trigger word appears in an off-topic context
    (e.g. "my **travel plan** got cancelled" should NOT auto-run the
    travel-planner DAG just because "travel plan" was uttered).

    When more than one meta-skill matched the user's message (D1 + D2),
    the hint also surfaces the runner-up candidates so the LLM can pick
    a better match than the priority-winner. The phrasing tells the LLM
    it is free to pick any skill from ``<available_skills>`` if none
    of the candidates fits (D4) — the substring matcher is not the
    final arbiter of intent.
    """
    lines = [
        "\n\n## Meta-skill trigger hint",
        f'The user message contains the phrase "{trigger_phrase}", which is a '
        f'registered trigger for the meta-skill `{skill_name}`. If running '
        f'that workflow end-to-end matches the user\'s intent, call '
        f'`meta_invoke(name="{skill_name}")`; the framework will drive the '
        f'multi-step DAG and the deliverable becomes the assistant reply.',
    ]
    if candidates and len(candidates) > 1:
        lines.append("")
        lines.append(
            "Other candidates also matched (in priority order, winner first):"
        )
        for prio, name, phrase in candidates:
            marker = " ← chosen" if name == skill_name else ""
            lines.append(f"  • `{name}` (priority {prio}, trigger {phrase!r}){marker}")
        lines.append(
            "If one of the runner-ups fits the user's intent better, call "
            "`meta_invoke(name=\"<runner-up name>\")` instead of the chosen one."
        )
    lines.append("")
    lines.append(
        "If the user is asking *about* a meta-skill, querying status, or their "
        "request is only tangentially related to the trigger phrase, ignore "
        "this hint and answer normally. You can also call `meta_invoke` for "
        "any other meta-skill listed in `<available_skills>` whose description "
        "fits the request — the substring trigger above is a hint, not a "
        "constraint."
    )
    return "\n".join(lines)


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

    # Candidate digest for the hint (priority, name, trigger). The hint
    # surfaces this so the LLM sees runner-ups, not just the
    # priority-winner — important when two meta-skills' triggers
    # overlap and the substring matcher's pick may not be the user's
    # intent (D1 + D2).
    candidate_digest: list[tuple[int, str, str]] = [
        (int(prio), str(name), str(phrase))
        for prio, name, _plan, phrase in matched
    ]

    match = MetaMatch(
        plan=chosen_plan,  # type: ignore[arg-type]
        inputs=make_meta_inputs(
            user_message=ctx.message,
            system_prompt=getattr(ctx, "system_prompt", ""),
        ),
    )
    ctx.metadata["meta_match"] = match
    ctx.metadata["meta_match_trigger"] = chosen_trigger
    ctx.metadata["meta_match_candidates"] = candidate_digest

    if getattr(chosen_plan, "name", "") == "meta-skill-creator":
        highest = _highest_text_tier(ctx)
        if highest is not None:
            tier_name, model = highest
            baseline_model = str(getattr(ctx, "model", "") or "")
            ctx.model = model
            ctx.metadata["meta_required_tier"] = tier_name
            ctx.metadata["meta_required_model"] = model
            ctx.metadata["meta_required_source"] = "meta-skill-creator"
            ctx.metadata.setdefault("baseline_model", baseline_model)
            ctx.metadata["routed_tier"] = tier_name
            ctx.metadata["routed_model"] = model
            ctx.metadata["routing_source"] = "meta_skill_required_tier"
            ctx.metadata["routing_confidence"] = 1.0
            ctx.metadata["routing_applied"] = True
            ctx.metadata["applied_model"] = model

    # ── Soft-hint injection ────────────────────────────────────────────
    # Append to the uncached suffix slot of system_prompt so cache
    # breakpoints upstream stay stable across turns. Both str and tuple
    # shapes are handled the same way as in skills_filter.py. Skipped
    # silently when ctx has no system_prompt attribute (some unit tests
    # construct ctx as a bare SimpleNamespace).
    skill_name = getattr(chosen_plan, "name", "")
    sp = getattr(ctx, "system_prompt", None)
    if skill_name and chosen_trigger and sp is not None:
        hint = _build_hint(skill_name, chosen_trigger, candidate_digest)
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
        # D1: log all candidate names + priorities so operators can
        # spot trigger overlaps from logs without re-running the turn.
        candidate_list=[(n, p) for p, n, _t in candidate_digest],
        # Include the head of the actual input so an operator can
        # diagnose accidental fires from the log alone.
        message_head=(ctx.message or "")[:200],
    )
    return ctx
