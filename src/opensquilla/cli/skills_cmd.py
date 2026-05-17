"""CLI commands for skill management."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

import typer

from opensquilla.cli.output import print_json
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
from opensquilla.cli.skills_publish import publish_skill_for_cli
from opensquilla.cli.skills_rows import load_skill_rows
from opensquilla.cli.skills_search_rows import search_skill_rows
from opensquilla.cli.skills_taps import add_skill_tap, list_skill_taps, remove_skill_tap
from opensquilla.cli.ui import console

skills_app = typer.Typer(help="Skill management - list, search, install, uninstall.")


def _install_result_payload(result: Any) -> dict[str, Any]:
    payload = dict(result) if isinstance(result, dict) else asdict(result)
    scan = payload.get("scan")
    if scan is None:
        payload.pop("scan", None)
    return payload


def _emit_skill_mutation_result(
    payload: dict[str, Any],
    *,
    json_output: bool,
    success_label: str,
    fallback_name: str,
) -> None:
    success = bool(payload.get("success", False))
    if json_output:
        print_json(payload)
        if not success:
            raise typer.Exit(1)
        return

    name = str(payload.get("name") or fallback_name)
    message = str(payload.get("message") or "")
    if success:
        path = payload.get("path")
        suffix = f" -> {path}" if path else ""
        console.print(f"[green]{success_label}:[/] {name}{suffix}")
        if message:
            console.print(message)
        return

    console.print(f"[red]Failed:[/] {message or name}")
    raise typer.Exit(1)


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
            _emit_skill_mutation_result(
                payload,
                json_output=json_output,
                success_label="Installed",
                fallback_name=identifier,
            )
            return

        if not json_output:
            console.print(f"Installing '{identifier}' from {source}...")
        outcome = await run_local_skill_install(
            identifier,
            source=source,
            force=force,
        )
        if outcome.unavailable_message:
            _emit_skill_mutation_result(
                {"success": False, "message": outcome.unavailable_message},
                json_output=json_output,
                success_label="Installed",
                fallback_name=identifier,
            )
            return

        result = outcome.result
        if result is None:
            _emit_skill_mutation_result(
                {"success": False, "message": "No skill install result returned"},
                json_output=json_output,
                success_label="Installed",
                fallback_name=identifier,
            )
            return

        if json_output:
            print_json(_install_result_payload(result))
            if not result.success:
                raise typer.Exit(1)
            return

        if result.success:
            console.print(f"[green]Installed:[/] {result.name} → {result.path}")
            if result.scan and result.scan.verdict != "safe":
                scan = result.scan
                console.print(
                    f"[yellow]Security: {scan.verdict} ({len(scan.findings)} findings)[/]"
                )
        else:
            console.print(f"[red]Failed:[/] {result.message}")
            raise typer.Exit(1)

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
            _emit_skill_mutation_result(
                payload,
                json_output=json_output,
                success_label="Uninstalled",
                fallback_name=name,
            )
            return

        outcome = await run_local_skill_uninstall(name)
        if outcome.unavailable_message:
            _emit_skill_mutation_result(
                {"success": False, "message": outcome.unavailable_message},
                json_output=json_output,
                success_label="Uninstalled",
                fallback_name=name,
            )
            return

        result = outcome.result
        if result is None:
            _emit_skill_mutation_result(
                {"success": False, "message": "No skill uninstall result returned"},
                json_output=json_output,
                success_label="Uninstalled",
                fallback_name=name,
            )
            return

        if json_output:
            print_json(_install_result_payload(result))
            if not result.success:
                raise typer.Exit(1)
            return

        if result.success:
            console.print(f"[green]Uninstalled:[/] {result.name}")
        else:
            console.print(f"[red]Failed:[/] {result.message}")
            raise typer.Exit(1)

    asyncio.run(_uninstall())


# ── Tap sub-commands ──────────────────────────────────────────────────────

tap_app = typer.Typer(help="Manage custom skill source repositories (taps).")
skills_app.add_typer(tap_app, name="tap")


@tap_app.command("add")
def tap_add(owner_repo: str = typer.Argument(..., help="GitHub owner/repo")) -> None:
    """Add a custom skill source tap."""
    try:
        tap = add_skill_tap(owner_repo)
        console.print(f"[green]Added tap:[/] {tap.full_name} ({tap.url})")
    except ValueError as e:
        console.print(f"[red]Error:[/] {e}")


@tap_app.command("list")
def tap_list() -> None:
    """List registered taps."""
    taps = list_skill_taps()
    if not taps:
        console.print("[dim]No taps registered.[/]")
        return
    for t in taps:
        console.print(f"  {t.full_name}  {t.url}  (added {t.added_at})")


@tap_app.command("remove")
def tap_remove(owner_repo: str = typer.Argument(..., help="GitHub owner/repo")) -> None:
    """Remove a tap."""
    if remove_skill_tap(owner_repo):
        console.print(f"[green]Removed:[/] {owner_repo}")
    else:
        console.print(f"[yellow]Not found:[/] {owner_repo}")


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
