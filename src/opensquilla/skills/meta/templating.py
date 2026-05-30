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
from typing import Any

import jinja2

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
            return token
    return ""


def _build_jinja_env() -> jinja2.Environment:
    env = jinja2.Environment(
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


def format_step_prompt(skill_name: str, args: dict[str, Any]) -> str:
    """Render the user-message payload that drives one sub-Agent turn."""

    if not args:
        return (
            f"Run the {skill_name} skill with no arguments. "
            "Produce the deliverable described in its SKILL.md."
        )

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
