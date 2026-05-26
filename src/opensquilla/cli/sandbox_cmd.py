"""CLI: opensquilla sandbox posture controls."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import typer

from opensquilla.cli.output import print_json
from opensquilla.onboarding.config_store import (
    load_config,
    persist_config,
    resolve_config_path,
)
from opensquilla.sandbox.status import status_payload as _status_payload

sandbox_app = typer.Typer(help="Show or change the default sandbox posture.")


_SOURCE_LABEL = {
    "explicit": "from --config",
    "env": "from OPENSQUILLA_GATEWAY_CONFIG_PATH",
    "cwd": "found in cwd",
    "home": "default in $HOME",
}


def _resolve_path(config_path: Path | None) -> Path:
    target, source = resolve_config_path(config_path)
    typer.echo(f"Config: {target} ({_SOURCE_LABEL[source]})")
    return target


def _apply_posture(config: Any, posture: Literal["on", "bypass", "full"]) -> Any:
    if posture == "on":
        config.sandbox.sandbox = True
        config.sandbox.security_grading = True
        config.permissions.default_mode = "off"
        return config
    config.sandbox.sandbox = False
    config.sandbox.security_grading = False
    config.permissions.default_mode = posture
    return config


def _write_posture(config_path: Path | None, posture: Literal["on", "bypass", "full"]) -> None:
    target = _resolve_path(config_path)
    config = _apply_posture(load_config(target), posture)
    persist_config(config, path=target, restart_required=True)
    payload = _status_payload(config, restart_required=True)
    typer.echo(
        "Sandbox posture set to "
        f"{payload['posture']}. Restart the gateway for running processes to apply it."
    )


@sandbox_app.command("status")
def sandbox_status(
    config_path: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show the configured default sandbox posture."""

    target, _source = resolve_config_path(config_path)
    config = load_config(target)
    payload = _status_payload(config, restart_required=False)
    if json_output:
        print_json(payload)
        return
    typer.echo(f"Config: {target}")
    typer.echo(f"Posture: {payload['posture']}")
    typer.echo(
        "Sandbox: "
        f"sandbox={payload['sandbox']['sandbox']} "
        f"security_grading={payload['sandbox']['security_grading']}"
    )
    typer.echo(f"Permissions default: {payload['permissions']['default_mode']}")


@sandbox_app.command("bypass")
def sandbox_bypass(
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Disable runtime sandboxing and auto-grant approvals except sensitive paths."""

    _write_posture(config_path, "bypass")


@sandbox_app.command("full")
def sandbox_full(
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Disable runtime sandboxing and skip approval and sensitive-path gates."""

    _write_posture(config_path, "full")


@sandbox_app.command("on")
def sandbox_on(
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Restore the default sandboxed posture."""

    _write_posture(config_path, "on")


@sandbox_app.command("reset")
def sandbox_reset(
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Reset sandbox posture to OpenSquilla defaults."""

    _write_posture(config_path, "bypass")
