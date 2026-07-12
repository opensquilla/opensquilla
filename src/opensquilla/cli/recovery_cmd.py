"""Offline, machine-readable Desktop profile recovery commands."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import typer

from opensquilla.recovery import (
    RecoveryError,
    RecoveryReport,
    choose_workspace,
    inspect_profile,
    reconcile_profile,
)

recovery_app = typer.Typer(
    help="Inspect and repair Desktop profiles without starting the runtime.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _emit(report: RecoveryReport, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
        return
    typer.echo(f"{report.outcome}: {report.stable_code}")
    typer.echo(f"home: {report.primary_home}")
    typer.echo(f"workspace: {report.effective_workspace or '-'}")


def _desktop_profile_kind(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"desktop-primary", "desktop-recovery"}:
        raise typer.BadParameter("use desktop-primary or desktop-recovery")
    return normalized


def _failure_report(
    home: Path,
    error: RecoveryError,
    *,
    profile_kind: str | None = None,
) -> RecoveryReport:
    try:
        base = inspect_profile(home, profile_kind=profile_kind)
    except Exception:
        # Inspection is intentionally resilient, but a damaged/unreadable home
        # can still fail below pathlib itself. Keep stdout protocol-valid.
        from opensquilla.recovery.models import RecoveryReport as Report

        return Report(
            outcome="recovery_required",
            stable_code=error.stable_code,
            primary_home=home.expanduser().absolute(),
            effective_workspace=None,
            candidates=(),
            allowed_actions=("copy-diagnostics",),
            transaction_id="",
            revision=0,
        )
    return replace(base, outcome="recovery_required", stable_code=error.stable_code)


def _run(
    operation: Callable[[], RecoveryReport],
    *,
    home: Path,
    json_output: bool,
    profile_kind: str | None = None,
) -> None:
    try:
        report = operation()
    except RecoveryError as exc:
        _emit(
            _failure_report(home, exc, profile_kind=profile_kind),
            json_output=json_output,
        )
        if not json_output:
            typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None
    _emit(report, json_output=json_output)


@recovery_app.command("inspect")
def recovery_inspect(
    home: Path = typer.Option(..., "--home", help="Desktop profile root H."),
    profile_kind: str = typer.Option(
        "desktop-primary",
        "--profile-kind",
        help="desktop-primary (default) or desktop-recovery.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the fixed JSON protocol."),
) -> None:
    """Read profile safety state without creating or modifying any path."""
    kind = _desktop_profile_kind(profile_kind)
    _run(
        lambda: inspect_profile(home, profile_kind=kind),
        home=home,
        json_output=json_output,
        profile_kind=kind,
    )


@recovery_app.command("reconcile")
def recovery_reconcile(
    home: Path = typer.Option(..., "--home", help="Desktop profile root H."),
    profile_kind: str = typer.Option(
        "desktop-primary",
        "--profile-kind",
        help="desktop-primary (default) or desktop-recovery.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the fixed JSON protocol."),
) -> None:
    """Apply only a proven no-conflict legacy layout repair."""
    kind = _desktop_profile_kind(profile_kind)
    _run(
        lambda: reconcile_profile(home, profile_kind=kind),
        home=home,
        json_output=json_output,
        profile_kind=kind,
    )


@recovery_app.command("choose-workspace")
def recovery_choose_workspace(
    home: Path = typer.Option(..., "--home", help="Desktop profile root H."),
    profile_kind: str = typer.Option(
        "desktop-primary",
        "--profile-kind",
        help="desktop-primary (default) or desktop-recovery.",
    ),
    transaction_id: str = typer.Option(..., "--transaction-id", help="Inspection transaction id."),
    expected_revision: int = typer.Option(
        ...,
        "--expected-revision",
        min=0,
        help="Inspection revision used for compare-and-swap.",
    ),
    workspace: Path = typer.Option(..., "--workspace", help="User-confirmed workspace path."),
    json_output: bool = typer.Option(False, "--json", help="Emit the fixed JSON protocol."),
) -> None:
    """Persist a user-confirmed workspace with transaction and config CAS."""
    kind = _desktop_profile_kind(profile_kind)
    _run(
        lambda: choose_workspace(
            home,
            transaction_id=transaction_id,
            expected_revision=expected_revision,
            workspace=workspace,
            profile_kind=kind,
        ),
        home=home,
        json_output=json_output,
        profile_kind=kind,
    )


__all__ = ["recovery_app"]
