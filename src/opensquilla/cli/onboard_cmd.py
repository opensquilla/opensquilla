"""CLI: opensquilla onboard / configure."""

from __future__ import annotations

import typer

from opensquilla.cli.ui import (
    ACCENT,
    ACCENT_SOFT,
    banner_panel,
    console,
    error_console,
    markup_escape,
    warning_panel,
)
from opensquilla.onboarding.config_store import load_config
from opensquilla.onboarding.flow import (
    OnboardOptions,
    run_interactive_configure,
    run_interactive_onboard,
    run_noninteractive_provider_configure,
)
from opensquilla.onboarding.next_steps import env_reference_warnings, format_next_steps
from opensquilla.onboarding.status import get_onboarding_status


def _print_env_reference_warnings(config) -> None:
    for warning in env_reference_warnings(config):
        console.print(warning_panel(warning))


def onboard_command(
    provider: str = typer.Option("", "--provider"),
    model: str = typer.Option("", "--model"),
    api_key: str = typer.Option("", "--api-key"),
    api_key_env: str = typer.Option("", "--api-key-env"),
    base_url: str = typer.Option("", "--base-url"),
    router: str = typer.Option(
        "recommended",
        "--router",
        help="recommended | openrouter-mix | disabled",
    ),
    minimal: bool = typer.Option(False, "--minimal"),
    skip_channels: bool = typer.Option(False, "--skip-channels"),
    skip_search: bool = typer.Option(False, "--skip-search"),
    skip_image_generation: bool = typer.Option(False, "--skip-image-generation"),
    if_needed: bool = typer.Option(False, "--if-needed"),
) -> None:
    """Run first-run onboarding (interactive or non-interactive)."""
    if if_needed:
        cfg = load_config()
        status = get_onboarding_status(cfg)
        if status.has_config and status.llm_configured:
            console.print(
                f"[{ACCENT_SOFT}]◆[/] [bold]onboarding already complete[/]"
                " [dim]— nothing to do[/dim]"
            )
            raise typer.Exit(code=0)

    if provider:
        result = run_noninteractive_provider_configure(
            provider,
            {
                "model": model,
                "api_key": api_key,
                "api_key_env": api_key_env,
                "base_url": base_url,
                "router": router,
            },
        )
        console.print(
            banner_panel(
                "Provider Configured",
                f"{provider} · {result.path}",
            )
        )
        cfg = load_config(result.path)
        _print_env_reference_warnings(cfg)
        console.print(
            format_next_steps(cfg, config_path=result.path),
            markup=False,
            highlight=False,
        )
        return

    options = OnboardOptions(
        skip_channels=skip_channels,
        skip_search=skip_search,
        skip_image_generation=skip_image_generation,
        if_needed=if_needed,
        provider_id=provider or None,
        model=model or None,
        api_key=api_key or None,
        api_key_env=api_key_env or None,
        base_url=base_url or None,
        router_mode=router,
        minimal=minimal,
    )
    result = run_interactive_onboard(options)
    if "tty_required" in result.warnings:
        raise typer.Exit(code=2)
    console.print(
        banner_panel(
            "Onboarding Complete",
            str(result.path),
        )
    )
    cfg = load_config(result.path)
    _print_env_reference_warnings(cfg)
    console.print(
        format_next_steps(cfg, config_path=result.path),
        markup=False,
        highlight=False,
    )


