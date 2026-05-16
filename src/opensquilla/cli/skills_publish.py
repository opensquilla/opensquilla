"""Local publish workflow for CLI skill commands."""

from __future__ import annotations

from typing import Any


async def publish_skill_for_cli(skill_dir: str, repo: str | None = None) -> Any:
    """Validate and publish a skill using the hub operation boundary."""

    from opensquilla.skills.hub.operations import (
        publish_skill_from_request,
        skill_publish_request,
    )

    return await publish_skill_from_request(
        skill_publish_request({"skill_dir": skill_dir, "target_repo": repo})
    )
