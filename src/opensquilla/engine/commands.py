"""Unified slash-command registry.

Source of truth for slash commands across chat surfaces. Per-surface adapters
in ``cli/repl/commands.py``, ``channels/command_registry.py``, and the web
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

    Legacy names remain as enum aliases for existing in-process callers. Use
    :func:`parse_surface` for user/input parsing so old values such as ``web``
    and ``tui`` normalize to the canonical surface names.
    """

    WEB_CHAT = "web_chat"
    CLI_GATEWAY = "cli_gateway"
    CLI_STANDALONE = "cli_standalone"
    CHANNEL = "channel"

    WEB = "web_chat"
    TUI = "cli_gateway"
    CLI = "cli_gateway"


_SURFACE_ALIASES = {
    "web": Surface.WEB_CHAT,
    "tui": Surface.CLI_GATEWAY,
    "cli": Surface.CLI_GATEWAY,
}


def parse_surface(value: str) -> Surface:
    """Parse canonical and legacy surface names."""
    normalized = value.strip().lower()
    if normalized in _SURFACE_ALIASES:
        return _SURFACE_ALIASES[normalized]
    try:
        return Surface(normalized)
    except ValueError as exc:
        valid = ", ".join(sorted({s.value for s in Surface} | set(_SURFACE_ALIASES)))
        raise ValueError(f"unknown surface {value!r}; valid: {valid}") from exc


# Per-envelope params builder for channel-mode dispatch. Kept as a generic
# Callable to avoid a cycle with opensquilla.gateway.routing.RouteEnvelope at
# import time — the channel dispatcher passes its own envelope and we only
# require attribute access (`session_key`).
ParamsFactory = Callable[[Any], dict[str, Any]]


@dataclass(frozen=True)
class ArgumentChoice:
    """One user-visible argument option for slash-command completion."""

    value: str
    description: str


class ExecutionKind(StrEnum):
    """How a surface executes a slash command."""

    RPC = "rpc"
    LOCAL = "local"


@dataclass(frozen=True)
class CommandExecution:
    """Per-surface execution metadata for a slash command."""

    kind: ExecutionKind
    action: str
    rpc_method: str | None = None
    rpc_params: ParamsFactory | None = None


@dataclass(frozen=True)
class CommandDef:
    """One slash command as visible across all surfaces it supports.

    The same `CommandDef` instance is shared by every surface that lists the
    command. Per-surface execution metadata describes whether a surface calls
    gateway RPC or handles the command locally.
    """

    name: str
    usage: str
    description: str
    execution: Mapping[Surface, CommandExecution]
    aliases: tuple[str, ...] = ()
    argument_choices: tuple[ArgumentChoice, ...] = ()

    @property
    def surfaces(self) -> frozenset[Surface]:
        """Return surfaces where this command has visible execution."""
        return frozenset(self.execution.keys())

    @property
    def rpc_method(self) -> str | None:
        """Deprecated channel RPC method compatibility projection."""
        execution = self.execution_for(Surface.CHANNEL)
        return execution.rpc_method if execution is not None else None

    @property
    def rpc_params(self) -> ParamsFactory | None:
        """Deprecated channel RPC params compatibility projection."""
        execution = self.execution_for(Surface.CHANNEL)
        return execution.rpc_params if execution is not None else None

    def execution_for(self, surface: Surface | str) -> CommandExecution | None:
        """Return execution metadata for a surface, if visible there."""
        parsed = parse_surface(surface) if isinstance(surface, str) else surface
        return self.execution.get(parsed)

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

    def for_surface(self, surface: Surface | str) -> tuple[CommandDef, ...]:
        parsed = parse_surface(surface) if isinstance(surface, str) else surface
        return tuple(c for c in self._commands if c.execution_for(parsed) is not None)

    def find(self, value: str, surface: Surface | str | None = None) -> CommandDef | None:
        head = value.strip().split(maxsplit=1)[0].lower() if value.strip() else ""
        if not head:
            return None
        cmd = self._by_word.get(head)
        if cmd is None:
            return None
        if surface is not None and cmd.execution_for(surface) is None:
            return None
        return cmd

    def help_lines(self, surface: Surface | str) -> list[str]:
        """Return ``["/name — description", ...]`` for the surface, sorted."""
        return [f"{c.name} — {c.description}" for c in self.for_surface(surface)]


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


_W = Surface.WEB_CHAT
_T = Surface.CLI_GATEWAY
_S = Surface.CLI_STANDALONE
_C = Surface.CHANNEL


def _local(action: str) -> CommandExecution:
    return CommandExecution(kind=ExecutionKind.LOCAL, action=action)


def _rpc(method: str, params: ParamsFactory | None = None) -> CommandExecution:
    return CommandExecution(
        kind=ExecutionKind.RPC,
        action=method,
        rpc_method=method,
        rpc_params=params,
    )


