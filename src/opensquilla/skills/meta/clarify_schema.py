"""Surface-agnostic JSON protocol for user_input form schemas.

When a meta-skill pauses at a ``user_input`` step, the runtime needs to
hand the form description to one of three surfaces (Web / CLI / IM)
*without* leaking implementation-internal types. This module produces a
stable, JSON-safe dict that all surfaces can render against.

The protocol is intentionally minimal:
- Only fields the renderer needs (name, type, prompt, required,
  defaults, choices, range, length).
- All user-facing text (``prompt``, ``intro``) is XML-escaped at the
  boundary so surface templates that embed the strings in HTML or
  XML-shaped tool descriptions cannot be injected.
- The same payload shape is consumed by:
  - ``gateway/rpc_chat.py`` (PR5) — emits as
    ``session.event.meta_clarify_request``
  - ``cli/repl/*`` (PR6) — prompts via ``prompt-toolkit``
  - ``channels/*`` (PR7) — renders as plain text fallback

Cross-references:
- Design §9 — Surface Renderers
- Design §10 — Error Handling (the protocol does NOT carry validation
  errors; those go on a separate ``meta_clarify_errors`` event)
"""

from __future__ import annotations

from typing import Any

from opensquilla.skills.meta.types import ClarifyField, ClarifyStepConfig


def _xml_escape(text: str) -> str:
    """Minimal XML/HTML escape applied to author-supplied text.

    Mirrors the existing escape in ``opensquilla.skills.injector`` so a
    single string can be re-rendered into the meta-skill catalogue, a
    WebSocket payload, or a plain-text bot message without double
    escaping.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def field_to_protocol(field: ClarifyField) -> dict[str, Any]:
    """Convert one ClarifyField into the stable JSON shape surfaces consume.

    Only the keys the renderer needs are exposed; defaults / range /
    length appear only when the author set them, so the payload size
    stays minimal for fields with no constraints.
    """

    payload: dict[str, Any] = {
        "name": field.name,
        "type": field.type,
        "required": field.required,
        "prompt": _xml_escape(field.prompt),
    }
    if field.choices:
        payload["choices"] = list(field.choices)
    if field.default is not None:
        payload["default"] = field.default
    if field.min is not None:
        payload["min"] = field.min
    if field.max is not None:
        payload["max"] = field.max
    if field.max_chars is not None:
        payload["max_chars"] = field.max_chars
    return payload


def schema_to_protocol(
    schema: ClarifyStepConfig,
    *,
    intro_override: str = "",
) -> dict[str, Any]:
    """Convert a ClarifyStepConfig to a JSON-safe surface payload.

    ``intro_override`` lets the caller (executor / orchestrator) supply
    a step-specific intro line that takes precedence over the schema's
    own intro — useful when the step body has author-customised
    pre-form text.

    Returns a dict with these keys (all serialisable):
      ``mode``           — "form" | "chat"
      ``intro``          — XML-escaped intro string (may be empty)
      ``fields``         — list of field protocol dicts
      ``cancel_keywords`` — tuple-as-list of normalised cancel words
      ``timeout_hours``  — int
      ``nl_extract``     — bool (informational; surfaces don't render
                            this differently, but operators may inspect)
    """

    intro_source = intro_override if intro_override else schema.intro
    return {
        "mode": schema.mode,
        "intro": _xml_escape(intro_source),
        "fields": [field_to_protocol(f) for f in schema.fields],
        "cancel_keywords": list(schema.cancel_keywords),
        "timeout_hours": schema.timeout_hours,
        "nl_extract": schema.nl_extract,
    }
