"""Offline, machine-readable Desktop profile recovery commands."""

from __future__ import annotations

import json
import sys
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
from opensquilla.recovery.settings_transaction import (
    MAX_SETTINGS_INPUT_BYTES,
    apply_desktop_settings,
    recover_desktop_settings,
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


def _settings_payload_from_stdin() -> object:
    raw = sys.stdin.buffer.read(MAX_SETTINGS_INPUT_BYTES + 1)
    if len(raw) > MAX_SETTINGS_INPUT_BYTES:
        raise RecoveryError(
            "Desktop settings input is too large",
            stable_code="settings_input_too_large",
        )
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError(
            "Desktop settings input is invalid",
            stable_code="settings_input_invalid",
        ) from exc


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


@recovery_app.command("apply-settings")
def recovery_apply_settings(
    home: Path = typer.Option(..., "--home", help="Desktop profile root H."),
    transaction_id: str = typer.Option(..., "--transaction-id", help="Inspection transaction id."),
    expected_revision: int = typer.Option(
        ...,
        "--expected-revision",
        min=0,
        help="Inspection revision used for compare-and-swap.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the fixed JSON protocol."),
) -> None:
    """Read secret-bearing candidates from stdin and publish them as one pair."""

    _run(
        lambda: apply_desktop_settings(
            home,
            transaction_id=transaction_id,
            expected_revision=expected_revision,
            payload=_settings_payload_from_stdin(),
        ),
        home=home,
        json_output=json_output,
        profile_kind="desktop-primary",
    )


@recovery_app.command("recover-settings")
def recovery_recover_settings(
    home: Path = typer.Option(..., "--home", help="Desktop profile root H."),
    json_output: bool = typer.Option(False, "--json", help="Emit the fixed JSON protocol."),
) -> None:
    """Finish an identity-proven interrupted Desktop settings transaction."""

    _run(
        lambda: recover_desktop_settings(home),
        home=home,
        json_output=json_output,
        profile_kind="desktop-primary",
    )


@recovery_app.command("restore-profile")
def recovery_restore_profile(
    backup: Path = typer.Option(..., "--backup", help="Exact recorded profile backup path."),
    json_output: bool = typer.Option(False, "--json", help="Emit the fixed JSON protocol."),
) -> None:
    """Restore a recorded sibling backup after backing up the current target."""
    from opensquilla.recovery.restore import (
        recorded_backup_target,
        restore_profile,
    )

    backup_path = backup.expanduser().absolute()
    try:
        target = recorded_backup_target(backup_path)
    except RecoveryError:
        # Keep failure responses protocol-valid without guessing a successful
        # target. ``restore_profile`` repeats the exact history validation and
        # supplies the authoritative stable code through ``_run``.
        target = backup_path.parent / "opensquilla"
    _run(
        lambda: restore_profile(backup_path),
        home=target,
        json_output=json_output,
        profile_kind="desktop-primary",
    )


@recovery_app.command("recover-transaction")
def recovery_recover_transaction(
    home: Path = typer.Option(..., "--home", help="Desktop primary profile root H."),
    transaction_id: str = typer.Option(..., "--transaction-id", help="Inspection transaction id."),
    expected_revision: int = typer.Option(
        ...,
        "--expected-revision",
        min=0,
        help="Inspection revision used for compare-and-swap.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the fixed JSON protocol."),
) -> None:
    """Safely rollback or finalize one typed interrupted profile transaction."""

    from opensquilla.migration.opensquilla_home import recover_interrupted_profile_import
    from opensquilla.recovery.transaction import recover_profile_transaction

    _run(
        lambda: recover_profile_transaction(
            home,
            transaction_id=transaction_id,
            expected_revision=expected_revision,
            import_recoverer=recover_interrupted_profile_import,
        ),
        home=home,
        json_output=json_output,
        profile_kind="desktop-primary",
    )


__all__ = ["recovery_app"]
