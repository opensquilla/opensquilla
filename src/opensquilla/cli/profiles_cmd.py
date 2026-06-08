"""CLI: opensquilla profiles <subcommand>.

Profile-level batch operations that complement the per-profile
``opensquilla --profile <name> init`` wizard. The headline command
is ``opensquilla profiles init-all``: scan every profile directory
under ``$OPENSQUILLA_HOME/profiles/``, and for each profile that has
not been initialised yet (no ``.env`` / ``config.toml`` pair), write
the same provider / API-key / model triple the user supplies on the
command line, then register the per-profile logon autostart entry
(issue #193 dispatcher). Profiles that already have a ``.env`` are
skipped — re-running the command is idempotent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import typer
from rich.table import Table

from opensquilla.cli import autostart
from opensquilla.cli.init_cmd import persist_profile
from opensquilla.cli.ui import ACCENT, ACCENT_SOFT, console, markup_escape
from opensquilla.paths import default_profiles_root, is_valid_profile_name

profiles_app = typer.Typer(
    help=(
        "Profile-level batch operations: discover profiles, "
        "initialize every profile in one go, list autostart targets."
    ),
)


@dataclass(frozen=True)
class ProfileTarget:
    """A profile discovered under $OPENSQUILLA_HOME/profiles/."""

    name: str
    home: Path
    initialised: bool  # True when both .env and config.toml are present


def _discover_profiles(profiles_root: Path) -> list[ProfileTarget]:
    """Return every subdirectory of ``profiles_root`` that is a valid profile.

    Subdirectories whose name fails the profile-name regex are
    skipped, because the home resolver would reject them too. A
    profile is reported as "initialised" only when both ``.env`` and
    ``config.toml`` are present; a partial directory (only one of
    the two) is reported as not initialised so the init wizard
    repairs it.
    """
    if not profiles_root.is_dir():
        return []
    targets: list[ProfileTarget] = []
    for child in sorted(profiles_root.iterdir()):
        if not child.is_dir():
            continue
        if not is_valid_profile_name(child.name):
            continue
        has_env = (child / ".env").is_file()
        has_cfg = (child / "config.toml").is_file()
        targets.append(
            ProfileTarget(
                name=child.name,
                home=child,
                initialised=has_env and has_cfg,
            )
        )
    return targets


def _initialise_one(
    target: ProfileTarget,
    *,
    provider: str,
    api_key: str | None,
    api_key_env: str | None,
    model: str | None,
    autostart_register: bool,
) -> tuple[bool, str]:
    """Initialise a single profile in-place.

    Returns ``(ok, detail)`` where ``detail`` is the autostart summary
    or the failure reason. Errors are caught and surfaced as
    ``(False, str)`` so a partial failure does not abort the loop.
    """
    if target.initialised:
        return True, "skipped (already initialised)"

    try:
        persist_profile(
            target.home,
            provider=provider,
            api_key=api_key,
            api_key_env=api_key_env,
            model=model,
        )
    except OSError as exc:
        return False, f"write failed: {exc}"

    if not autostart_register:
        return True, "wrote .env + config.toml"

    try:
        result = autostart.register_logon_task(
            profile=target.name, home=target.home
        )
    except autostart.AutostartError as exc:
        return True, f"wrote .env + config.toml; autostart skipped: {exc}"
    return True, result.summary()


@profiles_app.command("list")
def profiles_list() -> None:
    """List every profile under $OPENSQUILLA_HOME/profiles/ with state."""
    profiles_root = default_profiles_root()
    targets = _discover_profiles(profiles_root)
    if not targets:
        console.print(
            f"[dim]No profiles found under {markup_escape(str(profiles_root))}[/dim]"
        )
        return
    table = Table(title=f"Profiles under {profiles_root}")
    table.add_column("profile", no_wrap=True)
    table.add_column("state")
    table.add_column("home")
    for t in targets:
        state = (
            f"[{ACCENT}]◆[/] ready" if t.initialised else "[yellow]uninitialised[/]"
        )
        table.add_row(
            t.name,
            state,
            markup_escape(str(t.home)),
        )
    console.print(table)


@profiles_app.command("init-all")
def profiles_init_all(
    provider: str = typer.Option(
        ...,
        "--provider",
        help="Provider id applied to every profile (openrouter, openai, anthropic, deepseek, minimax, custom).",
    ),
    api_key: str = typer.Option(
        "",
        "--api-key",
        help="Provider API key written into each profile's .env. Mutually exclusive with --api-key-env.",
    ),
    api_key_env: str = typer.Option(
        "",
        "--api-key-env",
        help=(
            "Env-var name the gateway should read the provider key from "
            "(e.g. OPENROUTER_API_KEY). The env-var is read at "
            "runtime; nothing is written into .env."
        ),
    ),
    model: str = typer.Option(
        "",
        "--model",
        help="Override the model id. Defaults to the provider's recommended model.",
    ),
    autostart_register: bool = typer.Option(
        True,
        "--autostart/--no-autostart",
        help=(
            "Register a per-profile logon autostart entry on this host "
            "after writing the env / config files. On by default; "
            "errors are surfaced per-profile and do not abort the loop."
        ),
    ),
    only_uninitialised: bool = typer.Option(
        True,
        "--only-uninitialised/--all",
        help=(
            "Skip profiles that already have a .env + config.toml "
            "(the default). Pass --all to re-write every profile."
        ),
    ),
    profiles_root: Path | None = typer.Option(
        None,
        "--profiles-root",
        help="Override the profiles root. Defaults to $OPENSQUILLA_HOME/profiles.",
    ),
) -> None:
    """Initialise every profile in $OPENSQUILLA_HOME/profiles/.

    Iterates over each profile directory and writes the same
    provider / API-key / model triple to every profile that has not
    been initialised yet. Already-initialised profiles are skipped
    unless --all is passed. Autostart registration is best-effort
    per profile; a failure on one profile is logged and the loop
    continues.
    """
    if (api_key and api_key_env) or (not api_key and not api_key_env):
        console.print(
            "[red]Provide exactly one of --api-key or --api-key-env.[/red]"
        )
        raise typer.Exit(code=2)
    if not provider:
        console.print("[red]--provider is required.[/red]")
        raise typer.Exit(code=2)

    root = profiles_root or default_profiles_root()
    targets = _discover_profiles(root)
    if not targets:
        console.print(
            f"[yellow]No profiles found under {markup_escape(str(root))}.[/yellow] "
            f"Create profile directories first "
            f"(e.g. `mkdir -p {root}/coder`)."
        )
        raise typer.Exit(code=1)

    if only_uninitialised:
        targets = [t for t in targets if not t.initialised]
    if not targets:
        console.print(
            f"[{ACCENT_SOFT}]◆[/] All profiles already initialised; nothing to do."
        )
        return

    table = Table(title=f"Initialising {len(targets)} profile(s) under {root}")
    table.add_column("profile", no_wrap=True)
    table.add_column("state")
    table.add_column("detail")
    for t in targets:
        ok, detail = _initialise_one(
            t,
            provider=provider,
            api_key=api_key or None,
            api_key_env=api_key_env or None,
            model=model or None,
            autostart_register=autostart_register,
        )
        state = f"[{ACCENT}]◆[/] ok" if ok else "[red]failed[/red]"
        table.add_row(t.name, state, markup_escape(detail))
    console.print(table)
