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
* Trigger matches still use the soft ``meta_invoke`` path rather than
  directly calling ``MetaOrchestrator``, but the first provider request is
  forced to choose ``meta_invoke``. This keeps execution observable through
  the normal tool path while preventing routed models from bypassing the
  meta DAG with ordinary tools after a deterministic trigger match.
* Semantic-only matches remain advisory: they inject the hint and leave tool
  choice automatic so retrieval false positives do not hard-start a DAG.
* Any parse error on a meta-skill is logged and skipped — the rest of the
  turn falls back to normal handling (fail-open).
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from typing import Any

import structlog

from opensquilla.engine.pipeline import TurnContext
from opensquilla.skills.meta.clarify_nl_extract import extract as _nl_extract
from opensquilla.skills.meta.clarify_text import parse_clarify_reply
from opensquilla.skills.meta.inputs import make_meta_inputs
from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch
from opensquilla.skills.retrieval import HybridRetriever

log = structlog.get_logger(__name__)


# ── Session-sticky meta match (continuation across multi-turn chats) ──
#
# Hard problem the trigger-only matcher could not solve: once T1 of a
# chat hits a meta-skill trigger (e.g. "帮我写篇论文"), the LLM might
# fail to actually emit ``meta_invoke`` on that turn — for example
# deepseek-v4-flash can length-cap on reasoning before producing the
# forced tool call. Then T2 carries follow-up details ("我想写 RAG…")
# which does not contain the trigger phrase, so the matcher returns
# nothing, ``meta_invoke`` falls out of the tool surface, and the LLM
# tries ``read_file`` / ``glob_search`` instead.
#
# This module-level cache keeps the chosen ``(skill_name, trigger)``
# alive for a small number of follow-up turns. It is in-memory only
# (lost on gateway restart, which is fine — restart is rare and an
# unstuck T1 will re-trigger naturally). The cache is bounded by:
# * ``_STICKY_TTL_SECONDS`` — wall-clock window
# * ``_STICKY_MAX_USES`` — max follow-up turns where a sticky hit re-arms
#   the match before we give up
#
# Eviction triggers:
# * TTL expires → entry dropped on next access
# * Uses exhausted → entry dropped on next access
# * User message contains a sticky-cancel keyword → entry dropped now
# * The awaiting branch fires (proper continuation took over) → entry
#   dropped because we never reach the trigger/sticky code path
_STICKY_TTL_SECONDS = 1800.0
_STICKY_MAX_USES = 3
_STICKY_CANCEL_KEYWORDS = (
    "取消", "算了", "别写了", "不写了", "停止",
    "cancel", "stop", "nevermind", "never mind", "forget it",
)
_sticky_lock = threading.Lock()
_meta_sticky_cache: dict[str, dict[str, Any]] = {}


