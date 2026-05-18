"""CLI: opensquilla onboard / configure."""

from __future__ import annotations

import json as _json

import typer
from rich.table import Table

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
from opensquilla.onboarding.section_status import SectionStatus
from opensquilla.onboarding.status import OnboardingStatus, get_onboarding_status

_STATUS_BLOCKING = {SectionStatus.MISSING, SectionStatus.DEGRADED, SectionStatus.UNKNOWN}


def _print_env_reference_warnings(config) -> None:
    for warning in env_reference_warnings(config):
        console.print(warning_panel(warning))


def _print_saved_path(path: object) -> None:
    console.print(
        f"[bold {ACCENT}]◆[/] [bold]saved[/] "
        f"[dim]→[/] [{ACCENT_SOFT}]{markup_escape(path)}[/]",
        soft_wrap=True,
    )


def _format_missing_sections(status: OnboardingStatus) -> str:
    parts = [
        f"{name} ({state.value})"
        for name, state in status.sections.items()
        if state in _STATUS_BLOCKING
    ]
    return ", ".join(parts) if parts else "none"


onboard_app = typer.Typer(
    help="Run or inspect OpenSquilla onboarding.",
    invoke_without_command=True,
    no_args_is_help=False,
)


@onboard_app.callback(invoke_without_command=True)
def onboard_command(
    ctx: typer.Context,
    provider: str = typer.Option("", "--provider"),
    model: str = typer.Option("", "--model"),
    api_key: str = typer.Option("", "--api-key"),
    api_key_env: str = typer.Option("", "--api-key-env"),
    base_url: str = typer.Option("", "--base-url"),
    router: str = typer.Option(
        "recommended",
        "--router",
        metavar="MODE",
        help="Router profile: recommended, openrouter-mix, or disabled.",
    ),
    minimal: bool = typer.Option(False, "--minimal"),
    skip_channels: bool = typer.Option(False, "--skip-channels"),
    skip_search: bool = typer.Option(False, "--skip-search"),
    skip_image_generation: bool = typer.Option(False, "--skip-image-generation"),
    if_needed: bool = typer.Option(False, "--if-needed"),
) -> None:
    """Run first-run onboarding (interactive or non-interactive)."""
    if ctx.invoked_subcommand is not None:
        # ``opensquilla onboard <subcommand>`` was invoked; let the subcommand
        # handler take over instead of running the interactive flow.
        return
    if if_needed:
        cfg = load_config()
        status = get_onboarding_status(cfg)
        if status.has_config and not status.needs_onboarding:
            console.print(
                f"[{ACCENT_SOFT}]◆[/] [bold]onboarding already complete[/]"
                " [dim]— nothing to do[/dim]"
            )
            raise typer.Exit(code=0)
        # Tell the operator what is still pending so it is obvious why the
        # idempotent gate did not short-circuit.
        if status.has_config:
            console.print(
                f"[{ACCENT_SOFT}]◆[/] [bold]onboarding has unfinished sections:[/] "
                f"{markup_escape(_format_missing_sections(status))}"
            )

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


_STATUS_STYLE: dict[SectionStatus, str] = {
    SectionStatus.OK: "green",
    SectionStatus.OPTIONAL: "dim",
    SectionStatus.MISSING: "yellow",
    SectionStatus.DEGRADED: "yellow",
    SectionStatus.UNKNOWN: "red",
}


def _status_payload(status: OnboardingStatus) -> dict:
    return {
        "configPath": status.config_path,
        "hasConfig": status.has_config,
        "needsOnboarding": status.needs_onboarding,
        "sections": {name: state.value for name, state in status.sections.items()},
        "llmSource": status.llm_source,
        "imageGenerationEnabled": status.image_generation_enabled,
        "imageGenerationProvider": status.image_generation_provider,
        "imageGenerationPrimary": status.image_generation_primary,
        "channelCount": status.channel_count,
    }


@onboard_app.command("status")
def onboard_status_command(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Print readiness of every onboarding section without mutating state."""
    cfg = load_config()
    status = get_onboarding_status(cfg)

    if json_output:
        typer.echo(_json.dumps(_status_payload(status), ensure_ascii=False))
        return

    table = Table(title="Onboarding readiness", show_header=True)
    table.add_column("Section")
    table.add_column("Status")
    table.add_column("Detail")
    for name, state in status.sections.items():
        style = _STATUS_STYLE.get(state, "")
        detail = ""
        if name == "llm":
            detail = status.llm_source
        elif name == "image_generation" and status.image_generation_provider:
            detail = (
                f"{status.image_generation_provider} "
                f"({status.image_generation_source})"
            ).strip()
        elif name == "channels":
            detail = f"{status.channel_count} configured"
        table.add_row(
            name,
            f"[{style}]{state.value}[/]" if style else state.value,
            detail,
        )
    console.print(table)
    console.print(
        f"[bold]Needs onboarding:[/] "
        f"{'yes' if status.needs_onboarding else 'no'}"
    )
    if status.needs_onboarding:
        console.print(
            f"  [dim]Run[/] [{ACCENT_SOFT}]opensquilla onboard --if-needed[/] "
            f"[dim]to address:[/] "
            f"{markup_escape(_format_missing_sections(status))}"
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
                _print_saved_path(result.path)
                _print_env_reference_warnings(load_config(result.path))
                return
            if normalized == "router" and router:
                engine = SetupEngine()
                engine.apply("router", {"mode": router})
                result = engine.persist()
                _print_saved_path(result.path)
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
                _print_saved_path(result.path)
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
                _print_saved_path(result.path)
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
                _print_saved_path(result.path)
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
                _print_saved_path(result.path)
                return
        except (KeyError, TypeError, ValueError) as exc:
            error_console.print(f"[red]Error:[/red] {markup_escape(exc)}")
            raise typer.Exit(code=2) from exc

    interactive_result = run_interactive_configure(selected or None)
    if interactive_result is not None:
        _print_saved_path(interactive_result.path)
