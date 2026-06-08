"""First-run configuration wizard."""

from __future__ import annotations

import questionary
import tomli_w
import typer

from opensquilla.cli import autostart
from opensquilla.cli.ui import console
from opensquilla.paths import default_opensquilla_home, default_profile_name


def _default_model_for_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "openrouter":
        return "deepseek/deepseek-v4-pro"
    if normalized == "deepseek":
        return "deepseek-v4-flash"
    if normalized == "minimax":
        return "minimax/MiniMax-M3"
    return "openai/gpt-4o-mini"


def run_init(*, autostart_register: bool = False) -> None:
    """Create a basic OpenSquilla home with env and config files.

    When ``autostart_register`` is True, register a per-profile logon
    autostart entry (Task Scheduler on Windows, LaunchAgent on macOS,
    systemd --user on Linux) after writing the env / config files.
    The dispatch is best-effort: failures are surfaced as console
    warnings and do not block init, because a typo'd host key in
    ``.env`` should not abort the wizard.
    """
    home = default_opensquilla_home()
    env_path = home / ".env"
    config_path = home / "config.toml"
    home.mkdir(parents=True, exist_ok=True)
    (home / "state").mkdir(parents=True, exist_ok=True)

    provider = questionary.select(
        "Choose provider:",
        choices=["openrouter", "openai", "anthropic", "deepseek", "minimax", "custom"],
        default="openrouter",
    ).ask()
    if not provider:
        raise typer.Exit(1)

    api_key = questionary.password("API key:").ask()
    if api_key is None:
        raise typer.Exit(1)

    default_model = questionary.text(
        "Default model:",
        default=_default_model_for_provider(provider),
    ).ask()
    if not default_model:
        raise typer.Exit(1)

    key_name = f"{provider.upper()}_API_KEY" if provider != "custom" else "OPENSQUILLA_LLM_API_KEY"
    existing_env = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = [line for line in existing_env.splitlines() if not line.startswith(f"{key_name}=")]
    lines.append(f"{key_name}={api_key}")
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    config = {
        "llm": {
            "provider": provider,
            "model": default_model,
        },
        "state_dir": str(home / "state"),
    }
    config_path.write_text(tomli_w.dumps(config), encoding="utf-8")

    console.print(f"[green]Wrote[/green] {env_path}")
    console.print(f"[green]Wrote[/green] {config_path}")
    console.print("[dim]Tip: enable shell completion with `opensquilla --install-completion`[/dim]")

    if autostart_register:
        _maybe_register_autostart(home)


def _maybe_register_autostart(home) -> None:
    """Register a per-profile logon autostart entry, best-effort."""
    profile = default_profile_name()
    try:
        result = autostart.register_logon_task(profile=profile, home=home)
    except autostart.AutostartError as exc:
        console.print(
            f"[yellow]Autostart registration skipped:[/yellow] {exc}"
        )
        return
    console.print(
        f"[green]Autostart registered:[/green] {result.summary()}"
    )


def init_command(
    autostart_register: bool = typer.Option(
        False,
        "--autostart/--no-autostart",
        help=(
            "Register a per-profile logon autostart entry on this host "
            "(Task Scheduler on Windows, LaunchAgent on macOS, "
            "systemd --user on Linux) after the env / config files are "
            "written. Off by default; requires the opensquilla "
            "executable on PATH."
        ),
    ),
) -> None:
    """Initialize a workspace.

    Deprecated: prefer ``opensquilla onboard`` for full provider/channel setup.
    Kept for compatibility with older scripts.
    """
    run_init(autostart_register=autostart_register)
