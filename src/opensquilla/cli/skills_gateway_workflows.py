"""CLI workflows for gateway-backed skill commands."""

from __future__ import annotations

from opensquilla.cli.skills_gateway_presenters import (
    emit_gateway_skill_update,
    emit_gateway_skill_view,
)
from opensquilla.cli.skills_gateway_queries import (
    load_gateway_skill,
    update_gateway_skills,
)


def view_gateway_skill_for_cli(name: str, *, json_output: bool) -> None:
    """Load and emit one gateway-backed skill."""

    payload = load_gateway_skill(name, json_output=json_output)
    emit_gateway_skill_view(payload, fallback_name=name, json_output=json_output)


def update_gateway_skills_for_cli(
    name: str | None,
    *,
    all_skills: bool,
    json_output: bool,
) -> None:
    """Update gateway-backed skills and emit the result."""

    payload = update_gateway_skills(
        name,
        all_skills=all_skills,
        json_output=json_output,
    )
    emit_gateway_skill_update(payload, json_output=json_output)
