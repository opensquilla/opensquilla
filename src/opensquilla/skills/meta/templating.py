"""Jinja-templated argument rendering for MetaOrchestrator steps.

Houses the restricted Jinja environment used to render ``with_args`` /
``tool_args`` / ``entrypoint`` templates, the route resolver that picks one
``RouteCase`` per step, and the small text formatters that turn rendered
arguments into the user-message payload of a sub-Agent (or the classifier
prompt body, or the choice coercion at reply time).

These functions are deliberately stateless and free of orchestrator
internals so they can be re-used by future executors (sop_block, policy
attachments) without dragging the scheduler in.
"""

from __future__ import annotations

import html
import re
from decimal import Decimal
from typing import Any

import jinja2
import jinja2.sandbox

from opensquilla.skills.meta.types import MetaStep, RouteCase

# ---------------------------------------------------------------------------
# Restricted Jinja environment for ``with_args`` rendering
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_PATH_TOKEN_RE = re.compile(
    r"(?<![\w.-])"
    r"(?:/[\w./@%+\-=]+|[\w./@%+\-=]+?\."
    r"(?:md|txt|csv|tsv|json|yaml|yml|xlsx))"
    r"(?![\w.-])",
    re.IGNORECASE,
)
_PATH_TRAILING_PUNCT = "`\"'，。；;,)）]】"
_SHORT_DRAMA_SHOT_HEADER_RE = re.compile(
    r"(?m)^=== SHOT_(10|[1-9]) ===[ \t]*$",
)
_SHORT_DRAMA_DURATION_RE = re.compile(
    r"(?m)^DURATION_S:[ \t]*(\d+(?:\.\d+)?)[ \t]*$",
)
_SHORT_DRAMA_DECLARED_SHOTS_RE = re.compile(
    r"(?m)^N_SHOTS:[ \t]*(10|[1-9])[ \t]*$",
)


def _filter_xml_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _filter_truncate(value: object, length: int = 1024) -> str:
    text = str(value)
    if length <= 0 or len(text) <= length:
        return text
    return text[:length]


def _filter_slugify(value: object) -> str:
    return _SLUG_RE.sub("-", str(value)).strip("-").lower()[:128]


def _filter_extract_path(value: object, suffix: str = "") -> str:
    wanted = str(suffix or "").strip().lower().lstrip(".")
    for match in _PATH_TOKEN_RE.findall(str(value)):
        token = match.strip().strip(_PATH_TRAILING_PUNCT)
        if not token:
            continue
        if not wanted or token.lower().endswith(f".{wanted}"):
            return str(token)
    return ""


def _filter_contains_cjk(value: object) -> bool:
    return bool(re.search(r"[\u3400-\u9fff\uf900-\ufaff]", str(value or "")))


