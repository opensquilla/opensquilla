"""CLI workflows for skill publish commands."""

from __future__ import annotations

from opensquilla.cli.skills_publish import publish_skill_for_cli
from opensquilla.cli.skills_publish_presenters import emit_skill_publish_result


async def publish_skill_for_cli_command(
    skill_dir: str,
    repo: str | None,
) -> None:
    """Publish a skill and emit the CLI result."""

    result = await publish_skill_for_cli(skill_dir, repo)
    emit_skill_publish_result(result)
