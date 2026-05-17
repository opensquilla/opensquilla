"""CLI commands for skill management."""

from __future__ import annotations

import asyncio

import typer

from opensquilla.cli.skills_gateway_presenters import (
    emit_gateway_skill_update,
    emit_gateway_skill_view,
)
from opensquilla.cli.skills_gateway_queries import (
    load_gateway_skill,
    update_gateway_skills,
)
from opensquilla.cli.skills_list_workflows import list_skills_for_cli
from opensquilla.cli.skills_mutation_workflows import (
    install_skill_for_cli,
    uninstall_skill_for_cli,
)
from opensquilla.cli.skills_publish_workflows import publish_skill_for_cli_command
from opensquilla.cli.skills_search_workflows import search_skills_for_cli
from opensquilla.cli.skills_tap_workflows import (
    add_skill_tap_for_cli,
    list_skill_taps_for_cli,
    remove_skill_tap_for_cli,
)

skills_app = typer.Typer(help="Skill management - list, search, install, uninstall.")


@skills_app.command("list")
def skills_list(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all installed/available skills."""
    list_skills_for_cli(json_output=json_output)


@skills_app.command("search")
def skills_search(
    query: str = typer.Argument(..., help="Search query"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Search for skills across Community sources."""

    async def _search() -> None:
        await search_skills_for_cli(query, json_output=json_output)

    asyncio.run(_search())


@skills_app.command("view")
def skills_view(
    name: str = typer.Argument(..., help="Skill name"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect a single skill from the running gateway."""

    payload = load_gateway_skill(name, json_output=json_output)
    emit_gateway_skill_view(payload, fallback_name=name, json_output=json_output)


@skills_app.command("update")
def skills_update(
    name: str | None = typer.Argument(None, help="Skill name to update"),
    all_skills: bool = typer.Option(False, "--all", help="Update all managed skills"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Update one managed skill, or all managed skills."""
    if bool(name) == all_skills:
        raise typer.BadParameter("provide exactly one of NAME or --all")

    payload = update_gateway_skills(name, all_skills=all_skills, json_output=json_output)
    emit_gateway_skill_update(payload, json_output=json_output)


@skills_app.command("install")
def skills_install(
    identifier: str = typer.Argument(..., help="Skill name or identifier"),
    source: str = typer.Option(
        "clawhub",
        "--source",
        "-s",
        help=(
            "Source (clawhub, github). GitHub accepts owner/repo, "
            "owner/repo:path, or GitHub URLs."
        ),
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Force install (skip security block)"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Install a skill from a Community source."""

    async def _install() -> None:
        await install_skill_for_cli(
            identifier,
            source=source,
            force=force,
            json_output=json_output,
        )

    asyncio.run(_install())


@skills_app.command("uninstall")
def skills_uninstall(
    name: str = typer.Argument(..., help="Skill name to remove"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Uninstall a managed skill."""

    async def _uninstall() -> None:
        await uninstall_skill_for_cli(name, json_output=json_output)

    asyncio.run(_uninstall())


# ── Tap sub-commands ──────────────────────────────────────────────────────

tap_app = typer.Typer(help="Manage custom skill source repositories (taps).")
skills_app.add_typer(tap_app, name="tap")


@tap_app.command("add")
def tap_add(owner_repo: str = typer.Argument(..., help="GitHub owner/repo")) -> None:
    """Add a custom skill source tap."""
    add_skill_tap_for_cli(owner_repo)


@tap_app.command("list")
def tap_list() -> None:
    """List registered taps."""
    list_skill_taps_for_cli()


@tap_app.command("remove")
def tap_remove(owner_repo: str = typer.Argument(..., help="GitHub owner/repo")) -> None:
    """Remove a tap."""
    remove_skill_tap_for_cli(owner_repo)


# ── Publish command ───────────────────────────────────────────────────────


@skills_app.command("publish")
def skills_publish(
    skill_dir: str = typer.Argument(..., help="Path to skill directory"),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Target repo (owner/repo) for PR"),
) -> None:
    """Validate and publish a skill to a repository."""

    async def _publish() -> None:
        await publish_skill_for_cli_command(skill_dir, repo)

    asyncio.run(_publish())
