"""CLI workflows for channel commands."""

from __future__ import annotations

from pathlib import Path

from opensquilla.cli.channels_config_queries import (
    load_configured_channel_entries,
    resolve_channel_config_path,
)
from opensquilla.cli.channels_gateway_queries import (
    load_channel_status,
    logout_channel,
    restart_channel,
)
from opensquilla.cli.channels_presenters import (
    emit_channel_action_result,
    emit_channel_catalog_error,
    emit_channel_config_path,
    emit_channel_status,
    emit_channel_type_description,
    emit_channel_types,
    emit_configured_channels,
)
from opensquilla.cli.gateway_rpc import confirm_or_exit
from opensquilla.onboarding.channel_specs import (
    get_channel_setup_spec,
    list_channel_setup_specs,
)


def list_channel_types_for_cli(*, json_output: bool) -> None:
    """Load and emit supported channel types for the CLI."""

    emit_channel_types(list_channel_setup_specs(), json_output=json_output)


def list_configured_channels_for_cli(
    config_path: Path | None,
    *,
    json_output: bool,
) -> None:
    """Load and emit configured channels for the CLI."""

    target, source = resolve_channel_config_path(config_path)
    if not json_output:
        emit_channel_config_path(target, source=source)
    entries = load_configured_channel_entries(target)
    emit_configured_channels(entries, config_path=target, json_output=json_output)


def describe_channel_type_for_cli(type_name: str, *, json_output: bool) -> None:
    """Load and emit details for one channel type."""

    try:
        spec = get_channel_setup_spec(type_name)
    except KeyError as exc:
        emit_channel_catalog_error(exc)

    emit_channel_type_description(spec, json_output=json_output)


def show_channel_status_for_cli(
    name: str | None,
    *,
    json_output: bool,
) -> None:
    """Load and emit runtime channel status for the CLI."""

    payload = load_channel_status(json_output=json_output)
    emit_channel_status(payload, name=name, json_output=json_output)


def restart_channel_for_cli(
    name: str,
    *,
    yes: bool,
    json_output: bool,
) -> None:
    """Restart a live messaging channel for the CLI."""

    confirm_or_exit(
        f"Restart channel {name!r}? Message delivery may be interrupted.",
        yes=yes,
        json_output=json_output,
    )
    payload = restart_channel(name, json_output=json_output)
    emit_channel_action_result(
        payload,
        action_label="restarted",
        fallback_channel=name,
        json_output=json_output,
    )


def logout_channel_for_cli(
    name: str,
    *,
    yes: bool,
    json_output: bool,
) -> None:
    """Log out and disconnect a live messaging channel for the CLI."""

    confirm_or_exit(
        f"Log out channel {name!r}? Live channel session state will be dropped.",
        yes=yes,
        json_output=json_output,
    )
    payload = logout_channel(name, json_output=json_output)
    emit_channel_action_result(
        payload,
        action_label="logged out",
        fallback_channel=name,
        json_output=json_output,
    )
