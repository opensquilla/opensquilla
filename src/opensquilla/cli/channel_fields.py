"""Shared CLI helpers for channel field payloads."""

from __future__ import annotations

from typing import Any

import typer

from opensquilla.onboarding.channel_specs import get_channel_setup_spec

TOKEN_ALIASES = (
    "token",
    "access_token",
    "client_secret",
    "app_secret",
    "app_password",
    "corp_secret",
)


def coerce_channel_field_value(field_type: str, raw: str) -> Any:
    if field_type == "int":
        return int(raw)
    if field_type == "float":
        return float(raw)
    if field_type == "bool":
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return raw


def parse_channel_field_pairs(pairs: list[str], type_name: str) -> dict[str, Any]:
    spec = get_channel_setup_spec(type_name)
    by_name = {f.name: f for f in spec.fields}
    out: dict[str, Any] = {}
    for raw_pair in pairs:
        if "=" not in raw_pair:
            raise typer.BadParameter(f"--field expects key=value, got {raw_pair!r}")
        key, value = raw_pair.split("=", 1)
        if key not in by_name:
            raise typer.BadParameter(
                f"unknown field {key!r} for channel type {type_name!r}"
            )
        out[key] = coerce_channel_field_value(by_name[key].field_type, value)
    return out


def resolve_channel_token_field(type_name: str) -> str:
    """Pick the secret field that --token maps to, in alias-tuple order."""
    spec = get_channel_setup_spec(type_name)
    secret_names = {f.name for f in spec.fields if f.secret}
    for alias in TOKEN_ALIASES:
        if alias in secret_names:
            return alias
    typer.secho(
        f"--token is not supported for channel type {type_name!r}; "
        f"use --field <name>=... instead.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=2)


def apply_channel_token(payload: dict[str, Any], type_name: str, token: str) -> None:
    if not token:
        return
    field_name = resolve_channel_token_field(type_name)
    typer.secho(
        f"--token resolved to {type_name}.{field_name}",
        fg=typer.colors.CYAN,
    )
    payload[field_name] = token
