"""CLI commands for migration from external agent runtimes."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import datetime
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
from opensquilla.migration.opensquilla_home import (
    OPENSQUILLA_SOURCE_KINDS,
    OpenSquillaHomeMigrator,
    OpenSquillaMigrationOptions,
    PortableCandidate,
    detect_legacy_cli_home,
    enumerate_portable_homes,
    is_valid_opensquilla_home,
)
from opensquilla.paths import default_opensquilla_home

migrate_app = typer.Typer(
    help="Migration helpers for legacy OpenSquilla homes and external agent runtimes.",
    invoke_without_command=True,
    no_args_is_help=False,
)

_AUTO_DETECT_SOURCES: tuple[str, ...] = ("opensquilla", "openclaw", "hermes")


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
    """Discover importable homes on disk. Order: opensquilla, openclaw, hermes.

    Returns (source_id, source_path) pairs for every runtime whose default
    home is plausibly populated. The legacy OpenSquilla CLI home is offered
    only when it is not the active home (a plain CLI user must never see
    their own live home as a migration source).
    """
    found: list[tuple[str, Path]] = []
    legacy_home = detect_legacy_cli_home(default_opensquilla_home())
    if legacy_home is not None:
        found.append(("opensquilla", legacy_home))
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
    if name == "opensquilla":
        _reject_invalid_opensquilla_options(
            config=config,
            preset=preset,
            include=include,
            exclude=exclude,
        )
        opensquilla_options = OpenSquillaMigrationOptions(
            source=source_path,
            kind="cli-home",
            config_path=config,
            apply=apply,
            overwrite=overwrite,
        )
        migrator: Any = OpenSquillaHomeMigrator(opensquilla_options)
    elif name == "openclaw":
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
        migrator = OpenClawMigrator(options)
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
            "opensquilla, openclaw, hermes. Required when several are found "
            "and stdin is not a TTY."
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
    """Auto-detect importable homes under the user's home and migrate them.

    Subcommands (``migrate opensquilla``, ``migrate openclaw``,
    ``migrate hermes``) still work as before with explicit source paths.
    Calling ``opensquilla migrate`` with no subcommand scans the legacy
    ``~/.opensquilla`` CLI home (only when it is not the active home),
    ``~/.openclaw``, and ``~/.hermes``, then either prompts the user to
    pick which to import (TTY) or prints the discovered sources and asks
    for ``--source`` (non-TTY, ``--json``).
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
                f"{Path.home() / '.opensquilla'}, {Path.home() / '.openclaw'}, "
                f"{Path.home() / '.hermes'}. "
                "Use `opensquilla migrate opensquilla --source <path>`, "
                "`opensquilla migrate openclaw --source <path>`, or "
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
        if name == "opensquilla":
            _reject_invalid_opensquilla_options(
                config=config,
                preset=preset,
                include=include_options,
                exclude=exclude_options,
            )
        elif name == "openclaw":
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
            output_dir = str(reports[name].get("output_dir") or "")
            if output_dir:
                console.print(f"[dim]Report:[/dim] {output_dir}")

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


