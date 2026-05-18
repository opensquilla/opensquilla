"""CLI commands for migration from external agent runtimes."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, cast

import typer

from opensquilla.cli.ui import console
from opensquilla.migration.hermes import (
    MIGRATION_OPTIONS as HERMES_MIGRATION_OPTIONS,
)
from opensquilla.migration.hermes import (
    MIGRATION_PRESETS as HERMES_MIGRATION_PRESETS,
)
from opensquilla.migration.hermes import (
    SKILL_CONFLICT_MODES as HERMES_SKILL_CONFLICT_MODES,
)
from opensquilla.migration.hermes import (
    HermesMigrationOptions,
    HermesMigrator,
    _is_valid_hermes_home,
)
from opensquilla.migration.openclaw import (
    MIGRATION_OPTIONS,
    MIGRATION_PRESETS,
    PERSONA_CONFLICT_MODES,
    SKILL_CONFLICT_MODES,
    MigrationOptions,
    OpenClawMigrator,
    _is_valid_openclaw_home,
)

migrate_app = typer.Typer(
    help="Migration helpers for external agent runtimes.",
    invoke_without_command=True,
    no_args_is_help=False,
)

_AUTO_DETECT_SOURCES: tuple[str, ...] = ("openclaw", "hermes")


def _split_csv(values: list[str] | None) -> tuple[str, ...]:
    parsed: list[str] = []
    for value in values or []:
        for part in value.split(","):
            normalized = part.strip()
            if normalized:
                parsed.append(normalized)
    return tuple(parsed)


def _stdin_is_tty() -> bool:
    """Indirection point so tests can simulate TTY vs non-TTY contexts.

    ``CliRunner`` swaps ``sys.stdin`` with a non-TTY buffer, so patching
    ``sys.stdin.isatty`` directly doesn't reach the callback. Tests
    monkeypatch this helper instead.
    """
    return sys.stdin.isatty()


def _detect_migration_sources() -> list[tuple[str, Path]]:
    """Discover known external homes on disk. Order is stable: openclaw, hermes.

    Returns (source_id, source_path) pairs for every external runtime
    whose default home is plausibly populated.
    """
    found: list[tuple[str, Path]] = []
    openclaw_home = Path.home() / ".openclaw"
    if _is_valid_openclaw_home(openclaw_home):
        found.append(("openclaw", openclaw_home))
    hermes_home = Path.home() / ".hermes"
    if _is_valid_hermes_home(hermes_home):
        found.append(("hermes", hermes_home))
    return found


def _prompt_source_selection(detected: list[tuple[str, Path]]) -> list[str]:
    """Interactive multi-select for which detected sources to migrate.

    Returns the list of selected source ids. Empty list means the user
    cancelled or selected nothing.
    """
    import questionary

    choices = [
        questionary.Choice(title=f"{name} ({path})", value=name, checked=True)
        for name, path in detected
    ]
    answer = questionary.checkbox(
        "Which migration sources should be imported into OpenSquilla?",
        choices=choices,
    ).ask()
    return list(answer or [])


def _run_one_migration(
    name: str,
    source_path: Path,
    *,
    config: Path | None,
    apply: bool,
    migrate_secrets: bool,
    overwrite: bool,
    preset: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    skill_conflict: str,
    persona_conflict: str,
    json_output: bool,
) -> dict[str, Any]:
    """Run a single migrator. Validation errors raise typer.Exit(2)."""
    if name == "openclaw":
        _reject_invalid_options(
            preset=preset,
            include=include,
            exclude=exclude,
            skill_conflict=skill_conflict,
            persona_conflict=persona_conflict,
        )
        options = MigrationOptions(
            source=source_path,
            config_path=config,
            apply=apply,
            migrate_secrets=migrate_secrets,
            overwrite=overwrite,
            preset=preset,
            include=include,
            exclude=exclude,
            skill_conflict=skill_conflict,  # type: ignore[arg-type]
            persona_conflict=persona_conflict,  # type: ignore[arg-type]
        )
        migrator: Any = OpenClawMigrator(options)
    elif name == "hermes":
        _reject_invalid_hermes_options(
            preset=preset,
            include=include,
            exclude=exclude,
            skill_conflict=skill_conflict,
        )
        hermes_options = HermesMigrationOptions(
            source=source_path,
            config_path=config,
            apply=apply,
            migrate_secrets=migrate_secrets,
            overwrite=overwrite,
            preset=preset,
            include=include,
            exclude=exclude,
            skill_conflict=skill_conflict,  # type: ignore[arg-type]
        )
        migrator = HermesMigrator(hermes_options)
    else:  # pragma: no cover - guarded earlier
        raise typer.Exit(2)

    if json_output:
        with contextlib.redirect_stdout(io.StringIO()):
            return cast(dict[str, Any], migrator.migrate())
    return cast(dict[str, Any], migrator.migrate())


@migrate_app.callback()
def migrate_root(
    ctx: typer.Context,
    source: list[str] | None = typer.Option(
        None,
        "--source",
        help=(
            "Comma-separated source ids to migrate when auto-detecting: "
            "openclaw, hermes. Required when both are found and stdin is "
            "not a TTY."
        ),
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="OpenSquilla config path to write or preview.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply the migration. Without this flag, only a dry-run report is produced.",
    ),
    migrate_secrets: bool = typer.Option(
        False,
        "--migrate-secrets",
        help="Copy recognized secrets. Defaults to false.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite target workspace files after making item-level backups.",
    ),
    preset: str = typer.Option(
        "full",
        "--preset",
        help="Migration preset: user-data or full.",
    ),
    include: list[str] | None = typer.Option(
        None,
        "--include",
        help="Comma-separated migration option ids to include.",
    ),
    exclude: list[str] | None = typer.Option(
        None,
        "--exclude",
        help="Comma-separated migration option ids to exclude.",
    ),
    skill_conflict: str = typer.Option(
        "skip",
        "--skill-conflict",
        help="Skill conflict behavior: skip, overwrite, or rename.",
    ),
    persona_conflict: str = typer.Option(
        "prompt",
        "--persona-conflict",
        help=(
            "How to resolve SOUL/USER/AGENTS conflicts (openclaw only). "
            "Options: prompt (default), use-opensquilla, use-openclaw, "
            "merge, or skip."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Auto-detect external runtimes under the user's home and migrate them.

    Subcommands (``migrate openclaw``, ``migrate hermes``) still work as
    before with explicit source paths. Calling ``opensquilla migrate``
    with no subcommand scans ``~/.openclaw`` and ``~/.hermes``, then
    either prompts the user to pick which to import (TTY) or prints the
    discovered sources and asks for ``--source`` (non-TTY, ``--json``).
    """
    if ctx.invoked_subcommand is not None:
        return

    detected = _detect_migration_sources()
    detected_names = [name for name, _ in detected]

    if not detected:
        payload = {
            "detected": [],
            "message": (
                "No migration source detected. Checked default paths: "
                f"{Path.home() / '.openclaw'}, {Path.home() / '.hermes'}. "
                "Use `opensquilla migrate openclaw --source <path>` or "
                "`opensquilla migrate hermes --source <path>` to point "
                "at a non-default home."
            ),
        }
        if json_output:
            typer.echo(json.dumps(payload, ensure_ascii=False))
        else:
            console.print(payload["message"])
        raise typer.Exit(0)

    source_filter = _split_csv(source)
    if source_filter:
        unknown = sorted(set(source_filter) - set(_AUTO_DETECT_SOURCES))
        if unknown:
            typer.echo(
                f"Unknown migration source: {', '.join(unknown)} "
                f"(known: {', '.join(_AUTO_DETECT_SOURCES)})"
            )
            raise typer.Exit(2)
        missing = sorted(set(source_filter) - set(detected_names))
        if missing:
            typer.echo(
                f"Requested source not detected: {', '.join(missing)}. "
                f"Found: {', '.join(detected_names) or '(none)'}"
            )
            raise typer.Exit(2)
        selected = [name for name in _AUTO_DETECT_SOURCES if name in source_filter]
    elif len(detected) == 1:
        # Single source found: just run it, no need to ask.
        selected = detected_names
    else:
        # Multiple sources, no explicit filter. TTY: prompt. Non-TTY: list and exit.
        stdin_is_tty = _stdin_is_tty()
        if not stdin_is_tty or json_output:
            selection_payload: dict[str, Any] = {
                "detected": [
                    {"name": name, "path": str(path)} for name, path in detected
                ],
                "message": (
                    "Multiple migration sources detected. Re-run with "
                    "`--source <names>` to select. Example: "
                    f"`opensquilla migrate --source {','.join(detected_names)} --apply`"
                ),
            }
            if json_output:
                typer.echo(json.dumps(selection_payload, ensure_ascii=False))
            else:
                console.print(selection_payload["message"])
                console.print("[dim]Detected sources:[/dim]")
                for name, path in detected:
                    console.print(f"  - {name}: {path}")
            raise typer.Exit(0)
        selected = _prompt_source_selection(detected)
        if not selected:
            console.print("No source selected; nothing to do.")
            raise typer.Exit(0)

    include_options = _split_csv(include)
    exclude_options = _split_csv(exclude)
    # Validate every selected migrator's options BEFORE running any of
    # them, so a bad ``--include`` flag for hermes never half-applies
    # openclaw first and then bails out partway through the batch.
    for name in selected:
        if name == "openclaw":
            _reject_invalid_options(
                preset=preset,
                include=include_options,
                exclude=exclude_options,
                skill_conflict=skill_conflict,
                persona_conflict=persona_conflict,
            )
        elif name == "hermes":
            _reject_invalid_hermes_options(
                preset=preset,
                include=include_options,
                exclude=exclude_options,
                skill_conflict=skill_conflict,
            )

    detected_by_name = dict(detected)
    reports: dict[str, dict[str, Any]] = {}
    has_error = False
    for name in selected:
        report = _run_one_migration(
            name,
            detected_by_name[name],
            config=config,
            apply=apply,
            migrate_secrets=migrate_secrets,
            overwrite=overwrite,
            preset=preset,
            include=include_options,
            exclude=exclude_options,
            skill_conflict=skill_conflict,
            persona_conflict=persona_conflict,
            json_output=json_output,
        )
        reports[name] = report
        if any(item.get("status") == "error" for item in report.get("items", [])):
            has_error = True

    if json_output:
        typer.echo(
            json.dumps(
                {"selected": selected, "reports": reports},
                ensure_ascii=False,
            )
        )
    else:
        mode = "applied" if apply else "dry-run"
        for name in selected:
            console.print(f"[green]{name} migration complete[/green] ({mode})")
            console.print(f"[dim]Report:[/dim] {reports[name]['output_dir']}")

    if has_error:
        raise typer.Exit(1)


