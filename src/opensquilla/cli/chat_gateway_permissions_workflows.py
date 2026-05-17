"""Gateway permissions slash-command workflows for interactive chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import console

ForgetServerApprovals = Callable[[object | None, str | None], Awaitable[bool]]
SetLocalQueuePrompt = Callable[[], None]


class ApprovalModeClient(Protocol):
    async def set_approval_mode(self, mode: str) -> object: ...


class PermissionsCommand(Protocol):
    def __call__(
        self,
        command: str,
        mode_state: dict[str, str | None],
        *,
        client: object | None = None,
        forget_server_approvals: ForgetServerApprovals,
    ) -> Awaitable[None]: ...


def _set_local_queue_prompt() -> None:
    from opensquilla.application.approval_queue import get_approval_queue

    get_approval_queue().set_settings(mode="prompt")


async def handle_permissions_command(
    command: str,
    mode_state: dict[str, str | None],
    *,
    client: object | None = None,
    forget_server_approvals: ForgetServerApprovals,
    set_local_queue_prompt: SetLocalQueuePrompt = _set_local_queue_prompt,
) -> None:
    """Interpret /permissions and /elevated mode changes."""

    parts = command.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"
    if arg == "status":
        current = mode_state["mode"] or "off (sandboxed)"
        console.print(f"[cyan]permissions:[/cyan] {current}")
        return

    known = {"off": None, "on": "on", "bypass": "bypass", "full": "full"}
    if arg not in known:
        console.print(f"[red]Unknown permissions mode:[/red] {arg}")
        console.print("Usage: /permissions on | off | bypass | full | status")
        return

    mode_state["mode"] = known[arg]
    cleared = await forget_server_approvals(client, None)
    queue_mode_reset_warning = ""
    if arg == "off":
        if client is not None:
            try:
                await cast(ApprovalModeClient, client).set_approval_mode("prompt")
            except Exception as exc:
                queue_mode_reset_warning = (
                    f" [bold red]WARNING: queue mode not reset "
                    f"({type(exc).__name__}: {exc}).[/bold red]"
                )
        else:
            set_local_queue_prompt()

    revoked_suffix = (
        "Cached approvals revoked."
        if cleared
        else "[bold red]WARNING: cached approvals NOT revoked (see error above).[/bold red]"
    )

    if arg == "off":
        console.print(
            f"[cyan]permissions: off[/cyan] — exec runs inside the sandbox. "
            f"Queue mode reset to prompt. {revoked_suffix}{queue_mode_reset_warning}"
        )
    elif arg == "on":
        console.print(
            f"[yellow]permissions: on[/yellow] — exec on host, approvals required. "
            f"{revoked_suffix}"
        )
    elif arg == "bypass":
        console.print(
            f"[red]permissions: bypass[/red] — exec on host, approvals auto-granted. "
            f"Sensitive paths (~/.ssh, /etc, ...) still hard-blocked. {revoked_suffix}"
        )
    else:
        console.print(
            f"[red]permissions: full[/red] — exec on host, approvals skipped, "
            f"sensitive paths bypassed. Trusted operators only. {revoked_suffix}"
        )


async def handle_gateway_permissions_command(
    command: str,
    state: ChatSessionState,
    mode_state: dict[str, str | None],
    *,
    client: object,
    forget_server_approvals: ForgetServerApprovals,
    permissions_command: PermissionsCommand = handle_permissions_command,
) -> bool:
    """Handle gateway /permissions and /elevated orchestration."""

    await permissions_command(
        command,
        mode_state,
        client=client,
        forget_server_approvals=forget_server_approvals,
    )
    state.elevated = mode_state.get("mode")
    return True
