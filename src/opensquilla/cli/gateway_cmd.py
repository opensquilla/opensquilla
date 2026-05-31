"""Gateway run command — start ASGI gateway with uvicorn."""

from __future__ import annotations

import asyncio
import json
import os

import typer

from opensquilla.cli.gateway_lifecycle import (
    GatewayLifecycleManager,
    GatewayLifecycleResult,
    remote_gateway_status,
)
from opensquilla.cli.ui import ACCENT_MARKUP, console
from opensquilla.gateway.boot import start_gateway_server
from opensquilla.gateway.config import GatewayConfig, is_public_bind, resolve_listen_address
from opensquilla.paths import default_opensquilla_home


def gateway_startup_guidance(host: str, port: int, scheme: str = "http") -> tuple[str, ...]:
    """Return operator-facing guidance shown after the gateway starts."""

    base_url = f"{scheme}://{host}:{port}"
    return (
        f"[bold]Web UI:[/bold] {base_url}/control/",
        f"[bold]API base:[/bold] {base_url}",
        f"[bold]Debug log:[/bold] {default_opensquilla_home() / 'logs' / 'debug.log'}",
        "[dim]Keep this terminal open. Press Ctrl+C to stop.[/dim]",
    )


def run_gateway(
    port: int | None = typer.Option(18791, "--port", "-p", help="Port to bind"),
    bind: str | None = typer.Option("127.0.0.1", "--bind", "-b", help="Host to bind"),
    listen: str = typer.Option("", "--listen", help="Host to bind (wins over --bind)"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug mode"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path"),
) -> None:
    """Start the ASGI gateway server.

    Precedence: ``--listen`` > ``--bind`` > ``OPENSQUILLA_LISTEN`` >
    ``OPENSQUILLA_GATEWAY_HOST`` > toml ``host`` field > default ``127.0.0.1``.

    The toml ``host`` field was previously silently ignored — operators
    setting ``host = "0.0.0.0"`` in opensquilla.toml then ran the gateway
    expecting public binding and got loopback instead. The toml is now
    honoured as the fallback when no CLI flag or env var is supplied,
    matching what the field name promises.
    """
    # Load config FIRST so its ``host`` field can act as the final
    # fallback below ``OPENSQUILLA_GATEWAY_HOST``.
    config = GatewayConfig.load(config_path or os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))
    if config_path and not config.config_path:
        config.config_path = str(config_path)
    # Treat the CLI ``--bind`` default as "not explicitly supplied" so the
    # env vars + toml get a chance to participate when the operator only
    # sets one of them.
    explicit_flag: str | None = listen or (bind if bind and bind != "127.0.0.1" else None)
    host = resolve_listen_address(explicit_flag, default=config.host or "127.0.0.1")
    resolved_port = port if port is not None else config.port
    config = config.model_copy(update={"host": host, "port": resolved_port, "debug": debug})

    banner_host = f"[red]{host}[/red]" if is_public_bind(host) else f"[{ACCENT_MARKUP}]{host}[/]"
    console.print(
        f"[bold green]Starting OpenSquilla gateway[/bold green] on {banner_host}:{resolved_port}"
    )
    scheme = "https" if (config.tls.keyfile and config.tls.certfile) else "http"
    for line in gateway_startup_guidance(host, resolved_port, scheme=scheme):
        console.print(line)
    if is_public_bind(host):
        # Use ASCII-only glyphs here so the warning still prints on Windows
        # consoles configured for legacy GBK code pages (where U+26A0 / em-dash
        # crash Rich's legacy renderer with UnicodeEncodeError).
        console.print(
            "[yellow]WARNING: gateway is bound to a wildcard address - "
            "reachable from every interface.[/yellow]"
        )
        if config.auth.mode == "none":
            console.print(
                "[yellow]  auth.mode=none + wildcard bind = LAN-open. "
                "Anyone reachable on this network can use the chat, sessions, "
                "and config surfaces with your provider credentials.[/yellow]"
            )
        console.print(
            "[yellow]  Bypass / elevated mode remains owner-only and "
            "is unreachable from non-loopback peers; the chat UI will "
            "self-disable that pill.[/yellow]"
        )

    async def _run() -> None:
        # Subscription manager is gateway-specific (WS event routing)
        from opensquilla.gateway.websocket import SubscriptionManager

        subscription_mgr = SubscriptionManager()

        # build_services() inside start_gateway_server handles:
        # session_manager, provider_selector, tool_registry, usage_tracker,
        # memory, skills, scheduler, search, MCP discovery.
        server = await start_gateway_server(
            config=config,
            subscription_manager=subscription_mgr,
            run=True,
        )
        assert server._task is not None
        try:
            await server._task
        except (KeyboardInterrupt, asyncio.CancelledError):
            await server.close("keyboard_interrupt")

    try:
        asyncio.run(_run())
    except ValueError as exc:
        from opensquilla.onboarding.next_steps import env_recovery_commands
        from opensquilla.onboarding.status import get_onboarding_status

        console.print(f"[red]Gateway could not start:[/red] {exc}")
        status = get_onboarding_status(config)
        recovery_entries = env_recovery_commands(status)
        if not recovery_entries:
            embedding = getattr(getattr(config, "memory", None), "embedding", None)
            remote = getattr(embedding, "remote", None)
            env_key = str(getattr(remote, "api_key_env", "") or "").strip()
            if not env_key and config.config_path:
                try:
                    import tomllib

                    with open(config.config_path, "rb") as f:
                        raw_config = tomllib.load(f)
                    env_key = str(
                        raw_config.get("memory", {})
                        .get("embedding", {})
                        .get("remote", {})
                        .get("api_key_env", "")
                        or ""
                    ).strip()
                except (OSError, tomllib.TOMLDecodeError):
                    env_key = ""
            if env_key and not os.environ.get(env_key):
                from opensquilla.onboarding.next_steps import set_env_hint

                recovery_entries.append(
                    {"label": "Set memory key", "command": set_env_hint(env_key)}
                )
        for entry in recovery_entries:
            console.print(f"{entry['label']}: {entry['command']}")
        if config.config_path:
            console.print(
                f"Inspect onboarding: opensquilla onboard status --config {config.config_path}"
            )
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n[yellow]Gateway stopped.[/yellow]")


