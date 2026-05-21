"""Internal tools for meta-skill-creator."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import ValidationError

from opensquilla.engine.steps.meta_resolution import _trigger_matches
from opensquilla.skills.creator.patterns import PATTERN_SLOT_SCHEMA
from opensquilla.skills.loader import SkillLoader
from opensquilla.tools.registry import tool

_TEMPLATES_DIR = Path(__file__).resolve().parent / "patterns"


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def meta_skill_assemble(pattern_id: str, slots_json: str) -> str:
    """Render SKILL.md from validated slots."""
    if pattern_id not in PATTERN_SLOT_SCHEMA:
        raise ValueError(f"unknown pattern_id: {pattern_id}")
    schema = PATTERN_SLOT_SCHEMA[pattern_id]
    try:
        slots_dict = json.loads(slots_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"slots_json not valid JSON: {exc}") from exc
    try:
        slots = schema.model_validate(slots_dict)
    except ValidationError as exc:
        raise ValueError(f"slots failed schema {pattern_id}: {exc}") from exc

    env = _jinja_env()
    template_name = f"{pattern_id}.md.j2"
    rendered = env.get_template(template_name).render(**slots.model_dump())
    return rendered


def _call_llm_for_slots(prompt: str, **kwargs: Any) -> str:
    """Production LLM call for slot filling. Builds a provider from environment
    variables and calls make_llm_chat_from_provider.

    Tests monkeypatch this symbol to inject deterministic stubs.
    """
    import asyncio
    import os

    from opensquilla.engine.types import AgentConfig
    from opensquilla.provider.selector import build_provider
    from opensquilla.skills.meta.orchestrator import make_llm_chat_from_provider

    # Resolve provider + API key from environment (mirrors gateway behaviour).
    # Preference order: openrouter → anthropic → openai
    if os.environ.get("OPENROUTER_API_KEY"):
        provider_name = "openrouter"
        api_key = os.environ["OPENROUTER_API_KEY"]
        model = kwargs.get("model", "anthropic/claude-3.5-haiku")
    elif os.environ.get("ANTHROPIC_API_KEY"):
        provider_name = "anthropic"
        api_key = os.environ["ANTHROPIC_API_KEY"]
        model = kwargs.get("model", "claude-3-5-haiku-20241022")
    elif os.environ.get("OPENAI_API_KEY"):
        provider_name = "openai"
        api_key = os.environ["OPENAI_API_KEY"]
        model = kwargs.get("model", "gpt-4o-mini")
    else:
        raise RuntimeError(
            "meta-skill-creator: no LLM provider configured. "
            "Set OPENROUTER_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY."
        )

    provider = build_provider(provider=provider_name, model=model, api_key=api_key)
    base_config = AgentConfig(model_id=model)
    llm_chat = make_llm_chat_from_provider(
        provider=provider, base_config=base_config, max_tokens=2048
    )

    async def _drive() -> str:
        return await llm_chat("", prompt)

    return asyncio.run(_drive())


def _build_catalog_summary() -> str:
    """Enumerate available bundled skills (name + 1-line description)."""
    bundled = Path(__file__).resolve().parents[1] / "bundled"
    loader = SkillLoader(
        bundled_dir=bundled,
        snapshot_path=Path(tempfile.gettempdir()) / "creator-catalog-snap.json",
    )
    loader.invalidate_cache()
    lines: list[str] = []
    for spec in loader.load_all():
        first_line = (spec.description or "").split("\n", 1)[0][:120]
        lines.append(f"- {spec.name}: {first_line}")
    return "\n".join(lines)


def meta_skill_fill_slots(
    pattern_id: str, history_summary: str, user_intent: str,
) -> str:
    """Drive LLM to fill pattern slots; Pydantic-validate; retry once on
    ValidationError. Returns validated JSON string."""
    if pattern_id not in PATTERN_SLOT_SCHEMA:
        raise ValueError(f"unknown pattern_id: {pattern_id}")
    schema = PATTERN_SLOT_SCHEMA[pattern_id]
    catalog = _build_catalog_summary()

    base_prompt = (
        f"Fill the {pattern_id} slot schema.\n\n"
        f"Available skills (catalog):\n{catalog}\n\n"
        f"History summary:\n{history_summary}\n\n"
        f"User intent: {user_intent}\n\n"
        f"Emit ONLY a JSON object matching the {pattern_id} schema. No prose."
    )

    response = _call_llm_for_slots(base_prompt)
    try:
        validated = schema.model_validate_json(response)
        return str(validated.model_dump_json())
    except ValidationError as exc:
        # N4 fix: Pydantic v2 custom-validator errors embed raw ValueError
        # objects in ctx.error, which are not JSON-serializable. Use
        # default=str to coerce them so json.dumps() doesn't TypeError before
        # the retry LLM call fires.
        retry_prompt = (
            base_prompt
            + "\n\nYour previous response failed schema validation with these errors:\n"
            + json.dumps(exc.errors(), default=str)
            + "\n\nEmit a corrected JSON object."
        )
        retry_response = _call_llm_for_slots(retry_prompt)
        validated = schema.model_validate_json(retry_response)
        return str(validated.model_dump_json())


def simulate_meta_resolution(
    skill_md: str, prompt: str, classifier_model: str,
) -> bool:
    """Load skill_md into a tmp SkillLoader, run trigger matching against
    `prompt`, return True if the candidate skill matches.

    For Phase 1, classifier_model is informational only; matching uses the
    same word-boundary regex used by `engine.steps.meta_resolution` (which
    is itself a deterministic substring/word-boundary check, no LLM)."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "candidate"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        loader = SkillLoader(
            bundled_dir=Path(tmp),
            snapshot_path=Path(tmp) / "snap.json",
        )
        loader.invalidate_cache()
        specs = loader.load_all()
        if not specs:
            return False
        spec = specs[0]
        # IMPORTANT: _trigger_matches requires pre-lowered second arg
        # (meta_resolution.py:32). Pre-lower once here.
        prompt_lower = prompt.lower()
        return any(_trigger_matches(trig, prompt_lower) for trig in spec.triggers)