def _reject_invalid_opensquilla_options(
    *,
    config: Path | None,
    preset: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> None:
    # The self-migration is a whole-home copy with no per-item option
    # surface; only the shared defaults are accepted silently.
    if preset not in ("", "full") or include or exclude:
        typer.echo("opensquilla source does not take preset/include/exclude")
        raise typer.Exit(2)
    if config is not None:
        typer.echo(
            "--config is not supported for OpenSquilla self-migration. "
            "Set OPENSQUILLA_STATE_DIR to the target home and re-run without --config."
        )
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


def _describe_portable_candidate(candidate: PortableCandidate) -> str:
    era = candidate.era_hint or "unknown era"
    last_used = datetime.fromtimestamp(candidate.last_used).isoformat(timespec="seconds")
    return f"{candidate.path} ({era}, last used {last_used}, {candidate.size_bytes} bytes)"


def _prompt_portable_home(candidates: list[PortableCandidate]) -> Path:
    import questionary

    choices = [
        questionary.Choice(
            title=f"{index}. {_describe_portable_candidate(candidate)}",
            value=str(candidate.path),
        )
        for index, candidate in enumerate(candidates, start=1)
    ]
    answer = questionary.select(
        "Which portable OpenSquilla home should be imported?",
        choices=choices,
    ).ask()
    if not answer:
        raise typer.Exit(0)
    return Path(answer)


def _resolve_portable_source(home: Path | None, *, json_output: bool) -> Path:
    """Resolve the portable source home for ``--kind windows-portable``."""
    candidates = enumerate_portable_homes()
    if home is not None:
        selected = Path(home).expanduser()
        for candidate in candidates:
            try:
                if candidate.path.resolve() == selected.resolve():
                    return candidate.path
            except OSError:
                continue
        if is_valid_opensquilla_home(selected):
            return selected
        typer.echo(f"--home does not point at a portable OpenSquilla home: {selected}")
        raise typer.Exit(2)
    if len(candidates) == 1:
        return candidates[0].path
    if not candidates:
        typer.echo(
            "No portable OpenSquilla homes were found under LOCALAPPDATA/TEMP. "
            "Pass --source <path> to point at one explicitly."
        )
        raise typer.Exit(2)
    if json_output or not _stdin_is_tty():
        lines = ["Multiple portable OpenSquilla homes found; re-run with --home <path>:"]
        lines.extend(f"  - {_describe_portable_candidate(candidate)}" for candidate in candidates)
        typer.echo("\n".join(lines))
        raise typer.Exit(2)
    return _prompt_portable_home(candidates)


@migrate_app.command("opensquilla")
def migrate_opensquilla(
    source: Path | None = typer.Option(
        None,
        "--source",
        help="Legacy OpenSquilla home directory (any kind).",
    ),
    kind: str = typer.Option(
        "cli-home",
        "--kind",
        help="Source kind: cli-home, windows-portable, or desktop-home.",
    ),
    home: Path | None = typer.Option(
        None,
        "--home",
        help="Select one enumerated portable home (windows-portable only).",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="OpenSquilla config path to write or preview.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply/--dry-run",
        help="Apply the migration. Without this flag, only a dry-run report is produced.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite a non-empty target home after taking timestamped backups.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Import a legacy OpenSquilla home (CLI, Windows portable, or desktop)."""

    if config is not None:
        typer.echo(
            "--config is not supported for OpenSquilla self-migration. "
            "Set OPENSQUILLA_STATE_DIR to the target home and re-run without --config."
        )
        raise typer.Exit(2)
    if kind not in OPENSQUILLA_SOURCE_KINDS:
        typer.echo(
            f"Unknown source kind: {kind} (known: {', '.join(OPENSQUILLA_SOURCE_KINDS)})"
        )
        raise typer.Exit(2)
    if home is not None and source is not None:
        typer.echo("Pass either --source or --home, not both.")
        raise typer.Exit(2)
    if home is not None and kind != "windows-portable":
        typer.echo("--home applies to --kind windows-portable only; use --source instead.")
        raise typer.Exit(2)
    source_path = source
    if source_path is None and kind == "windows-portable":
        source_path = _resolve_portable_source(home, json_output=json_output)

    options = OpenSquillaMigrationOptions(
        source=source_path,
        kind=kind,
        config_path=config,
        apply=apply,
        overwrite=overwrite,
    )
    if json_output:
        with contextlib.redirect_stdout(io.StringIO()):
            report = OpenSquillaHomeMigrator(options).migrate()
    else:
        report = OpenSquillaHomeMigrator(options).migrate()
    has_error = any(item.get("status") == "error" for item in report.get("items", []))
    if json_output:
        typer.echo(json.dumps(report, ensure_ascii=False))
    else:
        mode = "applied" if apply else "dry-run"
        counts: dict[str, int] = {}
        for item in report.get("items", []):
            status = str(item.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        if has_error:
            console.print(f"[red]OpenSquilla self-migration failed[/red] ({mode})")
        else:
            console.print(f"[green]OpenSquilla self-migration complete[/green] ({mode})")
        if counts:
            summary = ", ".join(f"{status}: {count}" for status, count in sorted(counts.items()))
            console.print(f"[dim]Items:[/dim] {summary}")
        paused = report.get("paused_jobs") or []
        if paused:
            console.print(
                f"[dim]Scheduler:[/dim] {len(paused)} imported job(s) arrive paused; "
                "review them with `opensquilla cron list`."
            )
        output_dir = str(report.get("output_dir") or "")
        if output_dir:
            console.print(f"[dim]Report:[/dim] {output_dir}")
    if has_error:
        raise typer.Exit(1)


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
