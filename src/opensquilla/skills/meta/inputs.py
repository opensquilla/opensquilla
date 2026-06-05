"""Shared input helpers for meta-skill invocations."""

from __future__ import annotations

import base64
import json
import re
from typing import Any

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_EXPLICIT_CHINESE_RE = re.compile(
    r"\b(?:in|to|into|as)\s+(?:simplified\s+)?(?:chinese|mandarin)\b"
    r"|\b(?:simplified\s+)?chinese\b"
    r"|中文|简体|普通话",
    re.IGNORECASE,
)
_EXPLICIT_ENGLISH_RE = re.compile(
    r"\b(?:in|to|into|as)\s+english\b|\benglish[- ]only\b|\benglish\b",
    re.IGNORECASE,
)
_PREFLIGHT_CONFIRMED_RE = re.compile(
    r"\s*<!--\s*opensquilla:meta_preflight_confirmed=1\s*-->\s*",
    re.IGNORECASE,
)
_PREFLIGHT_RUN_ID_RE = re.compile(
    r"\s*<!--\s*opensquilla:meta_preflight_run_id=([A-Za-z0-9:_-]+)\s*-->\s*",
    re.IGNORECASE,
)
_PREFLIGHT_FIELDS_RE = re.compile(
    r"\s*<!--\s*opensquilla:meta_preflight_fields=([A-Za-z0-9_\-=]+)\s*-->\s*",
    re.IGNORECASE,
)


def _decode_preflight_fields(value: str) -> dict[str, Any]:
    if not value or len(value) > 16_384:
        return {}
    padded = value + ("=" * (-len(value) % 4))
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): item
        for key, item in payload.items()
        if key is not None and str(key).strip()
    }


def system_prompt_input(system_prompt: Any) -> str:
    """Serialize the live system prompt into a meta-skill template input."""

    if system_prompt is None:
        return ""
    if isinstance(system_prompt, tuple):
        parts = [str(part) for part in system_prompt if part]
        return "\n\n".join(parts)
    return str(system_prompt)


def detect_user_language(user_message: str) -> str:
    """Return the best-effort output language for a meta-skill request."""

    text = user_message or ""
    if _EXPLICIT_CHINESE_RE.search(text):
        return "zh"
    if _EXPLICIT_ENGLISH_RE.search(text):
        return "en"
    if _CJK_RE.search(text):
        return "zh"
    if _LATIN_RE.search(text):
        return "en"
    return "same"


def language_instruction_for_user_message(user_message: str) -> str:
    """Build the global language guard injected into meta-skill text steps."""

    language = detect_user_language(user_message)
    if language == "zh":
        return (
            "Output language rule: write final user-facing prose, headings, "
            "labels, and summaries in Simplified Chinese unless the user "
            "explicitly asks for another language. Do not switch to English "
            "because a template includes English examples; machine-readable "
            "protocol labels may stay in their required format."
        )
    if language == "en":
        return (
            "Output language rule: write final user-facing prose, headings, "
            "labels, and summaries in English only unless the user explicitly "
            "asks for another language. Do not copy Chinese or bilingual "
            "headings from meta-skill templates; translate template examples "
            "to English. Non-user-facing protocol labels may stay in their "
            "required format, and source quotations may preserve their "
            "original language."
        )
    return (
        "Output language rule: match the user's language for final "
        "user-facing prose, headings, labels, and summaries. Treat bilingual "
        "template examples as examples, not required output text. "
        "Non-user-facing protocol labels may stay in their required format."
    )


def make_meta_inputs(*, user_message: str, system_prompt: Any = "") -> dict[str, Any]:
    """Build the common input map visible to meta-skill Jinja templates."""

    meta_preflight_confirmed = bool(_PREFLIGHT_CONFIRMED_RE.search(user_message or ""))
    run_id_match = _PREFLIGHT_RUN_ID_RE.search(user_message or "")
    fields_match = _PREFLIGHT_FIELDS_RE.search(user_message or "")
    clean_user_message = _PREFLIGHT_CONFIRMED_RE.sub("\n", user_message or "")
    clean_user_message = _PREFLIGHT_RUN_ID_RE.sub("\n", clean_user_message).strip()
    clean_user_message = _PREFLIGHT_FIELDS_RE.sub("\n", clean_user_message).strip()
    user_language = detect_user_language(clean_user_message)
    preflight_fields = (
        _decode_preflight_fields(fields_match.group(1))
        if fields_match
        else {}
    )
    inputs: dict[str, Any] = {
        "user_message": clean_user_message,
        "user_language": user_language,
        "language_instruction": language_instruction_for_user_message(clean_user_message),
        "system_prompt": system_prompt_input(system_prompt),
        # Populated by MetaOrchestrator.resume() in PR3; downstream
        # template authors address structured user_input values as
        # `inputs.collected.<step_id>.<field>` (see design §5.3).
        "collected": {},
    }
    if meta_preflight_confirmed:
        inputs["meta_preflight_confirmed"] = True
    if run_id_match:
        inputs["meta_preflight_run_id"] = run_id_match.group(1)
    if preflight_fields:
        inputs["meta_preflight_fields"] = preflight_fields
        inputs["collected"]["preflight"] = preflight_fields
    return inputs