def run_smoke_gates(
    skill_md: str,
    *,
    fixture_gen_fn: Callable[..., str],
    classifier_model: str,
) -> dict[str, object]:
    """Run G3 (positive smoke) + G4 (negative smoke).

    `fixture_gen_fn(skill_md, kind, ...)` returns a generated prompt string
    for kind in {"positive", "negative"}. Cross-vendor pinning: caller is
    expected to inject a fixture_gen_fn that uses a DIFFERENT model family
    than `classifier_model` to break LLM-self-confirmation bias.
    """
    positive = fixture_gen_fn(skill_md, "positive")
    g3_matched = simulate_meta_resolution(skill_md, positive, classifier_model)

    negative = fixture_gen_fn(skill_md, "negative")
    g4_matched = simulate_meta_resolution(skill_md, negative, classifier_model)

    degraded = (
        classifier_model == "stub"
        or fixture_gen_fn is _deterministic_fixture
    )

    return {
        "G3": {
            "passed": g3_matched,
            "positive_fixture": positive,
            "classifier": classifier_model,
            "degraded": degraded,
        },
        "G4": {
            "passed": not g4_matched,
            "negative_fixture": negative,
            "classifier": classifier_model,
            "degraded": degraded,
        },
        "degraded": degraded,
    }


def real_fixture_gen(
    skill_md: str,
    kind: str,
    *,
    llm_chat,
    fixture_gen_model: str,
) -> str:
    """LLM-driven fixture gen for cross-vendor smoke (Step 2 of meta-skill-smoke-test's SKILL.md).

    Phase 1 fallback to deterministic when llm_chat is None. Real LLM wiring
    deferred to follow-on iteration.

    Caller must supply an llm_chat bound to fixture_gen_model that is DIFFERENT
    from the classifier_model to break LLM-self-confirmation bias.
    """
    if llm_chat is None:
        return _deterministic_fixture(skill_md, kind)
    raise NotImplementedError(
        "real LLM fixture-gen is wired in Step 3.14 with cross-vendor pinning"
    )


def _deterministic_fixture(skill_md: str, kind: str) -> str:
    """Trigger-string based fixture generator for offline tests.

    Tries double-quoted triggers first (the predominant YAML style in this
    codebase's bundled meta-skills), then unquoted bare triggers. Returns
    the hardcoded fallback only when neither matches.
    """
    import re
    if kind == "positive":
        # Double-quoted: triggers: \n  - "phrase"
        m = re.search(r"triggers:\s*\n((?:\s*-\s*\"[^\"]+\"\s*\n)+)", skill_md)
        if m:
            first = re.search(r'-\s*"([^"]+)"', m.group(1))
            if first:
                return f"please use {first.group(1)}"
        # Unquoted: triggers: \n  - phrase
        m = re.search(r"triggers:\s*\n((?:\s*-\s*[^\"\n]+\n)+)", skill_md)
        if m:
            first = re.search(r"-\s*([^\"\n]+)", m.group(1))
            if first:
                return f"please use {first.group(1).strip()}"
        return "please run this meta-skill"
    # Cross-domain negative fixture: any prompt unrelated to common bundled
    # skills. Weather is a safe choice because the corpus's weather bundle
    # uses tight triggers ("weather", "天气") that won't be matched by this
    # free-form phrasing. If a future user-authored meta-skill is itself
    # about weather, this fixture will false-fail G4 — flag at that time.
    if kind == "negative":
        return "what's the weather forecast for tomorrow?"
    raise ValueError(f"Unknown fixture kind: {kind}")


# ---------------------------------------------------------------------------
# @tool-decorated async wrappers — registered into the default ToolRegistry
# at import time so that the orchestrator's tool_invoker can dispatch them.
# ---------------------------------------------------------------------------

_PATTERN_ENUM = sorted(PATTERN_SLOT_SCHEMA.keys())


@tool(
    name="meta_skill_assemble",
    description=(
        "Render a meta-skill SKILL.md from a pattern_id + Pydantic-validated "
        "slots JSON. Returns the full SKILL.md text as a string."
    ),
    params={
        "pattern_id": {"type": "string", "enum": _PATTERN_ENUM},
        "slots_json": {"type": "string"},
    },
    required=["pattern_id", "slots_json"],
    exposed_by_default=False,  # internal orchestrator dispatch only
)
async def meta_skill_assemble_tool(pattern_id: str, slots_json: str) -> str:
    return meta_skill_assemble(pattern_id, slots_json)


@tool(
    name="meta_skill_fill_slots",
    description=(
        "Drive an LLM to fill the slot schema for the chosen pattern. "
        "Returns validated JSON string consumed by meta_skill_assemble."
    ),
    params={
        "pattern_id": {"type": "string", "enum": _PATTERN_ENUM},
        "history_summary": {"type": "string"},
        "user_intent": {"type": "string"},
    },
    required=["pattern_id", "history_summary", "user_intent"],
    exposed_by_default=False,  # internal orchestrator dispatch only
)
async def meta_skill_fill_slots_tool(
    pattern_id: str, history_summary: str, user_intent: str,
) -> str:
    # Run the sync core in a worker thread to avoid nested event loop conflict
    # when invoked from inside the orchestrator's running event loop.
    # The sync core uses asyncio.run() internally to call the LLM provider.
    import asyncio
    return await asyncio.to_thread(
        meta_skill_fill_slots, pattern_id, history_summary, user_intent,
    )