def configure_command(
    section_arg: str = typer.Argument(
        "",
        help="provider | router | channels | search | image-generation | memory-embedding",
    ),
    section: str = typer.Option(
        "", "--section",
        help="provider | router | channels | search | image-generation | memory-embedding",
    ),
    provider: str = typer.Option("", "--provider"),
    model: str = typer.Option("", "--model"),
    api_key: str = typer.Option("", "--api-key"),
    api_key_env: str = typer.Option("", "--api-key-env"),
    base_url: str = typer.Option("", "--base-url"),
    router: str = typer.Option("", "--router", help="recommended | openrouter-mix | disabled"),
    search_provider: str = typer.Option("", "--search-provider"),
    max_results: int = typer.Option(5, "--max-results"),
    channel_type: str = typer.Option("", "--channel-type"),
    name: str = typer.Option("", "--name"),
    token: str = typer.Option("", "--token"),
    fields: list[str] = typer.Option(
        [], "--field", "-f", help="Repeatable key=value channel field."
    ),
    image_provider: str = typer.Option("", "--image-provider"),
    primary: str = typer.Option("", "--primary"),
    memory_provider: str = typer.Option("", "--memory-provider"),
    onnx_dir: str = typer.Option("", "--onnx-dir"),
) -> None:
    """Reconfigure a section (providers/channels/search/image-generation)."""
    selected = section or section_arg
    if selected:
        from opensquilla.onboarding.setup_engine import SetupEngine

        normalized = selected.strip().lower()
        try:
            if normalized in {"provider", "providers"} and provider:
                engine = SetupEngine()
                engine.apply(
                    "provider",
                    {
                        "providerId": provider,
                        "model": model,
                        "apiKey": api_key,
                        "apiKeyEnv": api_key_env,
                        "baseUrl": base_url,
                    },
                )
                result = engine.persist()
                console.print(
                    f"[bold {ACCENT}]◆[/] [bold]saved[/] "
                    f"[dim]→[/] [{ACCENT_SOFT}]{markup_escape(result.path)}[/]"
                )
                _print_env_reference_warnings(load_config(result.path))
                return
            if normalized == "router" and router:
                engine = SetupEngine()
                engine.apply("router", {"mode": router})
                result = engine.persist()
                console.print(
                    f"[bold {ACCENT}]◆[/] [bold]saved[/] "
                    f"[dim]→[/] [{ACCENT_SOFT}]{markup_escape(result.path)}[/]"
                )
                _print_env_reference_warnings(load_config(result.path))
                return
            if normalized == "search" and search_provider:
                engine = SetupEngine()
                engine.apply(
                    "search",
                    {
                        "providerId": search_provider,
                        "apiKey": api_key,
                        "apiKeyEnv": api_key_env,
                        "maxResults": max_results,
                    },
                )
                result = engine.persist()
                console.print(
                    f"[bold {ACCENT}]◆[/] [bold]saved[/] "
                    f"[dim]→[/] [{ACCENT_SOFT}]{markup_escape(result.path)}[/]"
                )
                _print_env_reference_warnings(load_config(result.path))
                return
            if normalized in {"channel", "channels"} and channel_type and name:
                from opensquilla.cli.channel_fields import (
                    apply_channel_token,
                    parse_channel_field_pairs,
                )

                engine = SetupEngine()
                entry = {"type": channel_type, "name": name}
                apply_channel_token(entry, channel_type, token)
                entry.update(parse_channel_field_pairs(fields, channel_type))
                engine.apply("channel", {"entry": entry})
                result = engine.persist()
                console.print(
                    f"[bold {ACCENT}]◆[/] [bold]saved[/] "
                    f"[dim]→[/] [{ACCENT_SOFT}]{markup_escape(result.path)}[/]"
                )
                return
            if normalized in {"image-generation", "image_generation"} and image_provider:
                engine = SetupEngine()
                engine.apply(
                    "image-generation",
                    {
                        "providerId": image_provider,
                        "primary": primary,
                        "apiKey": api_key,
                        "apiKeyEnv": api_key_env,
                        "baseUrl": base_url,
                        "enabled": True,
                    },
                )
                result = engine.persist()
                console.print(
                    f"[bold {ACCENT}]◆[/] [bold]saved[/] "
                    f"[dim]→[/] [{ACCENT_SOFT}]{markup_escape(result.path)}[/]"
                )
                return
            if normalized in {"memory-embedding", "memory_embedding"} and memory_provider:
                engine = SetupEngine()
                engine.apply(
                    "memory-embedding",
                    {
                        "providerId": memory_provider,
                        "model": model,
                        "apiKey": api_key,
                        "baseUrl": base_url,
                        "onnxDir": onnx_dir,
                    },
                )
                result = engine.persist()
                console.print(
                    f"[bold {ACCENT}]◆[/] [bold]saved[/] "
                    f"[dim]→[/] [{ACCENT_SOFT}]{markup_escape(result.path)}[/]"
                )
                return
        except (KeyError, TypeError, ValueError) as exc:
            error_console.print(f"[red]Error:[/red] {markup_escape(exc)}")
            raise typer.Exit(code=2) from exc

    interactive_result = run_interactive_configure(selected or None)
    if interactive_result is not None:
        console.print(
            f"[bold {ACCENT}]◆[/] [bold]saved[/] "
            f"[dim]→[/] [{ACCENT_SOFT}]{markup_escape(interactive_result.path)}[/]"
        )
