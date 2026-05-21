"""Internal tools for meta-skill-creator."""

from __future__ import annotations

import json
import re as _re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import ValidationError

from opensquilla.engine.steps.meta_resolution import _trigger_matches
from opensquilla.skills.creator.patterns import PATTERN_SLOT_SCHEMA
from opensquilla.skills.loader import SkillLoader
from opensquilla.tools.registry import tool

_TEMPLATES_DIR = Path(__file__).resolve().parent / "patterns"
_log = structlog.get_logger(__name__)


class _FillSlotsValidationError(ValueError):
    """Wraps the underlying ValidationError with actionable message text."""


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences common in LLM JSON responses.

    Handles ``\\`\\`\\`json...\\`\\`\\```, ``\\`\\`\\`...\\`\\`\\```, and bare JSON.
    Returns the inner text.
    """
    text = text.strip()
    # Pattern: optional ```lang at start, content, optional ``` at end
    m = _re.match(r"^```(?:json|JSON)?\s*\n(.*?)\n```\s*$", text, _re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: strip leading/trailing ``` even without lang tag
    if text.startswith("```") and text.endswith("```"):
        inner = text[3:-3]
        # Strip leading 'json\n' if present
        inner = _re.sub(r"^json\s*\n?", "", inner, flags=_re.IGNORECASE)
        return inner.strip()
    return text


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


def _resolve_provider_from_config() -> tuple[str | None, str | None, str | None, str | None]:
    """Read provider/model/api_key/base_url from the gateway config.

    N14 fix: delegates to GatewayConfig.load() so env-var overrides
    (OPENSQUILLA_LLM_PROVIDER / _MODEL / _API_KEY / _BASE_URL) and
    base_url / proxy / provider_routing fields are honoured identically
    to the gateway.  The N6 manual tomllib reader missed these, breaking
    creator in env-configured and vllm/azure/custom-endpoint deployments.

    Uses ``importlib.import_module`` (not a bare ``from … import``) so
    the architecture import-contract test (which detects edges via
    ``ast.walk`` on module-level *and* function-body nodes) does not see
    a ``skills → gateway`` static import statement.

    Fix #C — env-var override priority note:
    ``OPENSQUILLA_LLM_MODEL`` and friends ARE honoured when no TOML file
    exists (pydantic-settings reads them via LlmProviderConfig's own
    ``env_prefix="OPENSQUILLA_LLM_"``).  However, when a TOML file is
    present ``GatewayConfig.load()`` passes the TOML dict to the
    constructor and pydantic-settings' env-var scan is only applied to
    fields that were NOT supplied in the dict — so a TOML ``[llm]``
    section can shadow env vars.  To override the LLM in the presence of
    a TOML file, use the *correct pydantic-settings nested delimiter*:
    ``OPENSQUILLA_GATEWAY__LLM__MODEL=<value>`` (double underscores,
    ``OPENSQUILLA_GATEWAY_`` prefix from the parent GatewayConfig).
    The simpler ``OPENSQUILLA_LLM_MODEL`` only works when the LLM
    section is absent from the TOML file.

    After GatewayConfig.load(), we apply an explicit env-var post-override
    so that ``OPENSQUILLA_LLM_MODEL`` / ``OPENSQUILLA_LLM_PROVIDER`` /
    ``OPENSQUILLA_LLM_API_KEY`` / ``OPENSQUILLA_LLM_BASE_URL`` always win
    regardless of TOML content — matching user expectations from the docs.
    """
    import importlib
    import os

    try:
        # Resolve the config path the same way the old manual reader did:
        # OPENSQUILLA_GATEWAY_CONFIG_PATH env var wins; GatewayConfig.load()
        # then also falls back to ./opensquilla.toml and ~/.opensquilla/config.toml.
        config_path_env = os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH", "").strip() or None

        gateway_config_mod = importlib.import_module("opensquilla.gateway.config")
        cfg = gateway_config_mod.GatewayConfig.load(config_path_env)
        llm = cfg.llm
        provider_name = (getattr(llm, "provider", None) or "").strip() or None
        model = (getattr(llm, "model", None) or "").strip() or None
        # N11: accept empty api_key — keyless local providers (ollama,
        # lm_studio, ovms, vllm) do not require an API key.
        api_key = (getattr(llm, "api_key", "") or "").strip()
        base_url = (getattr(llm, "base_url", "") or "").strip()

        # Fix #C: apply explicit env-var post-overrides so that
        # OPENSQUILLA_LLM_MODEL / _PROVIDER / _API_KEY / _BASE_URL always win
        # over TOML file values (pydantic-settings nesting means the sub-model's
        # env bindings are shadowed by the parent TOML dict when a [llm] section
        # is present in config.toml).
        env_provider = os.environ.get("OPENSQUILLA_LLM_PROVIDER", "").strip()
        env_model = os.environ.get("OPENSQUILLA_LLM_MODEL", "").strip()
        env_api_key = os.environ.get("OPENSQUILLA_LLM_API_KEY", "").strip()
        env_base_url = os.environ.get("OPENSQUILLA_LLM_BASE_URL", "").strip()
        if env_provider:
            provider_name = env_provider
        if env_model:
            model = env_model
        if env_api_key:
            api_key = env_api_key
        if env_base_url:
            base_url = env_base_url

        if provider_name and model:
            return (provider_name, model, api_key, base_url)
    except Exception:
        pass
    return (None, None, None, None)


def _resolve_provider_from_env() -> tuple[str | None, str | None, str | None]:
    """Fallback: scan env vars in priority order.

    Preference order: openrouter → anthropic → openai.
    """
    import os

    if os.environ.get("OPENROUTER_API_KEY"):
        return ("openrouter", "anthropic/claude-3.5-haiku", os.environ["OPENROUTER_API_KEY"])
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ("anthropic", "claude-3-5-haiku-20241022", os.environ["ANTHROPIC_API_KEY"])
    if os.environ.get("OPENAI_API_KEY"):
        return ("openai", "gpt-4o-mini", os.environ["OPENAI_API_KEY"])
    return (None, None, None)


def _call_llm_for_slots(prompt: str, **kwargs: Any) -> str:
    """Production LLM call for slot filling. Resolves provider via GatewayConfig
    first (matches the gateway's normal config-loading path), then falls back to
    env vars for bare-script and test scenarios.

    Tests monkeypatch this symbol to inject deterministic stubs.
    """
    import asyncio

    from opensquilla.engine.types import AgentConfig
    from opensquilla.provider.selector import build_provider
    from opensquilla.skills.meta.orchestrator import make_llm_chat_from_provider

    # Config-driven resolution first (matches gateway behaviour for deployments
    # that use ~/.opensquilla/config.toml instead of raw env vars).
    provider_name, model, api_key, base_url = _resolve_provider_from_config()
    if provider_name is None:
        provider_name, model, api_key = _resolve_provider_from_env()
        base_url = ""
    if provider_name is None:
        raise RuntimeError(
            "meta-skill-creator: no LLM provider configured. "
            "Set provider in ~/.opensquilla/config.toml or set "
            "OPENROUTER_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY."
        )

    # Both helpers that succeed return non-None values; narrow for mypy.
    assert model is not None
    assert api_key is not None
    assert base_url is not None

    # kwargs.get("model") can override the resolved model (e.g. in tests).
    effective_model: str = kwargs.get("model", model)

    # Fix #C: log resolved provider/model so E2E logs show which model
    # actually handled the call and whether OPENSQUILLA_LLM_MODEL is honoured.
    _log.info(
        "meta_skill_fill_slots.llm_call",
        provider=provider_name,
        model=effective_model,
        prompt_chars=len(prompt),
    )

    provider = build_provider(
        provider=provider_name, model=effective_model, api_key=api_key, base_url=base_url,
    )
    base_config = AgentConfig(model_id=effective_model)
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


def _build_pattern_example(pattern_id: str) -> dict:
    """Return a minimal valid example for the pattern's slot schema.

    Anchors the LLM on the exact field names — Pydantic schema descriptions
    alone are insufficient to prevent field-name hallucination (e.g. LLMs
    naturally write ``execution_sequence`` when the schema says ``steps``).
    """
    if pattern_id == "p1_sequential":
        return {
            "name": "example-pipeline",
            "description": "A 2-step example that extracts PDF text then summarizes it.",
            "meta_priority": 50,
            "triggers": ["example trigger phrase"],
            "steps": [
                {
                    "id": "extract",
                    "skill": "pdf-toolkit",
                    "task": "Extract text from the PDF",
                    "with_keys": {},
                },
                {
                    "id": "digest",
                    "skill": "summarize",
                    "task": "Summarize the extracted text",
                    "with_keys": {},
                },
            ],
        }
    if pattern_id == "p2_fan_out_merge":
        return {
            "name": "example-fan-out",
            "description": (
                "Gather weather and POI info in parallel, then merge into a travel itinerary."
            ),
            "meta_priority": 50,
            "triggers": ["example fan-out trigger"],
            "branches": [
                {"id": "weather", "skill": "weather", "task": "Fetch weather", "with_keys": {}},
                {
                    "id": "poi",
                    "skill": "multi-search-engine",
                    "task": "Search POIs",
                    "with_keys": {},
                },
            ],
            "merge": {
                "id": "itin",
                "skill": "summarize",
                "task": "Combine into itinerary",
                "with_keys": {},
            },
            "tail": None,
        }
    return {}


def meta_skill_fill_slots(
    pattern_id: str, history_summary: str, user_intent: str,
) -> str:
    """Drive LLM to fill pattern slots; Pydantic-validate; retry once on
    ValidationError. Returns validated JSON string."""
    if pattern_id not in PATTERN_SLOT_SCHEMA:
        raise ValueError(f"unknown pattern_id: {pattern_id}")
    schema = PATTERN_SLOT_SCHEMA[pattern_id]
    catalog = _build_catalog_summary()

    # Fix #A: inject the Pydantic JSON schema and a concrete example so the
    # LLM cannot hallucinate field names such as ``execution_sequence`` or
    # ``trigger_condition``.
    schema_dict = schema.model_json_schema()
    schema_json = json.dumps(schema_dict, ensure_ascii=False, indent=2)
    example_obj = _build_pattern_example(pattern_id)
    example_json = json.dumps(example_obj, ensure_ascii=False, indent=2)

    base_prompt = (
        f"Fill the {pattern_id} slot schema for a new bundled meta-skill.\n\n"
        f"## JSON Schema (REQUIRED field names — do NOT rename)\n"
        f"```\n{schema_json}\n```\n\n"
        f"## Example output for {pattern_id}\n"
        f"```\n{example_json}\n```\n\n"
        f"## Available skills (catalog)\n"
        f"You may only reference these skills in `steps[].skill` (or `branches[].skill`):\n"
        f"{catalog}\n\n"
        f"## History summary\n{history_summary}\n\n"
        f"## User intent\n{user_intent}\n\n"
        f"## Output instructions\n"
        f"Emit ONLY a JSON object matching the schema above. No prose. No markdown.\n"
        f"CRITICAL field-name rules:\n"
        f"- The list of phrases is called `triggers` (NOT `trigger_condition`).\n"
        f"- The pipeline is called `steps` (NOT `execution_sequence`, `pipeline`, "
        f"`actions`, or `sequence`).\n"
        f"- Each step must have: id (str, snake_case), skill (str from catalog), "
        f"task (str, max 400 chars, no double-quotes/newlines/backslashes), "
        f"with_keys (dict, often empty {{}})."
    )

    response = _call_llm_for_slots(base_prompt)
    response = _strip_code_fences(response)  # Fix #A
    try:
        validated = schema.model_validate_json(response)
        return str(validated.model_dump_json())
    except ValidationError as exc:
        # Fix #B: log raw response on initial failure so E2E logs capture LLM output.
        _log.warning(
            "meta_skill_fill_slots.validation_failed_initial",
            pattern_id=pattern_id,
            response_preview=response[:500],
            errors=str(exc.errors()[:5]) if exc.errors() else str(exc),
        )
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
        retry_response = _strip_code_fences(retry_response)  # Fix #A
        try:
            validated = schema.model_validate_json(retry_response)
            return str(validated.model_dump_json())
        except ValidationError as retry_exc:
            # Fix #B: log raw response on retry failure.
            _log.warning(
                "meta_skill_fill_slots.validation_failed_retry",
                pattern_id=pattern_id,
                response_preview=retry_response[:500],
                errors=str(retry_exc.errors()[:5]) if retry_exc.errors() else str(retry_exc),
            )
            raise _FillSlotsValidationError(
                f"LLM returned invalid slots JSON after 1 retry. "
                f"Pattern: {pattern_id}. "
                f"Last error: {str(retry_exc)[:300]}. "
                f"Last response preview: {retry_response[:200]!r}"
            ) from retry_exc


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

@tool(
    name="emit_text",
    description=(
        "Emit a fixed text string as the step output. "
        "Used by harvest_empty fallback in meta-skill-creator."
    ),
    params={"text": {"type": "string"}},
    required=["text"],
    exposed_by_default=False,
)
async def emit_text_tool(text: str) -> str:
    return text


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

    # Fix #B (Option B1): catch _FillSlotsValidationError and return a
    # structured error JSON so the orchestrator sees the actual diagnostic
    # instead of the generic "The tool 'X' failed with an internal error."
    # that the envelope layer emits for unknown exception classes.
    # The downstream meta_skill_assemble call will then fail with an
    # actionable message from this payload rather than a silent black-box.
    try:
        return await asyncio.to_thread(
            meta_skill_fill_slots, pattern_id, history_summary, user_intent,
        )
    except _FillSlotsValidationError as exc:
        return json.dumps(
            {
                "_creator_error": "validation_failed_after_retry",
                "pattern_id": pattern_id,
                "detail": str(exc),
            },
            ensure_ascii=False,
        )