def _reject_invalid_options(
    *,
    preset: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    skill_conflict: str,
    persona_conflict: str | None = None,
) -> None:
    if preset not in MIGRATION_PRESETS:
        typer.echo(f"Unknown migration preset: {preset}")
        raise typer.Exit(2)
    unknown_include = sorted(set(include) - MIGRATION_OPTIONS)
    if unknown_include:
        typer.echo(f"Unknown migration option in include: {', '.join(unknown_include)}")
        raise typer.Exit(2)
    unknown_exclude = sorted(set(exclude) - MIGRATION_OPTIONS)
    if unknown_exclude:
        typer.echo(f"Unknown migration option in exclude: {', '.join(unknown_exclude)}")
        raise typer.Exit(2)
    if skill_conflict not in SKILL_CONFLICT_MODES:
        typer.echo(f"Unknown skill conflict behavior: {skill_conflict}")
        raise typer.Exit(2)
    if persona_conflict is not None and persona_conflict not in PERSONA_CONFLICT_MODES:
        typer.echo(f"Unknown persona conflict behavior: {persona_conflict}")
        raise typer.Exit(2)


def _reject_invalid_hermes_options(
    *,
    preset: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    skill_conflict: str,
) -> None:
    if preset not in HERMES_MIGRATION_PRESETS:
        typer.echo(f"Unknown Hermes migration preset: {preset}")
        raise typer.Exit(2)
    unknown_include = sorted(set(include) - HERMES_MIGRATION_OPTIONS)
    if unknown_include:
        typer.echo(f"Unknown Hermes migration option in include: {', '.join(unknown_include)}")
        raise typer.Exit(2)
    unknown_exclude = sorted(set(exclude) - HERMES_MIGRATION_OPTIONS)
    if unknown_exclude:
        typer.echo(f"Unknown Hermes migration option in exclude: {', '.join(unknown_exclude)}")
        raise typer.Exit(2)
    if skill_conflict not in HERMES_SKILL_CONFLICT_MODES:
        typer.echo(f"Unknown Hermes skill conflict behavior: {skill_conflict}")
        raise typer.Exit(2)


