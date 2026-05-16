"""Compatibility re-export for the shared slash-command registry."""

from __future__ import annotations

from opensquilla.commands import (
    DEFAULT_REGISTRY,
    CommandDef,
    ParamsFactory,
    SlashCommandRegistry,
    Surface,
)

__all__ = [
    "CommandDef",
    "DEFAULT_REGISTRY",
    "ParamsFactory",
    "SlashCommandRegistry",
    "Surface",
]
