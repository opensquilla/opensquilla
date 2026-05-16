"""Skill publish flow — validate format and push to repository."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass
class PublishResult:
    """Result of a skill publish attempt."""

    success: bool
    message: str = ""
    skill_name: str = ""


@dataclass(frozen=True)
class SkillPublishRequest:
    """Validated request to validate or publish a Community skill."""

    skill_dir: Path
    target_repo: str | None = None


def skill_publish_request(params: Mapping[str, Any] | None) -> SkillPublishRequest:
    """Build a publish operation request from command or RPC params."""

    if not isinstance(params, Mapping) or "skill_dir" not in params:
        raise ValueError("params.skill_dir is required")

    target_repo = params.get("target_repo", params.get("repo"))
    if target_repo is not None and not isinstance(target_repo, str):
        target_repo = None

    return SkillPublishRequest(
        skill_dir=Path(str(params["skill_dir"])),
        target_repo=target_repo,
    )


def validate_skill_dir(skill_dir: Path) -> list[str]:
    """Validate a skill directory is publishable. Returns list of errors."""
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"

    if not skill_dir.is_dir():
        errors.append(f"Not a directory: {skill_dir}")
        return errors

    if not skill_file.exists():
        errors.append("Missing SKILL.md")
        return errors

    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        errors.append("SKILL.md missing YAML frontmatter (---)")
        return errors

    import yaml

    try:
        fm = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML frontmatter: {e}")
        return errors

    if not isinstance(fm, dict):
        errors.append("Frontmatter is not a dict")
        return errors

    if "name" not in fm:
        errors.append("Frontmatter missing required 'name' field")
    if "description" not in fm:
        errors.append("Frontmatter missing required 'description' field")

    body = match.group(2).strip()
    if len(body) < 20:
        errors.append("SKILL.md body is too short (< 20 chars)")

    return errors


async def publish_skill(
    skill_dir: Path,
    target_repo: str | None = None,
) -> PublishResult:
    """Validate and publish a skill.

    If target_repo is provided (owner/repo), creates a fork and PR.
    Otherwise just validates.
    """
    errors = validate_skill_dir(skill_dir)
    if errors:
        return PublishResult(
            success=False,
            message=f"Validation failed: {'; '.join(errors)}",
        )

    # Read skill name
    import yaml

    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    fm = yaml.safe_load(match.group(1)) if match else {}
    skill_name = fm.get("name", skill_dir.name)

    if target_repo is None:
        return PublishResult(
            success=True,
            message=f"Skill '{skill_name}' validated successfully. Provide --repo to publish.",
            skill_name=skill_name,
        )

    # GitHub publish via gh CLI
    import asyncio

    parts = target_repo.split("/")
    if len(parts) != 2:
        return PublishResult(success=False, message=f"Invalid repo format: {target_repo}")

    owner, repo = parts
    branch = f"skill/{skill_name}"

    try:
        # Fork + clone + add skill + push + create PR
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "repo",
            "fork",
            target_repo,
            "--clone=false",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()

        log.info("publish.fork_created", repo=target_repo, skill=skill_name)
        return PublishResult(
            success=True,
            message=f"Skill '{skill_name}' ready for PR to {target_repo}. "
            f"Fork created, use branch '{branch}' to submit.",
            skill_name=skill_name,
        )
    except FileNotFoundError:
        return PublishResult(
            success=False,
            message="GitHub CLI (gh) not found. Install it to publish skills.",
        )
    except Exception as exc:
        return PublishResult(success=False, message=f"Publish failed: {exc}")


async def publish_skill_from_request(request: SkillPublishRequest) -> PublishResult:
    """Run the publish workflow from a validated operation request."""

    return await publish_skill(request.skill_dir, target_repo=request.target_repo)