@migrate_app.command("openclaw")
def migrate_openclaw(
    source: Path = typer.Option(
        Path.home() / ".openclaw",
        "--source",
        help="OpenClaw home directory.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="OpenSquilla config path to write or preview.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply the migration. Without this flag, only a dry-run report is produced.",
    ),
    migrate_secrets: bool = typer.Option(
        False,
        "--migrate-secrets",
        help="Copy recognized secrets. Defaults to false.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite target workspace files after making item-level backups.",
    ),
    preset: str = typer.Option(
        "full",
        "--preset",
        help="Migration preset: user-data or full.",
    ),
    include: list[str] | None = typer.Option(
        None,
        "--include",
        help="Comma-separated migration option ids to include.",
    ),
    exclude: list[str] | None = typer.Option(
        None,
        "--exclude",
        help="Comma-separated migration option ids to exclude.",
    ),
    skill_conflict: str = typer.Option(
        "skip",
        "--skill-conflict",
        help="Skill conflict behavior: skip, overwrite, or rename.",
    ),
    persona_conflict: str = typer.Option(
        "prompt",
        "--persona-conflict",
        help=(
            "How to resolve SOUL/USER/AGENTS conflicts when the destination "
            "already holds real user content: prompt (interactive, default), "
            "use-opensquilla, use-openclaw, merge, or skip."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Migrate OpenClaw state into OpenSquilla-native files."""

    include_options = _split_csv(include)
    exclude_options = _split_csv(exclude)
    _reject_invalid_options(
        preset=preset,
        include=include_options,
        exclude=exclude_options,
        skill_conflict=skill_conflict,
        persona_conflict=persona_conflict,
    )
    options = MigrationOptions(
        source=source,
        config_path=config,
        apply=apply,
        migrate_secrets=migrate_secrets,
        overwrite=overwrite,
        preset=preset,
        include=include_options,
        exclude=exclude_options,
        skill_conflict=skill_conflict,  # type: ignore[arg-type]
        persona_conflict=persona_conflict,  # type: ignore[arg-type]
    )
    if json_output:
        with contextlib.redirect_stdout(io.StringIO()):
            report = OpenClawMigrator(options).migrate()
    else:
        report = OpenClawMigrator(options).migrate()
    has_error = any(item.get("status") == "error" for item in report.get("items", []))
    if json_output:
        typer.echo(json.dumps(report, ensure_ascii=False))
    else:
        mode = "applied" if apply else "dry-run"
        console.print(f"[green]OpenClaw migration complete[/green] ({mode})")
        console.print(f"[dim]Report:[/dim] {report['output_dir']}")
    if has_error:
        raise typer.Exit(1)


@migrate_app.command("hermes")
def migrate_hermes(
    source: Path | None = typer.Option(
        None,
        "--source",
        help="Hermes home directory.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Hermes profile name under ~/.hermes/profiles.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="OpenSquilla config path to write or preview.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply the migration. Without this flag, only a dry-run report is produced.",
    ),
    migrate_secrets: bool = typer.Option(
        False,
        "--migrate-secrets",
        help="Copy recognized secrets. Defaults to false.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite target workspace files after making item-level backups.",
    ),
    preset: str = typer.Option(
        "full",
        "--preset",
        help="Migration preset: user-data or full.",
    ),
    include: list[str] | None = typer.Option(
        None,
        "--include",
        help="Comma-separated migration option ids to include.",
    ),
    exclude: list[str] | None = typer.Option(
        None,
        "--exclude",
        help="Comma-separated migration option ids to exclude.",
    ),
    skill_conflict: str = typer.Option(
        "skip",
        "--skill-conflict",
        help="Skill conflict behavior: skip, overwrite, or rename.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Migrate Hermes Agent state into OpenSquilla-native files."""

    include_options = _split_csv(include)
    exclude_options = _split_csv(exclude)
    _reject_invalid_hermes_options(
        preset=preset,
        include=include_options,
        exclude=exclude_options,
        skill_conflict=skill_conflict,
    )
    options = HermesMigrationOptions(
        source=source,
        profile=profile,
        config_path=config,
        apply=apply,
        migrate_secrets=migrate_secrets,
        overwrite=overwrite,
        preset=preset,
        include=include_options,
        exclude=exclude_options,
        skill_conflict=skill_conflict,  # type: ignore[arg-type]
    )
    if json_output:
        with contextlib.redirect_stdout(io.StringIO()):
            report = HermesMigrator(options).migrate()
    else:
        report = HermesMigrator(options).migrate()
    has_error = any(item.get("status") == "error" for item in report.get("items", []))
    if json_output:
        typer.echo(json.dumps(report, ensure_ascii=False))
    else:
        mode = "applied" if apply else "dry-run"
        console.print(f"[green]Hermes migration complete[/green] ({mode})")
        console.print(f"[dim]Report:[/dim] {report['output_dir']}")
    if has_error:
        raise typer.Exit(1)
