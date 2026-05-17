"""CLI workflows for skill publish commands."""

from __future__ import annotations

import asyncio

from opensquilla.cli.skills_publish import publish_skill_for_cli
from opensquilla.cli.skills_publish_presenters import emit_skill_publish_result


def publish_skill_for_cli_command(
    skill_dir: str,
    repo: str | None,
) -> None:
    """Run a skill publish workflow from a synchronous CLI command."""

    asyncio.run(_publish_skill_for_cli_command(skill_dir, repo))


async def _publish_skill_for_cli_command(
    skill_dir: str,
    repo: str | None,
) -> None:
    """Publish a skill and emit the CLI result."""

    result = await publish_skill_for_cli(skill_dir, repo)
    emit_skill_publish_result(result)
