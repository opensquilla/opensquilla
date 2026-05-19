"""CLI workflows for cron scheduler commands."""

from __future__ import annotations

from typing import Any, cast

import typer

from opensquilla.cli.cron_presenters import (
    emit_cron_jobs,
    emit_cron_runs,
    emit_cron_success,
)
from opensquilla.cli.gateway_rpc import confirm_or_exit, run_gateway_sync

_SESSION_TARGETS = {"isolated", "main", "current", "session"}


def list_cron_jobs_for_cli(agent: str | None, *, json_output: bool) -> None:
    """Load and emit scheduled cron jobs."""

    params: dict[str, Any] = {}
    if agent:
        params["agentId"] = agent

    async def _run(client: Any) -> Any:
        return await client.call("cron.list", params)

    payload = run_gateway_sync(_run, json_output=json_output)
    emit_cron_jobs(payload, json_output=json_output)


def show_cron_job_for_cli(job_id: str, *, json_output: bool) -> None:
    """Load and emit one cron job."""

    payload = _call_cron_rpc(
        "cron.status",
        {"id": job_id},
        json_output=json_output,
    )
    emit_cron_success(payload, json_output=json_output, title=f"Cron job {job_id}")


def add_cron_job_for_cli(
    *,
    expression: str,
    text: str,
    name: str | None,
    agent: str | None,
    session_target: str,
    timeout: float | None,
    json_output: bool,
) -> None:
    """Add and emit a scheduled cron job."""

    params: dict[str, Any] = {
        "expression": expression,
        "text": text,
        "sessionTarget": _validate_session_target(session_target),
    }
    if name:
        params["name"] = name
    if agent:
        params["agentId"] = agent
    if timeout is not None:
        params["timeout"] = timeout

    payload = _call_cron_rpc("cron.add", params, json_output=json_output)
    emit_cron_success(payload, json_output=json_output, title="Cron job added")


def update_cron_job_for_cli(
    job_id: str,
    *,
    expression: str | None,
    text: str | None,
    name: str | None,
    enabled: bool | None,
    timeout: float | None,
    json_output: bool,
) -> None:
    """Update and emit a scheduled cron job."""

    params: dict[str, Any] = {"id": job_id}
    if expression is not None:
        params["expression"] = expression
    if text is not None:
        params["text"] = text
    if name is not None:
        params["name"] = name
    if enabled is not None:
        params["enabled"] = enabled
    if timeout is not None:
        params["timeout"] = timeout
    if len(params) == 1:
        raise typer.BadParameter("provide at least one field to update")

    payload = _call_cron_rpc("cron.update", params, json_output=json_output)
    emit_cron_success(payload, json_output=json_output, title="Cron job updated")


def remove_cron_job_for_cli(job_id: str, *, yes: bool, json_output: bool) -> None:
    """Remove and emit a scheduled cron job."""

    confirm_or_exit(f"Remove cron job {job_id!r}?", yes=yes, json_output=json_output)

    async def _run(client: Any) -> dict[str, Any]:
        await client.call("cron.remove", {"id": job_id})
        return {"id": job_id, "removed": True}

    payload = run_gateway_sync(_run, json_output=json_output)
    emit_cron_success(payload, json_output=json_output, title="Cron job removed")


def run_cron_job_for_cli(job_id: str, *, yes: bool, json_output: bool) -> None:
    """Run and emit a scheduled cron job."""

    confirm_or_exit(
        f"Run cron job {job_id!r} now? This may post into a live session or channel.",
        yes=yes,
        json_output=json_output,
    )
    payload = _call_cron_rpc("cron.run", {"id": job_id}, json_output=json_output)
    emit_cron_success(payload, json_output=json_output, title="Cron run result")


def list_cron_runs_for_cli(job_id: str, *, limit: int, json_output: bool) -> None:
    """Load and emit recent runs for a cron job."""

    payload = _call_cron_rpc(
        "cron.runs",
        {"id": job_id, "limit": limit},
        json_output=json_output,
    )
    emit_cron_runs(payload, json_output=json_output)


def _validate_session_target(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in _SESSION_TARGETS:
        raise typer.BadParameter(
            "--session-target must be one of isolated, main, current, session"
        )
    return normalized


def _call_cron_rpc(method: str, params: dict[str, Any], *, json_output: bool) -> Any:
    async def _run(client: Any) -> Any:
        return await client.call(method, params)

    return cast(Any, run_gateway_sync(_run, json_output=json_output))
