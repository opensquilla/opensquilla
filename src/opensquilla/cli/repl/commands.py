"""Slash-command registry for the chat REPL — TUI compat layer.

This module is a thin TUI-surface adapter over
:data:`opensquilla.commands.DEFAULT_REGISTRY`. The public
API (``SlashCommand`` shim, ``REGISTRY`` tuple, ``slash_words``,
``is_exit_command``, ``find_command``, ``render_help_table``) is preserved
for backward compatibility with ``cli/repl/prompt.py`` and
``cli/chat_cmd.py``; nothing visible to the TUI changes except that
``/help`` now also lists aliases inline.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.markup import escape
from rich.table import Table

from opensquilla.commands import DEFAULT_REGISTRY, CommandDef, Surface


@dataclass(frozen=True)
class SlashCommand:
    """TUI-side view of a unified :class:`CommandDef`.

    Kept as a thin dataclass with the same shape the REPL has used
    historically, so consumers that destructure or pattern-match on these
    fields continue to work without touching their imports.
    """

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


REGISTRY: tuple[SlashCommand, ...] = tuple(
    _to_shim(cmd) for cmd in DEFAULT_REGISTRY.for_surface(Surface.TUI)
)


# Bare-string exit aliases that the user can type without a leading slash.
# These do not fit the slash-command registry naturally; they live here as
# a TUI convenience because the REPL prompt does not require slash prefix
# to quit.
_BARE_EXIT_WORDS: frozenset[str] = frozenset({":q", "quit", "exit"})


def slash_words() -> list[str]:
    """Return all words offered by prompt-toolkit completion.

    Includes canonical names, slash-prefixed aliases, and the bare exit
    words (``:q`` / ``quit`` / ``exit``) so the user can complete them
    even though they bypass the slash-command registry.
    """
    words: list[str] = [word for command in REGISTRY for word in command.words]
    words.extend(_BARE_EXIT_WORDS)
    return words


def is_exit_command(value: str) -> bool:
    head = value.strip().lower()
    if not head:
        return False
    if head in _BARE_EXIT_WORDS:
        return True
    cmd = DEFAULT_REGISTRY.find(head, surface=Surface.TUI)
    return cmd is not None and cmd.name == "/exit"


def find_command(value: str) -> SlashCommand | None:
    head = value.strip().split(maxsplit=1)[0].lower() if value.strip() else ""
    if not head:
        return None
    if head in _BARE_EXIT_WORDS:
        cmd = DEFAULT_REGISTRY.find("/exit", surface=Surface.TUI)
        return _to_shim(cmd) if cmd is not None else None
    cmd = DEFAULT_REGISTRY.find(head, surface=Surface.TUI)
    return _to_shim(cmd) if cmd is not None else None


def render_help_table() -> Table:
    table = Table(title="OpenSquilla Chat Commands", show_header=True, header_style="bold cyan")
    table.add_column("Command", style="bold")
    table.add_column("Description")
    for command in REGISTRY:
        cell = command.usage
        if command.aliases:
            cell += f"  (alias: {', '.join(command.aliases)})"
        table.add_row(escape(cell), command.description)
    return table