_COMMANDS: tuple[CommandDef, ...] = (
    # ---- Cross-surface (web + tui + channel where applicable) -------------
    CommandDef(
        name="/new",
        usage="/new [title]",
        description="Start a new chat session.",
        execution={
            _W: _rpc("sessions.reset", _key),
            _T: _local("session.new"),
            _S: _local("session.new"),
            _C: _rpc("sessions.reset", _key),
        },
    ),
    CommandDef(
        name="/reset",
        usage="/reset",
        description="Clear the current conversation context.",
        execution={
            _W: _rpc("sessions.reset", _key),
            _T: _local("session.reset"),
            _S: _local("session.reset"),
            _C: _rpc("sessions.reset", _key),
        },
        aliases=("/clear",),
    ),
    CommandDef(
        name="/compact",
        usage="/compact",
        description="Compact older context in the current session.",
        execution={
            _W: _rpc("sessions.contextCompact", _key),
            _T: _local("session.compact"),
            _S: _local("session.compact"),
            _C: _rpc("sessions.contextCompact", _key),
        },
        aliases=("/cmp",),
    ),
    # ---- TUI + Channel ----------------------------------------------------
    CommandDef(
        name="/help",
        usage="/help",
        description="Show available commands.",
        execution={_T: _local("help.show"), _S: _local("help.show"), _C: _rpc("status", _empty)},
    ),
    CommandDef(
        name="/theme",
        usage="/theme [name]",
        description="List or switch the OpenTUI color theme.",
        execution={_T: _local("theme.set"), _S: _local("theme.set")},
    ),
    CommandDef(
        name="/status",
        usage="/status",
        description="Show current session, model, and mode.",
        execution={
            _T: _local("status.show"),
            _S: _local("status.show"),
            _C: _rpc("status", _empty),
        },
        aliases=("/session",),
    ),
    CommandDef(
        name="/model",
        usage="/model [name]",
        description="List available models.",
        execution={
            _T: _local("model.list"),
            _S: _local("model.list"),
            _C: _rpc("models.list", _empty),
        },
    ),
    # ---- TUI only ---------------------------------------------------------
    CommandDef(
        name="/models",
        usage="/models",
        description="List available models (TUI variant).",
        execution={_T: _local("models.list")},
    ),
    CommandDef(
        name="/cost",
        usage="/cost",
        description="Show current REPL session usage.",
        execution={_T: _local("usage.cost"), _S: _local("usage.cost")},
    ),
    CommandDef(
        name="/usage",
        usage="/usage",
        description="Show gateway aggregate usage.",
        execution={
            _W: _rpc("usage.status"),
            _T: _rpc("usage.status"),
            _C: _rpc("usage.status", _empty),
        },
    ),
    CommandDef(
        name="/file",
        usage="/file <path> [prompt]",
        description="Upload a local file from this CLI machine.",
        execution={_T: _local("cli.file")},
    ),
    CommandDef(
        name="/save",
        usage="/save [file]",
        description="Export the current REPL transcript as markdown.",
        execution={_T: _local("transcript.save"), _S: _local("transcript.save")},
    ),
    CommandDef(
        name="/image",
        usage="/image <path> [prompt]",
        description="Attach an image and send a prompt.",
        execution={_T: _local("image.attach"), _S: _local("image.attach")},
    ),
    CommandDef(
        name="/path",
        usage="/path <path> [prompt]",
        description=(
            "Analyze a local path without uploading bytes; sends the path string "
            "as prompt text."
        ),
        execution={_T: _local("path.analyze"), _S: _local("path.analyze")},
    ),
    CommandDef(
        name="/approvals",
        usage="/approvals [reset]",
        description="Show or reset approval state.",
        execution={_T: _local("approvals.show")},
    ),
    CommandDef(
        name="/permissions",
        usage="/permissions [mode]",
        description="Show or set the session permission override.",
        execution={_T: _local("permissions.show")},
        aliases=("/elevated",),
        argument_choices=(
            ArgumentChoice("off", "Clear session override; configured default resumes."),
            ArgumentChoice("on", "Host exec, approvals required."),
            ArgumentChoice(
                "bypass",
                "Host exec, approvals auto-granted; sensitive paths still blocked.",
            ),
            ArgumentChoice("full", "Host exec, approvals skipped; sensitive paths bypassed."),
            ArgumentChoice("status", "Show current session permissions override."),
        ),
    ),
    CommandDef(
        name="/forget",
        usage="/forget [target]",
        description="Clear cached approval decisions.",
        execution={_T: _local("approvals.forget")},
    ),
    CommandDef(
        name="/sessions",
        usage="/sessions [limit]",
        description="List recent sessions.",
        execution={_T: _local("sessions.list")},
    ),
    CommandDef(
        name="/resume",
        usage="/resume <id>",
        description="Resume an existing session.",
        execution={_T: _local("sessions.resume")},
    ),
    CommandDef(
        name="/delete",
        usage="/delete <id>",
        description="Delete a session.",
        execution={_T: _local("sessions.delete")},
    ),
    CommandDef(
        name="/exit",
        usage="/exit",
        description="Exit the REPL.",
        execution={_T: _local("repl.exit"), _S: _local("repl.exit")},
        aliases=("/quit",),
    ),
    # ---- Channel only -----------------------------------------------------
    CommandDef(
        name="/abort",
        usage="/abort",
        description="Abort the in-progress turn.",
        execution={_C: _rpc("sessions.abort", _key)},
    ),
    CommandDef(
        name="/history",
        usage="/history",
        description="Show recent chat history.",
        execution={_C: _rpc("chat.history", _session_key)},
    ),
    CommandDef(
        name="/memory",
        usage="/memory",
        description="Show memory subsystem status.",
        execution={_C: _rpc("doctor.memory.status", _empty)},
    ),
    CommandDef(
        name="/meta",
        usage="/meta [skill-name]",
        description="List meta-skills, or run one with /meta <skill-name>.",
        execution={
            _W: _local("meta.menu"),
            _T: _local("meta.menu"),
            _S: _local("meta.menu"),
            _C: _rpc("meta.list", _empty),
        },
    ),
    CommandDef(
        name="/skills",
        usage="/skills",
        description="List loaded skills.",
        execution={_C: _rpc("skills.list", _empty)},
    ),
)


DEFAULT_REGISTRY = SlashCommandRegistry(_COMMANDS)


__all__ = [
    "CommandDef",
    "CommandExecution",
    "DEFAULT_REGISTRY",
    "ExecutionKind",
    "ParamsFactory",
    "SlashCommandRegistry",
    "Surface",
    "parse_surface",
]
