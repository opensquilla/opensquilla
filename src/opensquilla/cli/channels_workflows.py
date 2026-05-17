"""CLI workflows for channel commands."""

from __future__ import annotations

from opensquilla.cli.channels_presenters import (
    emit_channel_catalog_error,
    emit_channel_type_description,
    emit_channel_types,
)
from opensquilla.onboarding.channel_specs import (
    get_channel_setup_spec,
    list_channel_setup_specs,
)


def list_channel_types_for_cli(*, json_output: bool) -> None:
    """Load and emit supported channel types for the CLI."""

    emit_channel_types(list_channel_setup_specs(), json_output=json_output)


def describe_channel_type_for_cli(type_name: str, *, json_output: bool) -> None:
    """Load and emit details for one channel type."""

    try:
        spec = get_channel_setup_spec(type_name)
    except KeyError as exc:
        emit_channel_catalog_error(exc)

    emit_channel_type_description(spec, json_output=json_output)