def _sticky_get(session_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    now = time.time()
    with _sticky_lock:
        entry = _meta_sticky_cache.get(session_id)
        if entry is None:
            return None
        if now - entry["ts"] > _STICKY_TTL_SECONDS or entry["uses"] <= 0:
            _meta_sticky_cache.pop(session_id, None)
            return None
        return dict(entry)


def _sticky_put(session_id: str, skill: str, trigger: str) -> None:
    if not session_id or not skill:
        return
    with _sticky_lock:
        _meta_sticky_cache[session_id] = {
            "ts": time.time(),
            "uses": _STICKY_MAX_USES,
            "skill": skill,
            "trigger": trigger,
        }


def _sticky_consume(session_id: str) -> None:
    """Decrement uses on a sticky hit; drop entry when exhausted."""
    if not session_id:
        return
    with _sticky_lock:
        entry = _meta_sticky_cache.get(session_id)
        if entry is None:
            return
        entry["uses"] -= 1
        if entry["uses"] <= 0:
            _meta_sticky_cache.pop(session_id, None)


def _sticky_drop(session_id: str) -> None:
    if not session_id:
        return
    with _sticky_lock:
        _meta_sticky_cache.pop(session_id, None)


def _clamp_thinking_for_meta(ctx: TurnContext) -> None:
    """Force ``thinking_level=low`` on a meta-matched turn.

    Even with ``meta_match_tool_choice`` forcing ``meta_invoke``, some
    models (notably deepseek-v4-flash) burn the entire output budget on
    reasoning before producing the tool call. The structured argument
    list for ``meta_invoke`` does not need deep reasoning, so we clamp
    to low here. Recorded in ``thinking_source`` so the next pipeline
    step can see who set it last.
    """
    ctx.metadata["thinking_level"] = "low"
    ctx.metadata["thinking_requested"] = True
    ctx.metadata["thinking_source"] = "meta_resolution"


def _hits_cancel_keywords(message: str, keywords: tuple[str, ...]) -> bool:
    if not keywords:
        return False
    lower = (message or "").lower()
    for kw in keywords:
        if kw and kw in lower:
            return True
    return False


def _chat_pending_fields(schema, awaiting):
    """Return tuple of fields not yet in awaiting_filled_json (chat mode).

    The nl_extract whitelist is the SINGLE currently-asked field in chat
    mode so the LLM cannot accidentally fill out later fields the user
    has not been prompted for yet.
    """
    import json as _json
    try:
        filled = _json.loads(awaiting.awaiting_filled_json or "{}")
    except Exception:  # noqa: BLE001
        filled = {}
    for field in schema.fields:
        if field.name not in filled:
            return (field,)
    return tuple(schema.fields)  # all filled — defensive (shouldn't reach here)


def _deserialize_awaiting_schema(schema_json: str):
    """Re-create a ClarifyStepConfig from the awaiting_schema_json column."""
    import json as _json  # noqa: PLC0415

    from opensquilla.skills.meta.plan_serde import clarify_config_from_jsonable  # noqa: PLC0415

    try:
        raw = _json.loads(schema_json or "{}")
    except Exception:  # noqa: BLE001
        return clarify_config_from_jsonable({"mode": "form", "fields": []})
    return clarify_config_from_jsonable(raw)


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


_SEMANTIC_WORKFLOW_CUES = (
    "pdf",
    "document",
    "doc",
    "report",
    "research",
    "summarize",
    "summary",
    "analyze",
    "analysis",
    "review",
    "migration",
    "migrate",
    "upgrade",
    "travel",
    "trip",
    "itinerary",
    "skill",
    "workflow",
    "文件",
    "文档",
    "报告",
    "调研",
    "研究",
    "总结",
    "分析",
    "看看",
    "看一下",
    "读一下",
    "迁移",
    "升级",
    "旅行",
    "行程",
    "技能",
    "流程",
)


def _has_semantic_workflow_cue(query: str) -> bool:
    """Keep semantic fallback from turning every utterance into a meta hint."""

    text = query.lower().strip()
    if not text:
        return False
    if re.search(r"\.(pdf|docx?|md|txt|csv|json)\b", text):
        return True
    return any(cue in text for cue in _SEMANTIC_WORKFLOW_CUES)


def _semantic_meta_candidate(
    ctx: TurnContext,
    candidates: list[tuple[int, str, object, object]],
) -> tuple[int, str, object, str] | None:
    """Return the best meta-skill candidate from retrieval, if any.

    Trigger matching is the high-precision path. This fallback keeps the
    product behavior soft: retrieval only chooses which meta-skill to hint;
    the outer LLM still decides whether invoking the DAG fits the user intent.
    """

    if not candidates:
        return None
    query = (
        getattr(ctx, "semantic_message", None)
        or getattr(ctx, "raw_message", None)
        or getattr(ctx, "message", "")
        or ""
    )
    if not str(query).strip():
        return None
    if not _has_semantic_workflow_cue(str(query)):
        return None

    retriever = HybridRetriever(strategy="hybrid")
    specs = [spec for _priority, _name, _plan, spec in candidates]
    try:
        ranked = retriever.retrieve(specs, str(query), top_k=1)
    except Exception as exc:  # noqa: BLE001 - fail open; triggers still work.
        log.warning("meta_resolution.semantic_match_failed", error=str(exc))
        return None
    if not ranked:
        return None
    chosen_name = getattr(ranked[0], "name", "")
    for priority, name, plan, _spec in candidates:
        if name == chosen_name:
            return (priority, name, plan, "semantic")
    return None


def _build_hint(
    skill_name: str,
    trigger_phrase: str,
    candidates: list[tuple[int, str, str]] | None = None,
    activation_mode: str = "recommend",
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
    mode = "hint" if activation_mode == "hint" else "recommend"
    if mode == "hint":
        lead = (
            f"The user message is semantically similar to the meta-skill "
            f"`{skill_name}`. Treat this as a candidate, not a command."
        )
        action = (
            f"First decide whether the user is asking for the end-to-end "
            f"meta-skill deliverable. If yes, call "
            f"`meta_invoke(name=\"{skill_name}\")` as the first action; the "
            f"framework will drive the DAG and the deliverable becomes the "
            f"assistant reply. Do not emit explanatory text before calling "
            f"`meta_invoke`. Do not answer directly in that case. Do not call "
            f"ordinary tools before `meta_invoke`; the meta-skill will call "
            f"its own sub-skills internally. If a direct answer is more "
            f"appropriate because the user is only asking a quick question or "
            f"asking about the meta-skill itself, ignore this candidate and "
            f"answer normally."
        )
    else:
        if trigger_phrase == "semantic":
            evidence = (
                f"The previous turn selected `{skill_name}` by semantic "
                "similarity and this turn is a sticky continuation."
            )
        else:
            evidence = (
                f'The user message contains the phrase "{trigger_phrase}", '
                f"which is a registered trigger for the meta-skill `{skill_name}`."
            )
        lead = evidence
        action = (
            f"For a concrete deliverable request that matches this meta-skill, "
            f"call `meta_invoke(name=\"{skill_name}\")` as the next action. "
            f"Concrete deliverable "
            f"requests include asking for an audit, review, decision brief, "
            f"plan, comparison, extraction, report, rollback plan, or other "
            f"multi-step work product. Do not emit explanatory text before "
            f"calling `meta_invoke`. Do not answer directly or call ordinary "
            f"tools such as web/search/http/file tools before `meta_invoke` "
            f"in that case; the meta-skill DAG will call any required "
            f"sub-skills internally and its deliverable becomes the assistant "
            f"reply."
        )
    lines = [
        "\n\n## Meta-skill activation guidance",
        f"Activation mode: {mode}",
        lead,
        action,
        "Do not call `skill_view` for this meta-skill; `skill_view` is for "
        "ordinary skills, while this meta-skill should be started with "
        "`meta_invoke` directly.",
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
        "this hint and answer normally. Otherwise, for matched multi-step "
        "deliverable requests, prefer starting the matched meta-skill over "
        "manually reproducing its steps with ordinary tools. You can also call "
        "`meta_invoke` for any other meta-skill listed in `<available_skills>` "
        "whose description fits the request — the substring trigger above is "
        "a hint, not a constraint."
    )
    return "\n".join(lines)


async def meta_resolution(ctx: TurnContext) -> TurnContext:
    """Resolve a Meta-Skill trigger, stash a MetaMatch, and inject a soft hint."""

    from opensquilla.skills.meta.enabled import is_meta_skill_enabled

    if not is_meta_skill_enabled(getattr(ctx, "config", None)):
        return ctx

    writer = ctx.metadata.get("meta_run_writer")
    # TurnContext field is `session_key`; DAO interface alias is `session_id`.
    session_id = getattr(ctx, "session_key", "") or ""

    # ── Leading awaiting branch (PR3, design §8.2) ─────────────────
    if writer is not None and session_id:
        try:
            awaiting = writer.peek_awaiting(session_id=session_id)
        except Exception as exc:  # noqa: BLE001 — fail-open
            log.warning("meta_resolution.peek_awaiting_failed", error=str(exc))
            awaiting = None

        if awaiting is not None:
            schema = _deserialize_awaiting_schema(awaiting.awaiting_schema_json)
            now = time.time()

            if now - awaiting.awaiting_since > schema.timeout_hours * 3600:
                writer.mark_expired(run_id=awaiting.run_id)
                ctx.metadata["meta_clarify_expired"] = awaiting
                return ctx

            if _hits_cancel_keywords(ctx.message, schema.cancel_keywords):
                writer.mark_cancelled(
                    run_id=awaiting.run_id, reason="user_cancel",
                )
                ctx.metadata["meta_clarify_cancelled"] = awaiting
                ctx.metadata["meta_clarify_cancel_reason"] = "user_cancel"
                return ctx

            parsed, errors = parse_clarify_reply(
                ctx.message, schema,
                surface=getattr(ctx, "surface_kind", "unknown"),
            )
            if errors and schema.nl_extract:
                # PR9: opt-in LLM fallback. Run ONLY when the
                # deterministic parser failed. Validators are reapplied
                # inside extract() so prompt-injection in user_message
                # cannot bypass type/range/choice constraints.
                nl_chat = ctx.metadata.get("meta_llm_chat")
                if nl_chat is not None:
                    active = (
                        _chat_pending_fields(schema, awaiting)
                        if schema.mode == "chat"
                        else schema.fields
                    )
                    try:
                        nl_result = await _nl_extract(
                            reply_text=ctx.message,
                            schema=schema,
                            active_fields=active,
                            llm_chat=nl_chat,
                            tier=schema.nl_extract_tier,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "meta_resolution.nl_extract_failed",
                            error=str(exc),
                        )
                    else:
                        if not nl_result.errors and nl_result.fields:
                            parsed, errors = nl_result.fields, []
            if errors:
                failure_count = writer.increment_parse_failures(
                    run_id=awaiting.run_id,
                )
                if failure_count >= 3:
                    writer.mark_cancelled(
                        run_id=awaiting.run_id, reason="parse_failure_limit",
                    )
                    ctx.metadata["meta_clarify_cancelled"] = awaiting
                    ctx.metadata["meta_clarify_cancel_reason"] = (
                        "parse_failure_limit"
                    )
                    return ctx
                ctx.metadata["meta_clarify_errors"] = errors
                ctx.metadata["meta_clarify_reprompt"] = awaiting
                return ctx

            # Parse-success path: the resume CAS belongs before DAG reentry.
            claim = await asyncio.to_thread(
                writer.try_claim_resume,
                run_id=awaiting.run_id,
                session_id=session_id,
            )
            if claim is None:
                ctx.metadata["meta_clarify_race_lost"] = awaiting.run_id
                return ctx
            ctx.metadata["meta_resume"] = (claim, parsed)
            # Proper continuation (awaiting → resume) took over. Drop any
            # stale sticky entry — the DAG is now driving and the trigger
            # path should be inert for the remainder of this run.
            _sticky_drop(session_id)
            return ctx

    # ── Original trigger-matching path (with sticky continuation) ──
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

    # Sticky-cancel: explicit user opt-out always wins over a stale match.
    if _hits_cancel_keywords(ctx.message or "", _STICKY_CANCEL_KEYWORDS):
        _sticky_drop(session_id)

    matched: list[tuple[int, str, object, str]] = []
    semantic_candidates: list[tuple[int, str, object, object]] = []
    for spec in all_skills:
        if getattr(spec, "kind", "skill") != "meta":
            continue
        if getattr(spec, "disable_model_invocation", False):
            continue
        triggers = getattr(spec, "triggers", None) or []
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
        semantic_candidates.append((plan.priority, plan.name, plan, spec))
        if any(
            isinstance(t, str) and t and _trigger_matches(t, message_lower) for t in triggers
        ):
            trigger_phrase = _first_matching_trigger(triggers, message_lower)
            matched.append((plan.priority, plan.name, plan, trigger_phrase))

    sticky_replay = False
    if not matched:
        # No current trigger — try the sticky cache for this session.
        # The contract: a recent prior turn matched a meta-skill but the
        # LLM never managed to actually fire ``meta_invoke`` (e.g. it
        # length-capped on reasoning, the user closed the form and is
        # now retrying with details, etc.). Replay the stored choice
        # for up to ``_STICKY_MAX_USES`` follow-up turns so meta_invoke
        # stays on the toolbox and trigger-originated tool_choice stays forced.
        sticky = _sticky_get(session_id)
        if sticky is None:
            semantic_match = _semantic_meta_candidate(ctx, semantic_candidates)
            if semantic_match is None:
                return ctx
            matched.append(semantic_match)
            ctx.metadata["meta_match_source"] = "semantic"
        else:
            for spec in all_skills:
                if (
                    getattr(spec, "kind", "skill") != "meta"
                    or getattr(spec, "name", None) != sticky["skill"]
                ):
                    continue
                try:
                    plan = parse_meta_plan(spec)
                except MetaPlanError:
                    continue
                if plan is None:
                    continue
                matched.append((plan.priority, plan.name, plan, sticky["trigger"]))
                break
            if not matched:
                # Skill no longer present (loader changed) — drop stale entry.
                _sticky_drop(session_id)
                return ctx
            _sticky_consume(session_id)
            sticky_replay = True
    else:
        ctx.metadata["meta_match_source"] = "trigger"

    # Highest priority wins; ties broken by name for determinism.
    matched.sort(key=lambda item: (-item[0], item[1]))
    chosen_plan = matched[0][2]
    chosen_trigger = matched[0][3]

    if not sticky_replay:
        # Fresh trigger match — arm/refresh the sticky cache so the next
        # 1-3 turns can replay this choice if the LLM stalls on the
        # current turn.
        _sticky_put(session_id, str(matched[0][1]), str(chosen_trigger))

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
    activation_mode = "hint" if str(chosen_trigger) == "semantic" else "recommend"
    ctx.metadata["meta_activation_mode"] = activation_mode
    if sticky_replay:
        ctx.metadata["meta_match_sticky"] = True
        ctx.metadata["meta_match_source"] = "sticky"

    if activation_mode == "recommend":
        ctx.metadata["meta_match_tool_choice"] = {
            "type": "function",
            "function": {"name": "meta_invoke"},
        }

    # Clamp reasoning budget so the LLM cannot length-cap on thinking
    # before producing the forced ``meta_invoke`` call. Applies to both
    # fresh matches and sticky replays — the meta-invoke argument shape
    # never needs deep reasoning.
    _clamp_thinking_for_meta(ctx)

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
        hint = _build_hint(
            skill_name,
            chosen_trigger,
            candidate_digest,
            activation_mode=activation_mode,
        )
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
        activation_mode=activation_mode,
        candidates=len(matched),
        sticky_replay=sticky_replay,
        # D1: log all candidate names + priorities so operators can
        # spot trigger overlaps from logs without re-running the turn.
        candidate_list=[(n, p) for p, n, _t in candidate_digest],
        # Include the head of the actual input so an operator can
        # diagnose accidental fires from the log alone.
        message_head=(ctx.message or "")[:200],
    )
    return ctx
