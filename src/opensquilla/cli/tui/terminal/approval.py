"""Approval prompt handling for TUI and chat turns."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from opensquilla.cli.tui.terminal.prompt import prompt_approval
from opensquilla.cli.ui import console, notice_panel
from opensquilla.engine.commands import Surface


def _approval_choices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sources = []
    params = payload.get("params")
    if isinstance(params, dict):
        raw_sources.append(params)
    raw_sources.append(payload)

    for source in raw_sources:
        raw_choices = source.get("choices")
        if not isinstance(raw_choices, list):
            continue
        choices: list[dict[str, Any]] = []
        for item in raw_choices:
            if not isinstance(item, dict):
                continue
            choice_id = str(item.get("id") or "").strip()
            if choice_id:
                choices.append(dict(item))
        if choices:
            return choices
    return []


def _choice_label(choice: dict[str, Any]) -> str:
    label = str(choice.get("label") or choice.get("id") or "Choose").strip()
    description = str(choice.get("description") or "").strip()
    if description:
        return f"{label} - {description}"
    return label


def _select_approval_choice(
    choices: list[dict[str, Any]],
    answer: str,
) -> dict[str, Any] | None:
    normalized = answer.strip().lower()
    if not normalized:
        return choices[0]
    if normalized.isdigit():
        index = int(normalized) - 1
        if 0 <= index < len(choices):
            return choices[index]
    for choice in choices:
        choice_id = str(choice.get("id") or "").strip().lower()
        label = str(choice.get("label") or "").strip().lower()
        if normalized in {choice_id, label}:
            return choice
    if normalized in {"d", "deny", "n", "no"}:
        for choice in choices:
            if str(choice.get("id") or "").strip().lower() == "deny":
                return choice
    if normalized in {"o", "once", "y", "yes"}:
        for choice in choices:
            if bool(choice.get("approved", True)):
                return choice
    return None


async def maybe_handle_approval(
    result: Any,
    live: Any,
    resolver: Callable[..., Awaitable[Any]],
    elevated_state: dict[str, str | None] | None = None,
    *,
    surface: Surface = Surface.CLI_GATEWAY,
) -> None:
    """Prompt for approval or render a blocking notice for a tool result."""
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
    choices = _approval_choices(payload)

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
        if choices:
            for index, choice in enumerate(choices, start=1):
                console.print(f"[dim]  [bold]{index}[/bold]  {_choice_label(choice)}[/dim]")
            answer = await prompt_approval(
                f"Decision [1-{len(choices)}]: ",
                surface=surface,
            )
            selected = _select_approval_choice(choices, answer)
            if selected is None:
                console.print("[red]Invalid approval choice[/red]")
                return
            approved = bool(selected.get("approved", True))
            choice_id = str(selected.get("id") or "").strip()
            label = str(selected.get("label") or choice_id or "Selected")
            try:
                await resolver(
                    approval_id,
                    approved,
                    allow_always=False,
                    choice=choice_id,
                )
                color = "green" if approved else "red"
                console.print(f"[{color}]{label}[/{color}]")
            except Exception as exc:  # pragma: no cover - RPC/queue transport errors
                console.print(f"[red]Failed to resolve approval:[/red] {exc}")
            return

        console.print(
            "[dim]  [bold]o[/bold]nce    allow this call only[/dim]\n"
            "[dim]  [bold]a[/bold]lways  allow this intent for the session[/dim]\n"
            "[dim]  [bold]b[/bold]ypass  approve + skip future approvals "
            "(sensitive paths still blocked)[/dim]\n"
            "[dim]  [bold]d[/bold]eny    reject[/dim]"
        )
        answer = await prompt_approval("Decision [o/a/b/d]: ", surface=surface)

        flip_to_bypass = False
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
                    " — session now uses the legacy [red]bypass[/red] alias "
                    "for Trusted-Sandbox. Use /elevated off to revert."
                )
            elif allow_always:
                suffix = " — future similar intents auto-approve."
            else:
                suffix = ""
            console.print(f"[{color}]{label}[/{color}]{suffix}")
        except Exception as exc:  # pragma: no cover - RPC/queue transport errors
            console.print(f"[red]Failed to resolve approval:[/red] {exc}")
    finally:
        live.start()
