"""Shared input helpers for meta-skill invocations."""

from __future__ import annotations

from typing import Any


def system_prompt_input(system_prompt: Any) -> str:
    """Serialize the live system prompt into a meta-skill template input."""

    if system_prompt is None:
        return ""
    if isinstance(system_prompt, tuple):
        parts = [str(part) for part in system_prompt if part]
        return "\n\n".join(parts)
    return str(system_prompt)


def make_meta_inputs(*, user_message: str, system_prompt: Any = "") -> dict[str, Any]:
    """Build the common input map visible to meta-skill Jinja templates."""

    return {
        "user_message": user_message,
        "system_prompt": system_prompt_input(system_prompt),
    }
