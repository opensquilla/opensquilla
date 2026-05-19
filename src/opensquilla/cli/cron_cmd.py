"""Cron scheduler CLI commands backed by OpenSquilla gateway RPCs."""

from __future__ import annotations

import typer

from opensquilla.cli.cron_workflows import (
    add_cron_job_for_cli,
    list_cron_jobs_for_cli,
    list_cron_runs_for_cli,
    remove_cron_job_for_cli,
    run_cron_job_for_cli,
    show_cron_job_for_cli,
    update_cron_job_for_cli,
)

cron_app = typer.Typer(help="Inspect and manage scheduled OpenSquilla runs.")


@cron_app.command("list")
def cron_list(
    agent: str | None = typer.Option(None, "--agent", help="Filter by agent id"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List scheduled cron jobs."""

    list_cron_jobs_for_cli(agent, json_output=json_output)


@cron_app.command("status")
def cron_status(
    job_id: str = typer.Argument(..., help="Cron job id"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show one cron job."""

    show_cron_job_for_cli(job_id, json_output=json_output)


@cron_app.command("add")
def cron_add(
    expression: str = typer.Option(..., "--expression", help="Cron expression"),
    text: str = typer.Option(..., "--text", help="Prompt text to run"),
    name: str | None = typer.Option(None, "--name", help="Display name"),
    agent: str | None = typer.Option(None, "--agent", help="Agent id"),
    session_target: str = typer.Option(
        "isolated",
        "--session-target",
        help="Target session mode: isolated, main, current, or session",
    ),
    timeout: float | None = typer.Option(None, "--timeout", help="Run timeout in seconds"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add a scheduled cron job."""

    add_cron_job_for_cli(
        expression=expression,
        text=text,
        name=name,
        agent=agent,
        session_target=session_target,
        timeout=timeout,
        json_output=json_output,
    )


@cron_app.command("update")
def cron_update(
    job_id: str = typer.Argument(..., help="Cron job id"),
    expression: str | None = typer.Option(None, "--expression", help="Cron expression"),
    text: str | None = typer.Option(None, "--text", help="Prompt text to run"),
    name: str | None = typer.Option(None, "--name", help="Display name"),
    enabled: bool | None = typer.Option(None, "--enabled/--disabled", help="Enable/disable job"),
    timeout: float | None = typer.Option(None, "--timeout", help="Run timeout in seconds"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Update a scheduled cron job."""

    update_cron_job_for_cli(
        job_id,
        expression=expression,
        text=text,
        name=name,
        enabled=enabled,
        timeout=timeout,
        json_output=json_output,
    )


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Cron job id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove a scheduled cron job."""

    remove_cron_job_for_cli(job_id, yes=yes, json_output=json_output)


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Cron job id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Run a scheduled cron job now."""

    run_cron_job_for_cli(job_id, yes=yes, json_output=json_output)


@cron_app.command("runs")
def cron_runs(
    job_id: str = typer.Argument(..., help="Cron job id"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum rows"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List recent runs for a cron job."""

    list_cron_runs_for_cli(job_id, limit=limit, json_output=json_output)
