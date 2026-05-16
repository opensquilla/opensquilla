"""Channel-side slash-command dispatcher — adapter over the unified registry.

``DEFAULT_COMMAND_REGISTRY`` is derived from the shared slash-command registry
rather than holding its own hard-coded command table. The ``CommandRegistry.match`` and ``dispatch``
API is preserved for existing callers (``gateway/boot.py``,
``gateway/channel_dispatch.py``).

The channel-side slash-intercept-pre-persist invariant
(``channel_dispatch.py:88-100``) stays where it lives; this module only
provides the dispatch lookup table.
"""

from __future__ import annotations

from typing import Any

from opensquilla.channels.types import OutgoingMessage
from opensquilla.commands import DEFAULT_REGISTRY, ParamsFactory, Surface


class CommandRegistry:
    """Channel-mode dispatcher.

    Matches inbound channel messages against a registered slash-command set
    and forwards the resulting RPC call to the gateway dispatcher. Lookup
    keys are bare command names (without leading slash, lowercased).
    """

    def __init__(self, commands: dict[str, tuple[str, ParamsFactory]]) -> None:
        self._commands = commands

    def match(self, envelope: Any, content: str) -> tuple[str, str, ParamsFactory] | None:
        head = content.strip().split(maxsplit=1)[0] if content.strip() else ""
        source_kind = getattr(envelope, "source_kind", None)
        source_kind_value = getattr(source_kind, "value", source_kind)
        if source_kind_value != "channel" or not head.startswith("/") or head == "/":
            return None
        bare = head[1:].lower()
        command = self._commands.get(bare)
        return (bare, *command) if command else None

    async def dispatch(
        self,
        *,
        envelope: Any,
        message_content: str,
        rpc_dispatcher: Any,
        context_factory: Any,
    ) -> OutgoingMessage | None:
        match = self.match(envelope, message_content)
        if match is None:
            return None
        name, method, params_factory = match
        res = await rpc_dispatcher.dispatch(
            f"channel-command:{name}",
            method,
            params_factory(envelope),
            context_factory(envelope),
        )
        denied = bool(not res.ok and getattr(res.error, "code", "") == "UNAUTHORIZED")
        reason = "" if res.ok else f": {getattr(res.error, 'message', 'command failed')}"
        state = "completed" if res.ok else ("denied" if denied else "failed")
        return OutgoingMessage(
            content=f"/{name} {state}{reason}",
            reply_to=envelope.thread_id or envelope.channel_id,
            metadata={"command": name, "method": method, "denied": denied},
        )


def _build_default_command_table() -> dict[str, tuple[str, ParamsFactory]]:
    """Project the unified registry's CHANNEL surface into the dispatcher table.

    Inserts both the canonical command name and any declared aliases under
    their bare (slash-stripped, lowercase) form so an alias advertised via
    ``commands.list_for_surface`` actually dispatches when typed by a
    channel user. Skips ``CommandDef`` entries that lack RPC metadata —
    channels require a method + params factory to dispatch.
    """
    table: dict[str, tuple[str, ParamsFactory]] = {}
    for cmd in DEFAULT_REGISTRY.for_surface(Surface.CHANNEL):
        if cmd.rpc_method is None or cmd.rpc_params is None:
            continue
        for word in cmd.words():
            table[word.lstrip("/").lower()] = (cmd.rpc_method, cmd.rpc_params)
    return table


DEFAULT_COMMAND_REGISTRY = CommandRegistry(_build_default_command_table())
