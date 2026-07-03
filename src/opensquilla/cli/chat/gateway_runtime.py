"""Gateway chat runtime for the WebSocket-backed chat path.

This module owns gateway session setup and input dispatch. It is kept separate
from the concrete terminal app so `chat_cmd.py` can stay as CLI entrypoint and
compatibility wiring.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from opensquilla.cli.chat.output import ChatOutputHandle
from opensquilla.cli.chat.session_context import GatewayRuntimeScope, GatewaySessionContext
from opensquilla.cli.chat.session_state import ChatSessionState
from opensquilla.cli.chat.turn import TurnResult

GatewayRuntimeNoticeKind = Literal[
    "created",
    "resumed",
    "resume_model_ignored",
    "model",
    "welcome",
    "goodbye",
    "unknown_command",
    "error",
]


@dataclass(frozen=True)
class GatewayRuntimeNotice:
    kind: GatewayRuntimeNoticeKind
    session_key: str | None = None
    model: str | None = None
    message: str | None = None


class GatewayClientLike(Protocol):
    async def call(self, method: str, params: dict | None = None) -> Any: ...

    async def create_session(
        self,
        agent_id: str = "main",
        model: str | None = None,
        display_name: str | None = None,
    ) -> str: ...

    async def list_sessions(self, limit: int = 50) -> dict[str, Any]: ...

    async def resolve_session(self, key: str) -> dict[str, Any]: ...

    async def delete_sessions(self, keys: list[str]) -> dict[str, Any]: ...

    async def reset_session(self, key: str) -> dict[str, Any]: ...

    async def compact_session(self, key: str) -> dict[str, Any]: ...

    async def list_models(
        self,
        provider: str | None = None,
        capabilities: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...

    async def patch_session(self, key: str, **fields: Any) -> dict[str, Any]: ...

    async def usage_status(self) -> dict[str, Any]: ...

    async def upload_file(self, path: Path, mime: str, name: str) -> str: ...

    def send_message(
        self,
        session_key: str,
        message: str,
        attachments: list[dict] | None = None,
        elevated: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def resolve_approval(
        self,
        approval_id: str,
        approved: bool,
        *,
        allow_always: bool = False,
        choice: str | None = None,
    ) -> Any: ...

    async def abort_session(self, key: str) -> dict[str, Any]: ...


class GatewayRunInputLoop(Protocol):
    async def __call__(
        self,
        *,
        scope: GatewayRuntimeScope,
        dispatch: Callable[[str], Coroutine[Any, Any, bool]],
        abort_active_turn: Callable[[], Awaitable[None]] | None = None,
    ) -> None: ...


class GatewayStreamResponse(Protocol):
    async def __call__(
        self,
        client: GatewayClientLike,
        session_key: str,
        message: str,
        elevated_state: dict[str, str | None] | None = None,
        attachments: list[dict] | None = None,
        *,
        tui_output: ChatOutputHandle | None = None,
    ) -> TurnResult: ...


class GatewayHandleSlashCommand(Protocol):
    async def __call__(
        self,
        cmd: str,
        state: ChatSessionState,
        client: GatewayClientLike,
        elevated_state: dict[str, str | None],
        *,
        tui_output: ChatOutputHandle | None = None,
    ) -> bool: ...


@dataclass(frozen=True)
class GatewayRuntimeDependencies:
    stream_response: GatewayStreamResponse
    handle_slash_command: GatewayHandleSlashCommand
    run_input_loop: GatewayRunInputLoop
    get_tui_output: Callable[[GatewayRuntimeScope], ChatOutputHandle | None]
    is_exit_command: Callable[[str], bool]
    notify: Callable[[GatewayRuntimeNotice], None]


async def run_gateway_chat(
    *,
    model: str | None,
    session_id: str | None,
    deps: GatewayRuntimeDependencies,
) -> None:
    """Run gateway chat without owning a concrete terminal application."""
    from opensquilla.cli.gateway_client import GatewayClient, GatewayRPCError
    from opensquilla.cli.gateway_rpc import default_gateway_token, default_gateway_url

    client = GatewayClient()
    await client.connect(default_gateway_url(), token=default_gateway_token())

    elevated_state: dict[str, str | None] = {"mode": None}

    try:
        if session_id:
            session_key = session_id
            deps.notify(
                GatewayRuntimeNotice(kind="resumed", session_key=session_key)
            )
            if model:
                deps.notify(GatewayRuntimeNotice(kind="resume_model_ignored"))
        else:
            session_key = await client.create_session(model=model)
            deps.notify(
                GatewayRuntimeNotice(kind="created", session_key=session_key)
            )
            if model:
                deps.notify(GatewayRuntimeNotice(kind="model", model=model))
        state = ChatSessionState(session_key=session_key, model=model)
        try:
            resolved = await asyncio.wait_for(client.resolve_session(session_key), timeout=2.0)
            state.model = resolved.get("model") or state.model
        except Exception:  # noqa: BLE001 - network/timeout; non-fatal
            pass

        session_context = GatewaySessionContext.create(state)
        active_turn_session_key: str | None = None

        deps.notify(GatewayRuntimeNotice(kind="welcome"))

        async def _dispatch_input(user_input: str) -> bool:
            nonlocal active_turn_session_key

            if user_input is None or deps.is_exit_command(user_input):
                deps.notify(GatewayRuntimeNotice(kind="goodbye"))
                return False

            stripped = user_input.strip()
            if not stripped:
                return True

            if stripped.startswith("/"):
                try:
                    handled = await deps.handle_slash_command(
                        stripped,
                        session_context.state,
                        client,
                        elevated_state,
                        tui_output=deps.get_tui_output(session_context.scope),
                    )
                except GatewayRPCError as exc:
                    deps.notify(GatewayRuntimeNotice(kind="error", message=str(exc)))
                    return True
                if handled:
                    session_context.sync_from_state()
                    return True
                deps.notify(GatewayRuntimeNotice(kind="unknown_command"))
                return True

            turn_session_key = session_context.session_key
            active_turn_session_key = turn_session_key
            try:
                result = await deps.stream_response(
                    client,
                    turn_session_key,
                    user_input,
                    elevated_state,
                    tui_output=deps.get_tui_output(session_context.scope),
                )
            except GatewayRPCError as exc:
                deps.notify(GatewayRuntimeNotice(kind="error", message=str(exc)))
                return True
            finally:
                if active_turn_session_key == turn_session_key:
                    active_turn_session_key = None
            session_context.state.model = result.model_after or session_context.model
            session_context.state.transcript.add("user", user_input)
            session_context.state.transcript.add("assistant", result.text)
            session_context.state.usage.apply(result.usage)
            session_context.sync_from_state()
            return True

        def _abort_active_turn() -> Awaitable[None]:
            nonlocal active_turn_session_key
            turn_session_key = active_turn_session_key
            active_turn_session_key = None

            async def _abort_captured_turn() -> None:
                if turn_session_key is None:
                    return
                await client.abort_session(turn_session_key)

            return _abort_captured_turn()

        await deps.run_input_loop(
            scope=session_context.scope,
            dispatch=_dispatch_input,
            abort_active_turn=_abort_active_turn,
        )
    finally:
        await client.close()
