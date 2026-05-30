"""Shared input helpers for meta-skill invocations."""

from __future__ import annotations

import re
from typing import Any

_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def system_prompt_input(system_prompt: Any) -> str:
    """Serialize the live system prompt into a meta-skill template input."""

    if system_prompt is None:
        return ""
    if isinstance(system_prompt, tuple):
        parts = [str(part) for part in system_prompt if part]
        return "\n\n".join(parts)
    return str(system_prompt)


def detect_user_language(user_message: str) -> str:
    """Return the deterministic language hint exposed to meta-skill templates."""

    return "zh" if _CJK_RE.search(user_message or "") else "en"


def make_meta_inputs(*, user_message: str, system_prompt: Any = "") -> dict[str, Any]:
    """Build the common input map visible to meta-skill Jinja templates."""

    return {
        "user_message": user_message,
        "user_language": detect_user_language(user_message),
        "system_prompt": system_prompt_input(system_prompt),
        # Populated by MetaOrchestrator.resume() in PR3; downstream
        # template authors address structured user_input values as
        # `inputs.collected.<step_id>.<field>` (see design §5.3).
        "collected": {},
    }