def _resolve_lifecycle_host(*, bind: str, listen: str) -> str:
    explicit_flag: str | None = listen or (bind if bind and bind != "127.0.0.1" else None)
    return resolve_listen_address(explicit_flag)


def _lifecycle_manager(
    *,
    port: int | None,
    bind: str | None,
    listen: str,
    config_path: str | None = None,
    health_timeout: float = 60.0,
    shutdown_timeout: float = 10.0,
) -> GatewayLifecycleManager:
    config = GatewayConfig.load(config_path or os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))
    host = _resolve_lifecycle_host(bind=bind or "127.0.0.1", listen=listen)
    if not listen and (bind is None or bind == "127.0.0.1"):
        host = resolve_listen_address(None, default=config.host or "127.0.0.1")
    resolved_port = port if port is not None else config.port
    return GatewayLifecycleManager(
        host=host,
        port=resolved_port,
        config_path=config_path or os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH") or None,
        health_timeout=health_timeout,
        shutdown_timeout=shutdown_timeout,
    )


def _emit_lifecycle_result(result: GatewayLifecycleResult, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, default=str))
    elif result.ok:
        typer.echo(f"{result.state}: {result.url}")
    else:
        typer.echo(f"Error: {result.message or result.code or result.state}", err=True)

    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)


def start_gateway(
    port: int | None = typer.Option(18791, "--port", "-p", help="Port to bind"),
    bind: str | None = typer.Option("127.0.0.1", "--bind", "-b", help="Host to bind"),
    listen: str = typer.Option("", "--listen", help="Host to bind (wins over --bind)"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path"),
    health_timeout: float = typer.Option(60.0, "--timeout", help="Readiness wait timeout"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Start the gateway in the background and wait for readiness."""

    manager = _lifecycle_manager(
        port=port,
        bind=bind,
        listen=listen,
        config_path=config_path,
        health_timeout=health_timeout,
    )
    _emit_lifecycle_result(manager.start(), json_output=json_output)


def status_gateway(
    port: int | None = typer.Option(18791, "--port", "-p", help="Port to inspect"),
    bind: str | None = typer.Option("127.0.0.1", "--bind", "-b", help="Host to inspect"),
    listen: str = typer.Option("", "--listen", help="Host to inspect (wins over --bind)"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path"),
    gateway_url: str | None = typer.Option(None, "--gateway", help="Remote gateway URL"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect the managed gateway process without mutating state."""

    if gateway_url:
        _emit_lifecycle_result(remote_gateway_status(gateway_url), json_output=json_output)
        return

    manager = _lifecycle_manager(port=port, bind=bind, listen=listen, config_path=config_path)
    _emit_lifecycle_result(manager.status(), json_output=json_output)


def stop_gateway(
    port: int | None = typer.Option(18791, "--port", "-p", help="Port to stop"),
    bind: str | None = typer.Option("127.0.0.1", "--bind", "-b", help="Host to stop"),
    listen: str = typer.Option("", "--listen", help="Host to stop (wins over --bind)"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path"),
    shutdown_timeout: float = typer.Option(10.0, "--timeout", help="Shutdown wait timeout"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Stop the recorded gateway process."""

    manager = _lifecycle_manager(
        port=port,
        bind=bind,
        listen=listen,
        config_path=config_path,
        shutdown_timeout=shutdown_timeout,
    )
    _emit_lifecycle_result(manager.stop(), json_output=json_output)


def restart_gateway(
    port: int | None = typer.Option(18791, "--port", "-p", help="Port to restart"),
    bind: str | None = typer.Option("127.0.0.1", "--bind", "-b", help="Host to restart"),
    listen: str = typer.Option("", "--listen", help="Host to restart (wins over --bind)"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path"),
    health_timeout: float = typer.Option(60.0, "--timeout", help="Readiness wait timeout"),
    shutdown_timeout: float = typer.Option(
        10.0, "--shutdown-timeout", help="Shutdown wait timeout"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Restart the recorded gateway process."""

    manager = _lifecycle_manager(
        port=port,
        bind=bind,
        listen=listen,
        config_path=config_path,
        health_timeout=health_timeout,
        shutdown_timeout=shutdown_timeout,
    )
    _emit_lifecycle_result(manager.restart(), json_output=json_output)
