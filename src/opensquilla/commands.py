"""Unified slash-command registry.

Source of truth for slash commands across the three chat surfaces (web RPC,
TUI REPL, external channels). Per-surface adapters in
``cli/repl/commands.py``, ``channels/command_registry.py``, and the web
frontend consume this single registry so the visible command set stays in
lockstep across surfaces.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Surface(StrEnum):
    """Chat surface that may render a slash command.

    Aligned with `opensquilla.tools.types.CallerKind` values where applicable
    (CallerKind.WEB / CLI / CHANNEL). The TUI value is named "tui" rather
    than "cli" because the registry's perspective is rendering surface,
    not the broader caller-kind taxonomy.
    """

    WEB = "web"
    TUI = "tui"
    CHANNEL = "channel"


# Per-envelope params builder for channel-mode dispatch. Kept as a generic
# Callable so the channel dispatcher can pass its own envelope while this
# registry only requires attribute access (`session_key`).
ParamsFactory = Callable[[Any], dict[str, Any]]


@dataclass(frozen=True)
class CommandDef:
    """One slash command as visible across all surfaces it supports.

    The same `CommandDef` instance is shared by every surface that lists
    the command — surfaces filter visibility via the `surfaces` field, but
    the description and usage text are deliberately unified.

    For channel-mode dispatch (RPC fan-out), `rpc_method` and `rpc_params`
    are populated; both are required together. For TUI/web client-side
    dispatch, leave them as None — the surface owns the handler.
    """

    name: str
    usage: str
    description: str
    surfaces: frozenset[Surface]
    aliases: tuple[str, ...] = ()
    rpc_method: str | None = None
    rpc_params: ParamsFactory | None = None

    def words(self) -> tuple[str, ...]:
        """Return name + aliases. Used by completion machinery."""
        return (self.name, *self.aliases)


class SlashCommandRegistry:
    """Per-surface lookup, alias resolution, and stable help generation.

    The registry is constructed once with the canonical command tuple. All
    lookups normalize the input head (lowercase, strip leading whitespace)
    so callers can pass user-typed text directly. Result lists are
    alphabetically ordered by canonical name to keep snapshot tests stable.
    """

    def __init__(self, commands: tuple[CommandDef, ...]) -> None:
        self._commands: tuple[CommandDef, ...] = tuple(sorted(commands, key=lambda c: c.name))
        self._by_word: dict[str, CommandDef] = {}
        for cmd in self._commands:
            for word in cmd.words():
                lower = word.lower()
                if lower in self._by_word:
                    raise ValueError(
                        f"duplicate slash word {word!r}: {self._by_word[lower].name} vs {cmd.name}"
                    )
                self._by_word[lower] = cmd

    def for_surface(self, surface: Surface) -> tuple[CommandDef, ...]:
        return tuple(c for c in self._commands if surface in c.surfaces)

    def find(self, value: str, surface: Surface | None = None) -> CommandDef | None:
        head = value.strip().split(maxsplit=1)[0].lower() if value.strip() else ""
        if not head:
            return None
        cmd = self._by_word.get(head)
        if cmd is None:
            return None
        if surface is not None and surface not in cmd.surfaces:
            return None
        return cmd

    def help_lines(self, surface: Surface) -> list[str]:
        """Return ``["/name — description", ...]`` for the surface, sorted."""
        return [f"{c.name} — {c.description}" for c in self.for_surface(surface)]


def command_def_rpc_payload(cmd: CommandDef) -> dict[str, Any]:
    """Project a CommandDef into a JSON-safe RPC payload."""

    out: dict[str, Any] = {
        "name": cmd.name,
        "usage": cmd.usage,
        "description": cmd.description,
        "aliases": list(cmd.aliases),
    }
    if cmd.rpc_method is not None:
        out["rpc_method"] = cmd.rpc_method
    return out


def commands_for_surface_rpc_payload(
    params: Mapping[str, Any] | None,
    registry: SlashCommandRegistry | None = None,
) -> dict[str, Any]:
    """Build the RPC wire payload for slash commands visible on a surface."""

    registry = registry or DEFAULT_REGISTRY
    if params is not None and not isinstance(params, Mapping):
        raise ValueError("params must be an object")
    raw = (params or {}).get("surface", "web")
    if not isinstance(raw, str):
        raise ValueError("params.surface must be a string")
    try:
        surface = Surface(raw.lower())
    except ValueError as exc:
        valid = ", ".join(sorted(s.value for s in Surface))
        raise ValueError(f"unknown surface {raw!r}; valid: {valid}") from exc
    return {
        "surface": surface.value,
        "commands": [command_def_rpc_payload(cmd) for cmd in registry.for_surface(surface)],
    }


# ---------------------------------------------------------------------------
# Canonical registry: every slash command shipped today across the three
# surfaces. Sourced from:
#   - cli/repl/commands.py REGISTRY (TUI, 17)
#   - channels/command_registry.py DEFAULT_COMMAND_REGISTRY (channel, 9)
#   - gateway/static/js/views/chat.js slash-command list (web, 3)
# Where canonical name diverges (TUI's /clear vs web/channel's /reset),
# we pick the cross-surface name and demote the other to alias.
# ---------------------------------------------------------------------------


def _key(envelope: Any) -> dict[str, str]:
    return {"key": envelope.session_key}


def _session_key(envelope: Any) -> dict[str, str]:
    return {"sessionKey": envelope.session_key}


def _empty(_envelope: Any) -> dict[str, Any]:
    return {}


_W = Surface.WEB
_T = Surface.TUI
_C = Surface.CHANNEL


_COMMANDS: tuple[CommandDef, ...] = (
    # ---- Cross-surface (web + tui + channel where applicable) -------------
    CommandDef(
        name="/new",
        usage="/new [title]",
        description="Start a new chat session.",
        surfaces=frozenset({_W, _T, _C}),
        rpc_method="sessions.reset",
        rpc_params=_key,
    ),
    CommandDef(
        name="/reset",
        usage="/reset",
        description="Clear the current conversation context.",
        surfaces=frozenset({_W, _T, _C}),
        aliases=("/clear",),
        rpc_method="sessions.reset",
        rpc_params=_key,
    ),
    CommandDef(
        name="/compact",
        usage="/compact",
        description="Compact older context in the current session.",
        surfaces=frozenset({_W, _T, _C}),
        rpc_method="sessions.contextCompact",
        rpc_params=_key,
    ),
    # ---- TUI + Channel ----------------------------------------------------
    CommandDef(
        name="/help",
        usage="/help",
        description="Show available commands.",
        surfaces=frozenset({_T, _C}),
        rpc_method="status",
        rpc_params=_empty,
    ),
    CommandDef(
        name="/status",
        usage="/status",
        description="Show current session, model, and mode.",
        surfaces=frozenset({_T, _C}),
        aliases=("/session",),
        rpc_method="status",
        rpc_params=_empty,
    ),
    CommandDef(
        name="/model",
        usage="/model [name]",
        description="List available models.",
        surfaces=frozenset({_T, _C}),
        rpc_method="models.list",
        rpc_params=_empty,
    ),
    # ---- TUI only ---------------------------------------------------------
    CommandDef(
        name="/models",
        usage="/models",
        description="List available models (TUI variant).",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/cost",
        usage="/cost",
        description="Show current REPL session usage.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/usage",
        usage="/usage",
        description="Show gateway aggregate usage.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/tool-compress",
        usage="/tool-compress [off|truncate|summarize|status]",
        description="Show or set tool result compression mode.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/save",
        usage="/save [file]",
        description="Export the current REPL transcript as markdown.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/image",
        usage="/image <path> [prompt]",
        description="Attach an image and send a prompt.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/path",
        usage="/path <path> [prompt]",
        description=(
            "Analyze a local path without uploading bytes; sends the path string "
            "as prompt text."
        ),
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/approvals",
        usage="/approvals [reset]",
        description="Show or reset approval state.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/permissions",
        usage="/permissions [mode]",
        description="Show or set host-exec approval mode.",
        surfaces=frozenset({_T}),
        aliases=("/elevated",),
    ),
    CommandDef(
        name="/forget",
        usage="/forget [target]",
        description="Clear cached approval decisions.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/sessions",
        usage="/sessions [limit]",
        description="List recent sessions.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/resume",
        usage="/resume <id>",
        description="Resume an existing session.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/delete",
        usage="/delete <id>",
        description="Delete a session.",
        surfaces=frozenset({_T}),
    ),
    CommandDef(
        name="/exit",
        usage="/exit",
        description="Exit the REPL.",
        surfaces=frozenset({_T}),
        aliases=("/quit",),
    ),
    # ---- Channel only -----------------------------------------------------
    CommandDef(
        name="/abort",
        usage="/abort",
        description="Abort the in-progress turn.",
        surfaces=frozenset({_C}),
        rpc_method="sessions.abort",
        rpc_params=_key,
    ),
    CommandDef(
        name="/history",
        usage="/history",
        description="Show recent chat history.",
        surfaces=frozenset({_C}),
        rpc_method="chat.history",
        rpc_params=_session_key,
    ),
    CommandDef(
        name="/memory",
        usage="/memory",
        description="Show memory subsystem status.",
        surfaces=frozenset({_C}),
        rpc_method="doctor.memory.status",
        rpc_params=_empty,
    ),
    CommandDef(
        name="/skills",
        usage="/skills",
        description="List loaded skills.",
        surfaces=frozenset({_C}),
        rpc_method="skills.list",
        rpc_params=_empty,
    ),
)


DEFAULT_REGISTRY = SlashCommandRegistry(_COMMANDS)


__all__ = [
    "CommandDef",
    "DEFAULT_REGISTRY",
    "ParamsFactory",
    "SlashCommandRegistry",
    "Surface",
    "command_def_rpc_payload",
    "commands_for_surface_rpc_payload",
]
