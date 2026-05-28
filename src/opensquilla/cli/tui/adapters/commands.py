"""Slash-command registry helpers for the terminal chat frontend."""

from __future__ import annotations

from dataclasses import dataclass

from rich.markup import escape
from rich.table import Table

from opensquilla.cli.chat.commands import (
    BARE_EXIT_WORDS,
)
from opensquilla.cli.ui import ACCENT_HEADER
from opensquilla.engine.commands import DEFAULT_REGISTRY, CommandDef, Surface

DEFAULT_SURFACE = Surface.CLI_GATEWAY


@dataclass(frozen=True)
class SlashCommand:
    """TUI-side view of a unified :class:`CommandDef`."""

    name: str
    usage: str
    description: str
    aliases: tuple[str, ...] = ()

    @property
    def words(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


def _to_shim(cmd: CommandDef) -> SlashCommand:
    return SlashCommand(
        name=cmd.name,
        usage=cmd.usage,
        description=cmd.description,
        aliases=cmd.aliases,
    )


def registry_for_surface(surface: Surface | str = DEFAULT_SURFACE) -> tuple[SlashCommand, ...]:
    return tuple(_to_shim(cmd) for cmd in DEFAULT_REGISTRY.for_surface(surface))


REGISTRY: tuple[SlashCommand, ...] = registry_for_surface(DEFAULT_SURFACE)

_BARE_EXIT_WORDS = BARE_EXIT_WORDS


def slash_words(surface: Surface | str = DEFAULT_SURFACE) -> list[str]:
    words: list[str] = [word for command in registry_for_surface(surface) for word in command.words]
    words.extend(_BARE_EXIT_WORDS)
    return words


def is_exit_command(value: str, surface: Surface | str = DEFAULT_SURFACE) -> bool:
    head = value.strip().lower()
    if not head:
        return False
    if head in _BARE_EXIT_WORDS:
        return True
    cmd = DEFAULT_REGISTRY.find(head, surface=surface)
    return cmd is not None and cmd.name == "/exit"


def find_command(value: str, surface: Surface | str = DEFAULT_SURFACE) -> SlashCommand | None:
    head = value.strip().split(maxsplit=1)[0].lower() if value.strip() else ""
    if not head:
        return None
    if head in _BARE_EXIT_WORDS:
        cmd = DEFAULT_REGISTRY.find("/exit", surface=surface)
        return _to_shim(cmd) if cmd is not None else None
    cmd = DEFAULT_REGISTRY.find(head, surface=surface)
    return _to_shim(cmd) if cmd is not None else None


def render_help_table(surface: Surface | str = DEFAULT_SURFACE) -> Table:
    table = Table(title="OpenSquilla Chat Commands", show_header=True, header_style=ACCENT_HEADER)
    table.add_column("Command", style="bold")
    table.add_column("Description")
    for command in registry_for_surface(surface):
        cell = command.usage
        if command.aliases:
            cell += f"  (alias: {', '.join(command.aliases)})"
        table.add_row(escape(cell), command.description)
    return table
