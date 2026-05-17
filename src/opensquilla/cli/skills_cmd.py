"""CLI commands for skill management."""

from __future__ import annotations

import asyncio

import typer

from opensquilla.cli.skills_catalog_presenters import (
    emit_skill_rows,
    emit_skill_search_results,
)
from opensquilla.cli.skills_gateway_mutations import try_gateway_skill_mutation
from opensquilla.cli.skills_gateway_presenters import (
    emit_gateway_skill_update,
    emit_gateway_skill_view,
)
from opensquilla.cli.skills_gateway_queries import (
    load_gateway_skill,
    update_gateway_skills,
)
from opensquilla.cli.skills_local_mutations import (
    run_local_skill_install,
    run_local_skill_uninstall,
)
from opensquilla.cli.skills_mutation_presenters import (
    emit_failed_skill_mutation,
    emit_local_skill_install_result,
    emit_local_skill_install_start,
    emit_local_skill_uninstall_result,
    emit_missing_skill_mutation_result,
    emit_skill_mutation_payload,
)
from opensquilla.cli.skills_publish import publish_skill_for_cli
from opensquilla.cli.skills_rows import load_skill_rows
from opensquilla.cli.skills_search_rows import search_skill_rows
from opensquilla.cli.skills_tap_presenters import (
    emit_skill_tap_added,
    emit_skill_tap_error,
    emit_skill_tap_removed,
    emit_skill_taps,
)
from opensquilla.cli.skills_taps import add_skill_tap, list_skill_taps, remove_skill_tap
from opensquilla.cli.ui import console

skills_app = typer.Typer(help="Skill management - list, search, install, uninstall.")


@skills_app.command("list")
def skills_list(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all installed/available skills."""
    rows = load_skill_rows()
    emit_skill_rows(rows, json_output=json_output)


@skills_app.command("search")
def skills_search(
    query: str = typer.Argument(..., help="Search query"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Search for skills across Community sources."""

    async def _search() -> None:
        results = await search_skill_rows(query)
        emit_skill_search_results(query, results, json_output=json_output)

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
        payload = await try_gateway_skill_mutation(
            "skills.install",
            {"identifier": identifier, "source": source, "force": force},
            json_output=json_output,
        )
        if payload is not None:
            emit_skill_mutation_payload(
                payload,
                json_output=json_output,
                success_label="Installed",
                fallback_name=identifier,
            )
            return

        emit_local_skill_install_start(identifier, source, json_output=json_output)
        outcome = await run_local_skill_install(
            identifier,
            source=source,
            force=force,
        )
        if outcome.unavailable_message:
            emit_failed_skill_mutation(
                outcome.unavailable_message,
                json_output=json_output,
                success_label="Installed",
                fallback_name=identifier,
            )
            return

        result = outcome.result
        if result is None:
            emit_missing_skill_mutation_result(
                "install",
                json_output=json_output,
                success_label="Installed",
                fallback_name=identifier,
            )
            return

        emit_local_skill_install_result(result, json_output=json_output)

    asyncio.run(_install())


@skills_app.command("uninstall")
def skills_uninstall(
    name: str = typer.Argument(..., help="Skill name to remove"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Uninstall a managed skill."""

    async def _uninstall() -> None:
        payload = await try_gateway_skill_mutation(
            "skills.uninstall",
            {"name": name},
            json_output=json_output,
        )
        if payload is not None:
            emit_skill_mutation_payload(
                payload,
                json_output=json_output,
                success_label="Uninstalled",
                fallback_name=name,
            )
            return

        outcome = await run_local_skill_uninstall(name)
        if outcome.unavailable_message:
            emit_failed_skill_mutation(
                outcome.unavailable_message,
                json_output=json_output,
                success_label="Uninstalled",
                fallback_name=name,
            )
            return

        result = outcome.result
        if result is None:
            emit_missing_skill_mutation_result(
                "uninstall",
                json_output=json_output,
                success_label="Uninstalled",
                fallback_name=name,
            )
            return

        emit_local_skill_uninstall_result(result, json_output=json_output)

    asyncio.run(_uninstall())


# ── Tap sub-commands ──────────────────────────────────────────────────────

tap_app = typer.Typer(help="Manage custom skill source repositories (taps).")
skills_app.add_typer(tap_app, name="tap")


@tap_app.command("add")
def tap_add(owner_repo: str = typer.Argument(..., help="GitHub owner/repo")) -> None:
    """Add a custom skill source tap."""
    try:
        tap = add_skill_tap(owner_repo)
        emit_skill_tap_added(tap)
    except ValueError as e:
        emit_skill_tap_error(e)


@tap_app.command("list")
def tap_list() -> None:
    """List registered taps."""
    taps = list_skill_taps()
    emit_skill_taps(taps)


@tap_app.command("remove")
def tap_remove(owner_repo: str = typer.Argument(..., help="GitHub owner/repo")) -> None:
    """Remove a tap."""
    emit_skill_tap_removed(owner_repo, removed=remove_skill_tap(owner_repo))


# ── Publish command ───────────────────────────────────────────────────────


@skills_app.command("publish")
def skills_publish(
    skill_dir: str = typer.Argument(..., help="Path to skill directory"),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Target repo (owner/repo) for PR"),
) -> None:
    """Validate and publish a skill to a repository."""

    async def _publish() -> None:
        result = await publish_skill_for_cli(skill_dir, repo)
        if result.success:
            console.print(f"[green]OK:[/] {result.message}")
        else:
            console.print(f"[red]Failed:[/] {result.message}")

    asyncio.run(_publish())
