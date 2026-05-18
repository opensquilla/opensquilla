"""Chat command — interactive chat mode with Rich output.

Two modes:
- Default (gateway): Connect to running gateway daemon via WebSocket. Full features.
- --standalone: TurnRunner-based direct mode, no gateway daemon needed.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import getpass
import inspect
import json
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

import typer
from rich.panel import Panel
from rich.table import Table

from opensquilla.cli import attachments as _cli_attachments
from opensquilla.cli.repl.commands import is_exit_command, render_help_table
from opensquilla.cli.repl.prompt import (
    interactive_session,
    prompt_approval,
    queued_input_start_payload,
    user_input_echo_payload,
)
from opensquilla.cli.repl.session_state import ChatSessionState, messages_to_markdown
from opensquilla.cli.repl.signal_handlers import install_chat_signal_handlers
from opensquilla.cli.repl.slash_policy import SlashCategory, classify
from opensquilla.cli.repl.stream import StreamingRenderer, TurnResult, UsageSummary
from opensquilla.cli.ui import ACCENT, ACCENT_HEADER, console, error_panel, notice_panel
from opensquilla.engine.commands import Surface
from opensquilla.execution_status import derive_is_error
from opensquilla.permissions import configured_default_elevated
from opensquilla.session.compaction import (
    build_compaction_config_from_provider,
    call_compact_with_optional_config,
)
from opensquilla.session.compaction_lifecycle import (
    flush_receipt_allows_destructive_compaction,
)
from opensquilla.session.terminal_reply import build_terminal_reply

_CLI_ALLOWED_FILE_MIMES = _cli_attachments.CLI_ALLOWED_FILE_MIMES
_CLI_INLINE_THRESHOLD_BYTES = _cli_attachments.CLI_INLINE_THRESHOLD_BYTES
_PATH_REMOTE_GATEWAY_MESSAGE = _cli_attachments.PATH_REMOTE_GATEWAY_MESSAGE
_CLI_ATTACHMENT_COMPAT_EXPORTS = (_CLI_ALLOWED_FILE_MIMES, _CLI_INLINE_THRESHOLD_BYTES)


def _tool_result_success_from_status(status: Any, *, legacy_is_error: bool) -> bool:
    if isinstance(status, dict):
        return status.get("status") == "success" and not derive_is_error(status)
    return not legacy_is_error

_DEFAULT_STREAM_HEARTBEAT_INTERVAL_SECONDS = 15.0
_DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS = 600.0

# Maximum number of inputs that may queue behind an in-flight turn. When the cap
# is reached, additional Enter presses are rejected
# with a toast and the user must wait for the current turn to finish before
# enqueueing more. Module-level so tests can monkeypatch a tighter cap.
_PENDING_QUEUE_MAX_SIZE = 8

GATEWAY_SLASH_HANDLER_WORDS = frozenset(
    {
        "/approvals",
        "/clear",
        "/compact",
        "/cost",
        "/delete",
        "/elevated",
        "/exit",
        "/file",
        "/forget",
        "/help",
        "/image",
        "/model",
        "/models",
        "/new",
        "/path",
        "/permissions",
        "/quit",
        "/reset",
        "/resume",
        "/session",
        "/sessions",
        "/save",
        "/status",
        "/tool-compress",
        "/usage",
    }
)
STANDALONE_SLASH_HANDLER_WORDS = frozenset(
    {
        "/clear",
        "/compact",
        "/cost",
        "/exit",
        "/help",
        "/image",
        "/model",
        "/new",
        "/path",
        "/quit",
        "/reset",
        "/save",
        "/session",
        "/status",
        "/tool-compress",
    }
)


def _turn_stream_error_message(event: Any) -> str:
    message = getattr(event, "message", "")
    code = str(getattr(event, "code", "") or "").lower()
    message_text = str(message)
    if "timeout" in code or "stream idle" in message_text.lower():
        return build_terminal_reply(
            {
                "status": "timeout",
                "terminal_reason": "timeout",
                "error_class": getattr(event, "code", None),
                "error_message": message_text,
            }
        )
    return message_text


def _timeout_exception_message(exc: BaseException) -> str:
    return build_terminal_reply(
        {
            "status": "timeout",
            "terminal_reason": "timeout",
            "error_class": exc.__class__.__name__,
            "error_message": str(exc),
        }
    )


class _GatewayClientLike(Protocol):
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
    ) -> Any: ...

    async def abort_session(self, key: str) -> dict[str, Any]: ...


def _optional_positive_config_float(config_source: Any, attr: str, default: float) -> float | None:
    config = getattr(config_source, "config", config_source)
    raw = getattr(config, attr, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else None


def _wrap_cli_turn_stream(stream: Any, config_source: Any) -> Any:
    from opensquilla.engine.stream_wrappers import wrap_stream

    return wrap_stream(
        stream,
        idle_timeout=_optional_positive_config_float(
            config_source,
            "agent_stream_idle_timeout_seconds",
            _DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS,
        ),
        heartbeat_interval=_optional_positive_config_float(
            config_source,
            "agent_stream_heartbeat_interval_seconds",
            _DEFAULT_STREAM_HEARTBEAT_INTERVAL_SECONDS,
        ),
        heartbeat_phase="cli",
        heartbeat_message="Still working",
    )


def _resolve_compaction_provider(
    provider_selector: Any,
    model_override: str | None = None,
) -> Any | None:
    if provider_selector is None:
        return None
    selector = provider_selector
    clone = getattr(provider_selector, "clone", None)
    if callable(clone):
        try:
            selector = clone()
        except Exception:  # noqa: BLE001
            selector = provider_selector
    if model_override and selector is not provider_selector:
        override = getattr(selector, "override_model", None)
        if callable(override):
            try:
                override(model_override)
            except Exception:  # noqa: BLE001
                pass
    resolver = getattr(selector, "resolve", None)
    if not callable(resolver):
        return None
    try:
        return resolver()
    except Exception:  # noqa: BLE001
        return None


def _is_approval_or_blocked_result(result: Any) -> bool:
    """Return True when a tool_result payload is an approval/block envelope.

    The tool itself has not finished in those cases — the real outcome arrives
    in a later tool_result with the same tool_use_id once the user approves or
    the call retries. Gating tool_finished() on this prevents ToolCallStrip
    from flushing a run prematurely while the user is being prompted.
    """
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return False
        if not isinstance(parsed, dict):
            return False
        payload = parsed
    elif isinstance(result, dict):
        payload = result
    else:
        return False
    return payload.get("status") in {"approval_required", "approval_pending", "blocked"}


async def _maybe_handle_approval(
    result: Any,
    live: Any,
    resolver: Callable[..., Awaitable[Any]],
    elevated_state: dict[str, str | None] | None = None,
    *,
    surface: Surface = Surface.CLI_GATEWAY,
) -> None:
    """If *result* is an approval-required/pending payload, prompt/notify the user.

    The prompt offers four approval choices:

    * ``o`` / ``y`` — allow once (approve only this specific call)
    * ``a``         — allow always (cache intent for the session lifetime)
    * ``b``         — bypass (approve + flip session into /elevated bypass mode;
                      future destructive ops auto-approve, sensitive paths still
                      hard-blocked)
    * ``d`` / ``n`` — deny

    ``resolver(approval_id, approved, allow_always=...)`` is called with the
    user's decision. The Live display is paused during input and resumed
    afterwards so the prompt isn't mangled by the refresh loop.
    """
    payload: dict[str, Any]
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return
        if not isinstance(parsed, dict):
            return
        payload = parsed
    elif isinstance(result, dict):
        payload = result
    else:
        return

    # Hard-block envelope (sensitive path, etc.) — just show the refusal,
    # no prompt to offer.
    if payload.get("status") == "blocked":
        live.stop()
        try:
            console.print()
            console.print(
                notice_panel(
                    str(payload.get("message", "")),
                    kind="block",
                    command=str(payload.get("command", "")).strip() or None,
                )
            )
        finally:
            live.start()
        return

    status = str(payload.get("status") or "")
    if status not in {"approval_required", "approval_pending"}:
        return
    approval_id = payload.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        return
    command = str(payload.get("command", "")).strip()
    warning = str(payload.get("warning") or payload.get("message") or "").strip()

    live.stop()
    try:
        console.print()
        console.print(
            notice_panel(
                warning,
                kind="warn",
                title="Approval pending" if status == "approval_pending" else "Approval required",
                command=command or "(not shown)",
            )
        )
        console.print(
            "[dim]  [bold]o[/bold]nce    allow this call only[/dim]\n"
            "[dim]  [bold]a[/bold]lways  allow this intent for the session[/dim]\n"
            "[dim]  [bold]b[/bold]ypass  approve + skip future approvals "
            "(sensitive paths still blocked)[/dim]\n"
            "[dim]  [bold]d[/bold]eny    reject[/dim]"
        )
        answer = await prompt_approval("Decision [o/a/b/d]: ", surface=surface)

        flip_to_bypass = False
        # Backwards compatibility: y still means once, n still means deny.
        if answer in ("b", "bypass"):
            approved, allow_always, label = True, True, "Approved + bypass mode"
            flip_to_bypass = True
        elif answer in ("a", "always"):
            approved, allow_always, label = True, True, "Always approved"
        elif answer in ("o", "y", "yes", "once", ""):
            approved, allow_always, label = True, False, "Approved (once)"
        else:
            approved, allow_always, label = False, False, "Denied"

        try:
            await resolver(approval_id, approved, allow_always=allow_always)
            color = "green" if approved else "red"
            if flip_to_bypass:
                if elevated_state is not None:
                    elevated_state["mode"] = "bypass"
                suffix = (
                    " — session now in [red]bypass[/red] mode. "
                    "Sensitive paths still blocked. Use /elevated off to revert."
                )
            elif allow_always:
                suffix = " — future similar intents auto-approve."
            else:
                suffix = ""
            console.print(f"[{color}]{label}[/{color}]{suffix}")
        except Exception as exc:  # pragma: no cover — RPC/queue transport errors
            console.print(f"[red]Failed to resolve approval:[/red] {exc}")
    finally:
        live.start()


def _cli_sender_id() -> str:
    raw = os.environ.get("USER")
    if raw and raw.strip():
        return raw.strip()
    try:
        return getpass.getuser() or "cli-user"
    except Exception:
        return "cli-user"


def _slash_parts(cmd: str, name: str) -> list[str] | None:
    if cmd == name or cmd.startswith(f"{name} "):
        return cmd.split(maxsplit=1)
    return None


def _slash_parts_any(cmd: str, *names: str) -> list[str] | None:
    for name in names:
        parts = _slash_parts(cmd, name)
        if parts is not None:
            return parts
    return None


def _clear_current_cancel() -> None:
    """Keep one Ctrl+C scoped to the active turn under asyncio.run."""
    task = asyncio.current_task()
    if task is not None and hasattr(task, "uncancel"):
        task.uncancel()


async def _run_concurrent_repl(
    *,
    surface: Surface,
    scope: dict[str, Any],
    dispatch: Callable[[str], Coroutine[Any, Any, bool]],
) -> None:
    """Concurrent input/turn loop driven by a long-lived ChatApplication.

    The Application stays attached for the lifetime of the REPL so input
    keystrokes are accepted while a turn task is in flight. New input
    that arrives mid-turn is routed by category (see ``slash_policy``):

    * ``DESTRUCTIVE`` (``/clear`` / ``/reset`` / ``/compact``) — PURGE the
      pending deque, cancel the active turn (await ``CancelledError``),
      then run the handler synchronously (NOT as a turn task — a
      destructive command must not be cancellable by a subsequent Ctrl+G
      while it is the only thing running).
    * ``EXIT`` (``/exit`` / ``/quit``) — drain the pending deque (process
      each queued input in order through ``dispatch``), then dispatch the
      exit command itself which returns ``False`` to terminate the loop.
      Queued user work is preserved across the exit (locked policy).
    * ``STATE_MUTATION`` / ``PURE_INFO`` / ``NON_SLASH`` — enqueue behind
      the in-flight turn (FIFO); when nothing is in flight, spawn a turn
      task and await it.

    Ctrl+G is bound on the Application's key bindings
    (``app.py:_build_key_bindings``) and invokes a cancel callback
    registered here that cancels the in-flight turn task. Per
    ``engine/runtime.py:2318-2366``, cancellation lands at the next
    ``await`` point in the turn task — no engine modification required.
    """
    pending_commands: collections.deque[str] = collections.deque()

    async with interactive_session(
        surface=surface,
        model=scope.get("model"),
        session_id=scope.get("session_key"),
    ) as handle:
        chat_app = handle.application
        # Expose the active ChatApplication to dispatch closures so the
        # production stream paths can route token writes through the
        # output mutex (`StreamingRenderer.aappend_text`) and so
        # ``_maybe_handle_approval`` can prompt against this surface's own
        # Application instead of the default gateway lookup.
        scope["chat_app"] = chat_app
        turn_task: asyncio.Task[bool] | None = None

        def _schedule_gateway_abort() -> None:
            client = scope.get("client")
            session_key = scope.get("session_key")
            if not session_key or client is None or not hasattr(client, "abort_session"):
                return

            async def _abort() -> None:
                with contextlib.suppress(Exception):
                    await client.abort_session(str(session_key))

            asyncio.create_task(_abort())

        def _cancel_inflight_turn() -> None:
            # Registered as the Ctrl+G callback. The task may have completed
            # between the keypress and the callback firing — guard with
            # `done()` so cancel() on a finished task is a no-op.
            task = turn_task
            if task is not None and not task.done():
                if surface is Surface.CLI_GATEWAY:
                    _schedule_gateway_abort()
                task.cancel()

        chat_app.set_cancel_callback(_cancel_inflight_turn)

        def _shutdown_drain_then_exit() -> None:
            # Registered as the Ctrl+C double-press callback. Emit
            # EOF on the submit queue so the main loop's existing EOF
            # path runs: drain pending → finalize in-flight turn → print
            # "Goodbye." → return. We do NOT cancel the turn — the
            # Ctrl-D / EOF contract preserves queued work and finishes
            # the active turn rather than aborting it. Guarded with
            # `getattr` so unit tests faking a minimal ChatApplication
            # without `_emit_eof` cannot tear down the binding.
            emit_eof = getattr(chat_app, "_emit_eof", None)
            if callable(emit_eof):
                emit_eof()

        # `set_shutdown_callback` is owned by ChatApplication; unit tests
        # using a minimal fake skip it silently via getattr so existing
        # fakes do not have to grow a method they never exercise.
        _set_shutdown_cb = getattr(chat_app, "set_shutdown_callback", None)
        if callable(_set_shutdown_cb):
            _set_shutdown_cb(_shutdown_drain_then_exit)

        # Install SIGWINCH (redraw on resize) + SIGTSTP (block
        # Ctrl-Z mid-turn; default at idle) handlers. Platform-guarded
        # inside the install helper — Windows skips silently. Lifetime
        # is bounded to the chat loop via try/finally so subsequent
        # tests / REPL runs are not polluted. ``getattr`` on the inner
        # prompt-toolkit Application lets unit tests that fake the
        # ChatApplication surface skip signal wiring without having to
        # stub a full Application — the production path always sees a
        # real Application with ``invalidate``.
        def _is_turn_in_flight() -> bool:
            return turn_task is not None and not turn_task.done()

        _pt_app = getattr(chat_app, "application", None)
        _on_resize_cb = getattr(_pt_app, "invalidate", lambda: None)
        _uninstall_signals = install_chat_signal_handlers(
            loop=asyncio.get_running_loop(),
            on_resize=_on_resize_cb,
            is_turn_in_flight=_is_turn_in_flight,
        )

        task_name = f"chat-turn-{surface.value if hasattr(surface, 'value') else surface}"

        async def _await_turn_or_cancel() -> bool:
            """Await the in-flight ``turn_task`` and surface cancellation.

            Returns ``True`` to keep the loop going (including the
            "user pressed Ctrl+G mid-turn" case) and ``False`` when the
            dispatch signalled exit.
            """
            nonlocal turn_task
            current = turn_task
            if current is None:
                return True
            try:
                keep_going = await current
            except asyncio.CancelledError:
                _clear_current_cancel()
                console.print("[yellow]Cancelled.[/yellow]")
                keep_going = True
            finally:
                turn_task = None
            return keep_going

        # Persistent next-line read armed exactly once at a time. The
        # main loop races this against any in-flight turn_task via
        # asyncio.wait so a destructive `/clear` arriving mid-turn can
        # actually preempt the turn. When turn_task
        # finishes first the next_line read stays armed for the next
        # iteration, so no input is dropped.
        next_line_task: asyncio.Task[str | None] | None = None

        async def _drop_next_line() -> None:
            """Cancel the pending next-line read on shutdown paths."""
            nonlocal next_line_task
            if next_line_task is None:
                return
            if not next_line_task.done():
                next_line_task.cancel()
                try:
                    await next_line_task
                except BaseException:  # noqa: BLE001 - shutdown path
                    pass
            next_line_task = None

        try:
            while True:
                if next_line_task is None:
                    next_line_task = asyncio.create_task(
                        handle.next_line(),
                        name=f"chat-input-{task_name}",
                    )

                # Race the pending next_line read against any in-flight
                # turn. Both wakeups are valid; we always process the
                # turn completion (if any) first so destructive routing
                # sees a clean state.
                waitables: set[asyncio.Task] = {next_line_task}
                if turn_task is not None and not turn_task.done():
                    waitables.add(turn_task)
                await asyncio.wait(
                    waitables, return_when=asyncio.FIRST_COMPLETED
                )

                # Drain a finished turn task before consuming any input.
                if turn_task is not None and turn_task.done():
                    keep_going = await _await_turn_or_cancel()
                    if not keep_going:
                        await _drop_next_line()
                        return
                    # Promote-and-race: if queued work waits behind the
                    # finished turn, spawn the next queued item as a fresh
                    # turn_task and continue. The next loop iteration arms
                    # a fresh next_line read and races it against the
                    # promoted turn, so a destructive `/clear` arriving
                    # while the promoted turn is running can still preempt
                    # it via the same code path that preempts user-typed
                    # turns. Without this, awaiting each queued item to
                    # completion inside a private drain loop made queued
                    # turns un-preemptible until the deque emptied.
                    if pending_commands:
                        queued = pending_commands.popleft()
                        await _echo_queued_turn_start(chat_app)
                        turn_task = asyncio.create_task(
                            dispatch(queued), name=task_name
                        )
                        continue
                    # If next_line is still armed (turn won the race), loop
                    # so the next iteration either reads the input or
                    # waits on it alongside any newly-spawned turn.
                    if not next_line_task.done():
                        continue

                # next_line_task is done (or finished alongside turn) —
                # consume it.
                if not next_line_task.done():
                    # Defensive: should not happen because asyncio.wait
                    # only returns when at least one waitable completes.
                    continue
                user_input = next_line_task.result()
                next_line_task = None

                if user_input is None:
                    # Ctrl-D / EOF — drain pending then any in-flight turn
                    # before exiting so queued work is preserved and no
                    # task is left dangling on the loop.
                    if turn_task is not None and not turn_task.done():
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            pass
                        turn_task = None
                    # Shutdown drain: process queued work serially. This is
                    # an intentional shutdown-time drain — preemption is
                    # NOT desired because the user has signalled exit and
                    # queued user work must run to completion (locked
                    # slash policy) before the loop returns.
                    while pending_commands:
                        queued = pending_commands.popleft()
                        await _echo_queued_turn_start(chat_app)
                        turn_task = asyncio.create_task(
                            dispatch(queued), name=task_name
                        )
                        keep_going = await _await_turn_or_cancel()
                        if not keep_going:
                            return
                    console.print("[yellow]Goodbye.[/yellow]")
                    return

                # Echo the submitted line into the scrollback. The
                # persistent `Application` uses a `BufferControl` whose
                # accept handler clears the buffer without echoing, so
                # without this the assistant reply appears with no
                # question above it.
                await _echo_user_input(chat_app, user_input)

                category = classify(user_input)

                if category is SlashCategory.DESTRUCTIVE:
                    # Locked slash policy: destructive commands invalidate
                    # everything queued behind them AND the active turn.
                    # 1) PURGE the pending deque first so queued state-
                    #    mutation slash commands do not race the handler.
                    # 2) Cancel the active turn task (if any) and swallow
                    #    CancelledError — we want the destructive handler to
                    #    run, not surface a cancellation notice.
                    # 3) Run the destructive handler synchronously (NOT as a
                    #    turn task). Destructive commands MUST run to
                    #    completion; a follow-up Ctrl+G is meaningless here.
                    pending_commands.clear()
                    if turn_task is not None and not turn_task.done():
                        turn_task.cancel()
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            _clear_current_cancel()
                        turn_task = None
                    keep_going = await dispatch(user_input)
                    if not keep_going:
                        return
                    continue

                if category is SlashCategory.EXIT:
                    # Locked slash policy: exit drains pending work
                    # before terminating, mirroring Ctrl-D semantics. Queued
                    # user inputs must run before the loop exits.
                    if turn_task is not None and not turn_task.done():
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            _clear_current_cancel()
                        turn_task = None
                    # Shutdown drain: process queued work serially. This is
                    # an intentional shutdown-time drain — preemption is
                    # NOT desired because the user has signalled exit and
                    # queued user work must run to completion (locked
                    # slash policy) before the loop returns.
                    while pending_commands:
                        queued = pending_commands.popleft()
                        await _echo_queued_turn_start(chat_app)
                        turn_task = asyncio.create_task(
                            dispatch(queued), name=task_name
                        )
                        keep_going = await _await_turn_or_cancel()
                        if not keep_going:
                            return
                    # The dispatch closure routes /exit and /quit through
                    # is_exit_command and returns False — that signal
                    # terminates the loop. Run synchronously so the
                    # "Goodbye." notice lands in order.
                    keep_going = await dispatch(user_input)
                    if not keep_going:
                        return
                    # Defensive: a dispatch closure that doesn't recognise
                    # /exit (shouldn't happen given the shared registry)
                    # falls through to the normal loop.
                    continue

                # Enqueue path (STATE_MUTATION, PURE_INFO, NON_SLASH all reach
                # here). If a turn is in flight, append to pending FIFO and
                # let the next loop iteration race the read against it;
                # otherwise spawn the dispatch as a child task. We DO NOT
                # await it inline — the next iteration's asyncio.wait
                # services both the in-flight turn and the next read so
                # destructive inputs can preempt the turn.
                if turn_task is not None and not turn_task.done():
                    if len(pending_commands) >= _PENDING_QUEUE_MAX_SIZE:
                        # Reject queue overflow with a toast.
                        # The user must wait for the current turn before
                        # enqueuing more. The rejected input is dropped on
                        # the floor; this matches the locked decision over
                        # the alternative of silent oldest-eviction or
                        # blocking the input task.
                        console.print(
                            f"[yellow]Queue full ({_PENDING_QUEUE_MAX_SIZE} items)."
                            " Wait for the current turn to complete.[/yellow]"
                        )
                        continue
                    pending_commands.append(user_input)
                    continue

                turn_task = asyncio.create_task(dispatch(user_input), name=task_name)
                # Fall through to the top of the loop; the next iteration
                # arms a fresh next_line and races it against turn_task.
        finally:
            # Drop the chat_app handle from scope so callers that retain
            # a reference to ``scope`` after the REPL exits cannot reach a
            # torn-down Application.
            scope.pop("chat_app", None)
            # Clear the cancel callback before the Application tears down so a
            # stale binding cannot reach a finished task on the next session.
            chat_app.set_cancel_callback(None)
            # Clear the shutdown callback for the same reason — a
            # stale binding firing on the next session would emit EOF on
            # an unrelated submit queue. `getattr` keeps minimal-fake
            # tests happy.
            _clear_shutdown_cb = getattr(chat_app, "set_shutdown_callback", None)
            if callable(_clear_shutdown_cb):
                _clear_shutdown_cb(None)
            await _drop_next_line()
            # Restore previous signal handlers so subsequent
            # REPL runs / tests start from a clean signal-handler state.
            try:
                _uninstall_signals()
            except Exception:
                pass


def _quiet_logs_for_interactive_chat() -> None:
    """Filter chat-process log output to WARNING+ during the interactive REPL.

    The chat surface shares a single TTY with two log streams:

    * structlog events from OpenSquilla itself (default ``PrintLoggerFactory``
      writes to stderr at ``INFO``).
    * stdlib ``logging`` events from third-party deps that initialise on first
      use — most visibly ``jieba``, whose default logger emits a multi-line
      ``Building prefix dict.../Loading model.../Prefix dict has been built``
      block at ``DEBUG`` on first segmentation call.

    Both streams interleave with the streamed model reply and bury the
    conversation. Raising the minimum level on both surfaces keeps the chat
    pane focused on the conversation while still surfacing real warnings and
    errors. Override via ``OPENSQUILLA_LOG_LEVEL`` (``debug`` / ``info`` /
    ``warning`` / ``error``).
    """
    import logging  # noqa: PLC0415 — keep top-level imports minimal

    import structlog  # noqa: PLC0415

    level_name = os.environ.get("OPENSQUILLA_LOG_LEVEL", "warning").strip().upper()
    level = getattr(logging, level_name, logging.WARNING)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )
    logging.getLogger().setLevel(level)
    # ``jieba`` (CJK tokenizer, used by the memory layer) installs its own
    # ``StreamHandler`` on ``default_logger`` and calls ``setLevel(DEBUG)``
    # during import. A pre-import ``setLevel`` would be overridden when jieba
    # later imports; force the import here, then pin the level back down and detach
    # the in-tree handler so the init
    # chatter ("Building prefix dict ...") cannot reach the TTY at all.
    try:
        import jieba  # type: ignore[import-untyped]  # noqa: F401, PLC0415
    except ImportError:
        pass
    else:
        jieba_logger = logging.getLogger("jieba")
        jieba_logger.setLevel(level)
        jieba_logger.propagate = False
        for handler in list(jieba_logger.handlers):
            jieba_logger.removeHandler(handler)


def _clear_screen_for_interactive_chat() -> None:
    """Start the persistent chat surface on a clean terminal page."""
    if console.is_terminal:
        console.clear()


def run_chat(
    model: str = typer.Option("", "--model", "-m", help="Model override (provider/model)"),
    session_id: str = typer.Option("", "--session", "-s", help="Resume session ID"),
    standalone: bool = typer.Option(False, "--standalone", help="Direct Agent without gateway"),
    workspace: str = typer.Option("", "--workspace", help="Workspace root for standalone tools"),
    workspace_strict: bool | None = typer.Option(
        None,
        "--workspace-strict/--no-workspace-strict",
        help="Restrict read-side file tools to --workspace in standalone mode",
    ),
    timeout: float | None = None,
) -> None:
    """Start interactive chat with the agent.

    Default: connects to the running gateway daemon for full features
    (tools, skills, session persistence). Use --standalone for direct
    TurnRunner mode without a gateway daemon.
    """
    _timeout = timeout
    if not sys.stdin.isatty() or not console.is_terminal:
        typer.echo(
            "opensquilla chat is interactive; use `opensquilla agent -m '...'` for non-TTY.",
            err=True,
        )
        raise typer.Exit(2)
    _quiet_logs_for_interactive_chat()
    _clear_screen_for_interactive_chat()
    if standalone:
        console.print(
            Panel(
                f"[bold {ACCENT}]OpenSquilla Chat[/bold {ACCENT}]\n"
                "[dim]Enter sends. Ctrl+C clears input or cancels the current turn. "
                "Ctrl+D exits. /help lists commands.[/dim]",
                title="OpenSquilla",
                border_style=ACCENT,
            )
        )
        if model:
            console.print(f"[dim]Model: {model}[/dim]")
        if session_id:
            console.print(f"[dim]Session: {session_id}[/dim]")
        asyncio.run(
            _standalone_repl(
                model=model or None,
                session_id=session_id or None,
                workspace=workspace or None,
                workspace_strict=workspace_strict,
                timeout=_timeout,
            )
        )
    else:
        # Default: gateway mode — full agent capabilities
        if workspace or workspace_strict is not None:
            console.print(
                "[yellow]Note:[/yellow] --workspace only affects --standalone chat. "
                "In gateway mode, /path requires the path to be visible to the "
                "gateway runtime; use /file to upload from this CLI machine for "
                "remote gateways."
            )
        asyncio.run(
            _gateway_chat(
                model=model or None,
                session_id=session_id or None,
            )
        )


# ---------------------------------------------------------------------------
# Standalone mode (--standalone) — TurnRunner + build_services, no daemon
# ---------------------------------------------------------------------------


async def _read_standalone_transcript(
    session_manager: Any,
    session_key: str,
) -> list[Any] | None:
    """Read the durable transcript before a destructive standalone command."""
    if session_manager is None:
        return []
    for method_name in ("get_transcript", "read_transcript"):
        reader = getattr(session_manager, method_name, None)
        if not callable(reader):
            continue
        try:
            result = reader(session_key)
            if inspect.isawaitable(result):
                result = await result
        except KeyError:
            return []
        except Exception:  # noqa: BLE001
            return None
        return list(result or [])
    return None


async def _flush_before_standalone_rewrite(
    svc: Any,
    session_key: str,
    *,
    operation: str,
) -> bool:
    """Fail closed before reset; compact can continue on flush degradation."""
    compaction_operation = operation.strip().lower() == "compact"
    transcript = await _read_standalone_transcript(
        getattr(svc, "session_manager", None),
        session_key,
    )
    if transcript is None:
        if compaction_operation:
            console.print(
                f"[yellow]{operation}: could not inspect durable transcript; "
                "continuing with compaction only.[/yellow]"
            )
            return True
        console.print(
            f"[yellow]{operation} aborted: could not inspect the durable transcript.[/yellow]"
        )
        return False
    if not transcript:
        return True

    flush_service = getattr(svc, "flush_service", None)
    if flush_service is None:
        if compaction_operation:
            console.print(
                f"[yellow]{operation}: flush service is unavailable; "
                "continuing with compaction only.[/yellow]"
            )
            return True
        console.print(
            f"[yellow]{operation} aborted: flush service is unavailable and "
            "the durable transcript is non-empty.[/yellow]"
        )
        return False

    try:
        receipt = await flush_service.execute(
            transcript,
            session_key,
            agent_id="main",
            timeout=30.0,
            message_window=0,
            segment_mode="auto",
        )
    except Exception as exc:  # noqa: BLE001
        if compaction_operation:
            console.print(
                f"[yellow]{operation}: flush failed ({exc}); "
                "continuing with compaction only.[/yellow]"
            )
            return True
        console.print(f"[yellow]{operation} aborted: flush failed ({exc}).[/yellow]")
        return False

    if not flush_receipt_allows_destructive_compaction(receipt):
        if compaction_operation:
            error = getattr(receipt, "error", None) or "degraded receipt"
            console.print(
                f"[yellow]{operation}: flush failed ({error}); "
                "continuing with compaction only.[/yellow]"
            )
            return True
        error = getattr(receipt, "error", None) or "unknown error"
        console.print(f"[yellow]{operation} aborted: flush failed ({error}).[/yellow]")
        return False
    return True


async def _standalone_repl(
    model: str | None,
    session_id: str | None,
    workspace: str | None = None,
    workspace_strict: bool | None = None,
    timeout: float | None = None,
) -> None:
    """Interactive REPL backed by TurnRunner (full tools, skills, session persistence)."""
    from opensquilla.cli.agent_cmd import _resolve_workspace_strict
    from opensquilla.gateway import build_services, build_turn_runner_from_services
    from opensquilla.gateway.routing import build_cli_route_envelope, tool_context_from_envelope

    svc = await build_services()
    session_manager = svc.session_manager
    if session_manager is None:
        raise RuntimeError("standalone chat requires session manager")
    session_key = session_id or f"agent:main:standalone:{uuid4().hex[:8]}"
    await session_manager.get_or_create(session_key, agent_id="main")
    active_workspace = workspace or getattr(svc.config, "workspace_dir", None)
    effective_workspace_strict = _resolve_workspace_strict(
        cli_value=workspace_strict,
        config_value=getattr(svc.config, "workspace_strict", None),
        entrypoint_default=bool(active_workspace),
    )

    def _build_tool_ctx(active_session_key: str) -> object:
        route_envelope = build_cli_route_envelope(
            session_key=active_session_key,
            agent_id="main",
            channel_id="cli:chat",
            sender_id=_cli_sender_id(),
            source_name="chat",
        )
        return tool_context_from_envelope(
            route_envelope,
            is_owner=True,
            workspace_dir=active_workspace,
            workspace_strict=effective_workspace_strict,
            default_elevated=configured_default_elevated(svc.config),
        )

    tool_ctx = _build_tool_ctx(session_key)
    state = ChatSessionState(session_key=session_key, model=model)

    turn_runner = build_turn_runner_from_services(svc)

    # Mutable scope shared with the per-input helper so a /new command can
    # rotate session_key / tool_ctx / state in place without redefining the
    # helper. Wrapping in a single-element list is the simplest way to
    # rebind without `nonlocal` chains across an async closure.
    scope: dict[str, Any] = {
        "session_key": session_key,
        "tool_ctx": tool_ctx,
        "state": state,
        "model": model,
    }

    async def _dispatch_input(user_input: str) -> bool:
        """Process one input line. Returns True to keep looping, False to exit.

        Slash handlers run synchronously inside the loop so the concurrent
        routing policy can decide whether to cancel, execute, or enqueue.
        """
        if user_input is None or is_exit_command(user_input):
            console.print("[yellow]Goodbye.[/yellow]")
            return False

        stripped = user_input.strip()
        if not stripped:
            return True

        active_state: ChatSessionState = scope["state"]
        active_session_key: str = scope["session_key"]
        active_tool_ctx = scope["tool_ctx"]
        active_model: str | None = scope["model"]

        if stripped.startswith("/"):
            if stripped == "/help":
                console.print(render_help_table(Surface.CLI_STANDALONE))
                return True
            if parts := _slash_parts(stripped, "/new"):
                new_session_key = f"agent:main:standalone:{uuid4().hex[:8]}"
                await session_manager.get_or_create(new_session_key, agent_id="main")
                scope["session_key"] = new_session_key
                scope["tool_ctx"] = _build_tool_ctx(new_session_key)
                scope["state"] = ChatSessionState(session_key=new_session_key, model=active_model)
                title = parts[1].strip() if len(parts) > 1 else None
                label = f" ({title})" if title else ""
                console.print(f"[green]Started new session{label}:[/green] {new_session_key}")
                return True
            if stripped in {"/status", "/session"}:
                console.print(
                    f"[{ACCENT}]session[/] [dim]{active_state.session_key}[/dim]\n"
                    f"[{ACCENT}]model[/] [dim]{active_state.model or 'default'}[/dim]"
                )
                return True
            if stripped == "/models":
                console.print("[yellow]/models requires gateway mode.[/yellow]")
                return True
            if parts := _slash_parts(stripped, "/model"):
                if len(parts) == 1:
                    console.print(f"[dim]model={active_state.model or 'default'}[/dim]")
                else:
                    new_model = parts[1].strip()
                    scope["model"] = new_model
                    active_state.model = new_model
                    console.print(f"[green]model:[/green] {new_model}")
                return True
            if stripped == "/cost":
                console.print(active_state.usage.render())
                return True
            if _slash_parts(stripped, "/tool-compress"):
                await _handle_tool_compress_command(stripped, config=svc.config)
                return True
            if stripped in {"/clear", "/reset"}:
                if svc.session_manager is not None:
                    safe_to_reset = await _flush_before_standalone_rewrite(
                        svc,
                        active_session_key,
                        operation="Reset",
                    )
                    if not safe_to_reset:
                        return True
                    await svc.session_manager.truncate(active_session_key, max_messages=0)
                active_state.transcript.clear()
                active_state.usage.reset()
                console.print(f"[{ACCENT}]cleared[/] [dim]{active_state.session_key}[/dim]")
                return True
            if stripped == "/compact":
                if svc.session_manager is not None:
                    safe_to_compact = await _flush_before_standalone_rewrite(
                        svc,
                        active_session_key,
                        operation="Compact",
                    )
                    if not safe_to_compact:
                        return True
                    context_window = (
                        getattr(svc.config, "context_budget_tokens", 100_000)
                        if svc.config is not None
                        else 100_000
                    )
                    compaction_config = build_compaction_config_from_provider(
                        _resolve_compaction_provider(svc.provider_selector, active_model),
                        model_override=active_model,
                        compaction_config=getattr(svc.config, "compaction", None),
                    )
                    compact_with_result = getattr(
                        svc.session_manager, "compact_with_result", None
                    )
                    if callable(compact_with_result):
                        result = await compact_with_result(
                            active_session_key,
                            context_window,
                            compaction_config,
                        )
                        summary = getattr(result, "summary", "") or ""
                        token_stats = (
                            f"{getattr(result, 'tokens_before', 0)} -> "
                            f"{getattr(result, 'tokens_after', 0)} tokens, "
                            f"{getattr(result, 'remaining_budget_tokens', 0)} remaining, "
                            f"{getattr(result, 'summary_source', 'unknown')}"
                        )
                    else:
                        summary = await call_compact_with_optional_config(
                            svc.session_manager.compact,
                            active_session_key,
                            context_window,
                            compaction_config,
                        )
                        token_stats = f"summary {len(summary)} chars"
                    if summary:
                        console.print(
                            f"[{ACCENT}]compacted[/] "
                            f"[dim]{token_stats}[/dim]"
                        )
                    else:
                        console.print(
                            f"[{ACCENT}]compact skipped[/] "
                            "[dim]context already within budget[/dim]"
                        )
                else:
                    console.print("[yellow]No session manager available.[/yellow]")
                return True
            if _slash_parts(stripped, "/save"):
                _save_transcript_command(stripped, active_state)
                return True
            if parts := _slash_parts(stripped, "/image"):
                if len(parts) == 1 or not parts[1].strip():
                    console.print("[red]Usage: /image <path> [prompt][/red]")
                    return True
                result = await _handle_image_command_turnrunner(
                    turn_runner,
                    active_session_key,
                    active_tool_ctx,
                    stripped,
                    model=active_model,
                    svc=svc,
                    timeout=timeout,
                    chat_app=scope.get("chat_app"),
                )
                active_state.transcript.add("user", _image_prompt_from_command(stripped))
                active_state.transcript.add("assistant", result.text)
                active_state.usage.apply(result.usage)
                return True
            if parts := _slash_parts(stripped, "/path"):
                if len(parts) == 1 or not parts[1].strip():
                    console.print("[red]Usage: /path <path> [prompt][/red]")
                    return True
                try:
                    prompt, attachments = _path_prompt_and_attachments(stripped)
                except ValueError as exc:
                    console.print(error_panel(str(exc)))
                    return True
                if attachments:
                    console.print(error_panel("/path must not create attachments."))
                    return True
                result = await _stream_response_turnrunner(
                    turn_runner,
                    active_session_key,
                    active_tool_ctx,
                    prompt,
                    model=active_model,
                    svc=svc,
                    timeout=timeout,
                    chat_app=scope.get("chat_app"),
                )
                active_state.transcript.add("user", prompt)
                active_state.transcript.add("assistant", result.text)
                active_state.usage.apply(result.usage)
                return True
            console.print("[red]Unknown command.[/red] [dim]Use /help.[/dim]")
            return True

        result = await _stream_response_turnrunner(
            turn_runner,
            active_session_key,
            active_tool_ctx,
            user_input,
            model=active_model,
            svc=svc,
            timeout=timeout,
            chat_app=scope.get("chat_app"),
        )
        active_state.transcript.add("user", user_input)
        active_state.transcript.add("assistant", result.text)
        active_state.usage.apply(result.usage)
        return True

    try:
        await _run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope=scope,
            dispatch=_dispatch_input,
        )
    finally:
        await svc.close()


# ---------------------------------------------------------------------------
# Gateway mode (--gateway) — connect to running daemon via WebSocket
# ---------------------------------------------------------------------------


async def _gateway_chat(model: str | None, session_id: str | None) -> None:
    """Chat via gateway daemon. Full features: tools, skills, session persistence."""
    from opensquilla.cli.gateway_client import GatewayClient, GatewayRPCError

    client = GatewayClient()
    await client.connect()

    elevated_state: dict[str, str | None] = {"mode": None}

    try:
        if session_id:
            session_key = session_id
            console.print(f"[dim]Connected to gateway. Resuming session: {session_key}[/dim]")
            if model:
                console.print(
                    "[yellow]Note: --model is honored only at session creation; "
                    "ignored when resuming a session.[/yellow]"
                )
        else:
            session_key = await client.create_session(model=model)
            console.print(f"[dim]Connected to gateway. Session: {session_key}[/dim]")
            if model:
                console.print(f"[dim]Model: {model}[/dim]")
        state = ChatSessionState(session_key=session_key, model=model)
        # Best-effort: latch the gateway-resolved model name into state so the
        # prompt label shows the real model identifier from the first keystroke.
        try:
            _resolved = await asyncio.wait_for(
                client.resolve_session(session_key), timeout=2.0
            )
            state.model = _resolved.get("model") or state.model
        except Exception:  # noqa: BLE001 — network/timeout; non-fatal
            pass

        # Interactive REPL via gateway
        console.print(
            Panel(
                f"[bold {ACCENT}]OpenSquilla Chat[/bold {ACCENT}]\n"
                "[dim]Enter sends. Ctrl+C cancels the current turn or clears input. "
                "Ctrl+D exits. /help lists commands.[/dim]",
                title="Gateway",
                border_style=ACCENT,
            )
        )

        scope: dict[str, Any] = {
            "session_key": session_key,
            "state": state,
            "model": model,
        }

        async def _dispatch_input(user_input: str) -> bool:
            """Process one input line. Returns True to keep looping, False to exit."""
            if user_input is None or is_exit_command(user_input):
                console.print("[yellow]Goodbye.[/yellow]")
                return False

            stripped = user_input.strip()
            if not stripped:
                return True

            active_state: ChatSessionState = scope["state"]
            active_session_key: str = scope["session_key"]

            if stripped.startswith("/"):
                try:
                    handled = await _handle_gateway_slash_command(
                        stripped,
                        active_state,
                        client,
                        elevated_state,
                        chat_app=scope.get("chat_app"),
                    )
                except GatewayRPCError as exc:
                    console.print(error_panel(str(exc)))
                    return True
                if handled:
                    # Slash commands may have rotated the session key / model;
                    # mirror those mutations back into the scope dict so the
                    # next turn sees the latest values.
                    scope["session_key"] = active_state.session_key
                    scope["model"] = active_state.model
                    return True
                console.print("[red]Unknown command.[/red] [dim]Use /help.[/dim]")
                return True

            try:
                result = await _stream_response_gateway(
                    client,
                    active_session_key,
                    user_input,
                    elevated_state,
                    chat_app=scope.get("chat_app"),
                )
            except GatewayRPCError as exc:
                console.print(error_panel(str(exc)))
                return True
            active_state.model = result.model_after or active_state.model
            active_state.transcript.add("user", user_input)
            active_state.transcript.add("assistant", result.text)
            active_state.usage.apply(result.usage)
            return True

        await _run_concurrent_repl(
            surface=Surface.CLI_GATEWAY,
            scope=scope,
            dispatch=_dispatch_input,
        )
    finally:
        await client.close()


async def _handle_gateway_slash_command(
    cmd: str,
    state: ChatSessionState,
    client: _GatewayClientLike,
    elevated_state: dict[str, str | None],
    *,
    chat_app: Any | None = None,
) -> bool:
    """Handle gateway-mode slash commands. Returns False for unknown commands.

    ``chat_app`` is the active ``ChatApplication`` for the REPL surface;
    it threads through to the per-slash streaming paths (``/image``,
    ``/path``, ``/file``) so their renderer goes through ``aappend_text``
    + ``ChatApplication.write_through`` instead of a direct
    ``console.file`` write, honoring the output mutex and approval
    suspend gate. Defaults to ``None`` for non-REPL callers that never
    enter the concurrent loop.
    """

    if cmd == "/help":
        console.print(render_help_table(Surface.CLI_GATEWAY))
        return True

    if parts := _slash_parts(cmd, "/new"):
        title = parts[1].strip() if len(parts) > 1 else None
        session_key = await client.create_session(model=state.model, display_name=title)
        state.session_key = session_key
        state.transcript.clear()
        state.usage.reset()
        try:
            _resolved = await asyncio.wait_for(
                client.resolve_session(session_key), timeout=2.0
            )
            state.model = _resolved.get("model") or state.model
        except Exception:  # noqa: BLE001 — network/timeout; non-fatal
            pass
        label = f" ({title})" if title else ""
        console.print(f"[green]Started new session{label}:[/green] {session_key}")
        return True

    if cmd in {"/status", "/session"}:
        console.print(
            f"[{ACCENT}]session[/] [dim]{state.session_key}[/dim]\n"
            f"[{ACCENT}]model[/] [dim]{state.model or 'default'}[/dim]\n"
            f"[{ACCENT}]permissions[/] [dim]{state.elevated or 'normal'}[/dim]"
        )
        return True

    if parts := _slash_parts(cmd, "/sessions"):
        limit = 10
        if len(parts) > 1:
            try:
                limit = int(parts[1])
            except ValueError:
                console.print("[red]Usage: /sessions [limit][/red]")
                return True
        payload = await client.list_sessions(limit=limit)
        _print_sessions_table(payload.get("sessions", []))
        return True

    if parts := _slash_parts(cmd, "/resume"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /resume <id>[/red]")
            return True
        target = cmd.split(maxsplit=1)[1].strip()
        payload = await client.resolve_session(target)
        state.session_key = payload.get("session_key") or payload.get("key") or target
        state.model = payload.get("model") or state.model
        state.transcript.clear()
        state.usage.reset()
        console.print(f"[green]Resumed session:[/green] {state.session_key}")
        return True

    if parts := _slash_parts(cmd, "/delete"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /delete <id>[/red]")
            return True
        target = cmd.split(maxsplit=1)[1].strip()
        resolved = await client.resolve_session(target)
        session_key = resolved.get("session_key") or resolved.get("key") or target
        payload = await client.delete_sessions([session_key])
        errors = [str(item) for item in payload.get("errors") or []]
        deleted = [str(item) for item in payload.get("deleted") or []]
        if errors:
            console.print(error_panel("\n".join(errors), title="Delete failed"))
        elif deleted:
            console.print(f"[yellow]Deleted session:[/yellow] {deleted[0]}")
        else:
            console.print(error_panel("No session was deleted.", title="Delete failed"))
        return True

    if cmd in {"/clear", "/reset"}:
        await client.reset_session(state.session_key)
        state.transcript.clear()
        state.usage.reset()
        console.print(f"[{ACCENT}]cleared[/] [dim]{state.session_key}[/dim]")
        return True

    if cmd == "/compact":
        payload = await client.compact_session(state.session_key)
        if payload.get("compacted"):
            before = int(payload.get("tokens_before") or 0)
            after = int(payload.get("tokens_after") or 0)
            remaining = int(payload.get("remaining_budget_tokens") or 0)
            source = payload.get("summary_source") or "unknown"
            token_stats = (
                f"{before} -> {after} tokens, {remaining} remaining, {source}"
                if before or after
                else f"summary {payload.get('summary_len', 0)} chars"
            )
            console.print(
                f"[{ACCENT}]compacted[/] "
                f"[dim]{token_stats}[/dim]"
            )
        else:
            console.print(
                f"[{ACCENT}]compact skipped[/] "
                "[dim]context already within budget[/dim]"
            )
        return True

    if parts := _slash_parts(cmd, "/models"):
        if len(parts) > 1:
            console.print("[red]Usage: /models[/red]")
            return True
        models = await client.list_models()
        _print_models_table(models)
        return True

    if parts := _slash_parts(cmd, "/model"):
        if len(parts) == 1:
            console.print(f"[dim]model={state.model or 'default'}[/dim]")
        else:
            new_model = parts[1].strip()
            await client.patch_session(state.session_key, model=new_model)
            state.model = new_model
            console.print(f"[green]model:[/green] {new_model}")
        return True

    if cmd == "/cost":
        console.print(state.usage.render())
        return True

    if cmd == "/usage":
        payload = await client.usage_status()
        console.print(
            "[dim]aggregate usage: "
            f"{payload.get('totalTokens', 0):,} tok · "
            f"${float(payload.get('totalCostUsd', 0.0) or 0.0):.6f}[/dim]"
        )
        return True

    if _slash_parts(cmd, "/tool-compress"):
        await _handle_tool_compress_command(cmd, client=client)
        return True

    if _slash_parts(cmd, "/save"):
        await _save_gateway_transcript_command(cmd, state, client)
        return True

    if parts := _slash_parts(cmd, "/image"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /image <path> [prompt][/red]")
            return True
        try:
            prompt, attachments = _image_prompt_and_attachments(cmd)
        except ValueError as exc:
            console.print(error_panel(str(exc)))
            return True
        result = await _stream_response_gateway(
            client,
            state.session_key,
            prompt,
            elevated_state,
            attachments=attachments,
            chat_app=chat_app,
        )
        state.transcript.add("user", prompt)
        state.transcript.add("assistant", result.text)
        state.usage.apply(result.usage)
        return True

    if parts := _slash_parts(cmd, "/path"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /path <path> [prompt][/red]")
            return True
        if not _gateway_client_is_local(client):
            console.print(error_panel(_PATH_REMOTE_GATEWAY_MESSAGE))
            return True
        try:
            prompt, attachments = _path_prompt_and_attachments(cmd)
        except ValueError as exc:
            console.print(error_panel(str(exc)))
            return True
        result = await _stream_response_gateway(
            client,
            state.session_key,
            prompt,
            elevated_state,
            attachments=attachments,
            chat_app=chat_app,
        )
        state.transcript.add("user", prompt)
        state.transcript.add("assistant", result.text)
        state.usage.apply(result.usage)
        return True

    if parts := _slash_parts(cmd, "/file"):
        if len(parts) == 1 or not parts[1].strip():
            console.print("[red]Usage: /file <path> [prompt][/red]")
            return True

        async def _bridge_upload(path: Path, mime: str, name: str) -> str:
            return await client.upload_file(path, mime, name)

        try:
            prompt, attachments = await _async_file_prompt_and_attachments(
                cmd, upload_callable=_bridge_upload
            )
        except ValueError as exc:
            console.print(error_panel(str(exc)))
            return True
        result = await _stream_response_gateway(
            client,
            state.session_key,
            prompt,
            elevated_state,
            attachments=attachments,
            chat_app=chat_app,
        )
        state.transcript.add("user", prompt)
        state.transcript.add("assistant", result.text)
        state.usage.apply(result.usage)
        return True

    if _slash_parts_any(cmd, "/permissions", "/elevated"):
        await _handle_elevated_command(cmd, elevated_state, client)
        state.elevated = elevated_state.get("mode")
        return True

    if cmd == "/forget" or cmd.startswith("/forget "):
        await _handle_forget_command(cmd, client)
        return True

    if cmd == "/approvals" or cmd.startswith("/approvals "):
        await _handle_approvals_command(cmd, client)
        return True

    return False


async def _handle_tool_compress_command(
    cmd: str,
    *,
    config: object | None = None,
    client: object | None = None,
) -> None:
    parts = cmd.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"
    aliases = {"on": "truncate", "trim": "truncate", "summary": "summarize"}
    mode_arg = aliases.get(arg, arg)
    if len(parts) > 2 or mode_arg not in {"off", "truncate", "summarize", "status"}:
        console.print("[red]Usage: /tool-compress [off|truncate|summarize|status][/red]")
        return

    enabled_path = "agent_token_saving.tool_result_compression_enabled"
    mode_path = "agent_token_saving.tool_result_compression_mode"
    model_path = "agent_token_saving.tool_result_compression_summary_model"
    if client is not None:
        from opensquilla.cli.gateway_client import GatewayClient

        assert isinstance(client, GatewayClient)
        if mode_arg == "status":
            mode = await client.get_config(mode_path)
            enabled = bool(await client.get_config(enabled_path))
            model = await client.get_config(model_path)
            mode = mode if mode in {"off", "truncate", "summarize"} else None
            resolved_mode = str(mode or ("truncate" if enabled else "off"))
        else:
            resolved_mode = mode_arg
            await client.patch_config_safe(
                {
                    mode_path: resolved_mode,
                    enabled_path: resolved_mode != "off",
                }
            )
            model = await client.get_config(model_path) if resolved_mode == "summarize" else None
    else:
        cfg = getattr(config, "agent_token_saving", None)
        if cfg is None:
            console.print("[yellow]Tool result compression config is unavailable.[/yellow]")
            return
        if mode_arg == "status":
            mode = getattr(cfg, "tool_result_compression_mode", None)
            enabled = bool(getattr(cfg, "tool_result_compression_enabled", True))
            model = getattr(cfg, "tool_result_compression_summary_model", None)
            if mode in {"off", "truncate", "summarize"}:
                resolved_mode = str(mode)
            else:
                resolved_mode = "truncate" if enabled else "off"
        else:
            resolved_mode = mode_arg
            setattr(cfg, "tool_result_compression_mode", resolved_mode)
            setattr(cfg, "tool_result_compression_enabled", resolved_mode != "off")
            model = getattr(cfg, "tool_result_compression_summary_model", None)

    model_suffix = f" [dim]model={model}[/dim]" if resolved_mode == "summarize" and model else ""
    console.print(f"[{ACCENT}]tool result compression:[/] {resolved_mode.upper()}{model_suffix}")


def _print_sessions_table(rows: list[dict[str, Any]]) -> None:
    table = Table(title="Sessions", show_header=True, header_style=ACCENT_HEADER)
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Model")
    table.add_column("Messages", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("key") or row.get("session_key") or ""),
            str(row.get("status") or ""),
            str(row.get("model") or ""),
            str(row.get("message_count") or row.get("entry_count") or 0),
        )
    console.print(table)


def _print_models_table(rows: list[dict[str, Any]]) -> None:
    table = Table(title="Models", show_header=True, header_style=ACCENT_HEADER)
    table.add_column("ID")
    table.add_column("Provider")
    table.add_column("Context", justify="right")
    table.add_column("Capabilities")
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("provider") or ""),
            str(row.get("contextWindow") or ""),
            ", ".join(str(v) for v in row.get("capabilities") or []),
        )
    console.print(table)


def _save_transcript_command(cmd: str, state: ChatSessionState) -> None:
    parts = cmd.split(maxsplit=1)
    if len(parts) > 1:
        target = Path(parts[1]).expanduser()
    else:
        suffix = state.session_key.replace(":", "-")
        target = Path(f"opensquilla-chat-{suffix}.md")
    target.write_text(state.transcript.to_markdown(), encoding="utf-8")
    console.print(f"[green]Saved transcript:[/green] {target}")


async def _save_gateway_transcript_command(
    cmd: str, state: ChatSessionState, client: object
) -> None:
    from opensquilla.cli.gateway_client import GatewayClient

    assert isinstance(client, GatewayClient)
    parts = cmd.split(maxsplit=1)
    if len(parts) > 1:
        target = Path(parts[1]).expanduser()
    else:
        suffix = state.session_key.replace(":", "-")
        target = Path(f"opensquilla-chat-{suffix}.md")

    history = await client.session_history(state.session_key, limit=1000)
    messages = history.get("messages") or []
    markdown = messages_to_markdown(messages) if isinstance(messages, list) else ""
    if not markdown.strip():
        markdown = state.transcript.to_markdown()
    target.write_text(markdown, encoding="utf-8")
    console.print(f"[green]Saved transcript:[/green] {target}")


def _image_prompt_from_command(command: str) -> str:
    return _cli_attachments.image_prompt_from_command(command)


def _image_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
    prompt, attachments = _cli_attachments.image_prompt_and_attachments(command)
    if attachments:
        name = attachments[0].get("name") or "image"
        data = attachments[0].get("data") or ""
        console.print(f"[dim]Sending image: {name} ({len(data) // 1024}KB base64)[/dim]")
    return prompt, attachments


def _gateway_client_is_local(client: object) -> bool:
    local_attr = getattr(client, "is_local_gateway", None)
    if callable(local_attr):
        try:
            return bool(local_attr())
        except TypeError:
            return False
    if local_attr is not None:
        return bool(local_attr)

    try:
        from opensquilla.cli.gateway_client import gateway_base_is_local
    except Exception:  # pragma: no cover - defensive import fallback
        return False
    return gateway_base_is_local(getattr(client, "_http_base", None))


def _parse_path_command(command: str) -> tuple[Path, str]:
    return _cli_attachments.parse_path_command(command)


def _path_strategy_hint(path: Path) -> str:
    return _cli_attachments.path_strategy_hint(path)


def _path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, Any]]]:
    return _cli_attachments.path_prompt_and_attachments(command)


def _file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    return _cli_attachments.file_prompt_and_attachments(
        command, upload_callable=upload_callable
    )


async def _async_file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    return await _cli_attachments.async_file_prompt_and_attachments(
        command, upload_callable=upload_callable
    )


async def _forget_server_approvals(client: object | None, target: str | None = None) -> bool:
    """Clear intent cache. Returns True when the right cache actually changed.

    In gateway mode we must hit the server — the chat process's in-memory
    cache is disjoint from the gateway process's. If the RPC fails (e.g.
    older gateway without the ``exec.approval.forget`` handler), clearing
    locally is a no-op for the running agent, so the caller must be told.
    """
    if client is not None:
        from opensquilla.cli.gateway_client import GatewayClient

        assert isinstance(client, GatewayClient)
        try:
            await client.forget_approvals(target)
            return True
        except Exception as exc:
            console.print(
                f"[red]Failed to clear server-side approvals:[/red] {type(exc).__name__}: {exc}"
            )
            console.print(
                "[red]The gateway is likely running older code. "
                "Restart it with[/red] [bold]pkill -f 'opensquilla gateway' "
                "&& opensquilla gateway run[/bold][red] and retry.[/red]"
            )
            return False

    from opensquilla.sandbox.intent_cache import get_intent_cache

    cache = get_intent_cache()
    if target:
        cache.forget(f"rm {target}")
        cache.forget(target)
    else:
        cache.clear()
    return True


async def _handle_approvals_command(cmd: str, client: object | None = None) -> None:
    """Diagnostic view / reset for the approval queue.

    * ``/approvals``        — show the current mode and cached intent entries.
    * ``/approvals reset``  — reset queue mode to ``prompt`` + clear cache.
    """
    parts = cmd.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"

    if client is None:
        from opensquilla.gateway.approval_queue import get_approval_queue
        from opensquilla.sandbox.intent_cache import get_intent_cache

        queue = get_approval_queue()
        cache = get_intent_cache()
        if arg == "reset":
            queue.set_settings(mode="prompt")
            cache.clear()
            console.print(f"[{ACCENT}]Approval mode reset to prompt; cache cleared.[/]")
            return
        entries = [
            f"  [dim]{scope}[/dim] {k}:{t}"
            for (k, t), (_exp, scope) in cache._entries.items()  # noqa: SLF001
        ]
        console.print(f"[{ACCENT}]mode:[/] {queue.get_settings().mode}")
        console.print(f"[{ACCENT}]cached intents ({len(entries)}):[/]")
        for line in entries or ["  [dim](none)[/dim]"]:
            console.print(line)
        return

    from opensquilla.cli.gateway_client import GatewayClient

    assert isinstance(client, GatewayClient)

    if arg == "reset":
        try:
            await client.set_approval_mode("prompt")
            await client.forget_approvals()
            console.print(f"[{ACCENT}]Approval mode reset to prompt; server cache cleared.[/]")
        except Exception as exc:
            console.print(f"[red]Failed to reset approvals:[/red] {type(exc).__name__}: {exc}")
            console.print("[red]Restart the gateway if this is an older build.[/red]")
        return

    try:
        snap = await client.approvals_snapshot()
    except Exception as exc:
        console.print(f"[red]Failed to query approvals:[/red] {type(exc).__name__}: {exc}")
        console.print("[red]Older gateway? Restart it.[/red]")
        return
    console.print(f"[{ACCENT}]mode:[/] {snap.get('mode')}")
    raw_entries = snap.get("intent_cache_entries")
    approval_entries = (
        cast(list[dict[str, Any]], raw_entries) if isinstance(raw_entries, list) else []
    )
    console.print(f"[{ACCENT}]cached intents ({len(approval_entries)}):[/]")
    if not approval_entries:
        console.print("  [dim](none)[/dim]")
    for e in approval_entries:
        console.print(f"  [dim]{e.get('scope')}[/dim] {e.get('kind')}:{e.get('target')}")


async def _handle_forget_command(cmd: str, client: object | None = None) -> None:
    """Clear cached approvals. ``/forget`` wipes all; ``/forget <path>`` wipes one.

    In gateway mode the RPC ``exec.approval.forget`` reaches the server's
    intent cache. In standalone mode the in-process singleton is used.
    """
    parts = cmd.split(maxsplit=1)
    if len(parts) < 2:
        if await _forget_server_approvals(client):
            console.print(
                f"[{ACCENT}]All cached approvals cleared.[/] Future destructive "
                "ops will prompt again."
            )
        return
    target = parts[1].strip()
    if await _forget_server_approvals(client, target):
        console.print(
            f"[{ACCENT}]Cached approval for[/] {target} [{ACCENT}]cleared[/] (if one existed)."
        )


async def _handle_elevated_command(
    cmd: str,
    state: dict[str, str | None],
    client: object | None = None,
) -> None:
    """Interpret ``/permissions`` / ``/elevated`` and mutate state in place.

    Any mode change is treated as an explicit user action (top priority) and
    wipes the intent-cache so earlier ``allow-always`` grants don't leak into
    the new mode. ``status`` is pure-read and leaves state untouched.

    Modes:

    * ``off``     — clear the session override; configured default resumes
    * ``on``      — exec on host, approvals still required
    * ``bypass``  — exec on host, approvals auto-granted, sensitive paths still blocked
    * ``full``    — exec on host, approvals auto-granted, sensitive paths bypassed
    """
    parts = cmd.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"
    if arg == "status":
        current = state["mode"] or "off (session override cleared; configured default applies)"
        console.print(f"[{ACCENT}]permissions:[/] {current}")
        return

    known = {"off": None, "on": "on", "bypass": "bypass", "full": "full"}
    if arg not in known:
        console.print(f"[red]Unknown permissions mode:[/red] {arg}")
        console.print("Usage: /permissions on | off | bypass | full | status")
        return

    state["mode"] = known[arg]
    # Top-priority: explicit mode switch resets the approval trust state.
    cleared = await _forget_server_approvals(client)
    # `off` is the "go back to cautious" transition — also drop any stale
    # queue-level auto-approve setting the operator might have left behind.
    queue_mode_reset_warning = ""
    if arg == "off":
        if client is not None:
            from opensquilla.cli.gateway_client import GatewayClient

            assert isinstance(client, GatewayClient)
            try:
                await client.set_approval_mode("prompt")
            except Exception as exc:
                queue_mode_reset_warning = (
                    f" [bold red]WARNING: queue mode not reset "
                    f"({type(exc).__name__}: {exc}).[/bold red]"
                )
        else:
            from opensquilla.gateway.approval_queue import get_approval_queue

            get_approval_queue().set_settings(mode="prompt")
    revoked_suffix = (
        "Cached approvals revoked."
        if cleared
        else "[bold red]WARNING: cached approvals NOT revoked (see error above).[/bold red]"
    )

    if arg == "off":
        console.print(
            f"[{ACCENT}]permissions: off[/] — exec runs inside the sandbox. "
            f"Queue mode reset to prompt. {revoked_suffix}{queue_mode_reset_warning}"
        )
    elif arg == "on":
        console.print(
            f"[yellow]permissions: on[/yellow] — exec on host, approvals required. {revoked_suffix}"
        )
    elif arg == "bypass":
        console.print(
            f"[red]permissions: bypass[/red] — exec on host, approvals auto-granted. "
            f"Sensitive paths (~/.ssh, /etc, ...) still hard-blocked. {revoked_suffix}"
        )
    else:  # full
        console.print(
            f"[red]permissions: full[/red] — exec on host, approvals skipped, "
            f"sensitive paths bypassed. Trusted operators only. {revoked_suffix}"
        )


def _render_gateway_task_group_status(
    event_name: str,
    event: dict[str, Any],
    renderer: StreamingRenderer,
) -> None:
    status_item = _gateway_task_group_status(event_name, event)
    if status_item is None:
        return
    message, style = status_item
    status = getattr(renderer, "status", None)
    if callable(status):
        status(message, style=style)
    else:
        console.print(f"[{style}]{message}[/]")


def _gateway_task_group_status(
    event_name: str,
    event: dict[str, Any],
) -> tuple[str, str] | None:
    phase = event_name.rsplit(".", 1)[-1]
    style = "dim"
    if phase == "waiting":
        pending = event.get("pending_count")
        suffix = f" ({pending} pending)" if isinstance(pending, int) and pending >= 0 else ""
        message = f"subagents waiting{suffix}"
    elif phase == "synthesizing":
        child_count = event.get("child_count")
        suffix = f" from {child_count} children" if isinstance(child_count, int) else ""
        message = f"subagents complete; synthesizing final answer{suffix}"
    elif phase == "done":
        delivery_status = event.get("delivery_status")
        suffix = f" (delivery: {delivery_status})" if isinstance(delivery_status, str) else ""
        message = f"background synthesis complete{suffix}"
    elif phase == "failed":
        error_message = event.get("error_message")
        suffix = f": {error_message}" if isinstance(error_message, str) and error_message else ""
        message = f"background synthesis failed{suffix}"
        style = "yellow"
    else:
        return None
    return message, style


async def _arender_gateway_task_group_status(
    event_name: str,
    event: dict[str, Any],
    renderer: StreamingRenderer,
) -> None:
    status_item = _gateway_task_group_status(event_name, event)
    if status_item is None:
        return
    message, style = status_item
    await _renderer_status(renderer, message, style=style)


async def _renderer_status(renderer: Any, message: str, *, style: str = "dim") -> None:
    astatus = getattr(renderer, "astatus", None)
    if callable(astatus):
        await astatus(message, style=style)
        return
    status = getattr(renderer, "status", None)
    if callable(status):
        status(message, style=style)
    else:
        console.print(f"[{style}]{message}[/]")


async def _renderer_tool_start(
    renderer: Any,
    name: str,
    args: dict | None,
    tool_use_id: str | None,
) -> None:
    atool_start = getattr(renderer, "atool_start", None)
    if callable(atool_start):
        await atool_start(name, args, tool_use_id)
        return
    renderer.tool_start(name, args, tool_use_id)


async def _renderer_tool_finished(
    renderer: Any,
    tool_use_id: str | None,
    *,
    success: bool,
) -> None:
    atool_finished = getattr(renderer, "atool_finished", None)
    if callable(atool_finished):
        await atool_finished(tool_use_id, success=success)
        return
    renderer.tool_finished(tool_use_id, success=success)


async def _renderer_error(renderer: Any, message: str) -> None:
    aerror = getattr(renderer, "aerror", None)
    if callable(aerror):
        await aerror(message)
        return
    renderer.error(message)


async def _renderer_finalize(
    renderer: Any,
    usage: UsageSummary | None = None,
    *,
    cancelled: bool = False,
) -> None:
    afinalize = getattr(renderer, "afinalize", None)
    if callable(afinalize):
        await afinalize(usage, cancelled=cancelled)
        return
    renderer.finalize(usage, cancelled=cancelled)


async def _renderer_close(renderer: Any) -> None:
    aclose = getattr(renderer, "aclose", None)
    if callable(aclose):
        await aclose()


async def _echo_user_input(chat_app: Any, text: str) -> None:
    payload = user_input_echo_payload(text)
    if not payload:
        return
    write_through = getattr(chat_app, "write_through", None)
    if callable(write_through):
        await write_through(payload)
        return
    console.file.write(payload)
    console.file.flush()


async def _echo_queued_turn_start(chat_app: Any) -> None:
    payload = queued_input_start_payload()
    write_through = getattr(chat_app, "write_through", None)
    if callable(write_through):
        await write_through(payload)
        return
    console.file.write(payload)
    console.file.flush()


def _artifact_event_payload(event: Any) -> dict[str, Any]:
    from opensquilla.artifacts import artifact_payload

    if isinstance(event, dict):
        return artifact_payload(
            {key: value for key, value in event.items() if key not in {"event", "payload"}}
        )

    return artifact_payload(event)


def _artifact_status_line(artifact: dict[str, Any]) -> str:
    name = artifact.get("name") if isinstance(artifact.get("name"), str) else "artifact"
    target = artifact.get("download_url") if isinstance(artifact.get("download_url"), str) else ""
    return f"Generated file: {name} -> {target or artifact.get('id', '')}"


async def _stream_response_gateway(
    client: _GatewayClientLike,
    session_key: str,
    message: str,
    elevated_state: dict[str, str | None] | None = None,
    attachments: list[dict] | None = None,
    *,
    chat_app: Any | None = None,
) -> TurnResult:
    """Stream response from gateway with Rich live display.

    When ``chat_app`` is provided, token writes are routed through the
    output mutex via ``StreamingRenderer.aappend_text`` so stream
    chunks cannot collide with the inline approval ``PromptSession`` that
    owns the screen during the inline-approval suspend window.
    """
    elevated = elevated_state["mode"] if elevated_state else None
    usage: UsageSummary | None = None
    cancelled = False
    artifacts: list[dict[str, Any]] = []
    model_after: str | None = None

    approval_surface = (
        chat_app.surface
        if chat_app is not None and hasattr(chat_app, "surface")
        else Surface.CLI_GATEWAY
    )

    with StreamingRenderer(chat_app=chat_app) as renderer:
        try:
            try:
                async for event in client.send_message(
                    session_key, message, attachments=attachments, elevated=elevated
                ):
                    event_name = event.get("event", "")
                    if event_name == "session.event.text_delta":
                        await renderer.aappend_text(event.get("text", ""))
                    elif event_name == "session.event.tool_use_start":
                        await _renderer_tool_start(
                            renderer,
                            event.get("tool_name") or event.get("toolName") or "tool",
                            event.get("input") or event.get("arguments"),
                            event.get("tool_use_id") or event.get("toolUseId"),
                        )
                    elif event_name == "session.event.tool_result":
                        await _maybe_handle_approval(
                            event.get("result"),
                            renderer,
                            client.resolve_approval,
                            elevated_state=elevated_state,
                            surface=approval_surface,
                        )
                        if not _is_approval_or_blocked_result(event.get("result")):
                            await _renderer_tool_finished(
                                renderer,
                                event.get("tool_use_id") or event.get("toolUseId"),
                                success=_tool_result_success_from_status(
                                    event.get("execution_status")
                                    or event.get("executionStatus"),
                                    legacy_is_error=bool(
                                        event.get("is_error") or event.get("isError")
                                    ),
                                ),
                            )
                    elif event_name == "session.event.artifact":
                        artifact = _artifact_event_payload(event)
                        artifacts.append(artifact)
                        await _renderer_status(renderer, _artifact_status_line(artifact))
                    elif event_name.startswith("session.event.task_group."):
                        await _arender_gateway_task_group_status(event_name, event, renderer)
                    elif event_name == "session.event.error":
                        message_text = event.get("message", "unknown")
                        await _renderer_error(renderer, message_text)
                        return TurnResult(
                            text=renderer.buffer,
                            usage=usage,
                            error=message_text,
                            artifacts=artifacts,
                        )
                    elif event_name == "session.event.done":
                        usage = UsageSummary.from_gateway_payload(event)
                        cancelled = event.get("reason") == "aborted"
                        model_after = event.get("routed_model") or event.get("model") or None
            except (KeyboardInterrupt, asyncio.CancelledError):
                _clear_current_cancel()
                await client.abort_session(session_key)
                cancelled = True
            await _renderer_finalize(renderer, usage, cancelled=cancelled)
        finally:
            await _renderer_close(renderer)
    return TurnResult(
        text=renderer.buffer,
        usage=usage,
        cancelled=cancelled,
        artifacts=artifacts,
        model_after=model_after,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _local_approval_resolver() -> Callable[..., Awaitable[None]]:
    """Return a resolver that talks directly to the in-process approval queue.

    Used in --standalone mode where there is no gateway RPC to call.
    """

    async def _resolve(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        from opensquilla.gateway.approval_queue import get_approval_queue

        get_approval_queue().resolve(approval_id, approved, allow_always=allow_always)

    return _resolve


async def _stream_response_turnrunner(
    turn_runner: object,
    session_key: str,
    tool_ctx: object,
    message: str,
    model: str | None = None,
    svc: object = None,
    timeout: float | None = None,
    *,
    chat_app: Any | None = None,
) -> TurnResult:
    """Stream TurnRunner response with Rich live display (standalone mode).

    When ``chat_app`` is provided, token writes are routed through the
    output mutex via ``StreamingRenderer.aappend_text`` so stream
    chunks cannot collide with the inline approval ``PromptSession`` that
    owns the screen during the inline-approval suspend window.
    """
    from opensquilla.engine.runtime import TurnRunner
    from opensquilla.engine.types import (
        ArtifactEvent,
        DoneEvent,
        ErrorEvent,
        RunHeartbeatEvent,
        TextDeltaEvent,
        ToolResultEvent,
        ToolUseStartEvent,
        WarningEvent,
    )
    from opensquilla.tools.types import ToolContext

    assert isinstance(turn_runner, TurnRunner)
    assert isinstance(tool_ctx, ToolContext)

    # Persist user message — TurnRunner only persists assistant responses
    session_manager = getattr(svc, "session_manager", None) if svc is not None else None
    if session_manager is not None:
        _persisted = await session_manager.append_message(
            session_key, role="user", content=message
        )
        if _persisted is not None and isinstance(_persisted.content, str):
            message = _persisted.content

    resolver = _local_approval_resolver()
    usage: UsageSummary | None = None
    cancelled = False
    artifacts: list[dict[str, Any]] = []
    model_after: str | None = None

    approval_surface = (
        chat_app.surface
        if chat_app is not None and hasattr(chat_app, "surface")
        else Surface.CLI_STANDALONE
    )

    with StreamingRenderer(chat_app=chat_app) as renderer:
        try:
            try:
                stream = turn_runner.run(
                    message, session_key, tool_context=tool_ctx, model=model, timeout=timeout
                )
                async for event in _wrap_cli_turn_stream(stream, svc):
                    if isinstance(event, TextDeltaEvent):
                        await renderer.aappend_text(event.text)
                    elif isinstance(event, RunHeartbeatEvent):
                        renderer.pulse()
                    elif isinstance(event, ToolUseStartEvent):
                        await _renderer_tool_start(
                            renderer,
                            event.tool_name,
                            None,
                            event.tool_use_id,
                        )
                    elif isinstance(event, ToolResultEvent):
                        await _maybe_handle_approval(
                            event.result,
                            renderer,
                            resolver,
                            surface=approval_surface,
                        )
                        if not _is_approval_or_blocked_result(event.result):
                            await _renderer_tool_finished(
                                renderer,
                                event.tool_use_id,
                                success=_tool_result_success_from_status(
                                    event.execution_status,
                                    legacy_is_error=event.is_error,
                                ),
                            )
                    elif isinstance(event, ArtifactEvent):
                        artifact = _artifact_event_payload(event)
                        artifacts.append(artifact)
                        await _renderer_status(renderer, _artifact_status_line(artifact))
                    elif isinstance(event, WarningEvent):
                        await _renderer_status(renderer, event.message, style="yellow")
                    elif isinstance(event, ErrorEvent):
                        message_text = _turn_stream_error_message(event)
                        await _renderer_error(renderer, message_text)
                        return TurnResult(
                            text=renderer.buffer,
                            usage=usage,
                            error=message_text,
                            artifacts=artifacts,
                        )
                    elif isinstance(event, DoneEvent):
                        usage = UsageSummary.from_done_event(event)
                        model_after = usage.model or None
            except (KeyboardInterrupt, asyncio.CancelledError):
                _clear_current_cancel()
                cancelled = True
            except TimeoutError as exc:
                message_text = _timeout_exception_message(exc)
                await _renderer_error(renderer, message_text)
                return TurnResult(text=renderer.buffer, error=message_text)
            await _renderer_finalize(renderer, usage, cancelled=cancelled)
        finally:
            await _renderer_close(renderer)
    return TurnResult(
        text=renderer.buffer,
        usage=usage,
        cancelled=cancelled,
        artifacts=artifacts,
        model_after=model_after,
    )


async def _handle_image_command_turnrunner(
    turn_runner: object,
    session_key: str,
    tool_ctx: object,
    command: str,
    model: str | None = None,
    svc: object = None,
    timeout: float | None = None,
    *,
    chat_app: Any | None = None,
) -> TurnResult:
    """Handle /image <path> [prompt] — send image via TurnRunner attachments.

    ``chat_app`` is the active ``ChatApplication`` for the REPL surface;
    when provided, token streaming routes through ``aappend_text`` +
    ``ChatApplication.write_through`` so the output mutex and
    approval suspend gate apply to /image output the same way they
    apply to regular turn output. Defaults to ``None`` for non-REPL
    callers.
    """
    from opensquilla.engine.runtime import TurnRunner
    from opensquilla.engine.types import (
        DoneEvent,
        ErrorEvent,
        RunHeartbeatEvent,
        TextDeltaEvent,
        ToolUseStartEvent,
    )
    from opensquilla.tools.types import ToolContext

    assert isinstance(turn_runner, TurnRunner)
    assert isinstance(tool_ctx, ToolContext)

    try:
        prompt, attachments = _image_prompt_and_attachments(command)
    except ValueError as exc:
        console.print(error_panel(str(exc)))
        return TurnResult(error=str(exc))

    # Persist user message before running turn
    session_manager = getattr(svc, "session_manager", None) if svc is not None else None
    if session_manager is not None:
        _persisted = await session_manager.append_message(
            session_key, role="user", content=prompt
        )
        if _persisted is not None and isinstance(_persisted.content, str):
            prompt = _persisted.content

    usage: UsageSummary | None = None
    with StreamingRenderer(chat_app=chat_app) as renderer:
        try:
            try:
                stream = turn_runner.run(
                    prompt,
                    session_key,
                    tool_context=tool_ctx,
                    model=model,
                    attachments=attachments,
                    timeout=timeout,
                )
                async for event in _wrap_cli_turn_stream(stream, svc):
                    if isinstance(event, TextDeltaEvent):
                        await renderer.aappend_text(event.text)
                    elif isinstance(event, RunHeartbeatEvent):
                        renderer.pulse()
                    elif isinstance(event, ToolUseStartEvent):
                        await _renderer_tool_start(
                            renderer,
                            event.tool_name,
                            None,
                            event.tool_use_id,
                        )
                    elif isinstance(event, ErrorEvent):
                        message_text = _turn_stream_error_message(event)
                        await _renderer_error(renderer, message_text)
                        return TurnResult(text=renderer.buffer, usage=usage, error=message_text)
                    elif isinstance(event, DoneEvent):
                        usage = UsageSummary.from_done_event(event)
            except TimeoutError as exc:
                message_text = _timeout_exception_message(exc)
                await _renderer_error(renderer, message_text)
                return TurnResult(text=renderer.buffer, error=message_text)
            await _renderer_finalize(renderer, usage)
        finally:
            await _renderer_close(renderer)
    return TurnResult(text=renderer.buffer, usage=usage)