def _filter_int(value: object, default: int = 0) -> int:
    """Parse ``value`` as an integer, returning ``default`` on failure."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        match = re.search(r"-?\d+", text)
        if match:
            try:
                return int(match.group(0))
            except ValueError:
                return default
        return default


def _short_drama_cost_basis(value: object) -> tuple[int, Decimal, Decimal] | None:
    """Return active shots and the provider-billed duration range.

    A valid short-drama script has one exact ``=== SHOT_N ===`` block per
    active shot and one ``DURATION_S`` line in each block. The paid media DAG
    uses the same exact headers and clamps each video request to 3-15 seconds,
    so the estimate mirrors the work that can actually be submitted. If a
    malformed block omits its duration, use the provider-billed 4-15 second
    interval instead of inventing a precise figure. OpenRouter's Seedance 2.0
    routes bill the workflow's 3-second option as a 4-second generation before
    the local runtime trims the delivered clip back to 3 seconds.
    """

    text = str(value or "")
    headers = list(_SHORT_DRAMA_SHOT_HEADER_RE.finditer(text))
    durations: dict[int, Decimal | None] = {}
    for index, header in enumerate(headers):
        shot_number = int(header.group(1))
        if shot_number in durations:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        duration_match = _SHORT_DRAMA_DURATION_RE.search(text, header.end(), end)
        duration = Decimal(duration_match.group(1)) if duration_match else None
        durations[shot_number] = duration

    if not durations:
        declared_match = _SHORT_DRAMA_DECLARED_SHOTS_RE.search(text)
        overview_end = headers[0].start() if headers else len(text)
        overview_duration = _SHORT_DRAMA_DURATION_RE.search(text, 0, overview_end)
        if declared_match is None or overview_duration is None:
            return None
        shot_count = int(declared_match.group(1))
        duration = Decimal(overview_duration.group(1))
        minimum = Decimal(3 * shot_count)
        maximum = Decimal(15 * shot_count)
        clamped = min(max(duration, minimum), maximum)
        # The overview-only fallback does not expose how the total is split
        # across shots. Each 3-second shot can therefore add one billed second.
        billed_high = min(maximum, clamped + Decimal(shot_count))
        billed_low = max(clamped, Decimal(4 * shot_count))
        return shot_count, billed_low, max(billed_low, billed_high)

    duration_low = Decimal("0")
    duration_high = Decimal("0")
    for duration in durations.values():
        if duration is None:
            duration_low += Decimal("4")
            duration_high += Decimal("15")
            continue
        clamped = min(max(duration, Decimal("3")), Decimal("15"))
        billed = Decimal("4") if clamped == Decimal("3") else clamped
        duration_low += billed
        duration_high += billed
    return len(durations), duration_low, duration_high


def _format_duration_range(low: Decimal, high: Decimal, *, language: str) -> str:
    def _format(value: Decimal) -> str:
        return format(value.normalize(), "f")

    if low == high:
        return f"{_format(low)} 秒" if language == "zh" else f"{_format(low)}s"
    separator = "-"
    if language == "zh":
        return f"{_format(low)}{separator}{_format(high)} 秒"
    return f"{_format(low)}-{_format(high)}s"


def _filter_short_drama_media_cost(value: object, language: str = "en") -> str:
    """Render a deterministic consent-time USD estimate for a drama script."""

    localized = "zh" if str(language).strip().lower().startswith("zh") else "en"
    basis = _short_drama_cost_basis(value)
    if basis is None:
        if localized == "zh":
            return (
                "本次脚本无法解析出镜头数和总时长，暂时无法给出可授权的美元估算区间；"
                "请先修订脚本，不要批准媒体生成。"
            )
        return (
            "The script does not expose a parseable shot count and total duration, "
            "so no authorizable USD estimate can be shown yet. Revise the script "
            "before approving media generation."
        )

    shot_count, duration_low, duration_high = basis
    image_low = Decimal(shot_count) * Decimal("0.05") + Decimal("0.05")
    image_high = Decimal(shot_count) * Decimal("0.05") + Decimal("0.10")
    total_low = image_low + duration_low * Decimal("0.15")
    total_high = image_high + duration_high * Decimal("0.15")
    cost_range = f"USD ${total_low:.2f}-${total_high:.2f}"
    duration = _format_duration_range(duration_low, duration_high, language=localized)

    if localized == "zh":
        return (
            f"本次脚本媒体成本估算：{shot_count} 个镜头，计费剧情时长 {duration}；"
            f"预计总计 {cost_range}。依据：镜头图约 $0.05/张、全角色参考图 "
            "$0.05-$0.10、视频约 $0.15/秒；实际账单由所选提供商决定。"
        )
    shot_label = "shot" if shot_count == 1 else "shots"
    return (
        f"Estimated media cost for this script: {shot_count} {shot_label}, "
        f"{duration} of billable story footage; estimated total {cost_range}. "
        "Basis: about $0.05 per shot image, $0.05-$0.10 for the full-cast "
        "reference image, and about $0.15 per video second. The selected "
        "provider determines the actual bill."
    )


def _build_jinja_env() -> jinja2.sandbox.ImmutableSandboxedEnvironment:
    # ``ImmutableSandboxedEnvironment`` blocks Python attribute introspection
    # (``__class__`` / ``__mro__`` / ``__subclasses__``) and mutation
    # operations on inputs. The previous ``jinja2.Environment`` cleared
    # globals and installed a filter allowlist, but left attribute access
    # open — a SKILL.md author could escape via
    # ``{{ inputs.__class__.__mro__[1].__subclasses__() }}``. Sandboxing
    # at the env level keeps ``inputs.get(...)`` / ``inputs['x']`` /
    # ``outputs.prev`` working for legitimate templates.
    env = jinja2.sandbox.ImmutableSandboxedEnvironment(
        undefined=jinja2.StrictUndefined,
        autoescape=False,
        extensions=[],
        keep_trailing_newline=False,
    )
    # Strip unsafe globals/filters; install our allowlist.
    env.globals.clear()
    env.filters = {
        "xml_escape": _filter_xml_escape,
        "truncate": _filter_truncate,
        "slugify": _filter_slugify,
        "tojson": jinja2.filters.do_tojson,
        "default": jinja2.filters.do_default,
        "length": len,
        "join": jinja2.filters.do_join,
        "lower": lambda value: str(value).lower(),
        "extract_path": _filter_extract_path,
        "contains_cjk": _filter_contains_cjk,
        "int": _filter_int,
        "short_drama_media_cost": _filter_short_drama_media_cost,
    }
    return env


_JINJA_ENV = _build_jinja_env()


def render_with_args(
    template_map: dict[str, Any],
    *,
    inputs: dict[str, Any],
    outputs: dict[str, str],
) -> dict[str, Any]:
    """Render every leaf string in ``template_map`` against ``inputs/outputs``.

    Non-string leaves pass through unchanged. Nested dicts / lists are walked
    recursively. A ``jinja2.UndefinedError`` becomes a regular ValueError so
    the orchestrator's StepFailure handling treats it as a normal failure.
    """

    context = {
        "inputs": inputs,
        "outputs": outputs,
    }

    def _render(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return _JINJA_ENV.from_string(value).render(**context)
            except jinja2.UndefinedError as exc:
                raise ValueError(f"undefined template variable: {exc}") from exc
            except jinja2.TemplateSyntaxError as exc:
                raise ValueError(f"template syntax error: {exc}") from exc
            except jinja2.sandbox.SecurityError as exc:
                raise ValueError(
                    f"template security violation: {exc}",
                ) from exc
        if isinstance(value, dict):
            return {k: _render(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_render(item) for item in value]
        return value

    rendered = _render(template_map)
    assert isinstance(rendered, dict)
    return rendered


def resolve_route(
    cases: tuple[RouteCase, ...],
    *,
    inputs: dict[str, Any],
    outputs: dict[str, str],
) -> str | None:
    """Return the ``to`` skill of the first case whose ``when`` evaluates truthy.

    Returns ``None`` when ``cases`` is empty or no case matches — caller falls
    back to the step's default ``skill`` name.  Jinja errors are surfaced as
    :class:`ValueError` so the orchestrator's step-failure path catches them.
    """

    if not cases:
        return None
    context = {"inputs": inputs, "outputs": outputs}
    for index, case in enumerate(cases):
        # Wrap the expression as ``{{ (<expr>) | tojson }}`` is overkill; use
        # Jinja's ``compile_expression`` so the user writes a real expression
        # (``outputs.classify == 'URL'``) rather than a template.
        try:
            expr = _JINJA_ENV.compile_expression(case.when)
        except jinja2.TemplateSyntaxError as exc:
            raise ValueError(
                f"route[{index}] when expression syntax error: {exc}",
            ) from exc
        try:
            value = expr(**context)
        except jinja2.UndefinedError as exc:
            raise ValueError(
                f"route[{index}] when references undefined variable: {exc}",
            ) from exc
        except jinja2.sandbox.SecurityError as exc:
            raise ValueError(
                f"route[{index}] when security violation: {exc}",
            ) from exc
        if value:
            return case.to
    return None


def evaluate_when(
    expression: str,
    *,
    inputs: dict[str, Any],
    outputs: dict[str, str],
) -> bool:
    """Evaluate a step-level ``when`` expression with route-like semantics."""

    if not expression:
        return True
    context = {"inputs": inputs, "outputs": outputs}
    try:
        expr = _JINJA_ENV.compile_expression(expression)
    except jinja2.TemplateSyntaxError as exc:
        raise ValueError(f"when expression syntax error: {exc}") from exc
    try:
        return bool(expr(**context))
    except jinja2.UndefinedError as exc:
        raise ValueError(f"when references undefined variable: {exc}") from exc
    except jinja2.sandbox.SecurityError as exc:
        raise ValueError(f"when security violation: {exc}") from exc


def format_step_prompt(
    skill_name: str,
    args: dict[str, Any],
    *,
    language_instruction: str = "",
) -> str:
    """Render the user-message payload that drives one sub-Agent turn."""

    if not args:
        prompt = (
            f"Run the {skill_name} skill with no arguments. "
            "Produce the deliverable described in its SKILL.md."
        )
        if language_instruction.strip():
            prompt = f"{prompt}\n\n{language_instruction.strip()}"
        return prompt

    lines = [f"Invoke the {skill_name} skill with the following arguments:"]
    for key, value in args.items():
        if isinstance(value, str):
            lines.append(f"- {key}: {value}")
        else:
            lines.append(f"- {key}: {value!r}")
    lines.append(
        "\nWhen the work is complete, reply with the final deliverable as plain text. "
        "If the skill produced a file, include the absolute path on the last line.",
    )
    if language_instruction.strip():
        lines.append(f"\n{language_instruction.strip()}")
    return "\n".join(lines)


def _format_classify_prompt(step: MetaStep, args: dict[str, Any]) -> str:
    """Render the user-message body for an ``llm_classify`` step.

    Concatenates the rendered ``with_args`` values into a flat prompt — the
    classifier system prompt already constrains the output, so we don't
    re-state the choices here.
    """

    if not args:
        return ""
    parts: list[str] = []
    for key, value in args.items():
        text = value if isinstance(value, str) else repr(value)
        # Skip purely-decorative keys; otherwise prefix with the key for clarity.
        if key in ("text", "prompt", "task", "input"):
            parts.append(text)
        else:
            parts.append(f"{key}: {text}")
    return "\n".join(parts).strip()


def _expand_skill_placeholders(skill_spec: Any) -> str:
    """Substitute ``{baseDir}`` (and aliases) in a skill body with its real path.

    Bundled SKILL.md files reference helper scripts via ``{baseDir}/scripts/foo.py``.
    Regular skill invocation routes the body through tooling that resolves
    these placeholders; meta-skill composition injects the body directly into
    a sub-Agent system prompt, so we must do the same substitution here —
    otherwise the sub-Agent sees a literal ``{baseDir}`` and tries to glob
    the workspace for it.
    """

    body = (getattr(skill_spec, "content", "") or "").strip()
    base_dir = str(getattr(skill_spec, "base_dir", "") or "").rstrip("/")
    if not base_dir:
        return body
    # Cover both the canonical ``{baseDir}`` and the snake-case alias some
    # internal tools emit; keep substitution simple (no regex) so the body
    # remains byte-stable for callers that hash it.
    return body.replace("{baseDir}", base_dir).replace("{base_dir}", base_dir)


def _coerce_to_choice(raw: str, choices: list[str]) -> str:
    """Normalise a model reply to one of the allowed labels.

    Match precedence: exact → quote/punctuation-stripped → case-insensitive →
    uppercase-substring containment. When nothing matches the original trimmed
    text is returned — downstream route ``when`` clauses use Python's ``in``
    against it and can still succeed.
    """

    if not choices:
        return raw.strip()
    text = raw.strip()
    if text in choices:
        return text
    stripped = text.strip("'\"`.,!? \t\r\n")
    if stripped in choices:
        return stripped
    upper = stripped.upper()
    for choice in choices:
        if upper == choice.upper():
            return choice
    for choice in choices:
        if choice.upper() in upper:
            return choice
    return stripped or text


__all__ = [
    "_JINJA_ENV",
    "_coerce_to_choice",
    "_expand_skill_placeholders",
    "_format_classify_prompt",
    "format_step_prompt",
    "evaluate_when",
    "render_with_args",
    "resolve_route",
]
