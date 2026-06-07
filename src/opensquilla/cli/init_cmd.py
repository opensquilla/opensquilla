"""First-run configuration wizard."""

from __future__ import annotations

import questionary
import tomli_w
import typer

from opensquilla.cli import autostart
from opensquilla.cli.ui import console
from opensquilla.paths import default_opensquilla_home, default_profile_name
from opensquilla.provider.registry import (
    UnknownProviderError,
    get_provider_spec,
)


def _default_model_for_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "openrouter":
        return "deepseek/deepseek-v4-pro"
    if normalized == "deepseek":
        return "deepseek-v4-flash"
    if normalized == "minimax":
        return "minimax/MiniMax-M3"
    # MiniMax variants: pick the bare model name (the OpenAI-compatible
    # endpoint at api.minimaxi.com/v1 expects `MiniMax-M3`, not the
    # OpenRouter-namespace form). The other variants' spec.env_key
    # decides whether we write the anthropic or openai adapter.
    if normalized in {"minimax_openai", "minimax_cn", "minimax_global"}:
        return "MiniMax-M3"
    return "openai/gpt-4o-mini"


def _env_key_name_for_provider(provider: str) -> str:
    """Return the canonical env-var name for the provider's API key.

    Looks the answer up in :data:`opensquilla.provider.registry` so a
    fleet init via ``init-all`` writes the same key name the runtime
    adapter is going to read. Falls back to ``f"{PROVIDER}_API_KEY"``
    only when the provider is unknown to the registry — by then
    ``persist_profile`` will already have raised and the caller is
    on its own.
    """
    if provider.strip().lower() == "custom":
        return "OPENSQUILLA_LLM_API_KEY"
    try:
        return get_provider_spec(provider).env_key
    except UnknownProviderError:
        return f"{provider.strip().upper()}_API_KEY"


def persist_profile(
    home,
    *,
    provider: str,
    api_key: str | None = None,
    api_key_env: str | None = None,
    model: str | None = None,
) -> None:
    """Write the per-profile .env, config.toml, and state directory.

    Pure (no questionary, no console) so non-interactive paths
    (``opensquilla profiles init-all`` and friends) can reuse it.
    Exactly one of ``api_key`` or ``api_key_env`` must be provided,
    except when the provider does not require an API key (e.g.
    ``ollama``, ``vllm``) — in that case both may be ``None``.
    ``api_key_env`` is the env-var name the gateway reads at
    runtime, so when it is supplied nothing is written into ``.env``.

    The persisted ``config.toml`` always carries the four fields
    the runtime adapter needs: ``provider``, ``model``,
    ``api_key_env`` (the env-var name), and ``base_url`` (the
    upstream HTTP root). Pulling ``api_key_env`` and ``base_url``
    from :class:`ProviderSpec` instead of leaving them blank is
    what keeps a freshly-initialised profile from looking
    "configured" while still failing every chat call (see
    issue #215 L1 audit: ``provider_ready`` does not require the
    env-var to be present, so the bug was silent).

    Raises ``ValueError`` if both or neither of ``api_key`` /
    ``api_key_env`` are given (when the provider requires a key),
    or if the provider is unknown to the registry.
    """
    spec = get_provider_spec(provider)  # raises UnknownProviderError if bogus
    requires_key = spec.requires_api_key()
    if requires_key and (api_key is None) == (api_key_env is None):
        raise ValueError("configure either api_key or api_key_env, not both")

    env_path = home / ".env"
    config_path = home / "config.toml"
    home.mkdir(parents=True, exist_ok=True)
    (home / "state").mkdir(parents=True, exist_ok=True)

    # Env-var name → always derive from the spec, never from the
    # caller's `api_key_env` (which is just a *label* they used to
    # pass the key in). Otherwise a fleet init that used the wrong
    # label would silently persist the wrong lookup name.
    env_var_name = spec.env_key
    existing_env = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = [
        line
        for line in existing_env.splitlines()
        if not line.startswith(f"{env_var_name}=")
    ]
    if api_key is not None:
        lines.append(f"{env_var_name}={api_key}")
    env_path.write_text(
        "\n".join(lines).rstrip() + "\n" if lines else "",
        encoding="utf-8",
    )

    selected_model = model or _default_model_for_provider(provider)
    llm_section: dict[str, object] = {
        "provider": provider,
        "model": selected_model,
    }
    # The runtime reads `api_key_env` first; write the canonical
    # name so a misnamed label can't strand a profile.
    if spec.requires_api_key():
        llm_section["api_key_env"] = env_var_name
    if spec.default_base_url:
        llm_section["base_url"] = spec.default_base_url
    config = {
        "llm": llm_section,
        "state_dir": str(home / "state"),
    }
    config_path.write_text(tomli_w.dumps(config), encoding="utf-8")


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

    persist_profile(
        home,
        provider=provider,
        api_key=api_key,
        model=default_model,
    )

    env_path = home / ".env"
    config_path = home / "config.toml"
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
